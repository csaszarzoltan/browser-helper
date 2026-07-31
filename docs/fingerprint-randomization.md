# Fingerprint Randomization

**Since:** v1.7.0

Browser fingerprinting uses a combination of browser signals (WebGL renderer, canvas drawing, audio processing, navigator properties, screen) to create a unique identifier. Browser Helper's fingerprint randomization injects JavaScript patches at the CDP level that alter these signals — making each browser session appear as a different device.

## Architecture

Two complementary layers work together:

| Layer | Module | Purpose |
|-------|--------|---------|
| Signal Modules | `src/anti_detection/signal_modules.py` | Per-signal JS patches for canvas, WebGL, navigator, audio, screen |
| Fingerprint Randomizer | `src/anti_detection/fingerprint_randomizer.py` | Profile-aware JS generators using stored fingerprint values |
| Fingerprint Engine | `src/fingerprint_engine.py` | Per-session seeded noise generation + GPU pool |
| Stealth Injector | `src/stealth_injector.py` | Level-based patch presets (low/medium/high) |

## Signal Modules (P1-1)

### CanvasFingerprinter

Injects deterministic noise into canvas operations. Same seed → same noise → same fingerprint. Seeds vary per session so each session produces unique, but consistent, canvas output.

```javascript
// Patches HTMLCanvasElement.prototype.toDataURL and toBlob
// Adds ±1 per-channel pixel noise using seeded LCG hash
const SEED = 12345;
function seededHash(x, y) {
    let h = (SEED ^ (x * 374761393 + y * 668265263)) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return (h ^ (h >>> 16)) & 3;
}
```

### WebGLSpoofer

Overrides WebGL `getParameter()` for the two fingerprint-critical constants:

```javascript
// UNMASKED_VENDOR_WEBGL  (0x9245 → 37445)
// UNMASKED_RENDERER_WEBGL (0x9246 → 37446)
ctx.getParameter = function(p) {
    if (p === 37445) return 'Google Inc. (Intel)';
    if (p === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630)';
    return orig(p);
};
```

### NavigatorSpoofer

Patches 6 `navigator` properties via `Object.defineProperty` with `get:` accessors:

| Property | Patch |
|----------|-------|
| `navigator.userAgent` | Full UA string matching the profile |
| `navigator.platform` | Inferred from UA (Win32, MacIntel, Linux x86_64, iPhone) |
| `navigator.language` | Profile locale (e.g., `"en-US"`, `"de-DE"`) |
| `navigator.languages` | Ordered array matching language |
| `navigator.hardwareConcurrency` | Profile value (e.g., 4, 8, 12) |
| `navigator.deviceMemory` | Profile value (e.g., 4, 8, 16 GB) |

### AudioContextRandomizer

Adds sub-percent variance to `AudioBuffer.getChannelData()` output (default: 0.01% = 0.0001). Valid range: 0.001%–1%.

```javascript
AudioBuffer.prototype.getChannelData = function(channel) {
    const data = origGetChannelData.call(this, channel);
    for (let i = 0; i < data.length; i++) {
        data[i] += (Math.random() - 0.5) * 0.0001;
    }
    return data;
};
```

### ScreenColorConsistency

Ensures `screen.colorDepth` and `screen.pixelDepth` return the same value (24 or 32), preventing a common fingerprint inconsistency.

## Fingerprint Randomizer (P1-2)

The `FingerprintRandomizer` class generates injection-ready JavaScript strings from stored profile fingerprint values:

```python
from anti_detection.fingerprint_randomizer import FingerprintRandomizer

# Canvas offset patch — shifts RGBA values by (dx, dy)
canvas_js = FingerprintRandomizer.build_canvas_patch((2, -1))

# WebGL vendor/renderer patch
webgl_js = FingerprintRandomizer.build_webgl_patch(
    "Google Inc. (NVIDIA)",
    "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
)

# Audio noise patch
audio_js = FingerprintRandomizer.build_audio_patch(0.0001)
```

## Fingerprint Engine

The `FingerprintEngine` (`src/fingerprint_engine.py`) provides per-session seed generation with a curated GPU vendor/renderer pool:

```python
from fingerprint_engine import FingerprintConfig, FingerprintEngine

config = FingerprintEngine.get_default_config()
# Customise dimensions
config.timezone = "Europe/Berlin"
config.locale = "de-DE"
config.hardware_concurrency = 8

engine = FingerprintEngine(config)
scripts = engine.generate_all_scripts()
# Returns dict: {canvas_js, webgl_js, audio_js, navigator_js, screen_js}
```

### GPU Vendor/Renderer Pool

Curated from real hardware for plausibility:

| Vendor | Example Renderers |
|--------|------------------|
| NVIDIA | RTX 4090, RTX 4080, RTX 3080, RTX 3070, RTX 3060 Ti, GTX 1660 |
| AMD | RX 7900 XTX, RX 7800 XT, RX 6800 XT, Radeon Graphics |
| Intel | Arc A770, Arc A750, UHD Graphics 770, Iris Xe |
| Apple | M2, M2 Pro, M2 Max, M3, M3 Pro, M3 Max |

### FingerprintConfig

14 configurable dimensions. All fields default to `0`, `None`, or `""`, meaning "auto-pick":

| Field | Type | Description |
|-------|------|-------------|
| `canvas_noise_seed` | `int` | Seed for canvas noise (0 = random per session) |
| `webgl_vendor` | `str` | WebGL vendor override (empty = auto-pick) |
| `webgl_renderer` | `str` | WebGL renderer override (empty = auto-pick) |
| `audio_sample_rate` | `int` | AudioContext sample rate (default 44100) |
| `geolocation` | `dict` | `{lat, lng}` override |
| `timezone` | `str` | IANA timezone (e.g., "America/New_York") |
| `locale` | `str` | Locale string (e.g., "en-US") |
| `canvas_offset_x` / `canvas_offset_y` | `int` | Canvas 2D noise offset |
| `hardware_concurrency` | `int` | navigator.hardwareConcurrency |
| `device_memory` | `float` | navigator.deviceMemory |
| `screen_width` / `screen_height` | `int` | Screen resolution |
| `color_depth` | `int` | Screen color depth |
| `platform` | `str` | navigator.platform |

## REST API

### Generate a fingerprint (POST) {#post-fingerprint}

Creates a randomised fingerprint for an existing profile.

```bash
curl -X POST http://localhost:8000/profile/work-stealth/fingerprint \
  -H 'Content-Type: application/json' \
  -d '{"overrides": {"timezone": "Europe/Berlin", "hardware_concurrency": 8}}'
```

**Response (201):**
```json
{
  "fingerprint": {
    "canvas_offset_x": 3,
    "canvas_offset_y": -2,
    "webgl_vendor": "Google Inc. (NVIDIA)",
    "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
    "hardware_concurrency": 8,
    "device_memory": 16,
    "screen_width": 1920,
    "screen_height": 1080,
    "color_depth": 30,
    "timezone": "Europe/Berlin",
    "platform": "Win32"
  }
}
```

### Get fingerprint (GET)

```bash
curl http://localhost:8000/profile/work-stealth/fingerprint
```

**Response:**
```json
{
  "fingerprint": { "...": "..." },
  "fingerprint_config": null
}
```

### Set fingerprint config (PUT)

Persist a `FingerprintConfig` to a profile. Only known fields accepted — unknown keys return 422.

```bash
curl -X PUT http://localhost:8000/profile/work-stealth/fingerprint \
  -H 'Content-Type: application/json' \
  -d '{
    "timezone": "Europe/London",
    "locale": "en-GB",
    "hardware_concurrency": 4
  }'
```

**Accepted config fields:** `canvas_noise_seed`, `webgl_vendor`, `webgl_renderer`, `audio_sample_rate`, `geolocation`, `timezone`, `locale`, `canvas_offset_x`, `canvas_offset_y`, `hardware_concurrency`, `device_memory`, `screen_width`, `screen_height`, `color_depth`, `platform`.

## Integration with Headless Sessions

Fingerprint patches are automatically injected when launching a headless session with a profile that has fingerprint data:

```bash
# Launch with anti-detection profile — fingerprint injected automatically
curl -X POST http://localhost:8000/headless/launch \
  -H 'Content-Type: application/json' \
  -d '{"profile": "work-stealth"}'
```

The `StealthInjector` applies patches at `low`, `medium`, or `high` levels (TBD — P1 implementation) via `Page.addScriptToEvaluateOnNewDocument` before any page scripts execute.
