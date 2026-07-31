# Proxy Rotation Manager

**Since:** v1.8.0

`ProxyRotationManager` (`src/proxy_rotation_manager.py`) is the v1.8 evolution of the existing [proxy pool](proxy-rotation.md). It wraps `ProxyPool` and adds environment-variable loading, a fifth health-check rotation strategy, and non-blocking async health probes — all exposed through the `/api/v1/proxy/*` REST API.

## Overview

The rotation manager gives you:

- **Env-var auto-load** — populate the pool from `PROXY_LIST` / `PROXY_FILE` in one call
- **5 rotation strategies** — round-robin, random, sticky, by-tag (from `ProxyPool`) plus the new health-check strategy
- **Non-blocking health checks** — `health_check_async` / `health_check_all_async` use `httpx.AsyncClient`, so a slow or unreachable proxy never stalls the event loop (review fix R3)
- **Full CRUD** — add, list, get, remove, clear proxies through one REST collection

Protocol support is unchanged from the pool: HTTP, HTTPS, and SOCKS5 URLs are auto-detected from the scheme.

## Environment Variables

| Variable | Format | Description |
|----------|--------|-------------|
| `PROXY_LIST` | comma-separated proxy URLs | e.g. `socks5://user:pass@host1:1080,http://host2:3128` |
| `PROXY_FILE` | path to a text file | one proxy URL per line; `#` comments and blank lines are ignored |

Load them into the pool at runtime:

```bash
curl -X POST http://localhost:8000/api/v1/proxy/load-from-env
```

```json
{
  "status": "ok",
  "added": 3
}
```

`added` is the number of proxies successfully parsed and inserted. Invalid URLs are skipped with a warning log — one bad entry never aborts the rest.

## Rotation Strategies

Pass `strategy` to `get_proxy()` (or to the headless-session launch flow):

| Strategy | Behavior |
|----------|----------|
| `round-robin` (default) | Cycle through healthy proxies in order |
| `random` | Pick uniformly at random |
| `sticky` | Same session always gets the same proxy |
| `by-tag` | Rotate only within proxies matching a tag |
| `health-check` | Pick the healthy proxy with the lowest `latency_ms`; falls back to round-robin before any proxy has been checked |

```python
# Python: pick a proxy with the lowest-latency strategy
from proxy_rotation_manager import ProxyRotationManager

mgr = ProxyRotationManager()
mgr.load_from_env()
proxy = mgr.get_proxy(strategy="health-check")
```

## REST API — `/api/v1/proxy/*`

All endpoints return `{"status": "ok", ...}` on success and `{"status": "error", "error": "..."}` with a 4xx code on failure.

### POST /api/v1/proxy/load-from-env

Load proxies from `PROXY_LIST` / `PROXY_FILE`. Response: `{"status": "ok", "added": int}`.

### GET /api/v1/proxy

List all proxies in the pool:

```json
{
  "status": "ok",
  "proxies": [
    {
      "id": "a1b2c3d4-...",
      "url": "socks5://user:pass@host:1080",
      "type": "SOCKS5",
      "healthy": true,
      "latency_ms": 342.1,
      "tags": ["datacenter", "us"],
      "success_count": 12,
      "fail_count": 0
    }
  ]
}
```

### POST /api/v1/proxy

Add one or more proxies.

**Request:**
```json
{
  "proxies": [
    {"url": "socks5://user:pass@host1:1080", "type": "SOCKS5", "tags": ["us"]},
    {"url": "http://host2:3128"}
  ]
}
```

**Response:** `{"status": "ok", "ids": ["<uuid>", "<uuid>"]}` — `type` is auto-detected from the URL scheme when omitted. Returns `400` for an invalid URL, `422` if `proxies` is missing or an entry has no `url`.

### GET /api/v1/proxy/health

Health summary (no probe run):

```json
{
  "status": "ok",
  "total": 3,
  "healthy": 2,
  "unhealthy": 1
}
```

### POST /api/v1/proxy/health

Run health checks. Empty body checks all proxies; `{"proxy_id": "<uuid>"}` checks one. Uses the async probe — the event loop stays responsive while unreachable proxies time out.

```json
{
  "status": "ok",
  "results": [
    {"proxy_id": "a1b2c3d4-...", "healthy": true, "latency_ms": 342.1, "last_checked": 1712345678.9}
  ]
}
```

### GET /api/v1/proxy/stats

Usage statistics: `{"status": "ok", "stats": {"total": 3, "healthy": 2, "unhealthy": 1, "total_requests": 12, "total_success": 12, "total_failures": 0, "by_tag": {"us": 2}}}`.

### GET /api/v1/proxy/{proxy_id}

Get one proxy entry. `404` if not found.

### DELETE /api/v1/proxy/{proxy_id}

Remove one proxy. `404` if not found.

### DELETE /api/v1/proxy

Clear the entire pool: `{"status": "ok"}`.

## Related

- [Proxy Pool (v1.2)](proxy-rotation.md) — the underlying `ProxyPool`, headless-session rotation, and troubleshooting
- Source: [`src/proxy_rotation_manager.py`](../src/proxy_rotation_manager.py), [`src/proxy_manager.py`](../src/proxy_manager.py)
- Example: [examples/proxy_rotation.py](../examples/proxy_rotation.py)
