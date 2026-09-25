#!/usr/bin/env python3
"""Regenerate tests/fixtures: small PNGs of every colour type, bit depth, filter and
interlacing, written by a plain Python encoder (so every filter and Adam7 occurs),
plus Pillow's. The goldens in tests/fixtures/golden.txt were taken from the 0.1
decoder (luce-png 6cc9dcf) and must not be regenerated with a changed decoder."""
import random, struct, zlib
from pathlib import Path
from PIL import Image

OUT = Path(__file__).resolve().parent / "fixtures"
rng = random.Random(77)
PASSES = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]

def chunk(name, data):
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))

def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c

def encode(pixels, w, h, nc, bits, color, interlace, filter_kind, palette=None, transparency=None, split=0):
    """pixels[y][x] is a tuple of nc samples; filter_kind -1 cycles through all five."""
    passes = PASSES if interlace else [(0, 0, 1, 1)]
    rows = bytearray()
    bpp = max(1, (nc * bits + 7) // 8)
    for xs, ys, dx, dy in passes:
        previous = None
        for y in range(ys, h, dy):
            values = [s for x in range(xs, w, dx) for s in pixels[y][x]]
            if not values:
                continue
            if bits == 16:
                row = b"".join(struct.pack(">H", v) for v in values)
            elif bits == 8:
                row = bytes(values)
            else:
                packed = bytearray((len(values) * bits + 7) // 8)
                for i, v in enumerate(values):
                    packed[i * bits // 8] |= v << (8 - bits - (i * bits % 8))
                row = bytes(packed)
            if previous is None:
                previous = bytes(len(row))
            kind = (y % 5) if filter_kind < 0 else filter_kind
            out = bytearray()
            for i, v in enumerate(row):
                a = row[i - bpp] if i >= bpp else 0
                b = previous[i]
                c = previous[i - bpp] if i >= bpp else 0
                out.append((v - [0, a, b, (a + b) // 2, paeth(a, b, c)][kind]) & 255)
            rows += bytes([kind]) + out
            previous = row
    data = zlib.compress(bytes(rows), 9)
    body = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, bits, color, 0, 0, 1 if interlace else 0))
    if palette:
        body += chunk(b"PLTE", palette)
    if transparency:
        body += chunk(b"tRNS", transparency)
    if split:
        for i in range(0, len(data), split):
            body += chunk(b"IDAT", data[i:i + split])
    else:
        body += chunk(b"IDAT", data)
    return b"\x89PNG\r\n\x1a\n" + body + chunk(b"IEND", b"")

def picture(w, h, nc, top):
    return [[tuple(rng.randrange(top + 1) if rng.random() < 0.3 else ((x * 5 + y * 3 + c * 40) % (top + 1)) for c in range(nc)) for x in range(w)] for y in range(h)]

OUT.mkdir(exist_ok=True)
for color, nc, depths in [(0, 1, [1, 2, 4, 8, 16]), (2, 3, [8, 16]), (3, 1, [1, 2, 4, 8]), (4, 2, [8, 16]), (6, 4, [8, 16])]:
    for bits in depths:
        for interlace in [False, True]:
            for w, h in [(1, 1), (7, 5), (33, 17)]:
                top = (1 << bits) - 1
                entries = min(top + 1, 40)
                px = picture(w, h, nc, entries - 1 if color == 3 else top)
                palette = bytes(rng.randrange(256) for _ in range(entries * 3)) if color == 3 else None
                name = f"c{color}_b{bits}_{'i' if interlace else 'n'}_{w}x{h}.png"
                (OUT / name).write_bytes(encode(px, w, h, nc, bits, color, interlace, -1, palette, split=37 if w == 33 else 0))
# Transparency keys and palette alpha.
px = picture(20, 9, 1, 255)
(OUT / "trns_gray.png").write_bytes(encode(px, 20, 9, 1, 8, 0, False, -1, transparency=struct.pack(">H", px[3][4][0])))
px = picture(20, 9, 3, 255)
(OUT / "trns_rgb.png").write_bytes(encode(px, 20, 9, 3, 8, 2, True, -1, transparency=struct.pack(">HHH", *px[2][2])))
px = picture(20, 9, 3, 65535)
(OUT / "trns_rgb16.png").write_bytes(encode(px, 20, 9, 3, 16, 2, False, 4, transparency=struct.pack(">HHH", *px[1][1])))
px = picture(20, 9, 1, 15)
(OUT / "trns_palette.png").write_bytes(encode(px, 20, 9, 1, 4, 3, False, -1, bytes(rng.randrange(256) for _ in range(48)), bytes(rng.randrange(256) for _ in range(10))))
# Pillow's own, including one large enough for the threaded paths.
base = Image.new("RGB", (400, 300))
bp = base.load()
for y in range(300):
    for x in range(400):
        bp[x, y] = ((x * 255) // 399, (y * 255) // 299, ((x // 25 + y // 25) % 2) * 200 + rng.randrange(20))
base.convert("RGBA").save(OUT / "pil_rgba_400x300.png")
base.save(OUT / "pil_rgb_400x300.png", compress_level=1)
base.convert("L").save(OUT / "pil_gray_400x300.png")
base.convert("P", palette=Image.ADAPTIVE, colors=64).save(OUT / "pil_palette_400x300.png")
print(len(list(OUT.glob("*.png"))), "fixtures")
