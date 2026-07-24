# Browser Helper 🦎

Remote Chrome control proxy — connects to your local Chrome via **Chrome DevTools Protocol (CDP)** and exposes a fast REST API + WebSocket GUI dashboard.

## Why?

**The Problem:** AI agents (Hermes, etc.) running on a remote server need to control Chrome on your local machine through an SSH tunnel. Standard CDP tools (snapshot, vision) send megabytes over the tunnel — every operation takes seconds.

**The Solution:** A lightweight Python proxy running on **your machine**. It connects directly to Chrome via local CDP (instant), exposes a compact REST API. Your AI agent sends compact JSON commands over the tunnel (`POST /click {"selector": ".btn"}`) and gets compact JSON responses back. **10–50× faster** than raw CDP over tunnel.

## Features

### Core API

| Feature | Endpoint | Description |
|---------|----------|-------------|
| 🔌 Connect | `POST /connect` | Connect to Chrome CDP (auto-discover or explicit URL) |
| 🔌 Disconnect | `POST /disconnect` | Disconnect from CDP |
| 🚀 Navigate | `POST /navigate?url=...` | Navigate current tab to a URL |
| 💻 Execute JS | `POST /eval` | Run JavaScript, get result |
| 🖱 Click | `POST /click` | Click element by CSS selector |
| ⌨️ Type | `POST /type` | Type text into form fields |
| 📸 Screenshot | `POST /screenshot` | Viewport JPEG screenshot |
| 📖 Get Text | `POST /get_text` | Extract visible page text |
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
| 🔍 Scan All Tabs | `POST /tabs/scan` | Extract content from ALL tabs without switching |
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

Open **http://localhost:8000** in any browser to see:
- **Real-time status** — connection indicator, tabs count, last operation
- **Operation log** — timestamped history with durations
- **Screenshot viewer** — viewport + full page screenshots
- **Tab manager** — list, switch, close, open tabs
- **Network log** — live network request tracking
- **Cookie viewer** — inspect and clear cookies
- **Script runner** — write and execute multi-step scripts
- **Session manager** — save/restore browser sessions
- **Action buttons** — one-click PDF, screenshot, text extraction
- **JS Console** — execute arbitrary JS and see results

All updated in real-time via WebSocket. No page reload needed.

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
python run.py --port 8000
```

> **Note for Windows users:** Use `python run.py` instead of `uvicorn src.main:app` to avoid import conflicts with other installed packages.

### 3. Start browsing

```bash
# Check server health
curl -s http://localhost:8000/health | python -m json.tool

# Navigate to a page
curl -s -X POST "http://localhost:8000/navigate?url=https://example.com" | python -m json.tool

# Run JavaScript
curl -s -X POST http://localhost:8000/eval \
  -H "Content-Type: application/json" \
  -d '{"js": "document.title"}' | python -m json.tool

# Take a screenshot
curl -s -X POST http://localhost:8000/screenshot | python -m json.tool

# Click an element
curl -s -X POST http://localhost:8000/click \
  -H "Content-Type: application/json" \
  -d '{"selector": "a"}' | python -m json.tool
```

Open **http://localhost:8000** in your browser for the GUI dashboard.

## API Authentication

Set the `API_TOKEN` environment variable to enable Bearer token protection on all endpoints (except `/`, `/health`, `/ready`, `/ws`, and OpenAPI docs):

```bash
API_TOKEN=my-secret-token python run.py
```

Protected endpoints require:
```
Authorization: Bearer my-secret-token
```

If `API_TOKEN` is not set, all endpoints are open.

### Using with Hermes Agent

```bash
# In your Hermes environment
API_TOKEN=my-secret-token python run.py

# Hermes calls the REST API with:
# Authorization: Bearer my-secret-token
```

## Architecture

```
Your machine                       Remote server (Hermes)
┌─────────────────────────┐        ┌──────────────────────────┐
│ Chrome  ◄──port:9555─── │        │      AI Agent            │
│         CDP              │ tunnel │         │                │
│  ┌──────────────────┐   │ ◄─────►│  Compact JSON commands   │
│  │ Browser Helper    │   │        │  (POST /click, /eval…)  │
│  │ :8000             │   │        │          │               │
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
docker run -p 8000:8000 \
  -e API_TOKEN=my-secret-token \
  browser-helper
```

The container bundles the CDP backend. Chrome must still be running on the host with `--remote-debugging-port=9555`; use `--add-host host.docker.internal:host-gateway` on Linux to reach it.

## Use Cases

1. **AI Agent Browser Control** — Hermes (or any agent) uses the REST API instead of slow CDP-over-tunnel
2. **Web Scraping** — Extract data, take screenshots, generate PDFs at scale
3. **Automated Testing** — Script multi-step test scenarios
4. **Session Replay** — Save/restore authenticated sessions
5. **Network Debugging** — Capture and inspect network requests
6. **Remote Monitoring** — Watch browser state from the dashboard

## Test

```bash
cd tests && pytest -v
```

Current test suite: **259 tests pass, 26 skipped, 0 failures** (285 total). All source files pass `ruff check` cleanly.

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Prerequisites, install, first run |
| [API Reference](docs/api-reference.md) | Complete endpoint docs with examples |
| [Docker](docs/docker.md) | Container build and deployment |
| [Changelog](CHANGELOG.md) | Version history and release notes |
| [Workflow Example](examples/browse-workflow.py) | Complete automation pipeline demo |
| [Dashboard Demo](examples/dashboard-demo.py) | WebSocket streaming example in Python |
