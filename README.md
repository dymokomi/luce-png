# luce-png

A fast multithreaded PNG decoder and encoder for Luce/Base.

Split out of luce-image on 2026-09-22 so every file format is its own package, like luce-svg and luce-psd. luce-image depends on it for `Image.open`/`save`; it depends on luce-raster, luce-compress.

## Decoding

```luce
import png

let found = try png.info(data)                        # size, bits, colour type, interlace, alpha
try png.decode_rgba8(data, pixels)                    # w * h * 4 bytes; 16-bit rounds to 8
try png.decode_rgba16(data, samples)                  # w * h * 4 u16; 8-bit scales by 257
try png.decode_rows(data, sink, (void*)&state, deep = false)   # bands of RGBA rows, in order

try png.probe(&raster)                                # the Raster route, as before
try raster.allocate()
try png.decode(&raster)
```

Every colour type and depth, palettes, tRNS and Adam7. PNGs this encoder wrote decode band by band on every processor (see below); any other PNG inflates on the calling thread while up to seven threads unfilter the rows behind it in a wavefront (each row a few kilobytes behind the one above) and another checks the Adler-32.

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

| | photo | flat-colour art |
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
./test.sh    # module tests, then the drivers in native and C modes against tests/fixtures
```

`tests/fixtures/golden.txt` holds the 0.1 decoder's samples for every fixture (made by `tests/make_fixtures.py`: every colour type, depth, filter and interlacing, and Pillow's files). The gate checks every decoding API against them and, with Pillow, against libpng; that the encoder is lossless in all eight formats and gives the same bytes across threads and streaming; and that damaged files fail cleanly.
