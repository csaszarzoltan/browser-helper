"""
FastAPI REST API server for browser-helper.

Wraps the CDP client and provides REST + WebSocket endpoints
for browser automation. Serves a GUI dashboard and streams
real-time status updates over WebSocket.
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Auth / rate limiting
# ---------------------------------------------------------------------------
from cdp_client import CDPClient

# Paths excluded from auth and rate-limiting middleware
PUBLIC_PATHS = {"/", "/health", "/ready", "/ws"}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("browser-helper")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", "8000"))
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
API_TOKEN = os.environ.get("API_TOKEN", "")

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown lifecycle handler."""
    global start_time
    start_time = time.monotonic()
    logger.info("Browser Helper API starting up ...")
    try:
        result = await client.connect()
        state["connected"] = True
        state["cdp_url"] = result.get("cdp_url", "auto-discovered")
        logger.info("Auto-connected to CDP at %s", state["cdp_url"])
    except Exception as exc:
        logger.warning("Auto-connect to CDP failed (server will start anyway): %s", exc)
    yield
    # Shutdown
    if client.is_connected:
        try:
            await client.disconnect()
        except Exception:
            pass
    for ws in ws_clients.copy():
        try:
            await ws.close()
        except Exception:
            pass
    ws_clients.clear()


app = FastAPI(
    title="Browser Helper API",
    version="1.0.0",
    description="REST + WebSocket API for browser automation via CDP.",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow all origins
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# GZip compression — reduces JSON responses by 70-80%
app.add_middleware(GZipMiddleware, minimum_size=500)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
client = CDPClient()

# Operation log: list of dicts, max 100 entries
# Each entry: {timestamp, operation, status, duration_ms, details}
operation_log: list[dict[str, Any]] = []

# Connected WebSocket clients
ws_clients: set[WebSocket] = set()

# Shared state dict broadcast to WS clients on every change
state: dict[str, Any] = {
    "connected": False,
    "tabs_count": 0,
    "last_operation": None,
    "last_operation_time": None,
    "cdp_url": None,
}

# Start time for uptime calculation in health endpoint
# Freshly initialised in ``on_startup`` so that uptime is measured from
# application startup, not module import.
start_time = 0.0


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------
class EvalRequest(BaseModel):
    js: str


class ClickRequest(BaseModel):
    selector: str


class TypeRequest(BaseModel):
    selector: str
    text: str


class ConnectRequest(BaseModel):
    cdp_url: str | None = None


# ---------------------------------------------------------------------------
# Pydantic request models — new endpoints
# ---------------------------------------------------------------------------
class FullScreenshotRequest(BaseModel):
    quality: int = 70


class ElementScreenshotRequest(BaseModel):
    selector: str
    quality: int = 80


class PDFRequest(BaseModel):
    options: dict = {}


class SetCookieRequest(BaseModel):
    name: str
    value: str
    domain: str | None = None
    path: str | None = None
    secure: bool = False
    httpOnly: bool = False


class DOMQueryRequest(BaseModel):
    selector: str
    attribute: str | None = None


class DOMClickAllRequest(BaseModel):
    selector: str


class ScriptRequest(BaseModel):
    steps: list[dict]


class SessionRestoreRequest(BaseModel):
    session: dict


class NewTabRequest(BaseModel):
    url: str = "about:blank"


# ─── New: Smart interaction models ──────────────────────────────


class FormFillRequest(BaseModel):
    fields: list[dict]
    timeout: int = 5


class WaitRequest(BaseModel):
    selector: str
    timeout: int = 10
    visible: bool = True


class ClickTextRequest(BaseModel):
    text: str
    timeout: int = 5


# ---------------------------------------------------------------------------
# Auth middleware — Bearer token check
# ---------------------------------------------------------------------------


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require Bearer token on all non-public endpoints."""
    if API_TOKEN:
        path = request.url.path
        # Skip auth for public paths and OpenAPI docs
        if path not in PUBLIC_PATHS and not path.startswith(("/docs", "/openapi.json", "/redoc")):
            auth_header = request.headers.get("Authorization", "")
            token = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
            if token != API_TOKEN:
                return JSONResponse(status_code=401, content={"detail": "Invalid or missing API token"})
    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_memory_mb() -> float:
    """Get current RSS memory usage in MB from /proc/self/status."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) / 1024
    except Exception:
        pass
    return 0.0


def log_operation(
    operation: str,
    status: str,
    duration_ms: float,
    details: str = "",
) -> dict[str, Any]:
    """Append an operation entry to the ring buffer and update global state."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": operation,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "details": details,
    }
    operation_log.append(entry)
    if len(operation_log) > 100:
        operation_log.pop(0)

    # Sync global state from client
    state["connected"] = client.is_connected
    state["tabs_count"] = client.tabs_count
    state["last_operation"] = operation
    state["last_operation_time"] = entry["timestamp"]

    return entry


async def broadcast_state():
    """Push current state + recent log entries to all WS clients."""
    payload = {
        "type": "state_update",
        "state": dict(state),
        "recent_log": operation_log[-10:],
    }
    stale: set[WebSocket] = set()
    for ws in ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            stale.add(ws)
    if stale:
        ws_clients.difference_update(stale)


def ensure_connected():
    """Raise 400 if the CDP client is not connected."""
    if not client.is_connected:
        raise HTTPException(status_code=400, detail="Not connected to CDP. Call POST /connect first.")


async def run_op(operation: str, method, *args, **kwargs) -> dict[str, Any]:
    """
    Execute a CDP client method, time it, log it, broadcast state,
    and return a standardised response dict.
    """
    ensure_connected()
    start = time.monotonic()
    try:
        result = await method(*args, **kwargs)
        elapsed = (time.monotonic() - start) * 1000
        log_operation(operation, "success", elapsed, str(result)[:200])
        await broadcast_state()
        return {"status": "ok", "operation": operation, "result": result}
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        logger.exception("Operation '%s' failed", operation)
        log_operation(operation, "error", elapsed, str(exc))
        await broadcast_state()
        return {"status": "error", "operation": operation, "error": str(exc)}


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Serve the GUI dashboard."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"message": "Browser Helper API — install a static/index.html for the dashboard."}


@app.get("/status")
async def get_status():
    """Return current connection status."""
    return {
        "connected": client.is_connected,
        "tabs_count": client.tabs_count,
        "last_operation": state["last_operation"],
        "last_operation_time": state["last_operation_time"],
        "cdp_url": state["cdp_url"],
        "log_size": len(operation_log),
    }


@app.post("/connect")
async def connect(body: ConnectRequest | None = None):
    """
    Connect to Chrome CDP.

    If *cdp_url* is provided it is used directly; otherwise the client
    auto-discovers the endpoint via ``http://127.0.0.1:9555/json``.
    """
    cdp_url = body.cdp_url if body else None
    start = time.monotonic()
    try:
        result = await client.connect(cdp_url)
        elapsed = (time.monotonic() - start) * 1000
        state["cdp_url"] = result.get("cdp_url", cdp_url)
        log_operation("connect", "success", elapsed, str(result)[:200])
        await broadcast_state()
        return {"status": "ok", "operation": "connect", "result": result}
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        logger.exception("Connect failed")
        log_operation("connect", "error", elapsed, str(exc))
        await broadcast_state()
        return {"status": "error", "operation": "connect", "error": str(exc)}


@app.post("/navigate")
async def navigate(url: str = Query(..., description="Target URL to navigate to")):
    """Navigate the current tab to *url*."""
    # Invalidate tab cache — navigation changes the page URL
    client._tabs_cache = []
    client._tabs_cache_ts = 0
    return await run_op("navigate", client.navigate, url)


@app.post("/eval")
async def eval_js(body: EvalRequest):
    """Execute JavaScript in the current page."""
    return await run_op("eval", client.evaluate_js, body.js)


@app.post("/click")
async def click_element(body: ClickRequest):
    """Click the element matching *selector* (CSS selector)."""
    return await run_op("click", client.click, body.selector)


@app.post("/type")
async def type_text(body: TypeRequest):
    """Type *text* into the element matching *selector*."""
    return await run_op("type", client.type_text, body.selector, body.text)


# ─── New: Smart interaction endpoints ────────────────────────────


@app.post("/form/fill")
async def form_fill(body: FormFillRequest):
    """Fill form fields by label text — no CSS selectors needed.

    Each field in *fields* has ``label`` (search text) and ``value``.
    The engine finds inputs by <label>, placeholder, name, or aria-label.
    """
    return await run_op("form_fill", client.smart_form_fill,
                        body.fields, body.timeout)


@app.post("/wait")
async def wait_element(body: WaitRequest):
    """Wait until an element matching *selector* appears in the DOM.

    Polls every 200ms. Returns when found or timeout.
    Use before form fill, click, or screenshot to ensure the page is ready.
    """
    return await run_op("wait", client.wait_for_element,
                        body.selector, body.timeout, body.visible)


@app.post("/click/text")
async def click_by_text(body: ClickTextRequest):
    """Click an element by its visible text content.

    Searches a/button/span elements whose text matches.
    No CSS selector needed — just the text you see on screen.
    """
    return await run_op("click_text", client.click_by_text,
                        body.text, body.timeout)


@app.post("/screenshot")
async def screenshot():
    """
    Capture a screenshot of the current page.

    Returns a base64-encoded JPEG image (quality 70).
    """
    return await run_op("screenshot", client.screenshot)


@app.get("/tabs")
async def list_tabs():
    """List all open browser tabs."""
    return await run_op("get_tabs", client.get_tabs)


@app.post("/tabs/scan")
async def scan_tabs():
    """Extract content from ALL open tabs WITHOUT switching.

    Opens a temporary CDP WS connection to each tab, evaluates JS
    to get title/URL/text, and returns everything in one response.

    Much faster than sequential switch_tab + get_text — no tab
    switching overhead, and the active tab stays unchanged.
    """
    return await run_op("scan_all_tabs", client.scan_all_tabs)


@app.post("/tabs/deep-scan/{tab_id}")
async def deep_scan_tab(tab_id: str):
    """Deep-extract ALL content from a tab: sub-tabs, iframes, meta.

    Switches to the tab, then runs a comprehensive JS engine that:
    - Detects all sub-tab navigation (hash links, data-tab, ARIA tabs)
    - Clicks each one and captures the visible content
    - Extracts same-origin iframe content
    - Returns everything in one structured JSON response

    One call replaces: switch_tab + N× (click + get_text) + iframe scan.
    """
    return await run_op("deep_scan_tab", client.deep_scan_tab, tab_id)


@app.post("/switch_tab/{tab_id}")
async def switch_tab(tab_id: str):
    """Switch the active context to the tab identified by *tab_id*."""
    return await run_op("switch_tab", client.switch_tab, tab_id)


@app.post("/get_text")
async def get_text():
    """Return the visible text content of the current page."""
    return await run_op("get_text", client.get_page_text)


@app.post("/disconnect")
async def disconnect():
    """Disconnect from Chrome CDP."""
    start = time.monotonic()
    try:
        result = await client.disconnect()
        elapsed = (time.monotonic() - start) * 1000
        state["cdp_url"] = None
        log_operation("disconnect", "success", elapsed, str(result)[:200])
        await broadcast_state()
        return {"status": "ok", "operation": "disconnect", "result": result}
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        logger.exception("Disconnect failed")
        log_operation("disconnect", "error", elapsed, str(exc))
        await broadcast_state()
        return {"status": "error", "operation": "disconnect", "error": str(exc)}


# ---------------------------------------------------------------------------
# REST endpoints — new: screenshots & PDF
# ---------------------------------------------------------------------------


@app.post("/full_screenshot")
async def full_screenshot(body: FullScreenshotRequest | None = None):
    """
    Capture a full-page screenshot.

    Captures the entire scrollable page, not just the viewport.
    Optional body: {"quality": 70} (default 70).
    """
    quality = body.quality if body else 70
    return await run_op("full_screenshot", client.full_page_screenshot, quality)


@app.post("/element_screenshot")
async def element_screenshot(body: ElementScreenshotRequest):
    """
    Capture a screenshot of a specific DOM element.

    Body: {"selector": "css-selector", "quality": 80}
    """
    return await run_op("element_screenshot", client.element_screenshot, body.selector, body.quality)


@app.post("/pdf")
async def pdf_export(body: PDFRequest | None = None):
    """
    Generate a PDF of the current page.

    Optional body: {"options": {...}} with PDF options (landscape, printBackground,
    paperWidth, paperHeight, marginTop, marginBottom, marginLeft, marginRight, scale).
    """
    options = body.options if body else {}
    return await run_op("pdf", client.pdf, options)


# ---------------------------------------------------------------------------
# REST endpoints — new: cookies
# ---------------------------------------------------------------------------


@app.get("/cookies")
async def get_cookies(truncate: bool = Query(False, description="Truncate cookie values to save bandwidth")):
    """Get all browser cookies.

    Use ?truncate=true to truncate long cookie values (saves bandwidth).
    """
    result = await run_op("get_cookies", client.get_cookies)
    if truncate and result.get("result", {}).get("cookies"):
        for c in result["result"]["cookies"]:
            if len(c.get("value", "")) > 80:
                c["value"] = c["value"][:40] + "..." + c["value"][-37:]
    return result


@app.post("/set_cookie")
async def set_cookie(body: SetCookieRequest):
    """
    Set a browser cookie.

    Body: {"name": "...", "value": "...", "domain": "...", "path": "/",
           "secure": false, "httpOnly": false}
    """
    kwargs: dict[str, Any] = {"secure": body.secure, "httpOnly": body.httpOnly}
    if body.domain is not None:
        kwargs["domain"] = body.domain
    if body.path is not None:
        kwargs["path"] = body.path
    return await run_op("set_cookie", client.set_cookie, body.name, body.value, **kwargs)


@app.post("/clear_cookies")
async def clear_cookies():
    """Clear all browser cookies."""
    return await run_op("clear_cookies", client.clear_cookies)


# ---------------------------------------------------------------------------
# REST endpoints — new: DOM query
# ---------------------------------------------------------------------------


@app.post("/dom_query")
async def dom_query(body: DOMQueryRequest):
    """
    Query DOM elements by CSS selector.

    Body: {"selector": "css-selector", "attribute": "href"} (attribute optional).
    Returns text content of each match, or a specific attribute if given.
    """
    return await run_op("dom_query", client.dom_query, body.selector, body.attribute)


@app.post("/dom_click_all")
async def dom_click_all(body: DOMClickAllRequest):
    """
    Click ALL elements matching a selector (e.g. all 'Load more' buttons).

    Body: {"selector": "css-selector"}
    """
    return await run_op("dom_click_all", client.dom_click_all, body.selector)


# ---------------------------------------------------------------------------
# REST endpoints — new: batch script
# ---------------------------------------------------------------------------


@app.post("/script")
async def execute_script(body: ScriptRequest):
    """
    Execute a batch of operations sequentially.

    Body: {"steps": [{"action": "navigate", "params": {"url": "..."}}, ...]}

    Supported actions: navigate, click, type, eval, screenshot,
    full_page_screenshot, element_screenshot, wait, scroll, get_text, pdf.
    """
    return await run_op("execute_script", client.execute_script, body.steps)


# ---------------------------------------------------------------------------
# REST endpoints — new: network monitoring
# ---------------------------------------------------------------------------


@app.post("/network/start")
async def network_start():
    """Start tracking network requests."""
    return await run_op("network_start", client.start_network_monitoring)


@app.post("/network/stop")
async def network_stop():
    """Stop tracking network requests."""
    return await run_op("network_stop", client.stop_network_monitoring)


@app.get("/network/log")
async def network_log():
    """Get collected network request/response log."""
    return await run_op("network_log", client.get_network_log)


@app.post("/network/clear")
async def network_clear():
    """Clear the network request log."""
    return await run_op("network_clear", client.clear_network_log)


# ---------------------------------------------------------------------------
# REST endpoints — new: session management
# ---------------------------------------------------------------------------


@app.post("/session/save")
async def session_save():
    """
    Save the current browser session (cookies + localStorage + sessionStorage).

    Returns a session object that can be restored later via /session/restore.
    """
    return await run_op("session_save", client.session_save)


@app.post("/session/restore")
async def session_restore(body: SessionRestoreRequest):
    """
    Restore a previously saved browser session.

    Body: {"session": {...}} where session is the value returned by /session/save.
    """
    return await run_op("session_restore", client.session_restore, body.session)


# ---------------------------------------------------------------------------
# REST endpoints — new: health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns uptime, memory usage, connection status, and operation count.
    Does not require CDP connection.
    No authentication is required (excluded from auth and rate-limiting middleware).
    """
    uptime_secs = time.monotonic() - start_time if start_time else 0.0
    memory_mb = _get_memory_mb()
    return {
        "status": "ok",
        "version": app.version,
        "uptime_seconds": round(uptime_secs, 2),
        "memory_mb": memory_mb,
        "connected": client.is_connected,
        "tabs_count": client.tabs_count,
        "operation_count": len(operation_log),
    }


@app.get("/ready")
async def readiness_check():
    """
    Readiness probe endpoint.

    Returns 200 when the CDP client is connected, 503 when not.
    Does not require CDP connection.
    No authentication is required (excluded from auth and rate-limiting middleware).
    """
    if client.is_connected:
        return {
            "status": "ok",
            "ready": True,
            "connected": True,
        }
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=503,
        content={"status": "error", "ready": False, "connected": False, "detail": "CDP not connected"},
    )


# ---------------------------------------------------------------------------
# REST endpoints — new: tab management
# ---------------------------------------------------------------------------


@app.post("/tab/new")
async def tab_new(body: NewTabRequest):
    """Open a new browser tab to the specified URL (default: about:blank)."""
    return await run_op("open_new_tab", client.open_new_tab, body.url)


@app.post("/tab/close/{tab_id}")
async def tab_close(tab_id: str):
    """Close a browser tab by its target ID."""
    return await run_op("close_tab", client.close_tab, tab_id)


# ---------------------------------------------------------------------------
# REST endpoints — new: JavaScript toggle
# ---------------------------------------------------------------------------


@app.post("/javascript/disable")
async def javascript_disable():
    """Disable JavaScript execution on the current page."""
    return await run_op("disable_javascript", client.disable_javascript)


@app.post("/javascript/enable")
async def javascript_enable():
    """Re-enable JavaScript execution on the current page."""
    return await run_op("enable_javascript", client.enable_javascript)


# ---------------------------------------------------------------------------
# REST endpoints — new: performance metrics
# ---------------------------------------------------------------------------


@app.get("/metrics")
async def get_metrics():
    """Get page performance metrics (timing, memory, etc.)."""
    return await run_op("get_performance_metrics", client.get_performance_metrics)


# ---------------------------------------------------------------------------
# WebSocket — real-time status streaming
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(ws_clients))

    # Send the current state immediately on connect
    try:
        await ws.send_json({
            "type": "hello",
            "state": dict(state),
            "recent_log": operation_log[-10:],
        })
    except Exception:
        ws_clients.discard(ws)
        return

    try:
        while True:
            data = await ws.receive_text()

            # Plain ping/pong keep-alive
            if data == "ping":
                await ws.send_json({"type": "pong"})
                continue

            # JSON action messages
            try:
                msg = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            action = msg.get("action", "")
            start = time.monotonic()

            try:
                if action == "status":
                    await ws.send_json({
                        "type": "status",
                        "connected": client.is_connected,
                        "tabs_count": client.tabs_count,
                        "last_operation": state["last_operation"],
                    })

                elif action == "screenshot":
                    quality = msg.get("quality", 0)
                    result = await client.screenshot(quality=quality)
                    await ws.send_json({
                        "type": "screenshot",
                        "data": result.get("data", ""),
                        "format": result.get("format", "jpeg"),
                        "size": result.get("size", 0),
                    })

                elif action == "eval":
                    js = msg.get("js", "")
                    result = await client.evaluate(js)
                    await ws.send_json({
                        "type": "eval_result",
                        "result": result,
                    })

                elif action == "navigate":
                    url = msg.get("url", "")
                    client._tabs_cache = []
                    client._tabs_cache_ts = 0
                    result = await client.navigate(url)
                    await ws.send_json({
                        "type": "navigate_result",
                        "result": result,
                    })

                elif action == "click":
                    selector = msg.get("selector", "")
                    result = await client.click(selector)
                    await ws.send_json({
                        "type": "click_result",
                        "result": result,
                    })

                elif action == "get_text":
                    result = await client.get_page_text()
                    await ws.send_json({
                        "type": "text_result",
                        "result": result,
                    })

                elif action == "get_cookies":
                    result = await client.get_cookies()
                    truncate = msg.get("truncate", False)
                    if truncate and result.get("cookies"):
                        for c in result["cookies"]:
                            if len(c.get("value", "")) > 80:
                                c["value"] = c["value"][:40] + "..." + c["value"][-37:]
                    await ws.send_json({
                        "type": "cookies_result",
                        "result": result,
                    })

                elif action == "batch":
                    """Execute multiple steps in one WS message."""
                    steps = msg.get("steps", [])
                    results = []
                    for i, step in enumerate(steps):
                        step_action = step.get("action", "")
                        try:
                            if step_action == "navigate":
                                client._tabs_cache = []
                                client._tabs_cache_ts = 0
                                r = await client.navigate(step.get("url", ""))
                            elif step_action == "eval":
                                r = await client.evaluate(step.get("js", ""))
                            elif step_action == "click":
                                r = await client.click(step.get("selector", ""))
                            elif step_action == "screenshot":
                                r = await client.screenshot(quality=step.get("quality", 0))
                            elif step_action == "get_text":
                                r = await client.get_page_text()
                            else:
                                r = {"status": "error", "error": f"Unknown action: {step_action}"}
                            results.append({"step": i, "action": step_action, "result": r, "status": "ok"})
                        except Exception as e:
                            results.append({"step": i, "action": step_action, "result": str(e), "status": "error"})
                    elapsed = (time.monotonic() - start) * 1000
                    await ws.send_json({
                        "type": "batch_result",
                        "steps": len(steps),
                        "results": results,
                        "duration_ms": round(elapsed, 2),
                    })

                else:
                    await ws.send_json({
                        "type": "error",
                        "message": f"Unknown action: {action}",
                    })

                # Log the action
                elapsed = (time.monotonic() - start) * 1000
                log_operation(f"ws:{action}", "success", elapsed, "")

            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                log_operation(f"ws:{action}", "error", elapsed, str(e))
                await ws.send_json({
                    "type": "error",
                    "action": action,
                    "message": str(e),
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        ws_clients.discard(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(ws_clients))


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    logger.info("Serving static files from %s", STATIC_DIR)
else:
    logger.warning("Static directory not found: %s", STATIC_DIR)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Run the server with uvicorn."""
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
