# luce-png

A fast multithreaded PNG decoder and encoder for Luce/Base.

Split out of luce-image on 2026-09-22 so every file format is its own package, like luce-svg and luce-psd. luce-image depends on it for `Image.open`/`save`; it depends on luce-raster, luce-compress.

## Decoding

```luce
from luce_png import png

let found = try png.info(data)                        # size, bits, color type, interlace, alpha
try png.decode_rgba8(data, pixels)                    # w * h * 4 bytes; 16-bit rounds to 8
try png.decode_rgba16(data, samples)                  # w * h * 4 u16; 8-bit scales by 257
try png.decode_rows(data, sink, (void*)&state, deep = false)   # bands of RGBA rows, in order
try png.decode_rows_at(read, (void*)&file, size, sink, (void*)&state)   # the same, the file read in pieces

try png.probe(&raster)                                # the Raster route, as before
try raster.allocate()
try png.decode(&raster)
```

Every color type and depth, palettes, tRNS and Adam7, and the color chunks:

```luce
let found = try png.info(data)
if let cicp = found.colorimetry.cicp:              # cICP: ITU-T H.273 code points
    use(cicp.color_primaries, cicp.transfer_function)
let profile = try png.icc_profile(&found)          # iCCP inflated, or none; the caller frees it
let intent = found.colorimetry.srgb_intent         # sRGB, gAMA (x 100 000), cHRM too
```

The color chunks are read as libpng 1.6.50 reads them (each before PLTE and IDAT, once, at its
length), and the iCCP profile is inflated up to its declared length and checked as
png_handle_iCCP checks it; a chunk libpng would ignore is absent here too. Which one wins is
the reader's choice: PNG 3 orders them cICP, iCCP, sRGB, gAMA, cHRM. PNGs this encoder wrote decode band by band on every processor (see below); any other PNG inflates on the calling thread while up to seven threads unfilter the rows behind it in a wavefront (each row a few kilobytes behind the one above) and another checks the Adler-32.

`decode_rows_at` never holds the file: `read(context, offset, buffer)` gives its bytes. The chunks are walked in place, then the IDAT data is read a megabyte block at a time into the inflate window (banded files a group of bands at a time, decoded on every processor), each chunk's CRC checked as it goes. Interlaced files, whose rows complete only at the last pass, inflate into all their scanlines first, a block of the file at a time; `DecodeOptions.coarse` hears their first pass (every eighth pixel each way) as soon as it is in.

## Animated PNG

```luce
let found = try png.info(data)                 # found.animated, frame_count, loop_count, plays()
var animation = try png.Animation.open(data)   # `data` must outlive it
defer animation.release()
for (index, frame) in animation.frames().indexed():
    try animation.render(index, pixels)        # frame `index`, every frame before it composited
    show(pixels, frame.duration)               # milliseconds: delay_numerator * 1000 / delay_denominator
```

An APNG's acTL, fcTL and fdAT chunks are walked as libpng 1.6.50 with the APNG patch (the
libpng Ladybird links) reads them when Ladybird's PNG loader drives it: frame by frame, the
hidden default image counted, fcTL and fdAT in one sequence of numbers, an fcTL out of range
or with bad operations an error, the first frame's fcTL ignored off the origin or at another
size, OVER on an opaque image read as SOURCE, chunks between frames skipped. A failure
before the image data fails `Animation.open`; after it, the frames read so far stand and
`complete` is false (Ladybird then shows the first frame as a still image). The still
decoders give the default image.

Each `Frame` has its rectangle (`left`, `top`, `width`, `height`), `delay_numerator` and
`delay_denominator` as written, `duration` in milliseconds (a denominator of 0 is 100),
`disposal` (`keep`, `background`, `previous`) and `blend` (OVER, else SOURCE). `render`
disposes of the frame before, decodes the frame at its size and draws it into its
rectangle as Ladybird's Painter draws it into a straight-alpha canvas: through Skia's highp
raster pipeline (premultiplied floats; Copy for SOURCE and for restoring a "previous"
disposal, SourceOver with a fused multiply-add for OVER; unpremultiplied and rounded to
nearest even), so its canvases are Ladybird's to the bit on arm64. A still PNG is an
animation of one frame.

`tests/fixtures/apng` (Ladybird's two APNG test inputs and 34 files from
`gen_apng.py`: Pillow's animations in every disposal, blend and color type, and hand-built
ones with offsets, odd delays, interlacing, chunks between frames, too many and too few
frames, broken sequences, CRCs and fcTLs, files cut short) decode to libpng's frames,
timing and failures, every composited frame's hash the same as the oracle's
(`luce-browser-tools/oracles/luce-png/apng`, libpng with the same drawing steps), and every
frame identical to the frames Ladybird's own ImageDecoder makes of them (`apng/ladybird`). Of 1,500 mutations of them with valid CRCs,
1,477 agree; libpng also takes a frame whose zlib stream goes on past its rows, or a second
tRNS chunk, with a warning, where luce-png refuses them. Like the still decoders,
16-bit samples round to 8 bits where libpng's `png_set_strip_16` (Ladybird's) keeps the
high byte, so a 16-bit APNG can differ from Ladybird's by one.

## Encoding

```luce
try png.encode_rgba8(pixels, width, height, &out)      # level 6, adaptive filters
try png.encode_rgba16(samples, width, height, &out, png.EncodeOptions(level = 9))

var encoder = try png.Encoder.begin(width, height, .rgba8, &out)   # or .rgb8, .gray16, ...
defer encoder.close()
try encoder.write_rows(band, rows)                     # write_rows16 for 16-bit formats
try encoder.finish()

try png.encode(&raster, &out)                          # a Raster, uint8 or uint16, 1..4 channels
```

- `EncodeOptions`: `level` 0..9 (zlib's), `filter` -1 (libpng's minimum sum of absolute differences per row) or a fixed 0..4, `threads`, and `band_rows` (0 for about a megabyte of pixels a band).
- Rows are filtered and deflated in bands on every processor, each band an independent DEFLATE segment (a fresh window, the first row filtered None or Sub) in its own IDAT chunk, joined by sync flushes into one valid zlib stream, as pigz does. A private ancillary chunk `luPD` records the bands so this decoder can decode them in parallel; other decoders ignore it.
- An `Encoder` holds a few bands a thread; rows come straight from the caller's buffer when whole groups arrive. Every thread count and push size gives the same bytes.

## Speed

24 MP RGBA8 on an M4 Max (16 cores), `tests/bench.lucb`; libpng through Pillow for reference:

| | photo | flat-color art |
| --- | ---: | ---: |
| 0.1 decode (Raster) | 5942 ms | 1408 ms |
| decode, file from this encoder | 58 ms | 23 ms |
| decode, file from libpng | 324 ms | 39 ms |
| libpng (Pillow) decode | 310 ms | 147 ms |
| 0.1 encode (Raster) | 5518 ms, 76.2 MB | 2356 ms, 1.54 MB |
| encode level 6 | 390 ms, 48.35 MB | 103 ms, 430 KB |
| libpng level 6 | 5900 ms, 47.98 MB | 430 ms, 414 KB |
| encode level 1 | 190 ms, 51.31 MB | 82 ms, 842 KB |
| libpng level 1 | 1060 ms, 52.76 MB | 320 ms, 813 KB |

Decoding a libpng photo is bound by inflating one stream on one thread.

## Tests

```
luc test     # module tests, then tests/drivers in native and C modes against tests/fixtures
```

`tests/fixtures/golden.txt` holds the 0.1 decoder's samples for every fixture (made by `tests/make_fixtures.py`: every color type, depth, filter and interlacing, and Pillow's files). The gate checks every decoding API against them and, with Pillow, against libpng; that the encoder is lossless in all eight formats and gives the same bytes across threads and streaming; and that damaged files fail cleanly.
