# browser-helper

Remote Chrome control proxy via CDP — Hermes skill for browser automation. Provides a REST API to control a headless or headed Chrome browser through Chrome DevTools Protocol (CDP), with support for navigation, interaction, form operations, page analysis, screenshots, tab management, cookies, network monitoring, profiles, and headless sessions.

## Trigger

Use when you need to control a Chrome browser programmatically — navigate, click, type, extract page content, manage tabs, take screenshots, fill forms, or automate any web interaction at scale.

## LLM Agent API (v1.0)

Prefer this compact interface for LLM tool use:

- `GET /agent/capabilities` discovers supported actions and observation features.
- `POST /agent/observe` returns token-budgeted observations, stable `snapshot_id` and `element_id` references, cursor pagination, and optional differential state.
- `POST /agent/act` performs high-level navigate, click, fill, select, wait, evaluate, capture, and workflow actions.
- `GET /artifacts/{artifact_id}` downloads screenshot artifacts.

All new endpoints use the `browser-helper-envelope-v1` response shape. Errors use non-2xx HTTP status codes. Headless evaluation uses `Runtime.evaluate`; headless screenshots use `Page.captureScreenshot` and return artifact metadata. See `docs/agent-api.md` for request examples and stale-snapshot behavior.

## Setup

### Prerequisites

- Chrome/Chromium installed on the target machine
- Python 3.10+ with FastAPI dependencies
- CDP enabled on Chrome (`--remote-debugging-port=9222` or auto-launched)

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | HTTP server port |
| `API_TOKEN` | `""` (disabled) | Bearer token for API auth |
| `CDP_PORT` | `9222` | Chrome DevTools Protocol debug port |
| `CHROME_PATH` | platform-default | Path to Chrome binary |
| `HEADLESS` | `false` | Run headless by default |

### SSH Tunnel Setup

When Chrome runs on a remote machine, set up an SSH tunnel:

```bash
ssh -L 9222:localhost:9222 user@remote-host
```

Then configure the API to connect via `POST /connect` with `{"cdp_url": "http://localhost:9222"}`.

### Starting the API Server

```bash
# From the browser-helper directory
python run.py --port 8000

# Or directly via uvicorn
cd src && uvicorn main:app --host 0.0.0.0 --port 8000
```

### Testing Connectivity

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

### API Token Configuration

Set `API_TOKEN` environment variable to enable authentication:

```bash
export API_TOKEN="your-secret-token"
python run.py --port 8000
```

Then include the token in all requests:

```bash
curl -s -H "Authorization: Bearer your-secret-token" http://localhost:8000/health
```

## Endpoints

### Connection

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/connect` | Establish CDP connection to Chrome |
| `POST` | `/disconnect` | Close CDP connection and clean up |
| `GET` | `/status` | Current connection status |
| `GET` | `/health` | Health check (no auth required) |
| `GET` | `/ready` | Readiness check (no auth required) |

#### POST /connect

Establish a CDP link to a Chrome instance. If no `cdp_url` is provided, the service auto-discovers Chrome or launches one.

**Request body:**
```json
{
  "cdp_url": "http://localhost:9222"
}
```

*Fields:* `cdp_url` (string, optional) — CDP endpoint URL. If omitted, auto-launches or discovers Chrome.

**Response:**
```json
{
  "status": "ok",
  "operation": "connect",
  "result": {
    "connected": true,
    "tabs_count": 1,
    "cdp_url": "http://localhost:9222"
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/connect \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"cdp_url": "http://localhost:9222"}' | python3 -m json.tool
```

#### POST /disconnect

Close the CDP connection and release resources.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "disconnect",
  "result": {"connected": false}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/disconnect \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### GET /status

Return current connection status, tab count, last operation, and CDP URL.

**Response:**
```json
{
  "status": "ok",
  "connected": true,
  "tabs_count": 3,
  "last_operation": "navigate",
  "cdp_url": "http://localhost:9222"
}
```

**Example:**
```bash
curl -s http://localhost:8000/status \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### GET /health

Simple health check endpoint — no authentication required.

**Response:**
```json
{
  "status": "ok",
  "service": "browser-helper"
}
```

**Example:**
```bash
curl -s http://localhost:8000/health
```

#### GET /ready

Readiness check — returns whether CDP is connected and operational.

**Response:**
```json
{
  "status": "ok",
  "ready": true,
  "connected": true,
  "tabs_count": 1
}
```

**Example:**
```bash
curl -s http://localhost:8000/ready
```

---

### Navigation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/navigate` | Navigate the active tab to a URL |

#### POST /navigate

Navigate to a URL in the current active tab. Waits for page load to complete.

**Query parameters:** `url` (string, required) — the URL to navigate to.

**Response:**
```json
{
  "status": "ok",
  "operation": "navigate",
  "result": {
    "url": "https://example.com",
    "title": "Example Domain",
    "status": "loaded"
  }
}
```

**Example:**
```bash
curl -s -X POST "http://localhost:8000/navigate?url=https://example.com" \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### Interaction

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/click` | Click element by CSS selector |
| `POST` | `/click/text` | Click element by visible text content |
| `POST` | `/click/label` | Click `<label>` element by visible text |
| `POST` | `/click/label/text` | Alias for `/click/label` **NEW v0.8** |
| `POST` | `/click/coordinates` | Click at specified pixel coordinates **NEW v0.8** |
| `POST` | `/type` | Type text into an input field |

#### POST /click

Click an element identified by CSS selector.

**Request body:**
```json
{
  "selector": "#submit-btn"
}
```

*Fields:* `selector` (string, required) — CSS selector for the target element.

**Response:**
```json
{
  "status": "ok",
  "operation": "click",
  "result": {
    "selector": "#submit-btn",
    "tag": "button",
    "text": "Submit",
    "clicked": true
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/click \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"selector": "#submit-btn"}' | python3 -m json.tool
```

#### POST /click/text

Click the first element containing the specified visible text.

**Request body:**
```json
{
  "text": "Submit",
  "timeout": 5,
  "container_selector": null,
  "nth": 0
}
```

*Fields:*
- `text` (string, required) — visible text to search for
- `timeout` (integer, optional, default `5`) — seconds to wait for element
- `container_selector` (string, optional) — scope search to a container
- `nth` (integer, optional, default `0`) — which match to click (0-based)

**Response:**
```json
{
  "status": "ok",
  "operation": "click/text",
  "result": {
    "text": "Submit",
    "tag": "button",
    "selector": "button:contains('Submit')",
    "clicked": true
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/click/text \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"text": "Submit", "timeout": 5}' | python3 -m json.tool
```

#### POST /click/label

Click a `<label>` element by its visible text, which in turn activates the associated form control.

**Request body:**
```json
{
  "text": "Email",
  "timeout": 5
}
```

*Fields:*
- `text` (string, required) — the text of the label to click
- `timeout` (integer, optional, default `5`) — seconds to wait

**Response:**
```json
{
  "status": "ok",
  "operation": "click/label",
  "result": {
    "text": "Email",
    "tag": "label",
    "clicked": true
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/click/label \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"text": "Email", "timeout": 5}' | python3 -m json.tool
```

#### POST /click/coordinates

Click at specified pixel coordinates on the page. Useful for canvas, SVG, video elements, or when CDP provides coordinates but no stable CSS selector.

**Request body:**
```json
{
  "x": 450,
  "y": 320,
  "button": "left",
  "click_count": 1
}
```

*Fields:*
- `x` (integer, required) — horizontal pixel coordinate
- `y` (integer, required) — vertical pixel coordinate
- `button` (string, optional, default `"left"`) — mouse button: `"left"`, `"right"`, `"middle"`
- `click_count` (integer, optional, default `1`) — number of clicks (e.g., `2` for double-click)

**Response:**
```json
{
  "status": "ok",
  "operation": "click/coordinates",
  "result": {
    "x": 450,
    "y": 320,
    "button": "left",
    "click_count": 1
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/click/coordinates \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"x": 450, "y": 320}' | python3 -m json.tool
```

#### POST /type

Type text into an input field identified by CSS selector.

**Request body:**
```json
{
  "selector": "#email",
  "text": "user@example.com"
}
```

*Fields:*
- `selector` (string, required) — CSS selector of the input field
- `text` (string, required) — text to type

**Response:**
```json
{
  "status": "ok",
  "operation": "type",
  "result": {
    "selector": "#email",
    "text_length": 16
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/type \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"selector": "#email", "text": "user@example.com"}' | python3 -m json.tool
```

---

### Form Operations

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/form/fill` | Fill multiple form fields by label, CSS selector, or placeholder **v1.1 enhanced** |
| `POST` | `/form/select` | Select an option from a dropdown |
| `POST` | `/form/select/by-label` | Alias for `/form/select` with `by=label` **NEW v0.8** |
| `POST` | `/dropdown/select` | Simplified dropdown selection by label **NEW v0.8** |
| `POST` | `/checkbox/select` | Check a checkbox/radio by label |
| `POST` | `/checkbox/deselect` | Uncheck a checkbox/radio by label |

#### POST /form/fill

Fill one or more form fields. Each field can be identified by:
- **label** — finds `<label>`, placeholder, name, or aria-label containing the text (smart lookup)
- **selector** — direct CSS selector (fastest, e.g. `#email`, `.title-input`)
- **placeholder** — exact placeholder attribute match (e.g. `Enter title`)
- **nth** — 0-based index when multiple fields match the label (default `0`)

**Request body:**
```json
{
  "fields": [
    {"label": "Email", "value": "user@example.com"},
    {"selector": "#password", "value": "s3cret"},
    {"placeholder": "Enter title", "value": "My Project"},
    {"label": "Name", "value": "Zoltan", "nth": 2}
  ],
  "timeout": 5
}
```

*Fields:*
- `fields` (array of objects, required) — each object may contain:
  - `value` (string, required) — value to type into the field
  - `label` (string, optional) — smart lookup by label text
  - `selector` (string, optional) — direct CSS selector (fastest path)
  - `placeholder` (string, optional) — exact placeholder match
  - `nth` (integer, optional, default `0`) — index among matching fields
- `timeout` (integer, optional, default `5`) — seconds to wait per field
- Also supports shorthand: `{"selector": "#id", "text": "value"}`

**Response:**
```json
{
  "status": "ok",
  "operation": "form/fill",
  "result": {
    "fields_filled": 4,
    "results": [
      {"field": "Email", "status": "ok", "tag": "input", "type": "text", "filled": "user@ex"},
      {"field": "#password", "status": "ok", "tag": "input", "type": "password", "filled": "s3cre"},
      {"field": "Enter title", "status": "ok", "tag": "textarea", "type": "", "filled": "My Proj"},
      {"field": "Name", "status": "ok", "tag": "input", "type": "text", "filled": "Zoltan"}
    ]
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/form/fill \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"fields": [{"selector": "#email", "value": "user@example.com"}]}' | python3 -m json.tool
```

#### POST /form/select

Select an option from a `<select>` dropdown by label, name, or CSS selector.

**Request body:**
```json
{
  "by": "label",
  "text_or_value": "Country",
  "option_value": "US"
}
```

*Fields:*
- `by` (string, required) — selection method: `"label"`, `"name"`, or `"selector"`
- `text_or_value` (string, required) — the label text, name attribute, or CSS selector
- `option_value` (string, optional) — the value attribute of the `<option>` to select

**Response:**
```json
{
  "status": "ok",
  "operation": "form/select",
  "result": {
    "by": "label",
    "selected": "US",
    "selected_text": "United States"
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/form/select \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"by": "label", "text_or_value": "Country", "option_value": "US"}' | python3 -m json.tool
```

#### POST /dropdown/select

Simplified dropdown selection interface — pass the label text and the visible option text (or option value) directly.

**Request body:**
```json
{
  "label": "Country",
  "option": "United States",
  "option_value": null,
  "timeout": 5
}
```

*Fields:*
- `label` (string, required) — visible text of the label associated with the `<select>`
- `option` (string, optional) — visible text of the option to select
- `option_value` (string, optional) — value attribute of the option to select (takes precedence if both provided)
- `timeout` (integer, optional, default `5`) — seconds to wait

**Response:**
```json
{
  "status": "ok",
  "operation": "dropdown/select",
  "result": {
    "label": "Country",
    "option": "United States",
    "option_value": "US"
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/dropdown/select \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"label": "Country", "option": "United States"}' | python3 -m json.tool
```

#### POST /checkbox/select

Check a checkbox or radio button identified by label text.

**Request body (single):**
```json
{
  "text": "I agree to terms",
  "timeout": 5
}
```

**Request body (batch):**
```json
{
  "texts": ["Option A", "Option B"],
  "timeout": 5
}
```

*Fields:*
- Single mode: `text` (string, required) — label text
- Batch mode: `texts` (array of strings, required) — multiple label texts
- `timeout` (integer, optional, default `5`)

**Response:**
```json
{
  "status": "ok",
  "operation": "checkbox/select",
  "result": {
    "checked": ["I agree to terms"]
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/checkbox/select \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"text": "I agree to terms"}' | python3 -m json.tool
```

#### POST /checkbox/deselect

Uncheck a checkbox or radio button by label text. Supports the same single/batch format as `/checkbox/select`.

**Request body:**
```json
{
  "text": "Notify me"
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/checkbox/deselect \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"text": "Notify me"}' | python3 -m json.tool
```

---

### Wait Operations

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/wait` | Wait for element by CSS selector |
| `POST` | `/wait/visible` | Wait for element to be visible **NEW v0.8** |
| `POST` | `/wait/text` | Wait for text content to appear/disappear |
| `POST` | `/wait/navigation` | Wait for page navigation to complete |
| `POST` | `/wait/network-idle` | Wait for network to be idle |

#### POST /wait

Wait for an element matching a CSS selector to appear in the DOM.

**Request body:**
```json
{
  "selector": "#loading",
  "timeout": 10,
  "visible": true
}
```

*Fields:*
- `selector` (string, required) — CSS selector
- `timeout` (integer, optional, default `10`) — max seconds to wait
- `visible` (boolean, optional, default `true`) — require the element to be visible

**Response:**
```json
{
  "status": "ok",
  "operation": "wait",
  "result": {
    "selector": "#loading",
    "found": true,
    "visible": true,
    "elapsed_ms": 234
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/wait \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"selector": "#content", "timeout": 10}' | python3 -m json.tool
```

#### POST /wait/visible

Dedicated endpoint for waiting until an element is both present in the DOM and visually visible. Equivalent to `/wait` with `visible=true` but with a simpler interface.

**Request body:**
```json
{
  "selector": "#content",
  "timeout": 10
}
```

*Fields:*
- `selector` (string, required) — CSS selector for the element
- `timeout` (integer, optional, default `10`) — max seconds to wait

**Response:**
```json
{
  "status": "ok",
  "operation": "wait/visible",
  "result": {
    "selector": "#content",
    "visible": true,
    "tag": "div",
    "elapsed_ms": 150
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/wait/visible \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"selector": "#content", "timeout": 10}' | python3 -m json.tool
```

#### POST /wait/text

Wait for specified text content to appear (or disappear) from the page.

**Request body:**
```json
{
  "text": "Welcome",
  "timeout": 10,
  "present": true
}
```

*Fields:*
- `text` (string, required) — text to wait for
- `timeout` (integer, optional, default `10`) — max seconds to wait
- `present` (boolean, optional, default `true`) — if `true`, waits for text to appear; if `false`, waits for it to disappear

**Response:**
```json
{
  "status": "ok",
  "operation": "wait/text",
  "result": {
    "text": "Welcome",
    "found": true,
    "present": true,
    "elapsed_ms": 300
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/wait/text \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"text": "Welcome", "timeout": 10}' | python3 -m json.tool
```

#### POST /wait/navigation

Wait for a page navigation event to complete. Useful after clicking links or submitting forms that trigger navigation.

**Request body:**
```json
{
  "timeout": 10,
  "quiet_ms": 500
}
```

*Fields:*
- `timeout` (integer, optional, default `10`) — max seconds to wait
- `quiet_ms` (integer, optional, default `500`) — ms of network quiet before considering navigation done

**Response:**
```json
{
  "status": "ok",
  "operation": "wait/navigation",
  "result": {
    "navigated": true,
    "url": "https://example.com/dashboard",
    "elapsed_ms": 1500
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/wait/navigation \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"timeout": 10}' | python3 -m json.tool
```

#### POST /wait/network-idle

Wait until the browser's network activity has ceased for a specified quiet period.

**Request body:**
```json
{
  "timeout": 10,
  "quiet_ms": 500
}
```

**Response:**
```json
{
  "status": "ok",
  "operation": "wait/network-idle",
  "result": {
    "idle": true,
    "elapsed_ms": 2000
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/wait/network-idle \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"timeout": 10}' | python3 -m json.tool
```

---

### Page Analysis

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/page/analyze` | Full page snapshot with modals, buttons, forms |
| `POST` | `/page/text` | Extract all visible text from the page |
| `POST` | `/page/find` | Find elements containing specific text |
| `POST` | `/page/outline` | Get a simplified outline of the page structure |
| `POST` | `/page/diff` | Compare current page state against previous snapshot |

#### POST /page/analyze

Take a structured snapshot of the current page, including modals, buttons, links, forms, inputs, and tables. The `?condensed=true` variant strips navigation, sidebar, and footer for focused analysis on the main content area.

**Query parameters:** `condensed` (boolean, default `false`) — enable condensed mode.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "page/analyze",
  "result": {
    "title": "Example Page",
    "url": "https://example.com",
    "modals": [],
    "buttons": [
      {"tag": "button", "text": "Submit", "selector": "#submit"}
    ],
    "links": [{"text": "About", "href": "/about", "selector": "a.nav-link"}],
    "forms": [{"action": "/login", "method": "post", "fields": ["email", "password"]}],
    "inputs": [{"type": "email", "label": "Email", "selector": "#email"}],
    "tables": [],
    "condensed": false
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/page/analyze \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool

# Condensed mode:
curl -s -X POST "http://localhost:8000/page/analyze?condensed=true" \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /page/text

Extract all visible text content from the current page.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "page/text",
  "result": {
    "text": "Welcome to Example\n\nThis is a sample page...",
    "length": 1024
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/page/text \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /page/find

Search for elements containing specific text on the page.

**Request body:**
```json
{
  "text": "Submit",
  "tag": "button"
}
```

*Fields:*
- `text` (string, required) — text to search for
- `tag` (string, optional) — restrict search to a specific HTML tag

**Response:**
```json
{
  "status": "ok",
  "operation": "page/find",
  "result": {
    "matches": [
      {"tag": "button", "text": "Submit", "selector": "#submit"}
    ],
    "count": 1
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/page/find \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"text": "Submit", "tag": "button"}' | python3 -m json.tool
```

#### POST /page/outline

Get a simplified HTML outline of the page structure — headings, sections, and key landmarks.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "page/outline",
  "result": {
    "outline": [
      {"level": "h1", "text": "Main Title"},
      {"level": "section", "heading": "Section 1"},
      {"level": "h2", "text": "Subsection"}
    ]
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/page/outline \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /page/diff

Compare the current page state against the previous snapshot captured by the last `/page/analyze` call.

**Request body:** None (optional: pass a previous result as JSON body)

**Response:**
```json
{
  "status": "ok",
  "operation": "page/diff",
  "result": {
    "changed": true,
    "added": [{"type": "button", "text": "New Button"}],
    "removed": [],
    "changed_elements": [
      {"type": "text", "from": "Loading...", "to": "Done!"}
    ]
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/page/diff \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### Iframe Operations

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/page/iframe-text` | Extract text from an iframe by index |
| `POST` | `/page/iframe/switch` | Switch context to a specific iframe |

#### POST /page/iframe-text

Extract all visible text from an iframe on the page.

**Request body:**
```json
{
  "index": 0
}
```

*Fields:* `index` (integer, optional, default `0`) — the iframe index (0-based).

**Response:**
```json
{
  "status": "ok",
  "operation": "page/iframe-text",
  "result": {
    "text": "Iframe content...",
    "length": 500
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/page/iframe-text \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"index": 0}' | python3 -m json.tool
```

#### POST /page/iframe/switch

Switch the execution context to an iframe by index. All subsequent operations run inside the selected iframe.

**Request body:**
```json
{
  "index": 1
}
```

**Response:**
```json
{
  "status": "ok",
  "operation": "page/iframe/switch",
  "result": {"iframe_index": 1}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/page/iframe/switch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"index": 1}' | python3 -m json.tool
```

---

### Screenshots

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/screenshot` | Take a screenshot of the full viewport |
| `POST` | `/api/screenshot` | API alias for `/screenshot` **NEW v0.8** |
| `POST` | `/full_screenshot` | Take a full-page screenshot (scrolls to capture) |
| `POST` | `/element_screenshot` | Screenshot a specific element |

#### POST /screenshot

Capture a screenshot of the current viewport as a base64-encoded JPEG.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "screenshot",
  "result": {
    "screenshot": "/9j/4AAQ...",
    "format": "jpeg",
    "width": 1280,
    "height": 720
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/screenshot \
  -H "Authorization: Bearer $API_TOKEN" \
  -o screenshot.json
```

#### POST /full_screenshot

Capture a full-page screenshot by scrolling through the entire page and stitching.

**Request body:**
```json
{
  "quality": 70
}
```

*Fields:* `quality` (integer, optional, default `70`) — JPEG quality (1–100).

**Response:**
```json
{
  "status": "ok",
  "operation": "full_screenshot",
  "result": {
    "screenshot": "/9j/4AAQ...",
    "format": "jpeg",
    "full_height": 4500,
    "sections": 5
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/full_screenshot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"quality": 80}' -o screenshot.json
```

#### POST /element_screenshot

Capture a screenshot of a specific element identified by CSS selector.

**Request body:**
```json
{
  "selector": "#main-content",
  "quality": 80
}
```

*Fields:*
- `selector` (string, required) — CSS selector for the element
- `quality` (integer, optional, default `80`) — JPEG quality

**Response:**
```json
{
  "status": "ok",
  "operation": "element_screenshot",
  "result": {
    "screenshot": "/9j/4AAQ...",
    "format": "jpeg",
    "selector": "#main-content"
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/element_screenshot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"selector": "#main-content"}' -o element-screenshot.json
```

---

### PDF Export

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/pdf` | Export current page as PDF |

#### POST /pdf

Generate a PDF of the current page using Chrome's built-in PDF rendering.

**Request body:**
```json
{
  "options": {}
}
```

*Fields:* `options` (object, optional) — Chrome PDF options (e.g., `{"printBackground": true, "paperWidth": 8.5}`).

**Response:** Binary PDF data (Content-Type: `application/pdf`).

**Example:**
```bash
curl -s -X POST http://localhost:8000/pdf \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{}' -o page.pdf
```

---

### Tab Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tabs` | List all open tabs |
| `GET` | `/api/tabs` | API alias for `/tabs` **NEW v0.8** |
| `POST` | `/tabs/scan` | Scan and refresh tab list |
| `POST` | `/tabs/deep-scan/{tab_id}` | Deep scan a specific tab for resources |
| `POST` | `/tab/new` | Open a new tab |
| `POST` | `/tab/close/{tab_id}` | Close a tab by ID |
| `POST` | `/switch_tab/{tab_id}` | Switch to a tab by ID |
| `POST` | `/activate-tab/{tab_id}` | Activate a tab by ID |

#### GET /tabs

List all open tabs with their IDs, titles, and URLs.

**Response:**
```json
{
  "status": "ok",
  "operation": "tabs",
  "result": {
    "tabs": [
      {"id": "tab-1", "title": "Example", "url": "https://example.com", "active": true}
    ],
    "active_id": "tab-1",
    "count": 1
  }
}
```

**Example:**
```bash
curl -s http://localhost:8000/tabs \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /tabs/scan

Refresh the tab list by re-discovering all tabs via CDP.

**Request body:** None

**Example:**
```bash
curl -s -X POST http://localhost:8000/tabs/scan \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /tabs/deep-scan/{tab_id}

Perform a deep scan of a specific tab, enumerating frames, resources, and JavaScript contexts.

**Path parameters:** `tab_id` (string) — the tab ID to scan.

**Example:**
```bash
curl -s -X POST http://localhost:8000/tabs/deep-scan/tab-1 \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /tab/new

Open a new browser tab with an optional URL.

**Request body:**
```json
{
  "url": "about:blank"
}
```

*Fields:* `url` (string, optional, default `"about:blank"`) — URL to open in the new tab.

**Response:**
```json
{
  "status": "ok",
  "operation": "tab/new",
  "result": {
    "id": "tab-2",
    "url": "about:blank",
    "title": ""
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/tab/new \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"url": "https://example.com"}' | python3 -m json.tool
```

#### POST /tab/close/{tab_id}

Close a specific tab by its ID.

**Path parameters:** `tab_id` (string) — the tab ID to close.

**Response:**
```json
{
  "status": "ok",
  "operation": "tab/close",
  "result": {"closed": "tab-2"}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/tab/close/tab-2 \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /switch_tab/{tab_id}

Switch to a tab by its ID, making it the active tab.

**Path parameters:** `tab_id` (string) — the tab to switch to.

**Response:**
```json
{
  "status": "ok",
  "operation": "switch_tab",
  "result": {"switched": true, "active_id": "tab-1"}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/switch_tab/tab-1 \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /activate-tab/{tab_id}

Activate a tab by ID (alias for `/switch_tab/{tab_id}` with auto-activation behavior).

**Path parameters:** `tab_id` (string) — the tab to activate.

**Example:**
```bash
curl -s -X POST http://localhost:8000/activate-tab/tab-1 \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### DOM Operations

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/dom_query` | Query DOM elements by CSS selector with optional attribute extraction |
| `POST` | `/dom_click_all` | Click all elements matching a CSS selector |

#### POST /dom_query

Query elements in the DOM by CSS selector and optionally extract a specific attribute.

**Request body:**
```json
{
  "selector": "a.nav-link",
  "attribute": "href"
}
```

*Fields:*
- `selector` (string, required) — CSS selector to query
- `attribute` (string, optional) — if provided, extracts this attribute from each match; otherwise returns element count

**Response:**
```json
{
  "status": "ok",
  "operation": "dom_query",
  "result": {
    "count": 5,
    "results": ["/home", "/about", "/contact"],
    "attribute": "href"
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/dom_query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"selector": "a.nav-link", "attribute": "href"}' | python3 -m json.tool
```

#### POST /dom_click_all

Click every element matching a CSS selector.

**Request body:**
```json
{
  "selector": ".like-button"
}
```

*Fields:* `selector` (string, required) — CSS selector for elements to click.

**Response:**
```json
{
  "status": "ok",
  "operation": "dom_click_all",
  "result": {
    "selector": ".like-button",
    "clicked": 3
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/dom_click_all \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"selector": ".like-button"}' | python3 -m json.tool
```

---

### Script Execution

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/script` | Execute a multi-step workflow script |
| `POST` | `/eval` | Evaluate arbitrary JavaScript in the page context |

#### POST /script

Execute a sequence of scripted steps (workflow). Each step specifies an action and parameters.

**Supported actions:**

| Action | Params | Description |
|--------|--------|-------------|
| `navigate` | `url` | Navigate to URL |
| `click` | `selector` | Click element by CSS selector |
| `click_text` | `text`, `timeout`, `nth` | Click by visible text |
| `click_label` | `text`, `timeout` | Click `<label>` by text |
| `type` | `selector`, `text` | Type into input/textarea |
| `eval` | `js` | Execute JavaScript |
| `form_fill` | `fields[]`, `timeout` | Smart form fill (label/selector/placeholder/nth) |
| `form_select` | `by`, `text_or_value`, `option_value` | Select dropdown option |
| `find_element` | `text`, `tag` | Find element by text |
| `wait` | `ms` | Sleep for N milliseconds |
| `wait_for_element` | `selector`, `timeout`, `visible` | Wait for element to appear |
| `wait_text` | `text`, `timeout`, `present` | Wait for text on page |
| `wait_for_navigation` | `timeout` | Wait for page navigation |
| `wait_for_network_idle` | `timeout`, `quiet_ms` | Wait for network to settle |
| `scroll` | `x`, `y` | Scroll the page |
| `screenshot` | `quality` | Take JPEG screenshot |
| `full_page_screenshot` | `quality` | Full-page screenshot |
| `element_screenshot` | `selector`, `quality` | Screenshot of specific element |
| `get_text` | — | Get page text content |
| `pdf` | — | Generate PDF |
| `upload_files` | `selector`, `files` | Upload files to input |
| `get_iframe_text` | `iframe_index` | Get text from iframe |
| `switch_to_iframe` | `iframe_index` | Switch context to iframe |
| `get_page_outline` | — | Get page structure outline |
| `analyze_page` | — | Full page analysis |
| `page_diff` | `previous_snapshot` | Compare with previous snapshot |
| `close` | — | Close browser |

**Request body:**
```json
{
  "steps": [
    {"action": "navigate", "params": {"url": "https://example.com"}},
    {"action": "wait_for_network_idle", "params": {"timeout": 10}},
    {"action": "form_fill", "params": {"fields": [
      {"selector": "#email", "value": "user@example.com"},
      {"placeholder": "Password", "value": "s3cret"}
    ]}},
    {"action": "click_text", "params": {"text": "Sign In"}},
    {"action": "wait", "params": {"ms": 2000}},
    {"action": "get_text", "params": {}}
  ]
}
```

*Fields:* `steps` (array, required) — list of `{action, params}` objects.

**Response:**
```json
{
  "status": "ok",
  "operation": "script",
  "result": {
    "completed": 6,
    "results": [
      {"step": 0, "status": "ok", "action": "navigate"},
      {"step": 1, "status": "ok", "action": "wait_for_network_idle"},
      {"step": 2, "status": "ok", "action": "form_fill"},
      {"step": 3, "status": "ok", "action": "click_text"},
      {"step": 4, "status": "ok", "action": "wait"},
      {"step": 5, "status": "ok", "action": "get_text"}
    ],
    "failed": []
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/script \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"steps": [{"action": "navigate", "params": {"url": "https://example.com"}}]}' | python3 -m json.tool
```

#### POST /eval

Execute raw JavaScript in the context of the current page.

**Request body:**
```json
{
  "js": "document.title",
  "format": "raw"
}
```

*Fields:*
- `js` (string, required) — JavaScript code to evaluate
- `format` (string, optional, default `"raw"`) — output format: `"raw"`, `"pretty"`, or `"structured"`

**Response:**
```json
{
  "status": "ok",
  "operation": "eval",
  "result": {
    "value": "Example Domain",
    "format": "raw"
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/eval \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"js": "document.title"}' | python3 -m json.tool
```

---

### Cookies

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/cookies` | Get all cookies for the current page |
| `POST` | `/set_cookie` | Set a cookie |
| `POST` | `/clear_cookies` | Clear all cookies |

#### GET /cookies

Retrieve all cookies for the current page's domain.

**Query parameters:** `truncate` (boolean, default `false`) — truncate cookie values to save bandwidth.

**Response:**
```json
{
  "status": "ok",
  "operation": "cookies",
  "result": {
    "cookies": [
      {"name": "session", "value": "abc123", "domain": ".example.com", "path": "/", "secure": false}
    ],
    "count": 1
  }
}
```

**Example:**
```bash
curl -s http://localhost:8000/cookies \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /set_cookie

Set a cookie on the current page's domain.

**Request body:**
```json
{
  "name": "session",
  "value": "abc123",
  "domain": ".example.com",
  "path": "/",
  "secure": false,
  "httpOnly": false
}
```

*Fields:*
- `name` (string, required)
- `value` (string, required)
- `domain` (string, optional)
- `path` (string, optional)
- `secure` (boolean, optional, default `false`)
- `httpOnly` (boolean, optional, default `false`)

**Response:**
```json
{
  "status": "ok",
  "operation": "set_cookie",
  "result": {"set": true}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/set_cookie \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"name": "session", "value": "abc123"}' | python3 -m json.tool
```

#### POST /clear_cookies

Clear all cookies for the current page's domain.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "clear_cookies",
  "result": {"cleared": true}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/clear_cookies \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### Network Monitoring

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/network/start` | Start network request monitoring |
| `POST` | `/network/stop` | Stop network request monitoring |
| `GET` | `/network/log` | Get captured network log entries |
| `POST` | `/network/clear` | Clear network log |

#### POST /network/start

Start capturing network requests and responses.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "network/start",
  "result": {"monitoring": true}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/network/start \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /network/stop

Stop capturing network requests.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "network/stop",
  "result": {"monitoring": false}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/network/stop \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### GET /network/log

Get all captured network log entries (requests, responses, timing).

**Response:**
```json
{
  "status": "ok",
  "operation": "network/log",
  "result": {
    "entries": [
      {"request": {"url": "https://api.example.com/data", "method": "GET"}, "response": {"status": 200}}
    ],
    "count": 1
  }
}
```

**Example:**
```bash
curl -s http://localhost:8000/network/log \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /network/clear

Clear all captured network log entries.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "network/clear",
  "result": {"cleared": true}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/network/clear \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### Session Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/session/save` | Save the current session state |
| `POST` | `/session/restore` | Restore a previously saved session |

#### POST /session/save

Save the current browser session state (tabs, cookies, local storage) for later restoration.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "session/save",
  "result": {
    "session_id": "sess_abc123",
    "tabs_count": 3
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/session/save \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /session/restore

Restore a previously saved session.

**Request body:**
```json
{
  "session": {"tabs": [], "cookies": []}
}
```

*Fields:* `session` (object, required) — session data previously returned by `/session/save`.

**Response:**
```json
{
  "status": "ok",
  "operation": "session/restore",
  "result": {"restored": true}
}
```

**Example:**
```bash
# Capture session, then restore it
SESSION=$(curl -s -X POST http://localhost:8000/session/save -H "Authorization: Bearer $API_TOKEN")
echo "$SESSION" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'session': d['result']}))" | \
  curl -s -X POST http://localhost:8000/session/restore \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $API_TOKEN" \
    -d @- | python3 -m json.tool
```

---

### Browser Lifecycle

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/browser/launch` | Launch a new Chrome instance |
| `POST` | `/browser/stop` | Stop a Chrome instance |
| `GET` | `/browser/status` | Get Chrome process status |

#### POST /browser/launch

Launch a new Chrome/Chromium instance with optional profile and debug port.

**Request body:**
```json
{
  "profile_dir": "/tmp/chrome-profile",
  "port": 9222
}
```

*Fields:*
- `profile_dir` (string, optional) — custom profile directory
- `port` (integer, optional) — CDP debug port
- `chrome_path` (string, optional) — path to Chrome binary

**Response:**
```json
{
  "status": "ok",
  "operation": "browser/launch",
  "result": {
    "pid": 12345,
    "port": 9222,
    "cdp_url": "http://localhost:9222"
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/browser/launch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"port": 9222}' | python3 -m json.tool
```

#### POST /browser/stop

Stop a running Chrome instance by PID.

**Request body:**
```json
{
  "pid": 12345
}
```

*Fields:* `pid` (integer, optional) — process ID to stop. If omitted, stops all managed instances.

**Response:**
```json
{
  "status": "ok",
  "operation": "browser/stop",
  "result": {"stopped": true, "pid": 12345}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/browser/stop \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{}' | python3 -m json.tool
```

#### GET /browser/status

Return the status of managed Chrome processes.

**Response:**
```json
{
  "status": "ok",
  "operation": "browser/status",
  "result": {
    "running": true,
    "pid": 12345,
    "port": 9222,
    "uptime_seconds": 3600
  }
}
```

**Example:**
```bash
curl -s http://localhost:8000/browser/status \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### Settings

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/settings` | Get current settings |
| `POST` | `/settings` | Update settings |

#### GET /settings

Retrieve the current configuration settings.

**Response:**
```json
{
  "status": "ok",
  "settings": {
    "chrome_profile_dir": null,
    "chrome_debug_port": 9222,
    "chrome_path": "/usr/bin/chromium"
  }
}
```

**Example:**
```bash
curl -s http://localhost:8000/settings \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /settings

Update configuration settings.

**Request body:**
```json
{
  "chrome_debug_port": 9333
}
```

*Fields:*
- `chrome_profile_dir` (string, optional)
- `chrome_debug_port` (integer, optional)
- `chrome_path` (string, optional)

**Response:**
```json
{
  "status": "ok",
  "settings": {
    "chrome_debug_port": 9333
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/settings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"chrome_debug_port": 9333}' | python3 -m json.tool
```

---

### Headless Sessions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/headless/launch` | Launch a new headless session (supports proxy rotation) |
| `POST` | `/headless/close` | Close a headless session |
| `GET` | `/headless/sessions` | List all headless sessions |
| `POST` | `/headless/navigate` | Navigate a headless session |
| `POST` | `/headless/eval` | Evaluate JS in a headless session |
| `POST` | `/headless/screenshot` | Screenshot a headless session |
| `POST` | `/headless/batch-screenshot` | Batch screenshots for a headless session |
| `GET` | `/headless/health` | Headless session pool health |

#### POST /headless/launch

Launch a new headless Chrome session.

**Request body:**
```json
{
  "profile_dir": null,
  "port": null,
  "profile": null,
  "extensions": null,
  "proxy_url": null,
  "proxy_strategy": null,
  "proxy_group": null
}
```

*Fields:*
- `profile_dir` (string, optional)
- `port` (integer, optional)
- `profile` (string, optional) — named profile to use
- `extensions` (array of strings, optional) — extension paths to load
- `proxy_url` (string, optional) — explicit proxy URL (takes precedence over strategy)
- `proxy_strategy` (string, optional) — rotation strategy: `round-robin`, `random`, `sticky`, `by-tag`
- `proxy_group` (string, optional) — tag group filter for `by-tag` strategy

**Response:**
```json
{
  "status": "ok",
  "operation": "headless/launch",
  "result": {
    "session_id": "hs_abc123",
    "cdp_port": 9223
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/headless/launch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{}' | python3 -m json.tool
```

#### POST /headless/close

Close a headless session by its session ID.

**Request body:**
```json
{
  "session_id": "hs_abc123"
}
```

*Fields:* `session_id` (string, required).

**Response:**
```json
{
  "status": "ok",
  "operation": "headless/close",
  "result": {"session_id": "hs_abc123", "closed": true}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/headless/close \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"session_id": "hs_abc123"}' | python3 -m json.tool
```

#### GET /headless/sessions

List all active headless sessions with resource usage.

**Response:**
```json
{
  "status": "ok",
  "sessions": [
    {"session_id": "hs_abc123", "url": "https://example.com", "uptime_seconds": 120}
  ],
  "count": 1
}
```

**Example:**
```bash
curl -s http://localhost:8000/headless/sessions \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /headless/navigate

Navigate a headless session to a URL.

**Request body:**
```json
{
  "session_id": "hs_abc123",
  "url": "https://example.com"
}
```

*Fields:*
- `session_id` (string, required)
- `url` (string, required)

**Example:**
```bash
curl -s -X POST http://localhost:8000/headless/navigate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"session_id": "hs_abc123", "url": "https://example.com"}' | python3 -m json.tool
```

#### POST /headless/eval

Evaluate JavaScript in a headless session.

**Request body:**
```json
{
  "session_id": "hs_abc123",
  "expression": "document.title"
}
```

*Fields:*
- `session_id` (string, required)
- `expression` (string, required) — JavaScript expression to evaluate

**Example:**
```bash
curl -s -X POST http://localhost:8000/headless/eval \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"session_id": "hs_abc123", "expression": "document.title"}' | python3 -m json.tool
```

#### POST /headless/screenshot

Take a screenshot of a headless session's current page.

**Request body:**
```json
{
  "session_id": "hs_abc123"
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/headless/screenshot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"session_id": "hs_abc123"}' -o headless-screenshot.json
```

#### POST /headless/batch-screenshot

Take multiple screenshots by navigating to each URL in sequence.

**Request body:**
```json
{
  "session_id": "hs_abc123",
  "urls": ["https://example.com", "https://example.org"]
}
```

*Fields:*
- `session_id` (string, required)
- `urls` (array of strings, required) — URLs to screenshot

**Example:**
```bash
curl -s -X POST http://localhost:8000/headless/batch-screenshot \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"session_id": "hs_abc123", "urls": ["https://example.com"]}' | python3 -m json.tool
```

#### GET /headless/health

Headless session pool health and stats.

**Response:**
```json
{
  "status": "ok",
  "pool_size": 1,
  "active_sessions": 1,
  "memory_mb": 256.5
}
```

**Example:**
```bash
curl -s http://localhost:8000/headless/health \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### Profile Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/profiles` | List all profiles |
| `POST` | `/profiles` | Create a new profile |
| `GET` | `/profiles/{name}` | Get a profile by name |
| `PUT` | `/profiles/{name}` | Update a profile |
| `DELETE` | `/profiles/{name}` | Delete a profile |
| `POST` | `/profiles/{name}/export` | Export a profile as ZIP |
| `POST` | `/profiles/import` | Import a profile from ZIP |
| `GET` | `/profiles/{name}/extensions` | List extensions for a profile |
| `POST` | `/profiles/{name}/extensions` | Add an extension to a profile |
| `DELETE` | `/profiles/{name}/extensions` | Remove an extension from a profile |

#### GET /profiles

List all available browser profiles.

**Response:**
```json
{
  "status": "ok",
  "profiles": [
    {"name": "default", "extensions": [], "description": "", "tags": [], "created": "2026-01-01T00:00:00"}
  ]
}
```

**Example:**
```bash
curl -s http://localhost:8000/profiles \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /profiles

Create a new browser profile.

**Request body:**
```json
{
  "name": "work",
  "extensions": [],
  "description": "Work profile",
  "tags": ["work"],
  "resource_limits": null
}
```

*Fields:*
- `name` (string, required)
- `extensions` (array of strings, optional)
- `description` (string, optional)
- `tags` (array of strings, optional)
- `resource_limits` (object, optional)

**Response (201 Created):**
```json
{
  "status": "ok",
  "profile": {
    "name": "work",
    "extensions": [],
    "description": "Work profile"
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/profiles \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"name": "work", "description": "Work profile"}' | python3 -m json.tool
```

#### GET /profiles/{name}

Get details of a specific profile.

**Path parameters:** `name` (string) — the profile name.

**Example:**
```bash
curl -s http://localhost:8000/profiles/work \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### PUT /profiles/{name}

Update a profile's description, tags, and resource limits.

**Request body:**
```json
{
  "description": "Updated work profile",
  "tags": ["work", "production"]
}
```

**Example:**
```bash
curl -s -X PUT http://localhost:8000/profiles/work \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"description": "Updated work profile"}' | python3 -m json.tool
```

#### DELETE /profiles/{name}

Delete a profile and its data directory.

**Example:**
```bash
curl -s -X DELETE http://localhost:8000/profiles/work \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /profiles/{name}/export

Export a profile as a ZIP archive.

**Example:**
```bash
curl -s -X POST http://localhost:8000/profiles/work/export \
  -H "Authorization: Bearer $API_TOKEN" -o work-profile.zip
```

#### POST /profiles/import

Import a profile from a ZIP archive path.

**Request body:**
```json
{
  "path": "/tmp/work-profile.zip"
}
```

*Fields:* `path` (string, required) — path to the ZIP file on the server.

**Example:**
```bash
curl -s -X POST http://localhost:8000/profiles/import \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"path": "/tmp/work-profile.zip"}' | python3 -m json.tool
```

#### GET /profiles/{name}/extensions

List all extensions installed for a profile.

**Example:**
```bash
curl -s http://localhost:8000/profiles/work/extensions \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /profiles/{name}/extensions

Add an extension to a profile.

**Request body:**
```json
{
  "path": "/path/to/extension.crx"
}
```

*Fields:* `path` (string, required) — path to the extension file.

**Example:**
```bash
curl -s -X POST http://localhost:8000/profiles/work/extensions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"path": "/path/to/extension.crx"}' | python3 -m json.tool
```

#### DELETE /profiles/{name}/extensions

Remove an extension from a profile.

**Request body:**
```json
{
  "path": "/path/to/extension.crx"
}
```

**Example:**
```bash
curl -s -X DELETE http://localhost:8000/profiles/work/extensions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"path": "/path/to/extension.crx"}' | python3 -m json.tool
```

---

### Visual Regression

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/screenshot/baseline` | Create or update a visual baseline for a URL |
| `POST` | `/screenshot/compare` | Compare a screenshot against a baseline |
| `GET` | `/screenshot/baselines` | List all baselines |
| `DELETE` | `/screenshot/baseline` | Delete a specific baseline |

#### POST /screenshot/baseline

Create or update a visual regression baseline for a URL.

**Request body:**
```json
{
  "url": "https://example.com",
  "profile": "default",
  "quality": 70,
  "viewport": null
}
```

*Fields:*
- `url` (string, required)
- `profile` (string, optional)
- `quality` (integer, optional, default `70`)
- `viewport` (object, optional) — `{"width": 1280, "height": 720}`

**Response:**
```json
{
  "status": "ok",
  "operation": "screenshot/baseline",
  "result": {
    "url": "https://example.com",
    "baseline_id": "bl_abc123",
    "created": true
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/screenshot/baseline \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"url": "https://example.com"}' | python3 -m json.tool
```

#### POST /screenshot/compare

Compare a screenshot of a URL against its stored baseline.

**Request body:**
```json
{
  "url": "https://example.com",
  "profile": "default",
  "threshold": 0.001,
  "quality": 70
}
```

*Fields:*
- `url` (string, required)
- `profile` (string, optional)
- `threshold` (number, optional, default `0.001`) — diff threshold (0.0–1.0)
- `quality` (integer, optional, default `70`)

**Response:**
```json
{
  "status": "ok",
  "operation": "screenshot/compare",
  "result": {
    "url": "https://example.com",
    "diff_percent": 0.05,
    "passed": true,
    "diff_image": "/9j/4AAQ..."
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/screenshot/compare \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"url": "https://example.com", "threshold": 0.001}' | python3 -m json.tool
```

#### GET /screenshot/baselines

List all stored baselines, optionally filtered by profile.

**Query parameters:** `profile` (string, optional) — filter by profile name.

**Response:**
```json
{
  "status": "ok",
  "baselines": [
    {"url": "https://example.com", "profile": "default", "created": "2026-01-01T00:00:00"}
  ]
}
```

**Example:**
```bash
curl -s "http://localhost:8000/screenshot/baselines?profile=default" \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### DELETE /screenshot/baseline

Delete a baseline for a specific URL and profile.

**Request body:**
```json
{
  "url": "https://example.com",
  "profile": "default"
}
```

*Fields:*
- `url` (string, required)
- `profile` (string, optional)

**Response:**
```json
{
  "status": "ok",
  "operation": "screenshot/baseline",
  "result": {"deleted": true}
}
```

**Example:**
```bash
curl -s -X DELETE http://localhost:8000/screenshot/baseline \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"url": "https://example.com"}' | python3 -m json.tool
```

---

### JavaScript Controls

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/javascript/disable` | Disable JavaScript execution |
| `POST` | `/javascript/enable` | Re-enable JavaScript execution |

#### POST /javascript/disable

Disable JavaScript execution in the browser.

**Request body:** None

**Response:**
```json
{
  "status": "ok",
  "operation": "javascript/disable",
  "result": {"javascript_enabled": false}
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/javascript/disable \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /javascript/enable

Re-enable JavaScript execution.

**Example:**
```bash
curl -s -X POST http://localhost:8000/javascript/enable \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### Post-Action Confirmation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/confirm-action` | Take a screenshot or analyze after an action |

#### POST /confirm-action

After performing an interactive action, call this to capture a screenshot or analyze the page state for confirmation.

**Query parameters:** `confirm` (string, default `"analyze"`) — `"screenshot"` for a base64 JPEG, `"analyze"` for a page state comparison.

**Response:**
```json
{
  "status": "ok",
  "operation": "confirm-action",
  "result": {
    "type": "analyze",
    "data": {...}
  }
}
```

**Example:**
```bash
# Screenshot confirmation
curl -s -X POST "http://localhost:8000/confirm-action?confirm=screenshot" \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool

# Analyze confirmation
curl -s -X POST "http://localhost:8000/confirm-action?confirm=analyze" \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

### Utilities

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve GUI dashboard (static/index.html) |
| `GET` | `/metrics` | Process metrics and resource usage |
| `POST` | `/upload` | Upload files through the browser file input |
| `POST` | `/get_text` | Alias: get text content (deprecated, use `/page/text`) |
| `POST` | `/eval` | Execute JS (see Script Execution section) |

#### GET /

Serve the GUI dashboard if `static/index.html` exists.

**Example:**
```bash
curl -s http://localhost:8000/ | head -20
```

#### GET /metrics

Get process metrics and resource usage statistics.

**Response:**
```json
{
  "status": "ok",
  "memory_mb": 85.2,
  "uptime_seconds": 3600,
  "operations_count": 150
}
```

**Example:**
```bash
curl -s http://localhost:8000/metrics \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

#### POST /upload

Upload file(s) through a browser file input identified by CSS selector.

**Request body:**
```json
{
  "selector": "#file-input",
  "files": ["/path/to/file.pdf"]
}
```

*Fields:*
- `selector` (string, required) — CSS selector for the `<input type="file">` element
- `files` (array of strings, required) — absolute paths to files on the server to upload

**Response:**
```json
{
  "status": "ok",
  "operation": "upload",
  "result": {
    "selector": "#file-input",
    "files_uploaded": 1
  }
}
```

**Example:**
```bash
curl -s -X POST http://localhost:8000/upload \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"selector": "#file-input", "files": ["/tmp/report.pdf"]}' | python3 -m json.tool
```

#### POST /get_text

Alias for `/page/text` (deprecated). Extract text from the current page.

**Example:**
```bash
curl -s -X POST http://localhost:8000/get_text \
  -H "Authorization: Bearer $API_TOKEN" | python3 -m json.tool
```

---

## CDP Connection Lifecycle

1. **POST /connect** → Establish a CDP link to a Chrome instance (or auto-launch one)
2. **POST /navigate** → Navigate to the target URL
3. **Use interaction/analysis endpoints** → Click, type, fill, wait, analyze, screenshot
4. **POST /disconnect** → Cleanly close the CDP connection and release resources

### Typical Session

```bash
# 1. Connect
curl -s -X POST http://localhost:8000/connect \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"cdp_url": "http://localhost:9222"}'

# 2. Navigate
curl -s -X POST "http://localhost:8000/navigate?url=https://example.com" \
  -H "Authorization: Bearer $API_TOKEN"

# 3. Interact
curl -s -X POST http://localhost:8000/click/text \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"text": "Learn more"}'

# 4. Disconnect
curl -s -X POST http://localhost:8000/disconnect \
  -H "Authorization: Bearer $API_TOKEN"
```

## Common Patterns

### Authentication

All endpoints (except `GET /`, `GET /health`, `GET /ready`) require a Bearer token:

```bash
-H "Authorization: Bearer $API_TOKEN"
```

Set the token via the `API_TOKEN` environment variable when starting the server.

### Auto-Activation

Every interactive operation automatically activates the current tab first — it activates the tab before dispatching any command. You do not need to call `/switch_tab` or `/activate-tab` before clicking or typing.

### Standard Response Format

All endpoints return a consistent JSON response:

```json
{
  "status": "ok",
  "operation": "<endpoint_name>",
  "result": { ... }
}
```

On error:
```json
{
  "status": "error",
  "operation": "<endpoint_name>",
  "error": "Descriptive error message"
}
```

### Post-Action Confirmation

Interactive endpoints (`/click`, `/click/text`, `/click/label`, `/checkbox/select`, `/checkbox/deselect`) accept an optional `?confirm=` query parameter:

- `?confirm=screenshot` — returns a base64 JPEG screenshot after the action
- `?confirm=analyze` — returns a page state analysis after the action

```bash
curl -s -X POST "http://localhost:8000/click/text?confirm=screenshot" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{"text": "Submit"}'
```

### v0.8 Feature Notes

The following features and improvements were added in v0.8:

#### New Endpoints

| Endpoint | Type | Purpose |
|----------|------|---------|
| `POST /click/coordinates` | New | Click at raw pixel coordinates for canvas/SVG/video |
| `POST /dropdown/select` | New (simplified) | Simplified dropdown selection by label text |
| `POST /wait/visible` | New (dedicated) | Dedicated visible-element wait |
| `POST /click/label/text` | Alias | Alias for `/click/label` |
| `POST /form/select/by-label` | Alias | Alias for `/form/select` with `by=label` |
| `GET /api/tabs` | Alias | Backward-compatible alias for `/tabs` |
| `POST /api/screenshot` | Alias | Backward-compatible alias for `/screenshot` |

#### /click/label "label" Alias

`POST /click/label` now accepts `"label"` as an alias for `"text"` in the request body, in addition to the standard `"text"` field. This allows both forms:

```json
{"label": "Email", "timeout": 5}
{"text": "Email", "timeout": 5}
```

If both `label` and `text` are provided, `text` takes precedence. This flexibility is useful when the agent already has label-keyed data from `analyze_page()` and wants to click without remapping field names.

#### /form/fill Dual Format Support

`POST /form/fill` accepts form field data in either format:

**Standard (array):**
```json
{
  "fields": [
    {"label": "Email", "value": "user@example.com"},
    {"label": "Password", "value": "s3cret"}
  ],
  "timeout": 5
}
```

**Single object (auto-coerced):** Pass a single `FormFillField` object — the API converts it to the array format automatically. Each field supports `label` (required), `value` (required), and `type` (optional, e.g. `"email"`, `"password"`).

#### API Aliases for Backward Compatibility

The following alias routes provide backward compatibility for clients built against earlier API versions:

- `GET /api/tabs` → delegates to `GET /tabs`
- `POST /api/screenshot` → delegates to `POST /screenshot`
- `POST /click/label/text` → delegates to `POST /click/label`
- `POST /form/select/by-label` → delegates to `POST /form/select` with `by="label"`

These aliases are transparent — they follow the exact same request/response format as the target endpoint and are maintained alongside the primary routes.

#### Dropdown Selection Workflow

`POST /dropdown/select` provides a simplified one-call dropdown interface compared to `POST /form/select`. The recommended workflow for interaction patterns that require opening a dropdown first (e.g. custom JS dropdowns that are not `<select>` elements):

```
click trigger → wait for menu → click option
```

Use the explicit click→wait→click workflow for custom JS dropdowns:

```bash
# 1. Click the dropdown trigger (by text)
curl -s -X POST http://localhost:8000/click/text \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"text": "Country", "timeout": 5}'

# 2. Wait for the option menu to appear
curl -s -X POST http://localhost:8000/wait/visible \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"selector": "[role=option]:first-child", "timeout": 5}'

# 3. Click the option by text
curl -s -X POST http://localhost:8000/click/text \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"text": "United States", "timeout": 5}'
```

For native `<select>` dropdowns, use the simpler single-call endpoint:

```bash
curl -s -X POST http://localhost:8000/dropdown/select \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"label": "Country", "option": "United States"}'
```

#### Coordinate Click Use Cases

`POST /click/coordinates` targets pixel coordinates on the page, useful when:
- **Canvas/WebGL elements** — no DOM selectors available for game canvases or chart renderers
- **SVG/vector graphics** — interactive charts, maps, or diagrams where elements are SVG children
- **Video players** — clicking play/pause/seek on `<video>` controls that don't expose individual selectors
- **Image maps** — `<area>` elements mapped to coordinates
- **CDP-inspected coordinates** — when `analyze_page()` returns `{x, y}` positions, pass them directly to `/click/coordinates` for pixel-precise targeting

Example: double-click on canvas at position (450, 320):

```bash
curl -s -X POST http://localhost:8000/click/coordinates \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"x": 450, "y": 320, "button": "left", "click_count": 2}'
```

#### Modal Element Discovery

`POST /page/analyze` now performs deep modal inspection. The response includes:

- **`buttons[].in_modal`** — boolean flag on each detected button indicating whether it lives inside a modal/popup/dialog
- **`modals[]`** — array of open modal dialogs, each containing:
  - `id`, `cls` — modal element identifiers
  - `buttons[]` — buttons inside the modal (including buttons with complex `aria-label` attributes; falls back to `aria-label` when no visible `textContent` exists)
  - `tabs[]` — tab UI elements inside the modal with `has_unread` indicators
  - `modal_text` — full text content of the modal (truncated to 500 chars)

This makes it possible to discover and interact with elements inside modals, popups, and dialogs without needing separate selectors. Combine with `/click/text` using `container_selector` to target buttons inside a specific modal:

```bash
# 1. Analyze page (includes modal buttons)
curl -s -X POST http://localhost:8000/page/analyze \
  -H "Authorization: Bearer ***" | python3 -m json.tool

# 2. Click inside a modal by container
curl -s -X POST http://localhost:8000/click/text \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"text": "Accept", "container_selector": ".modal", "timeout": 5}'
```

### Proxy Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/proxy/pool` | Add one or more proxies to the pool |
| `GET` | `/proxy/pool` | List all proxies in the pool |
| `GET` | `/proxy/pool/{proxy_id}` | Get a single proxy by ID |
| `DELETE` | `/proxy/pool/{proxy_id}` | Remove a single proxy |
| `DELETE` | `/proxy/pool` | Clear all proxies |
| `POST` | `/proxy/health` | Run health check on all or a single proxy |
| `GET` | `/proxy/health` | Get health summary for all proxies |
| `POST` | `/proxy/stats` | Get proxy usage statistics |

#### POST /proxy/pool

Add one or more proxies to the rotation pool.

**Request body:**
```json
{
  "proxies": [
    {"url": "socks5://user:pass@proxy.example.com:1080", "type": "SOCKS5", "tags": ["datacenter", "us"]},
    {"url": "http://user:pass@proxy2.example.com:3128", "type": "HTTP", "tags": ["residential"]}
  ]
}
```

*Fields:*
- `proxies` (array, required) — list of proxy objects
- `url` (string, required) — full proxy URL including protocol
- `type` (string, optional) — proxy type (HTTP, HTTPS, SOCKS5); auto-detected from URL if omitted
- `tags` (array of strings, optional) — tags for group-based rotation

**Response:**
```json
{
  "status": "ok",
  "data": {
    "ids": ["uuid-1", "uuid-2"]
  }
}
```

#### GET /proxy/pool

List all proxies in the pool.

**Response:**
```json
{
  "status": "ok",
  "data": {
    "proxies": [
      {
        "id": "uuid",
        "url": "socks5://user:pass@proxy.example.com:1080",
        "type": "SOCKS5",
        "tags": ["datacenter"],
        "enabled": true,
        "healthy": true,
        "last_checked": 0.0,
        "latency_ms": 0.0,
        "success_count": 0,
        "fail_count": 0,
        "created_at": 1234567890.0
      }
    ]
  }
}
```

#### Rotation Strategies

Proxies support four rotation strategies when retrieving a proxy from the pool:

| Strategy | Description |
|----------|-------------|
| `round-robin` | Cycle through healthy proxies sequentially (default) |
| `random` | Pick a random healthy proxy |
| `sticky` | Pin a session to the same proxy via `session_id` |
| `by-tag` | Round-robin within a tag group |

Proxy parameters on `/headless/launch`:

| Field | Description |
|-------|-------------|
| `proxy_url` | Explicit proxy URL (takes precedence over strategy) |
| `proxy_strategy` | Rotation strategy (`round-robin`, `random`, `sticky`, `by-tag`) |
| `proxy_group` | Tag group filter for `by-tag` strategy |

### HTTP Methods Reference

| Method | Convention |
|--------|------------|
| `GET` | Read-only: list, status, health |
| `POST` | Create, execute, or mutate state |
| `PUT` | Update an existing resource |
| `DELETE` | Remove a resource |

### Agent Navigation Engine (v1.3)

Prefer `POST /agent/observe` with `mode=accessibility` for complex pages. Use `/agent/forms/discover` and `/agent/forms/fill` instead of manually locating each field, `/agent/extract` for evidence-backed structured data, `/agent/available-actions` when the next step is unclear, and `/agent/execute-task` for bounded form-and-continue workflows. Accessibility refs are snapshot scoped and stale refs must be refreshed.
