# Image Compression

> **⚠️ DEPRECATED** — This feature was part of the previous Playwright-based backend.
> The current CDP backend does **not** include an image compression endpoint.
>
> Image compression may be re-added in a future release. For now, use standalone
> tools (e.g. `ffmpeg`, `libvips`, or Pillow scripts) for image processing.

---

## Previous API (removed)

The old `POST /image/compress` endpoint accepted multipart form-data uploads and
supported JPEG, PNG, and WebP conversion with:
- Quality control (1–100)
- Lossless WebP mode
- Resizing (width/height with aspect-ratio preservation)
- Metadata stripping (EXIF removal)
- Compression ratio response headers

Refer to git history for the original implementation.
