# Proxy Rotation

**Since:** v1.2.0

Browser Helper includes a built-in proxy pool manager for anti-detection web scraping and automation. Add SOCKS5, HTTP, or HTTPS proxies, check their health, and rotate them across headless sessions using 4 built-in strategies.

## Overview

Proxy rotation spreads your requests across multiple IP addresses to:

- **Avoid rate limiting** — websites see requests coming from different IPs
- **Reduce CAPTCHA triggers** — same-IP behaviour patterns are easier to detect
- **Improve geographic coverage** — use proxies from specific regions
- **Maintain availability** — unhealthy proxies are automatically skipped

The proxy pool is persisted to `~/.browser-helper/proxy_pool.json` so your proxies survive server restarts. No extra dependencies are needed — everything is built in.

## Getting Started

### No extra dependencies

The proxy pool uses only Python stdlib (`json`, `uuid`, `dataclasses`, `threading`). Health checks use `httpx` which is already a dependency of browser-helper.

### Add your first proxy

```bash
curl -X POST http://localhost:8000/proxy/pool \
  -H 'Content-Type: application/json' \
  -d '{
    "proxies": [
      {"url": "socks5://user:pass@proxy.example.com:1080", "type": "SOCKS5", "tags": ["datacenter", "us"]}
    ]
  }'
```

**Response:**
```json
{
  "status": "ok",
  "operation": "add_proxies",
  "data": {
    "ids": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]
  }
}
```

### Test proxy health

```bash
# Health check a single proxy
curl -X POST http://localhost:8000/proxy/health \
  -H 'Content-Type: application/json' \
  -d '{"proxy_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}'

# Health check all proxies
curl -X POST http://localhost:8000/proxy/health \
  -H 'Content-Type: application/json' \
  -d '{}'
```

```json
{
  "status": "ok",
  "operation": "trigger_health_check",
  "data": {
    "results": [
      {
        "proxy_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "healthy": true,
        "latency_ms": 342.1,
        "last_checked": 1712345678.9
      }
    ]
  }
}
```

## API Reference

All proxy endpoints return the [standard response envelope](api-reference.md#response-format) (`status`, `operation`, `data`).

### POST /proxy/pool

Add one or more proxies to the pool.

**Request body:**
```json
{
  "proxies": [
    {
      "url": "socks5://user:pass@host:1080",
      "type": "SOCKS5",
      "tags": ["datacenter", "us"]
    }
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `proxies` | `array` | ✓ | List of proxy objects |
| `proxies[].url` | `string` | ✓ | Proxy URL with scheme, host, and port |
| `proxies[].type` | `string` | | Proxy type (auto-detected from URL if omitted: `socks5://` → SOCKS5, `http://` → HTTP, `https://` → HTTPS) |
| `proxies[].tags` | `array[string]` | | Optional tags for rotation group filtering |

**Response (201):**
```json
{
  "status": "ok",
  "operation": "add_proxies",
  "data": {
    "ids": ["<uuid>", "<uuid>"]
  }
}
```

**Errors:** `400` if any URL is invalid (missing scheme, host, or port). `400` if the pool is full (default max: 100 proxies).

```bash
curl -X POST http://localhost:8000/proxy/pool \
  -H 'Content-Type: application/json' \
  -d '{
    "proxies": [
      {"url": "socks5://user:pass@proxy1.example.com:1080", "type": "SOCKS5", "tags": ["datacenter"]},
      {"url": "http://user:pass@proxy2.example.com:3128", "tags": ["residential"]}
    ]
  }'
```

### GET /proxy/pool

List all proxies in the pool with their health status and metadata.

```bash
curl http://localhost:8000/proxy/pool
```

**Response:**
```json
{
  "status": "ok",
  "operation": "get_proxies",
  "data": {
    "proxies": [
      {
        "id": "a1b2c3d4-...",
        "url": "socks5://***:***@proxy1.example.com:1080",
        "type": "SOCKS5",
        "tags": ["datacenter"],
        "enabled": true,
        "healthy": true,
        "last_checked": 1712345678.9,
        "latency_ms": 342.1,
        "success_count": 15,
        "fail_count": 1,
        "created_at": 1712345600.0
      }
    ]
  }
}
```

> **Note:** Proxy credentials are **redacted** in the returned `url` field (shown as `***:***@`). The full URL is stored internally and used for session connections.

### GET /proxy/pool/{proxy_id}

Get a single proxy by its UUID.

```bash
curl http://localhost:8000/proxy/pool/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Response:**
```json
{
  "status": "ok",
  "operation": "get_proxy",
  "data": {
    "id": "a1b2c3d4-...",
    "url": "socks5://***:***@proxy1.example.com:1080",
    "type": "SOCKS5",
    "tags": ["datacenter"],
    "healthy": true,
    "latency_ms": 342.1
  }
}
```

**Errors:** `404` if proxy ID not found.

### DELETE /proxy/pool/{proxy_id}

Remove a single proxy from the pool.

```bash
curl -X DELETE http://localhost:8000/proxy/pool/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Response:**
```json
{
  "status": "ok",
  "operation": "delete_proxy",
  "data": {
    "proxy_id": "a1b2c3d4-..."
  }
}
```

**Errors:** `404` if proxy ID not found. Sticky session references to the removed proxy are automatically cleaned up.

### DELETE /proxy/pool

Remove all proxies from the pool.

```bash
curl -X DELETE http://localhost:8000/proxy/pool
```

**Response:**
```json
{
  "status": "ok",
  "operation": "clear_pool",
  "data": {
    "cleared": true
  }
}
```

### POST /proxy/health

Run a health check on one proxy or all proxies. Each proxy is tested by making a request through it to `https://httpbin.org/ip`.

```bash
# Check all proxies
curl -X POST http://localhost:8000/proxy/health \
  -H 'Content-Type: application/json' \
  -d '{}'

# Check a single proxy
curl -X POST http://localhost:8000/proxy/health \
  -H 'Content-Type: application/json' \
  -d '{"proxy_id": "a1b2c3d4-..."}'
```

**Request fields:**

| Field | Type | Description |
|-------|------|-------------|
| `proxy_id` | `string` | Optional — check a single proxy. Omit to check all. |

**Response:**
```json
{
  "status": "ok",
  "operation": "trigger_health_check",
  "data": {
    "results": [
      {
        "proxy_id": "a1b2c3d4-...",
        "healthy": true,
        "latency_ms": 342.1,
        "last_checked": 1712345678.9
      }
    ]
  }
}
```

If a proxy fails, `healthy` is `false` and an `error` field is included with details.

**Errors:** `404` if `proxy_id` is specified but not found.

### GET /proxy/health

Get a summary of pool health (counts only, no per-proxy results).

```bash
curl http://localhost:8000/proxy/health
```

**Response:**
```json
{
  "status": "ok",
  "operation": "get_health_status",
  "data": {
    "total": 4,
    "healthy": 3,
    "unhealthy": 1
  }
}
```

### POST /proxy/stats

Get detailed proxy usage statistics including request counts and breakdown by tag.

```bash
curl -X POST http://localhost:8000/proxy/stats
```

**Response:**
```json
{
  "status": "ok",
  "operation": "get_proxy_stats",
  "data": {
    "total": 4,
    "healthy": 3,
    "unhealthy": 1,
    "total_requests": 42,
    "total_success": 38,
    "total_failures": 4,
    "by_tag": {
      "datacenter": 2,
      "residential": 2,
      "us": 1,
      "eu": 1
    }
  }
}
```

## Proxy Types

### SOCKS5 (recommended for scraping)

SOCKS5 proxies operate at the transport layer and work with any protocol (HTTP, HTTPS, TCP). They are the most compatible choice for browser automation:

```
socks5://user:password@proxy.example.com:1080
socks5://proxy.example.com:1080
```

Note: `socks://` without a version number also maps to SOCKS5.

### HTTP / HTTPS

HTTP(S) proxies operate at the application layer and are compatible with most proxy providers:

```
http://user:password@proxy.example.com:3128
https://proxy.example.com:443
```

HTTPS proxies (SSL-wrapped HTTP) support encrypted tunnels but may have higher latency.

### Authentication

Credentials are passed inline in the proxy URL. Both `user:password` and URL-encoded special characters are supported:

```
socks5://username:password@host:1080
socks5://user_name:pass-word@host:1080
```

> **Security note:** Proxy credentials are redacted (`***:***@`) in all API responses and server logs. The full URL with credentials is only used when launching Chrome with `--proxy-server`.

## Rotation Strategies

The proxy pool supports 4 strategies. These are applied when launching a headless Chrome session.

### round-robin (default)

Cycles through healthy proxies in order. Each call gets the next proxy in the sequence, ensuring even distribution.

```
request 1 → proxy A
request 2 → proxy B
request 3 → proxy C
request 4 → proxy A
```

### random

Picks a random healthy proxy each time. Best for avoiding detection patterns.

```
request 1 → proxy C
request 2 → proxy A
request 3 → proxy C
request 4 → proxy B
```

### sticky

Pins a session to a single proxy. Every request with the same `session_id` gets the same proxy. If the sticky proxy becomes unhealthy, the session is reassigned to a healthy proxy automatically.

```
session-abc → proxy B (always)
session-xyz → proxy A (always)
```

### by-tag

Filters the pool by a tag group (e.g., `"residential"`, `"datacenter"`, `"eu"`) then applies round-robin within that group.

```bash
# Launch headless session with by-tag strategy
curl -X POST http://localhost:8000/headless/launch \
  -H 'Content-Type: application/json' \
  -d '{
    "proxy_strategy": "by-tag",
    "proxy_group": "residential"
  }'
```

Unhealthy proxies are always skipped regardless of strategy.

## Health Checks

### How automatic health checks work

Each health check sends a request through the proxy to `https://httpbin.org/ip` with a 10-second timeout. A proxy is marked **healthy** if it returns HTTP 200.

While health checks are triggered on demand via `POST /proxy/health`, the pool is designed for scheduled health monitoring. A 60-second periodic check interval is recommended for production use (implementable via external scheduler or cron).

### Passive failure detection

In addition to explicit health checks, the pool tracks real request outcomes:

- **`report_success(proxy_id)`** — increments `success_count`, restores health if previously unhealthy
- **`report_failure(proxy_id)`** — increments `fail_count`
- After **3 consecutive failures** (`FAILURE_THRESHOLD`), the proxy is marked **unhealthy** and **disabled** (removed from rotation)

### Recovery mechanism

A disabled proxy can recover in two ways:

1. **Explicit health check** — `POST /proxy/health` re-tests the proxy against httpbin. If it passes, `healthy` is set back to `true`.
2. **Passive recovery** — A successful `report_success()` call restores the proxy to healthy status.

```python
# Python example: report proxy outcome
import httpx

response = httpx.post(
    "http://localhost:8000/proxy/health",
    json={"proxy_id": "a1b2c3d4-..."},
)
```

## Proxy Provider Examples

### Bright Data (residential proxy)

```bash
curl -X POST http://localhost:8000/proxy/pool \
  -H 'Content-Type: application/json' \
  -d '{
    "proxies": [
      {
        "url": "http://brd-customer-<ACCOUNT>-zone-<ZONE>:<PASSWORD>@zproxy.lum-superproxy.io:22225",
        "type": "HTTP",
        "tags": ["residential", "brightdata"]
      }
    ]
  }'
```

### Oxylabs (datacenter proxy)

```bash
curl -X POST http://localhost:8000/proxy/pool \
  -H 'Content-Type: application/json' \
  -d '{
    "proxies": [
      {
        "url": "http://<USERNAME>:<PASSWORD>@dc.oxylabs.io:8000",
        "type": "HTTP",
        "tags": ["datacenter", "oxylabs"]
      }
    ]
  }'
```

### Smartproxy (SOCKS5 proxy)

```bash
curl -X POST http://localhost:8000/proxy/pool \
  -H 'Content-Type: application/json' \
  -d '{
    "proxies": [
      {
        "url": "socks5://<USERNAME>:<PASSWORD>@socks-socks5.smartproxy.com:1080",
        "type": "SOCKS5",
        "tags": ["residential", "smartproxy"]
      }
    ]
  }'
```

### Generic HTTP proxy

```bash
curl -X POST http://localhost:8000/proxy/pool \
  -H 'Content-Type: application/json' \
  -d '{
    "proxies": [
      {
        "url": "http://user:password@proxy.example.com:8080",
        "type": "HTTP",
        "tags": ["custom"]
      }
    ]
  }'
```

## Headless Session Proxy

Launch a headless Chrome session with a proxy by passing `proxy_url`, `proxy_strategy`, or `proxy_group` to the launch endpoint.

### Launch with explicit proxy URL

```bash
curl -X POST http://localhost:8000/headless/launch \
  -H 'Content-Type: application/json' \
  -d '{
    "proxy_url": "socks5://user:pass@proxy.example.com:1080"
  }'
```

### Launch with rotation strategy

```bash
# Round-robin across all healthy proxies
curl -X POST http://localhost:8000/headless/launch \
  -H 'Content-Type: application/json' \
  -d '{
    "proxy_strategy": "round-robin"
  }'

# Sticky session — same proxy every time
curl -X POST http://localhost:8000/headless/launch \
  -H 'Content-Type: application/json' \
  -d '{
    "proxy_strategy": "sticky",
    "proxy_group": "datacenter"
  }'
```

### Priority order

When multiple proxy parameters are provided:

1. `proxy_url` — explicit URL takes the **highest precedence**
2. `proxy_strategy` / `proxy_group` — falls back to pool rotation if no explicit URL is given
3. Neither — session launches **without a proxy** (existing behaviour)

### Python example

```python
import httpx

base = "http://localhost:8000"

# Add proxies to the pool
httpx.post(f"{base}/proxy/pool", json={
    "proxies": [
        {"url": "socks5://user:pass@us-east.proxy.com:1080", "tags": ["us"]},
        {"url": "socks5://user:pass@eu-west.proxy.com:1080", "tags": ["eu"]},
    ]
})

# Launch headless session with proxy rotation
resp = httpx.post(f"{base}/headless/launch", json={
    "proxy_strategy": "round-robin",
    "proxy_group": "us",
})
session = resp.json()["data"]
print(f"Session {session['session_id']} on port {session['port']}")
```

### Per-session vs per-instance

| Approach | Scope | Use case |
|----------|-------|----------|
| **Per-instance** via `proxy_url` | The entire Chrome instance uses one proxy for all tabs/sessions | Testing a single proxy |
| **Per-session** via `proxy_strategy` | Each headless session picks a proxy from the pool | Rotating IPs across parallel scraping tasks |

## Visible Chrome Proxy

When using a visible (non-headless) Chrome instance, pass the `proxy` field on `/connect` to restart Chrome with `--proxy-server`:

```bash
curl -X POST http://localhost:8000/connect \
  -H 'Content-Type: application/json' \
  -d '{
    "proxy": "socks5://user:pass@proxy.example.com:1080"
  }'
```

The connection endpoint accepts an optional `cdp_url` alongside the proxy:

```bash
curl -X POST http://localhost:8000/connect \
  -H 'Content-Type: application/json' \
  -d '{
    "cdp_url": "http://127.0.0.1:9555",
    "proxy": "socks5://user:pass@proxy.example.com:1080"
  }'
```

> **Note:** The visible Chrome proxy uses the Chrome `--proxy-server` flag. This applies the proxy to the **entire Chrome instance**, not individual tabs. Changing the proxy requires disconnecting and reconnecting with a new proxy value.

## Troubleshooting

### Proxy not working / health check failing

- **Check the URL format** — must include scheme, host, and port: `socks5://host:1080`
- **Verify credentials** — some providers require authentication; ensure they are in the URL: `socks5://user:pass@host:1080`
- **Test manually** — use curl to test the proxy independently:
  ```bash
  curl -x socks5://user:pass@host:1080 https://httpbin.org/ip
  ```
- **Check the proxy provider's status page** — the proxy service itself may be down

### Authentication issues

- **Special characters** — URL-encode special chars in passwords: `pass@word` → `pass%40word`
- **Provider-format credentials** — some providers use customer IDs or zone names as the username (see the Proxy Provider Examples section above)

### Chrome ignoring proxy settings

- **DNS resolution** — Chrome may bypass the proxy for DNS resolution. This is expected with SOCKS proxies.
- **WebSocket connections** — some WebSocket traffic may not go through the proxy (protocol limitation)
- **Extension conflicts** — browser extensions like VPNs or proxy switchers can override `--proxy-server`
- The proxy is applied via Chrome's `--proxy-server` flag and affects **the entire instance**

### Connection timeouts

- **Latency** — proxy health checks use a 10-second timeout. High-latency proxies may fail the health check but still work for normal browsing.
- **Firewall** — ensure port 1080 (SOCKS5) or your provider's port is not blocked
- **Max pool size** — the pool defaults to 100 proxies. Adding more is rejected with `Pool full (100/100 proxies)`.

### Retrieving proxy IDs for deletion or health check

When adding proxies, the `POST /proxy/pool` response returns their IDs. If you lose an ID, list all proxies to find it:

```bash
curl http://localhost:8000/proxy/pool | python -m json.tool
```
