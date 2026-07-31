# Anti-Detection Compositor

**Since:** v1.8.0

`AntiDetectCompositor` (`src/anti_detection/compositor.py`) is the facade that combines every anti-detection layer — fingerprint, proxy, stealth injection, session persistence — into a single **profile bundle** (`AntiDetectProfileBundle`). One bundle describes a complete browser persona; the compositor resolves it into concrete JS patches, a proxy pick, and a session policy.

## Bundle Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | — (required) | Bundle name |
| `fingerprint_template` | string | `chrome-120` | Template name from the [Fingerprint Database](fingerprint-database.md) |
| `fingerprint_config` | object | `{}` | Optional overrides merged into the template config |
| `proxy_strategy` | string | `round-robin` | One of round-robin, random, sticky, by-tag, health-check |
| `proxy_group` | string | `null` | Tag filter for `by-tag` rotation |
| `stealth_level` | string | `medium` | `low`, `medium`, or `high` (see below) |
| `session_ttl` | number | `3600.0` | Session expiry in seconds |

**Stealth levels** (`src/stealth_injector.py`, `LEVEL_PATCHES`):

| Level | Patches applied |
|-------|-----------------|
| `low` | `navigator.webdriver` |
| `medium` | + `navigator.plugins`, `navigator.languages`, `navigator.platform` |
| `high` | + `navigator.hardwareConcurrency`, `navigator.deviceMemory`, `navigator.userAgent`, `WebGL.vendor`, `WebGL.renderer`, `canvas.fingerprint`, `screen.orientation` |

## REST API — `/api/v1/compose/*`

### POST /api/v1/compose

Compose a full anti-detection profile.

**Request:**
```json
{
  "name": "us-shopper",
  "fingerprint_template": "chrome-120",
  "fingerprint_config": {"timezone": "America/New_York"},
  "proxy_strategy": "health-check",
  "stealth_level": "high",
  "session_ttl": 1800
}
```

**Response:**
```json
{
  "status": "ok",
  "bundle": {
    "fingerprint": {
      "config": {"canvas_noise_seed": 42, "webgl_vendor": "Google Inc. (NVIDIA)", "timezone": "America/New_York"},
      "js_patches": ["(function(){const _origGetImageData=...})();"],
      "gpu": {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, ...)"}
    },
    "proxy": {"id": "...", "url": "socks5://...", "healthy": true, "latency_ms": 342.1},
    "stealth": {"level": "high", "patches": {"navigator.webdriver": "...", "WebGL.vendor": "..."}, "count": 10},
    "session": {"ttl": 1800.0},
    "combined": ["<fingerprint JS>", "<stealth JS>"]
  }
}
```

`combined` is the concatenation of all fingerprint + stealth JS patches — inject it once with `Page.addScriptToEvaluateOnNewDocument`. `400` for an unknown template or stealth level.

### POST /api/v1/compose/resolve

Resolve a fingerprint template into config + JS patches without a full compose.

**Request:** `{"template_name": "chrome-120", "overrides": {"timezone": "Europe/Berlin"}}`

**Response:** `{"status": "ok", "config": {...}, "js_patches": ["..."]}`

### POST /api/v1/compose/resolve-stealth

Resolve the JS patches for a stealth level.

**Request:** `{"level": "high"}`

**Response:** `{"status": "ok", "patches": {"navigator.webdriver": "...", ...}}` — `400` for an unknown level.

### POST /api/v1/compose/test

Run a detection test with the composed profile against known fingerprint test sites (`bot.sannysoft.com`, `fingerprintjs.com/demo`, `creepjs.org/checker`).

**Request:**
```json
{
  "bundle": {"name": "us-shopper", "fingerprint_template": "chrome-120"},
  "cdp_url": "ws://localhost:9555/devtools/page/abc123"
}
```

**Response:**
```json
{
  "status": "ok",
  "results": {
    "sites": [
      {"site": "https://bot.sannysoft.com", "passed": true, "details": "..."}
    ],
    "summary": {"total": 3, "passed": 3}
  }
}
```

`422` if `bundle` or `cdp_url` is missing. If the CDP endpoint is unreachable, per-site results carry explicit errors and the response adds a `warning` field — no fabricated passes (review fix C1).

### POST /api/v1/compose/export

Export a bundle to a JSON file on the server.

**Request:** `{"name": "us-shopper", "path": "/tmp/us-shopper.json"}` (path defaults to `/tmp/<name>.json`)

**Response:** `{"status": "ok", "path": "/tmp/us-shopper.json"}`

### POST /api/v1/compose/import

Import a bundle from a JSON file on the server.

**Request:** `{"path": "/tmp/us-shopper.json"}`

**Response:** `{"status": "ok", "bundle": {"name": "us-shopper", "fingerprint_template": "chrome-120", ...}}` — `404` if the file is missing, `422` if `path` is absent.

## Python API

```python
from anti_detection.compositor import AntiDetectCompositor, AntiDetectProfileBundle
from anti_detection.fingerprint_database import FingerprintDatabase
from proxy_rotation_manager import ProxyRotationManager
from stealth_injector import StealthInjector

compositor = AntiDetectCompositor(
    fingerprint_db=FingerprintDatabase(),
    proxy_mgr=ProxyRotationManager(),
    stealth=StealthInjector(),
)

bundle = AntiDetectProfileBundle(
    name="us-shopper",
    fingerprint_template="chrome-120",
    proxy_strategy="health-check",
    stealth_level="high",
    session_ttl=1800.0,
)

result = compositor.compose(bundle)
combined_js = result["combined_js"]   # one-shot injection payload

compositor.export_bundle(bundle, "/tmp/us-shopper.json")
loaded = compositor.import_bundle("/tmp/us-shopper.json")
```

## Related

- [Fingerprint Database](fingerprint-database.md) — the template store backing `fingerprint_template`
- [Proxy Rotation Manager](proxy-rotation-manager.md) — strategies for `proxy_strategy`
- [Session Persistence](session-persistence.md) — `session_ttl` semantics
- Source: [`src/anti_detection/compositor.py`](../src/anti_detection/compositor.py), [`src/stealth_injector.py`](../src/stealth_injector.py)
- Example: [examples/anti_detect_compositor.py](../examples/anti_detect_compositor.py)
