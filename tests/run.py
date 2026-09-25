#!/usr/bin/env python3
"""luce-png's gate: the module's test blocks, then the drivers in native and C modes:

- every fixture decodes through the Raster API to exactly the samples of the 0.1
  decoder built the same way (tests/fixtures/golden.txt);
- decode_rgba16, decode_rgba8 and decode_rows agree with those samples, on one
  thread and on several, and (with Pillow) with libpng for 8-bit files;
- the encoder is lossless in every format, gives the same bytes on one thread, on
  all and streamed, at every level and filter, in one band or many; its files
  decode the same here in parallel and sequentially and (with Pillow) in libpng;
- truncated and corrupted files fail cleanly, never crash or hang.
"""
import hashlib, os, random, struct, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT.parent / "luce-base/build/luce-base").resolve()
MODES = [["--native"], ["--backend=c"]]
env = dict(os.environ, LUCE_BASE=str(BASE), LUCE_STD=str((ROOT.parent / "luce-base/src/std").resolve()))
FIXTURES = sorted((ROOT / "tests/fixtures").glob("*.png"))
GOLDEN = {}
for line in (ROOT / "tests/fixtures/golden.txt").read_text().splitlines():
    if line and not line.startswith("#"):
        native, c, name = line.split("  ")
        GOLDEN[name] = {"--native": native, "--backend=c": c}

try:
    from PIL import Image
except ImportError:
    Image = None


def run(command, **options):
    return subprocess.run([str(x) for x in command], env=env, cwd=ROOT, timeout=300, **options)


def fail(message):
    raise SystemExit(f"FAIL {message}")


def header(path):
    data = Path(path).read_bytes()
    width, height, bits, color = struct.unpack(">IIBB", data[16:26])
    return width, height, bits, color


def read_raw(path):
    data = Path(path).read_bytes()
    width, height, size = struct.unpack_from("<III", data)
    return width, height, size, data[12:]


def samples16(data):
    return list(struct.unpack(f"<{len(data) // 2}H", data))


def expected_rgba16(dump, bits):
    """RGBA16 from the Raster samples: 8-bit and low depths scale by 257."""
    width, height, channels, data = read_raw(dump)
    values = samples16(data)
    scale = 1 if bits == 16 else 257
    out = []
    for p in range(width * height):
        v = [x * scale for x in values[p * channels:(p + 1) * channels]]
        if channels == 1:
            out += [v[0], v[0], v[0], 65535]
        elif channels == 2:
            out += [v[0], v[0], v[0], v[1]]
        elif channels == 3:
            out += v + [65535]
        else:
            out += v
    return out


def check_decoding(tmp, flags, dump, tool):
    raw, out = tmp / "raw", tmp / "out"
    compared = 0
    for fixture in FIXTURES:
        name = fixture.name
        if run([dump, fixture, raw]).returncode != 0:
            fail(f"{name}: the Raster decode failed")
        if hashlib.sha256(raw.read_bytes()).hexdigest() != GOLDEN[name][flags[0]]:
            fail(f"{name}: Raster samples differ from the 0.1 decoder")
        width, height, bits, color = header(fixture)
        deep = expected_rgba16(raw, bits)
        shallow = bytes((v * 255 + 32767) // 65535 for v in deep)
        for mode, threads in [("rgba16", 1), ("rgba16", 0), ("rows16", 0), ("rgba8", 1), ("rgba8", 0), ("rows8", 3)]:
            if run([tool, "decode", fixture, out, mode, threads]).returncode != 0:
                fail(f"{name}: {mode} decode on {threads} threads failed")
            pixels = read_raw(out)[3]
            if (samples16(pixels) if "16" in mode else pixels) != (deep if "16" in mode else shallow):
                fail(f"{name}: {mode} on {threads} threads differs from the Raster samples")
        if Image and bits == 8:
            with Image.open(fixture) as image:
                reference = image.convert("RGBA").tobytes()
            if reference != shallow:
                fail(f"{name}: RGBA8 differs from libpng")
            compared += 1
    print(f"ok    {len(FIXTURES)} fixtures identical to the 0.1 decoder through every API"
          + (f"; {compared} identical to libpng" if Image else "; Pillow absent, libpng comparisons skipped"))


def check_encoding(tmp, flags, tool):
    out = tmp / "out"
    sources = [ROOT / "tests/fixtures" / name for name in ["pil_rgba_400x300.png", "pil_gray_400x300.png", "c6_b16_n_33x17.png", "c4_b8_i_33x17.png", "c0_b1_n_1x1.png"]]
    formats = ["gray8", "ga8", "rgb8", "rgba8", "gray16", "ga16", "rgb16", "rgba16"]
    checked = 0
    for source in sources:
        if run([tool, "decode", source, out, "rgba16", 1]).returncode != 0:
            fail(f"{source.name}: does not decode")
        original = samples16(read_raw(out)[3])
        for index, kind in enumerate(formats):
            channels = index % 4 + 1
            deep = index >= 4
            # What the format keeps of the source.
            expected = []
            for p in range(len(original) // 4):
                r, g, b, a = original[p * 4:p * 4 + 4]
                if not deep:
                    r, g, b, a = [(v >> 8) * 257 for v in (r, g, b, a)]
                if channels <= 2:
                    g = b = r
                if channels in (1, 3):
                    a = 65535
                expected += [r, g, b, a]
            for level, filter_kind, band_rows in [(6, -1, 0), (1, 4, 37), (0, 0, 5), (9, 2, 64)]:
                outputs = []
                for how, threads in [("whole", 0), ("whole", 1), ("stream", 0)]:
                    encoded = tmp / f"{how}{threads}.png"
                    if run([tool, "encode", source, encoded, level, filter_kind, kind, how, threads, band_rows], capture_output=True).returncode != 0:
                        fail(f"{source.name}: {kind} level {level} encode failed")
                    outputs.append(encoded.read_bytes())
                if outputs[1] != outputs[0] or outputs[2] != outputs[0]:
                    fail(f"{source.name}: {kind} level {level} differs between threads or streaming")
                encoded = tmp / "whole0.png"
                for threads in [0, 1]:
                    if run([tool, "decode", encoded, out, "rgba16", threads]).returncode != 0:
                        fail(f"{source.name}: {kind} level {level} output does not decode")
                    if samples16(read_raw(out)[3]) != expected:
                        fail(f"{source.name}: {kind} level {level} is not lossless (threads {threads})")
                if Image and not deep:
                    run([tool, "decode", encoded, out, "rgba8", 0], check=True)
                    with Image.open(encoded) as image:
                        if image.convert("RGBA").tobytes() != read_raw(out)[3]:
                            fail(f"{source.name}: {kind} level {level} decodes differently in libpng")
                checked += 1
    print(f"ok    {checked} encodings lossless and identical across threads, streaming and decoders")


def check_damage(tmp, dump, tool):
    rng = random.Random(7)
    bad = tmp / "bad.png"
    encoded = tmp / "banded.png"
    run([tool, "encode", ROOT / "tests/fixtures/pil_rgba_400x300.png", encoded, 6, -1, "rgba8", "whole", 0, 29], check=True)
    damaged = 0
    for path in [ROOT / "tests/fixtures/c6_b8_i_33x17.png", ROOT / "tests/fixtures/c3_b4_n_33x17.png", ROOT / "tests/fixtures/pil_rgba_400x300.png", encoded]:
        data = path.read_bytes()
        cases = [data[:n] for n in range(8, len(data), max(1, len(data) // 50))]
        for _ in range(40):
            changed = bytearray(data)
            for _ in range(rng.randrange(1, 4)):
                changed[rng.randrange(8, len(changed))] = rng.randrange(256)
            cases.append(bytes(changed))
        for case in cases:
            bad.write_bytes(case)
            for command in [[dump, bad, tmp / "raw"], [tool, "decode", bad, tmp / "out", "rgba8", 0], [tool, "decode", bad, tmp / "out", "rows8", 0]]:
                result = run(command, capture_output=True)
                if result.returncode not in (0, 1):
                    fail(f"{path.name}: a damaged file ended the process with {result.returncode}")
                damaged += 1
    print(f"ok    {damaged} decodes of damaged files ended cleanly")


for flags in MODES:
    run([BASE, "test", ROOT / "src/luce_png/png", *flags], check=True)
    with tempfile.TemporaryDirectory(prefix="luce-png-") as name:
        tmp = Path(name)
        dump, tool = tmp / "dump", tmp / "tool"
        run([BASE, "build", ROOT / "tests/dump.lucb", *flags, "-o", dump], check=True)
        run([BASE, "build", ROOT / "tests/tool.lucb", *flags, "-o", tool], check=True)
        check_decoding(tmp, flags, dump, tool)
        check_encoding(tmp, flags, tool)
        check_damage(tmp, dump, tool)
print("PASS luce-png")
