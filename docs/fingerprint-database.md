# Fingerprint Database

**Since:** v1.8.0

`FingerprintDatabase` (`src/anti_detection/fingerprint_database.py`) is a JSON-backed store of browser fingerprint templates. Each template bundles realistic signal values (canvas, WebGL, audio, navigator, screen, timezone, locale) plus a matching `config` that the compositor turns into JS patches. Templates persist to disk under `~/.browser-helper/fingerprints/` and are reloaded on init, so templates added through the API survive restarts (review fix R1).

## Shipped Templates

Four templates are available out of the box. Template **names differ from the v1.7 profile types** (`stealth-chrome-120` / `mobile-safari-ios` are `Profile` types; these are database entries):

| Template | Browser | Platform | Screen | GPU | Locale |
|----------|---------|----------|--------|-----|--------|
| `chrome-120` | chrome | Win32 | 1920×1080 | NVIDIA GeForce RTX 3060 | en-US |
| `firefox-linux` | firefox | Linux x86_64 | 1920×1080 | AMD Radeon (Mesa) | en-GB |
| `safari-ios` | safari | iPhone | 390×844 | Apple GPU | en-US |
| `edge-windows` | edge | Win32 | 2560×1440 | Microsoft Basic Render Driver | en-US |

## REST API — `/api/v1/fingerprints/*`

All endpoints return `{"status": "ok", ...}` on success, `{"status": "error", "error": "..."}` with a 4xx code on failure.

### GET /api/v1/fingerprints

List all templates (name + browser + metadata):

```json
{
  "status": "ok",
  "templates": [
    {"name": "chrome-120", "browser": "chrome", "metadata": {"version": 1, "description": "Chrome 120 on Windows 10"}}
  ]
}
```

### POST /api/v1/fingerprints

Add a template. Persisted to disk immediately (survives restart).

**Request:**
```json
{
  "name": "my-chrome",
  "browser": "chrome",
  "signals": {"timezone": "Europe/Berlin"},
  "config": {"timezone": "Europe/Berlin"}
}
```

**Response:** `{"status": "ok", "name": "my-chrome"}` — `400` if the name already exists, `422` if `name` is missing.

### GET /api/v1/fingerprints/{name}

Full template (name, browser, metadata, signals, config). `404` if not found.

### PUT /api/v1/fingerprints/{name}

Update template fields in place (any of `name`, `browser`, `signals`, `config`, `metadata`). Persisted immediately. `404` if not found.

### DELETE /api/v1/fingerprints/{name}

Delete a template (persisted). `404` if not found.

### POST /api/v1/fingerprints/generate

Generate a plausible random template for a browser type (`chrome`, `firefox`, `safari`, `edge`). Uses the GPU pool from `fingerprint_engine` and randomizes screen, hardware concurrency, and noise seeds.

**Request:** `{"browser": "chrome"}`

**Response:**
```json
{
  "status": "ok",
  "template": {
    "name": "chrome-1785486097",
    "browser": "chrome",
    "metadata": {"version": 1, "created_at": 1785486097.0, "description": "Generated chrome template"},
    "signals": {
      "canvas": {"noise_enabled": true, "noise_seed": 731},
      "webgl": {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, ...)"},
      "audio": {"sample_rate": 48000, "noise_enabled": true},
      "navigator": {"platform": "Win32", "hardwareConcurrency": 8, "deviceMemory": 8},
      "screen": {"width": 1920, "height": 1080, "colorDepth": 24},
      "timezone": "America/New_York",
      "locale": "en-US,en;q=0.9"
    },
    "config": {"canvas_noise_seed": 731, "webgl_vendor": "Google Inc. (NVIDIA)", "timezone": "America/New_York", "locale": "en-US"}
  }
}
```

`400` for an unknown browser type.

### POST /api/v1/fingerprints/{name}/export

Export a template to a JSON file on the server.

**Request:** `{"path": "/tmp/chrome-120.json"}` (path defaults to `/tmp/test.json`)

**Response:** `{"status": "ok", "path": "/tmp/chrome-120.json"}` — `404` if the template does not exist.

### POST /api/v1/fingerprints/import

Import a template from a JSON file on the server (the file must already be accessible to the server process). Imported templates are persisted immediately.

**Request:** `{"path": "/tmp/chrome-120.json"}`

**Response:** `{"status": "ok", "name": "chrome-120"}` — `404` if the file is missing, `422` if `path` is required and absent.

## Python API

```python
# Programmatic usage
from anti_detection.fingerprint_database import FingerprintDatabase, FingerprintTemplate

db = FingerprintDatabase()  # loads persisted templates + seeds defaults

# CRUD
db.add_template(FingerprintTemplate(name="my-chrome", browser="chrome",
                                    signals={"timezone": "Europe/Berlin"}))
db.list_templates()
db.get_template("chrome-120")
db.update_template("my-chrome", {"signals": {"timezone": "Europe/London"}})
db.delete_template("my-chrome")

# Generation + persistence
tpl = db.generate_template("firefox")
db.save()                       # one JSON file per template
db.export_template("chrome-120", "/tmp/chrome-120.json")
db.import_template("/tmp/chrome-120.json")
```

## Storage Layout

```
~/.browser-helper/fingerprints/
├── chrome-120.json
├── firefox-linux.json
├── safari-ios.json
└── edge-windows.json
```

One JSON file per template. Corrupted files are skipped with a warning; if nothing loads and the store is empty, the four defaults are seeded.

## Related

- [Anti-Detection Compositor](anti-detection-compositor.md) — turns templates into runnable JS patches
- Source: [`src/anti_detection/fingerprint_database.py`](../src/anti_detection/fingerprint_database.py)
- Example: [examples/fingerprint_database.py](../examples/fingerprint_database.py)
