# Getting Started

## Prerequisites

- **Python 3.10+** installed on your system
- **Chrome/Chromium** running with `--remote-debugging-port=9555`
- The browser-helper server must be on the same machine as Chrome (or reachable via SSH tunnel)

> The CDP backend connects to an existing Chrome instance — no separate browser binary needed.

---

## Installation

### From source (recommended)

```bash
git clone <repo-url>
cd browser-helper

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install fastapi uvicorn websockets httpx Pillow
```

### Quick install (no virtualenv)

```bash
pip install fastapi uvicorn websockets httpx Pillow
```

---

## First Run

### 1. Start Chrome with remote debugging

```bash
# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9555

# Linux
google-chrome --remote-debugging-port=9555

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9555
```

### 2. Start Browser Helper

```bash
# Recommended — handles import path automatically
python run.py

# Or with custom port
python run.py --port 8000
```

The server **auto-connects** to Chrome CDP on startup via the lifespan handler.
If Chrome isn't running yet, the server starts anyway and you can connect later
via `POST /connect`.

### 3. Connect and start browsing

```bash
# Check server is alive
curl -s http://localhost:8000/health | python -m json.tool

# Navigate to a page
curl -s -X POST "http://localhost:8000/navigate?url=https://example.com" | python -m json.tool

# Get visible page text
curl -s -X POST http://localhost:8000/get_text | python -m json.tool

# Take a screenshot
curl -s -X POST http://localhost:8000/screenshot | python -m json.tool

# Run JavaScript
curl -s -X POST http://localhost:8000/eval \
  -H "Content-Type: application/json" \
  -d '{"js": "document.title"}' | python -m json.tool

# Click an element
curl -s -X POST http://localhost:8000/click \
  -H "Content-Type: application/json" \
  -d '{"selector": "a"}' | python -m json.tool
```

Open **http://localhost:8000** in any browser to see the real-time GUI dashboard.

---

## What's Next

- Browse the **[API Reference](api-reference.md)** for all available endpoints
- Use **[Docker](docker.md)** for containerised deployment
- Explore the **[Workflow Example](../examples/browse-workflow.py)** for a complete automation pipeline
- Try the **[Dashboard Demo](../examples/dashboard-demo.py)** for real-time WebSocket streaming
