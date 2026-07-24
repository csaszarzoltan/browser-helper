# API Reference

**Base URL:** `http://localhost:8000`

**Authentication:** Set `API_TOKEN` environment variable to enable Bearer token auth on all
endpoints except `/`, `/health`, `/ready`, `/ws`, and OpenAPI docs. See [Authentication](#authentication)
for details.

## Response Format

All endpoints return JSON with a standard envelope:

```json
{
  "status": "ok",
  "operation": "navigate",
  "result": { ... }
}
```

| Field | Description |
|-------|-------------|
| `status` | `"ok"` or `"error"` |
| `operation` | The operation name (matches the endpoint) |
| `result` | Operation-specific payload |
| `error` | Error message (only present on failure) |

Error responses use FastAPI's standard JSON format:

```json
{
  "detail": "Not connected to CDP. Call POST /connect first."
}
```

---

## Authentication

By default all endpoints are open. To enable authentication, set the `API_TOKEN` environment variable:

```bash
API_TOKEN=my-secret-token python run.py
```

When set, every request to a protected endpoint must include:

```
Authorization: Bearer my-secret-token
```

Protected endpoints: all except `/`, `/health`, `/ready`, `/ws`, `/docs`, `/openapi.json`, `/redoc`.

```bash
curl -s -X POST http://localhost:8000/navigate?url=https://example.com \
  -H "Authorization: Bearer my-secret-token" | python -m json.tool
```

**401 response:**
```json
{
  "detail": "Invalid or missing API token"
}
```

---

## Health & Status

These endpoints do **not** require CDP connection and are **excluded from authentication**.

---

### `GET /health` — Server health check

Returns server uptime, memory usage, CDP connection state, and operation count.

```bash
curl -s http://localhost:8000/health | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "uptime_seconds": 1234.56,
  "memory_mb": 42.1,
  "connected": true,
  "tabs_count": 3,
  "operation_count": 27
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` when server is running |
| `version` | string | API version |
| `uptime_seconds` | float | Seconds since server start |
| `memory_mb` | float | Current RSS memory in MB |
| `connected` | bool | CDP connection status |
| `tabs_count` | int | Number of open browser tabs |
| `operation_count` | int | Total operations logged |

---

### `GET /ready` — CDP readiness probe

Returns 200 when CDP is connected, 503 otherwise. Use this for orchestration health checks.

```bash
curl -s http://localhost:8000/ready | python -m json.tool
```

**Response (200 — connected):**
```json
{
  "status": "ok",
  "ready": true,
  "connected": true
}
```

**Response (503 — not connected):**
```json
{
  "status": "error",
  "ready": false,
  "connected": false,
  "detail": "CDP not connected"
}
```

---

### `GET /status` — Connection status snapshot

```bash
curl -s http://localhost:8000/status | python -m json.tool
```

**Response (200):**
```json
{
  "connected": true,
  "tabs_count": 3,
  "last_operation": "navigate",
  "last_operation_time": "2026-07-24T04:50:00.123456+00:00",
  "cdp_url": "ws://127.0.0.1:9555/devtools/browser/abc123",
  "log_size": 42
}
```

---

## Connection

### `POST /connect` — Connect to Chrome CDP

Auto-discovers the CDP endpoint (via `http://127.0.0.1:9555/json`) or uses an explicit URL.

```bash
# Auto-discover
curl -s -X POST http://localhost:8000/connect | python -m json.tool

# Explicit CDP URL
curl -s -X POST http://localhost:8000/connect \
  -H "Content-Type: application/json" \
  -d '{"cdp_url": "ws://127.0.0.1:9222/devtools/browser/abc123"}' | python -m json.tool
```

**Request body (optional):**
```json
{
  "cdp_url": "ws://..."
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cdp_url` | string | auto-discover | Explicit CDP WebSocket URL |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "connect",
  "result": {
    "target_id": "ABC...",
    "title": "about:blank",
    "url": "about:blank",
    "tabs_count": 1,
    "cdp_url": "ws://127.0.0.1:9555/devtools/browser/abc123"
  }
}
```

> The server also **auto-connects** on startup via the lifespan handler. You only need
> to call `/connect` explicitly if the auto-connect failed or you want to reconnect
> to a different CDP endpoint.

---

### `POST /disconnect` — Disconnect from CDP

```bash
curl -s -X POST http://localhost:8000/disconnect | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "disconnect",
  "result": { "status": "disconnected" }
}
```

---

## Navigation

### `POST /navigate` — Navigate to a URL

Navigates the current tab to the specified URL. Invalidates tab cache.

```bash
curl -s -X POST "http://localhost:8000/navigate?url=https://example.com" | python -m json.tool
```

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | yes | Target URL to navigate to |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "navigate",
  "result": {
    "frame_id": "ABC123DEF456...",
    "url": "https://example.com"
  }
}
```

---

## JavaScript Execution

### `POST /eval` — Execute JavaScript

Runs JavaScript in the current page context and returns the result.

```bash
curl -s -X POST http://localhost:8000/eval \
  -H "Content-Type: application/json" \
  -d '{"js": "document.title"}' | python -m json.tool
```

**Request body:**
```json
{
  "js": "document.title"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `js` | string | yes | JavaScript expression to evaluate |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "eval",
  "result": {
    "result": "Example Domain",
    "type": "string"
  }
}
```

**Example — compute in JS:**
```bash
curl -s -X POST http://localhost:8000/eval \
  -H "Content-Type: application/json" \
  -d '{"js": "Math.max(...[1, 5, 3, 9, 2])"}' | python -m json.tool
# → { "result": 9, "type": "number" }
```

**Example — return object:**
```bash
curl -s -X POST http://localhost:8000/eval \
  -H "Content-Type: application/json" \
  -d '{"js": "({userAgent: navigator.userAgent, language: navigator.language})"}' | python -m json.tool
```

---

## Element Interaction

### `POST /click` — Click element by CSS selector

```bash
curl -s -X POST http://localhost:8000/click \
  -H "Content-Type: application/json" \
  -d '{"selector": "#submit-btn"}' | python -m json.tool
```

**Request body:**
```json
{
  "selector": "#submit-btn"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `selector` | string | yes | CSS selector for the target element |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "click",
  "result": { "status": "clicked" }
}
```

---

### `POST /type` — Type text into a form field

```bash
curl -s -X POST http://localhost:8000/type \
  -H "Content-Type: application/json" \
  -d '{"selector": "#search-input", "text": "browser automation"}' | python -m json.tool
```

**Request body:**
```json
{
  "selector": "#search-input",
  "text": "browser automation"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `selector` | string | yes | CSS selector for the input element |
| `text` | string | yes | Text to type into the field |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "type",
  "result": { "status": "typed" }
}
```

---

## Content Extraction

### `POST /get_text` — Get visible page text

Returns the visible text content of the current page (equivalent to `document.body.innerText`).

```bash
curl -s -X POST http://localhost:8000/get_text | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "get_text",
  "result": {
    "text": "Example Domain\n\nThis domain is for use in illustrative examples...",
    "length": 1234
  }
}
```

---

### `POST /dom_query` — Query DOM elements by CSS selector

Extract text content or a specific attribute from elements matching a CSS selector.

```bash
curl -s -X POST http://localhost:8000/dom_query \
  -H "Content-Type: application/json" \
  -d '{"selector": "a", "attribute": "href"}' | python -m json.tool
```

**Request body:**
```json
{
  "selector": "a",
  "attribute": "href"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `selector` | string | yes | — | CSS selector to match elements |
| `attribute` | string | no | `null` (returns text content) | Attribute name to extract (e.g. `"href"`, `"src"`) |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "dom_query",
  "result": {
    "items": [
      "https://www.iana.org/domains/example",
      "https://www.iana.org/domains/reserved"
    ],
    "count": 2
  }
}
```

When `attribute` is omitted, returns text content of each matched element. When
`attribute` is provided, returns the attribute value.

---

### `POST /dom_click_all` — Click all matching elements

Clicks every element matching a CSS selector. Useful for "Load more" buttons or
expand-all patterns.

```bash
curl -s -X POST http://localhost:8000/dom_click_all \
  -H "Content-Type: application/json" \
  -d '{"selector": ".load-more"}' | python -m json.tool
```

**Request body:**
```json
{
  "selector": ".load-more"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `selector` | string | yes | CSS selector for elements to click |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "dom_click_all",
  "result": {
    "clicked": 3,
    "details": "Clicked 3 elements matching '.load-more'"
  }
}
```

---

## Screenshots

### `POST /screenshot` — Viewport screenshot

Captures the current viewport as a base64-encoded JPEG (quality 70).

```bash
curl -s -X POST http://localhost:8000/screenshot | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "screenshot",
  "result": {
    "data": "/9j/4AAQSkZJRg...",
    "format": "jpeg",
    "size": 123456,
    "width": 1920,
    "height": 1080
  }
}
```

| Result Field | Type | Description |
|--------------|------|-------------|
| `data` | string | Base64-encoded JPEG image data |
| `format` | string | Image format (`"jpeg"`) |
| `size` | int | Byte size of the decoded image |
| `width` | int | Image width in pixels |
| `height` | int | Image height in pixels |

---

### `POST /full_screenshot` — Full-page screenshot

Captures the entire scrollable page, not just the viewport.

```bash
curl -s -X POST http://localhost:8000/full_screenshot \
  -H "Content-Type: application/json" \
  -d '{"quality": 80}' | python -m json.tool
```

**Request body (optional):**
```json
{
  "quality": 80
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `quality` | int | `70` | JPEG quality (1–100) |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "full_screenshot",
  "result": {
    "data": "/9j/4AAQSkZJRg...",
    "format": "jpeg",
    "size": 456789,
    "height": 5432
  }
}
```

---

### `POST /element_screenshot` — Element screenshot

Captures a screenshot of a specific DOM element.

```bash
curl -s -X POST http://localhost:8000/element_screenshot \
  -H "Content-Type: application/json" \
  -d '{"selector": "#main-content", "quality": 90}' | python -m json.tool
```

**Request body:**
```json
{
  "selector": "#main-content",
  "quality": 90
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `selector` | string | yes | — | CSS selector for the target element |
| `quality` | int | no | `80` | JPEG quality (1–100) |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "element_screenshot",
  "result": {
    "data": "/9j/4AAQSkZJRg...",
    "format": "jpeg",
    "size": 34567
  }
}
```

---

## PDF Export

### `POST /pdf` — Generate PDF of current page

Converts the current page to PDF with configurable options.

```bash
curl -s -X POST http://localhost:8000/pdf \
  -H "Content-Type: application/json" \
  -d '{}' | python -m json.tool
```

**Request body (optional):**
```json
{
  "options": {
    "landscape": true,
    "printBackground": true,
    "paperWidth": 8.27,
    "paperHeight": 11.69,
    "marginTop": 0,
    "marginBottom": 0,
    "marginLeft": 0,
    "marginRight": 0,
    "scale": 1.0
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `options` | object | `{}` | PDF configuration |
| `options.landscape` | bool | `false` | Landscape orientation |
| `options.printBackground` | bool | `true` | Include background graphics |
| `options.paperWidth` | float | `8.27` | Paper width in inches (A4) |
| `options.paperHeight` | float | `11.69` | Paper height in inches (A4) |
| `options.marginTop` | float | `0` | Top margin in inches |
| `options.marginBottom` | float | `0` | Bottom margin in inches |
| `options.marginLeft` | float | `0` | Left margin in inches |
| `options.marginRight` | float | `0` | Right margin in inches |
| `options.scale` | float | `1.0` | Page scale (0.1–2.0) |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "pdf",
  "result": {
    "data": "JVBERi0xLjc...",
    "format": "pdf",
    "size": 78901
  }
}
```

---

## Tab Management

### `GET /tabs` — List all open tabs

```bash
curl -s http://localhost:8000/tabs | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "get_tabs",
  "result": [
    {
      "id": "ABC123...",
      "title": "Example Domain",
      "url": "https://example.com",
      "active": true
    },
    {
      "id": "DEF456...",
      "title": "about:blank",
      "url": "about:blank",
      "active": false
    }
  ]
}
```

---

### `POST /tabs/scan` — Scan all tabs (no switch needed)

Opens a temporary CDP connection to each tab, extracts title/URL/text, and returns
everything in one response — **without switching the active tab**.

```bash
curl -s -X POST http://localhost:8000/tabs/scan | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "scan_all_tabs",
  "result": {
    "tabs": [
      {
        "id": "ABC123...",
        "title": "Example Domain",
        "url": "https://example.com",
        "text": "Example Domain\n\nThis domain is for use...",
        "text_length": 123
      }
    ],
    "count": 1
  }
}
```

---

### `POST /tab/new` — Open a new tab

```bash
# Open blank tab
curl -s -X POST http://localhost:8000/tab/new | python -m json.tool

# Open tab to a URL
curl -s -X POST http://localhost:8000/tab/new \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' | python -m json.tool
```

**Request body (optional):**
```json
{
  "url": "https://example.com"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | `"about:blank"` | URL to open in the new tab |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "open_new_tab",
  "result": {
    "target_id": "NEW_ABC...",
    "status": "tab_created"
  }
}
```

---

### `POST /tab/close/{tab_id}` — Close a tab

```bash
curl -s -X POST "http://localhost:8000/tab/close/ABC123..." | python -m json.tool
```

**Path parameter:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tab_id` | string | Target ID of the tab to close (from `GET /tabs`) |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "close_tab",
  "result": { "status": "tab_closed" }
}
```

---

### `POST /switch_tab/{tab_id}` — Switch active tab

Switches the active CDP context to the specified tab.

```bash
curl -s -X POST "http://localhost:8000/switch_tab/DEF456..." | python -m json.tool
```

**Path parameter:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tab_id` | string | Target ID of the tab to switch to |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "switch_tab",
  "result": {
    "title": "Example Domain",
    "url": "https://example.com"
  }
}
```

---

## Cookie Management

### `GET /cookies` — Get all cookies

```bash
# All cookies
curl -s http://localhost:8000/cookies | python -m json.tool

# Truncate long values to save bandwidth
curl -s "http://localhost:8000/cookies?truncate=true" | python -m json.tool
```

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `truncate` | bool | `false` | Truncate values >80 chars to save bandwidth |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "get_cookies",
  "result": {
    "cookies": [
      {
        "name": "session_id",
        "value": "abc123...",
        "domain": "example.com",
        "path": "/",
        "secure": true,
        "httpOnly": true
      }
    ]
  }
}
```

---

### `POST /set_cookie` — Set a cookie

```bash
curl -s -X POST http://localhost:8000/set_cookie \
  -H "Content-Type: application/json" \
  -d '{"name": "session_id", "value": "abc123", "domain": "example.com"}' | python -m json.tool
```

**Request body:**
```json
{
  "name": "session_id",
  "value": "abc123",
  "domain": "example.com",
  "path": "/",
  "secure": false,
  "httpOnly": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | yes | — | Cookie name |
| `value` | string | yes | — | Cookie value |
| `domain` | string | no | current page | Cookie domain |
| `path` | string | no | `"/"` | Cookie path |
| `secure` | bool | no | `false` | Secure flag |
| `httpOnly` | bool | no | `false` | HTTP-only flag |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "set_cookie",
  "result": { "status": "cookie_set" }
}
```

---

### `POST /clear_cookies` — Clear all cookies

```bash
curl -s -X POST http://localhost:8000/clear_cookies | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "clear_cookies",
  "result": { "status": "cookies_cleared" }
}
```

---

## Network Monitoring

### `POST /network/start` — Start capturing network requests

```bash
curl -s -X POST http://localhost:8000/network/start | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "network_start",
  "result": { "status": "network_monitoring_started" }
}
```

---

### `POST /network/stop` — Stop network monitoring

```bash
curl -s -X POST http://localhost:8000/network/stop | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "network_stop",
  "result": { "status": "network_monitoring_stopped" }
}
```

---

### `GET /network/log` — Get captured network log

```bash
curl -s http://localhost:8000/network/log | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "network_log",
  "result": {
    "entries": [
      {
        "url": "https://example.com",
        "method": "GET",
        "status": 200,
        "type": "Document",
        "size": 1256,
        "duration_ms": 45.2,
        "timestamp": "2026-07-24T04:50:00.123Z"
      }
    ],
    "count": 1
  }
}
```

---

### `POST /network/clear` — Clear network log

```bash
curl -s -X POST http://localhost:8000/network/clear | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "network_clear",
  "result": { "status": "network_log_cleared" }
}
```

---

## Session Management

### `POST /session/save` — Save browser session

Saves cookies, localStorage, and sessionStorage from the current page context.

```bash
curl -s -X POST http://localhost:8000/session/save | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "session_save",
  "result": {
    "session": {
      "cookies": [...],
      "localStorage": { "key": "value" },
      "sessionStorage": {},
      "url": "https://example.com"
    }
  }
}
```

Save the `session` object and pass it back to `/session/restore`.

---

### `POST /session/restore` — Restore browser session

Restores cookies, localStorage, and sessionStorage from a previously saved session.

```bash
curl -s -X POST http://localhost:8000/session/restore \
  -H "Content-Type: application/json" \
  -d '{"session": {"cookies": [...], "localStorage": {}, "sessionStorage": {}, "url": "https://example.com"}}' | python -m json.tool
```

**Request body:**
```json
{
  "session": {
    "cookies": [...],
    "localStorage": { ... },
    "sessionStorage": { ... },
    "url": "https://example.com"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session` | object | yes | Session object from `/session/save` |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "session_restore",
  "result": { "status": "session_restored" }
}
```

---

## Batch Scripts

### `POST /script` — Execute multi-step script

Executes a sequence of browser operations sequentially.

**Supported actions:** `navigate`, `click`, `type`, `eval`, `screenshot`,
`full_page_screenshot`, `element_screenshot`, `wait`, `scroll`, `get_text`, `pdf`.

```bash
curl -s -X POST http://localhost:8000/script \
  -H "Content-Type: application/json" \
  -d '{
    "steps": [
      {"action": "navigate", "params": {"url": "https://example.com"}},
      {"action": "eval", "params": {"js": "document.title"}},
      {"action": "screenshot", "params": {}}
    ]
  }' | python -m json.tool
```

**Request body:**
```json
{
  "steps": [
    {"action": "navigate", "params": {"url": "https://example.com"}},
    {"action": "click", "params": {"selector": "#btn"}},
    {"action": "type", "params": {"selector": "#input", "text": "hello"}}
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `steps` | array | yes | Ordered operations (1–N items) |
| `steps[].action` | string | yes | Action name (see supported list) |
| `steps[].params` | object | varies | Action-specific parameters |

**Response (200):**
```json
{
  "status": "ok",
  "operation": "execute_script",
  "result": {
    "steps_executed": 3,
    "results": [
      {"step": 0, "action": "navigate", "status": "ok", "result": {...}},
      {"step": 1, "action": "eval", "status": "ok", "result": {...}},
      {"step": 2, "action": "screenshot", "status": "ok", "result": {...}}
    ]
  }
}
```

---

## JavaScript Toggle

### `POST /javascript/disable` — Disable JavaScript

Disables JavaScript execution on the current page (useful for faster page loads
on content-heavy sites).

```bash
curl -s -X POST http://localhost:8000/javascript/disable | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "disable_javascript",
  "result": { "status": "javascript_disabled" }
}
```

---

### `POST /javascript/enable` — Re-enable JavaScript

```bash
curl -s -X POST http://localhost:8000/javascript/enable | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "enable_javascript",
  "result": { "status": "javascript_enabled" }
}
```

---

## Performance Metrics

### `GET /metrics` — Page performance metrics

Returns performance timing, memory usage, and other page metrics.

```bash
curl -s http://localhost:8000/metrics | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok",
  "operation": "get_performance_metrics",
  "result": {
    "timing": {
      "domContentLoaded": 1234.5,
      "load": 2345.6,
      "firstPaint": 500.2
    },
    "memory": {
      "usedJSHeapSize": 45600000,
      "totalJSHeapSize": 60000000
    },
    "metrics": {
      "timestamp": 1234567890.123,
      "documents": 1,
      "jsEventListeners": 15,
      "nodes": 245,
      "layoutCount": 8,
      "recalcStyleCount": 12
    }
  }
}
```

---

## WebSocket Endpoint

### `GET /ws` — Real-time event stream (WebSocket upgrade)

Connects to the WebSocket endpoint for live browser events and state updates.

**Connection:**

```javascript
// JavaScript (browser)
const ws = new WebSocket("ws://localhost:8000/ws");

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log("WS message:", msg.type, msg);
};
```

```python
# Python (websockets library)
import asyncio
import websockets

async def listen():
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        async for raw in ws:
            msg = json.loads(raw)
            print(f"Received: {msg['type']}")
```

### Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `hello` | server → client | Sent immediately on connect. Contains current state + recent log |
| `state_update` | server → client | Broadcast on every REST operation. Updated state + recent log |
| `console_log` | server → client | CDP `Runtime.consoleAPICalled` event forwarded |
| `navigation` | server → client | CDP `Page.frameNavigated` event forwarded |
| `operation` | server → client | Operation completion (with duration, status) |
| `ping` | server → client | Heartbeat (client should reply with `"ping"` plain text) |
| `pong` | server → client | Heartbeat acknowledgement |
| `error` | server → client | Error message |
| `status` | client → server | Request current status (send `{"action": "status"}`) |
| `screenshot` | client → server | Take screenshot (send `{"action": "screenshot", "quality": 80}`) |
| `eval` | client → server | Execute JS (send `{"action": "eval", "js": "..."}`) |
| `navigate` | client → server | Navigate to URL (send `{"action": "navigate", "url": "..."}`) |
| `click` | client → server | Click element (send `{"action": "click", "selector": "..."}`) |
| `get_text` | client → server | Get page text (send `{"action": "get_text"}`) |
| `get_cookies` | client → server | Get cookies (send `{"action": "get_cookies", "truncate": false}`) |
| `batch` | client → server | Execute multiple steps (send `{"action": "batch", "steps": [...]}`) |

### Client heartbeat

Send plain text `"ping"` to keep the connection alive. The server responds with
`{"type": "pong"}`. Stale clients are pruned after 3 missed heartbeats.

```json
// Client sends:
"ping"

// Server responds:
{"type": "pong"}
```

### Example: hello message (server → client on connect)

```json
{
  "type": "hello",
  "state": {
    "connected": true,
    "tabs_count": 3,
    "last_operation": null,
    "last_operation_time": null,
    "cdp_url": "ws://127.0.0.1:9555/devtools/browser/abc123"
  },
  "recent_log": []
}
```

### Example: state_update (server → client after an operation)

```json
{
  "type": "state_update",
  "state": {
    "connected": true,
    "tabs_count": 3,
    "last_operation": "navigate",
    "last_operation_time": "2026-07-24T04:50:00.123456+00:00",
    "cdp_url": "ws://127.0.0.1:9555/devtools/browser/abc123"
  },
  "recent_log": [
    {
      "timestamp": "2026-07-24T04:50:00.123456+00:00",
      "operation": "navigate",
      "status": "success",
      "duration_ms": 234.56,
      "details": "{'frame_id': 'ABC...', 'url': 'https://example.com'}"
    }
  ]
}
```

---

## Error Codes

| Status Code | Meaning |
|-------------|---------|
| `400` | Not connected to CDP (operation requires connection) |
| `401` | Invalid or missing API token |
| `422` | Request validation error (missing or invalid fields) |
| `500` | Internal server error |
| `503` | CDP not connected (returned by `/ready` when not connected) |

---

## Response Header Reference (Custom)

Non-streaming responses include GZip compression (for payloads ≥500 bytes) reducing
JSON response size by 70–80%. No custom headers are added by the API itself.
