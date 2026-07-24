# Image Compression

Browser Helper includes a built-in image compression service powered by Pillow.
Upload an image and receive back a compressed, converted, or resized version —
all processing happens in memory, no temporary files written to disk.

> **Endpoint:** `POST /image/compress`

---

## Supported Formats

| Input          | Output            | Notes                                 |
|----------------|-------------------|---------------------------------------|
| JPEG (.jpg)    | JPEG, PNG, WebP  | Lossy quality control (1–100)         |
| PNG (.png)     | JPEG, PNG, WebP  | PNG output is always lossless         |
| WebP (.webp)   | JPEG, PNG, WebP  | Supports lossless and lossy modes     |

Unsupported input formats return `400 Bad Request`.

---

## Compression Modes

### Lossy (JPEG, WebP)

Set `quality` (1–100, default 85). Lower values = smaller files, lower quality.

```bash
# Aggressive JPEG compression
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@photo.jpg" \
  -F "format=jpeg" \
  -F "quality=30" \
  -o compressed.jpg
```

### Lossless (WebP only)

Set `lossless=true` to preserve every pixel. Quality is ignored in lossless mode.

```bash
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@screenshot.png" \
  -F "format=webp" \
  -F "lossless=true" \
  -o lossless.webp
```

### Format Conversion

Simply set a different output `format`:

```bash
# Convert PNG to JPEG
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@diagram.png" \
  -F "format=jpeg" \
  -o diagram.jpg
```

---

## Resizing

Provide `width` and/or `height` to resize the output image. If only one
dimension is given, the other is calculated to preserve the original aspect
ratio.

```bash
# Exact dimensions (may distort)
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@photo.jpg" \
  -F "width=800" \
  -F "height=600" \
  -o resized.jpg

# Width only — height auto-calculated
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@photo.jpg" \
  -F "width=400" \
  -o thumb.jpg
```

Resizing uses Lanczos filter (high-quality downscaling).

---

## Metadata Stripping

By default (`strip_metadata=true`), the service removes EXIF, ICC profiles, and
other metadata from the output image. This significantly reduces file size.

To preserve metadata:

```bash
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@photo.jpg" \
  -F "strip_metadata=false" \
  -o with-exif.jpg
```

---

## Response Headers

Every successful response includes compression statistics:

```
X-Original-Size: 2048000
X-Compressed-Size: 342100
X-Compression-Ratio: 5.99
X-Output-Format: webp
```

| Header               | Description                              |
|----------------------|------------------------------------------|
| `X-Original-Size`    | Input file size in bytes                 |
| `X-Compressed-Size`  | Output file size in bytes                |
| `X-Compression-Ratio`| Original ÷ compressed (higher = better) |
| `X-Output-Format`    | Actual output format (may differ from request) |

---

## Limits

- **Max upload size:** 50 MB (configurable via `MAX_UPLOAD_SIZE_MB` env var)
- **Max dimensions:** 10000 px (each axis)
- **File type:** must be a recognised image format (JPEG, PNG, or WebP)

---

## Use Cases

1. **Image optimisation for web** — batch convert to WebP with quality tuning
2. **Thumbnail generation** — resize large originals to display sizes
3. **Format migration** — convert legacy PNG assets to modern WebP
4. **Metadata sanitisation** — strip EXIF from user-uploaded images
5. **Pipeline integration** — compress images as part of a CI/CD or ETL workflow
