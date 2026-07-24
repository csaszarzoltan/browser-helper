# API Reference

**Base URL:** `http://localhost:8000`

## Response Formats

Responses vary by endpoint:

- **Health & Scrape & Function** — JSON object
- **Content** — raw `text/html` body
- **Screenshot & PDF & Image Compress** — raw binary bytes with appropriate
  `Content-Type` header

Error responses are standard FastAPI JSON errors:

```json
{
  "detail": "url field is required"
}
```

> **Authentication:** If the `AUTH_API_KEY` environment variable is set, every
> endpoint (except `/docs`, `/redoc`, `/openapi.json`) requires the header:
> ```
> X-API-Key: your-key-here
> ```

---

## Health

### `GET /health/liveness` — Liveness probe

Always returns 200. Use this for orchestration health checks (Kubernetes,
Docker, etc.) that should never consider the server unhealthy.

```bash
curl -s http://localhost:8000/health/liveness | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok"
}
```

---

### `GET /health/readiness` — Readiness probe

Returns 200 when the Playwright browser instance is fully started and ready
to accept requests. Returns 503 while the browser is still launching.

```bash
curl -s http://localhost:8000/health/readiness | python -m json.tool
```

**Response (200):**
```json
{
  "status": "ok"
}
```

**Response (503 — browser not ready):**
```json
{
  "status": "Service Unavailable"
}
```

---

## Content

### `POST /content` — Fetch rendered HTML

Navigate to a URL and return the fully rendered HTML. Supports cookies, custom
headers, and media blocking.

**Request body:**

```json
{
  "url": "https://example.com",
  "options": {
    "wait_until": "domcontentloaded",
    "timeout": 15000,
    "block_media": false,
    "wait_after_load": 0
  },
  "cookies": [
    {"name": "session", "value": "abc123", "domain": "example.com", "path": "/"}
  ],
  "headers": {
    "User-Agent": "Mozilla/5.0 ..."
  }
}
```

| Field             | Type                  | Default              | Description                               |
|-------------------|-----------------------|----------------------|-------------------------------------------|
| `url`             | string _(required)_   | —                    | URL to navigate to                        |
| `options`         | object _(optional)_   | —                    | Navigation options (see below)            |
| `options.wait_until` | enum              | `"domcontentloaded"` | One of `domcontentloaded`, `load`, `networkidle`, `networkidle2` |
| `options.timeout` | int                   | `15000`              | Navigation timeout in ms (1000–120000)    |
| `options.block_media` | bool              | `false`              | Block images/video/audio resources        |
| `options.wait_after_load` | int          | `0`                  | Extra wait after page load, in ms (0–30000) |
| `cookies`         | array _(optional)_    | —                    | Cookies to set before navigation          |
| `cookies[].name`  | string                | —                    | Cookie name                               |
| `cookies[].value` | string                | —                    | Cookie value                              |
| `cookies[].domain`| string _(optional)_   | —                    | Cookie domain                             |
| `cookies[].path`  | string _(optional)_   | —                    | Cookie path                               |
| `headers`         | object _(optional)_   | —                    | Extra HTTP headers for the navigation     |

**Example:**

```bash
curl -s -X POST http://localhost:8000/content \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "options": {
      "timeout": 30000,
      "wait_until": "networkidle"
    }
  }' -o page.html
```

**Response:** Raw HTML body (`Content-Type: text/html`).

---

## Screenshot

### `POST /screenshot` — Capture page screenshot

Navigate to a URL and capture a screenshot. Supports PNG, JPEG, and WebP output,
including full-page capture and configurable viewport.

**Request body:**

```json
{
  "url": "https://example.com",
  "options": {
    "type": "png",
    "quality": 80,
    "full_page": false,
    "width": 1920,
    "height": 1080
  }
}
```

| Field             | Type                  | Default    | Description                               |
|-------------------|-----------------------|------------|-------------------------------------------|
| `url`             | string _(required)_   | —          | URL to capture                            |
| `options`         | object _(optional)_   | —          | Screenshot options (see below)            |
| `options.type`    | enum                  | `"png"`    | Image format: `png`, `jpeg`, `webp`       |
| `options.quality` | int                   | `80`       | JPEG/WebP quality (1–100)                 |
| `options.full_page` | bool                | `false`    | Capture full scrollable page              |
| `options.width`   | int _(optional)_      | —          | Viewport width in px (320–7680)           |
| `options.height`  | int _(optional)_      | —          | Viewport height in px (240–4320)          |

**Example — default PNG screenshot:**

```bash
curl -s -X POST http://localhost:8000/screenshot \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' \
  -o screenshot.png
```

**Example — full-page WebP with custom quality:**

```bash
curl -s -X POST http://localhost:8000/screenshot \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "options": {
      "type": "webp",
      "quality": 90,
      "full_page": true
    }
  }' -o fullpage.webp
```

**Response:** Raw image bytes (`Content-Type: image/png`, `image/jpeg`, or `image/webp`).

**Error codes:**
- `422` — Unsupported image type
- `504` — Browser unavailable or navigation timed out

---

## PDF

### `POST /pdf` — Generate PDF from URL

Navigate to a URL and convert it to PDF with configurable page format, scale,
margins, and landscape mode.

**Request body:**

```json
{
  "url": "https://example.com",
  "options": {
    "scale": 1.0,
    "print_background": true,
    "landscape": false,
    "format": "A4",
    "page_ranges": "",
    "margin": {
      "top": "0px",
      "right": "0px",
      "bottom": "0px",
      "left": "0px"
    }
  }
}
```

| Field                  | Type                  | Default       | Description                       |
|------------------------|-----------------------|---------------|-----------------------------------|
| `url`                  | string _(required)_   | —             | URL to render                     |
| `options`              | object _(optional)_   | —             | PDF options (see below)           |
| `options.scale`        | float                 | `1.0`         | Page scale (0.1–2.0)              |
| `options.print_background` | bool             | `true`        | Include background graphics       |
| `options.landscape`    | bool                  | `false`       | Landscape orientation             |
| `options.format`       | enum                  | `"A4"`        | Page size: `Letter`, `Legal`, `Tabloid`, `A0`–`A6` |
| `options.page_ranges`  | string                | `""`          | Page ranges to print (e.g. `"1-3,5"`) |
| `options.margin`       | object _(optional)_   | —             | Custom margins (all default `"0px"`) |
| `options.margin.top`   | string                | `"0px"`       | CSS length value                   |
| `options.margin.right` | string                | `"0px"`       | CSS length value                   |
| `options.margin.bottom`| string                | `"0px"`       | CSS length value                   |
| `options.margin.left`  | string                | `"0px"`       | CSS length value                   |

**Example — basic A4 PDF:**

```bash
curl -s -X POST http://localhost:8000/pdf \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' \
  -o page.pdf
```

**Example — landscape Letter with margins:**

```bash
curl -s -X POST http://localhost:8000/pdf \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "options": {
      "format": "Letter",
      "landscape": true,
      "print_background": false,
      "margin": {
        "top": "20mm",
        "right": "15mm",
        "bottom": "20mm",
        "left": "15mm"
      }
    }
  }' -o letter-landscape.pdf
```

**Response:** Raw PDF bytes (`Content-Type: application/pdf`).

**Error codes:**
- `422` — Invalid page format
- `504` — Browser unavailable or PDF generation failed

---

## Scrape

### `POST /scrape` — Extract structured data

Navigate to a URL and extract data from one or more CSS selectors. Each element
definition specifies a selector, output type (text, HTML, or attribute), an
optional attribute name, and whether to return the first match or all matches.

**Request body:**

```json
{
  "url": "https://example.com",
  "elements": [
    {
      "selector": "h1",
      "name": "title",
      "type": "text",
      "multiple": false
    },
    {
      "selector": "a",
      "name": "links",
      "type": "attribute",
      "attribute": "href",
      "multiple": true
    },
    {
      "selector": ".article-body",
      "name": "body_html",
      "type": "html",
      "multiple": false
    }
  ]
}
```

| Field       | Type                  | Default         | Description                               |
|-------------|-----------------------|-----------------|-------------------------------------------|
| `url`       | string _(required)_   | —               | URL to scrape                             |
| `elements`  | array _(required)_    | —               | Element definitions (1–50 items)          |
| `elements[].selector` | string       | —               | CSS selector to find elements             |
| `elements[].name`   | string          | —               | Key name for this result                  |
| `elements[].type`   | enum           | —               | `"text"` — innerText, `"html"` — innerHTML, `"attribute"` — attribute value |
| `elements[].attribute` | string _(optional)_ | —           | Required when `type` is `"attribute"`     |
| `elements[].multiple` | bool           | `false`         | `false` = first match, `true` = all matches |

**Example — scrape all headlines and links:**

```bash
curl -s -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "elements": [
      {"selector": "h1", "name": "title", "type": "text"},
      {"selector": "p", "name": "paragraphs", "type": "text", "multiple": true},
      {"selector": "a", "name": "links", "type": "attribute", "attribute": "href", "multiple": true}
    ]
  }' | python -m json.tool
```

**Response (200):**
```json
{
  "title": "Example Domain",
  "paragraphs": [
    "This domain is for use in illustrative examples..."
  ],
  "links": [
    "https://www.iana.org/domains/example"
  ]
}
```

**Error codes:**
- `400` — Element requires attribute name when type is `"attribute"` and no attribute given
- `422` — Elements array is empty
- `504` — Browser unavailable or scrape failed

---

## Function

### `POST /function` — Execute JavaScript

Open a blank page and execute JavaScript code in the browser context. Returns
the evaluated result. Supports any JSON-serializable return value.

**Request body:**

```json
{
  "code": "document.title",
  "context": {}
}
```

| Field    | Type                  | Default  | Description                              |
|----------|-----------------------|----------|------------------------------------------|
| `code`   | string _(required)_   | —        | JavaScript code to evaluate (1–100000 chars) |
| `context`| object _(optional)_   | —        | Context variables (reserved, not yet used) |

**Example — get page title:**

```bash
curl -s -X POST http://localhost:8000/function \
  -H "Content-Type: application/json" \
  -d '{"code": "document.title"}' \
  | python -m json.tool
```

**Example — compute in JS:**

```bash
curl -s -X POST http://localhost:8000/function \
  -H "Content-Type: application/json" \
  -d '{"code": "Math.max(...[1, 5, 3, 9, 2])"}' \
  | python -m json.tool
# → {"result": 9}
```

**Example — return an object:**

```bash
curl -s -X POST http://localhost:8000/function \
  -H "Content-Type: application/json" \
  -d '{"code": "({userAgent: navigator.userAgent, language: navigator.language})"}' \
  | python -m json.tool
```

**Response (200):**
```json
{
  "result": "Example Domain"
}
```

**Error codes:**
- `400` — Code field is required, invalid syntax, or execution error

---

## Image Compression

### `POST /image/compress` — Compress/convert/resize an image

Upload an image file and receive a compressed, converted, or resized version.
Uses Pillow for in-memory processing. Supports JPEG, PNG, and WebP formats.

**Request (multipart form-data):**

| Field           | Type                | Default   | Description                              |
|-----------------|---------------------|-----------|------------------------------------------|
| `file`          | file _(required)_   | —         | Image file (JPEG, PNG, or WebP)          |
| `format`        | query _(optional)_  | input fmt | Output format: `jpeg`, `png`, `webp`     |
| `quality`       | query               | `85`      | Compression quality (1–100)              |
| `lossless`      | query               | `false`   | Use lossless compression (WebP only)     |
| `width`         | query _(optional)_  | —         | Resize width in px (1–10000)             |
| `height`        | query _(optional)_  | —         | Resize height in px (1–10000)            |
| `strip_metadata`| query               | `true`    | Remove EXIF and other metadata           |

**Example — compress and convert to WebP:**

```bash
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@photo.jpg" \
  -F "format=webp" \
  -F "quality=80" \
  -o photo.webp
```

**Example — resize and compress JPEG:**

```bash
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@large.png" \
  -F "format=jpeg" \
  -F "quality=70" \
  -F "width=800" \
  -o resized.jpg
```

**Example — lossless WebP with metadata kept:**

```bash
curl -s -X POST http://localhost:8000/image/compress \
  -F "file=@screenshot.png" \
  -F "format=webp" \
  -F "lossless=true" \
  -F "strip_metadata=false" \
  -o lossless.webp
```

**Response (200):** Raw image bytes with headers:

```
Content-Type: image/webp
X-Original-Size: 2048000
X-Compressed-Size: 342100
X-Compression-Ratio: 5.99
X-Output-Format: webp
```

| Response Header       | Description                              |
|-----------------------|------------------------------------------|
| `X-Original-Size`     | Input file size in bytes                 |
| `X-Compressed-Size`   | Output file size in bytes                |
| `X-Compression-Ratio` | Original / compressed size ratio         |
| `X-Output-Format`     | Output image format                      |

**Error codes:**
- `400` — Unrecognised image format, unsupported input/output format, or processing error
- `413` — File exceeds `MAX_UPLOAD_SIZE_MB` limit

---

## Error Reference

| Status Code | Meaning                        |
|-------------|--------------------------------|
| 200         | Success                        |
| 400         | Bad request (invalid params)   |
| 401         | Missing or invalid API key     |
| 403         | Invalid API key                |
| 413         | Upload file too large          |
| 422         | Validation error               |
| 504         | Browser unavailable or timeout |

---

## WebSocket — Real-time Dashboard (CDP Backend)

**Endpoint:** `ws://localhost:8000/ws`

The WebSocket endpoint streams real-time state updates, CDP events, and
operation results to dashboard clients. All messages use a typed JSON envelope
with ISO-8601 UTC timestamps.

### Message Types

| Type             | Direction       | Payload Fields                                    | Description                                      |
|------------------|-----------------|---------------------------------------------------|--------------------------------------------------|
| `hello`          | Server → Client | `state`, `recent_log`                             | Initial snapshot sent immediately on connect      |
| `state_update`   | Server → Client | `state`, `recent_log`                             | Broadcast after every REST API operation          |
| `console_log`    | Server → Client | `level`, `message`                                | Browser console (via CDP `consoleAPICalled`)     |
| `navigation`     | Server → Client | `url`, `frame_id`                                 | Page navigation (via CDP `frameNavigated`)       |
| `operation`      | Server → Client | `operation`, `status`, `duration_ms`, `details`   | REST API operation result                         |
| `ping`           | Server → Client | _(none)_                                          | Heartbeat every 30 seconds                        |
| `pong`           | Client → Server | _(none)_                                          | Send `"ping"` to get a `{"type": "pong"}` reply   |
| `error`          | Server → Client | `message`, `code` (optional)                      | Error notification                                |

### State Object

```json
{
  "connected": true,
  "tabs_count": 3,
  "last_operation": "navigate",
  "last_operation_time": "2026-07-24T03:30:00.123456",
  "cdp_url": "ws://127.0.0.1:9555/devtools/page/..."
}
```

### Console Log Events

CDP `Runtime.consoleAPICalled` events forwarded as `console_log` messages:

```json
{
  "type": "console_log",
  "timestamp": "2026-07-24T03:30:00.123456",
  "level": "log",
  "message": "Hello from the browser!"
}
```

Level values: `log`, `warn`, `error`, `info`, `debug`.

### Navigation Events

CDP `Page.frameNavigated` events forwarded as `navigation` messages:

```json
{
  "type": "navigation",
  "timestamp": "2026-07-24T03:30:00.123456",
  "url": "https://example.com/page2",
  "frame_id": "ABC123..."
}
```

### Client Examples

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  switch (msg.type) {
    case 'hello':
    case 'state_update':
      console.log('Connected:', msg.state.connected, 'Tabs:', msg.state.tabs_count);
      break;
    case 'console_log':
      console.log(`[${msg.level}] ${msg.message}`);
      break;
    case 'navigation':
      console.log(`Navigated to ${msg.url}`);
      break;
  }
};
```

```python
import asyncio, json, websockets

async def listen():
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        async for raw in ws:
            msg = json.loads(raw)
            print(f"[{msg['type']}]", msg.get("state", {}).get("last_operation", ""))
            if msg.get("type") == "ping":
                await ws.send("pong")

asyncio.run(listen())
```

### GUI Dashboard

Open `http://localhost:8000` for the full dashboard. It auto-connects to `/ws`
and updates in real time with panels for connection status, operation log,
screenshots, tabs, network log, cookies, script runner, session manager,
and JS console.
