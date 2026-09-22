# luce-png

A PNG decoder and encoder for Luce/Base.

Split out of luce-image on 2026-09-22 so every file format is its own package, like luce-svg and luce-psd. luce-image depends on it for `Image.open`/`save`; it depends on luce-raster, luce-deflate.

```
./test.sh    # the module's test blocks in native and C modes
```
