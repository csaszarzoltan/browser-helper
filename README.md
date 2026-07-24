# Browser Helper 🦎

Remote Chrome control proxy — connects to your local Chrome via CDP and exposes a fast REST API + WebSocket GUI dashboard.

## Why?

**The Problem:** Hermes AI agent (on a remote server) needs to control Chrome on your Windows machine through an SSH tunnel. Standard CDP tools (snapshot, vision) send megabytes over the tunnel — every operation takes seconds.

**The Solution:** A lightweight Python proxy running on YOUR Windows machine. It connects directly to Chrome via local CDP (instant), exposes a tiny REST API. Hermes sends compact JSON commands over the tunnel (`POST /click {"selector": ".btn"}`) and gets compact JSON responses back. **10-50x faster** than raw CDP over tunnel.

## Features

### Core
| Feature | Endpoint | Description |
|---------|----------|-------------|
| 🚀 Navigate | `POST /navigate` | Go to any URL |
| 💻 JavaScript | `POST /eval` | Execute JS and get result |
| 🖱 Click | `POST /click` | Click element by CSS selector |
| ⌨️ Type | `POST /type` | Type text into form fields |
| 📸 Screenshot | `POST /screenshot` | Viewport JPEG (quality configurable) |
| 📖 Get Text | `POST /get_text` | Extract visible text content |

### 🆕 Advanced Features
| Feature | Endpoint | Description |
|---------|----------|-------------|
| 📄 Full Page Screenshot | `POST /full_screenshot` | Capture entire scrollable page |
| 🔍 Element Screenshot | `POST /element_screenshot` | Screenshot specific element by selector |
| 📑 PDF Export | `POST /pdf` | Save page as PDF with options |
| 🍪 Cookies | `GET /cookies`, `POST /set_cookie`, `POST /clear_cookies` | Full cookie management |
| 📊 DOM Query | `POST /dom_query` | Extract data from elements by CSS selector |
| 📡 Network Monitor | `POST /network/start`, `GET /network/log` | Capture all network requests |
| 📋 Batch Script | `POST /script` | Multi-step automation scripts |
| 💾 Session | `POST /session/save`, `POST /session/restore` | Save/restore cookies + localStorage |
| 📈 Performance | `GET /metrics` | Page performance metrics |
| 🏥 Health | `GET /health` | Server health check with uptime |
| 🔐 Auth | — | Optional Bearer token auth |
| 🗂 Tab Management | `GET /tabs`, `POST /tab/new`, `POST /tab/close/{id}`, `POST /switch_tab/{id}` | Full tab control |
| ⚡ JS Toggle | `POST /javascript/disable`, `/javascript/enable` | Disable/enable JS |

## GUI Dashboard

![Dashboard](https://via.placeholder.com/800x500/1a1a2e/00ff88?text=Browser+Helper+Dashboard)

Open `http://localhost:8000` in any browser to see:
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

```bash
# Install
pip install fastapi uvicorn websockets httpx Pillow

# Run (Chrome must be running with --remote-debugging-port=9555)
uvicorn src.main:app --host 0.0.0.0 --port 8000

# Open dashboard
open http://localhost:8000

# Optional: protect with API token
API_TOKEN=my-secret-token uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## API Authentication

Set `API_TOKEN` environment variable to enable Bearer token auth:

```bash
API_TOKEN=my-secret-token python -m uvicorn src.main:app ...
```

All endpoints (except `/` and `/ws`) require:
```
Authorization: Bearer my-secret-token
```

## Architecture

```
Windows (user)                    Linux (Hermes server)
┌─────────────────────┐          ┌─────────────────────┐
│ Chrome ←─port:9555──┤          │       Hermes        │
│        CDP          │  tunnel  │         │            │
│ Browser-Helper:8000 │◄────────►│ REST API calls      │
│ ┌──────────────┐    │          │ (small JSON, fast)  │
│ │ FastAPI API   │    │          │                     │
│ │ + WebSocket   │    │          │  browser_cdp        │
│ │ + GUI dashb.  │    │          │  tools (fallback)   │
│ └──────────────┘    │          │                     │
└─────────────────────┘          └─────────────────────┘
```

## Container

```bash
docker build -t browser-helper .
docker run -p 8000:8000 browser-helper
```

## Use Cases

1. **AI Agent Browser Control** — Hermes (or any agent) uses the REST API instead of slow CDP-over-tunnel
2. **Web Scraping** — Extract data, take screenshots, generate PDFs at scale
3. **Automated Testing** — Script multi-step test scenarios
4. **Session Replay** — Save/restore authenticated sessions
5. **Network Debugging** — Capture and inspect network requests
6. **Remote Monitoring** — Watch browser state from the dashboard

## Test

```bash
cd tests && pytest test_core.py -v
```
