"""
FastAPI REST API server for browser-helper.

Wraps the CDP client and provides REST + WebSocket endpoints
for browser automation. Serves a GUI dashboard and streams
real-time status updates over WebSocket.
"""

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
import zipfile
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

# Python 3.10 compatibility: datetime.UTC is 3.11+
try:
    _UTC = datetime.UTC
except AttributeError:
    _UTC = UTC
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Auth / rate limiting
# ---------------------------------------------------------------------------
from playwright_backend import BackendManager as _BackendManager
backend_manager = _BackendManager()

from artifact_store import ArtifactStore
from agent_runtime import (ElementNotFoundError, SnapshotStore, StaleSnapshotError, diff_snapshots, paginate_snapshot)
from agent_navigation import (
    AccessibilitySnapshot,
    AccessibilityTreeBuilder,
    available_actions,
    discover_forms,
    extract_by_schema,
    validate_expectations,
)
from baseline_manager import BaselineManager
from cdp_client import CDPClient
from chrome_manager import ChromeManager
from headless_manager import HeadlessManager
from profile_manager import Profile, ProfileManager
from screenshot_diff import ScreenshotDiffEngine
from settings_manager import SettingsManager

from proxy_manager import ProxyParseError, ProxyPool

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
    # ── Auto-launch Chrome (if --launch-chrome was passed to run.py) ──
    if os.environ.get("CHROME_AUTO_LAUNCH") == "1":
        launch_kwargs = {}
        profile = os.environ.get("CHROME_AUTO_PROFILE")
        port = os.environ.get("CHROME_AUTO_PORT")
        if profile:
            launch_kwargs["profile_dir"] = profile
        if port:
            launch_kwargs["port"] = int(port)
        try:
            result = await chrome_mgr.launch(**launch_kwargs)
            if result.get("status") == "ok":
                port_str = result.get("port", "?")
                pid = result.get("pid", "?")
                logger.info("Chrome auto-launched on port %s (PID %s)", port_str, pid)
                print(f"✅ Chrome launched on port {port_str} (PID {pid})")
                # If auto-launch succeeded, try CDP connect using the launched port
                if not client.is_connected and result.get("cdp_http_url"):
                    try:
                        cdp_url = result["cdp_http_url"]
                        logger.info("Auto-connecting to launched Chrome at %s", cdp_url)
                        # Update the client's base CDP URL before connecting
                        client.cdp_http_url = cdp_url.rstrip("/")
                        conn = await client.connect()
                        state["connected"] = True
                        state["cdp_url"] = conn.get("cdp_url", cdp_url)
                    except Exception as exc2:
                        logger.warning("Auto-connect to launched Chrome failed: %s", exc2)
            else:
                logger.warning("Chrome auto-launch failed: %s", result.get("error", "unknown"))
        except Exception as exc3:
            logger.warning("Chrome auto-launch exception: %s", exc3)
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

# Settings and Chrome process manager
settings_mgr = SettingsManager()
chrome_mgr = ChromeManager(settings_mgr)

# Headless session manager
headless_mgr = HeadlessManager()

# Profile manager
profile_mgr = ProfileManager()

# Baseline manager for visual regression testing
baseline_mgr = BaselineManager()
artifact_store = ArtifactStore()
snapshot_store = SnapshotStore()
ax_builder = AccessibilityTreeBuilder()
ax_snapshots: dict[str, AccessibilitySnapshot] = {}
ax_snapshot_pins: dict[str, int] = {}
agent_recordings: dict[str, dict[str, Any]] = {}
active_recording_id: str | None = None

# Proxy pool for anti-detection proxy rotation
proxy_pool = ProxyPool()

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
    format: str = "raw"  # "raw" | "pretty" | "structured"


class ClickRequest(BaseModel):
    selector: str


class TypeRequest(BaseModel):
    selector: str
    text: str


class ConnectRequest(BaseModel):
    cdp_url: str | None = None
    proxy: str | None = None


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


# ─── Backend switch model (P1-1) ────────────────────────────────


class BackendSwitchRequest(BaseModel):
    backend: str


# ─── Settings & Chrome management models ────────────────────────


class SettingsRequest(BaseModel):
    chrome_profile_dir: str | None = None
    chrome_debug_port: int | None = None
    chrome_path: str | None = None


class LaunchRequest(BaseModel):
    profile_dir: str | None = None
    port: int | None = None
    chrome_path: str | None = None


class StopRequest(BaseModel):
    pid: int | None = None


class DOMClickAllRequest(BaseModel):
    selector: str


class ScriptRequest(BaseModel):
    steps: list[dict]


class SessionRestoreRequest(BaseModel):
    session: dict


# ─── Proxy management models ────────────────────────────────


class ProxyEntrySchema(BaseModel):
    url: str
    type: str | None = None
    tags: list[str] = []


class AddProxiesRequest(BaseModel):
    proxies: list[ProxyEntrySchema]


class HealthCheckRequest(BaseModel):
    proxy_id: str | None = None


class NewTabRequest(BaseModel):
    url: str = "about:blank"


# ─── New: Smart interaction models ──────────────────────────────


class FormFillRequest(BaseModel):
    fields: list[dict] | None = None
    selector: str | None = None
    text: str | None = None
    timeout: int = 5

    @model_validator(mode="before")
    @classmethod
    def normalize_shorthand(cls, data):
        """Normalise single-field shorthand {selector, text} into {fields: [{selector, text}]}.

        Accept both ``{"selector": "#email", "text": "hello"}`` (shorthand)
        and ``{"fields": [{"label": "Email", "value": "hello"}]}`` (existing).
        """
        if isinstance(data, dict) and "fields" not in data and "selector" in data and "text" in data:
            data["fields"] = [
                {"selector": data["selector"], "text": data["text"]},
            ]
        return data

    @field_validator("fields", mode="before")
    @classmethod
    def coerce_field_objects(cls, v):
        """Convert FormFillField objects to dicts for backward compatibility."""
        if v is not None:
            return [
                f.model_dump() if isinstance(f, BaseModel) else f
                for f in v
            ]
        return v

    @model_validator(mode="after")
    def ensure_fields(self):
        """Ensure *fields* is populated — one of the two formats must be provided."""
        if self.fields is None:
            raise ValueError(
                "Either 'fields' or 'selector' + 'text' must be provided"
            )
        return self


class FormFillField(BaseModel):
    """A single form field descriptor for smart_form_fill.

    Lookup order (any combination works):
      1. ``selector`` — direct CSS selector (fastest)
      2. ``label``    — ``<label>`` text, placeholder, name, aria-label (default)
      3. ``placeholder`` — exact placeholder match
      4. ``nth``      — 0-based index among all matching fields (use with label/selector)
    """
    value: str
    label: str | None = None
    selector: str | None = None
    placeholder: str | None = None
    nth: int = 0
    type: str | None = None


class WaitRequest(BaseModel):
    selector: str
    timeout: int = 10
    visible: bool = True


class ClickTextRequest(BaseModel):
    text: str
    timeout: int = 5
    container_selector: str | None = None
    nth: int = 0


class ClickLabelRequest(BaseModel):
    text: str
    timeout: int = 5

    @model_validator(mode="before")
    @classmethod
    def populate_text_from_label(cls, data):
        """Accept 'label' field as alias for 'text'."""
        if isinstance(data, dict):
            if "label" in data and "text" not in data:
                data["text"] = data["label"]
        return data


# ─── v0.8: New request models ──────────────────────────────────


class ClickCoordinatesRequest(BaseModel):
    """Pixel-precise click coordinates."""
    x: int
    y: int
    button: str = "left"
    click_count: int = 1


class DropdownSelectRequest(BaseModel):
    """Simplified dropdown selection by label text."""
    label: str
    option: str | None = None
    option_value: str | None = None
    timeout: int = 5


class WaitVisibleRequest(BaseModel):
    """Wait for an element to be present and visible."""
    selector: str
    timeout: int = 10


# ─── v0.8: API alias configuration ──────────────────────────────


API_ALIASES: dict[str, dict] = {
    "/dropdown/select": {
        "method": "POST",
        "target": "/form/select",
        "transform": True,
    },
    "/wait/visible": {
        "method": "POST",
        "target": "/wait",
        "fixed_params": {"visible": True},
    },
    "/api/tabs": {
        "method": "GET",
        "target": "/tabs",
    },
    "/api/screenshot": {
        "method": "POST",
        "target": "/screenshot",
    },
}


# ─── New: Checkbox operation models ────────────────────────────


class CheckboxRequest(BaseModel):
    """Single checkbox operation: target one checkbox/radio by label text."""
    text: str
    timeout: int = 5


class CheckboxBatchRequest(BaseModel):
    """Batch checkbox operation: target multiple checkboxes/radios by label texts."""
    texts: list[str]
    timeout: int = 5


# ─── New: Upload, find element models ────────────────────────────


class UploadRequest(BaseModel):
    selector: str
    files: list[str]


class FindElementRequest(BaseModel):
    text: str
    tag: str | None = None


# ─── New: Form select / iframe / page outline models ─────────


class FormSelectRequest(BaseModel):
    by: str  # "label", "name", "selector"
    text_or_value: str
    option_value: str | None = None


class IframeRequest(BaseModel):
    index: int = 0


# ─── New: Page analysis models ──────────────────────────────


class WaitTextRequest(BaseModel):
    text: str
    timeout: int = 10
    present: bool = True


class WaitNavigationRequest(BaseModel):
    timeout: int = 10
    quiet_ms: int = 500


class AnalyzePageRequest(BaseModel):
    """Empty — /page/analyze takes no args. Exists for consistency."""


class WorkflowStep(BaseModel):
    action: str
    params: dict = {}


class WorkflowRequest(BaseModel):
    steps: list[WorkflowStep]


# ─── Headless session models ────────────────────────────────────


class HeadlessLaunchRequest(BaseModel):
    profile_dir: str | None = None
    port: int | None = None
    profile: str | None = None
    extensions: list[str] | None = None
    proxy_url: str | None = None
    proxy_strategy: str | None = None
    proxy_group: str | None = None


class HeadlessCloseRequest(BaseModel):
    session_id: str


class HeadlessNavigateRequest(BaseModel):
    session_id: str
    url: str


class HeadlessEvalRequest(BaseModel):
    session_id: str
    expression: str


class HeadlessScreenshotRequest(BaseModel):
    session_id: str


class HeadlessBatchScreenshotRequest(BaseModel):
    session_id: str
    urls: list[str]


class AgentObserveRequest(BaseModel):
    condensed: bool = True
    mode: str = "semantic"
    scope: str = "page"
    include: list[str] | None = None
    interactive_only: bool = False
    changed_only: bool = False
    max_nodes: int = 250
    max_chars: int = 6000
    max_elements: int = 80
    cursor: str | None = None
    snapshot_id: str | None = None
    since_snapshot_id: str | None = None
    fallback: str | None = None
    search_text: str | None = None
    auto_modal: bool = True
    include_hidden: bool = False


class AgentTarget(BaseModel):
    snapshot_id: str | None = None
    element_id: str | None = None
    ref: str | None = None
    role: str | None = None
    name: str | None = None
    within: str | None = None
    backend_node_id: int | None = None
    selector: str | None = None
    text: str | None = None
    label: str | None = None


class AgentActionRequest(BaseModel):
    action: str
    target: AgentTarget | None = None
    url: str | None = None
    value: str | None = None
    fields: list[dict] | None = None
    option: str | None = None
    timeout: int = 10
    expression: str | None = None
    quality: int = 80
    steps: list[dict] | None = None
    expect: dict | None = None
    verify_after: dict | None = None
    timeout_ms: int | None = None
    recovery: dict | None = None
    strategy: list[str] | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    pin_snapshot: bool = True
    auto_recover: bool = True
    observe_after: bool = True


class AgentFormFillRequest(BaseModel):
    form_ref: str
    data: dict[str, Any]
    validate_result: bool = Field(default=True, alias="validate")


class AgentFormDiscoverRequest(BaseModel):
    snapshot_id: str | None = None
    scope: str = "page"


class AgentExtractRequest(BaseModel):
    extraction_schema: dict[str, Any] = Field(alias="schema")
    scope: dict[str, Any] | str | None = None
    include_evidence: bool = True
    snapshot_id: str | None = None


class AgentExecuteTaskRequest(BaseModel):
    goal: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    return_options: dict[str, Any] = Field(default_factory=dict, alias="return")



class AgentRecordRequest(BaseModel):
    start: bool = True
    name: str | None = None


class AgentReplayRequest(BaseModel):
    recording_id: str | None = None
    recorded_id: str | None = None
    on_error: str = "stop"
    data_overrides: dict[str, Any] = Field(default_factory=dict)

    @property
    def stop_on_error(self) -> bool:
        return self.on_error == "stop"

    @property
    def effective_recording_id(self) -> str:
        value = self.recorded_id or self.recording_id
        if not value:
            raise ValueError("recorded_id is required")
        return value



# ─── Profile management models ────────────────────────────────


class ProfileCreateRequest(BaseModel):
    name: str
    extensions: list[str] | None = None
    description: str = ""
    tags: list[str] | None = None
    resource_limits: dict | None = None


class ProfileUpdateRequest(BaseModel):
    description: str | None = None
    tags: list[str] | None = None
    resource_limits: dict | None = None


class ExtensionRequest(BaseModel):
    path: str


class ImportRequest(BaseModel):
    path: str


# ─── Visual regression testing models ────────────────────────


class ViewportModel(BaseModel):
    width: int
    height: int


class BaselineRequest(BaseModel):
    url: str
    profile: str | None = None
    quality: int = 70
    viewport: dict | None = None


class CompareRequest(BaseModel):
    url: str
    profile: str | None = None
    threshold: float = 0.001
    quality: int = 70

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")
        return v


class DeleteBaselineRequest(BaseModel):
    url: str
    profile: str | None = None


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

def api_success(operation: str, data: Any = None, status_code: int = 200, meta: dict | None = None):
    payload = {"status": "ok", "operation": operation, "data": data, "error": None, "meta": meta or {}}
    # Deprecated alias retained for one release for existing clients.
    payload["result"] = data
    return payload


def api_error(operation: str, code: str, message: str, status_code: int = 400, details: Any = None):
    return JSONResponse(status_code=status_code, content={
        "status": "error", "operation": operation, "data": None,
        "error": {"code": code, "message": message, "details": details}, "meta": {},
    })


def result_status(result: dict, default: int = 400) -> int:
    code = result.get("code", "") if isinstance(result, dict) else ""
    if code in {"session_not_found", "element_not_found", "artifact_not_found"}:
        return 404
    if code in {"stale_snapshot", "conflict"}:
        return 409
    if code in {"cdp_error", "not_connected"}:
        return 503
    if code == "timeout":
        return 504
    return default


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
        "timestamp": datetime.now(_UTC).isoformat(),
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
        return api_success(operation, result)
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        logger.exception("Operation '%s' failed", operation)
        log_operation(operation, "error", elapsed, str(exc))
        await broadcast_state()
        status = 504 if isinstance(exc, TimeoutError) else 503 if "connect" in str(exc).lower() else 400
        return api_error(operation, "operation_failed", str(exc), status)


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
    proxy = body.proxy if body else None

    # If proxy is provided, launch/restart Chrome with --proxy-server
    if proxy:
        try:
            launch_result = await chrome_mgr.launch(proxy=proxy)
            if launch_result.get("status") != "ok":
                logger.warning("Chrome launch with proxy returned: %s", launch_result.get("error"))
        except Exception as exc:
            logger.warning("Chrome launch with proxy failed: %s", exc)
    # If a CDP HTTP URL is provided (not a tab URL), update the client base URL
    if cdp_url and ("/json" not in cdp_url) and ("/devtools" not in cdp_url):
        # Treat as CDP HTTP base URL (e.g. "http://127.0.0.1:9556")
        client.cdp_http_url = cdp_url.rstrip("/")
        cdp_url = None  # Don't pass as tab filter
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


@app.post("/click/coordinates")
async def click_coordinates(body: ClickCoordinatesRequest):
    """Click at pixel coordinates using CDP Input.dispatchMouseEvent.

    Accepts ``{x, y}`` for pixel-precise clicks, with optional
    ``button`` (default ``"left"``) and ``click_count`` (default 1).
    Useful for canvas, image maps, and elements that don't have a CSS selector.
    """
    return await run_op("click_coordinates", client.click_coordinates,
                        body.x, body.y, body.button, body.click_count)


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


@app.post("/wait/visible")
async def wait_visible(body: WaitVisibleRequest):
    """Wait until an element matching *selector* is both present and visible.

    Polls every 200ms. Unlike ``/wait``, this explicitly requires
    the element's ``offsetParent`` to be non-null (i.e. visible).
    Returns element tag, text, and rect on success.
    """
    return await run_op("wait_visible", client.wait_visible,
                        body.selector, body.timeout)


@app.post("/click/text")
async def click_by_text(body: ClickTextRequest, confirm: str | None = Query(None, description="Post-click confirmation: 'screenshot' for base64 JPEG, 'analyze' for state comparison")):
    """Click an element by its visible text content.

    Searches a/button/span elements whose text matches.
    No CSS selector needed — just the text you see on screen.

    Optional ``container_selector`` restricts search to a specific
    container (e.g. "#accept-modal" to click inside a modal).

    Optional ``?confirm=screenshot`` or ``?confirm=analyze`` appends
    post-click screenshot / state comparison to the response.
    """
    # Capture before-state for confirmation
    if confirm:
        try:
            before = await client.analyze_page()
            client._before_visual_state = before.get("page", {}).get("visual_state", {})
        except Exception:
            client._before_visual_state = {}
    result = await run_op("click_text", client.click_by_text,
                          body.text, body.timeout, body.container_selector, body.nth)
    if confirm and result.get("status") == "ok":
        try:
            if confirm == "screenshot":
                conf = await client._confirm_with_screenshot()
            elif confirm == "analyze":
                conf = await client._confirm_with_analyze()
            else:
                conf = None
            if conf:
                result["confirmation"] = conf
        except Exception:
            pass
    return result


@app.post("/click/label")
async def click_label(body: ClickLabelRequest, confirm: str | None = Query(None, description="Post-click confirmation: 'screenshot' for base64 JPEG, 'analyze' for state comparison")):
    """Click a <label> element by its visible text.

    Framework-safe: clicks actual HTML <label> elements that toggle
    the associated input (React/Vue/Symfony forms only respond to
    real label clicks). Use this for radio buttons, checkboxes, and
    any field where click_by_text doesn't register with the framework.

    Optional ``?confirm=screenshot`` or ``?confirm=analyze`` appends
    post-click screenshot / state comparison to the response.
    """
    if confirm:
        try:
            before = await client.analyze_page()
            client._before_visual_state = before.get("page", {}).get("visual_state", {})
        except Exception:
            client._before_visual_state = {}
    result = await run_op("click_label", client.click_label,
                          body.text, body.timeout)
    if confirm and result.get("status") == "ok":
        try:
            if confirm == "screenshot":
                conf = await client._confirm_with_screenshot()
            elif confirm == "analyze":
                conf = await client._confirm_with_analyze()
            else:
                conf = None
            if conf:
                result["confirmation"] = conf
        except Exception:
            pass
    return result


@app.post("/click/label/text")
async def click_label_text(body: ClickLabelRequest):
    """Alias for /click/label — click a <label> by visible text."""
    return await click_label(body)


# ─── New: Checkbox operation endpoints ──────────────────────────


@app.post("/checkbox/select")
async def checkbox_select(body: CheckboxRequest | CheckboxBatchRequest, confirm: str | None = Query(None, description="Post-operation confirmation: 'screenshot' for base64 JPEG, 'analyze' for state comparison")):
    """Check/select a checkbox or radio by label text.

    Single mode: ``{"text": "Email notifications", "timeout": 5}``
    Batch mode:  ``{"texts": ["Email", "SMS"], "timeout": 5}``

    Framework-safe: uses the same label-resolution strategy as
    ``analyze_page()`` and clicks the associated <label> to toggle.

    Optional ``?confirm=screenshot`` or ``?confirm=analyze`` appends
    post-operation screenshot / state comparison to the response.
    """
    if confirm:
        try:
            before = await client.analyze_page()
            client._before_visual_state = before.get("page", {}).get("visual_state", {})
        except Exception:
            client._before_visual_state = {}
    if isinstance(body, CheckboxBatchRequest):
        result = await run_op("checkbox_select_batch",
                              client.checkbox_set_state_batch,
                              body.texts, True, body.timeout)
    else:
        result = await run_op("checkbox_select",
                              client.checkbox_set_state,
                              body.text, True, body.timeout)
    if confirm and result.get("status") == "ok":
        try:
            if confirm == "screenshot":
                conf = await client._confirm_with_screenshot()
            elif confirm == "analyze":
                conf = await client._confirm_with_analyze()
            else:
                conf = None
            if conf:
                result["confirmation"] = conf
        except Exception:
            pass
    return result


@app.post("/checkbox/deselect")
async def checkbox_deselect(body: CheckboxRequest | CheckboxBatchRequest, confirm: str | None = Query(None, description="Post-operation confirmation: 'screenshot' for base64 JPEG, 'analyze' for state comparison")):
    """Uncheck/deselect a checkbox or radio by label text.

    Single mode: ``{"text": "SMS notifications", "timeout": 5}``
    Batch mode:  ``{"texts": ["Email", "SMS"], "timeout": 5}``

    Optional ``?confirm=screenshot`` or ``?confirm=analyze`` appends
    post-operation screenshot / state comparison to the response.
    """
    if confirm:
        try:
            before = await client.analyze_page()
            client._before_visual_state = before.get("page", {}).get("visual_state", {})
        except Exception:
            client._before_visual_state = {}
    if isinstance(body, CheckboxBatchRequest):
        result = await run_op("checkbox_deselect_batch",
                              client.checkbox_set_state_batch,
                              body.texts, False, body.timeout)
    else:
        result = await run_op("checkbox_deselect",
                              client.checkbox_set_state,
                              body.text, False, body.timeout)
    if confirm and result.get("status") == "ok":
        try:
            if confirm == "screenshot":
                conf = await client._confirm_with_screenshot()
            elif confirm == "analyze":
                conf = await client._confirm_with_analyze()
            else:
                conf = None
            if conf:
                result["confirmation"] = conf
        except Exception:
            pass
    return result


# ─── New: Page analysis & wait endpoints ──────────────────────


@app.post("/page/analyze")
async def page_analyze(condensed: bool = Query(False, description="Enable condensed mode (strips nav/sidebar/footer)")):
    """Analyze the current page and return structured information.

    Returns a comprehensive snapshot of the page state in one call:
    - URL, title, visible buttons (with position, disabled, in_modal)
    - Open modals (with buttons, tabs, unread indicators)
    - Form fields (with labels, values, types)
    - Alert/success/error messages
    - Visible text preview

    Optional ``?condensed=true`` strips navigation/sidebar/footer
    and returns only main content with interactive elements.

    Replaces 3-4 separate eval() calls.
    """
    ensure_connected()
    try:
        raw = await (client.analyze_page_condensed() if condensed else client.analyze_page())
        snap = snapshot_store.add(raw)
        if isinstance(raw, dict):
            page = raw.get("page", raw)
            if isinstance(page, dict):
                page["snapshot_id"] = snap.snapshot_id
                page["elements"] = snap.elements
        return api_success("page_analyze_condensed" if condensed else "page_analyze", raw)
    except Exception as exc:
        return api_error("page_analyze", "operation_failed", str(exc), 400)


@app.post("/wait/text")
async def wait_text(body: WaitTextRequest):
    """Wait until *text* appears (or disappears) from the page.

    Polls every 300ms. Unlike /wait (CSS selector based), this watches
    the visible text content of the page body.

    Set ``present=false`` to wait for text to disappear.
    """
    return await run_op("wait_text", client.wait_for_text,
                        body.text, body.timeout, body.present)


@app.post("/wait/navigation")
async def wait_navigation(body: WaitNavigationRequest | None = None):
    """Wait until the page URL changes (SPA navigation).

    Stores the current URL, then polls until it changes.
    Returns the new URL and title when detected.
    Useful after clicking a link that triggers SPA routing.
    """
    timeout = body.timeout if body else 10
    return await run_op("wait_navigation", client.wait_for_navigation, timeout)


@app.post("/wait/network-idle")
async def wait_network_idle(body: WaitNavigationRequest | None = None):
    """Wait until the network has been quiet for a period.

    Polls CDP Network events.  Useful after form submissions or
    button clicks that trigger AJAX calls — ensures the next
    action won't race with in-flight network requests.

    *timeout*: max seconds to wait (default 10)
    *quiet_ms*: how many ms of silence confirms idle (default 500)
    """
    timeout = body.timeout if body else 10
    quiet_ms = body.quiet_ms if body else 500
    return await run_op("wait_for_network_idle", client.wait_for_network_idle,
                        timeout, quiet_ms)


@app.post("/page/diff")
async def page_diff(body: dict | None = None):
    """Compare current page state with a previous snapshot.

    Takes an optional *previous_snapshot* (the "page" dict from a
    prior /page/analyze response).  If omitted, returns the current
    snapshot as a baseline (call twice: baseline → action → diff).

    Returns only WHAT CHANGED (buttons added/removed, modals,
    error count, alerts, URL, text length) — LLM-friendly.
    """
    prev = (body or {}).get("previous_snapshot")
    return await run_op("page_diff", client.page_diff, prev)


# ─── New: File upload ─────────────────────────────────────────


@app.post("/upload")
async def upload_files(body: UploadRequest):
    """Upload files via a file input element.

    *selector* is a CSS selector for ``<input type="file">``.
    *files* is a list of absolute file paths on the local machine.

    Uses CDP DOM.setFileInputFiles — bypasses the OS file dialog.
    Works even when the input is hidden or styled with display:none.

    Example: {"selector": "#image-upload", "files": ["C:\\photos\\test.jpg"]}
    """
    return await run_op("upload_files", client.upload_files,
                        body.selector, body.files)


# ─── New: Page text extraction ────────────────────────────────


@app.post("/page/text")
async def page_text():
    """Extract the full visible text content of the current page.

    Returns the innerText of document.body — cleaner than raw HTML,
    preserves reading order, no script/style noise.

    Useful for LLM context extraction before deciding what to do.
    """
    return await run_op("get_page_text", client.get_page_text)


# ─── New: Find element by text ────────────────────────────────


@app.post("/page/find")
async def find_element(body: FindElementRequest):
    """Find a visible element by its text content.

    Returns position, CSS selector, tag, and attributes for all matches.
    Does NOT click — use /click/text to click.

    Optional *tag* restricts search (e.g. \"button\", \"a\", \"label\").

    Example: {"text": "Submit order", "tag": "button"}
    """
    return await run_op("find_element", client.find_element_by_text,
                        body.text, body.tag)


# ─── New: Form select / iframe / page outline ──────────────────


@app.post("/form/select")
async def form_select(body: FormSelectRequest):
    """Select an option from a <select> dropdown by label, name, or selector.

    ``by`` = \"label\" | \"name\" | \"selector\"
    ``text_or_value`` = label text, name attr, or CSS selector
    ``option_value`` = optional: select option by value instead of display text

    Examples:
      {\"by\": \"label\", \"text_or_value\": \"Country\", \"option_value\": \"HU\"}
      {\"by\": \"selector\", \"text_or_value\": \"#country\", \"option_value\": \"Hungary\"}
      {\"by\": \"name\", \"text_or_value\": \"country\", \"option_value\": \"HU\"}
    """
    return await run_op("form_select", client.form_select,
                        body.by, body.text_or_value, body.option_value)


@app.post("/form/select/by-label")
async def form_select_by_label(body: FormSelectRequest):
    """Alias for /form/select with by=label — select option by label text.

    Shorthand that defaults ``by`` to ``\"label\"`` for convenience.
    Accepts ``{\"text_or_value\": \"Country\", \"option_value\": \"HU\"}``.
    """
    return await form_select(FormSelectRequest(
        by="label",
        text_or_value=body.text_or_value,
        option_value=body.option_value,
    ))


@app.post("/dropdown/select")
async def dropdown_select(body: DropdownSelectRequest):
    """Select an option from a <select> dropdown by label text — one call.

    Simplified version of /form/select that assumes ``by=label``.
    Provide the visible label text (``label``) and the option text
    (``option``) or the option value (``option_value``).

    Example: ``{\"label\": \"Country\", \"option\": \"Hungary\"}``
    """
    return await run_op("dropdown_select", client.dropdown_select,
                        body.label, body.option, body.option_value, body.timeout)


@app.post("/page/iframe-text")
async def iframe_text(body: IframeRequest | None = None):
    """Extract text content from a specific iframe (index-based).

    *index*: which iframe (0 = first). -1 returns main page text.

    Returns the iframe's URL, title, and visible text.
    Cross-origin iframes return an error (CORS restriction).
    """
    idx = body.index if body else 0
    return await run_op("get_iframe_text", client.get_iframe_text, idx)


@app.post("/page/iframe/switch")
async def iframe_switch(body: IframeRequest | None = None):
    """Switch active context to a specific iframe.

    *index*: which iframe (0 = first). -1 switches back to main page.

    After switch, /click, /type, /page/analyze operate inside the iframe.
    """
    idx = body.index if body else 0
    return await run_op("switch_to_iframe", client.switch_to_iframe, idx)


@app.post("/page/outline")
async def page_outline():
    """Extract the page's heading hierarchy as a structured outline.

    Returns h1-h6 with text, id, position (x, y), and a snippet of the
    following paragraph.  Perfect for understanding long document structure
    without reading the full text — much cheaper than /page/text.
    """
    return await run_op("get_page_outline", client.get_page_outline)


# ─── Settings & Chrome management ──────────────────────────────


@app.get("/settings")
async def get_settings():
    """Return all saved settings (profile dir, debug port, Chrome path)."""
    return {
        "status": "ok",
        "settings": settings_mgr.get_all(),
    }


@app.post("/settings")
async def update_settings(body: SettingsRequest):
    """Update one or more settings (profile dir, debug port, Chrome path).

    Example: {"chrome_profile_dir": "C:\\Users\\me\\AppData\\Local\\Google\\Chrome\\User Data\\Profile 1", "chrome_debug_port": 9555}
    """
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"status": "ok", "message": "Nothing to update", "settings": settings_mgr.get_all()}
    settings_mgr.update(updates)
    logger.info("Settings updated: %s", updates)
    return {"status": "ok", "message": "Settings saved", "updated": updates, "settings": settings_mgr.get_all()}


@app.post("/browser/launch")
async def browser_launch(body: LaunchRequest | None = None):
    """Launch Chrome with remote debugging.

    Uses saved settings for profile dir, port, and Chrome path.
    You can override any of them per-request.

    If the configured port is busy (not Chrome), auto-increments
    up to +10 and saves the working port for next time.

    Returns the actual port, PID, and CDP URLs for connecting.
    """
    kwargs = {}
    if body:
        if body.profile_dir is not None:
            kwargs["profile_dir"] = body.profile_dir
        if body.port is not None:
            kwargs["port"] = body.port
        if body.chrome_path is not None:
            kwargs["chrome_path"] = body.chrome_path
    result = await chrome_mgr.launch(**kwargs)
    # Auto-configure CDP client to the launched port
    if result.get("status") == "ok" and result.get("cdp_http_url"):
        cdp_url = result["cdp_http_url"].rstrip("/")
        client.cdp_http_url = cdp_url
        # Auto-connect if not already connected
        if not client.is_connected:
            try:
                conn = await client.connect()
                state["connected"] = True
                state["cdp_url"] = conn.get("cdp_url", cdp_url)
                result["_auto_connected"] = True
                logger.info("Auto-connected to launched Chrome at %s", cdp_url)
            except Exception as exc:
                logger.warning("Auto-connect after launch failed: %s", exc)
    return {"status": "ok" if result.get("status") == "ok" else "error",
            "operation": "browser_launch",
            "result": result}


@app.post("/browser/stop")
async def browser_stop(body: StopRequest | None = None):
    """Stop Chrome (kill the managed process)."""
    kwargs = {}
    if body and body.pid is not None:
        kwargs["pid"] = body.pid
    result = await chrome_mgr.stop(**kwargs)
    return {"status": "ok", "operation": "browser_stop", "result": result}


@app.get("/browser/status")
async def browser_status():
    """Check if Chrome is running (port check, no CDP call)."""
    result = chrome_mgr.status()
    return {"status": "ok", "operation": "browser_status", "result": result}


@app.post("/screenshot")
async def screenshot():
    """
    Capture a screenshot of the current page.

    Returns a base64-encoded JPEG image (quality 70).
    """
    return await run_op("screenshot", client.screenshot)


@app.post("/api/screenshot")
async def api_screenshot_alias():
    """API alias: /api/screenshot -> /screenshot"""
    return await screenshot()


# ---------------------------------------------------------------------------
# REST endpoints — visual regression testing (screenshot baselines)
# ---------------------------------------------------------------------------


@app.post("/screenshot/baseline")
async def screenshot_baseline(body: BaselineRequest):
    """Capture the current page as a visual baseline.

    Takes a screenshot of the current page via CDP, saves it as
    a baseline image tied to the given URL (+ optional profile
    and viewport), and returns baseline metadata.

    Requires an active CDP connection.
    """
    ensure_connected()

    try:
        # Take screenshot via CDP
        screenshot_result = await client.screenshot()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Screenshot failed: {exc}",
        )

    image_data: str = screenshot_result.get("data", "")
    if not image_data:
        raise HTTPException(
            status_code=400,
            detail="Screenshot returned no data",
        )

    image_bytes = base64.b64decode(image_data)

    path = baseline_mgr.save_baseline(
        url=body.url,
        image_data=image_bytes,
        profile=body.profile,
        viewport=body.viewport,
    )

    stat = os.stat(path)

    return {
        "status": "ok",
        "baseline": {
            "url": body.url,
            "path": path,
            "size": stat.st_size,
            "timestamp": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        },
    }


@app.post("/screenshot/compare")
async def screenshot_compare(body: CompareRequest):
    """Compare the current page against its stored baseline.

    Takes a fresh screenshot via CDP, compares it to the
    previously stored baseline for this URL (+ profile/viewport),
    and returns a DiffResult with base64-encoded diff image.

    Requires an active CDP connection and an existing baseline.
    """
    ensure_connected()

    # Check baseline exists
    baseline_path = baseline_mgr.get_baseline(
        url=body.url,
        profile=body.profile,
    )
    if baseline_path is None:
        raise HTTPException(
            status_code=400,
            detail=f"No baseline found for URL: {body.url}",
        )

    # Take current screenshot
    try:
        screenshot_result = await client.screenshot()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Screenshot failed: {exc}",
        )

    image_data: str = screenshot_result.get("data", "")
    if not image_data:
        raise HTTPException(
            status_code=400,
            detail="Screenshot returned no data",
        )

    current_bytes = base64.b64decode(image_data)
    current_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    current_tmp.write(current_bytes)
    current_tmp.close()
    current_path = current_tmp.name

    diff_output = os.path.join(
        os.path.dirname(current_path),
        f"diff_{Path(baseline_path).stem}.png",
    )

    result = ScreenshotDiffEngine.diff(
        baseline_path=baseline_path,
        current_path=current_path,
        output_path=diff_output,
        threshold=body.threshold,
    )

    # Clean up temp current screenshot
    try:
        os.unlink(current_path)
    except Exception:
        pass

    baseline_stat = os.stat(baseline_path)

    return {
        "status": "ok",
        "comparison": {
            "url": body.url,
            "passed": result.passed,
            "pixel_delta": result.pixel_delta,
            "threshold": body.threshold,
            "dimensions_match": result.dimensions_match,
            "baseline_size": list(result.baseline_size) if result.baseline_size else None,
            "current_size": list(result.current_size) if result.current_size else None,
            "diff_image": result.diff_image,
            "baseline_taken_at": datetime.fromtimestamp(baseline_stat.st_mtime, tz=UTC).isoformat(),
            "compared_at": datetime.now(UTC).isoformat(),
        },
    }


@app.get("/screenshot/baselines")
async def screenshot_baselines(profile: str | None = None):
    """List all stored baselines, optionally filtered by profile."""
    baselines = baseline_mgr.list_baselines(profile=profile)
    return {
        "status": "ok",
        "baselines": baselines,
        "count": len(baselines),
    }


@app.delete("/screenshot/baseline")
async def screenshot_delete_baseline(body: DeleteBaselineRequest):
    """Delete a stored baseline for the given URL (+ optional profile).

    Idempotent for un-scoped deletes: returns 200 with ``deleted=true``
    even when no baseline exists.  For profile-scoped deletes, returns
    404 if the baseline is not found.
    """
    if body.profile and not baseline_mgr.get_baseline(url=body.url, profile=body.profile):
        raise HTTPException(
            status_code=404,
            detail=f"No baseline found for URL: {body.url}",
        )

    baseline_mgr.delete_baseline(
        url=body.url,
        profile=body.profile,
    )
    return {
        "status": "ok",
        "deleted": True,
    }


@app.get("/tabs")
async def list_tabs():
    """List all open browser tabs."""
    return await run_op("get_tabs", client.get_tabs)


@app.get("/api/tabs")
async def api_tabs_alias():
    """API alias: /api/tabs -> /tabs"""
    return await list_tabs()


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

    Body: {"steps": [{"action": "...", "params": {...}}, ...]}

    Supported actions: navigate, click, type, eval, screenshot,
    full_page_screenshot, element_screenshot, wait, wait_for_element,
    wait_text, wait_for_navigation, wait_for_network_idle, scroll, get_text, pdf,
    click_text, click_label, form_fill, form_select, analyze_page,
    upload_files, find_element, get_iframe_text, switch_to_iframe,
    get_page_outline, page_diff, close.
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


# ─── v0.7: New endpoints — tab activation & action confirmation ───


@app.post("/activate-tab/{tab_id}")
async def activate_tab(tab_id: str):
    """Activate a tab by target ID (brings it to foreground)."""
    return await run_op("activate_tab", client._activate_tab_by_id, tab_id)


@app.post("/confirm-action")
async def confirm_action(confirm: str = Query("analyze", description="Confirmation type: 'screenshot' or 'analyze'")):
    """Post-action confirmation helper.

    Returns screenshot or state comparison after an operation.
    Use after any action that doesn't natively support ?confirm=.

    ``?confirm=screenshot`` returns a base64 JPEG screenshot.
    ``?confirm=analyze`` returns visual_state before/after comparison.
    """
    ensure_connected()
    try:
        if confirm == "screenshot":
            result = await client._confirm_with_screenshot()
        else:
            result = await client._confirm_with_analyze()
        return {"status": "ok", "operation": "confirm_action", "result": result}
    except Exception as exc:
        return {"status": "error", "operation": "confirm_action", "error": str(exc)}


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
                            elif step_action == "click_text":
                                r = await client.click_by_text(
                                    step.get("text", ""),
                                    step.get("timeout", 5),
                                    step.get("container_selector", None),
                                )
                            elif step_action == "wait":
                                await asyncio.sleep(step.get("ms", 1000) / 1000)
                                r = {"status": "ok", "waited_ms": step.get("ms", 1000)}
                            elif step_action == "wait_for_element":
                                r = await client.wait_for_element(
                                    step.get("selector", ""),
                                    step.get("timeout", 10),
                                    step.get("visible", True),
                                )
                            elif step_action == "wait_text":
                                r = await client.wait_for_text(
                                    step.get("text", ""),
                                    step.get("timeout", 10),
                                    step.get("present", True),
                                )
                            elif step_action == "wait_for_navigation":
                                r = await client.wait_for_navigation(
                                    step.get("timeout", 10),
                                )
                            elif step_action == "analyze_page":
                                r = await client.analyze_page()
                            elif step_action == "form_fill":
                                r = await client.smart_form_fill(
                                    step.get("fields", []),
                                    step.get("timeout", 5),
                                )
                            elif step_action == "click_label":
                                r = await client.click_label(
                                    step.get("text", ""),
                                    step.get("timeout", 5),
                                )
                            elif step_action == "wait_for_network_idle":
                                r = await client.wait_for_network_idle(
                                    step.get("timeout", 10),
                                    step.get("quiet_ms", 500),
                                )
                            elif step_action == "page_diff":
                                r = await client.page_diff(
                                    step.get("previous_snapshot"),
                                )
                            elif step_action == "close":
                                await client.close()
                                r = {"status": "ok", "action": "close"}
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
# LLM agent API: stable references, observation, differential state and artifacts
# ---------------------------------------------------------------------------

AGENT_CAPABILITIES = {
    "version": "1.5.0",
    "response_schema": "browser-helper-envelope-v1",
    "actions": ["navigate", "click", "fill", "select", "wait", "evaluate", "capture", "workflow", "fill_form", "extract", "execute_task", "dismiss_overlay", "open_menu", "expand_section", "load_all_items", "extract_table", "switch_context"],
    "observation": {"stable_element_refs": True, "pagination": True, "differential": True, "token_budget": True, "accessibility_tree": True, "semantic_graph": True, "scopes": ["page", "main", "dialog", "form", "table", "region", "ref"]},
    "navigation_engine": {"form_discovery": True, "schema_extraction": True, "post_action_expectations": True, "available_actions": True, "backend_node_actions": True, "snapshot_pinning": True, "stale_auto_recovery": True, "modal_aware": True, "workflow_record_replay": True, "verify_after": True, "autocomplete_resolver": True, "hidden_nodes": True, "select_tab": True, "wait_for_element": True, "page_history": True},
    "artifacts": {"screenshots": True, "ttl_seconds": 86400},
}


async def _capture_agent_snapshot(condensed: bool = True):
    raw = await (client.analyze_page_condensed() if condensed else client.analyze_page())
    return snapshot_store.add(raw)


async def _capture_accessibility_snapshot(
    *, scope: str = "page", include: list[str] | None = None,
    interactive_only: bool = False, include_hidden: bool = False,
) -> AccessibilitySnapshot:
    raw = await client.get_accessibility_tree()
    snap = ax_builder.build(
        raw["tree"], page=raw.get("page", {}), scope=scope,
        include=include, interactive_only=interactive_only, include_hidden=include_hidden,
    )
    ax_snapshots[snap.snapshot_id] = snap
    while len(ax_snapshots) > 200:
        candidate = next((key for key in ax_snapshots if not ax_snapshot_pins.get(key)), None)
        if candidate is None:
            break
        del ax_snapshots[candidate]
    return snap


def _pin_ax_snapshot(snapshot_id: str) -> None:
    if snapshot_id not in ax_snapshots:
        raise StaleSnapshotError(f"Accessibility snapshot {snapshot_id!r} is missing")
    ax_snapshot_pins[snapshot_id] = ax_snapshot_pins.get(snapshot_id, 0) + 1


def _unpin_ax_snapshot(snapshot_id: str) -> None:
    count = ax_snapshot_pins.get(snapshot_id, 0)
    if count <= 1:
        ax_snapshot_pins.pop(snapshot_id, None)
    else:
        ax_snapshot_pins[snapshot_id] = count - 1


def _snapshot_contains_text(snapshot: Any, text: str) -> bool:
    needle = text.casefold()
    if isinstance(snapshot, AccessibilitySnapshot):
        return any(needle in f"{node.name} {node.description} {node.value or ''}".casefold() for node in snapshot.nodes)
    return needle in snapshot.text.casefold() or any(needle in f"{item.get('name', '')} {item.get('value', '')}".casefold() for item in snapshot.elements)


def _record_agent_step(kind: str, payload: dict[str, Any]) -> None:
    if active_recording_id and active_recording_id in agent_recordings:
        agent_recordings[active_recording_id]["steps"].append({"kind": kind, "payload": payload})


@app.get("/agent/capabilities")
async def agent_capabilities():
    return api_success("agent_capabilities", AGENT_CAPABILITIES)


@app.post("/agent/observe")
async def agent_observe(body: AgentObserveRequest):
    """Observe the page as either the legacy semantic snapshot or a real AX tree."""
    ensure_connected()
    try:
        if body.mode.lower() in {"accessibility", "ax"}:
            if body.snapshot_id:
                snap = ax_snapshots.get(body.snapshot_id)
                if not snap:
                    raise StaleSnapshotError(f"Accessibility snapshot {body.snapshot_id!r} is missing")
            else:
                snap = await _capture_accessibility_snapshot(
                    scope=("dialog" if body.auto_modal and body.scope == "page" else body.scope),
                    include=body.include, interactive_only=body.interactive_only,
                    include_hidden=body.include_hidden,
                )
            data = snap.as_dict(max_nodes=min(max(body.max_nodes, 1), 1000))
            if body.since_snapshot_id:
                old = ax_snapshots.get(body.since_snapshot_id)
                if not old:
                    raise StaleSnapshotError(f"Accessibility snapshot {body.since_snapshot_id!r} is missing")
                old_refs = {n.ref: n.as_dict() for n in old.nodes}
                new_refs = {n.ref: n.as_dict() for n in snap.nodes}
                changed = [v for k, v in new_refs.items() if old_refs.get(k) != v]
                data["diff"] = {
                    "from_snapshot_id": old.snapshot_id,
                    "to_snapshot_id": snap.snapshot_id,
                    "changed": old.fingerprint != snap.fingerprint,
                    "nodes_changed": changed,
                    "refs_removed": sorted(set(old_refs) - set(new_refs)),
                }
                if body.changed_only:
                    data["nodes"] = changed
            _record_agent_step("observe", {"mode": "accessibility", "scope": body.scope})
            return api_success("agent_observe", data, meta={"trust_level": "untrusted_web_content", "mode": "accessibility"})
        if body.snapshot_id:
            snap = snapshot_store.get(body.snapshot_id)
        else:
            snap = await _capture_agent_snapshot(body.condensed)
        if body.search_text and not _snapshot_contains_text(snap, body.search_text) and (body.fallback or "").lower() in {"accessibility", "ax"}:
            ax_snap = await _capture_accessibility_snapshot(scope="dialog" if body.auto_modal else body.scope, include=body.include, interactive_only=body.interactive_only, include_hidden=body.include_hidden)
            if not _snapshot_contains_text(ax_snap, body.search_text):
                ax_snap = await _capture_accessibility_snapshot(scope="page", include=body.include, interactive_only=body.interactive_only, include_hidden=body.include_hidden)
            data = ax_snap.as_dict(max_nodes=min(max(body.max_nodes, 1), 1000))
            data["fallback_from"] = "semantic"
            data["fallback_reason"] = f"search_text_not_found:{body.search_text}"
            _record_agent_step("observe", {"mode": "accessibility", "scope": body.scope, "search_text": body.search_text})
            return api_success("agent_observe", data, meta={"trust_level": "untrusted_web_content", "mode": "accessibility", "fallback": True})
        data = paginate_snapshot(snap, body.max_chars, body.max_elements, body.cursor)
        if body.since_snapshot_id:
            old = snapshot_store.get(body.since_snapshot_id)
            data["diff"] = diff_snapshots(old, snap)
        _record_agent_step("observe", {"mode": "semantic"})
        return api_success("agent_observe", data, meta={"trust_level": "untrusted_web_content", "mode": "semantic"})
    except StaleSnapshotError as exc:
        return api_error("agent_observe", "stale_snapshot", str(exc), 409)
    except ValueError as exc:
        return api_error("agent_observe", "invalid_observation", str(exc), 422)
    except Exception as exc:
        return api_error("agent_observe", "observation_failed", str(exc), 503)


async def _resolve_agent_target(target: AgentTarget | None) -> dict:
    if target is None:
        return {}
    if target.snapshot_id and target.ref:
        snap = ax_snapshots.get(target.snapshot_id)
        if not snap:
            raise StaleSnapshotError(f"Accessibility snapshot {target.snapshot_id!r} is missing")
        node = next((n for n in snap.nodes if n.ref == target.ref), None)
        if not node:
            raise ElementNotFoundError(f"Accessibility ref {target.ref!r} not found")
        return node.as_dict()
    if target.snapshot_id and target.element_id:
        return snapshot_store.resolve(target.snapshot_id, target.element_id)
    return target.model_dump(exclude_none=True)


@app.post("/agent/act")
async def agent_act(body: AgentActionRequest):
    ensure_connected()
    action = body.action.lower().strip()
    pinned_kind: str | None = None
    pinned_id: str | None = None
    if body.pin_snapshot and body.target and body.target.snapshot_id:
        pinned_id = body.target.snapshot_id
        try:
            if body.target.ref:
                _pin_ax_snapshot(pinned_id)
                pinned_kind = "ax"
            elif body.target.element_id:
                snapshot_store.pin(pinned_id)
                pinned_kind = "semantic"
        except StaleSnapshotError:
            if not body.auto_recover:
                return api_error("agent_act", "stale_snapshot", f"Snapshot {pinned_id!r} is missing or expired", 409)
            pinned_id = None
    try:
        try:
            target = await _resolve_agent_target(body.target)
        except StaleSnapshotError:
            if not body.auto_recover or not body.target:
                raise
            lookup = body.target.name or body.target.text or body.target.label
            if not lookup:
                raise
            recovered = await _capture_accessibility_snapshot(scope="dialog")
            matches = [item for item in recovered.nodes if lookup.casefold() in item.name.casefold()]
            if len(matches) != 1:
                recovered = await _capture_accessibility_snapshot(scope="page")
                matches = [item for item in recovered.nodes if lookup.casefold() in item.name.casefold()]
            if len(matches) != 1:
                raise StaleSnapshotError(f"Could not uniquely recover target {lookup!r}; found {len(matches)} candidates")
            target = matches[0].as_dict()
        before_ax = await _capture_accessibility_snapshot() if body.expect else None
        if action == "navigate":
            if not body.url:
                raise ValueError("url is required")
            result = await client.navigate(body.url)
        elif action == "click":
            if target.get("backend_node_id"):
                result = await client.click_backend_node(target["backend_node_id"])
            elif target.get("selector"):
                result = await client.click(target["selector"])
            else:
                text = target.get("text") or target.get("name") or target.get("label")
                if not text:
                    raise ValueError("click requires an element reference, selector or text")
                result = await client.click_by_text(text, body.timeout)
        elif action == "fill":
            fields = body.fields
            if fields is None and target.get("backend_node_id") and body.value is not None:
                result = await client.fill_backend_node(target["backend_node_id"], body.value)
                fields = []
            if fields is None:
                label = target.get("label") or target.get("name") or target.get("text")
                if not label or body.value is None:
                    raise ValueError("fill requires fields or target plus value")
                fields = [{"label": label, "value": body.value}]
            if fields:
                result = await client.smart_form_fill(fields, body.timeout)
        elif action == "select":
            label = target.get("label") or target.get("name") or target.get("text")
            if not label or body.option is None:
                raise ValueError("select requires target and option")
            result = await client.form_select("label", label, body.option)
        elif action == "wait":
            if target.get("selector"):
                result = await client.wait_for_element(target["selector"], body.timeout, True)
            else:
                text = target.get("text") or target.get("name")
                if not text:
                    raise ValueError("wait requires selector or text")
                result = await client.wait_for_text(text, body.timeout, True)
        elif action == "select_tab":
            text = target.get("text") or target.get("name") or target.get("label")
            if not text:
                raise ValueError("select_tab requires target.text")
            result = await client.select_tab_by_text(text, body.timeout_ms or body.timeout * 1000)
        elif action == "wait_for_element":
            text = target.get("text") or target.get("name") or target.get("label")
            if target.get("selector"):
                started = time.monotonic()
                waited = await client.wait_for_element(target["selector"], max(1, (body.timeout_ms or body.timeout * 1000) // 1000), True)
                inner = waited.get("result", {})
                result = {"found": inner.get("status") == "ok", "elapsed_ms": round((time.monotonic()-started)*1000), "actual_text": inner.get("text", "")}
            elif text:
                result = await client.wait_for_text_detailed(text, body.timeout_ms or body.timeout * 1000)
            else:
                raise ValueError("wait_for_element requires selector or text")
        elif action == "evaluate":
            if not body.expression:
                raise ValueError("expression is required")
            result = await client.evaluate(body.expression)
        elif action == "capture":
            captured = await client.screenshot(quality=body.quality)
            encoded = captured.get("data") or captured.get("screenshot")
            if not encoded:
                raise RuntimeError("Screenshot response did not contain image data")
            binary = base64.b64decode(encoded)
            result = {"artifact": artifact_store.put(binary, "image/jpeg", ".jpg")}
        elif action == "workflow":
            if not body.steps:
                raise ValueError("steps are required")
            result = await client.execute_script(body.steps)
        elif action in {"open_menu", "expand_section"}:
            name = target.get("name") or target.get("text") or body.parameters.get("name")
            if not name:
                raise ValueError(f"{action} requires a target name")
            result = await client.click_by_text(str(name), body.timeout)
        elif action == "dismiss_overlay":
            result = await client.evaluate("""(() => {
                const words=/accept|agree|close|dismiss|not now|no thanks/i;
                const roots=[...document.querySelectorAll('[role=dialog],dialog,[class*=cookie],[class*=modal],[class*=overlay]')]
                  .filter(el => el.offsetParent !== null);
                for (const root of roots) {
                  const button=[...root.querySelectorAll('button,[role=button]')]
                    .find(el => words.test((el.innerText||el.getAttribute('aria-label')||'').trim()));
                  if (button) { button.click(); return {dismissed:true,text:(button.innerText||button.getAttribute('aria-label')||'').trim()}; }
                }
                return {dismissed:false,reason:'no supported overlay control found'};
            })()""")
        elif action == "load_all_items":
            limit = min(max(int(body.parameters.get("limit", 100)), 1), 1000)
            result = await client.evaluate(f"""(async () => {{
                let clicks=0, previous=-1;
                while (clicks < 20 && document.querySelectorAll('*').length < {limit}) {{
                  const candidates=[...document.querySelectorAll('button,a,[role=button]')].filter(el => /load more|show more|more results/i.test(el.innerText||'') && el.offsetParent !== null);
                  if (!candidates.length) break;
                  candidates[0].click(); clicks++; await new Promise(r => setTimeout(r, 250));
                  const count=document.querySelectorAll('*').length; if (count===previous) break; previous=count;
                }}
                return {{clicks,element_count:document.querySelectorAll('*').length}};
            }})()""")
        elif action == "extract_table":
            result = await client.evaluate("""(() => [...document.querySelectorAll('table,[role=grid]')].map((table,index)=>({
                index, name:table.getAttribute('aria-label')||table.querySelector('caption')?.innerText||'',
                rows:[...table.querySelectorAll('tr,[role=row]')].map(row=>[...row.querySelectorAll('th,td,[role=cell],[role=columnheader],[role=rowheader]')].map(cell=>(cell.innerText||'').trim()))
            })))()""")
        elif action == "switch_context":
            tab_id = body.parameters.get("tab_id") or body.parameters.get("target")
            if not tab_id:
                raise ValueError("switch_context requires parameters.tab_id")
            result = await client.switch_tab(str(tab_id))
        else:
            return api_error("agent_act", "unknown_action", f"Unknown action: {action}", 422)
        data = {"action": action, "result": result}
        if before_ax is not None:
            after_ax = await _capture_accessibility_snapshot()
            verification = validate_expectations(before_ax, after_ax, body.expect)
            data["verification"] = verification
            if not verification["satisfied"] and int((body.recovery or {}).get("retry", 0)) > 0:
                if action == "click" and target.get("backend_node_id"):
                    data["retry_result"] = await client.click_backend_node(target["backend_node_id"])
                    after_ax = await _capture_accessibility_snapshot()
                    data["verification"] = validate_expectations(before_ax, after_ax, body.expect)
                data["replanned"] = True
            if not data["verification"]["satisfied"]:
                data["status"] = "needs_attention"
                strategies = body.strategy or []
                if "element_screenshot" in strategies and target.get("selector"):
                    captured = await client.element_screenshot(target["selector"], body.quality)
                    encoded = captured.get("data") or captured.get("screenshot")
                    if encoded:
                        data["visual_fallback"] = {"strategy": "element_screenshot", "artifact": artifact_store.put(base64.b64decode(encoded), "image/jpeg", ".jpg")}
                elif "viewport_screenshot" in strategies:
                    captured = await client.screenshot(quality=body.quality)
                    encoded = captured.get("data") or captured.get("screenshot")
                    if encoded:
                        data["visual_fallback"] = {"strategy": "viewport_screenshot", "artifact": artifact_store.put(base64.b64decode(encoded), "image/jpeg", ".jpg")}
        if body.verify_after:
            verification_type = body.verify_after.get("type")
            timeout_ms = int(body.verify_after.get("timeout_ms", 5000))
            if verification_type == "text_visible":
                verification = await client.wait_for_text_detailed(str(body.verify_after.get("text", "")), timeout_ms)
            elif verification_type == "element_visible":
                selector = body.verify_after.get("selector")
                if not selector:
                    raise ValueError("element_visible verification requires selector")
                started = time.monotonic()
                waited = await client.wait_for_element(selector, max(1, timeout_ms // 1000), True)
                inner = waited.get("result", {})
                verification = {"found": inner.get("status") == "ok", "elapsed_ms": round((time.monotonic()-started)*1000), "actual_text": inner.get("text", "")}
            else:
                raise ValueError(f"Unsupported verify_after type: {verification_type}")
            data["verified"] = bool(verification.get("found"))
            data["actual_text"] = verification.get("actual_text", "")
            data["verification_after"] = verification
        if body.observe_after and action not in {"evaluate", "capture"}:
            snap = await _capture_agent_snapshot(True)
            data["observation"] = paginate_snapshot(snap, 4000, 60)
        _record_agent_step("act", body.model_dump(mode="json", exclude_none=True, by_alias=True))
        return api_success("agent_act", data)
    except StaleSnapshotError as exc:
        return api_error("agent_act", "stale_snapshot", str(exc), 409)
    except ElementNotFoundError as exc:
        return api_error("agent_act", "element_not_found", str(exc), 404)
    except ValueError as exc:
        return api_error("agent_act", "invalid_request", str(exc), 422)
    except Exception as exc:
        return api_error("agent_act", "action_failed", str(exc), 503)
    finally:
        if pinned_id and pinned_kind == "ax":
            _unpin_ax_snapshot(pinned_id)
        elif pinned_id and pinned_kind == "semantic":
            snapshot_store.unpin(pinned_id)


@app.post("/agent/record")
async def agent_record(body: AgentRecordRequest):
    """Start recording subsequent observe and act calls in memory."""
    global active_recording_id
    if not body.start:
        return api_error("agent_record", "recording_not_started", "start must be true", 422)
    recording_id = f"rec_{uuid.uuid4().hex[:16]}"
    agent_recordings[recording_id] = {"recording_id": recording_id, "name": body.name or recording_id, "steps": []}
    active_recording_id = recording_id
    return api_success("agent_record", agent_recordings[recording_id])


@app.post("/agent/record/stop")
async def agent_record_stop():
    """Stop and return the active workflow recording."""
    global active_recording_id
    if not active_recording_id:
        return api_error("agent_record_stop", "no_active_recording", "No workflow recording is active", 409)
    result = agent_recordings[active_recording_id]
    active_recording_id = None
    return api_success("agent_record_stop", result)


def _apply_recording_overrides(value: Any, overrides: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: overrides.get(key, _apply_recording_overrides(item, overrides)) for key, item in value.items()}
    if isinstance(value, list):
        return [_apply_recording_overrides(item, overrides) for item in value]
    return value


@app.post("/agent/replay")
async def agent_replay(body: AgentReplayRequest):
    """Replay recorded act requests; observe steps are intentionally informational."""
    recording_id = body.effective_recording_id
    recording = agent_recordings.get(recording_id)
    if not recording:
        return api_error("agent_replay", "recording_not_found", "Recording not found", 404)
    results = []
    for index, step in enumerate(recording["steps"], 1):
        if step["kind"] != "act":
            continue
        payload = _apply_recording_overrides(step["payload"], body.data_overrides)
        replay_body = AgentActionRequest.model_validate(payload)
        replay_body.pin_snapshot = False
        replay_body.auto_recover = True
        response = await agent_act(replay_body)
        status = getattr(response, "status_code", 200)
        results.append({"step": index, "status_code": status})
        if body.stop_on_error and status >= 400:
            break
    return api_success("agent_replay", {"recording_id": recording_id, "results": results, "replayed": len(results)})


@app.post("/agent/forms/discover")
async def agent_forms_discover(body: AgentFormDiscoverRequest | None = None):
    """Discover forms; page_with_history first triggers bounded SPA lazy loading."""
    ensure_connected()
    body = body or AgentFormDiscoverRequest()
    try:
        history = None
        if body.scope == "page_with_history":
            history = await client.trigger_lazy_history()
        if body.snapshot_id:
            snap = ax_snapshots.get(body.snapshot_id)
            if not snap:
                raise StaleSnapshotError(f"Accessibility snapshot {body.snapshot_id!r} is missing")
        else:
            snap = await _capture_accessibility_snapshot(scope="page", include=["forms", "headings", "dialogs"])
        return api_success("agent_forms_discover", {
            "snapshot_id": snap.snapshot_id,
            "forms": discover_forms(snap),
            "history_load": history,
        })
    except Exception as exc:
        return api_error("agent_forms_discover", "discovery_failed", str(exc), 503)


async def _fill_semantic_form(snap: AccessibilitySnapshot, form_ref: str, data: dict[str, Any]) -> dict:
    forms = discover_forms(snap)
    form = next((item for item in forms if item["form_ref"] == form_ref), None)
    if not form:
        raise ValueError(f"Unknown form_ref: {form_ref}")
    nodes = {node.ref: node for node in snap.nodes}
    filled, confirmed, invalid, uncertain = [], [], [], []
    normalized_data = {key.lower().replace(" ", "_"): value for key, value in data.items()}
    for field in form["fields"]:
        key = field["semantic_type"]
        value_spec = normalized_data.get(key)
        if value_spec is None:
            label_key = field["label"].lower().replace(" ", "_")
            value_spec = normalized_data.get(label_key)
        resolver = value_spec.get("resolver") if isinstance(value_spec, dict) else None
        value = value_spec.get("value") if isinstance(value_spec, dict) else value_spec
        if value is None:
            if field["required"] and not field.get("current_value"):
                invalid.append({"field": field["label"], "reason": "required_value_missing"})
            continue
        node = nodes[field["ref"]]
        if node.backend_node_id is None:
            uncertain.append({"field": field["label"], "reason": "no_backend_node"})
            continue
        if resolver == "autocomplete":
            result = await client.fill_autocomplete(node.name or key, str(value))
            ok = result.get("result", {}).get("status") == "ok"
        elif node.role == "combobox":
            result = await client.form_select("label", node.name, str(value))
            ok = result.get("status") == "ok"
        else:
            result = await client.fill_backend_node(node.backend_node_id, str(value))
            ok = bool(result.get("confirmed"))
        filled.append({"field": field["label"], "ref": field["ref"], "result": result})
        if ok:
            confirmed.append(field["ref"])
        else:
            invalid.append({"field": field["label"], "reason": "value_not_confirmed", "result": result})
    status = "ok" if not invalid and not uncertain else "needs_attention"
    return {"status": status, "filled": len(filled), "confirmed": len(confirmed),
            "results": filled, "uncertain": uncertain, "invalid": invalid,
            "next_action": "continue" if status == "ok" else "correct_validation_errors"}


@app.post("/agent/forms/fill")
async def agent_forms_fill(body: AgentFormFillRequest):
    """Fill a discovered form from semantic key/value data and confirm writes."""
    ensure_connected()
    try:
        snap = await _capture_accessibility_snapshot(include=["forms", "dialogs"])
        result = await _fill_semantic_form(snap, body.form_ref, body.data)
        if body.validate_result:
            after = await _capture_accessibility_snapshot(include=["forms", "alerts", "dialogs"])
            result["validation"] = discover_forms(after)
        return api_success("agent_forms_fill", result)
    except ValueError as exc:
        return api_error("agent_forms_fill", "invalid_form", str(exc), 422)
    except Exception as exc:
        return api_error("agent_forms_fill", "fill_failed", str(exc), 503)


@app.post("/agent/extract")
async def agent_extract(body: AgentExtractRequest):
    """Extract schema-shaped data with source refs and field confidence."""
    ensure_connected()
    try:
        if body.snapshot_id:
            snap = ax_snapshots.get(body.snapshot_id)
            if not snap:
                raise StaleSnapshotError(f"Accessibility snapshot {body.snapshot_id!r} is missing")
        else:
            scope = body.scope if isinstance(body.scope, str) else (body.scope or {}).get("role", "page")
            snap = await _capture_accessibility_snapshot(scope=scope)
        return api_success("agent_extract", extract_by_schema(
            snap, body.extraction_schema, include_evidence=body.include_evidence,
        ))
    except StaleSnapshotError as exc:
        return api_error("agent_extract", "stale_snapshot", str(exc), 409)
    except ValueError as exc:
        return api_error("agent_extract", "invalid_schema", str(exc), 422)
    except Exception as exc:
        return api_error("agent_extract", "extraction_failed", str(exc), 503)


@app.post("/agent/available-actions")
async def agent_available_actions():
    """Return actions that are currently possible and their blocking reasons."""
    ensure_connected()
    try:
        snap = await _capture_accessibility_snapshot()
        result = available_actions(snap)
        result["snapshot_id"] = snap.snapshot_id
        return api_success("agent_available_actions", result)
    except Exception as exc:
        return api_error("agent_available_actions", "observation_failed", str(exc), 503)


@app.post("/agent/execute-task")
async def agent_execute_task(body: AgentExecuteTaskRequest):
    """Execute a bounded deterministic form-and-navigation micro-task.

    The engine deliberately supports only inspectable operations: semantic form
    filling and a single verified continuation click.  Unsupported or ambiguous
    goals return ``needs_attention`` with current candidate actions.
    """
    ensure_connected()
    max_steps = min(max(int(body.constraints.get("max_steps", 20)), 1), 50)
    stop_before = {str(item).lower() for item in body.constraints.get("stop_before", [])}
    try:
        snap = await _capture_accessibility_snapshot()
        steps: list[dict] = []
        forms = discover_forms(snap)
        if body.inputs and forms and len(steps) < max_steps:
            fill_result = await _fill_semantic_form(snap, forms[0]["form_ref"], body.inputs)
            steps.append({"action": "fill_form", "result": fill_result})
            snap = await _capture_accessibility_snapshot()
        blocked_terms = {"purchase", "buy", "pay", "submit payment", *stop_before}
        goal = body.goal.lower()
        candidates = [n for n in snap.nodes if "click" in n.actions]
        continue_words = ("continue", "next", "proceed", "save and continue")
        target = next((n for n in candidates if any(word in n.name.lower() for word in continue_words)), None)
        if target and len(steps) < max_steps and not any(term in target.name.lower() for term in blocked_terms):
            before = snap
            result = await client.click_backend_node(target.backend_node_id) if target.backend_node_id else await client.click_by_text(target.name)
            after = await _capture_accessibility_snapshot()
            verification = validate_expectations(before, after, None)
            steps.append({"action": "click", "target": target.ref, "result": result, "verification": verification})
            snap = after
        status = "ok" if steps and all(step.get("result", {}).get("status") == "ok" for step in steps) else "needs_attention"
        if any(term in goal for term in stop_before):
            status = "stopped_by_constraint"
        data = {"status": status, "goal": body.goal, "steps": steps,
                "step_count": len(steps), "final_snapshot_id": snap.snapshot_id}
        if status != "ok":
            data["available_actions"] = available_actions(snap)
        if body.return_options.get("final_observation", True):
            data["final_observation"] = snap.as_dict(max_nodes=100)
        return api_success("agent_execute_task", data)
    except Exception as exc:
        return api_error("agent_execute_task", "task_failed", str(exc), 503)


@app.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    found = artifact_store.get(artifact_id) or headless_mgr.artifacts.get(artifact_id)
    if not found:
        return api_error("artifact_get", "artifact_not_found", "Artifact not found", 404)
    path, record = found
    return FileResponse(path, media_type=record["mime_type"], filename=path.name)


# ---------------------------------------------------------------------------
# REST endpoints — headless Chrome sessions
# ---------------------------------------------------------------------------


@app.post("/headless/launch")
async def headless_launch(body: HeadlessLaunchRequest | None = None):
    """Launch a new headless Chrome session.

    Optionally provide profile_dir, port, profile (profile name), and/or
    extensions (list of extension paths).
    Returns session_id, port, cdp_url, pid.
    """
    kwargs = {}
    if body:
        if body.profile_dir is not None:
            kwargs["profile_dir"] = body.profile_dir
        if body.port is not None:
            kwargs["port"] = body.port
        if body.profile is not None:
            kwargs["profile"] = body.profile
        if body.extensions is not None:
            kwargs["extensions"] = body.extensions
        if body.proxy_url is not None:
            kwargs["proxy_url"] = body.proxy_url
        if body.proxy_strategy is not None:
            kwargs["proxy_strategy"] = body.proxy_strategy
        if body.proxy_group is not None:
            kwargs["proxy_group"] = body.proxy_group
    result = await headless_mgr.launch_session(**kwargs)
    if result.get("status") != "ok":
        return api_error("headless_launch", result.get("code", "launch_failed"), result.get("error", "Launch failed"), result_status(result))
    return api_success("headless_launch", result)


@app.post("/headless/close")
async def headless_close(body: HeadlessCloseRequest):
    result = await headless_mgr.close_session(body.session_id)
    if result.get("status") != "ok":
        return api_error("headless_close", result.get("code", "session_not_found"), result.get("error", "Session not found"), result_status(result, 404))
    return api_success("headless_close", result)


@app.get("/headless/sessions")
async def headless_sessions():
    return api_success("headless_sessions", {"sessions": headless_mgr.get_sessions()})


@app.post("/headless/navigate")
async def headless_navigate(body: HeadlessNavigateRequest):
    result = await headless_mgr.navigate(body.session_id, body.url)
    if result.get("status") != "ok":
        return api_error("headless_navigate", result.get("code", "navigation_failed"), result.get("error", "Navigation failed"), result_status(result))
    return api_success("headless_navigate", result)


@app.post("/headless/eval")
async def headless_eval(body: HeadlessEvalRequest):
    result = await headless_mgr.evaluate(body.session_id, body.expression)
    if result.get("status") != "ok":
        return api_error("headless_eval", result.get("code", "evaluation_failed"), result.get("error", "Evaluation failed"), result_status(result))
    return api_success("headless_eval", result)


@app.post("/headless/screenshot")
async def headless_screenshot(body: HeadlessScreenshotRequest):
    result = await headless_mgr.screenshot(body.session_id)
    if result.get("status") != "ok":
        return api_error("headless_screenshot", result.get("code", "capture_failed"), result.get("error", "Capture failed"), result_status(result))
    return api_success("headless_screenshot", result)


@app.post("/headless/batch-screenshot")
async def headless_batch_screenshot(body: HeadlessBatchScreenshotRequest):
    result = await headless_mgr.batch_screenshot(body.session_id, body.urls)
    if result.get("status") != "ok":
        return api_error("headless_batch_screenshot", result.get("code", "capture_failed"), result.get("error", "Capture failed"), result_status(result))
    return api_success("headless_batch_screenshot", result)


@app.get("/headless/health")
async def headless_health():
    return api_success("headless_health", headless_mgr.health_check())


# ---------------------------------------------------------------------------
# REST endpoints — Profile management
# ---------------------------------------------------------------------------


def _profile_to_response(p: Profile) -> dict:
    """Serialize a Profile to a JSON-safe dict for API responses."""
    return {
        "name": p.name,
        "data_dir": p.data_dir,
        "created_at": p.created_at,
        "last_used": p.last_used,
        "extensions": list(p.extensions),
        "description": p.description,
        "tags": list(p.tags),
        "resource_limits": dict(p.resource_limits),
    }


@app.get("/profiles")
async def list_profiles():
    """List all profiles."""
    profiles = profile_mgr.list_profiles()
    return {
        "status": "ok",
        "profiles": [_profile_to_response(p) for p in profiles],
    }


@app.post("/profiles", status_code=201)
async def create_profile(body: ProfileCreateRequest):
    """Create a new profile."""
    if not body.name:
        return JSONResponse(
            status_code=400,
            content={"detail": "Profile name must not be empty"},
        )
    try:
        profile = profile_mgr.create_profile(
            name=body.name,
            extensions=body.extensions,
            description=body.description,
            tags=body.tags,
            resource_limits=body.resource_limits,
        )
        return {
            "status": "ok",
            "profile": _profile_to_response(profile),
        }
    except ValueError as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "duplicate" in msg:
            return JSONResponse(
                status_code=409,
                content={"detail": str(exc)},
            )
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )


@app.get("/profiles/{name}")
async def get_profile(name: str):
    """Get profile details by name."""
    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    return {
        "status": "ok",
        "profile": _profile_to_response(profile),
    }


@app.put("/profiles/{name}")
async def update_profile(name: str, body: ProfileUpdateRequest):
    """Update profile metadata (description, tags, resource_limits)."""
    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )

    # Apply updates via the manager's internal dict
    updated = Profile(
        name=profile.name,
        data_dir=profile.data_dir,
        created_at=profile.created_at,
        last_used=profile.last_used,
        extensions=profile.extensions,
        description=body.description if body.description is not None else profile.description,
        tags=body.tags if body.tags is not None else profile.tags,
        resource_limits=body.resource_limits if body.resource_limits is not None else profile.resource_limits,
    )

    # Directly update the data dict and save
    profile_mgr._data[name] = updated.to_dict()
    profile_mgr.save()

    return {
        "status": "ok",
        "profile": _profile_to_response(
            profile_mgr.get_profile(name)  # type: ignore[arg-type]
        ),
    }


@app.delete("/profiles/{name}")
async def delete_profile(name: str):
    """Delete a profile and its data directory."""
    if profile_mgr.get_profile(name) is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    profile_mgr.delete_profile(name)
    return {"status": "ok"}


@app.post("/profiles/{name}/export")
async def export_profile(name: str):
    """Export a profile as a ZIP archive."""
    import tempfile

    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )

    output = str(tempfile.mktemp(suffix=".zip"))
    result = profile_mgr.export_profile(name, output)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    return {"status": "ok", "path": result}


@app.post("/profiles/import", status_code=201)
async def import_profile(body: ImportRequest):
    """Import a profile from a ZIP archive."""
    try:
        profile = profile_mgr.import_profile(body.path)
        return {
            "status": "ok",
            "profile": _profile_to_response(profile),
        }
    except (ValueError, zipfile.BadZipFile) as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )


@app.get("/profiles/{name}/extensions")
async def get_extensions(name: str):
    """List extensions for a profile."""
    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    return {
        "status": "ok",
        "extensions": profile.extensions,
    }


@app.post("/profiles/{name}/extensions")
async def add_extension(name: str, body: ExtensionRequest):
    """Add an extension to a profile."""
    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    profile_mgr.add_extension(name, body.path)
    return {
        "status": "ok",
        "extensions": profile_mgr.get_extensions(name),
    }


@app.delete("/profiles/{name}/extensions")
async def remove_extension(name: str, body: ExtensionRequest):
    """Remove an extension from a profile."""
    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    profile_mgr.remove_extension(name, body.path)
    return {
        "status": "ok",
        "extensions": profile_mgr.get_extensions(name),
    }


# ---------------------------------------------------------------------------
# Proxy management REST endpoints
# ---------------------------------------------------------------------------


@app.post("/proxy/pool")
async def add_proxies(body: AddProxiesRequest):
    """Add one or more proxies to the pool."""
    ids = []
    for proxy in body.proxies:
        try:
            pid = proxy_pool.add_proxy(
                url=proxy.url,
                proxy_type=proxy.type,
                tags=proxy.tags,
            )
            ids.append(pid)
        except (ValueError, ProxyParseError) as exc:
            return api_error("add_proxies", "invalid_proxy_url", str(exc), 400)
    return api_success("add_proxies", {"ids": ids})


@app.get("/proxy/pool")
async def get_proxies():
    """List all proxies in the pool."""
    proxies = proxy_pool.get_pool()
    return api_success("get_proxies", {"proxies": proxies})


@app.get("/proxy/pool/{proxy_id}")
async def get_proxy(proxy_id: str):
    """Get a single proxy by ID."""
    entry = proxy_pool.get_proxy(proxy_id=proxy_id)
    if entry is None:
        return api_error("get_proxy", "proxy_not_found", f"Proxy {proxy_id!r} not found", 404)
    return api_success("get_proxy", entry)


@app.delete("/proxy/pool/{proxy_id}")
async def delete_proxy(proxy_id: str):
    """Remove a single proxy by ID."""
    if proxy_pool.remove_proxy(proxy_id):
        return api_success("delete_proxy", {"proxy_id": proxy_id})
    return api_error("delete_proxy", "proxy_not_found", f"Proxy {proxy_id!r} not found", 404)


@app.delete("/proxy/pool")
async def clear_pool():
    """Remove all proxies from the pool."""
    proxy_pool.clear()
    return api_success("clear_pool", {"cleared": True})


@app.post("/proxy/health")
async def trigger_health_check(body: HealthCheckRequest):
    """Run health check on all or a single proxy."""
    if body.proxy_id:
        result = proxy_pool.health_check(body.proxy_id)
        if result is None:
            return api_error("trigger_health_check", "proxy_not_found", f"Proxy {body.proxy_id!r} not found", 404)
        return api_success("trigger_health_check", {"results": [result]})
    results = proxy_pool.health_check_all()
    return api_success("trigger_health_check", {"results": results})


@app.get("/proxy/health")
async def get_health_status():
    """Get health summary for all proxies."""
    stats = proxy_pool.get_stats()
    return api_success("get_health_status", {
        "total": stats["total"],
        "healthy": stats["healthy"],
        "unhealthy": stats["unhealthy"],
    })


@app.post("/proxy/stats")
async def get_proxy_stats():
    """Get proxy usage statistics."""
    stats = proxy_pool.get_stats()
    return api_success("get_proxy_stats", stats)


# ---------------------------------------------------------------------------
# Backend switch routes (P1-1)
# ---------------------------------------------------------------------------


@app.post("/backend/switch")
async def switch_backend(req: BackendSwitchRequest):
    """Switch the active automation backend ("cdp" or "playwright")."""
    return backend_manager.switch(req.backend)


@app.get("/backend/status")
async def backend_status():
    """Return current backend status, available backends, and versions."""
    return backend_manager.get_status()


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

# Enterprise browser-agent operations (additive v1 API)
from enterprise_workspace import EnterpriseWorkspace, render_console
_enterprise = EnterpriseWorkspace(Path(os.getenv("ENTERPRISE_DB", "/tmp/browser-helper-enterprise.db")))

@app.get("/enterprise/{page}", include_in_schema=False)
async def enterprise_console(page: str):
    try:
        return HTMLResponse(render_console(page, _enterprise))
    except KeyError:
        raise HTTPException(status_code=404, detail="WORKSPACE_NOT_FOUND")

@app.post("/api/v1/enterprise/policies")
async def enterprise_policy(body: dict):
    return {"id": _enterprise.create_policy(body["tenant"], body["origins"], body["actions"]), "state": "ACTIVE"}

@app.post("/api/v1/enterprise/replays")
async def enterprise_replay(body: dict):
    return {"id": _enterprise.start_replay(body["tenant"]), "state": "RECORDING"}

@app.post("/api/v1/enterprise/takeovers")
async def enterprise_takeover(body: dict):
    return {"id": _enterprise.request_takeover(body["tenant"], body["run_id"], body["reason"]), "state": "WAITING"}

@app.post("/api/v1/enterprise/workflows")
async def enterprise_workflow(body: dict):
    return {"id": _enterprise.create_workflow(body["tenant"], body["name"], body["steps"]), "state": "READY"}

@app.post("/api/v1/enterprise/evaluations")
async def enterprise_evaluation(body: dict):
    return {"id": _enterprise.create_evaluation(body["candidate"], body["threshold"]), "state": "RUNNING"}
