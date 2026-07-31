# Anti-Detection Profile Manager

**Since:** v1.7.0

The profile manager extends the existing [multi-profile system](../#multi-profile-session-management-v04) with anti-detection capabilities. Each profile can carry a browser fingerprint — a set of realistic signal values (user-agent, screen, WebGL, canvas, audio, timezone) that are injected into browser contexts to avoid fingerprint-based detection.

## Predefined Fingerprint Templates

Four templates are available out of the box. Each is a full fingerprint with consistent UA, screen, GPU, and timing values:

| Template | UA | Platform | Screen | GPU | Locale |
|----------|----|----------|--------|-----|--------|
| `stealth-chrome-120` | Chrome 120 / Win10 | Win32 | 1920×1080 | Intel UHD | en-US |
| `mobile-safari-ios` | Safari 17 / iPhone | iPhone | 390×844 | Apple GPU | en-US |
| `firefox-linux` | Firefox 120 / Linux | Linux x86_64 | 1366×768 | Mesa Intel HD | de-DE |
| `edge-windows` | Edge 120 / Win10 | Win64 | 1920×1080 | Intel UHD | en-US |

## Creating an Anti-Detection Profile

```bash
# From a template (auto-named: ad_stealth_chrome_120)
curl -X POST http://localhost:8000/profiles \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "work-stealth",
    "description": "Stealth profile for work browsing",
    "profile_type": "stealth-chrome-120"
  }'

# List all profiles (standard + anti-detection)
curl http://localhost:8000/profiles

# Get profile details — includes fingerprint fields
curl http://localhost:8000/profiles/work-stealth
```

**Response for an anti-detection profile:**

```json
{
  "name": "work-stealth",
  "profile_type": "stealth-chrome-120",
  "fingerprint": {
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "platform": "Win32",
    "hardware_concurrency": 8,
    "device_memory": 8,
    "screen_width": 1920,
    "screen_height": 1080,
    "color_depth": 24,
    "pixel_ratio": 1.0,
    "timezone": "America/New_York",
    "webgl_vendor": "Google Inc. (Intel)",
    "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0)",
    "canvas_offset": [0, 0],
    "audio_variance_pct": 0.0001
  },
  "data_dir": "~/.browser-helper/profiles/work-stealth/",
  "created_at": 1712345678.9,
  "last_used": 1712345678.9
}
```

## Profile Selection Strategies

When multiple anti-detection profiles exist, `ProfileManager.select_profile_for_request()` chooses one per request:

| Strategy | Behavior |
|----------|----------|
| `random` | Picks uniformly at random from available anti-detection profiles |
| `sticky` | Pins a session to one profile — same `session_id` always gets the same profile |
| `geo-match` | Matches profile timezone region (America/Europe/Asia) to the request location |

```python
# Python: select a profile for a request
from profile_manager import ProfileManager

mgr = ProfileManager()

# Pick uniformly at random
profile = mgr.select_profile_for_request(strategy="random")

# Pin to a session
profile = mgr.select_profile_for_request(strategy="sticky", session_id="sess-123")

# Match by timezone region
profile = mgr.select_profile_for_request(
    strategy="geo-match",
    timezone="Europe/Berlin",
)
```

## Profile Validation

The `ProfileValidator` class performs static consistency checks on fingerprint data:

```python
from anti_detection.profile_types import ProfileValidator

validator = ProfileValidator()

# Check a fingerprint dict for internal consistency
issues = ProfileValidator.check_fingerprint_consistency(fingerprint_dict)
# Returns list of issue strings, empty if all checks pass
```

Detected issues include:
- UA/platform mismatch (e.g., iOS UA with Windows platform)
- Missing required fields
- Implausible combinations (e.g., macOS UA with Linux platform)

The validator also provides references to known remote checker services (`bot.sannysoft.com`, `fingerprint.com`) for live verification.

## Storage Layout

```
~/.browser-helper/
├── profiles.json          # Metadata for all profiles (standard + anti-detection)
└── profiles/
    └── <name>/            # Per-profile data directory
        └── ...            # Chrome user data, extensions, cookies
```

Anti-detection profiles use the same JSON persistence as standard profiles, with additional `profile_type` and `fingerprint` fields in the stored metadata.

## Integrating with Headless Sessions

Pass the profile name when launching a headless session — the anti-detection fingerprint is injected as JavaScript patches via `Page.addScriptToEvaluateOnNewDocument` before any page scripts run:

```bash
# Launch headless session WITH anti-detection profile
curl -X POST http://localhost:8000/headless/launch \
  -H 'Content-Type: application/json' \
  -d '{"profile": "work-stealth"}'
```

The fingerprint signals (user-agent, platform, WebGL, canvas, audio, screen) are patched at the CDP level, making them invisible to page scripts and fingerprinting services.
