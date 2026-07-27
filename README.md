# Browser Helper 🦎

Remote Chrome control proxy — connects to your local Chrome via **Chrome DevTools Protocol (CDP)** and exposes a fast REST API + WebSocket GUI dashboard.

## Why?

**The Problem:** AI agents (Hermes, etc.) running on a remote server need to control Chrome on your local machine through an SSH tunnel. Standard CDP tools (snapshot, vision) send megabytes over the tunnel — every operation takes seconds.

**The Solution:** A lightweight Python proxy running on **your machine**. It connects directly to Chrome via local CDP (instant), exposes a compact REST API. Your AI agent sends compact JSON commands over the tunnel (`POST /click {"selector": ".btn"}`) and gets compact JSON responses back. **10–50× faster** than raw CDP over tunnel.

Every interactive operation **activates the tab first** (`Target.activateTarget`) — so the tab is always awake and visible in Chrome.

## Features

### v0.7 — What's New

| Feature | Endpoint | Description |
|---------|----------|-------------|
| ✅ Tab Auto-Activation | transparent | Every operation auto-activates the tab first — no manual activation needed |
| ✅ Activate Tab | `POST /activate-tab/{tab_id}` | Manually bring a tab to the foreground |
| ✅ Checkbox State | `POST /page/analyze` | Returns `selected_options` (checked items) + `visual_state` (all checkbox/radio states) |
| ✅ Condensed Snapshot | `POST /page/analyze?condensed=true` | Strips nav/sidebar/footer, returns only main content with summary counts |
| ✅ Batch Checkbox Select | `POST /checkbox/select` | Select one or multiple checkboxes/radios by label text — single (`text`) or batch (`texts`) |
| ✅ Batch Checkbox Deselect | `POST /checkbox/deselect` | Deselect one or multiple checkboxes/radios by label text — single or batch |
| ✅ Screenshot Confirmation | `?confirm=screenshot|analyze` query param | Post-action screenshot or state comparison on `/click/text`, `/click/label`, `/checkbox/select`, `/checkbox/deselect` |
| ✅ Confirm Action | `POST /confirm-action` | Standalone post-action confirmation (screenshot or state comparison) |

### Core API

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 🔌 Connect | `POST /connect` | Connect to Chrome CDP (auto-discover or explicit URL — also accepts plain HTTP base URL) |
| 🔌 Disconnect | `POST /disconnect` | Disconnect from CDP |
| 🚀 Navigate | `POST /navigate?url=...` | Navigate current tab to a URL (auto-activates) |
| 💻 Execute JS | `POST /eval` | Run JavaScript, get result |
| 🖱 Click | `POST /click` | Click element by CSS selector |
| 👆 Click by Text | `POST /click/text` | Click element by visible text — **optional `nth` param** (0-indexed, e.g. 2nd "Edit" button) |
| 👆 Click by Label | `POST /click/label` | Click `<label>` by text — framework-safe for React/Vue radios & checkboxes |
| ⌨️ Type | `POST /type` | Type text into form fields |
| ✏️ Smart Form Fill | `POST /form/fill` | Fill forms by label text — finds inputs via &lt;label&gt;, placeholder, name, aria-label |
| 🔽 Dropdown Select | `POST /form/select` | Select dropdown option by label, name, or CSS selector — **searches inside same-origin iframes too** |
| ⏳ Wait for Element | `POST /wait` | Poll until element appears in DOM (CSS selector) |
| ⏳ Wait for Text | `POST /wait/text` | Wait for specific text to appear/disappear |
| ⏳ Wait for Navigation | `POST /wait/navigation` | Wait for URL change (SPA routing) |
| ⏳ Wait for Network Idle | `POST /wait/network-idle` | Wait until network is quiet (AJAX submissions) |
| 📊 Page Analyze | `POST /page/analyze` | **Comprehensive page snapshot** — buttons, forms, modals, alerts, text preview, **checkbox/radio state**, **iframe list** |
| 📄 Page Text | `POST /page/text` | Full page innerText — clean, no HTML/script noise |
| 📑 Page Outline | `POST /page/outline` | Heading hierarchy (h1-h6) with positions + section snippets |
| 🔍 Find Element | `POST /page/find` | Find visible element by text — returns CSS selector, position, tag, attributes |
| 📄 Page Diff | `POST /page/diff` | Compare current vs previous page state (buttons added/removed, URL, text change) |
| 📺 Iframe Text | `POST /page/iframe-text` | Extract text from a specific iframe (same-origin) |
| 🔄 Iframe Switch | `POST /page/iframe/switch` | Switch active context into an iframe (index=-1 returns to main) |
| 📸 Screenshot | `POST /screenshot` | Viewport JPEG screenshot |
| 📊 DOM Query | `POST /dom_query` | Query elements by CSS selector + attribute |
| 👆 DOM Click All | `POST /dom_click_all` | Click ALL matching elements (e.g. "Load more") |

### Page Capture & Export

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 📄 Full Page Screenshot | `POST /full_screenshot` | Capture entire scrollable page |
| 🔍 Element Screenshot | `POST /element_screenshot` | Screenshot a specific element |
| 📑 PDF Export | `POST /pdf` | Save current page as PDF with options |

### Tab Management

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 📋 List Tabs | `GET /tabs` | List all open browser tabs |
| 🔍 Scan All Tabs | `POST /tabs/scan` | Extract content from ALL tabs without switching (parallel) |
| 🔎 Deep Scan Tab | `POST /tabs/deep-scan/{id}` | Extract ALL content: sub-tabs, iframes, meta — one call |
| ➕ New Tab | `POST /tab/new` | Open a new tab (to URL or about:blank) |
| ❌ Close Tab | `POST /tab/close/{id}` | Close a tab by target ID |
| 🔄 Switch Tab | `POST /switch_tab/{id}` | Switch active context to a tab |

### Cookies

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 🍪 List Cookies | `GET /cookies` | Get all browser cookies |
| ➕ Set Cookie | `POST /set_cookie` | Set a browser cookie |
| 🗑 Clear Cookies | `POST /clear_cookies` | Clear all cookies |

### Network Monitoring

| Feature | Endpoint | Description |
|---------|----------|-------------|
| ▶️ Start | `POST /network/start` | Start capturing network requests |
| ⏹ Stop | `POST /network/stop` | Stop capturing |
| 📋 Log | `GET /network/log` | Get collected request/response log |
| 🧹 Clear | `POST /network/clear` | Clear the network log |

### Session Management

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 💾 Save | `POST /session/save` | Save cookies + localStorage + sessionStorage |
| 🔄 Restore | `POST /session/restore` | Restore a previously saved session |

### Automation & Control

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 📋 Batch Script | `POST /script` | Multi-step automation script (navigate, click, type, eval, wait, …) |
| ⚡ JS Toggle | `POST /javascript/disable` / `/javascript/enable` | Disable or re-enable JavaScript |
| 📈 Performance | `GET /metrics` | Page timing and performance metrics |
| 🏥 Health | `GET /health` | Server health check (uptime, memory, ops) |
| ✅ Readiness | `GET /ready` | CDP connection readiness probe |
| 📊 Status | `GET /status` | Current connection state |

### WebSocket Real-Time Streaming

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 🔌 WebSocket | `GET /ws` (upgrade) | Real-time state updates, CDP events, console logs, live operation feed |

### GUI Dashboard

Open **http://localhost:8001** in any browser to see:
- **Real-time status** — connection indicator, tabs count, last operation
- **Operation log** — timestamped history with durations
- **Screenshot viewer** — viewport + full page screenshots
- **Tab manager** — list, switch, close, open tabs
- **Network log** — live network request tracking
- **Cookie viewer** — inspect and clear cookies
- **Script runner** — write and execute multi-step scripts
- **Session manager** — save/restore browser sessions
- **Chrome Management** — configure profile dir, debug port, Chrome path; Launch/Stop browser buttons
- **Advanced Tools** — Page Text extract, Find Element, File Upload, Form Select, Iframe Text/Switch, Page Outline
- **Action buttons** — one-click PDF, screenshot, text extraction
- **JS Console** — execute arbitrary JS and see results

### Chrome Management (v0.4+)

Start and stop Chrome directly from the API — no manual command line needed.

| Feature | Endpoint | Description |
|---------|----------|-------------|
| ⚙️ Get Settings | `GET /settings` | View saved profile dir, debug port, Chrome path |
| ⚙️ Update Settings | `POST /settings` | Save chrome_profile_dir, chrome_debug_port, chrome_path |
| ▶️ Launch Chrome | `POST /browser/launch` | Start Chrome with remote debugging (auto-increments port if busy) |
| ⏹ Stop Chrome | `POST /browser/stop` | Kill managed Chrome process |
| 🔍 Chrome Status | `GET /browser/status` | Port-based running check (no CDP call needed) |

Also via CLI: `python run.py --launch-chrome` with optional `--profile-dir` and `--debug-port`.

### Headless Chrome Sessions (v0.3+)

Launch and manage headless Chrome instances with resource limits and timeout guards.

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 🚀 Launch Session | `POST /headless/launch` | Start a new headless Chrome instance |
| ⏹ Close Session | `POST /headless/close` | Kill a session by ID |
| 📋 List Sessions | `GET /headless/sessions` | Active sessions with resource usage |
| 🌐 Navigate | `POST /headless/navigate` | Navigate session to URL |
| 💻 Evaluate JS | `POST /headless/eval` | Execute JavaScript in session |
| 📸 Screenshot | `POST /headless/screenshot` | Capture page screenshot |
| 📸 Batch Screenshot | `POST /headless/batch-screenshot` | Multiple screenshots in sequence |
| 🏥 Health | `GET /headless/health` | Pool stats + per-session resource usage |

**Pool resource limits (configurable):**
- Max concurrent sessions: 5
- Session timeout: 300s (auto-kill)
- CPU threshold: 80% (auto-kill)
- Memory limit: 512MB (auto-kill)

**Profile-aware sessions:** Pass `"profile": "<name>"` in the launch request to use a named profile's isolated data directory and extensions (see Multi-Profile section below).

```bash
# Launch a headless session
curl -s -X POST http://localhost:8001/headless/launch | python -m json.tool

# Navigate it
curl -s -X POST http://localhost:8001/headless/navigate \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "abc123", "url": "https://example.com"}'

# Take a screenshot
curl -s -X POST http://localhost:8001/headless/screenshot \
  -H 'Content-Type: application/json' \
  -d '{"session_id": "abc123"}'

# Check pool health
curl -s http://localhost:8001/headless/health | python -m json.tool
```

### Multi-Profile Session Management (v0.4+)

Named profiles with isolated data directories, per-profile extensions, resource limits, and import/export as ZIP archives.

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 📋 List Profiles | `GET /profiles` | List all profiles |
| ➕ Create Profile | `POST /profiles` | Create a new profile (name, description, tags, extensions, resource_limits) |
| 🔍 Get Profile | `GET /profiles/{name}` | Get profile details by name |
| ✏️ Update Profile | `PUT /profiles/{name}` | Update description, tags, or resource limits |
| 🗑 Delete Profile | `DELETE /profiles/{name}` | Delete profile and its data directory |
| 📦 Export Profile | `POST /profiles/{name}/export` | Export profile as ZIP (metadata + data files) |
| 📥 Import Profile | `POST /profiles/import` | Import profile from ZIP archive |
| 📋 List Extensions | `GET /profiles/{name}/extensions` | List extensions for a profile |
| ➕ Add Extension | `POST /profiles/{name}/extensions` | Add an extension path to a profile |
| ❌ Remove Extension | `DELETE /profiles/{name}/extensions` | Remove an extension from a profile |

**Profile fields:**
- `name` — unique identifier, must not contain path separators (`/`, `\`, `..`)
- `description` — free-text label
- `tags` — list of strings for categorization
- `extensions` — list of absolute paths to Chrome extensions to load
- `resource_limits` — `{max_memory_mb: 512, max_cpu_percent: 80}`
- `data_dir` — auto-managed directory under `profiles/<name>/`
- `created_at`, `last_used` — UTC timestamps

**Storage layout:**
```
~/.browser-helper/
├── profiles.json          # Metadata for all profiles (JSON)
└── profiles/
    └── <name>/            # Per-profile data directory
        └── ...            # Chrome user data, extensions, cookies
```

**Integration with headless sessions:**

Pass a `profile` parameter to `/headless/launch` — the headless Chrome instance automatically uses that profile's isolated data directory and loads its extensions:

```bash
# Create a profile
curl -X POST http://localhost:8001/profiles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "work",
    "description": "Work profile with extensions",
    "tags": ["work", "automation"],
    "extensions": ["/path/to/adblocker"]
  }'

# List profiles
curl http://localhost:8001/profiles

# Get profile details
curl http://localhost:8001/profiles/work

# Update profile metadata
curl -X PUT http://localhost:8001/profiles/work \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated work profile", "tags": ["work", "prod"]}'

# Add extension to a profile
curl -X POST http://localhost:8001/profiles/work/extensions \
  -H "Content-Type: application/json" \
  -d '{"path": "/home/user/extensions/ublock"}'

# Launch headless session WITH profile (uses its data dir + extensions)
curl -X POST http://localhost:8001/headless/launch \
  -H "Content-Type: application/json" \
  -d '{"profile": "work"}'

# Launch headless session with profile + extra extensions
curl -X POST http://localhost:8001/headless/launch \
  -H "Content-Type: application/json" \
  -d '{
    "profile": "work",
    "extensions": ["/extra/ext1", "/extra/ext2"]
  }'

# Export profile as ZIP
curl -X POST http://localhost:8001/profiles/work/export -o work-profile.zip

# Import profile from ZIP (file must be on server)
curl -X POST http://localhost:8001/profiles/import \
  -H "Content-Type: application/json" \
  -d '{"path": "/tmp/work-profile.zip"}'

# Delete profile
curl -X DELETE http://localhost:8001/profiles/work
```

**Per-profile resource limits:** Each profile carries its own `resource_limits` (`max_memory_mb`, `max_cpu_percent`). These limits are stored in the profile metadata and can be used by session management to apply per-profile resource governance (defaults: 512 MB memory, 80% CPU).

**Profile-aware headless sessions:** When launching a headless session with a named profile:
1. The profile's data directory (`~/.browser-helper/profiles/<name>/`) is used as `--user-data-dir`
2. The profile's extension list is loaded via `--load-extension` flags
3. The session handle records `profile_name` for traceability
4. Explicit `extensions` passed at launch are merged only when no profile is used; with a profile, the profile's own extensions take precedence unless overridden


### Visual Regression Testing (v0.5.0)

Screenshot diff engine compares page screenshots against stored baselines. REST API for capturing, comparing, listing, and deleting baselines. CI/CD-friendly JSON output with configurable pass/fail thresholds.

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 📸 Capture Baseline | `POST /screenshot/baseline` | Capture current page as a baseline snapshot |
| 🔍 Compare Screenshot | `POST /screenshot/compare` | Compare current screenshot against a stored baseline |
| 📋 List Baselines | `GET /screenshot/baselines` | List all stored baselines |
| 🗑 Delete Baseline | `DELETE /screenshot/baseline` | Remove a stored baseline |

**Baseline storage:** Baselines are stored under `~/.browser-helper/baselines/<profile>/<url-hash>.png` with metadata in `~/.browser-helper/baselines/index.json`.

```bash
# Capture a baseline
curl -X POST http://localhost:8001/screenshot/baseline \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "profile": "work"}'

# Compare against baseline
curl -X POST http://localhost:8001/screenshot/compare \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "profile": "work", "threshold": 0.001}'

# List stored baselines
curl http://localhost:8001/screenshot/baselines

# List baselines for a specific profile
curl "http://localhost:8001/screenshot/baselines?profile=work"

# Delete a baseline
curl -X DELETE http://localhost:8001/screenshot/baseline \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "profile": "work"}'
```

**Comparison response:**
```json
{
  "status": "ok",
  "comparison": {
    "url": "https://example.com",
    "passed": true,
    "pixel_delta": 0.0003,
    "threshold": 0.001,
    "dimensions_match": true,
    "baseline_size": {"w": 1280, "h": 720},
    "current_size": {"w": 1280, "h": 720},
    "diff_image": "<base64>",
    "baseline_taken_at": "2026-07-26T10:00:00Z",
    "compared_at": "2026-07-26T10:01:00Z"
  }
}
```

The `pixel_delta` is the fraction of differing pixels (0.0 = identical, 1.0 = completely different). A comparison **passes** when `pixel_delta <= threshold`. The `diff_image` field contains a base64-encoded PNG showing pixel differences (white = match, red = difference).

### POST /screenshot/baseline
Capture current page as a baseline snapshot.

**Request:** `{"url": "...", "profile": "...", "quality": 70}`
- `url` (optional) — page URL tag for baseline lookup
- `profile` (optional) — scope baseline to a user profile
- `quality` (optional) — JPEG quality (default 70)

**Response:**
```json
{
  "status": "ok",
  "baseline": {
    "url": "https://example.com",
    "path": "~/.browser-helper/baselines/work/abc123hash.png",
    "size": 12345,
    "timestamp": "2026-07-26T10:00:00Z"
  }
}
```

### POST /screenshot/compare
Compare current screenshot against a stored baseline.

**Request:** `{"url": "...", "profile": "...", "threshold": 0.001}`
- `url` (optional) — baseline URL key
- `profile` (optional) — profile-scoped baseline
- `threshold` (optional) — pixel diff threshold 0.0-1.0 (default 0.001)

**Response:**
```json
{
  "status": "ok",
  "comparison": {
    "url": "https://example.com",
    "passed": true,
    "pixel_delta": 0.0003,
    "threshold": 0.001,
    "dimensions_match": true,
    "baseline_size": {"w": 1280, "h": 720},
    "current_size": {"w": 1280, "h": 720},
    "diff_image": "<base64>",
    "baseline_taken_at": "2026-07-26T10:00:00Z",
    "compared_at": "2026-07-26T10:01:00Z"
  }
}
```

### GET /screenshot/baselines
List all stored baselines.

**Query params:** `?profile=work` (optional filter)

**Response:**
```json
{
  "status": "ok",
  "baselines": [
    {
      "url": "https://example.com",
      "profile": "work",
      "path": "~/.browser-helper/baselines/work/abc123hash.png",
      "size": 12345,
      "timestamp": "2026-07-26T10:00:00Z"
    }
  ],
  "count": 1
}
```

### DELETE /screenshot/baseline
Remove a stored baseline.

**Request:** `{"url": "...", "profile": "..."}`
- `url` (optional) — baseline URL key
- `profile` (optional) — profile-scoped baseline

**Response:**
```json
{
  "status": "ok",
  "deleted": true
}
```

## Quick Start

### 1. Start Chrome with remote debugging

```bash
# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9555

# Linux
google-chrome --remote-debugging-port=9555

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9555
```

### 2. Install and start Browser Helper

```bash
# Install dependencies
pip install fastapi uvicorn websockets httpx Pillow

# Start (auto-connects to CDP)
python run.py

# Or with custom port
python run.py --port 8001
```

> **Note for Windows users:** Use `python run.py` instead of `uvicorn src.main:app` to avoid import conflicts with other installed packages.

### 3. Start browsing

```bash
# Check server health
curl -s http://localhost:8001/health | python -m json.tool

# Navigate to a page
curl -s -X POST "http://localhost:8001/navigate?url=https://example.com" | python -m json.tool

# Run JavaScript
curl -s -X POST http://localhost:8001/eval \
  -H "Content-Type: application/json" \
  -d '{"js": "document.title"}' | python -m json.tool

# Take a screenshot
curl -s -X POST http://localhost:8001/screenshot | python -m json.tool

# Click by text (no selectors needed)
curl -s -X POST http://localhost:8001/click/text \
  -H "Content-Type: application/json" \
  -d '{"text": "More information"}' | python -m json.tool

# Fill a form (find fields by label)
curl -s -X POST http://localhost:8001/form/fill \
  -H "Content-Type: application/json" \
  -d '{"fields": [{"label": "email", "value": "hello@test.hu"}]}' | python -m json.tool

# Deep scan a tab (all sub-tabs + iframes in one call)
curl -s -X POST http://localhost:8001/tabs/deep-scan/TAB_ID | python -m json.tool

# Scan all tabs without switching
curl -s -X POST http://localhost:8001/tabs/scan | python -m json.tool
```

Open **http://localhost:8001** in your browser for the GUI dashboard.

## API Authentication

Set the `API_TOKEN` environment variable to enable Bearer token protection on all endpoints (except `/`, `/health`, `/ready`, `/ws`, and OpenAPI docs):

```bash
API_TOKEN=my-secret-token python run.py
```

Protected endpoints require:
```
Authorization: Bearer ***
```

If `API_TOKEN` is not set, all endpoints are open.

### Using with Hermes Agent

```bash
# In your Hermes environment
API_TOKEN=my-secret-token python run.py

# Hermes calls the REST API with:
# Authorization: Bearer ***
```

## Smart Interaction Endpoints

### `POST /click/text` — Click by visible text

No CSS selectors needed. Just the text you see on screen.

```bash
curl -X POST http://localhost:8001/click/text \
  -H 'Content-Type: application/json' \
  -d '{"text": "Jelentkezem", "timeout": 5}'
```

**Matching priority:**
1. Exact match on `<a>`, `<button>`, `[role=button]`, `input[type=submit]`
2. Partial match on interactive elements (if no exact match found)
3. Exact match on `<span>`, `<div>`, `[onclick]` (fallback)

### `POST /form/fill` — Smart form fill by label

Fill any form using the labels you see — the engine finds the right input automatically.

```bash
curl -X POST http://localhost:8001/form/fill \
  -H 'Content-Type: application/json' \
  -d '{"fields": [
    {"label": "Email", "value": "hello@test.hu"},
    {"label": "Password", "value": "secret123"},
    {"label": "Name", "value": "John Doe"},
    {"label": "Message", "value": "Hello world"}
  ]}'
```

**Field detection order:**
1. `<label for="id">` — matches label text, uses linked input by ID
2. `<label>` wrapping `<input>` — label wraps the input directly
3. `placeholder` attribute — partial match
4. `name` or `aria-label` attribute — partial match
5. Adjacent sibling — previous element before the input

### `POST /wait` — Wait for element

Essential for dynamic pages. Polls every 200ms until the element appears or timeout.

```bash
curl -X POST http://localhost:8001/wait \
  -H 'Content-Type: application/json' \
  -d '{"selector": ".success-message", "timeout": 10}'
```

### `POST /tabs/deep-scan/{tab_id}` — Deep scan a tab

Extract ALL content from a tab in ONE API call — sub-tab navigation, iframes, and metadata.

```bash
curl -X POST http://localhost:8001/tabs/deep-scan/TAB_ID
```

**Returns:**
```json
{
  "status": "ok",
  "meta": { "title": "...", "tabsFound": 5, "tabsExtracted": 5, "iframesFound": 0, "interactiveElements": 26 },
  "sub_tabs": [
    {"label": "Description", "content": "...", "len": 1124},
    {"label": "Scope", "content": "...", "len": 176}
  ],
  "iframes": [
    {"idx": 0, "src": "...", "accessible": true, "text_preview": "..."}
  ]
}
```

The deep scan JavaScript engine detects:
- Hash-based tab links (`a[href^="#"]`)
- Data-tab attributes (`[data-tab]`)
- ARIA tabs (`[role=tab]`)
- Then clicks each one, captures the visible content
- Extracts same-origin iframe content

### `POST /tabs/scan` — Scan all tabs (parallel)

Extracts basic content from ALL open tabs without switching the active tab. Uses parallel WebSocket connections (5 concurrent, configurable).

```bash
curl -X POST http://localhost:8001/tabs/scan
```

Each inactive tab is activated (`Target.activateTarget`) before extraction to wake it from Chrome's memory discard.

## Performance

| Operation | Browser Helper | Raw CDP over tunnel | Speedup |
|-----------|---------------|-------------------|---------|
| Navigate | ~240ms | ~1-2s | 4-8× |
| Screenshot | ~175ms | ~8-20s | 45-114× |
| JS Eval | ~80ms | ~500ms | 6× |
| Cookies (412) | ~314ms | ~3s | 10× |
| Deep Scan (6 tabs) | ~550ms | N/A | — |
| GZip JSON | 74% smaller | — | — |
| WS Action | ~5ms | — | — |

## Architecture

```
Your machine                       Remote server (Hermes)
┌─────────────────────────┐        ┌──────────────────────────┐
│ Chrome  ◄──port:9555─── │        │      AI Agent            │
│         CDP              │ tunnel │         │                │
│  ┌──────────────────┐   │ ◄─────►│  Compact JSON commands   │
│  │ Browser Helper    │   │        │  (POST /click, /eval…)  │
│  │ :8001             │   │        │          │               │
│  │ ┌──────────────┐  │   │        │  browser_cdp tools      │
│  │ │ FastAPI REST  │  │   │        │  (fallback)             │
│  │ │ + WebSocket   │  │   │        │                         │
│  │ │ + GUI dashb.  │  │   │        │                         │
│  │ └──────────────┘  │   │        │                         │
│  └──────────────────┘   │        └──────────────────────────┘
└─────────────────────────┘
```

## Container

```bash
docker build -t browser-helper .
docker run -p 8001:8001 \
  -e API_TOKEN=my-secret-token \
  browser-helper
```

The container bundles the CDP backend. Chrome must still be running on the host with `--remote-debugging-port=9555`; use `--add-host host.docker.internal:host-gateway` on Linux to reach it.

## Use Cases

1. **AI Agent Browser Control** — Hermes (or any agent) uses the REST API instead of slow CDP-over-tunnel
2. **Web Scraping** — Extract data, take screenshots, generate PDFs at scale
3. **Automated Testing** — Script multi-step test scenarios without fragile CSS selectors
4. **Session Replay** — Save/restore authenticated sessions
5. **Network Debugging** — Capture and inspect network requests
6. **Remote Monitoring** — Watch browser state from the dashboard
7. **Form Automation** — Fill complex forms by label text, no selectors
8. **SPA Deep-Dive** — Extract all sub-views from single-page apps via deep scan

## Test

```bash
cd tests && pytest -v
```

Current test suite: **409 tests pass, 4 skipped, 19 pre-existing failures** (432 total). All source files pass `ruff check` cleanly.

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Prerequisites, install, first run |
| [API Reference](docs/api-reference.md) | Complete endpoint docs with examples |
| [Docker](docs/docker.md) | Container build and deployment |
| [Tab Auto-Activation](docs/tab-auto-activation.md) | How `_activate_current()` works transparently |
| [Condensed Snapshot](docs/condensed-snapshot.md) | Using `?condensed=true` on `/page/analyze` |
| [Checkbox Operations](docs/checkbox-operations.md) | Batch select/deselect checkboxes and radios |
| [Screenshot Confirmation](docs/screenshot-confirmation.md) | Post-action confirmation with screenshot/state comparison |
| [Changelog](CHANGELOG.md) | Version history and release notes |
| [Workflow Example](examples/browse-workflow.py) | Complete automation pipeline demo |
| [Dashboard Demo](examples/dashboard-demo.py) | WebSocket streaming example in Python |
| [Checkbox Ops Example](examples/checkbox_ops.py) | Batch checkbox selection/deselection |
| [Condensed vs Full Example](examples/condensed_comparison.py) | Compare condensed and full snapshot modes |
