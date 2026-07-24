# Docker

## Overview

The container bundles everything needed to run Browser Helper — Python,
Playwright, and a headless Chromium binary. No external Chrome or CDP setup
required. Just build and run.

## Quick Start

```bash
# Build
docker build -t browser-helper .

# Run
docker run -p 8000:8000 browser-helper
```

The container starts the FastAPI server on port 8000. Playwright launches a
headless Chromium instance inside the container on startup.

### With authentication

```bash
docker run -p 8000:8000 \
  -e AUTH_API_KEY=my-secret-key \
  browser-helper
```

## Using Docker Compose

```bash
docker compose up --build
```

The compose file exposes port 8000 and sets `AUTH_API_KEY` from an `.env` file
if present.

## Image Details

- **Base:** `python:3.12-slim` — minimal Debian-based Python image
- **Port:** 8000
- **User:** non-root `appuser`
- **Healthcheck:** queries `GET /health/liveness` every 30s

## Environment Variables

| Variable             | Default        | Description                                      |
|----------------------|----------------|--------------------------------------------------|
| `AUTH_API_KEY`       | _(none)_       | API key for `X-API-Key` authentication           |
| `MAX_UPLOAD_SIZE_MB` | `50`           | Max uploaded file size for image compression     |
| `PORT`               | `8000`         | Server listen port (uvicorn `--port` override)   |

## Dockerfile Structure

The Dockerfile uses four cache-optimised layers:

1. **System dependencies** — Playwright system libs + curl for healthchecks
2. **Playwright browsers** — downloads Chromium binary (cached unless Playwright version changes)
3. **Python dependencies** — cached by `pyproject.toml` checksum
4. **Source code** — changes most frequently

## Healthcheck

```bash
docker inspect --format='{{json .State.Health}}' browser-helper
```

The healthcheck runs `curl` against `http://localhost:8000/health/liveness` every
30s (after a 15s startup grace period). The liveness endpoint always returns 200
when the server is running, regardless of browser state.

## Resource Notes

- The container includes a full Chromium binary (~200 MB additional image size)
- Playwright browsers live under `/home/appuser/.cache/ms-playwright/`
- Typical idle memory usage: ~150 MB (Python + Chromium)
- Set memory limits via Docker: `--memory=512m --memory-reservation=256m`
