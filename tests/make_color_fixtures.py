#!/usr/bin/env python3
"""Write tests/fixtures/color: small PNGs with colour chunks (cICP, iCCP, sRGB, gAMA, cHRM)
in the places and shapes libpng accepts and ignores, each with the profile its iCCP should
inflate to beside it (NAME.icc) when libpng keeps one. The WPT and Ladybird images there
(see NOTICE) are copied, not written here."""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "fixtures" / "color"


def chunk(name, data):
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


def png(width, height, color, rows, before=(), after_plte=(), palette=None):
    """`rows` are the raw scanlines without filter bytes; chunks in `before` go after IHDR,
    those in `after_plte` after the palette."""
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
    for name, body in before:
        data += chunk(name, body)
    if palette is not None:
        data += chunk(b"PLTE", palette)
    for name, body in after_plte:
        data += chunk(name, body)
    data += chunk(b"IDAT", zlib.compress(b"".join(b"\0" + row for row in rows)))
    return data + chunk(b"IEND", b"")


def s15(v):
    return struct.pack(">i", int(round(v * 65536)))


def icc(dcs, curve_tags, version=0x04300000, cls=b"mntr"):
    """A small matrix/TRC (or gray) profile."""
    tags = list(curve_tags)
    offset = 132 + 12 * len(tags)
    table = b""
    body = b""
    for sig, data in tags:
        table += sig + struct.pack(">II", offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    size = offset + len(body)
    header = struct.pack(">I", size) + b"lucc" + struct.pack(">I", version) + cls + dcs + b"XYZ " + b"\0" * 12 + b"acsp"
    header += b"APPL" + b"\0" * 20 + struct.pack(">I", 0) + s15(0.9642) + s15(1.0) + s15(0.8249) + b"lucc" + b"\0" * 44
    return header + struct.pack(">I", len(tags)) + table + body


def xyz(x, y, z):
    return b"XYZ \0\0\0\0" + s15(x) + s15(y) + s15(z)


def gamma_curve(g):
    return b"curv\0\0\0\0" + struct.pack(">IH", 1, int(round(g * 256))) + b"\0\0"


def iccp(name, profile, level=9):
    return name + b"\0\0" + zlib.compress(profile, level)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rgb_rows = [bytes([0x99, 0, 0] * 4)] * 4
    gray_rows = [bytes([0x80] * 4)] * 4
    rgb_profile = icc(b"RGB ", [(b"rXYZ", xyz(0.4361, 0.2225, 0.0139)), (b"gXYZ", xyz(0.3851, 0.7169, 0.0971)), (b"bXYZ", xyz(0.1431, 0.0606, 0.7141)), (b"rTRC", gamma_curve(2.2)), (b"gTRC", gamma_curve(2.2)), (b"bTRC", gamma_curve(2.2))])
    gray_profile = icc(b"GRAY", [(b"kTRC", gamma_curve(1.8))])
    files = {}
    profiles = {}

    files["rgb-iccp.png"] = png(4, 4, 2, rgb_rows, before=[(b"iCCP", iccp(b"Adobe-ish", rgb_profile))])
    profiles["rgb-iccp.icc"] = rgb_profile
    files["gray-iccp.png"] = png(4, 4, 0, gray_rows, before=[(b"iCCP", iccp(b"gray", gray_profile))])
    profiles["gray-iccp.icc"] = gray_profile
    # A gray profile on an RGB image, and an RGB one on a gray image: libpng ignores both.
    files["rgb-gray-profile.png"] = png(4, 4, 2, rgb_rows, before=[(b"iCCP", iccp(b"gray", gray_profile))])
    files["gray-rgb-profile.png"] = png(4, 4, 0, gray_rows, before=[(b"iCCP", iccp(b"rgb", rgb_profile))])
    # After PLTE the colour chunks are out of place; the second of two is a duplicate.
    palette = bytes([0x99, 0, 0, 0, 0x99, 0])
    files["iccp-after-plte.png"] = png(4, 4, 3, [bytes([0, 1, 0, 1])] * 4, palette=palette, after_plte=[(b"iCCP", iccp(b"late", rgb_profile)), (b"gAMA", struct.pack(">I", 45455))])
    files["two-iccp.png"] = png(4, 4, 2, rgb_rows, before=[(b"iCCP", iccp(b"first", rgb_profile)), (b"iCCP", iccp(b"second", rgb_profile[:-4] + b"\1\2\3\4"))])
    profiles["two-iccp.icc"] = rgb_profile
    # A broken zlib stream, a profile shorter than its header says, an abstract profile,
    # a missing keyword and a deflate stream with trailing data.
    broken = bytearray(iccp(b"broken", rgb_profile))
    broken[-6] ^= 0xFF
    files["iccp-bad-zlib.png"] = png(4, 4, 2, rgb_rows, before=[(b"iCCP", bytes(broken))])
    short = struct.pack(">I", len(rgb_profile) + 64) + rgb_profile[4:]
    files["iccp-truncated.png"] = png(4, 4, 2, rgb_rows, before=[(b"iCCP", iccp(b"short", short))])
    abstract = rgb_profile[:12] + b"abst" + rgb_profile[16:]
    files["iccp-abstract.png"] = png(4, 4, 2, rgb_rows, before=[(b"iCCP", iccp(b"abstract", abstract))])
    files["iccp-no-keyword.png"] = png(4, 4, 2, rgb_rows, before=[(b"iCCP", b"\0\0" + zlib.compress(rgb_profile))])
    longer = rgb_profile + b"extra bytes past the profile"
    files["iccp-extra-data.png"] = png(4, 4, 2, rgb_rows, before=[(b"iCCP", iccp(b"longer", longer))])
    profiles["iccp-extra-data.icc"] = rgb_profile
    # cICP with iCCP (both read; the reader picks), and gAMA, cHRM and sRGB.
    files["cicp-iccp.png"] = png(4, 4, 2, rgb_rows, before=[(b"cICP", bytes([12, 13, 0, 1])), (b"iCCP", iccp(b"also", rgb_profile))])
    profiles["cicp-iccp.icc"] = rgb_profile
    chrm = struct.pack(">8I", 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000)
    files["gama-chrm-srgb.png"] = png(4, 4, 2, rgb_rows, before=[(b"gAMA", struct.pack(">I", 45455)), (b"cHRM", chrm), (b"sRGB", b"\x01")])
    # An sRGB intent past 3, a gAMA past 2^31 - 1 and a short cICP are ignored.
    files["color-invalid.png"] = png(4, 4, 2, rgb_rows, before=[(b"sRGB", b"\x05"), (b"gAMA", struct.pack(">I", 0x80000000)), (b"cICP", b"\x01\x0d\x00")])

    for name, data in sorted(files.items()):
        (OUT / name).write_bytes(data)
    for name, data in sorted(profiles.items()):
        (OUT / name).write_bytes(data)
    print(f"{len(files)} PNGs, {len(profiles)} profiles")


if __name__ == "__main__":
    main()
