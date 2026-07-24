"""
FastAPI REST API server for browser-helper.

Wraps the CDP client and provides REST + WebSocket endpoints
for browser automation. Serves a GUI dashboard and streams
real-time status updates over WebSocket.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cdp_client import CDPClient

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

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Browser Helper API",
    version="1.0.0",
    description="REST + WebSocket API for browser automation via CDP.",
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
    cdp_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log_operation(
    operation: str,
    status: str,
    duration_ms: float,
    details: str = "",
) -> dict[str, Any]:
    """Append an operation entry to the ring buffer and update global state."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
async def connect(body: Optional[ConnectRequest] = None):
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
        # Keep the connection alive and handle incoming pings / messages
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
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
# Startup — try auto-connect to CDP
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup():
    logger.info("Browser Helper API starting up ...")
    try:
        result = await client.connect()
        state["connected"] = True
        state["cdp_url"] = result.get("cdp_url", "auto-discovered")
        logger.info("Auto-connected to CDP at %s", state["cdp_url"])
    except Exception as exc:
        logger.warning("Auto-connect to CDP failed (server will start anyway): %s", exc)


@app.on_event("shutdown")
async def on_shutdown():
    """Clean up CDP connection and WS clients on shutdown."""
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
