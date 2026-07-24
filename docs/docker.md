# Docker

## Overview

The container bundles the Browser Helper CDP server — Python dependencies and the FastAPI application. Note that Chrome itself is **not** included in the container; Browser Helper connects to a Chrome instance running on the **host** machine via CDP over the network.

## Quick Start

```bash
# Build
docker build -t browser-helper .

# Run (Chrome must be accessible from the container)
docker run -p 8000:8000 \
  --add-host host.docker.internal:host-gateway \
  browser-helper
```

The `--add-host` flag on Linux makes `host.docker.internal` resolve to the host,
so Browser Helper can reach Chrome at `host.docker.internal:9555`.

### Chrome connection options

The CDP client auto-discovers Chrome via `http://127.0.0.1:9555/json` by default.
In Docker, you may need to set a custom CDP URL:

```bash
docker run -p 8000:8000 \
  -e CDP_HTTP_URL=http://host.docker.internal:9555 \
  --add-host host.docker.internal:host-gateway \
  browser-helper
```

### With authentication

```bash
docker run -p 8000:8000 \
  -e API_TOKEN=my-secret-token \
  --add-host host.docker.internal:host-gateway \
  browser-helper
```

## Using Docker Compose

```bash
docker compose up --build
```

The compose file exposes port 8000. Edit `docker-compose.yml` to set environment
variables like `API_TOKEN` and `CDP_HTTP_URL`.

## Image Details

- **Base:** `python:3.12-slim` — minimal Debian-based Python image
- **Port:** 8000
- **User:** non-root `appuser`
- **Healthcheck:** queries `GET /health` every 30s

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_TOKEN` | _(none)_ | Bearer token for API authentication |
| `PORT` | `8000` | Server listen port |
| `HOST` | `0.0.0.0` | Server bind address |
| `CDP_HTTP_URL` | `http://127.0.0.1:9555` | Chrome DevTools Protocol HTTP endpoint |

## Dockerfile Structure

The Dockerfile uses four cache-optimised layers:

1. **System dependencies** — curl for healthchecks
2. **Python dependencies** — cached by `pyproject.toml` checksum
3. **Source code** — changes most frequently
4. **Static files** — dashboard HTML/CSS

## Healthcheck

```bash
docker inspect --format='{{json .State.Health}}' browser-helper
```

The healthcheck runs `curl` against `http://localhost:8000/health` every 30s
(after a 15s startup grace period). The health endpoint always returns 200 when
the server is running, regardless of CDP connection state.

## Resource Notes

- The container is lightweight (~120 MB) since it does **not** bundle a browser
- Typical idle memory usage: ~50 MB (Python + FastAPI)
- Chrome must be running on the host and accessible from the container
- Set memory limits via Docker: `--memory=256m --memory-reservation=128m`
