# Getting Started

## Prerequisites

- **Python 3.10+** installed on your system
- **Playwright** (installed via pip, see below)

No Chrome/Chromium installation needed — Playwright manages its own headless
Chromium binary via `playwright install`.

---

## Installation

### From source (recommended)

```bash
git clone <repo-url>
cd browser-helper

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Install Playwright's bundled Chromium
playwright install chromium
```

### Minimal install (production)

```bash
pip install fastapi uvicorn Pillow python-multipart playwright pytest
playwright install chromium
```

See `pyproject.toml` for exact version requirements.

---

## First Run

```bash
# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On startup, the server:
1. Launches a headless Chromium instance via Playwright
2. Exposes the REST API on port 8000

The server starts serving immediately, but browser endpoints will return 504
until the browser is fully ready. Poll `/health/readiness` to know when it's up:

```bash
# Wait for browser readiness
while ! curl -sf http://localhost:8000/health/readiness > /dev/null; do
  sleep 1
done
echo "Browser is ready"
```

Open http://localhost:8000/docs to see interactive OpenAPI documentation.

> **Tip:** The server also serves a **real-time GUI dashboard** at http://localhost:8000
> when using the CDP-based backend (`src.main`, documented in the API Reference's
> WebSocket section). The Playwright backend (`app.main`) provides OpenAPI docs only.

---

## Verify It Works

With the server running:

```bash
# Check server is alive
curl -s http://localhost:8000/health/liveness
# → {"status": "ok"}

# Check browser is ready
curl -s http://localhost:8000/health/readiness
# → {"status": "ok"}

# Fetch rendered HTML
curl -s -X POST http://localhost:8000/content \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'

# Take a screenshot
curl -s -X POST http://localhost:8000/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' \
  -o shot.png

# Run JavaScript
curl -s -X POST http://localhost:8000/function \
  -H "Content-Type: application/json" \
  -d '{"code": "document.title"}' | python -m json.tool
# → {"result": "Example Domain"}
```

---

## What's Next

- Browse the **[API Reference](api-reference.md)** for all available endpoints
- Use **[Docker](docker.md)** for containerised deployment
- Learn about **[Image Compression](image-compression.md)** features
- Explore the **[Dashboard Demo](../examples/dashboard-demo.py)** for real-time WebSocket streaming
