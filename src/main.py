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
import uuid
import zipfile
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

# Python 3.10 compatibility: datetime.UTC is 3.11+
try:
    _UTC = datetime.UTC
except AttributeError:
    _UTC = UTC
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Auth / rate limiting
# ---------------------------------------------------------------------------
from playwright_backend import BackendManager as _BackendManager

backend_manager = _BackendManager()

from agent_navigation import (
    AccessibilitySnapshot,
    AccessibilityTreeBuilder,
    available_actions,
    discover_forms,
    extract_by_schema,
    validate_expectations,
)
from agent_runtime import (
    ElementNotFoundError,
    SnapshotStore,
    StaleSnapshotError,
    diff_snapshots,
    paginate_snapshot,
)
from anti_detection.compositor import AntiDetectCompositor, AntiDetectProfileBundle
from anti_detection.fingerprint_database import FingerprintDatabase
from artifact_store import ArtifactStore
from baseline_manager import BaselineManager
from capability_registry import CapabilityRegistry
from cdp_client import CDPClient, RateLimitConfig
from chrome_manager import ChromeManager
from daily_launchpad import build_daily_launchpad
from detection_tester import DetectionTester
from domain_throttle import domain_throttle

# Serialize concurrent navigate commands: Chrome's CDP WebSocket can't
# handle multiple Page.navigate calls at once — the second one silently
# times out while the first is still loading.  A global lock ensures at
# most one navigate is in-flight across all sessions.
_navigate_lock = asyncio.Lock()
from environment_store import EnvironmentStore
from headless_manager import HeadlessManager
from profile_manager import Profile, ProfileManager
from proxy_manager import ProxyParseError, ProxyPool

# ── Anti-detection v1.8.0 modules ──────────────────────────────────
from proxy_rotation_manager import ProxyRotationManager
from run_comparison import compare_runs
from run_recovery import RecoveryAdvisor
from run_timeline import RunStore
from screenshot_diff import ScreenshotDiffEngine
from session_manager import SessionManager
from session_registry import Session, SessionRegistry
from settings_manager import SettingsManager
from stealth_injector import StealthInjector
from workflow_catalog import WorkflowCatalog

# Global singleton instances for v1.8.0 API endpoints
_fingerprint_db = FingerprintDatabase()
_proxy_rotation = ProxyRotationManager()
_stealth_injector = StealthInjector()
_session_mgr = SessionManager()
_compositor = AntiDetectCompositor(
    fingerprint_db=_fingerprint_db,
    proxy_mgr=_proxy_rotation,
    stealth=_stealth_injector,
    session_mgr=_session_mgr,
)
_detection_tester = DetectionTester()
_capability_registry = CapabilityRegistry.default()
environment_store = EnvironmentStore()
workflow_catalog = WorkflowCatalog()

# Paths excluded from auth and rate-limiting middleware
PUBLIC_PATHS = {"/", "/health", "/ready", "/ws", "/api/v1/capabilities"}

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
    # ── Reap orphaned headless Chrome processes ──────────────────
    # Headless sessions whose registry was lost (server restart/crash) leave
    # zombie Chrome processes (--headless --remote-debugging-port=N or 0)
    # that no reaper can reach — they eat RAM until killed manually.
    # Kill any headless Chrome NOT owned by this process's live sessions.
    try:
        reaped = _reap_orphan_headless()
        if reaped:
            logger.warning("Reaped %d orphaned headless Chrome process(es) at startup", reaped)
    except Exception as exc:  # noqa: BLE001 — startup must never abort
        logger.warning("Orphan headless reap failed: %s", exc)
    # Connect to the LOCAL Chrome on the saved launched/debug port — NOT the
    # CDPClient default (9555), which may be another machine's SSH tunnel.
    # Priority: CHROME_AUTO_PORT (run.py --debug-port) > settings > 9557.
    local_port = int(os.environ["CHROME_AUTO_PORT"]) if os.environ.get("CHROME_AUTO_PORT") else (
        settings_mgr.get("chrome_launched_port")
        or settings_mgr.get("chrome_debug_port")
        or 9557
    )
    client.cdp_http_url = f"http://127.0.0.1:{local_port}"
    try:
        # Attach the global client to the BROWSER-LEVEL WebSocket (stable —
        # survives tab churn), not a page target (which _reap_orphan_tabs may
        # close, killing the WS and flipping connected → False; the watchdog
        # then misread that as a dead Chrome and auto-restarted every 5 min).
        import httpx as _httpx

        async with _httpx.AsyncClient(timeout=3.0) as http:
            resp = await http.get(f"http://127.0.0.1:{local_port}/json/version")
            if resp.status_code == 200:
                ws_url = resp.json().get("webSocketDebuggerUrl", "")
                if ws_url:
                    await client.connect_browser(ws_url)
                    state["connected"] = True
                    state["cdp_url"] = ws_url
                    logger.info("Auto-connected to browser-level CDP at %s", ws_url)
                else:
                    raise ConnectionError("no webSocketDebuggerUrl")
            else:
                raise ConnectionError(f"HTTP {resp.status_code}")
    except Exception as exc:
        logger.warning("Auto-connect to CDP failed (server will start anyway): %s", exc, exc_info=True)
    # ── Auto-launch Chrome (if --launch-chrome was passed to run.py) ──
    if os.environ.get("CHROME_AUTO_LAUNCH") == "1":
        launch_kwargs = {}
        profile = os.environ.get("CHROME_AUTO_PROFILE")
        port = os.environ.get("CHROME_AUTO_PORT")
        display = os.environ.get("CHROME_DISPLAY")
        if profile:
            launch_kwargs["profile_dir"] = profile
        if port:
            launch_kwargs["port"] = int(port)
        if display:
            os.environ["CHROME_DISPLAY"] = display
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
                        await _ensure_global_client_attached()
                    except Exception as exc2:
                        logger.warning("Auto-connect to launched Chrome failed: %s", exc2, exc_info=True)
            else:
                logger.warning("Chrome auto-launch failed: %s", result.get("error", "unknown"))
        except Exception as exc3:
            logger.warning("Chrome auto-launch exception: %s", exc3, exc_info=True)
    # ── Fleet orchestration (v1.18.0): start the health poller ──
    try:
        from fleet.api import get_fleet_coordinator

        _fleet_coordinator = get_fleet_coordinator()
        _fleet_coordinator.start()
        logger.info("Fleet health poller started")
    except Exception as exc:  # noqa: BLE001 — startup must never abort the server
        logger.warning("Fleet coordinator startup failed: %s", exc)
    # ── Session reaper: periodically close idle per-client sessions ──
    try:
        session_registry.start_reaper()
        logger.info("Session reaper started (TTL %ss)", session_registry._ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Session reaper startup failed: %s", exc)
    # ── Chrome health watchdog: reap orphans + auto-restart ──────
    try:
        asyncio.create_task(_chrome_health_watchdog())
        logger.info("Chrome health watchdog started (every 300s)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chrome health watchdog startup failed: %s", exc)
    # ── Keep-warm tab: pre-open the control-plane URL so the first agent
    # journey doesn't pay the launch+navigate penalty (~400ms cold start).
    # R3: PERIODIC — the session reaper (TTL 30 min) kills the warm session,
    # so a one-shot mint only protects the first 30 minutes.  Re-mint every
    # BH_KEEP_WARM_INTERVAL seconds (default 300) whenever the tab is gone.
    warm_url = os.environ.get("BH_KEEP_WARM_URL", "http://127.0.0.1:8080/")
    if os.environ.get("BH_KEEP_WARM", "1") != "0":
        async def _keep_warm() -> None:
            await asyncio.sleep(3)
            import httpx as _hx
            while True:
                try:
                    tabs = await client.get_tabs()
                    rows = tabs.get("data", []) if isinstance(tabs, dict) else []
                    if any(str(row.get("url", "")).startswith(warm_url) for row in rows):
                        await asyncio.sleep(int(os.environ.get("BH_KEEP_WARM_INTERVAL", "300")))
                        continue
                    await chrome_mgr.launch()
                    async with _hx.AsyncClient(timeout=5.0) as hx:
                        await hx.post(f"http://127.0.0.1:{os.environ.get('BH_PORT', '8020')}/session/new", params={"url": warm_url})
                    logger.info("Keep-warm session ensured at %s", warm_url)
                except Exception as exc:  # noqa: BLE001 — warm-up is best-effort
                    logger.debug("Keep-warm cycle failed: %s", exc)
                await asyncio.sleep(int(os.environ.get("BH_KEEP_WARM_INTERVAL", "300")))
        asyncio.create_task(_keep_warm())
        logger.info("Keep-warm task started (target %s, every %ss)", warm_url, os.environ.get("BH_KEEP_WARM_INTERVAL", "300"))
    yield
    # Shutdown
    # Stop the fleet health poller / release its HTTP client
    try:
        from fleet.api import get_fleet_coordinator

        await get_fleet_coordinator().stop()
    except Exception as exc:  # noqa: BLE001 — shutdown must never abort teardown
        logger.warning("Fleet coordinator shutdown failed: %s", exc)
    # Close all per-client sessions (tabs + WebSockets)
    try:
        await session_registry.close_all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Session registry shutdown failed: %s", exc)
    if client.is_connected:
        try:
            await client.disconnect()
        except Exception as exc:
            logger.debug("cleanup: client disconnect failed: %s", exc, exc_info=True)
    for ws in ws_clients.copy():
        try:
            await ws.close()
        except Exception as exc:
            logger.debug("cleanup: websocket close failed: %s", exc, exc_info=True)
    ws_clients.clear()


app = FastAPI(
    title="Browser Helper API",
    version="1.35.1",
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

# Per-client session registry (each session owns its own tab + CDP client)
# max_sessions: hard cap — LRU eviction closes the least-recently-used
# session's tab when the cap is reached (client auto-heals on next call).
# B8: 30 (was 20) — burst of parallel agents no longer triggers mass eviction.
session_registry = SessionRegistry(ttl=1800.0, max_sessions=int(os.environ.get("BH_MAX_SESSIONS", "30")))

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
run_store = RunStore(max_runs=100)
recovery_advisor = RecoveryAdvisor()

# Connected WebSocket clients
ws_clients: set[WebSocket] = set()

# Shared state dict broadcast to WS clients on every change
state: dict[str, Any] = {
    "connected": False,
    "tabs_count": 0,
    "last_operation": None,
    "last_operation_time": None,
    "active_environment": environment_store.active_id,
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
    js: str | None = None
    expression: str | None = None  # alias for js — accepts {"expression": "..."} as POST /headless/eval does
    format: str = "raw"  # "raw" | "pretty" | "structured"

    @model_validator(mode="after")
    def _coalesce_js(self):
        if self.js is None and self.expression is None:
            raise ValueError("Missing 'js' (or 'expression') — pass {\"js\": \"...\"} or {\"expression\": \"...\"}")
        if self.js is None:
            self.js = self.expression  # type: ignore[assignment]
        return self


class ClickRequest(BaseModel):
    selector: str


class NavigateRequest(BaseModel):
    model_config = {"populate_by_name": True}

    url: str | None = None
    wait: bool | None = None  # None = default (wait for ready); False = return immediately after navigate
    timeout: int | None = None  # wait_for_ready timeout in seconds (overrides default 3s); ignored if wait is False
    wait_until: str | None = Field(None, description="domContentLoaded | load | networkIdle — default domContentLoaded (~400ms); networkIdle waits for quiet 400ms")
    # P0-3 parity with Playwright: inject storageState BEFORE navigate via Page.addScriptToEvaluateOnNewDocument
    origins: list[dict] | None = Field(None, description="Playwright-style origins list: [{origin, localStorage:[{name,value}]}] — injected via addScriptToEvaluateOnNewDocument BEFORE navigate, so first paint already sees the value. Example: [{origin:'https://example.com',localStorage:[{name:'receiptlens.locale',value:'fr'}]}]")
    # Alias: storageState for direct Playwright storageState parity (origins list)
    storage_state: list[dict] | dict | None = Field(None, alias="storageState", description="Alias for origins — Playwright storageState origins: [{origin, localStorage:[{name,value}]}]")


class TypeRequest(BaseModel):
    selector: str
    text: str


class ConnectRequest(BaseModel):
    cdp_url: str | None = None
    proxy: str | None = None


class ConnectRemoteRequest(BaseModel):
    """POST /connect/remote body — requires a WebSocket endpoint."""

    ws_endpoint: str = Field(..., min_length=1, description="CDP WebSocket URL (ws:// or wss://)")


class RateConfigRequest(BaseModel):
    """POST /rate/config body — partial updates allowed.

    Unknown fields are rejected (model_config extra='forbid'), string
    values for numeric fields fail pydantic validation → 422.
    """

    model_config = {"extra": "forbid"}

    enabled: bool | None = None
    min_delay_ms: float | None = Field(default=None, ge=0)
    max_delay_ms: float | None = Field(default=None, ge=0)
    distribution: str | None = None


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
    domain_min_interval_sec: float | None = None


class LaunchRequest(BaseModel):
    profile_dir: str | None = None
    port: int | None = None
    chrome_path: str | None = None


class StopRequest(BaseModel):
    pid: int | None = None


class StealthConfigRequest(BaseModel):
    """Stealth configuration: ``enabled`` is required, ``level`` optional.

    ``enabled`` is required so a bare POST without intent returns 422
    (matches the RED-phase contract tests).
    """

    enabled: bool
    level: str | None = Field(default=None, pattern=r"^(low|medium|high)$")


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
        if isinstance(data, dict) and "label" in data and "text" not in data:
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
    # P1-4 bundling — one round-trip for observation + evidence
    include_console: bool = False
    include_network: bool = False
    include_screenshot: bool = False
    # Back-compat: comma-separated include_evidence alias
    include_evidence: str | None = Field(None, description="Comma list: console,network,screenshot — alias for the three booleans above")
    # 304-style fingerprint cache: if the page fingerprint matches this id's
    # fingerprint, return {unchanged:true} without re-serializing nodes.
    if_none_match_snapshot_id: str | None = None


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
    pin_snapshot: bool = Field(default=True, description="Pin the snapshot_id during act to avoid GC — bool only (not a snap string). Use target.snapshot_id + target.ref.")
    auto_recover: bool = True
    observe_after: bool = True
    include_observation: bool | None = Field(None, description="False skips the returning observation snapshot (fast path ~115ms); default mirrors observe_after")
    wait_until_visible: bool = Field(default=False, description="If true, wait until selector is visible before click (single-call SPA hydration, P0-1)")
    wait_ms: int = Field(default=5000, ge=0, le=30000, description="Max wait for visibility when wait_until_visible=true (ms)")


class AgentSearchRequest(BaseModel):
    """One-call search: navigate to the engine, run the query, wait for the
    result, and return the answer text — no manual sleeps or extra reads."""

    query: str
    engine: str = "google"  # "perplexity" | "google" | "ddg" | "bing"
    timeout: int = 45
    result_selector: str | None = None  # override the engine's answer selector
    max_chars: int = 6000


class AgentFlowStep(BaseModel):
    """One step of a test flow.

    Action enum: navigate | click_text | click | type | submit | wait_text |
    wait | eval | screenshot.  Field usage: navigate→url, click_text→text,
    click→selector, type→selector+value, eval→js.  Alias: click → click_text
    when ``text`` is set but ``selector`` is not.
    """

    action: str  # navigate, click_text, click, type, submit, wait_text, wait, eval, screenshot
    url: str | None = None
    text: str | None = None
    selector: str | None = None
    value: str | None = None
    js: str | None = None
    timeout: int = 10
    expect: str | None = None  # text to wait for after the action (success marker)
    screenshot: bool = False


class AgentFlowRequest(BaseModel):
    """E2E test flow: ordered steps, optional screenshots + baseline diff.

    Returns a per-step report (ok/error, elapsed, screenshot artifact ids,
    diff result vs baseline) so a tester agent gets the whole run in one call.
    """

    name: str = "flow"
    steps: list[AgentFlowStep]
    baseline: bool = False  # capture baseline screenshots on first run
    diff: bool = False  # compare screenshots against stored baseline
    stop_on_error: bool = True
    auto_wait: bool = True  # wait for page ready after navigate/click


class AgentDiffRequest(BaseModel):
    """Visual comparison of two URLs (or two states of the same URL)."""

    url_a: str
    url_b: str | None = None  # None → diff current page against url_a
    wait_timeout: int = 25
    threshold: float = 0.001
    full_page: bool = False


class VisualRegressionRequest(BaseModel):
    """Multi-URL visual regression run: baseline or compare per URL."""

    urls: list[str]
    profile: str | None = None
    viewport: dict | None = None
    threshold: float = 0.001
    wait_timeout: int = 25
    record: bool = False  # True → capture baselines; False → compare


class AgentConsoleRequest(BaseModel):
    """Console/JS error inspection."""

    clear_first: bool = False  # clear the buffer before the next action
    level: str | None = None  # filter: error | warning | exception | network_error


class NetworkMockRequest(BaseModel):
    """Request interception rules (mock API responses)."""

    mocks: list[dict[str, Any]] = Field(default_factory=list)


class NetworkBlockRequest(BaseModel):
    """Network block rules (fail requests matching URL regexes)."""

    patterns: list[str] = Field(default_factory=list)


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


# P0-4: polling expect — auto-retry visible|hidden|text:Scan
class AgentExpectRequest(BaseModel):
    selector: str | None = Field(None, description="CSS selector to check (mutually exclusive with ref)")
    ref: str | None = Field(None, description="AX ref from the last /agent/observe snapshot (mutually exclusive with selector)")
    condition: str = Field("visible", description="visible | hidden | exists | gone | text:<substring> — e.g. 'text:Scan' checks innerText contains Scan")
    timeout: int = Field(5000, ge=100, le=60000, description="Max wait in ms (default 5000)")
    poll: int = Field(100, ge=10, le=2000, description="Poll interval in ms (default 100)")


# Artifact bundle (P0-5) — retained trace.zip analog of Playwright retain-on-failure
class ArtifactBundleRequest(BaseModel):
    retain: str = Field("on-failure", description="always | on-failure — retain artifacts even when the test passed")
    include: list[str] | None = Field(None, description="Subset: screenshot, console, network, trace — default all")


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


class FingerprintRequest(BaseModel):
    """Request body for POST /profile/{name}/fingerprint."""
    overrides: dict[str, Any] | None = None


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
# A3: Verbose 422 — turn raw Pydantic errors into actionable messages
# ---------------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", []))
        msg = err.get("msg", "validation error")
        typ = err.get("type", "")
        hint = ""
        if typ == "missing":
            hint = " (required field not provided)"
        elif "enum" in typ:
            hint = " (check allowed values)"
        elif "type_error" in typ or "string_type" in typ:
            hint = " (wrong type)"
        errors.append(f"{loc}: {msg}{hint}" if loc else f"{msg}{hint}")
    detail = "; ".join(errors) if errors else str(exc)
    # Add body hint for 422s that confuse agents (e.g. POST without JSON)
    if not errors or all("missing" in e for e in errors):
        detail += " — hint: check Content-Type: application/json and JSON body shape"
    return JSONResponse(status_code=422, content={"detail": detail, "errors": errors})


# ---------------------------------------------------------------------------
# Auth middleware — Bearer token check
# ---------------------------------------------------------------------------


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require Bearer token on all non-public endpoints."""
    if API_TOKEN:
        # Fix-5 (2026-08-12): reject known placeholder tokens so admins
        # don't accidentally leave the API open with "changeme" etc.
        PLACEHOLDER_TOKENS = {
            "changeme",
            "your-token",
            "replace-me",
            "placeholder",
            "changethis",
            "your_token_here",
            "your_api_token_here",
            "token_here",
        }
        if API_TOKEN.lower().strip() in PLACEHOLDER_TOKENS:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "API token is set to a placeholder value. "
                        "Please set a real API_TOKEN in the environment, "
                        "or unset it to disable auth (dev only)."
                    )
                },
            )
        path = request.url.path
        # Skip auth for public paths and OpenAPI docs
        if path not in PUBLIC_PATHS and not path.startswith(
            ("/docs", "/openapi.json", "/redoc")
        ):
            auth_header = request.headers.get("Authorization", "")
            token = auth_header[len("Bearer ") :] if auth_header.startswith("Bearer ") else ""
            if token != API_TOKEN:
                return JSONResponse(
                    status_code=401, content={"detail": "Invalid or missing API token"}
                )
    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Session middleware — per-client tab isolation
# ---------------------------------------------------------------------------

# Mutable holder so run_op (running in the endpoint's task, which receives a
# copy of the context) can publish a freshly minted session back to the
# middleware.  ``set()`` on the contextvar is task-local, but the list object
# is shared — run_op appends, the middleware reads after call_next.
_current_session: ContextVar[list[Session | None]] = ContextVar(
    "current_session", default=None
)

# 1.32: opt-in auto-mint flag — set by session_middleware when the caller
# sends ``X-Session-Auto: true`` or when ``BH_SESSION_AUTO=1`` is set.
# When true, header-less browser ops mint a fresh session (1.30 fallback)
# instead of returning 400.
_session_auto: ContextVar[bool] = ContextVar("session_auto", default=False)

# 1.33 P2-1: per-request trace id — set by session_middleware, read by
# log_operation so every entry carries the caller's journey correlation id.
_current_trace: ContextVar[str | None] = ContextVar("current_trace", default=None)

# Paths that operate on the shared default client / are session-agnostic.
_SESSION_EXEMPT = {
    "/health", "/ready", "/status", "/connect", "/disconnect",
    "/browser/launch", "/browser/stop", "/browser/status",
    "/session/new", "/sessions", "/session/close", "/ws", "/",
    "/api/v1/launchpad",
}


def _set_current_session(sess: Session | None) -> None:
    """Publish *sess* into the request-scoped holder (idempotent)."""
    holder = _current_session.get()
    if not holder:
        _current_session.set([sess])
    else:
        holder[0] = sess


def _get_current_session() -> Session | None:
    holder = _current_session.get()
    return holder[0] if holder else None


def _session_id_from_request(request: Request) -> str | None:
    """Return session id from cookie OR header — header wins (thread-local safe).

    The E2E harness reuses one CookieJar + one X-Session-ID across its ThreadPool
    (global active-tab pointer). 1.32 keeps header OR cookie as valid (no double
    requirement): the invoker attaches via _add_sid on every request, so either
    source is enough to stay sticky. Header is preferred so URL-scoped / rendered
    paths don't depend on cookie sync timing.
    """
    return request.headers.get("X-Session-ID") or request.cookies.get("bh_session")


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    """Attach the caller's session (cookie ``bh_session`` / header ``X-Session-ID``).

    Resolves an existing session (from cookie/header) and exposes it to the
    request via the ``_current_session`` holder.  New sessions are minted
    lazily by :func:`run_op` on the first real browser operation — run_op
    publishes the minted session into the shared holder, which is read here
    after the handler ran so the response can advertise it via
    ``Set-Cookie`` + ``X-Session-ID`` for the client to echo back.

    1.32: ``X-Session-Auto: true`` (or ``BH_SESSION_AUTO=1``) opts in to the
    lazy auto-mint fallback for simple harnesses; otherwise a 400 Missing
    session is returned for browser-mutating ops.  Header OR cookie is enough
    — no double requirement.

    1.33 (P2-1): every request gets a ``trace_id`` — echoed from an incoming
    ``X-Trace-ID`` or minted (``tr_`` + uuid8) — attached to every
    log_operation entry so ``GET /logs?trace_id=...`` can correlate a full
    observe→act→assert journey. The response always carries ``X-Trace-ID``.
    """
    sid = _session_id_from_request(request)
    auto = request.headers.get("X-Session-Auto", "").strip().lower() in ("1", "true", "yes") or os.environ.get("BH_SESSION_AUTO", "").strip().lower() in ("1", "true", "yes")
    _session_auto.set(auto)
    # P2-1 structured logging: propagate or mint a trace id for this request
    trace_id = request.headers.get("X-Trace-ID") or f"tr_{uuid.uuid4().hex[:12]}"
    _current_trace.set(trace_id)
    sess = session_registry.get(sid) if sid else None
    _set_current_session(sess)
    try:
        response = await call_next(request)
        # run_op may have replaced the session with a freshly minted one.
        active = _get_current_session()
    finally:
        _current_session.set([])
        _session_auto.set(False)
        _current_trace.set(None)
    response.headers["X-Trace-ID"] = trace_id
    if active is not None:
        response.headers["X-Session-ID"] = active.session_id
        if active is not sess:
            response.set_cookie(
                "bh_session", active.session_id, max_age=86400 * 7,
                httponly=True, samesite="lax",
            )
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
    except Exception as exc:
        logger.debug("read /proc/self/status failed: %s", exc, exc_info=True)
    return 0.0


def log_operation(
    operation: str,
    status: str,
    duration_ms: float,
    details: str = "",
    *,
    verification: str = "unverified",
) -> dict[str, Any]:
    """Append an operation entry to the ring buffer and update global state.

    P2-1: entries carry the request-scoped ``trace_id`` (from the
    ``X-Trace-ID`` header or minted by session_middleware) so a whole
    observe→act→assert journey is correlatable via ``GET /logs?trace_id=``.
    """
    entry = {
        "timestamp": datetime.now(_UTC).isoformat(),
        "operation": operation,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "details": details,
        "trace_id": _current_trace.get(),
    }
    run = run_store.record(
        operation, status, duration_ms, details, verification=verification
    )
    entry["run_id"] = run["run_id"]
    entry["verification"] = run["verification"]
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
        except Exception as exc:
            logger.debug("ws broadcast failed: %s", exc, exc_info=True)
            stale.add(ws)
    if stale:
        ws_clients.difference_update(stale)


def ensure_connected():
    """Raise 400 if the CDP client is not connected."""
    if not client.is_connected:
        raise HTTPException(status_code=400, detail="Not connected to CDP. Call POST /connect first.")


def _local_cdp_http() -> str:
    """Return the local Chrome CDP HTTP base URL (saved launched port).

    ``CHROME_AUTO_PORT`` env wins when set (test suites launch a dedicated
    Chrome and must not touch the production one); otherwise fall back to
    the saved launched port, then the configured debug port.
    """
    env_port = os.environ.get("CHROME_AUTO_PORT")
    if env_port:
        return f"http://127.0.0.1:{env_port}"
    port = settings_mgr.get("chrome_launched_port") or settings_mgr.get("chrome_debug_port", 9557)
    return f"http://127.0.0.1:{port}"


def _reap_orphan_headless() -> int:
    """Kill headless Chrome processes not owned by live headless sessions.

    The HeadlessManager tracks its sessions in memory; after a restart or
    crash those handles are gone and the spawned Chrome processes become
    orphans (ppid=1) that the timeout guard can never close.  This scans
    for all ``chrome`` processes with ``--headless`` or
    ``--remote-debugging-port`` and kills those whose PID is not in the
    current session pool.  Returns the number killed.
    """
    import subprocess

    try:
        # Match all headless Chrome AND any Chrome on non-standard ports
        # (port=0, port=19xxx) that could be orphans from previous runs.
        out = subprocess.run(
            ["pgrep", "-af", "chrome.*--headless|chrome.*remote-debugging-port="],
            capture_output=True, text=True, timeout=10,
            check=False,  # pgrep returns non-zero when no match
        )
    except Exception as exc:
        logger.debug("pgrep chrome scan failed: %s", exc, exc_info=True)
        return 0
    lines = out.stdout.strip().split("\n")
    pids = [l.split()[0] for l in lines if l and l.split()[0].isdigit()]
    if not pids:
        return 0

    # Identify the main browser-helper Chrome (the one on port 9557)
    main_port = (
        settings_mgr.get("chrome_launched_port")
        or settings_mgr.get("chrome_debug_port")
        or 9557
    )
    try:
        out2 = subprocess.run(
            ["pgrep", "-af", f"remote-debugging-port={main_port}"],
            capture_output=True, text=True, timeout=5,
            check=False,  # pgrep returns non-zero when no match
        )
        main_pids = {l.split()[0] for l in out2.stdout.strip().split("\n")
                     if l and l.split()[0].isdigit()}
    except Exception as exc:
        logger.debug("pgrep main-port scan failed: %s", exc, exc_info=True)
        main_pids = set()

    try:
        live = {str(h.chrome_pid) for h in headless_mgr.pool.all_sessions()}
    except Exception as exc:
        logger.debug("headless session pool query failed: %s", exc, exc_info=True)
        live = set()

    killed = 0
    for pid in pids:
        if pid in live or pid in main_pids:
            continue  # owned by a live session or the main browser — leave it
        try:
            subprocess.run(
                ["kill", "-9", pid], capture_output=True, timeout=5,
                check=False,  # process may already be gone
            )
            killed += 1
        except Exception as exc:
            logger.debug("best-effort kill of orphan chrome failed: %s, %s", pid, exc, exc_info=True)
    if killed:
        logger.warning("Reaped %d orphaned Chrome PID(s)", killed)
    return killed


async def _ensure_global_client_attached() -> None:
    """Attach the global default client to a STABLE CDP endpoint.

    Since v1.24 the per-client sessions run on their own CDPClients; the
    global ``client`` is only used by legacy cookie-less paths.  It must NOT
    attach to a page target — session churn (``_reap_orphan_tabs`` closing
    unowned tabs, sessions dying) would kill the WS and flip
    ``state[\"connected\"]`` to False, which the watchdog used to misread as
    \"Chrome dead\" and auto-restart every 5 minutes (user-observed).

    The browser-level WebSocket (``/devtools/browser/<id>``) survives tab
    open/close — that is the correct anchor for the global client.
    """
    main_port = (
        settings_mgr.get("chrome_launched_port")
        or settings_mgr.get("chrome_debug_port")
        or 9557
    )
    client.cdp_http_url = f"http://127.0.0.1:{main_port}"
    if client.is_connected:
        return
    try:
        import httpx as _httpx

        async with _httpx.AsyncClient(timeout=3.0) as http:
            resp = await http.get(f"http://127.0.0.1:{main_port}/json/version")
            if resp.status_code != 200:
                raise ConnectionError("Chrome not responding")
            ws_url = resp.json().get("webSocketDebuggerUrl", "")
        if not ws_url:
            raise ConnectionError("no browser WebSocket URL in /json/version")
        await client.connect_browser(ws_url)
        state["connected"] = True
        state["cdp_url"] = ws_url
        logger.info("Global client attached to browser-level CDP: %s", ws_url)
    except Exception as exc:
        logger.debug("Global client browser-level attach failed: %s", exc, exc_info=True)


async def _chrome_health_watchdog() -> None:
    """Periodic background task: reap orphan Chrome + auto-restart if dead.

    After 2026-09-02 fix: 5-minute interval (was 120s), 2-tick debounce
    (3 probes ×8s inline → 24s confirmed downtime per tick, then 1 tick
    defer → ~10 min before a SingletonLock-clearing relaunch). A transient
    GC / X stall no longer kills a live Chrome (observed 2026-09-02: GC
    log arrived 30s after the watchdog had already relaunched).
    """

    WATCHDOG_INTERVAL = 300  # 5 min — 120s was too aggressive for X/extension stalls
    _FAIL_PROBES = 3  # probes per tick, 8s apart → ~24s confirmed downtime
    _FAIL_TICKS = 2  # require N consecutive failed ticks before relaunch
    _consecutive_failed_ticks = 0
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL)
        try:
            # 1. Reap orphan headless Chrome
            reaped = _reap_orphan_headless()
            if reaped:
                logger.info("Watchdog: reaped %d orphan Chrome process(es)", reaped)

            # 2. Check if the main Chrome is alive — probe the CDP HTTP port,
            # NOT the global client's WS state.  Since v1.24 the per-client
            # sessions run on their OWN CDPClients; the global `client` is
            # only used by legacy cookie-less paths and may be disconnected
            # while Chrome (and every active session) is perfectly healthy.
            # Watching `client.is_connected` here caused a false-positive
            # auto-restart every 5 minutes (user-observed: Chrome restarted
            # suspiciously often, soft-start warm-up repeated constantly).
            main_port = (
                settings_mgr.get("chrome_launched_port")
                or settings_mgr.get("chrome_debug_port")
                or 9557
            )
            # Inline retry: 3 probes spaced 8s — transient stalls don't count
            _probe_ok = False
            _last_exc: Exception | None = None
            for _pi in range(_FAIL_PROBES):
                if chrome_mgr._launch_in_progress:
                    logger.info("Watchdog: launch already in progress — skipping probe")
                    _probe_ok = True
                    break
                try:
                    import httpx as _httpx

                    async with _httpx.AsyncClient(timeout=5.0) as http:
                        resp = await http.get(f"http://127.0.0.1:{main_port}/json/version")
                        if resp.status_code == 200:
                            # Chrome is up.  If the global client happens to be
                            # disconnected, re-attach it quietly (no restart).
                            if not client.is_connected:
                                await _ensure_global_client_attached()
                            _probe_ok = True
                            break
                        raise ConnectionError(f"Chrome HTTP {resp.status_code}")
                except Exception as exc:  # noqa: BLE001 — probe: any failure counts
                    _last_exc = exc
                    logger.debug("watchdog probe %d/%d failed: %s", _pi + 1, _FAIL_PROBES, exc, exc_info=True)
                    if _pi + 1 < _FAIL_PROBES:
                        await asyncio.sleep(8.0)
            if _probe_ok:
                _consecutive_failed_ticks = 0
                continue  # Chrome alive — nothing to do

            # All inline probes failed — count the failed tick; defer the first
            # one.  A single ~24s stall (GC, X repaint) defers; only a 2nd
            # consecutive failed tick (~5 min later) triggers relaunch.
            _consecutive_failed_ticks += 1
            if _consecutive_failed_ticks < _FAIL_TICKS:
                logger.info(
                    "Watchdog: chrome probe failed (%d/%d) after %d probes — deferring relaunch until next tick (last: %s)",
                    _consecutive_failed_ticks, _FAIL_TICKS, _FAIL_PROBES, _last_exc,
                )
                continue
            _consecutive_failed_ticks = 0  # reset for the post-relaunch cycle
            exc = _last_exc or ConnectionError("Chrome not responding")
            try:
                raise exc
            except Exception as exc:  # keep existing `exc` handling path below
                logger.debug("chrome health check failed (debounced): %s", exc, exc_info=True)
                # Chrome not running at all — launch a new one.  But if a
                # launch is ALREADY in progress (run_op triggered it and the
                # warm-up window is still open), do NOT spawn a second
                # instance — the two would fight over the profile
                # SingletonLock and both die (observed 2026-08-11: json/new
                # 500s, launch storm).  Wait for the in-flight launch instead.
                if chrome_mgr._launch_in_progress:
                    logger.info("Watchdog: launch already in progress — waiting instead of relaunching")
                    await asyncio.sleep(5.0)
                    continue
                # R5 diagnostics: log WHY Chrome likely died — RSS of any
                # surviving chrome processes, last operation + its time, and
                # the session count at death.  Without this the "Chrome not
                # running" mystery (3× on 2026-08-23, no OOM trace) is
                # undebuggable from logs alone.
                try:
                    import subprocess as _sp

                    ps_out = _sp.run(  # noqa: ASYNC221 — 5s-bounded, watchdog path only
                        ["ps", "-eo", "rss,comm,args"], capture_output=True, text=True,
                        timeout=5, check=False,
                    ).stdout
                    chrome_rss = [
                        int(line.split()[0]) // 1024
                        for line in ps_out.splitlines()
                        if "chrome" in line.lower() and "grep" not in line
                    ]
                    total_mb = sum(chrome_rss)
                    logger.warning(
                        "Watchdog context: chrome procs alive=%d rss_total=%dMB; last_op=%s@%s; sessions=%d",
                        len(chrome_rss), total_mb,
                        state.get("last_operation"), state.get("last_operation_time"),
                        session_registry.count,
                    )
                except Exception as exc_diag:  # noqa: BLE001 — diagnostics must never block relaunch
                    logger.debug("watchdog diagnostics failed: %s", exc_diag)
                logger.warning("Watchdog: Chrome not running, launching fresh instance: %s", exc)
                try:
                    await chrome_mgr.launch()
                    await _ensure_global_client_attached()
                except Exception as exc2:
                    logger.warning("Watchdog: auto-launch failed: %s", exc2, exc_info=True)
        except Exception as exc:
            logger.debug("Chrome health watchdog iteration failed: %s", exc, exc_info=True)


def _resolve_session(request: Request) -> Session | None:
    """Resolve the caller's session from cookie or X-Session-ID header.

    Returns None when the caller has no session — the caller then falls back
    to the shared default client (legacy behaviour).
    """
    sid = request.cookies.get("bh_session") or request.headers.get("X-Session-ID")
    return session_registry.get(sid)


async def _ensure_browser(sess: Session | None = None) -> None:
    """
    Ensure a live CDP connection, launching and/or connecting to Chrome if needed.

    Lazy auto-start: if Chrome is not running, launch it with the saved profile
    on the saved debug port; then (re)connect to the *local* Chrome CDP endpoint.
    Uses the saved ``chrome_launched_port`` (default 9557) — NOT the CDPClient
    default (9555), which may be another machine's SSH tunnel.

    When *sess* is given, ensures that session's own client is connected to its
    dedicated tab (creating the session lazily is handled by the caller).
    Otherwise ensures the shared default client.
    """
    target = sess.client if sess is not None else client
    if target.is_connected:
        # Even when already connected, force-hold if the browser was just
        # (re)launched and the proxy extension is still warming up — the
        # first navigation would otherwise bypass the proxy and flash the
        # auth dialog.
        await chrome_mgr.await_chrome_ready()
        return
    if os.environ.get("BH_TEST_NO_CHROME") == "1":
        # Test isolation (MCP integration tests): never connect to a real
        # Chrome. CDP-gated calls then fail with the deterministic CDP
        # error instead of attaching to the live browser-helper service.
        raise HTTPException(
            status_code=503,
            detail="Chrome CDP unavailable: BH_TEST_NO_CHROME test isolation",
        )
    cdp_http = _local_cdp_http()
    try:
        launch_result = await chrome_mgr.launch()
        if launch_result.get("status") != "ok":
            logger.warning(
                "Auto-launch failed (continuing with connect attempt): %s",
                launch_result.get("error", "unknown"),
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Auto-launch exception (continuing): %s", exc, exc_info=True)

    # Connect to the local Chrome on the saved launched port (NOT the 9555 default)
    target.cdp_http_url = cdp_http
    try:
        if sess is not None:
            # Re-attach to the session's dedicated tab (heals a closed tab by
            # recreating it via the HTTP endpoint — no WS needed yet).
            try:
                await target.connect_to_target(sess.tab_id)
            except Exception as exc:
                logger.debug("tab reconnect failed (recreating tab): %s", exc, exc_info=True)
                # Tab gone — recreate it and update the session.
                new_tab = await session_registry._open_tab_http(target)
                sess.tab_id = new_tab
                await target.connect_to_target(sess.tab_id)
            state["connected"] = True
            state["cdp_url"] = target.cdp_http_url
        else:
            # Global (session-less) path: attach to the browser-level WS so
            # the connection survives tab churn (see _ensure_global_client_attached).
            await _ensure_global_client_attached()
            if not client.is_connected:
                raise ConnectionError("browser-level attach failed")
        logger.info("Auto-connected to local Chrome at %s", state["cdp_url"])
    except Exception as exc:
        logger.warning("auto-connect to local chrome failed: %s", exc, exc_info=True)
        state["connected"] = False
        raise HTTPException(
            status_code=503,
            detail=f"Chrome unavailable: could not launch/connect to CDP at {cdp_http}: {exc}",
        )


async def _resolve_session_client(require_session: bool = True) -> tuple[CDPClient, Session | None]:
    """Resolve the caller's session client.

    Endpoints that use ``client.xxx`` directly (instead of ``run_op``) must call
    this first to route onto the caller's own session tab — otherwise they hit
    the shared default tab and break per-client isolation.

    When *require_session* is True (default), a missing session (no
    ``X-Session-ID`` / ``bh_session`` cookie) raises 400 instead of lazily
    minting a new tab — this prevents the tab-leak / session-drift where
    every header-less call opened a fresh about:blank tab (P0).  1.32:
    ``X-Session-Auto: true`` (or ``BH_SESSION_AUTO=1``) re-enables lazy
    auto-mint for simple callers.  Callers that genuinely need a fresh
    session must POST /session/new first and echo the returned
    ``X-Session-ID`` OR ``bh_session`` (one of them is enough).
    Tests stub this helper, so they are unaffected.

    Returns ``(target_client, session)``.  When session creation fails (e.g.
    tests without Chrome) and require_session is False, falls back to
    ``(client, None)``.
    """
    sess = _get_current_session()
    if sess is None:
        if require_session:
            if _session_auto.get() or os.environ.get("BH_SESSION_AUTO", "").strip().lower() in ("1", "true", "yes"):
                try:
                    await chrome_mgr.launch()  # idempotent — reuses running Chrome
                    sess = await session_registry.create(_local_cdp_http())
                    _set_current_session(sess)
                    logger.info("Auto-minted session %s (tab %s) via X-Session-Auto opt-in (_resolve)", sess.session_id[:8], sess.tab_id[:8])
                except Exception as exc:
                    logger.warning("X-Session-Auto session creation failed in _resolve_session_client: %s", exc, exc_info=True)
                    sess = None
            if sess is None:
                # Tests set BH_TEST_NO_CHROME and stub this helper entirely, so
                # this branch is never hit in the test suite (see tests/conftest.py).
                raise HTTPException(
                    status_code=400,
                    detail="Missing session: send X-Session-ID header (or bh_session cookie) from POST /session/new; header-less browser ops no longer auto-mint (P0 tab-leak fix). Opt-in with X-Session-Auto: true or set BH_SESSION_AUTO=1",
                )
        else:
            try:
                await chrome_mgr.launch()  # idempotent — reuses running Chrome
                sess = await session_registry.create(_local_cdp_http())
                _set_current_session(sess)
                logger.info("Auto-minted session %s (tab %s) for cookie-less client — caller should reuse X-Session-ID", sess.session_id[:8], sess.tab_id[:8])
            except Exception as exc:
                logger.warning("Session creation failed, falling back to default client: %s", exc, exc_info=True)
                sess = None
    if sess is not None:
        await _ensure_browser(sess)
        return sess.client, sess
    else:
        await _ensure_browser()
        return client, None


def infer_verification(result: Any) -> str:
    """Infer only explicit outcome verification; never equate transport success with proof."""
    if not isinstance(result, dict):
        return "unverified"
    direct = result.get("verified")
    if isinstance(direct, bool):
        return "verified" if direct else "failed"
    verification = result.get("verification")
    if isinstance(verification, dict) and isinstance(verification.get("verified"), bool):
        return "verified" if verification["verified"] else "failed"
    confirmation = result.get("confirmation")
    if isinstance(confirmation, dict):
        state_change = confirmation.get("state_change")
        if isinstance(state_change, dict) and isinstance(state_change.get("changed"), bool):
            return "verified" if state_change["changed"] else "failed"
    return "unverified"


async def run_op(operation: str, method, *args, sess_override: Session | None = None, session_hook=None, **kwargs) -> dict[str, Any]:
    """
    Execute a CDP client method, time it, log it, broadcast state,
    and return a standardised response dict.

    Runs on the caller's session tab when the session middleware attached a
    session to this request (``_current_session`` contextvar), or when
    *sess_override* is given (MCP tools mint their own session and pass it
    explicitly — contextvars do not survive the FastMCP tool-task boundary);
    otherwise on the shared default client (legacy behaviour).

    *session_hook* (optional callable) is invoked with the resolved session
    right after it is determined/minted, letting callers cache it.
    """
    sess = sess_override if sess_override is not None else _get_current_session()
    if sess is None:
        # 1.31 P0 fix: header-less browser ops no longer auto-mint a fresh tab
        # (that caused session drift + tab-leak: every header-less call opened
        # a new about:blank tab).  Callers must POST /session/new first and
        # echo X-Session-ID OR bh_session on every later call (header OR cookie,
        # not both).
        # 1.32: ``X-Session-Auto: true`` (or ``BH_SESSION_AUTO=1``) re-enables
        # the 1.30 lazy auto-mint for simple harnesses.  Check the request flag
        # via _session_auto ContextVar (set by session_middleware).
        # Exceptions:
        #  - global read-only ops (get_tabs etc.) run on the shared client
        #  - tests (PYTEST_CURRENT_TEST / BH_TEST_NO_CHROME) keep the old
        #    fallback so the suite stays green without per-test session setup
        _GLOBAL_OPS = {"get_tabs", "scan_all_tabs", "sessions_list", "mcp_status", "get_status", "health", "status", "sessions"}
        if operation in _GLOBAL_OPS:
            sess = None
        elif os.environ.get("PYTEST_CURRENT_TEST") is not None or os.environ.get("BH_TEST_NO_CHROME") == "1":
            if os.environ.get("BH_TEST_NO_CHROME") == "1":
                sess = None
            else:
                try:
                    await chrome_mgr.launch()  # idempotent — reuses running Chrome
                    sess = await session_registry.create(_local_cdp_http())
                    _set_current_session(sess)
                except Exception as exc:
                    logger.warning("Session creation failed, falling back to default client: %s", exc, exc_info=True)
                    sess = None
        elif _session_auto.get() or os.environ.get("BH_SESSION_AUTO", "").strip().lower() in ("1", "true", "yes"):
            try:
                await chrome_mgr.launch()  # idempotent — reuses running Chrome
                sess = await session_registry.create(_local_cdp_http())
                _set_current_session(sess)
                logger.info("Auto-minted session %s (tab %s) via X-Session-Auto/BH_SESSION_AUTO opt-in", sess.session_id[:8], sess.tab_id[:8])
            except Exception as exc:
                logger.warning("X-Session-Auto session creation failed, falling back to default client: %s", exc, exc_info=True)
                sess = None
        else:
            raise HTTPException(
                status_code=400,
                detail="Missing session: send X-Session-ID header (or bh_session cookie) from POST /session/new; header-less browser ops no longer auto-mint (P0 tab-leak fix). Opt-in with X-Session-Auto: true or set BH_SESSION_AUTO=1",
            )
    if sess is not None and session_hook is not None:
        try:
            session_hook(sess)
        except Exception as exc:
            logger.debug("session hook failed: %s", exc, exc_info=True)
    if sess is not None:
        # Route the operation onto the session's own client: the REST
        # endpoints pass a bound method of the *global* client; rebind the
        # same method name onto the session client so the op runs on the
        # session's dedicated tab.
        method_name = getattr(method, "__name__", None)
        if method_name and hasattr(sess.client, method_name):
            method = getattr(sess.client, method_name)
        target = sess.client
    else:
        target = client
    try:
        # Force-hold during the proxy-extension warm-up window (soft-start):
        # the first browser operation must NOT race the extension init,
        # otherwise the navigation bypasses the proxy and shows the auth
        # dialog (seen as the "proxy password" popup on VNC).
        await chrome_mgr.await_chrome_ready()
        await _ensure_browser(sess)
        # Fix-3 (2026-08-12): if the target still is not connected after
        # ensure (launch + attach failed or the session's tab died), fail
        # with 409 Conflict + a clear message instead of returning a
        # misleading success envelope or a raw CDP error.
        if not target.is_connected:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Browser not connected (CDP session lost). "
                    "The browser-helper service is up, but no live Chrome/CDP "
                    "session is attached to this session's tab. "
                    "Call POST /connect to re-attach, then retry."
                ),
            )
        start = time.monotonic()
        try:
            # Domain throttle: never hammer a site with rapid back-to-back
            # navigations (multiple systems share this service). Applies to
            # navigate-style ops that carry a URL; interval is configurable
            # via settings.json ``domain_min_interval_sec`` (default 4.0s).
            if operation in ("navigate", "search_navigate") and args and isinstance(args[0], str):
                # Localhost / 127.0.0.1 / ::1 never throttled (control plane, tests)
                _url = str(args[0])
                _is_local = any(h in _url for h in ("127.0.0.1", "localhost", "::1", "0.0.0.0"))
                if _is_local:
                    waited = 0.0
                else:
                    raw_interval = settings_mgr.get("domain_min_interval_sec", 4.0)
                    try:
                        interval = float(raw_interval) if raw_interval is not None else 4.0
                    except (TypeError, ValueError):
                        interval = 4.0
                    waited = await domain_throttle.wait(args[0], interval)
                if waited > 0:
                    logger.info(
                        "Domain throttle: waited %.2fs before navigate to %s",
                        waited,
                        domain_throttle._domain_of(args[0]),
                    )
            # Navigate serialization: Chrome's CDP WebSocket can only handle
            # one Page.navigate at a time.  Without this lock, concurrent
            # navigations from multiple sessions cause 30s timeouts and
            # auto-heal tab storms.  The throttle waits ABOVE run inside the
            # lock so multiple callers can queue their throttle concurrently.
            if operation in ("navigate", "search_navigate"):
                async with _navigate_lock:
                    result = await method(*args, **kwargs)
            else:
                result = await method(*args, **kwargs)
            elapsed = (time.monotonic() - start) * 1000
            # Some CDP methods return a generator/iterator (e.g. streaming
            # results). Consuming it twice (str() for the log, then JSON
            # serialization in api_success) raised
            # "Cannot reuse already used iterator". Materialize it once so
            # both consumers see the same data.
            if hasattr(result, "__anext__"):
                # async generator
                items = []
                async for item in result:
                    items.append(item)
                result = items
            elif hasattr(result, "__next__") and not isinstance(result, (str, bytes, dict, list, tuple, set)):
                # sync iterator (map/filter/generator)
                result = list(result)
            verification = infer_verification(result)
            entry = log_operation(
                operation, "success", elapsed, str(result)[:200], verification=verification
            )
            _record_latency(operation, elapsed)
            await broadcast_state()
            return api_success(
                operation,
                result,
                meta={"run_id": entry["run_id"], "verification": entry["verification"]},
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            logger.exception("Operation '%s' failed", operation)
            entry = log_operation(operation, "error", elapsed, str(exc))
            _record_latency(f"{operation}:error", elapsed)
            await broadcast_state()
            status = 504 if isinstance(exc, TimeoutError) else 503 if "connect" in str(exc).lower() else 400
            return api_error(operation, "operation_failed", str(exc), status)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Browser setup failed for '%s'", operation)
        raise HTTPException(status_code=503, detail=f"Browser setup failed: {exc}")


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


@app.get("/api/v1/launchpad")
async def get_daily_launchpad():
    """Return one bounded, privacy-safe daily-work summary for the dashboard."""
    data = build_daily_launchpad(
        environments=environment_store.list(),
        workflows=workflow_catalog.list(),
        runs=run_store.list_runs(limit=20),
        connected=bool(state.get("connected")),
        tab_count=int(state.get("tabs_count", 0) or 0),
    )
    return api_success("daily_launchpad", data)


@app.get("/api/v1/workflows")
async def list_workflow_catalog(include_archived: bool = False):
    items = workflow_catalog.list(include_archived=include_archived)
    return api_success("workflow_catalog_list", {"count": len(items), "workflows": items})


@app.post("/api/v1/workflows", status_code=201)
async def create_catalog_workflow(body: dict[str, Any]):
    try:
        return api_success("workflow_catalog_create", workflow_catalog.create(body), 201)
    except ValueError as exc:
        return api_error("workflow_catalog_create", "invalid_workflow", str(exc), 422)


@app.get("/api/v1/workflows/{workflow_id}")
async def get_catalog_workflow(workflow_id: str, version: int | None = None):
    item = workflow_catalog.get(workflow_id, version)
    if item is None:
        return api_error("workflow_catalog_get", "workflow_not_found", "Workflow was not found.", 404)
    return api_success("workflow_catalog_get", item)


@app.post("/api/v1/workflows/{workflow_id}/versions", status_code=201)
async def create_catalog_workflow_version(workflow_id: str, body: dict[str, Any]):
    try:
        item = workflow_catalog.create_version(workflow_id, body)
    except KeyError:
        return api_error("workflow_catalog_version", "workflow_not_found", "Workflow was not found.", 404)
    except ValueError as exc:
        return api_error("workflow_catalog_version", "invalid_workflow", str(exc), 422)
    return api_success("workflow_catalog_version", item, 201)


@app.post("/api/v1/workflows/{workflow_id}/resolve")
async def resolve_catalog_workflow(workflow_id: str, body: dict[str, Any]):
    try:
        item = workflow_catalog.resolve(workflow_id, body.get("parameters", {}), body.get("version"))
    except KeyError:
        return api_error("workflow_catalog_resolve", "workflow_not_found", "Workflow was not found.", 404)
    except ValueError as exc:
        return api_error("workflow_catalog_resolve", "invalid_parameters", str(exc), 422)
    return api_success("workflow_catalog_resolve", item)


@app.post("/api/v1/workflows/{workflow_id}/archive")
async def archive_catalog_workflow(workflow_id: str):
    item = workflow_catalog.archive(workflow_id)
    if item is None:
        return api_error("workflow_catalog_archive", "workflow_not_found", "Workflow was not found.", 404)
    return api_success("workflow_catalog_archive", item)


@app.get("/api/v1/environments")
async def list_environments():
    """List reusable environment recipes without credential values."""
    items = environment_store.list()
    return api_success("environment_list", {"count": len(items), "environments": items})


@app.post("/api/v1/environments", status_code=201)
async def create_environment(body: dict[str, Any]):
    """Create a validated, privacy-safe environment recipe."""
    try:
        item = environment_store.create(body)
    except ValueError as exc:
        return api_error("environment_create", "invalid_environment", str(exc), 422)
    return api_success("environment_create", item, 201)


@app.get("/api/v1/environments/{environment_id}")
async def get_environment(environment_id: str):
    item = environment_store.get(environment_id)
    if item is None:
        return api_error("environment_get", "environment_not_found", "Environment was not found.", 404)
    return api_success("environment_get", item)


@app.post("/api/v1/environments/{environment_id}/activate")
async def activate_environment(environment_id: str):
    """Select a recipe as active context; launching remains an explicit action."""
    item = environment_store.activate(environment_id)
    if item is None:
        return api_error("environment_activate", "environment_not_found", "Environment was not found.", 404)
    state["active_environment"] = item["environment_id"]
    await broadcast_state()
    return api_success("environment_activate", item)


@app.delete("/api/v1/environments/{environment_id}")
async def delete_environment(environment_id: str):
    result = environment_store.delete(environment_id)
    if result == "active":
        return api_error("environment_delete", "environment_active", "Deactivate or activate another environment before deletion.", 409)
    if result == "missing":
        return api_error("environment_delete", "environment_not_found", "Environment was not found.", 404)
    return api_success("environment_delete", {"environment_id": environment_id, "deleted": True})


@app.get("/api/v1/runs")
async def list_runs(status: str | None = None, limit: int = Query(50, ge=1, le=100)):
    """Return newest-first, redacted operation runs with bounded retention."""
    runs = run_store.list_runs(status=status, limit=limit)
    return api_success("run_timeline_list", {"count": len(runs), "runs": runs})


@app.get("/api/v1/runs/compare")
async def compare_retained_runs(left: str, right: str):
    """Compare privacy-safe metadata for two retained runs."""
    left_run = run_store.get(left)
    right_run = run_store.get(right)
    if left_run is None or right_run is None:
        missing = left if left_run is None else right
        return api_error(
            "run_compare", "run_not_found", f"Run {missing[:80]} is no longer available.", 404
        )
    return api_success("run_compare", compare_runs(left_run, right_run))


@app.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str):
    """Return one retained, redacted run by its correlation ID."""
    run = run_store.get(run_id)
    if run is None:
        return api_error("run_get", "run_not_found", "The requested run is no longer available.", 404)
    return api_success("run_get", run)


@app.get("/api/v1/runs/{run_id}/recovery")
async def run_recovery(run_id: str):
    """Return deterministic recovery guidance without automatically retrying."""
    run = run_store.get(run_id)
    if run is None:
        return api_error(
            "run_recovery", "run_not_found", "The requested run is no longer available.", 404
        )
    return api_success("run_recovery", recovery_advisor.advise(run))


@app.get("/api/v1/runs/{run_id}/support")
async def run_support_bundle(run_id: str):
    """Build a bounded, redacted support document for one operation run."""
    run = run_store.get(run_id)
    if run is None:
        return api_error(
            "run_support_bundle", "run_not_found", "The requested run is no longer available.", 404
        )
    capabilities = _capability_registry.as_dict()
    bundle = {
        "schema_version": 1,
        "generated_at": datetime.now(_UTC).isoformat(),
        "run": run,
        "browser_context": {
            "connected": bool(client.is_connected),
            "tabs_count": int(client.tabs_count),
            "last_operation": state.get("last_operation"),
            "last_operation_time": state.get("last_operation_time"),
        },
        "capability_summary": capabilities["summary"],
        "privacy": {
            "redacted": True,
            "includes_page_content": False,
            "includes_credentials": False,
        },
    }
    return api_success("run_support_bundle", bundle)


@app.delete("/api/v1/runs")
async def clear_runs():
    """Clear the process-local run timeline without affecting browser state."""
    return api_success("run_timeline_clear", {"cleared": run_store.clear()})


@app.get("/api/v1/capabilities")
async def capability_readiness():
    """Return privacy-safe product maturity and dependency guidance."""
    return api_success("capability_readiness", _capability_registry.as_dict())


@app.get("/status")
async def get_status():
    """Return current connection status."""
    return {
        "connected": client.is_connected,
        # A default client külön él a session-öktől; ha session-ök vannak,
        # a böngésző elérhető, még ha a default client nincs is csatlakoztatva.
        "browser_available": client.is_connected or session_registry.count > 0,
        "tabs_count": client.tabs_count,
        "last_operation": state["last_operation"],
        "last_operation_time": state["last_operation_time"],
        "active_environment": state.get("active_environment"),
        "cdp_url": state["cdp_url"],
        "log_size": len(operation_log),
        "sessions": session_registry.count,
    }


# ---------------------------------------------------------------------------
# Per-client sessions
# ---------------------------------------------------------------------------


@app.post("/session/new")
async def session_new(url: str = Query("about:blank", description="Initial URL for the new session's tab"),
                      profile: str | None = Query(None, description="Profile name for cookie isolation (optional)")):
    """Mint a new isolated session with its own dedicated browser tab.

    The session id is returned in the ``X-Session-ID`` header and as a
    ``bh_session`` cookie; the client simply echoes it back on later calls.
    Header OR cookie is enough (not both).  ``/session/new`` responds with
    ``data``=``result`` containing ``session_id`` (both for compat).

    With *profile* set, the session gets a dedicated Chrome profile (own
    cookies/storage) — full isolation between clients.
    """
    try:
        await chrome_mgr.launch()
        profile_dir = None
        if profile:
            from profile_manager import ProfileManager

            pm = ProfileManager()
            pd = pm.get_data_dir(profile)
            if not pd:
                # Create the profile on the fly.
                pm.create_profile(profile)
                pd = pm.get_data_dir(profile)
            profile_dir = pd
        sess = await session_registry.create(_local_cdp_http(), url=url, profile_dir=profile_dir)
    except Exception as exc:
        logger.exception("Session creation failed")
        return api_error("session_new", "session_creation_failed", str(exc), 503)
    body = api_success("session_new", {"session_id": sess.session_id, "tab_id": sess.tab_id, "url": url})
    return JSONResponse(
        content=body,
        headers={
            "X-Session-ID": sess.session_id,
            "Set-Cookie": f"bh_session={sess.session_id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800",
        },
    )


@app.get("/sessions")
async def sessions_list():
    """List all active per-client sessions (id prefix, tab, age)."""
    now = time.monotonic()
    items = [
        {
            "session_id": sess.session_id,
            "tab_id": sess.tab_id,
            "age_s": round(now - sess.created, 1),
            "idle_s": round(now - sess.last_seen, 1),
        }
        for sess in session_registry._sessions.values()
    ]
    return api_success("sessions_list", {
        "count": len(items),
        "max_sessions": session_registry.max_sessions,
        "sessions": items,
    })


@app.get("/mcp-status")
async def mcp_status():
    """Report MCP-server readiness and per-session tool visibility.

    Fix-6 (2026-08-12): agents (Hermes / other MCP clients) need a cheap,
    SDK-free endpoint to learn whether the MCP surface is wired up and which
    tools are exposed for each live session.  Returns:

    ``{"status": "ok", "mcp_enabled": bool, "sessions": [{"id", "tab_id",
    "mcp_connected": bool, "tools": [...]}]}``
    """
    mcp_enabled = False
    tool_names: list[str] = []
    try:
        from mcp_server.config import load_mcp_settings

        mcp_enabled = load_mcp_settings().enabled
    except Exception:  # noqa: BLE001 — best-effort readyState poll  # noqa: BLE001 — diagnostic endpoint must never 500
        mcp_enabled = False
    try:
        from mcp_server.registry import build_tool_defs

        tool_names = [t.name for t in build_tool_defs()]
    except Exception:  # noqa: BLE001 — best-effort readyState poll  # noqa: BLE001 — registry may be unavailable in tests
        tool_names = []
    sessions = [
        {
            "id": sess.session_id,
            "tab_id": sess.tab_id,
            "mcp_connected": bool(getattr(sess.client, "is_connected", False)),
            "tools": tool_names,
        }
        for sess in session_registry._sessions.values()
    ]
    return api_success("mcp_status", {
        "mcp_enabled": mcp_enabled,
        "tool_count": len(tool_names),
        "sessions": sessions,
    })


@app.post("/session/close")
async def session_close(session_id: str = Query(..., description="Session id to close")):
    """Close a specific session (its tab + WebSocket)."""
    ok = await session_registry.destroy(session_id)
    if not ok:
        return api_error("session_close", "session_not_found", f"Session {session_id} not found", 404)
    return api_success("session_close", {"session_id": session_id, "closed": True})


# ── Auth-session clone / cookie porting (v1.27.0, F1) ──────────────

def _resolve_session_or_404(session_id: str):
    """Return the session or raise a 404-style error response."""
    sess = session_registry.get(session_id)
    if sess is None:
        return None, api_error("auth_clone", "session_not_found",
                               f"Session {session_id} not found", 404)
    return sess, None


@app.get("/session/{session_id}/export-cookies")
async def session_export_cookies(session_id: str):
    """Export all cookies from a session (auth-clone source).

    Returns the cookies as CDP ``Network.Cookie`` objects (name, value,
    domain, path, expires, httpOnly, secure, sameSite).  The payload is
    intended for immediate re-import into another session via
    ``/session/{sid}/import-cookies``.
    """
    sess, err = _resolve_session_or_404(session_id)
    if err:
        return err
    try:
        res = await sess.client.get_cookies()
    except Exception as exc:
        logger.warning("cookie export failed: %s", exc, exc_info=True)
        return api_error("auth_clone", "cookie_export_failed", str(exc), 502)
    return api_success("auth_clone", {
        "session_id": session_id,
        "count": res.get("count", 0),
        "cookies": res.get("cookies", []),
    })


@app.post("/session/{session_id}/import-cookies")
async def session_import_cookies(session_id: str, payload: dict):
    """Import cookies into a session (auth-clone target).

    Body: ``{"cookies": [...]}`` — CDP ``Network.CookieParam`` shapes.
    """
    sess, err = _resolve_session_or_404(session_id)
    if err:
        return err
    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        return api_error("auth_clone", "invalid_payload",
                         "Body must be {'cookies': [...]}", 400)
    try:
        res = await sess.client.set_cookies(cookies)
    except Exception as exc:
        logger.warning("cookie import failed: %s", exc, exc_info=True)
        return api_error("auth_clone", "cookie_import_failed", str(exc), 502)
    return api_success("auth_clone", {
        "session_id": session_id,
        "imported": res.get("imported", 0),
    })


@app.post("/session/{session_id}/clone")
async def session_clone(session_id: str):
    """Clone a session: mint a new session and copy all cookies over.

    The new session is immediately usable and carries the source session's
    authenticated state (e.g. Cloudflare cf_clearance, Google session).
    """
    src_sess, err = _resolve_session_or_404(session_id)
    if err:
        return err
    try:
        # 1. Export cookies from the source session.
        res = await src_sess.client.get_cookies()
        cookies = res.get("cookies", [])
        # 2. Mint a fresh session (own tab) via the registry.
        new_sess = await session_registry.create(_local_cdp_http(), url="about:blank")
        # 3. Import the cookies into the new session's tab.
        imp = await new_sess.client.set_cookies(cookies)
        imported = imp.get("imported", 0)
    except Exception as exc:
        logger.warning("session clone failed: %s", exc, exc_info=True)
        hint = ""
        if "session_not_found" in str(exc) or "not found" in str(exc).lower():
            hint = " The source session may have expired (TTL 900s). Check with GET /sessions."
        elif "tab" in str(exc).lower():
            hint = " The source tab may have been closed. The session registry auto-creates new tabs."
        return api_error(
            "auth_clone", "clone_failed",
            f"{exc!s}.{hint} Cookie export failed between source and target session.",
            502,
        )
    return api_success("auth_clone", {
        "session_id": new_sess.session_id,
        "tab_id": new_sess.tab_id,
        "source_session_id": session_id,
        "cookies_copied": imported,
    })


@app.get("/stealth/config")
async def get_stealth_config():
    """Return the current stealth configuration (enabled level, patches)."""
    from stealth_injector import LEVEL_PATCHES, StealthInjector

    level = state.get("stealth_level", "medium")
    injector = StealthInjector()
    return {
        "enabled": bool(state.get("stealth_enabled", True)),
        "level": level,
        "patches": LEVEL_PATCHES.get(level, []),
        "available": list(injector.patches.keys()),
    }


@app.post("/stealth/config")
async def post_stealth_config(body: StealthConfigRequest | None = None):
    """Enable/disable stealth or change its level.

    Body: ``{"enabled": bool, "level": "low"|"medium"|"high"}`` — ``enabled``
    is required; ``level`` is optional (keeps the current level). Patches
    apply to the next page load (they run on every new document).
    """

    if body is not None:
        state["stealth_enabled"] = body.enabled
        if body.level is not None:
            state["stealth_level"] = body.level
    if client.is_connected and state.get("stealth_enabled", True):
        try:
            client._apply_stealth_patches()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("stealth patch apply failed: %s", exc, exc_info=True)
            return {"status": "error", "error": str(exc)}
    return await get_stealth_config()


@app.post("/stealth/test")
async def post_stealth_test():
    """Evaluate the stealth patches in the current page.

    Returns ``{patch_name: bool}`` — whether each automation signal is
    masked (e.g. ``navigator.webdriver`` is no longer ``true``).
    """
    from stealth_injector import LEVEL_PATCHES, StealthInjector

    if client.is_connected:
        injector = StealthInjector()
        return await injector.verify(client)
    # Not connected: report the patch set as unverified (False).
    return {
        name: False for name in LEVEL_PATCHES.get(state.get("stealth_level", "medium"), [])
    }


@app.post("/connect/remote")
async def connect_remote(body: ConnectRemoteRequest):
    """Connect to a remote/cloud CDP WebSocket endpoint.

    Creates a fresh CDPClient connected directly to the given
    ``ws://``/``wss://`` endpoint (no local tab discovery) and enables the
    Page + Runtime domains. Mirrors the ``/connect`` envelope.
    """
    start = time.monotonic()
    try:
        remote_client = await CDPClient.connect_remote(body.ws_endpoint)
        # Register it as the active client so subsequent operations target it
        global client
        old = client
        client = remote_client
        if old is not None and old is not remote_client:
            try:
                await old.disconnect()
            except Exception as exc:
                logger.debug("cleanup: disconnect old client failed: %s", exc, exc_info=True)
        elapsed = (time.monotonic() - start) * 1000
        log_operation("connect_remote", "success", elapsed, body.ws_endpoint[:120])
        await broadcast_state()
        return {
            "status": "ok",
            "operation": "connect_remote",
            "result": {
                "status": "ok",
                "cdp_url": body.ws_endpoint,
                "target_id": remote_client._target_id or "",
            },
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning("connect_remote failed: %s", exc, exc_info=True)
        log_operation("connect_remote", "error", elapsed, str(exc)[:200])
        return api_error("connect_remote", "CONNECT_FAILED", str(exc), 400)


# ─── Rate limiting config (P0-3) ──────────────────────────────────────


@app.get("/rate/config")
async def get_rate_config() -> dict:
    """Return the current rate limiter configuration."""
    return client.get_rate_config()


@app.post("/rate/config")
async def post_rate_config(body: RateConfigRequest) -> dict:
    """Update the rate limiter configuration (partial updates merge)."""
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    # Validate the merged config (min<=max, valid distribution) via pydantic.
    try:
        RateLimitConfig(**{**client.get_rate_config(), **payload})
    except Exception as exc:  # pydantic ValidationError, ValueError, AssertionError
        logger.warning("invalid rate config: %s", exc, exc_info=True)
        raise HTTPException(status_code=422, detail=str(exc))
    return client.set_rate_config(payload)


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
            logger.warning("Chrome launch with proxy failed: %s", exc, exc_info=True)
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
async def navigate(url: str | None = Query(default=None, description="Target URL to navigate to"),
                   wait: bool | None = Query(default=None, description="Wait for ready after navigate (default true; ?wait=false skips the 3s wait)"),
                   timeout: int | None = Query(default=None, description="Max seconds to wait for ready (default 3, ignored if wait=false)"),
                   wait_until: str | None = Query(default=None, description="domContentLoaded|load|networkIdle — default domContentLoaded (~400ms)"),
                   body: NavigateRequest | None = None):
    """Navigate the current tab to *url*.

    The URL is accepted either as the ``?url=`` query parameter (legacy) OR
    in the JSON body ``{\"url\": \"...\"}``.  If neither is provided → 422 with
    a clear message (this used to be a bare 422 that confused callers into
    thinking the service was broken — see the 2026-08-11 agent incident).

    Query/body ``wait``/``timeout``/``waitUntil`` control the post-navigate wait:
    ``?wait=false`` returns immediately after ``Page.navigate``; ``?waitUntil=domContentLoaded``
    waits only for DCL (~400ms, default), ``networkIdle`` waits for quiet 400ms.
    Body fields take precedence over query params when both are sent.

    Fix-3 (1-tab-per-session): cross-origin navigation can make Chrome create
    a fresh target.  When that happens the session ROAMS onto the new tab AND
    closes the old one, so a session never ends up owning two tabs.
    """
    if url is None and body is not None:
        url = getattr(body, "url", None)
    # P0-3: normalize storageState → origins and inject BEFORE navigate via addScriptToEvaluateOnNewDocument
    origins_payload = None
    storage_state_payload = None
    if body is not None:
        origins_payload = getattr(body, "origins", None)
        storage_state_payload = getattr(body, "storage_state", None)
    # storageState alias → origins merge (Playwright shape: {"origins": [...] } or origins list directly)
    if storage_state_payload is not None:
        if isinstance(storage_state_payload, dict) and "origins" in storage_state_payload:
            _ss_origins = storage_state_payload["origins"]
            if isinstance(_ss_origins, list):
                origins_payload = (origins_payload or []) + _ss_origins
        elif isinstance(storage_state_payload, list):
            origins_payload = (origins_payload or []) + storage_state_payload
    # Merge wait/timeout/waitUntil: body > query > default
    eff_wait = body.wait if body is not None and body.wait is not None else wait
    if eff_wait is None:
        eff_wait = True
    eff_timeout = body.timeout if body is not None and body.timeout is not None else timeout
    if eff_timeout is None:
        eff_timeout = 3
    eff_timeout = max(1, min(int(eff_timeout), 30))
    eff_wait_until = (body.wait_until if body is not None and body.wait_until is not None else wait_until) or "domContentLoaded"
    if eff_wait_until not in ("domContentLoaded", "load", "networkIdle"):
        raise HTTPException(status_code=422, detail="waitUntil must be domContentLoaded|load|networkIdle")
    if url is None:
        raise HTTPException(
            status_code=422,
            detail="Missing 'url' — pass it as ?url=... query param OR JSON body {\"url\": \"...\"}",
        )
    # P0-3: inject localStorage via addScriptToEvaluateOnNewDocument BEFORE navigate
    if origins_payload:
        _pre = _get_current_session()
        _pre_client = _pre.client if _pre is not None else client
        # Build one script that sets each origin's localStorage before the document's scripts run
        _script_parts: list[str] = []
        for _origin in origins_payload if isinstance(origins_payload, list) else []:
            if not isinstance(_origin, dict):
                continue
            _ls = _origin.get("localStorage") or _origin.get("local_storage") or []
            if not isinstance(_ls, list) or not _ls:
                continue
            for _kv in _ls:
                _k = _kv.get("name") if isinstance(_kv, dict) else None
                _v = _kv.get("value") if isinstance(_kv, dict) else None
                if _k is None or _v is None:
                    continue
                _script_parts.append(f"try{{localStorage.setItem({json.dumps(str(_k))},{json.dumps(str(_v))});}}catch(e){{}}")
        if _script_parts:
            _js_src = "".join(_script_parts)
            try:
                await _pre_client.add_script_to_evaluate_on_new_document(_js_src)
            except Exception as exc:
                logger.debug("storageState addScript failed: %s", exc, exc_info=True)
    # Invalidate tab cache — navigation changes the page URL
    client._tabs_cache = []
    client._tabs_cache_ts = 0

    sess = _get_current_session()
    old_tab = None
    if sess is not None and sess.client._ws_tab_id:
        old_tab = sess.client._ws_tab_id

    result = await run_op("navigate", client.navigate, url)

    # Fix-1/3: tab-drift + 1-tab-per-session.
    # After navigation, if the session's WS moved to a NEW tab (cross-origin
    # target), close the old tab so the session owns exactly one.
    if sess is not None:
        new_tab = getattr(sess.client, "_ws_tab_id", None) or getattr(sess.client, "_active_tab_id", None)
        if new_tab:
            sess.tab_id = new_tab
        if old_tab and new_tab and old_tab != new_tab:
            logger.info(
                "Session %s cross-origin roam: %s -> %s (closing old tab)",
                sess.session_id[:8], old_tab[:8], new_tab[:8],
            )
            try:
                await sess.client.close_tab(old_tab)
            except Exception as exc:
                logger.debug("cleanup: close old tab failed: %s", exc, exc_info=True)
        # Refresh the client's tab cache so next discover_tabs picks up the new target
        sess.client._tabs_cache = []
        sess.client._tabs_cache_ts = 0
    # Post-navigate ready wait (default domContentLoaded ~400ms, was networkIdle 8s).
    # The 30s timeout came from 8s wait + 4s domain throttle; localhost is throttled at 0.
    if not eff_wait:
        return result
    try:
        wait_client = sess.client if sess is not None else client
        if eff_wait_until == "networkIdle":
            ready = await wait_client.wait_for_ready(timeout=eff_timeout, quiet_ms=400)
        elif eff_wait_until == "load":
            # Polynomial: poll document.readyState until "complete" (DCL + resources), cap at eff_timeout
            deadline = time.monotonic() + eff_timeout
            while time.monotonic() < deadline:
                try:
                    r = await wait_client.evaluate("document.readyState")
                    if (r.get("result") if isinstance(r, dict) else r) == "complete":
                        break
                except Exception:  # noqa: BLE001 — best-effort readyState poll
                    break
                await asyncio.sleep(0.1)
            ready = {"ready": True}
        else:  # domContentLoaded
            deadline = time.monotonic() + min(eff_timeout, 3)
            while time.monotonic() < deadline:
                try:
                    r = await wait_client.evaluate("document.readyState")
                    rs = r.get("result") if isinstance(r, dict) else r
                    if rs in ("interactive", "complete"):
                        break
                except Exception:  # noqa: BLE001 — best-effort readyState poll
                    break
                await asyncio.sleep(0.08)
            ready = {"ready": True}
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                data["ready"] = ready.get("ready", True)
                data["waitUntil"] = eff_wait_until
    except Exception as exc:
        logger.debug("Auto-wait after navigate skipped: %s", exc, exc_info=True)
    return result


@app.post("/eval")
async def eval_js(body: EvalRequest):
    """Execute JavaScript in the current page."""
    return await run_op("eval", client.evaluate_js, body.js)


@app.post("/click")
async def click_element(body: ClickRequest):
    """Click the element matching *selector* (CSS selector).

    Returns 404 with a clear message when the selector matches nothing on the
    current tab — previously the underlying CDP call returned ``200 OK`` with
    an ``{error: "Element not found"}`` payload, which callers misread as a
    successful click on a wrong/blank tab (2026-08-11 agent incident).
    """
    result = await run_op("click", client.click, body.selector)
    # The CDP click returns {status: "error"} INSIDE the run_op "data" — the
    # run_op envelope itself is always "ok" for a completed (non-throwing) CDP
    # call.  Unwrap the inner status to detect "Element not found" and turn it
    # into a real 404 instead of a misleading 200 OK.
    inner = result.get("data") if isinstance(result, dict) else None
    if isinstance(inner, dict) and inner.get("status") == "error":
        err = str(inner.get("error", ""))
        if "not found" in err.lower() or "no element" in err.lower():
            raise HTTPException(
                status_code=404,
                detail=f"Element not found for selector {body.selector!r} on the current tab",
            )
    return result


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
    """Type *text* into the element matching *selector*.

    Returns 404 with a clear message when the selector matches nothing on the
    current tab — same unwrap as ``POST /click`` (the CDP ``type_text`` returns
    ``{status: "error"}`` INSIDE the run_op \"data\", which used to surface as a
    misleading 200 OK).
    """
    result = await run_op("type", client.type_text, body.selector, body.text)
    inner = result.get("data") if isinstance(result, dict) else None
    if isinstance(inner, dict) and inner.get("status") == "error":
        err = str(inner.get("error", ""))
        if "not found" in err.lower() or "no element" in err.lower():
            raise HTTPException(
                status_code=404,
                detail=f"Element not found for selector {body.selector!r} on the current tab",
            )
    return result


# ─── New: Smart interaction endpoints ────────────────────────────


@app.post("/form/fill")
async def form_fill(body: FormFillRequest):
    """Fill form fields by label text — no CSS selectors needed.

    Each field in *fields* has ``label`` (search text) and ``value``.
    The engine finds inputs by <label>, placeholder, name, or aria-label.
    """
    return await run_op("form_fill", client.smart_form_fill,
                        body.fields, body.timeout)


@app.post("/form/extract")
async def form_extract():
    """Extract the page's form structure (fields, types, labels, required).

    Lets an agent introspect a SPA form before filling it — the returned
    labels/names feed directly into /form/fill.
    """
    return await run_op("form_extract", client.form_extract)


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
    # Resolve the caller's session client so the before/after confirmation
    # runs on the SAME tab as the click (not the global default client).
    target, _sess = await _resolve_session_client()
    # Capture before-state for confirmation
    if confirm:
        try:
            before = await target.analyze_page()
            target._before_visual_state = before.get("page", {}).get("visual_state", {})
        except Exception as exc:
            logger.debug("before-state capture failed: %s", exc, exc_info=True)
            target._before_visual_state = {}
    result = await run_op("click_text", client.click_by_text,
                          body.text, body.timeout, body.container_selector, body.nth)
    # run_op returns api_error(...) → JSONResponse when the CDP call fails;
    # only run the confirmation on a successful dict result.
    if not isinstance(result, dict):
        return result
    sess = _get_current_session()
    rtarget = sess.client if sess is not None else target
    if confirm and result.get("status") == "ok":
        try:
            if confirm == "screenshot":
                conf = await rtarget._confirm_with_screenshot()
            elif confirm == "analyze":
                conf = await rtarget._confirm_with_analyze()
            else:
                conf = None
            if conf:
                result["confirmation"] = conf
        except Exception as exc:
            logger.debug("post-click confirmation skipped: %s", exc, exc_info=True)
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
    target, _sess = await _resolve_session_client()
    if confirm:
        try:
            before = await target.analyze_page()
            target._before_visual_state = before.get("page", {}).get("visual_state", {})
        except Exception as exc:
            logger.debug("before-state capture failed: %s", exc, exc_info=True)
            target._before_visual_state = {}
    result = await run_op("click_label", client.click_label,
                          body.text, body.timeout)
    if not isinstance(result, dict):
        return result
    sess = _get_current_session()
    rtarget = sess.client if sess is not None else target
    if confirm and result.get("status") == "ok":
        try:
            if confirm == "screenshot":
                conf = await rtarget._confirm_with_screenshot()
            elif confirm == "analyze":
                conf = await rtarget._confirm_with_analyze()
            else:
                conf = None
            if conf:
                result["confirmation"] = conf
        except Exception as exc:
            logger.debug("post-click confirmation skipped: %s", exc, exc_info=True)
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
    target, _sess = await _resolve_session_client()
    if confirm:
        try:
            before = await target.analyze_page()
            target._before_visual_state = before.get("page", {}).get("visual_state", {})
        except Exception as exc:
            logger.debug("before-state capture failed: %s", exc, exc_info=True)
            target._before_visual_state = {}
    if isinstance(body, CheckboxBatchRequest):
        result = await run_op("checkbox_select_batch",
                              client.checkbox_set_state_batch,
                              body.texts, True, body.timeout)
    else:
        result = await run_op("checkbox_select",
                              client.checkbox_set_state,
                              body.text, True, body.timeout)
    if not isinstance(result, dict):
        return result
    sess = _get_current_session()
    rtarget = sess.client if sess is not None else target
    if confirm and result.get("status") == "ok":
        try:
            if confirm == "screenshot":
                conf = await rtarget._confirm_with_screenshot()
            elif confirm == "analyze":
                conf = await rtarget._confirm_with_analyze()
            else:
                conf = None
            if conf:
                result["confirmation"] = conf
        except Exception as exc:
            logger.debug("post-click confirmation skipped: %s", exc, exc_info=True)
    return result


@app.post("/checkbox/deselect")
async def checkbox_deselect(body: CheckboxRequest | CheckboxBatchRequest, confirm: str | None = Query(None, description="Post-operation confirmation: 'screenshot' for base64 JPEG, 'analyze' for state comparison")):
    """Uncheck/deselect a checkbox or radio by label text.

    Single mode: ``{"text": "SMS notifications", "timeout": 5}``
    Batch mode:  ``{"texts": ["Email", "SMS"], "timeout": 5}``

    Optional ``?confirm=screenshot`` or ``?confirm=analyze`` appends
    post-operation screenshot / state comparison to the response.
    """
    target, _sess = await _resolve_session_client()
    if confirm:
        try:
            before = await target.analyze_page()
            target._before_visual_state = before.get("page", {}).get("visual_state", {})
        except Exception as exc:
            logger.debug("before-state capture failed: %s", exc, exc_info=True)
            target._before_visual_state = {}
    if isinstance(body, CheckboxBatchRequest):
        result = await run_op("checkbox_deselect_batch",
                              client.checkbox_set_state_batch,
                              body.texts, False, body.timeout)
    else:
        result = await run_op("checkbox_deselect",
                              client.checkbox_set_state,
                              body.text, False, body.timeout)
    if not isinstance(result, dict):
        return result
    sess = _get_current_session()
    rtarget = sess.client if sess is not None else target
    if confirm and result.get("status") == "ok":
        try:
            if confirm == "screenshot":
                conf = await rtarget._confirm_with_screenshot()
            elif confirm == "analyze":
                conf = await rtarget._confirm_with_analyze()
            else:
                conf = None
            if conf:
                result["confirmation"] = conf
        except Exception as exc:
            logger.debug("post-click confirmation skipped: %s", exc, exc_info=True)
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
    target, _sess = await _resolve_session_client()
    try:
        raw = await (target.analyze_page_condensed() if condensed else target.analyze_page())
        snap = snapshot_store.add(raw)
        if isinstance(raw, dict):
            page = raw.get("page", raw)
            if isinstance(page, dict):
                page["snapshot_id"] = snap.snapshot_id
                page["elements"] = snap.elements
                # Detect JSON-only pages (e.g. auth errors, API endpoints
                # returning JSON instead of HTML).  Agents navigating to
                # API URLs see this instead of a real web page — warn them.
                visible_text = page.get("visible_text", "") or ""
                stripped = visible_text.strip()
                if stripped and (
                    (stripped.startswith("{") and stripped.endswith("}"))
                    or (stripped.startswith("[") and stripped.endswith("]"))
                ):
                    import json as _json
                    try:
                        _json.loads(stripped)
                        page.setdefault("warnings", []).append(
                            "Page contains only JSON (not HTML). "
                            "This may be an API endpoint that requires "
                            "authentication headers — navigate to a "
                            "browser-accessible URL instead, or check "
                            "the page content for error messages."
                        )
                    except (ValueError, TypeError):
                        pass  # not valid JSON — just looks like it
        return api_success("page_analyze_condensed" if condensed else "page_analyze", raw)
    except Exception as exc:
        logger.warning("page analyze failed: %s", exc, exc_info=True)
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


# ── v1.27: F2 — generic wait-for / assertion engine ────────────────

class WaitForRequest(BaseModel):
    """Generic DOM wait: kind × condition."""

    kind: str = Field("selector", description="selector|text|url")
    value: str = Field(..., description="CSS selector, text substring, or URL substring")
    condition: str = Field("present", description="present|gone|visible")
    timeout: int = Field(10, description="Max seconds to wait")


class AssertRequest(BaseModel):
    """DOM assertion: kind × condition, with optional expected value."""

    kind: str = Field("selector", description="selector|text|url|network")
    value: str | None = Field(None, description="CSS selector, text substring, or URL substring (required for DOM kinds)")
    condition: str = Field("exists", description="exists|not_exists|count|contains")
    expected: int | str | None = Field(None, description="Expected count (int) or substring (str)")
    # P1-2 network assertion: kind="network" checks the collected CDP request log
    url_pattern: str | None = Field(None, description="kind=network — URL substring/regex to match")
    status_min: int = Field(400, ge=100, le=600, description="kind=network — count requests with status >= this")
    max_count: int = Field(0, ge=0, description="kind=network — assertion fails when failure count exceeds this")

    @model_validator(mode="after")
    def _require_value_for_dom_kinds(self):
        if self.kind != "network" and not self.value:
            raise ValueError("'value' is required for kind=selector|text|url (only kind=network may omit it)")
        return self


class WaitJsRequest(BaseModel):
    """Wait for an arbitrary JS expression to return truthy."""

    js: str = Field(..., description="JavaScript expression that should return truthy when the condition is met (e.g. \"document.querySelectorAll('.completed').length > 0\")")
    timeout: int = Field(30, description="Max seconds to wait (polls every 200ms)")


@app.post("/wait/js")
async def wait_js(body: WaitJsRequest):
    """Wait for an arbitrary JS expression to become truthy.

    Unlike ``/wait/for`` (which only supports selector|text|url),
    this endpoint accepts any valid JS expression.  The expression is
    re-evaluated every 200ms until it returns a truthy value or timeout.

    Examples::

        {"js": "document.querySelectorAll('.completed').length > 0", "timeout": 30}
        {"js": "window.__APP_STATE__?.loaded === true", "timeout": 15}
        {"js": "document.querySelector('#toast')?.innerText.includes('Saved')", "timeout": 10}
    """
    js = f"""
(async function() {{
  const deadline = Date.now() + {int(body.timeout) * 1000};
  const poll = 200;
  while (Date.now() < deadline) {{
    try {{
      const result = {body.js};
      if (result) return JSON.stringify({{status: "ok", condition: "js_truthy", result: result}});
    }} catch (e) {{}}
    await new Promise(r => setTimeout(r, poll));
  }}
  return JSON.stringify({{status: "error", error: "timeout after {int(body.timeout)}s waiting for JS expression"}});
}})();
"""
    target, _sess = await _resolve_session_client()
    result = await target.evaluate(js)
    raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
    import json as _json
    try:
        data = _json.loads(raw) if isinstance(raw, str) else raw
    except (_json.JSONDecodeError, TypeError):
        data = {"error": "parse failed"}
    return api_success("wait_js", data)


@app.post("/wait/for")
async def wait_for(body: WaitForRequest):
    """Wait until a DOM condition holds (deterministic, no guessy sleeps).

    kind=selector|text|url, condition=present|gone|visible.
    """
    return await run_op("wait_for", client.wait_for_condition,
                        body.kind, body.value, body.condition, body.timeout)


@app.post("/assert")
async def assert_dom(body: AssertRequest):
    """Assert a DOM condition, returning structured pass/fail.

    On a failed assertion returns HTTP 409 with the mismatch details —
    the caller's test can fail deterministically instead of guessing.

    P1-2: ``kind="network"`` asserts on the collected CDP request log —
    counts requests whose status >= *status_min* and whose URL matches
    *url_pattern* (substring). Fails with 409 when the failure count
    exceeds *max_count*.
    """
    if body.kind == "network":
        target, _sess = await _resolve_session_client()
        try:
            await target.start_network_monitoring()
        except Exception as exc:  # noqa: BLE001 — monitoring may already be active
            logger.debug("start_network_monitoring (assert network): %s", exc)
        nlog = await target.get_network_log()
        entries = nlog.get("entries", []) if isinstance(nlog, dict) else []
        failures = []
        for e in entries:
            st = e.get("status") or 0
            url = e.get("url", "")
            if isinstance(st, int) and st >= body.status_min and (not body.url_pattern or str(body.url_pattern) in url):
                failures.append({"url": url, "status": st, "method": e.get("method", "")})
        passed = len(failures) <= int(body.max_count)
        data = {
            "kind": "network",
            "url_pattern": body.url_pattern,
            "status_min": body.status_min,
            "max_count": body.max_count,
            "failure_count": len(failures),
            "failures": failures[-20:],
            "passed": passed,
        }
        if not passed:
            return api_error("assert", "assertion_failed",
                             f"Assertion failed: {len(failures)} network failures (>= {body.status_min}) exceed max_count={body.max_count}",
                             409, details=data)
        return api_success("assert", {"result": data})
    res = await run_op("assert", client.assert_elements,
                       body.kind, body.value, body.condition, body.expected)
    data = res.get("data", {}) if isinstance(res, dict) else {}
    result = data.get("result") if isinstance(data, dict) else None
    passed = result.get("passed") if isinstance(result, dict) else None
    if passed is False:
        return api_error("assert", "assertion_failed",
                         f"Assertion failed: {body.condition} {body.kind}={body.value}",
                         409, details=data)
    return res


@app.get("/element/{selector:path}")
async def element_state(selector: str):
    """Get the current state of a DOM element by CSS selector.

    Returns disabled, text, value, visible, tag, classes, and bounding rect.

    Examples::

        GET /element/#my-button
        GET /element/input[name=email]
        GET /element/.completed:first-child
    """
    js = f"""(() => {{
  const el = document.querySelector({json.dumps(selector)});
  if (!el) return JSON.stringify({{status: "error", error: "Element not found: " + {json.dumps(selector)}}});
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  return JSON.stringify({{
    status: "ok",
    selector: {json.dumps(selector)},
    tag: el.tagName.toLowerCase(),
    text: (el.textContent || "").trim().substring(0, 500),
    value: el.value || null,
    disabled: el.disabled || false,
    readonly: el.readOnly || false,
    visible: el.offsetParent !== null && style.display !== "none" && style.visibility !== "hidden",
    classes: el.className || "",
    id: el.id || null,
    type: el.type || null,
    placeholder: el.placeholder || null,
    rect: {{x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)}}
  }});
}})()"""
    target, _sess = await _resolve_session_client()
    result = await target.evaluate(js)
    raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        data = {"error": "parse failed"}
    if data.get("status") == "error":
        return api_error("element_state", "not_found", data.get("error", "Element not found"), 404)
    return api_success("element_state", data)


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


# ── v1.27: F5 — download helper ───────────────────────────────────

class DownloadRequest(BaseModel):
    """Download a file via the browser and store it as an artifact."""

    url: str = Field(..., description="URL to download (navigates the current tab)")
    timeout: int = Field(30, description="Max seconds to wait for the file")


@app.post("/page/download")
async def page_download(body: DownloadRequest):
    """Download a file via the browser and store it as an artifact.

    Sets the download behavior to a temp dir, navigates to *url*, waits for
    the file, then stores it in the artifact store.  The artifact is served
    at ``GET /artifacts/{artifact_id}``.
    """
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="bh-dl-") as dl_dir:
            res = await run_op("page_download", client.download_file,
                               body.url, dl_dir, body.timeout)
            if not isinstance(res, dict) or res.get("data", {}).get("status") != "ok":
                return api_error("page_download", "download_failed",
                                 str(res.get("data", {}).get("error", res)), 502)
            data = res["data"]
            path = data["path"]
            import mimetypes

            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            suffix = Path(path).suffix or None

            import asyncio

            def _read_download() -> bytes:
                with open(path, "rb") as f:
                    return f.read()

            binary = await asyncio.to_thread(_read_download)
            record = artifact_store.put(binary, mime, suffix=suffix,
                                        metadata={"source_url": body.url, "name": data["name"]})
            return api_success("page_download", {
                "artifact": record,
                "source_url": body.url,
                "file_name": data["name"],
                "size_bytes": data["size_bytes"],
            })
    except Exception as exc:
        logger.warning("page download failed: %s", exc, exc_info=True)
        return api_error("page_download", "download_failed", str(exc), 502)


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


@app.api_route("/page/text", methods=["GET", "POST"])
async def page_text(wait_ready: bool = Query(False, description="Wait for network idle + stable DOM before reading"),
                    timeout: int = Query(30, description="Max seconds to wait when wait_ready=true")):
    """Extract the full visible text content of the current page.

    Returns the innerText of document.body — cleaner than raw HTML,
    preserves reading order, no script/style noise.

    With ``wait_ready=true`` the call first waits until the page is ready
    (network idle + DOM stable), then returns the text — no manual sleeps.

    Useful for LLM context extraction before deciding what to do.
    """
    if wait_ready:
        return await run_op("wait_for_ready", client.wait_for_ready, timeout)
    return await run_op("get_page_text", client.get_page_text)


@app.api_route("/page/visible-text", methods=["GET", "POST"])
async def page_visible_text(limit: int = Query(10000, description="Max chars of visible text")):
    """Fast visible-text read — no idle wait, just document.body.innerText (ergonomia S6)."""
    return await run_op("get_page_text", client.get_page_text)


@app.post("/page/content")
async def page_content():
    """Extract the *main* content, filtering nav/sidebar/footer noise.

    Picks the best content container (``<main>``, ``[role=main]``,
    ``article``, or the largest text block) and returns its innerText —
    far cleaner context for LLMs than full-page text.
    """
    return await run_op("get_main_content", client.get_main_content)


@app.post("/page/headline")
async def page_headline():
    """Extract the page's main headline (h1 or first large heading)."""
    return await run_op("get_page_headline", client.get_page_headline)


@app.post("/page/links")
async def page_links(limit: int = Query(50, description="Max links to return")):
    """Extract visible links (text + href) — capped, deduped."""
    return await run_op("get_page_links", client.get_page_links, limit)


@app.post("/page/forms")
async def page_forms():
    """Extract form fields (label, name, type, placeholder) — lightweight."""
    return await run_op("get_page_forms", client.get_page_forms)


@app.post("/page/table")
async def page_table():
    """Extract the largest table as rows (for data-heavy pages)."""
    return await run_op("get_page_table", client.get_page_table)


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
                logger.warning("Auto-connect after launch failed: %s", exc, exc_info=True)
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


@app.api_route("/screenshot", methods=["GET", "POST"])
async def screenshot():
    """
    Capture a screenshot of the current page.

    Returns a base64-encoded JPEG image (quality 70).
    To display: decode the base64 string and save as .jpg, or pass
    directly to vision tools. Do NOT attempt to read the raw base64
    as text — it is binary image data.
    """
    return await run_op("screenshot", client.screenshot)


@app.api_route("/api/screenshot", methods=["GET", "POST"])
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
    target, _sess = await _resolve_session_client()

    try:
        # Take screenshot via CDP
        screenshot_result = await target.screenshot()
    except Exception as exc:
        logger.warning("screenshot failed: %s", exc, exc_info=True)
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
    target, _sess = await _resolve_session_client()

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
        screenshot_result = await target.screenshot()
    except Exception as exc:
        logger.warning("screenshot failed: %s", exc, exc_info=True)
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
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as current_tmp:
        current_tmp.write(current_bytes)
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
    except OSError as exc:
        logger.debug("cleanup: unlink temp screenshot failed: %s", exc)

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


@app.post("/session/{sid}/export-cookies")
async def handle_export_cookies(request: Request, sid: str):
    """Export every cookie for the session *sid* as JSON.

    Resolves the session from the ``X-Session-ID`` header / ``bh_session``
    cookie (path parameter) and returns its full cookie jar via CDP
    ``Network.getAllCookies``. Each cookie carries the stable keys ``name``,
    ``value``, ``domain``, ``path``, ``expires``, ``httpOnly``, ``secure``,
    ``sameSite``.

    Responses: 200 with ``{"cookies": [...]}`` on success, 404 with a JSON
    error body when the session does not exist, 503 when the session's CDP
    connection is unavailable.
    """
    if not sid:
        return api_error("export_cookies", "invalid_session_id", "sid must be a non-empty string", 400)
    try:
        from services.cookie_service import SessionNotFoundError, export_cookies

        data = await export_cookies(sid)
    except SessionNotFoundError:
        return api_error("export_cookies", "session_not_found", f"Session {sid} not found", 404)
    except Exception as exc:
        logger.exception("Cookie export failed for session %s", sid)
        return api_error("export_cookies", "operation_failed", str(exc), 503)
    return JSONResponse(content=api_success("export_cookies", data))



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


@app.get("/network/requests")
async def network_requests(
    path: str | None = Query(None, description="Filter by URL path substring (e.g. '/api/')"),
    method: str | None = Query(None, description="Filter by HTTP method (GET, POST, …)"),
    status: int | None = Query(None, description="Filter by HTTP status code"),
    since: float | None = Query(None, description="Only entries with timestamp >= this value"),
    limit: int = Query(100, description="Max entries to return"),
):
    """Get network requests with optional filtering.

    Returns request/response pairs collected by the CDP Network domain.
    Use ``/network/start`` first to begin tracking.
    """
    target, _sess = await _resolve_session_client()
    try:
        await target.start_network_monitoring()
    except Exception as exc:  # noqa: BLE001 — monitoring may already be active
        logger.debug("start_network_monitoring (network_requests): %s", exc)
    data = await target.get_network_log()
    entries = data.get("entries", [])

    # Apply filters
    if path:
        entries = [e for e in entries if path in e.get("url", "")]
    if method:
        m = method.upper()
        entries = [e for e in entries if e.get("method", "").upper() == m]
    if status:
        entries = [e for e in entries if e.get("status") == status]
    if since is not None:
        entries = [e for e in entries if e.get("timestamp", 0) >= since]

    # Most recent last
    entries = entries[-limit:]

    return api_success("network_requests", {
        "count": len(entries),
        "failures": [e for e in entries if e.get("status", 0) >= 400][-50:],
        "network_failures": [e for e in entries if e.get("status", 0) >= 400][-50:],
        "entries": entries,
    })


@app.get("/notifications")
async def get_notifications(
    since: float | None = Query(None, description="Only notifications with timestamp >= this value"),
    limit: int = Query(50, description="Max notifications to return"),
    clear: bool = Query(False, description="Clear buffer after reading"),
):
    """Get captured toast/alert/notification messages.

    Uses a MutationObserver to watch for common notification elements
    (toast, alert, snackbar, notification, dialog, message, banner).
    Call ``GET /notifications/start`` first to begin monitoring.

    Returns an array of ``{text, classes, tag, timestamp}`` objects.
    """
    target, _sess = await _resolve_session_client()
    try:
        await target.start_notification_monitoring()
    except Exception as exc:  # noqa: BLE001 — monitoring may already be active
        logger.debug("start_notification_monitoring (notifications): %s", exc)
    # Read notifications from the browser's window.__bh_notifications__
    js = "JSON.stringify(window.__bh_notifications__ || [])"
    result = await target.evaluate(js)
    raw = result.get("result", "[]") if isinstance(result, dict) else "[]"
    try:
        entries = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        entries = []
    if not isinstance(entries, list):
        entries = []
    if since is not None:
        entries = [e for e in entries if e.get("timestamp", 0) >= since]
    entries = entries[-limit:]
    if clear:
        await target.evaluate("window.__bh_notifications__ = []")
    return api_success("notifications", {
        "count": len(entries),
        "entries": entries,
    })


@app.post("/notifications/start")
async def notifications_start():
    """Start monitoring for toast/alert/notification DOM changes."""
    target, _sess = await _resolve_session_client()
    return api_success("notifications_start", await target.start_notification_monitoring())


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


# ─── 1.33 P2-2: named auth profiles (persist + reuse) ─────────────

_AUTH_PROFILE_DIR = Path.home() / ".browser-helper" / "auth-profiles"


class AuthProfileSaveRequest(BaseModel):
    """Save the current session's auth state (cookies+storage) under a name."""

    name: str = Field(..., min_length=1, max_length=64, description="Profile name, e.g. 'production' or 'google-main'")


class AuthProfileRestoreRequest(BaseModel):
    """Restore a named auth profile onto the caller's session."""

    name: str = Field(..., min_length=1, description="Profile name to restore")


def _auth_profile_path(name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in "-_.")
    if not safe:
        raise ValueError("invalid profile name")
    return _AUTH_PROFILE_DIR / f"{safe}.json"


@app.post("/session/auth-profile/{name}")
async def auth_profile_save(name: str):
    """Save the current session's full auth state (cookies+localStorage+sessionStorage) as a named profile.

    The bundle is written to ``~/.browser-helper/auth-profiles/<name>.json`` and
    survives BH restarts — one manual login, unlimited test runs.
    """
    target, _sess = await _resolve_session_client()
    try:
        saved = await target.session_save()
        if not isinstance(saved, dict) or saved.get("status") != "ok":
            raise RuntimeError(f"session_save failed: {saved!r}"[:200])
        path = _auth_profile_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": name,
            "saved_at": datetime.now(_UTC).isoformat(),
            "session": saved.get("data") or saved,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return api_success("auth_profile_save", {
            "name": name,
            "path": str(path),
            "bytes": path.stat().st_size,
        })
    except ValueError as exc:
        return api_error("auth_profile_save", "invalid_name", str(exc), 422)
    except Exception as exc:
        logger.warning("auth profile save failed: %s", exc, exc_info=True)
        return api_error("auth_profile_save", "save_failed", str(exc), 503)


@app.post("/session/auth-profile/{name}/restore")
async def auth_profile_restore(name: str):
    """Restore a named auth profile onto the caller's current session tab."""
    path = _auth_profile_path(name)
    if not path.exists():
        return api_error("auth_profile_restore", "profile_not_found",
                         f"Auth profile {name!r} not found (looked at {path})", 404)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sess_bundle = payload.get("session")
        if not isinstance(sess_bundle, dict):
            raise TypeError("corrupt profile: no session bundle")
        result = await run_op("session_restore", client.session_restore, sess_bundle)
        data = result.get("data", {}) if isinstance(result, dict) else {}
        return api_success("auth_profile_restore", {
            "name": name,
            "restored": True,
            "saved_at": payload.get("saved_at"),
            "result": data,
        })
    except Exception as exc:
        logger.warning("auth profile restore failed: %s", exc, exc_info=True)
        return api_error("auth_profile_restore", "restore_failed", str(exc), 503)


@app.get("/session/auth-profiles")
async def auth_profile_list():
    """List saved auth profiles (name, saved_at, size)."""
    items = []
    if _AUTH_PROFILE_DIR.exists():
        for p in sorted(_AUTH_PROFILE_DIR.glob("*.json")):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
                items.append({
                    "name": payload.get("name") or p.stem,
                    "saved_at": payload.get("saved_at"),
                    "bytes": p.stat().st_size,
                })
            except Exception:  # noqa: BLE001 — corrupt file listed best-effort
                items.append({"name": p.stem, "bytes": p.stat().st_size})
    return api_success("auth_profiles", {"count": len(items), "profiles": items})


# ─── 1.33 P2-3: geolocation mock (location-aware app testing) ─────


class GeoMockRequest(BaseModel):
    """Override navigator.geolocation via CDP Emulation.setGeolocationOverride."""

    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")
    accuracy: float = Field(100, gt=0, description="Accuracy in meters")


@app.post("/geo/mock")
async def geo_mock(body: GeoMockRequest):
    """Set a geolocation override for the session's tab.

    Location-aware apps (weather, maps, payment) see *lat/lng* from
    ``navigator.geolocation`` — no real GPS needed.
    """
    target, _sess = await _resolve_session_client()
    try:
        await target._send_command("Emulation.setGeolocationOverride", {
            "latitude": body.lat,
            "longitude": body.lng,
            "accuracy": body.accuracy,
        })
        return api_success("geo_mock", {
            "lat": body.lat, "lng": body.lng, "accuracy": body.accuracy, "active": True,
        })
    except Exception as exc:
        logger.warning("geo mock failed: %s", exc, exc_info=True)
        return api_error("geo_mock", "geo_mock_failed", str(exc), 503)


@app.post("/geo/mock/clear")
async def geo_mock_clear():
    """Remove the geolocation override — back to real location."""
    target, _sess = await _resolve_session_client()
    try:
        await target._send_command("Emulation.clearGeolocationOverride", {})
        return api_success("geo_mock_clear", {"active": False})
    except Exception as exc:
        logger.warning("geo mock clear failed: %s", exc, exc_info=True)
        return api_error("geo_mock_clear", "geo_mock_clear_failed", str(exc), 503)


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
    """Open a new browser tab to the specified URL (default: about:blank).

    Fix-3 (1-tab-per-session): for a session-scoped caller this does NOT open
    a second tab — it navigates the caller's existing dedicated tab instead,
    preserving the one-tab-per-session invariant.  Unsigned (cookie-less)
    callers still get a fresh tab.
    """
    sess = _get_current_session()
    if sess is not None:
        # Session already owns a tab — navigate it rather than leaking a 2nd.
        sess.client._tabs_cache = []
        sess.client._tabs_cache_ts = 0
        result = await run_op("navigate", client.navigate, body.url)
        new_tab = getattr(sess.client, "_ws_tab_id", None) or sess.tab_id
        if new_tab:
            sess.tab_id = new_tab
        return result
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
    target, _sess = await _resolve_session_client()
    try:
        if confirm == "screenshot":
            result = await target._confirm_with_screenshot()
        else:
            result = await target._confirm_with_analyze()
        return {"status": "ok", "operation": "confirm_action", "result": result}
    except Exception as exc:
        logger.warning("confirm_action failed: %s", exc, exc_info=True)
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

# P2-9: op-latency ring for p50/p95 (benchmarkE2ERunners ground truth)
_latency_ring: dict[str, list[float]] = {}


def _record_latency(op: str, duration_ms: float) -> None:
    ring = _latency_ring.setdefault(op, [])
    ring.append(round(duration_ms, 2))
    if len(ring) > 500:
        del ring[: len(ring) - 500]


def _latency_stats(op: str) -> dict[str, Any]:
    ring = sorted(_latency_ring.get(op, []))
    if not ring:
        return {"count": 0}
    def _pct(p: float) -> float:
        idx = min(len(ring) - 1, max(0, round(p * (len(ring) - 1))))
        return ring[idx]
    return {
        "count": len(ring),
        "p50_ms": _pct(0.50),
        "p95_ms": _pct(0.95),
        "min_ms": ring[0],
        "max_ms": ring[-1],
    }


@app.get("/metrics")
async def get_metrics():
    """Get page performance metrics (timing, memory, etc.)."""
    return await run_op("get_performance_metrics", client.get_performance_metrics)


@app.get("/service/metrics")
async def service_metrics(format: str | None = Query(None, description="'prometheus' returns Prometheus text exposition; default JSON")):
    """BH service-level latency metrics.

    Default JSON ``{"operations": {...}}`` with p50/p95 per operation (500-sample
    ring) — the real CDP-side numbers benchmarkE2ERunners() should compare
    against Playwright.  ``?format=prometheus`` returns Prometheus text.
    """
    ops = {op: _latency_stats(op) for op in sorted(_latency_ring)}
    lines = [
        "# HELP bh_op_duration_ms BH operation latency in milliseconds",
        "# TYPE bh_op_duration_ms summary",
    ]
    for op, stats in ops.items():
        if stats.get("count"):
            lines.append(f'bh_op_duration_ms{{op="{op}",quantile="0.5"}} {stats["p50_ms"]}')
            lines.append(f'bh_op_duration_ms{{op="{op}",quantile="0.95"}} {stats["p95_ms"]}')
            lines.append(f'bh_op_duration_ms_count{{op="{op}"}} {stats["count"]}')
    if (format or "").lower() == "prometheus":
        return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
    return JSONResponse(content={"operations": ops, "prometheus": "\n".join(lines)})


# ─── 1.33 P2-1: structured log search ─────────────────────────────


@app.get("/logs")
async def logs_search(
    trace_id: str | None = Query(None, description="Correlate one journey: X-Trace-ID value"),
    op: str | None = Query(None, description="Filter by operation name (exact, e.g. 'navigate')"),
    status: str | None = Query(None, description="Filter: success|error|incomplete"),
    since: str | None = Query(None, description="Only entries at/after this ISO timestamp"),
    limit: int = Query(100, ge=1, le=100, description="Max entries (newest last)"),
):
    """Search the operation log — journey correlation via trace_id.

    Every entry carries the request's ``X-Trace-ID`` (echoed in the
    response header of every BH call), so a full observe→act→assert
    journey is reconstructable with ``GET /logs?trace_id=<id>``.
    """
    entries = list(operation_log)
    if trace_id:
        entries = [e for e in entries if e.get("trace_id") == trace_id]
    if op:
        entries = [e for e in entries if e.get("operation") == op]
    if status:
        entries = [e for e in entries if e.get("status") == status]
    if since:
        entries = [e for e in entries if str(e.get("timestamp", "")) >= since]
    return api_success("logs_search", {
        "count": len(entries[-limit:]),
        "entries": entries[-limit:],
    })


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
    except Exception as exc:
        logger.debug("websocket hello send failed: %s", exc, exc_info=True)
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
                            logger.debug("ws batch step failed: %s", e, exc_info=True)
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
                logger.debug("ws action failed: %s", e, exc_info=True)
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


async def _capture_agent_snapshot(condensed: bool = True, target: CDPClient | None = None):
    tc = target or client
    raw = await (tc.analyze_page_condensed() if condensed else tc.analyze_page())
    return snapshot_store.add(raw)


async def _capture_accessibility_snapshot(
    *, scope: str = "page", include: list[str] | None = None,
    interactive_only: bool = False, include_hidden: bool = False,
    target: CDPClient | None = None,
) -> AccessibilitySnapshot:
    tc = target or client
    raw = await tc.get_accessibility_tree()
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
async def agent_observe(body: AgentObserveRequest, include: str | None = Query(None, description="Comma list: console,network,screenshot — query alias for include_* booleans")):
    """Observe the page as either the legacy semantic snapshot or a real AX tree."""
    _t0 = time.monotonic()
    # Query ?include= alias → merge into body booleans
    if include:
        parts = {p.strip().lower() for p in include.split(",") if p.strip()}
        if "console" in parts:
            body.include_console = True
        if "network" in parts:
            body.include_network = True
        if "screenshot" in parts:
            body.include_screenshot = True
    # Body include_evidence comma alias
    if body.include_evidence:
        parts = {p.strip().lower() for p in body.include_evidence.split(",") if p.strip()}
        if "console" in parts:
            body.include_console = True
        if "network" in parts:
            body.include_network = True
        if "screenshot" in parts:
            body.include_screenshot = True
    async def _gather_evidence(tgt) -> dict:
        ev: dict[str, Any] = {}
        if body.include_console:
            try:
                await tgt.start_console_monitoring()
            except Exception as exc:  # noqa: BLE001
                logger.debug("console monitoring in observe bundle: %s", exc)
            entries = tgt.get_console_entries()
            errors = [e for e in entries if e.get("level") in ("error", "exception")]
            ev["console"] = {"count": len(entries), "errors": len(errors), "entries": entries[-50:]}
        if body.include_network:
            try:
                await tgt.start_network_monitoring()
            except Exception as exc:  # noqa: BLE001
                logger.debug("network monitoring in observe bundle: %s", exc)
            try:
                nlog = await tgt.get_network_log()
                entries = nlog.get("entries", []) if isinstance(nlog, dict) else []
            except Exception as exc:  # noqa: BLE001
                logger.debug("network log in observe bundle: %s", exc)
                entries = []
            failures = [e for e in entries if isinstance(e.get("status"), int) and e["status"] >= 400]
            ev["network"] = {"count": len(entries), "failures": failures[-20:], "failure_count": len(failures)}
        if body.include_screenshot:
            try:
                shot = await tgt.screenshot(quality=60)
                ev["screenshot"] = {"data": shot.get("data", ""), "format": shot.get("format", "jpeg"), "size": shot.get("size", 0)}
            except Exception as exc:  # noqa: BLE001
                logger.debug("screenshot in observe bundle: %s", exc)
                ev["screenshot"] = {"error": str(exc)}
        return ev
    target, _sess = await _resolve_session_client()
    # 1a: warn when request had no session (auto-minted about:blank tab — hints cookie-less caller)
    if _sess is not None and _get_current_session() is not None:
        sess_now = _get_current_session()
        if sess_now and sess_now.session_id == _sess.session_id and _sess.tab_id:
            # Fresh auto-minted session: check if it's still about:blank (no navigate yet)
            try:
                url_now = await target._get_current_url()  # type: ignore[attr-defined]
                if url_now in ("about:blank", "", None):
                    logger.info("agent/observe on fresh about:blank tab %s (session %s) — caller should POST /session/new or reuse X-Session-ID", _sess.tab_id[:8], _sess.session_id[:8])
            except Exception as exc:  # noqa: BLE001 — best-effort URL check
                logger.debug("about:blank check failed: %s", exc)
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
                    target=target,
                )
            data = snap.as_dict(max_nodes=min(max(body.max_nodes, 1), 1000))
            # 304-style short-circuit: same fingerprint → skip node serialization
            if body.if_none_match_snapshot_id:
                ref_snap = ax_snapshots.get(body.if_none_match_snapshot_id)
                if ref_snap is not None and ref_snap.fingerprint == snap.fingerprint:
                    unchanged = {
                        "unchanged": True,
                        "snapshot_id": snap.snapshot_id,
                        "matched_snapshot_id": body.if_none_match_snapshot_id,
                        "fingerprint": snap.fingerprint,
                        "page": snap.page if hasattr(snap, "page") else {},
                    }
                    _record_agent_step("observe", {"mode": "accessibility", "scope": body.scope, "unchanged": True})
                    return api_success("agent_observe", unchanged, meta={"trust_level": "untrusted_web_content", "mode": "accessibility", "not_modified": True})
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
            # S3 schema freeze 1.32: keep both nodes and elements (alias) for compat
            if "nodes" in data and "elements" not in data:
                data["elements"] = data["nodes"]
            elif "elements" in data and "nodes" not in data:
                data["nodes"] = data["elements"]
            # page shape stability: ensure page.title / page.url always present
            if "page" in data and isinstance(data["page"], dict):
                data["page"].setdefault("title", "")
                data["page"].setdefault("url", "")
            _record_agent_step("observe", {"mode": "accessibility", "scope": body.scope})
            if body.include_console or body.include_network or body.include_screenshot:
                ev = await _gather_evidence(target)
                data.update(ev)
                # re-alias after evidence merge (evidence may overwrite)
                if "nodes" in data and "elements" not in data:
                    data["elements"] = data["nodes"]
            _record_latency("agent_observe", (time.monotonic() - _t0) * 1000)
            return api_success("agent_observe", data, meta={"trust_level": "untrusted_web_content", "mode": "accessibility"})
        if body.snapshot_id:
            snap = snapshot_store.get(body.snapshot_id)
        else:
            snap = await _capture_agent_snapshot(body.condensed, target=target)
        if body.search_text and not _snapshot_contains_text(snap, body.search_text) and (body.fallback or "").lower() in {"accessibility", "ax"}:
            ax_snap = await _capture_accessibility_snapshot(scope="dialog" if body.auto_modal else body.scope, include=body.include, interactive_only=body.interactive_only, include_hidden=body.include_hidden, target=target)
            if not _snapshot_contains_text(ax_snap, body.search_text):
                ax_snap = await _capture_accessibility_snapshot(scope="page", include=body.include, interactive_only=body.interactive_only, include_hidden=body.include_hidden, target=target)
            data = ax_snap.as_dict(max_nodes=min(max(body.max_nodes, 1), 1000))
            data["fallback_from"] = "semantic"
            data["fallback_reason"] = f"search_text_not_found:{body.search_text}"
            if body.include_console or body.include_network or body.include_screenshot:
                ev = await _gather_evidence(target)
                data.update(ev)
            _record_agent_step("observe", {"mode": "accessibility", "scope": body.scope})
            _record_latency("agent_observe", (time.monotonic() - _t0) * 1000)
            return api_success("agent_observe", data, meta={"trust_level": "untrusted_web_content", "mode": "accessibility"})
        data = paginate_snapshot(snap, body.max_chars, body.max_elements, body.cursor)
        if body.since_snapshot_id:
            old = snapshot_store.get(body.since_snapshot_id)
            data["diff"] = diff_snapshots(old, snap)
        if body.include_console or body.include_network or body.include_screenshot:
            ev = await _gather_evidence(target)
            data.update(ev)
        # S3: nodes alias for semantic (elements canonical) + page stability
        if "elements" in data and "nodes" not in data:
            data["nodes"] = data["elements"]
        elif "nodes" in data and "elements" not in data:
            data["elements"] = data["nodes"]
        if "page" in data and isinstance(data["page"], dict):
            data["page"].setdefault("title", "")
            data["page"].setdefault("url", "")
        _record_agent_step("observe", {"mode": "semantic"})
        _record_latency("agent_observe", (time.monotonic() - _t0) * 1000)
        return api_success("agent_observe", data, meta={"trust_level": "untrusted_web_content", "mode": "semantic"})
    except StaleSnapshotError as exc:
        return api_error("agent_observe", "stale_snapshot", str(exc), 409)
    except ValueError as exc:
        return api_error("agent_observe", "invalid_observation", str(exc), 422)
    except Exception as exc:
        logger.warning("agent_observe failed: %s", exc, exc_info=True)
        return api_error("agent_observe", "observation_failed", str(exc), 503)


async def _resolve_agent_target(target: AgentTarget | None) -> dict:
    if target is None:
        return {}
    # Fast-path: direct backend_node_id without snapshot (observe→act cache hit)
    if target.backend_node_id is not None and not target.snapshot_id:
        return {"backend_node_id": target.backend_node_id}
    # Fast-path: ref without snapshot_id — caller sent stale/omitted snapshot_id;
    # try to find the ref in the newest accessibility snapshot.
    if target.ref and not target.snapshot_id:
        for snap in reversed(list(ax_snapshots.values())):
            node = next((n for n in snap.nodes if n.ref == target.ref), None)
            if node:
                return node.as_dict()
        if target.backend_node_id is not None:
            return {"backend_node_id": target.backend_node_id}
        # fall through: will be caught as missing ref below
    if target.snapshot_id and target.ref:
        snap = ax_snapshots.get(target.snapshot_id)
        if not snap:
            # snapshot_id expired/GC'd — try newest snapshot cache instead of 409
            for s in reversed(list(ax_snapshots.values())):
                node = next((n for n in s.nodes if n.ref == target.ref), None)
                if node:
                    return node.as_dict()
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
    _t0 = time.monotonic()
    tc, _sess = await _resolve_session_client()
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
            recovered = await _capture_accessibility_snapshot(scope="dialog", target=tc)
            matches = [item for item in recovered.nodes if lookup.casefold() in item.name.casefold()]
            if len(matches) != 1:
                recovered = await _capture_accessibility_snapshot(scope="page", target=tc)
                matches = [item for item in recovered.nodes if lookup.casefold() in item.name.casefold()]
            if len(matches) != 1:
                raise StaleSnapshotError(f"Could not uniquely recover target {lookup!r}; found {len(matches)} candidates")
            target = matches[0].as_dict()
        before_ax = await _capture_accessibility_snapshot(target=tc) if body.expect else None
        if action == "navigate":
            if not body.url:
                raise ValueError("url is required")
            result = await tc.navigate(body.url)
        elif action == "click":
            if target.get("backend_node_id"):
                result = await tc.click_backend_node(target["backend_node_id"])
                if isinstance(result, dict) and result.get("status") == "error":
                    # S5: surface as proper 404 with candidates instead of Uncaught
                    try:
                        snap_e = await _capture_accessibility_snapshot(target=tc)
                        cands = [{"ref": n.ref, "role": n.role, "name": n.name[:80]} for n in snap_e.nodes if n.role in ("button","link","tab")][:5]
                    except Exception:  # noqa: BLE001 — candidates best-effort
                        cands = []
                    raise ElementNotFoundError(f"target not found: backend_node_id {target.get('backend_node_id')} — candidates: {cands}")
            elif target.get("selector"):
                sel = target["selector"]
                # P0-1: single-call SPA hydration — wait until visible before click
                if body.wait_until_visible:
                    waited = await tc.wait_for_element(sel, max(1, (body.wait_ms or 5000) // 1000), True)
                    inner = waited.get("result", {}) if isinstance(waited, dict) else {}
                    if isinstance(inner, dict) and inner.get("status") != "ok":
                        raise ElementNotFoundError(f"selector {sel!r} not visible after {body.wait_ms}ms — wait_until_visible=true timed out")
                try:
                    result = await tc.click(sel)
                except Exception as exc:  # noqa: BLE001 — wrap selector probe
                    raise ElementNotFoundError(f"selector click failed: {sel!r}: {exc}")
                if isinstance(result, dict) and result.get("status") == "error" and body.auto_recover:
                    # P0-2 drift gate: auto_recover → re-wait + one bounded retry before failing.
                    # Recovery marker is stored in the click result (data is built later).
                    try:
                        retried = await tc.wait_for_element(sel, max(1, min(body.timeout, 5)), True)
                        inner_r = retried.get("result", {}) if isinstance(retried, dict) else {}
                        if isinstance(inner_r, dict) and inner_r.get("status") == "ok":
                            result = await tc.click(sel)
                            if isinstance(result, dict) and result.get("status") != "error":
                                result["auto_recovered"] = {"selector": sel, "attempt": 2}
                    except Exception:  # noqa: BLE001 — recovery best-effort, never blocks the 404 path
                        logger.debug("auto_recover selector retry failed for %r", sel)
                if isinstance(result, dict) and result.get("status") == "error":
                    # S4: enrich with candidates for SPA selector debugging
                    try:
                        snap_e = await _capture_accessibility_snapshot(target=tc)
                        # also scan live DOM for selector matches count
                        try:
                            probe = await tc.evaluate(f"document.querySelectorAll({__import__('json').dumps(sel)}).length")
                            sel_count = probe.get("result") if isinstance(probe, dict) else 0
                        except Exception:  # noqa: BLE001 — probe best-effort
                            sel_count = "unknown"
                        cands = [{"ref": n.ref, "role": n.role, "name": n.name[:80]} for n in snap_e.nodes if n.role in ("button","link","tab")][:5]
                    except Exception:  # noqa: BLE001 — candidates unavailable
                        sel_count, cands = "unknown", []
                    msg = result.get("error") or result.get("message") or str(result)
                    if "not found" in msg.lower() or "no element" in msg.lower() or "uncaught" in msg.lower() or not msg.strip():
                        raise ElementNotFoundError(f"target not found: selector {sel!r} (matches: {sel_count}) — available candidates: {cands}")
                    # other error: surface details instead of Uncaught (keep message + candidates)
                    raise RuntimeError(f"click selector {sel!r} failed: {msg} — candidates: {cands}")
            else:
                text = target.get("text") or target.get("name") or target.get("label")
                if not text:
                    raise ValueError("click requires an element reference, selector or text")
                result = await tc.click_by_text(text, body.timeout)
                if isinstance(result, dict) and result.get("status") == "error":
                    try:
                        snap_e2 = await _capture_accessibility_snapshot(target=tc)
                        cands2 = [{"ref": n.ref, "role": n.role, "name": n.name[:80]} for n in snap_e2.nodes if n.role in ("button","link","tab")][:5]
                    except Exception:  # noqa: BLE001 — candidates best-effort
                        cands2 = []
                    raise ElementNotFoundError(f"target not found: text {text!r} — candidates: {cands2}")
        elif action == "fill":
            fields = body.fields
            if fields is None and target.get("backend_node_id") and body.value is not None:
                result = await tc.fill_backend_node(target["backend_node_id"], body.value)
                fields = []
            if fields is None:
                label = target.get("label") or target.get("name") or target.get("text")
                if not label or body.value is None:
                    raise ValueError("fill requires fields or target plus value")
                fields = [{"label": label, "value": body.value}]
            if fields:
                result = await tc.smart_form_fill(fields, body.timeout)
        elif action == "select":
            label = target.get("label") or target.get("name") or target.get("text")
            if not label or body.option is None:
                raise ValueError("select requires target and option")
            result = await tc.form_select("label", label, body.option)
        elif action == "wait":
            if target.get("selector"):
                result = await tc.wait_for_element(target["selector"], body.timeout, True)
            else:
                text = target.get("text") or target.get("name")
                if not text:
                    raise ValueError("wait requires selector or text")
                result = await tc.wait_for_text(text, body.timeout, True)
        elif action == "select_tab":
            text = target.get("text") or target.get("name") or target.get("label")
            if not text:
                raise ValueError("select_tab requires target.text")
            result = await tc.select_tab_by_text(text, body.timeout_ms or body.timeout * 1000)
        elif action == "wait_for_element":
            text = target.get("text") or target.get("name") or target.get("label")
            if target.get("selector"):
                started = time.monotonic()
                waited = await tc.wait_for_element(target["selector"], max(1, (body.timeout_ms or body.timeout * 1000) // 1000), True)
                inner = waited.get("result", {})
                result = {"found": inner.get("status") == "ok", "elapsed_ms": round((time.monotonic()-started)*1000), "actual_text": inner.get("text", "")}
            elif text:
                result = await tc.wait_for_text_detailed(text, body.timeout_ms or body.timeout * 1000)
            else:
                raise ValueError("wait_for_element requires selector or text")
        elif action == "evaluate":
            if not body.expression:
                raise ValueError("expression is required")
            result = await tc.evaluate(body.expression)
        elif action == "capture":
            captured = await tc.screenshot(quality=body.quality) if isinstance(tc, object) else None
            if not isinstance(captured, dict):
                raise RuntimeError(f"Screenshot response malformed: {captured!r}")
            encoded = captured.get("data") or captured.get("screenshot") or captured.get("result")
            if not encoded:
                raise RuntimeError(f"Screenshot response did not contain image data: keys={list(captured.keys())}")
            try:
                binary = base64.b64decode(encoded)
            except Exception as _e:  # noqa: BLE001 — base64 decode
                raise RuntimeError(f"Screenshot base64 decode failed: {_e}")
            art = artifact_store.put(binary, "image/jpeg", ".jpg")
            # S5 envelope: keep artifact but also expose data alias for harness compat (data vs result.base64)
            result = {"artifact": art, "data": encoded, "artifact_id": art.get("artifact_id") or art.get("id"), "format": "jpeg"}
        elif action == "workflow":
            if not body.steps:
                raise ValueError("steps are required")
            result = await tc.execute_script(body.steps)
        elif action in {"open_menu", "expand_section"}:
            name = target.get("name") or target.get("text") or body.parameters.get("name")
            if not name:
                raise ValueError(f"{action} requires a target name")
            result = await tc.click_by_text(str(name), body.timeout)
        elif action == "dismiss_overlay":
            result = await tc.evaluate("""(() => {
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
            result = await tc.evaluate(f"""(async () => {{
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
            result = await tc.evaluate("""(() => [...document.querySelectorAll('table,[role=grid]')].map((table,index)=>({
                index, name:table.getAttribute('aria-label')||table.querySelector('caption')?.innerText||'',
                rows:[...table.querySelectorAll('tr,[role=row]')].map(row=>[...row.querySelectorAll('th,td,[role=cell],[role=columnheader],[role=rowheader]')].map(cell=>(cell.innerText||'').trim()))
            })))()""")
        elif action == "switch_context":
            tab_id = body.parameters.get("tab_id") or body.parameters.get("target")
            if not tab_id:
                raise ValueError("switch_context requires parameters.tab_id")
            result = await tc.switch_tab(str(tab_id))
        else:
            return api_error("agent_act", "unknown_action", f"Unknown action: {action}", 422)
        data = {"action": action, "result": result}
        # P0-1: surface wait timing when wait_until_visible was used
        if body.wait_until_visible and target.get("selector"):
            data["wait_until_visible"] = {"selector": target["selector"], "waited_ms": round((time.monotonic() - _t0) * 1000)}
        if before_ax is not None:
            after_ax = await _capture_accessibility_snapshot(target=tc)
            verification = validate_expectations(before_ax, after_ax, body.expect)
            data["verification"] = verification
            if not verification["satisfied"] and int((body.recovery or {}).get("retry", 0)) > 0:
                if action == "click" and target.get("backend_node_id"):
                    data["retry_result"] = await tc.click_backend_node(target["backend_node_id"])
                    after_ax = await _capture_accessibility_snapshot(target=tc)
                    data["verification"] = validate_expectations(before_ax, after_ax, body.expect)
                data["replanned"] = True
            if not data["verification"]["satisfied"]:
                data["status"] = "needs_attention"
                strategies = body.strategy or []
                if "element_screenshot" in strategies and target.get("selector"):
                    captured = await tc.element_screenshot(target["selector"], body.quality)
                    encoded = captured.get("data") or captured.get("screenshot")
                    if encoded:
                        data["visual_fallback"] = {"strategy": "element_screenshot", "artifact": artifact_store.put(base64.b64decode(encoded), "image/jpeg", ".jpg")}
                elif "viewport_screenshot" in strategies:
                    captured = await tc.screenshot(quality=body.quality)
                    encoded = captured.get("data") or captured.get("screenshot")
                    if encoded:
                        data["visual_fallback"] = {"strategy": "viewport_screenshot", "artifact": artifact_store.put(base64.b64decode(encoded), "image/jpeg", ".jpg")}
        if body.verify_after:
            verification_type = body.verify_after.get("type")
            timeout_ms = int(body.verify_after.get("timeout_ms", 5000))
            if verification_type == "text_visible":
                verification = await tc.wait_for_text_detailed(str(body.verify_after.get("text", "")), timeout_ms)
            elif verification_type == "element_visible":
                selector = body.verify_after.get("selector")
                if not selector:
                    raise ValueError("element_visible verification requires selector")
                started = time.monotonic()
                waited = await tc.wait_for_element(selector, max(1, timeout_ms // 1000), True)
                inner = waited.get("result", {})
                verification = {"found": inner.get("status") == "ok", "elapsed_ms": round((time.monotonic()-started)*1000), "actual_text": inner.get("text", "")}
            else:
                raise ValueError(f"Unsupported verify_after type: {verification_type}")
            data["verified"] = bool(verification.get("found"))
            data["actual_text"] = verification.get("actual_text", "")
            data["verification_after"] = verification
        if body.observe_after and body.include_observation is not False and action not in {"evaluate", "capture"}:
            snap = await _capture_agent_snapshot(True, target=tc)
            data["observation"] = paginate_snapshot(snap, 4000, 60)
        _record_agent_step("act", body.model_dump(mode="json", exclude_none=True, by_alias=True))
        _record_latency(f"agent_act:{action}", (time.monotonic() - _t0) * 1000)
        return api_success("agent_act", data)
    except StaleSnapshotError as exc:
        return api_error("agent_act", "stale_snapshot", str(exc), 409)
    except ElementNotFoundError as exc:
        return api_error("agent_act", "element_not_found", str(exc), 404)
    except ValueError as exc:
        return api_error("agent_act", "invalid_request", str(exc), 422)
    except Exception as exc:
        import traceback as _tb
        logger.warning("agent_act failed: %s", exc, exc_info=True)
        details = {"trace": _tb.format_exc()[-1200:]} if isinstance(exc, (AttributeError, TypeError)) else None
        # S5: map common NoneType get errors to 400 with helpful message
        msg = str(exc)
        if "NoneType" in msg and "get" in msg:
            return api_error("agent_act", "invalid_target", f"Target resolution returned None — check snapshot_id/ref/selector: {msg}", 400, details)
        return api_error("agent_act", "action_failed", msg, 503, details)
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
    target, _sess = await _resolve_session_client()
    body = body or AgentFormDiscoverRequest()
    try:
        history = None
        if body.scope == "page_with_history":
            history = await target.trigger_lazy_history()
        if body.snapshot_id:
            snap = ax_snapshots.get(body.snapshot_id)
            if not snap:
                raise StaleSnapshotError(f"Accessibility snapshot {body.snapshot_id!r} is missing")
        else:
            snap = await _capture_accessibility_snapshot(scope="page", include=["forms", "headings", "dialogs"], target=target)
        return api_success("agent_forms_discover", {
            "snapshot_id": snap.snapshot_id,
            "forms": discover_forms(snap),
            "history_load": history,
        })
    except Exception as exc:
        logger.warning("agent_forms_discover failed: %s", exc, exc_info=True)
        return api_error("agent_forms_discover", "discovery_failed", str(exc), 503)


async def _fill_semantic_form(snap: AccessibilitySnapshot, form_ref: str, data: dict[str, Any], tc: CDPClient | None = None) -> dict:
    cli = tc or client
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
            result = await cli.fill_autocomplete(node.name or key, str(value))
            ok = result.get("result", {}).get("status") == "ok"
        elif node.role == "combobox":
            result = await cli.form_select("label", node.name, str(value))
            ok = result.get("status") == "ok"
        else:
            result = await cli.fill_backend_node(node.backend_node_id, str(value))
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
    target, _sess = await _resolve_session_client()
    try:
        snap = await _capture_accessibility_snapshot(include=["forms", "dialogs"], target=target)
        result = await _fill_semantic_form(snap, body.form_ref, body.data, tc=target)
        if body.validate_result:
            after = await _capture_accessibility_snapshot(include=["forms", "alerts", "dialogs"], target=target)
            result["validation"] = discover_forms(after)
        return api_success("agent_forms_fill", result)
    except ValueError as exc:
        return api_error("agent_forms_fill", "invalid_form", str(exc), 422)
    except Exception as exc:
        logger.warning("agent_forms_fill failed: %s", exc, exc_info=True)
        return api_error("agent_forms_fill", "fill_failed", str(exc), 503)


@app.post("/agent/extract")
async def agent_extract(body: AgentExtractRequest):
    """Extract schema-shaped data with source refs and field confidence."""
    target, _sess = await _resolve_session_client()
    try:
        if body.snapshot_id:
            snap = ax_snapshots.get(body.snapshot_id)
            if not snap:
                raise StaleSnapshotError(f"Accessibility snapshot {body.snapshot_id!r} is missing")
        else:
            scope = body.scope if isinstance(body.scope, str) else (body.scope or {}).get("role", "page")
            snap = await _capture_accessibility_snapshot(scope=scope, target=target)
        return api_success("agent_extract", extract_by_schema(
            snap, body.extraction_schema, include_evidence=body.include_evidence,
        ))
    except StaleSnapshotError as exc:
        return api_error("agent_extract", "stale_snapshot", str(exc), 409)
    except ValueError as exc:
        return api_error("agent_extract", "invalid_schema", str(exc), 422)
    except Exception as exc:
        logger.warning("agent_extract failed: %s", exc, exc_info=True)
        return api_error("agent_extract", "extraction_failed", str(exc), 503)


@app.post("/agent/available-actions")
async def agent_available_actions():
    """Return actions that are currently possible and their blocking reasons."""
    target, _sess = await _resolve_session_client()
    try:
        snap = await _capture_accessibility_snapshot(target=target)
        result = available_actions(snap)
        result["snapshot_id"] = snap.snapshot_id
        return api_success("agent_available_actions", result)
    except Exception as exc:
        logger.warning("agent_available_actions failed: %s", exc, exc_info=True)
        return api_error("agent_available_actions", "observation_failed", str(exc), 503)


@app.post("/agent/execute-task")
async def agent_execute_task(body: AgentExecuteTaskRequest):
    """Execute a bounded deterministic form-and-navigation micro-task.

    The engine deliberately supports only inspectable operations: semantic form
    filling and a single verified continuation click.  Unsupported or ambiguous
    goals return ``needs_attention`` with current candidate actions.
    """
    tc, _sess = await _resolve_session_client()
    max_steps = min(max(int(body.constraints.get("max_steps", 20)), 1), 50)
    stop_before = {str(item).lower() for item in body.constraints.get("stop_before", [])}
    try:
        snap = await _capture_accessibility_snapshot(target=tc)
        steps: list[dict] = []
        forms = discover_forms(snap)
        if body.inputs and forms and len(steps) < max_steps:
            fill_result = await _fill_semantic_form(snap, forms[0]["form_ref"], body.inputs, tc=tc)
            steps.append({"action": "fill_form", "result": fill_result})
            snap = await _capture_accessibility_snapshot(target=tc)
        blocked_terms = {"purchase", "buy", "pay", "submit payment", *stop_before}
        goal = body.goal.lower()
        candidates = [n for n in snap.nodes if "click" in n.actions]
        continue_words = ("continue", "next", "proceed", "save and continue")
        target = next((n for n in candidates if any(word in n.name.lower() for word in continue_words)), None)
        if target and len(steps) < max_steps and not any(term in target.name.lower() for term in blocked_terms):
            before = snap
            result = await tc.click_backend_node(target.backend_node_id) if target.backend_node_id else await tc.click_by_text(target.name)
            after = await _capture_accessibility_snapshot(target=tc)
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
        logger.warning("agent_execute_task failed: %s", exc, exc_info=True)
        return api_error("agent_execute_task", "task_failed", str(exc), 503)


# ---------------------------------------------------------------------------
# High-level agent endpoints — one-call search & E2E test flows
# ---------------------------------------------------------------------------

# P0-4: polling expect — visible|hidden|text:Scan auto-retry (replaces wait_js innerText hack)
@app.post("/agent/expect")
async def agent_expect(body: AgentExpectRequest):
    """Polling expect: retry until selector|ref satisfies condition or timeout.

    * condition: ``visible`` | ``hidden`` | ``exists`` | ``gone`` | ``text:<sub>``
      (text: checks innerText contains sub, case-sensitive).
    * selector XOR ref (ref = AX ref from the last observe).
    * Polls every ``poll`` ms until timeout — no manual wait_js loop.
    """
    if (body.selector is None) == (body.ref is None):
        return api_error("agent_expect", "invalid_params", "Exactly one of selector or ref is required", 422)
    if body.ref and body.ref not in ax_snapshots:
        return api_error("agent_expect", "stale_snapshot",
                         f"AX snapshot ref {body.ref!r} not found — call POST /agent/observe first", 409)
    cond = (body.condition or "visible").strip()
    is_text = cond.startswith("text:")
    text_needle = cond[5:] if is_text else ""
    allowed = {"visible", "hidden", "exists", "gone"}
    if not is_text and cond not in allowed:
        return api_error("agent_expect", "invalid_condition",
                         "condition must be visible|hidden|exists|gone|text:<substring>", 422)
    target, _sess = await _resolve_session_client()
    deadline = time.monotonic() + body.timeout / 1000.0
    poll_s = max(body.poll, 10) / 1000.0
    last_err: str | None = None
    while True:
        try:
            if body.ref:
                snap = ax_snapshots.get(body.ref.split("#")[0]) or await _capture_accessibility_snapshot(target=target)
                # ref is an AX ref like "e4" — check node existence/visibility via snapshot
                _node = snap.nodes_by_ref.get(body.ref) if hasattr(snap, "nodes_by_ref") else None
                if is_text:
                    # find node text
                    name = (_node.name if _node else "") or ""
                    ok = text_needle in name
                elif cond in ("visible", "exists"):
                    ok = _node is not None and getattr(_node, "visible", True)
                else:  # hidden|gone
                    ok = _node is None or not getattr(_node, "visible", False)
                if ok:
                    return api_success("agent_expect", {"condition": cond, "selector": body.selector, "ref": body.ref, "matched": True, "elapsed_ms": round((body.timeout - max(0, (deadline - time.monotonic()) * 1000)))})
                last_err = f"AX ref {body.ref!r} not yet {cond}"
            else:
                # CSS selector path — evaluate in the page
                sel = body.selector
                if is_text:
                    js = f"JSON.stringify((document.querySelector({json.dumps(sel)})?.innerText || '').includes({json.dumps(text_needle)}))"
                    r = await target.evaluate(js)
                    val = (r.get("result") if isinstance(r, dict) else "") or ""
                    # r.result is JSON string "true"/"false"
                    try:
                        ok = json.loads(val) is True if isinstance(val, str) else bool(val)
                    except Exception:
                        ok = val == "true"
                    if ok:
                        return api_success("agent_expect", {"condition": cond, "selector": sel, "matched": True, "elapsed_ms": round((body.timeout - max(0, (deadline - time.monotonic()) * 1000)))})
                    last_err = f"text:{text_needle!r} not in {sel!r}"
                elif cond in ("visible", "exists"):
                    js = f"JSON.stringify((()=>{{const e=document.querySelector({json.dumps(sel)});return e&&e.offsetParent!==null&&getComputedStyle(e).visibility!=='hidden'&&getComputedStyle(e).display!=='none';}})())"
                    r = await target.evaluate(js)
                    val = r.get("result", "false") if isinstance(r, dict) else "false"
                    try:
                        ok = json.loads(val) is True if isinstance(val, str) else bool(val)
                    except Exception:
                        ok = False
                    if ok or (cond == "exists" and await _selector_exists(target, sel)):
                        return api_success("agent_expect", {"condition": cond, "selector": sel, "matched": True, "elapsed_ms": round((body.timeout - max(0, (deadline - time.monotonic()) * 1000)))})
                    last_err = f"{sel!r} not yet {cond}"
                else:  # hidden|gone
                    js = f"JSON.stringify((()=>{{const e=document.querySelector({json.dumps(sel)});return !e||e.offsetParent===null||getComputedStyle(e).visibility==='hidden'||getComputedStyle(e).display==='none';}})())"
                    r = await target.evaluate(js)
                    val = r.get("result", "false") if isinstance(r, dict) else "false"
                    try:
                        ok = json.loads(val) is True if isinstance(val, str) else bool(val)
                    except Exception:
                        ok = False
                    if ok:
                        return api_success("agent_expect", {"condition": cond, "selector": sel, "matched": True})
                    last_err = f"{sel!r} not yet {cond}"
        except Exception as exc:
            last_err = str(exc)[:200]
        if time.monotonic() >= deadline:
            return api_error("agent_expect", "expect_timeout",
                             f"Condition {cond!r} not met within {body.timeout}ms: {last_err}", 504)
        await asyncio.sleep(poll_s)


async def _selector_exists(target, sel: str) -> bool:
    try:
        r = await target.evaluate(f"JSON.stringify(!!document.querySelector({json.dumps(sel)}))")
        return r.get("result") == "true" if isinstance(r, dict) else False
    except Exception:
        return False


# P0-5: per-test artifact bundle — trace.zip + screenshot + console + network (retain-on-failure)
@app.post("/agent/bundle")
async def agent_bundle(body: ArtifactBundleRequest):
    """Build a per-test artifact bundle (screenshot + console + network + trace).

    Returns artifact records + a trace.zip (JSON bundle of the last journey's
    /logs + screenshots) analogous to Playwright's trace.zip retain-on-failure.
    Pass retain=always to force artifacts even on passing tests.
    """
    target, _sess = await _resolve_session_client()
    want = set(body.include or ["screenshot", "console", "network", "trace"])
    out: dict[str, Any] = {}
    # screenshot
    if "screenshot" in want:
        try:
            shot = await target.screenshot()
            out["screenshot"] = shot
        except Exception as exc:
            out["screenshot_error"] = str(exc)[:200]
    # console
    if "console" in want:
        try:
            await target.start_console_monitoring()
            entries = target.get_console_entries(level="error") if hasattr(target, "get_console_entries") else []
            out["console"] = {"count": len(entries), "entries": entries[-50:]}
        except Exception as exc:
            out["console_error"] = str(exc)[:200]
    # network
    if "network" in want:
        try:
            await target.start_network_monitoring()
            log = await target.get_network_log()
            entries = log.get("entries", []) if isinstance(log, dict) else []
            out["network"] = {"count": len(entries), "entries": entries[-100:]}
        except Exception as exc:
            out["network_error"] = str(exc)[:200]
    # trace: collect recent /logs for the current trace_id + inline JSON zip-like bundle
    if "trace" in want:
        try:
            trace_id = _current_trace.get()
            logs = [e for e in operation_log if e.get("trace_id") == trace_id] if trace_id else list(operation_log)[-20:]
            trace_payload = json.dumps({"trace_id": trace_id, "logs": logs, "captured_at": datetime.now(_UTC).isoformat()}, indent=2).encode()
            rec = artifact_store.put(trace_payload, "application/zip", ".zip", metadata={"kind": "trace", "trace_id": trace_id})
            out["trace"] = rec
        except Exception as exc:
            out["trace_error"] = str(exc)[:200]
    out["retain"] = body.retain
    return api_success("agent_bundle", out)


# Engine → (search URL builder, answer selector)
_SEARCH_ENGINES = {
    "perplexity": (
        lambda q: f"https://www.perplexity.ai/search?q={q}",
        "main",
    ),
    "google": (
        lambda q: f"https://www.google.com/search?q={q}",
        "#search, #main",
    ),
    "ddg": (
        lambda q: f"https://duckduckgo.com/?q={q}",
        "[data-result], .react-results--main",
    ),
    "bing": (
        lambda q: f"https://www.bing.com/search?q={q}",
        "#b_results",
    ),
}


@app.post("/agent/search")
async def agent_search(body: AgentSearchRequest):
    """One-call web search: navigate → run query → wait for the answer.

    ``engine`` may be ``perplexity`` (default), ``google``, ``ddg`` or
    ``bing``.  Returns the answer container's text — no manual sleeps,
    no extra reads.  The session's own tab is used.
    """
    import urllib.parse

    builder, default_selector = _SEARCH_ENGINES.get(
        body.engine.lower(), _SEARCH_ENGINES["perplexity"]
    )
    url = builder(urllib.parse.quote(body.query))
    selector = body.result_selector or default_selector
    try:
        # First navigation creates/mints the session; afterwards resolve the
        # session client so direct evaluate calls hit the session's own tab.
        # Must use _resolve_session_client() FIRST so the navigate runs on the
        # caller's OWN session tab, NOT the shared default client (which is
        # what run_op does on a fresh cookie-less call — it would navigate the
        # shared tab and every parallel agent would overwrite the same tab).
        target, sess = await _resolve_session_client()
        if sess is not None:
            _set_current_session(sess)
            await run_op("search_navigate", sess.client.navigate, url)
        else:
            await run_op("search_navigate", client.navigate, url)
        sess = _get_current_session()
        target = sess.client if sess is not None else client
        # Wait for the answer container to fill: poll until it has content
        # (streaming answers keep the DOM changing, so DOM-stability alone
        # is not enough — we wait for actual text in the container).
        deadline = time.monotonic() + body.timeout
        answer = ""
        while time.monotonic() < deadline:
            try:
                result = await target.evaluate(
                    f"""(function(){{
                      var el = document.querySelector({json.dumps(selector)});
                      if (!el) {{ var m = document.querySelector('main'); el = m; }}
                      return el ? el.innerText.substring(0, {int(body.max_chars)}) : '';
                    }})()"""
                )
                answer = result.get("result", "") or ""
            except Exception as exc:
                logger.debug("answer extraction failed: %s", exc, exc_info=True)
                answer = ""
            # Perplexity first shows "Searching the web..." then the answer;
            # wait until the answer is *substantive* (has sources / real text)
            # and the "Searching" indicator is gone.
            searching = "searching" in answer.lower()
            substantive = len(answer.strip()) > 200 and not searching
            if substantive:
                break
            await asyncio.sleep(1.5)
        return api_success("agent_search", {
            "engine": body.engine,
            "query": body.query,
            "url": url,
            "answer": answer,
            "answer_length": len(answer),
            "ready": len(answer.strip()) > 0,
        })
    except Exception as exc:
        logger.exception("agent_search failed")
        return api_error("agent_search", "search_failed", str(exc), 503)


@app.post("/agent/run-flow")
async def agent_run_flow(body: AgentFlowRequest):
    """Execute an ordered E2E test flow, returning a per-step report.

    Each step: navigate / click_text / click / type / submit / wait_text /
    wait / eval / screenshot.  Optional screenshots + baseline diff per step;
    ``stop_on_error`` halts on the first failing step.
    """
    # Ensure session is minted before the first step so direct client calls
    # (screenshot, wait_for_text) below run on the caller's own tab.
    flow_client, _sess = await _resolve_session_client()
    results = []
    ok_all = True
    start = time.monotonic()
    for idx, step in enumerate(body.steps):
        step_start = time.monotonic()
        step_report: dict[str, Any] = {"step": idx, "action": step.action}
        try:
            if step.action == "navigate":
                r = await run_op("flow_navigate", client.navigate, step.url)
                step_report["result"] = r.get("status")
                if body.auto_wait and r.get("status") == "ok":
                    # Inherit the /navigate waitUntil=domContentLoaded default (~400ms
                    # readyState poll) instead of the old wait_for_ready quiet-400ms
                    # networkIdle-style scan (~6s on busy SPAs).
                    deadline = time.monotonic() + min(step.timeout or 5, 5)
                    while time.monotonic() < deadline:
                        try:
                            rs = await client.evaluate("document.readyState")
                            val = rs.get("result") if isinstance(rs, dict) else rs
                            if val in ("interactive", "complete"):
                                break
                        except Exception:  # noqa: BLE001 — best-effort ready poll
                            break
                        await asyncio.sleep(0.08)
            elif step.action == "click_text":
                r = await run_op("flow_click_text", client.click_by_text, step.text or "", step.timeout)
                step_report["result"] = r.get("status")
                if body.auto_wait and r.get("status") == "ok":
                    await run_op("flow_click_wait", client.wait_for_ready, step.timeout or 5)
            elif step.action == "click":
                # Alias: if `text` is set but no `selector`, treat as click_text (control plane sends {action:click, text:"..."})
                if step.text and not step.selector:
                    r = await run_op("flow_click_text", client.click_by_text, step.text, step.timeout)
                else:
                    r = await run_op("flow_click", client.click, step.selector or "")
                step_report["result"] = r.get("status")
                if body.auto_wait and r.get("status") == "ok":
                    await run_op("flow_click_wait", client.wait_for_ready, step.timeout or 5)
            elif step.action == "type":
                r = await run_op("flow_type", client.type_text, step.selector or "", step.value or "")
                step_report["result"] = r.get("status")
            elif step.action == "submit":
                r = await run_op("flow_submit", client.evaluate,
                                 "(function(){var f=document.querySelector('form'); if(f){f.requestSubmit(); return 'ok';} return 'no-form';})()")
                step_report["result"] = r.get("result")
            elif step.action == "wait_text":
                r = await run_op("flow_wait_text", client.wait_for_text, step.text or "", step.timeout)
                step_report["result"] = r.get("status")
            elif step.action == "wait":
                r = await run_op("flow_wait", client.wait_for_ready, step.timeout)
                step_report["result"] = "ok"
            elif step.action == "eval":
                r = await run_op("flow_eval", client.evaluate, step.js or "")
                step_report["result"] = r.get("status")
                step_report["value"] = str(r.get("result", ""))[:300]
            elif step.action == "screenshot":
                await flow_client.screenshot()
                step_report["result"] = "ok"
                step_report["screenshot"] = True
            else:
                raise ValueError(f"Unknown flow action: {step.action}")

            # Post-action expectation (success marker text).
            if step.expect:
                wr = await flow_client.wait_for_text(step.expect, timeout=step.timeout)
                step_report["expect_ok"] = wr.get("status") == "ok"

            # Per-step screenshot.
            if step.screenshot:
                await flow_client.screenshot()
                step_report["screenshot"] = True

            step_report["ok"] = True
            step_report["elapsed_ms"] = round((time.monotonic() - step_start) * 1000)
        except Exception as exc:
            logger.debug("flow step failed: %s", exc, exc_info=True)
            step_report["ok"] = False
            step_report["error"] = str(exc)
            step_report["elapsed_ms"] = round((time.monotonic() - step_start) * 1000)
            ok_all = False
        results.append(step_report)
        if not step_report["ok"] and body.stop_on_error:
            break

    total_ms = round((time.monotonic() - start) * 1000)
    return api_success("agent_run_flow", {
        "name": body.name,
        "status": "ok" if ok_all else "failed",
        "steps": results,
        "step_count": len(results),
        "failed_steps": sum(1 for s in results if not s.get("ok")),
        "total_ms": total_ms,
    })


# ---------------------------------------------------------------------------
# Visual diff & console inspection
# ---------------------------------------------------------------------------


# ── Flow templates ─────────────────────────────────────────────────
_FLOW_TEMPLATES: dict[str, dict] = {
    "login": {
        "description": "Navigate, fill a login form, submit, verify success.",
        "requires": ["url", "username", "password", "success_text"],
        "build": lambda p: {
            "name": "login",
            "auto_wait": True,
            "stop_on_error": True,
            "steps": [
                {"action": "navigate", "url": p["url"], "timeout": 20},
                {"action": "wait", "timeout": 8},
                {"action": "type", "selector": "input[type=text], input[name*=user], input[name*=email], input[type=email]", "value": p["username"]},
                {"action": "type", "selector": "input[type=password]", "value": p["password"]},
                {"action": "submit"},
                {"action": "wait_text", "text": p["success_text"], "timeout": 12},
            ],
        },
    },
    "signup": {
        "description": "Navigate, fill a signup form, submit, verify success.",
        "requires": ["url", "email", "password", "success_text"],
        "build": lambda p: {
            "name": "signup",
            "auto_wait": True,
            "stop_on_error": True,
            "steps": [
                {"action": "navigate", "url": p["url"], "timeout": 20},
                {"action": "wait", "timeout": 8},
                {"action": "type", "selector": "input[type=email], input[name*=email]", "value": p["email"]},
                {"action": "type", "selector": "input[type=password]", "value": p["password"]},
                {"action": "submit"},
                {"action": "wait_text", "text": p["success_text"], "timeout": 12},
            ],
        },
    },
    "search": {
        "description": "Navigate and run a site search, verify results appear.",
        "requires": ["url", "query", "result_text"],
        "build": lambda p: {
            "name": "search",
            "auto_wait": True,
            "stop_on_error": True,
            "steps": [
                {"action": "navigate", "url": p["url"], "timeout": 20},
                {"action": "wait", "timeout": 6},
                {"action": "type", "selector": "input[type=search], input[name*=q], input[name*=search]", "value": p["query"]},
                {"action": "submit"},
                {"action": "wait_text", "text": p["result_text"], "timeout": 12},
            ],
        },
    },
    "checkout": {
        "description": "Go through a checkout: item page → cart → checkout page loads.",
        "requires": ["url", "item_selector", "checkout_text"],
        "build": lambda p: {
            "name": "checkout",
            "auto_wait": True,
            "stop_on_error": True,
            "steps": [
                {"action": "navigate", "url": p["url"], "timeout": 20},
                {"action": "wait", "timeout": 8},
                {"action": "click", "selector": p["item_selector"], "timeout": 10},
                {"action": "click_text", "text": "Add to cart", "timeout": 8},
                {"action": "wait_text", "text": p["checkout_text"], "timeout": 12},
            ],
        },
    },
}


@app.get("/agent/flow-templates")
async def agent_flow_templates():
    """List available E2E flow templates and their required parameters."""
    return api_success("agent_flow_templates", {
        "templates": [
            {"name": name, "description": t["description"], "requires": t["requires"]}
            for name, t in _FLOW_TEMPLATES.items()
        ]
    })


@app.post("/agent/flow-templates/{name}")
async def agent_flow_template_run(name: str, body: dict[str, Any]):
    """Build and run a flow from a template.

    Example: ``POST /agent/flow-templates/login`` with
    ``{"url": "...", "username": "...", "password": "...", "success_text": "Welcome"}``.
    """
    tpl = _FLOW_TEMPLATES.get(name.lower())
    if not tpl:
        return api_error("agent_flow_template", "template_not_found",
                         f"Unknown template '{name}'. Available: {', '.join(_FLOW_TEMPLATES)}", 404)
    missing = [k for k in tpl["requires"] if k not in body]
    if missing:
        return api_error("agent_flow_template", "missing_params",
                         f"Missing parameters: {', '.join(missing)}", 422)
    flow_dict = tpl["build"](body)
    flow_req = AgentFlowRequest(**flow_dict)
    return await agent_run_flow(flow_req)


@app.post("/agent/diff")
async def agent_diff(body: AgentDiffRequest):
    """Visually compare two URLs (or the current page against url_a).

    Loads both pages (in the session's tab), screenshots each, and runs the
    pixel-diff engine.  Returns pass/fail, pixel delta, and a diff-image
    artifact id the caller can fetch.
    """
    import tempfile

    try:
        # First navigation mints the session; resolve the session client after.
        await run_op("diff_navigate_a", client.navigate, body.url_a)
        sess = _get_current_session()
        target = sess.client if sess is not None else client
        await target.wait_for_ready(body.wait_timeout)
        shot_a = await target.screenshot()
        img_a = base64.b64decode(shot_a.get("data", ""))
        # Load page B (or keep A's screenshot as baseline against current)
        if body.url_b:
            await run_op("diff_navigate_b", target.navigate, body.url_b)
            await target.wait_for_ready(body.wait_timeout)
        shot_b = await target.screenshot()
        img_b = base64.b64decode(shot_b.get("data", ""))

        with tempfile.TemporaryDirectory() as td:
            p_a = os.path.join(td, "a.jpg")
            p_b = os.path.join(td, "b.jpg")
            p_out = os.path.join(td, "diff.png")

            import asyncio

            def _write_images() -> None:
                with open(p_a, "wb") as f:
                    f.write(img_a)
                with open(p_b, "wb") as f:
                    f.write(img_b)

            await asyncio.to_thread(_write_images)
            from screenshot_diff import ScreenshotDiffEngine

            result = ScreenshotDiffEngine.diff(
                p_a, p_b, p_out, threshold=body.threshold
            )
        # Store the diff image as an artifact so the caller can view it.
        artifact_id = None
        vlm_assessment = None
        # Diff-VLM: ha a vision modell konfigurálva van, értékeltesse a
        # diff-képet ("mi változott?" szövegesen).  Ha a diff-kép nem készült
        # el, a B screenshotját elemzi (milyen az új oldal).
        try:
            from vision_check import assess_screenshot

            if result.diff_image:
                diff_bytes = base64.b64decode(result.diff_image)
                rec = artifact_store.put(
                    diff_bytes, mime_type="image/png", suffix="diff"
                )
                artifact_id = rec.get("artifact_id") or rec.get("id")
                vlm_assessment = await assess_screenshot(
                    base64.b64encode(diff_bytes).decode(),
                    "Ez két weboldal vizuális diff-képe (piros = változás). "
                    "Írd le röviden, MI változott, és milyen jellegű (szöveg, layout, szín, elem eltűnt/új). "
                    "Ha nincs érdemi változás, írd: 'Nincs érdemi vizuális változás'.",
                )
            else:
                vlm_assessment = await assess_screenshot(
                    base64.b64encode(img_b).decode(),
                    f"Ez a '{body.url_b or body.url_a}' oldal screenshotja. "
                    "Írd le röviden, mit ábrázol az oldal (fő tartalom, layout, színek).",
                )
        except Exception as exc:
            logger.debug("diff VLM assessment failed: %s", exc, exc_info=True)
            vlm_assessment = None
        return api_success("agent_diff", {
            "url_a": body.url_a,
            "url_b": body.url_b,
            "passed": result.passed,
            "pixel_delta": result.pixel_delta,
            "dimensions_match": result.dimensions_match,
            "diff_artifact_id": artifact_id,
            "vlm": vlm_assessment,
            "error": result.error,
        })
    except Exception as exc:
        logger.exception("agent_diff failed")
        return api_error("agent_diff", "diff_failed", str(exc), 503)


@app.post("/agent/visual-regression")
async def agent_visual_regression(body: VisualRegressionRequest):
    """Multi-URL visual regression: record baselines or compare.

    ``record=true`` captures a baseline screenshot for each URL (first run).
    ``record=false`` (default) compares each URL's current screenshot against
    its stored baseline and reports pass/fail + pixel delta per URL.
    """
    import tempfile

    results = []
    ok_all = True
    try:
        await run_op("vr_navigate", client.navigate, body.urls[0])  # mint session
        sess = _get_current_session()
        target = sess.client if sess is not None else client
        for url in body.urls:
            item: dict[str, Any] = {"url": url}
            try:
                await run_op("vr_nav", target.navigate, url)
                await target.wait_for_ready(body.wait_timeout)
                shot = await target.screenshot()
                img = base64.b64decode(shot.get("data", ""))

                if body.record:
                    path = baseline_mgr.save_baseline(
                        url=url, image_data=img,
                        profile=body.profile, viewport=body.viewport,
                    )
                    item["recorded"] = True
                    item["baseline_path"] = path
                else:
                    baseline_path = baseline_mgr.get_baseline(
                        url, profile=body.profile, viewport=body.viewport
                    )
                    if not baseline_path:
                        item["status"] = "no_baseline"
                        item["ok"] = False
                        ok_all = False
                    else:
                        with tempfile.TemporaryDirectory() as td:
                            cur_path = os.path.join(td, "current.jpg")
                            out_path = os.path.join(td, "diff.png")

                            import asyncio

                            def _write_img(_p=cur_path, _i=img) -> None:
                                with open(_p, "wb") as f:
                                    f.write(_i)

                            await asyncio.to_thread(_write_img)
                            from screenshot_diff import ScreenshotDiffEngine

                            diff = ScreenshotDiffEngine.diff(
                                baseline_path, cur_path, out_path,
                                threshold=body.threshold,
                            )
                        item["status"] = "pass" if diff.passed else "fail"
                        item["ok"] = diff.passed
                        item["pixel_delta"] = round(diff.pixel_delta, 6)
                        if not diff.passed:
                            ok_all = False
                item["elapsed_ms"] = 0
                results.append(item)
            except Exception as exc:
                logger.debug("visual regression item failed: %s", exc, exc_info=True)
                item["ok"] = False
                item["error"] = str(exc)
                ok_all = False
                results.append(item)
        return api_success("agent_visual_regression", {
            "mode": "record" if body.record else "compare",
            "status": "ok" if ok_all else "failed",
            "urls": results,
            "url_count": len(results),
            "failed": sum(1 for r in results if not r.get("ok")),
        })
    except Exception as exc:
        logger.exception("visual_regression failed")
        return api_error("agent_visual_regression", "vr_failed", str(exc), 503)


@app.post("/recording/start")
async def recording_start(quality: int = Query(70, description="JPEG quality 1-100")):
    """Start CDP screencast recording of the current tab (video capture).

    Frames are collected in memory; call ``/recording/stop`` to get an
    animated GIF of the flow.
    """
    try:
        result = await run_op("recording_start", client.start_recording, quality)
        return result
    except Exception as exc:
        logger.warning("recording start failed: %s", exc, exc_info=True)
        return api_error("recording_start", "recording_failed", str(exc), 503)


@app.post("/recording/stop")
async def recording_stop():
    """Stop screencast and return an animated GIF (base64) of the frames."""
    try:
        result = await run_op("recording_stop", client.stop_recording)
        return result
    except Exception as exc:
        logger.warning("recording stop failed: %s", exc, exc_info=True)
        return api_error("recording_stop", "recording_failed", str(exc), 503)


@app.get("/recording/status")
async def recording_status():
    """Return whether a screencast recording is active."""
    target, _sess = await _resolve_session_client()
    return api_success("recording_status", {
        "recording": target._recording_frames is not None,
        "frames": len(target._recording_frames) if target._recording_frames else 0,
    })


@app.post("/network/mock")
async def network_mock(body: NetworkMockRequest | None = None):
    """Install URL-pattern request mocks (mock API responses).

    Body: ``{"mocks": [{"pattern": "regex", "status": 200, "body": "...",
    "content_type": "application/json"}]}``.  Empty list → clear mocks.
    """
    try:
        mocks = body.mocks if body else []
        result = await run_op("network_mock", client.set_request_mocks, mocks)
        return result
    except Exception as exc:
        logger.warning("network mock failed: %s", exc, exc_info=True)
        return api_error("network_mock", "mock_failed", str(exc), 503)


@app.post("/network/block")
async def network_block(body: NetworkBlockRequest | None = None):
    """Block network requests whose URL matches any regex pattern.

    Body: ``{"patterns": ["regex", ...]}``.  Empty list → clear blocks.
    Matching requests fail with a network error (analytics, trackers,
    error-path testing).
    """
    try:
        patterns = body.patterns if body else []
        result = await run_op("network_block", client.set_network_block, patterns)
        return result
    except Exception as exc:
        logger.warning("network block failed: %s", exc, exc_info=True)
        return api_error("network_block", "block_failed", str(exc), 503)


@app.post("/agent/console")
async def agent_console(body: AgentConsoleRequest | None = None):
    """Return collected console / JS errors / failed network requests.

    The browser-helper always captures ``Runtime.consoleAPICalled`` (errors +
    warnings), ``Runtime.exceptionThrown``, ``Log.entryAdded`` and
    ``Network.loadingFailed`` while connected.  Use ``clear_first`` to reset
    the buffer before the next action, then read afterwards.
    """
    body = body or AgentConsoleRequest()
    # Mint/resolve the caller's session so even a console-only client gets a
    # dedicated tab + cookie (otherwise every later call from this client
    # mints a NEW session → tab spam).
    target, _sess = await _resolve_session_client()
    try:
        await target.start_console_monitoring()
    except Exception as exc:
        logger.debug("console monitoring start failed: %s", exc, exc_info=True)
    if body.clear_first:
        target.clear_console_entries()
        return api_success("agent_console", {"cleared": True, "entries": []})
    entries = target.get_console_entries(level=body.level)
    errors = [e for e in entries if e.get("level") in ("error", "exception")]
    return api_success("agent_console", {
        "count": len(entries),
        "errors": len(errors),
        "console_errors": errors[-100:],
        "failures": errors[-100:],
        "entries": entries[-100:],
    })


@app.api_route("/console/errors", methods=["GET", "POST"])
async def console_errors(
    since: float | None = Query(None, description="Only errors with timestamp >= this value (unix seconds)"),
    limit: int = Query(50, description="Max errors to return"),
):
    """Get console errors without clearing the buffer.

    Unlike ``/agent/console`` (POST), this endpoint:
    - Only returns error/exception level entries
    - Does NOT clear the buffer on read (persistent)
    - Supports ``since`` filtering for incremental reads

    Use this for ongoing error monitoring; use ``/agent/console`` with
    ``clear_first=true`` to reset after taking action.
    """
    target, _sess = await _resolve_session_client()
    try:
        await target.start_console_monitoring()
    except Exception as exc:  # noqa: BLE001 — monitoring may already be active
        logger.debug("start_console_monitoring (console_errors): %s", exc)
    entries = target.get_console_entries(level="error")
    if since is not None:
        entries = [e for e in entries if e.get("timestamp", 0) >= since]
    return api_success("console_errors", {
        "count": len(entries),
        "entries": entries[-limit:],
    })


@app.post("/agent/flow-vlm")
async def agent_flow_vlm(body: AgentFlowRequest, llm_prompt: str = Query(
    "Describe what this page shows. Is it a login page? Reply concisely.",
    description="Prompt for the vision model")):
    """Run a flow and evaluate the final screenshot with a vision model.

    Executes the same steps as ``/agent/run-flow``, then captures a
    screenshot of the final state and asks a vision LLM (via the configured
    gateway) to describe/verify it.  Returns the flow report + the model's
    assessment — the tester agent gets visual confirmation without viewing
    the image itself.
    """
    flow_result = await agent_run_flow(body)
    # agent_run_flow returns api_success dict on success; api_error
    # returns JSONResponse. Handle both shapes so this endpoint never
    # crashes with "'JSONResponse' has no attribute 'get'".
    if isinstance(flow_result, JSONResponse):
        return flow_result
    if not isinstance(flow_result, dict) or flow_result.get("status") != "ok":
        return flow_result
    try:
        sess = _get_current_session()
        target = sess.client if sess is not None else client
        shot = await target.screenshot()
        image_b64 = shot.get("data", "")
        from vision_check import assess_screenshot

        assessment = await assess_screenshot(image_b64, llm_prompt)
        flow_result["data"]["vlm"] = assessment
        return flow_result
    except Exception as exc:
        logger.warning("VLM assessment failed: %s", exc, exc_info=True)
        if isinstance(flow_result, dict) and isinstance(flow_result.get("data"), dict):
            flow_result["data"]["vlm"] = {"status": "error", "error": str(exc)}
        return flow_result


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
    result = {
        "name": p.name,
        "data_dir": p.data_dir,
        "created_at": p.created_at,
        "last_used": p.last_used,
        "extensions": list(p.extensions),
        "description": p.description,
        "tags": list(p.tags),
        "resource_limits": dict(p.resource_limits),
    }
    if hasattr(p, "fingerprint"):
        result["fingerprint"] = p.fingerprint
    if hasattr(p, "fingerprint_config"):
        result["fingerprint_config"] = p.fingerprint_config
    return result


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
# Fingerprint REST endpoints
# ---------------------------------------------------------------------------


@app.post("/profile/{name}/fingerprint", status_code=201)
async def post_fingerprint(name: str, body: FingerprintRequest | None = None) -> dict:
    """Generate or update a fingerprint for the given profile.

    Accepts optional JSON body with ``overrides`` dict.
    Returns ``{"fingerprint": {…}}`` with status 201 on success,
    or 404 if the profile does not exist, 400/422 for invalid input.
    """
    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    overrides = body.overrides if body else None
    try:
        fp = profile_mgr.generate_fingerprint(name, overrides=overrides)
        return {"fingerprint": fp}
    except (ValueError, TypeError) as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )


@app.get("/profile/{name}/fingerprint")
async def get_fingerprint(name: str) -> dict:
    """Return the current fingerprint and fingerprint_config for the profile.

    Returns ``{"fingerprint": {…}, "fingerprint_config": {…}}`` with each
    field set to ``null`` if not configured.  Returns 404 if the profile
    does not exist.
    """
    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    fp = profile_mgr.get_fingerprint(name)
    # fingerprint_config is stored on the profile itself
    fpc = getattr(profile, "fingerprint_config", None) or profile_mgr.get_fingerprint_config(name)
    return {"fingerprint": fp, "fingerprint_config": fpc}


@app.put("/profile/{name}/fingerprint")
async def put_fingerprint_config(name: str, body: dict) -> dict:
    """Set fingerprint_config for the given profile.

    Accepts a JSON body with config fields.  Returns
    ``{"fingerprint_config": {…}}`` on success, 404 if profile not found,
    or 400/422 for invalid input.
    """
    profile = profile_mgr.get_profile(name)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    # Validate: body must be a dict
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=422,
            content={"detail": "Request body must be a JSON object"},
        )
    # Validate field names — only known fingerprint config fields allowed
    known_config_fields = {
        "canvas_noise_seed", "webgl_vendor", "webgl_renderer",
        "audio_sample_rate", "geolocation", "timezone", "locale",
        "canvas_offset_x", "canvas_offset_y", "hardware_concurrency",
        "device_memory", "screen_width", "screen_height",
        "color_depth", "platform",
    }
    for key in body:
        if key not in known_config_fields:
            return JSONResponse(
                status_code=422,
                content={"detail": f"Unknown fingerprint config field: {key!r}"},
            )

    # Persist
    profile_mgr.set_fingerprint_config(name, body)
    return {"fingerprint_config": body}


@app.delete("/profile/{name}")
async def delete_profile_singular(name: str):
    """Delete a profile (singular route alias)."""
    if profile_mgr.get_profile(name) is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Profile {name!r} not found"},
        )
    profile_mgr.delete_profile(name)
    return {"status": "ok"}


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
        result = await proxy_pool.health_check_async(body.proxy_id)
        if result is None:
            return api_error("trigger_health_check", "proxy_not_found", f"Proxy {body.proxy_id!r} not found", 404)
        return api_success("trigger_health_check", {"results": [result]})
    results = await proxy_pool.health_check_all_async()
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
    from fastapi.responses import JSONResponse

    try:
        result = backend_manager.switch(req.backend)
        return result
    except ValueError:
        return JSONResponse(
            status_code=503,
            content={"detail": f"Backend '{req.backend}' is not available"},
        )


@app.get("/backend/status")
async def backend_status():
    """Return current backend status, available backends, and versions."""
    return backend_manager.get_status()


# ---------------------------------------------------------------------------
# Mouse Config (P1-2) – behavioral mouse movement
# ---------------------------------------------------------------------------


from behavioral_mouse import MouseConfig as _MouseConfig
from behavioral_scroll import BehavioralScroll as _BehavioralScroll
from behavioral_scroll import InvalidModeError

_mouse_config_instance = _MouseConfig()
_scroll_instance = _BehavioralScroll()


class MouseConfigRequest(BaseModel):
    enabled: bool = True
    speed: str = "normal"


class ScrollConfigRequest(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    step_min: int | None = None
    step_max: int | None = None


@app.post("/mouse/config")
async def post_mouse_config(req: MouseConfigRequest):
    """Update mouse movement configuration."""
    from fastapi.responses import JSONResponse

    global _mouse_config_instance
    try:
        _mouse_config_instance = _MouseConfig(enabled=req.enabled, speed=req.speed)
        return _mouse_config_instance.to_dict()
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Validation error: {exc}"},
        )


@app.get("/mouse/config")
async def get_mouse_config():
    """Return the current mouse configuration."""
    return _mouse_config_instance.to_dict()


@app.post("/scroll/config")
async def post_scroll_config(req: ScrollConfigRequest):
    """Update the behavioral scroll configuration."""
    from fastapi.responses import JSONResponse

    try:
        _scroll_instance.update_config(
            enabled=req.enabled,
            mode=req.mode,
            step_min=req.step_min,
            step_max=req.step_max,
        )
        return _scroll_instance.get_config()
    except (ValueError, InvalidModeError) as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": f"Validation error: {exc}"},
        )


@app.get("/scroll/config")
async def get_scroll_config():
    """Return the current behavioral scroll configuration."""
    return _scroll_instance.get_config()


# ── B5+B6: press_key / hover / scroll / reload / wait_network_idle ──

class PressKeyRequest(BaseModel):
    key: str = Field(..., description="Key name (Enter, Escape, ArrowDown, Tab, etc.)")
    selector: str | None = Field(None, description="Optional CSS selector to focus before pressing")


class HoverRequest(BaseModel):
    selector: str = Field(..., description="CSS selector to hover over")


class ScrollRequest(BaseModel):
    x: int = Field(0, description="Horizontal scroll delta in pixels")
    y: int = Field(0, description="Vertical scroll delta in pixels")
    selector: str | None = Field(None, description="Optional CSS selector of scrollable element")


class ReloadRequest(BaseModel):
    ignore_cache: bool = Field(False, description="Bypass cache if true")


@app.post("/press_key")
async def press_key(body: PressKeyRequest):
    """Press a key (optionally focusing an element first)."""
    return await run_op("press_key", client.press_key, body.key, body.selector)


@app.post("/hover")
async def hover(body: HoverRequest):
    """Hover over element matching selector."""
    result = await run_op("hover", client.hover, body.selector)
    inner = result.get("data") if isinstance(result, dict) else None
    if isinstance(inner, dict) and inner.get("status") == "error":
        err = str(inner.get("error", ""))
        if "not found" in err.lower():
            raise HTTPException(status_code=404, detail=f"Element not found for selector {body.selector!r}")
    return result


@app.post("/scroll")
async def scroll(body: ScrollRequest):
    """Scroll page or element by x, y pixels."""
    return await run_op("scroll", client.scroll, body.x, body.y, body.selector)


@app.post("/reload")
async def reload_page(body: ReloadRequest | None = None):
    """Reload the current page."""
    ignore_cache = body.ignore_cache if body else False
    return await run_op("reload", client.reload, ignore_cache)


class DialogRequest(BaseModel):
    action: str = Field(..., description="accept|dismiss")
    prompt_text: str | None = Field(None, description="Prompt text when accepting a prompt() dialog")


@app.post("/dialog/handle")
async def dialog_handle(body: DialogRequest):
    """Accept or dismiss a JavaScript dialog (alert/confirm/prompt)."""
    if body.action not in ("accept", "dismiss"):
        raise HTTPException(status_code=422, detail="action must be 'accept' or 'dismiss'")
    if body.action == "accept":
        return await run_op("dialog_accept", client.dialog_accept, body.prompt_text)
    return await run_op("dialog_dismiss", client.dialog_dismiss)


@app.get("/rate_limiter/status")
async def rate_limiter_status():
    """Return current domain throttle + rate limiter state for debugging."""
    from domain_throttle import DEFAULT_MIN_INTERVAL_SEC
    from domain_throttle import domain_throttle as dt

    raw_interval = settings_mgr.get("domain_min_interval_sec", DEFAULT_MIN_INTERVAL_SEC)
    try:
        interval = float(raw_interval)
    except (TypeError, ValueError):
        interval = DEFAULT_MIN_INTERVAL_SEC
    # Expose last-hit per domain (monotonic timestamps) + remaining wait
    now = __import__("time").monotonic()
    domains: dict[str, dict] = {}
    for dom, ts in list(dt._last.items()):
        elapsed = now - ts
        remaining = max(0.0, interval - elapsed)
        domains[dom] = {"last_hit_ago_s": round(elapsed, 2), "remaining_wait_s": round(remaining, 2)}
    return api_success("rate_limiter_status", {
        "interval_sec": interval,
        "default_interval_sec": DEFAULT_MIN_INTERVAL_SEC,
        "domains": domains,
    })


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    logger.info("Serving static files from %s", STATIC_DIR)
else:
    logger.warning("Static directory not found: %s", STATIC_DIR)


# ---------------------------------------------------------------------------
# Fleet orchestration router (v1.18.0) — /fleet/* endpoints
# ---------------------------------------------------------------------------
from fleet.api import router as fleet_router  # imported after app is created

# NOTE: we extend ``app.routes`` with the router's concrete APIRoute objects
# instead of ``app.include_router()``.  This FastAPI version wraps included
# routers in a lazy ``_IncludedRouter`` placeholder that has no ``.path``
# attribute, which breaks route-introspection tests (e.g.
# ``test_enterprise_workspace.py::test_enterprise_routes_are_present``) that
# iterate ``app.routes``.  The router's routes carry the ``/fleet`` prefix
# baked in, so extending the list is equivalent for matching and schema.
app.routes.extend(fleet_router.routes)


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


# ===================================================================
# v1.8.0 Anti-Detection API — /api/v1/proxy/*
# ===================================================================


def _api_error(status_code: int, message: str) -> JSONResponse:
    """Return an API error response in the ``{status, error}`` shape."""
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "error": message},
    )


@app.post("/api/v1/proxy/load-from-env")
async def api_proxy_load_from_env():
    """Load proxies from PROXY_LIST/PROXY_FILE env vars."""
    added = _proxy_rotation.load_from_env()
    return {"status": "ok", "added": added}


@app.api_route("/api/v1/proxy/health", methods=["GET", "POST"])
async def api_proxy_health(request: Request):
    """Health check — POST runs checks, GET returns a summary."""
    if request.method == "GET":
        pool = _proxy_rotation.get_pool()
        total = len(pool)
        healthy = sum(1 for p in pool if p.get("healthy", True))
        unhealthy = total - healthy
        return {"status": "ok", "total": total, "healthy": healthy, "unhealthy": unhealthy}
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except ValueError:
        pass
    proxy_id = body.get("proxy_id") if isinstance(body, dict) else None
    if proxy_id:
        result = await _proxy_rotation.health_check_async(proxy_id)
        return {"status": "ok", "results": [result] if result else []}
    return {"status": "ok", "results": await _proxy_rotation.health_check_all_async()}


@app.get("/api/v1/proxy/stats")
async def api_proxy_stats():
    """Usage stats."""
    return {"status": "ok", "stats": _proxy_rotation.get_stats()}


@app.api_route("/api/v1/proxy/{proxy_id}", methods=["GET", "DELETE"])
async def api_proxy_by_id(request: Request, proxy_id: str):
    """Get (GET) or remove (DELETE) a single proxy by ID."""
    if request.method == "DELETE":
        if not _proxy_rotation.remove_proxy(proxy_id):
            return _api_error(404, f"Proxy not found: {proxy_id}")
        return {"status": "ok"}
    for p in _proxy_rotation.get_pool():
        if p.get("id") == proxy_id:
            return {"status": "ok", "proxy": p}
    return _api_error(404, f"Proxy not found: {proxy_id}")


@app.api_route("/api/v1/proxy", methods=["GET", "POST", "DELETE"])
async def api_proxy_collection(request: Request):
    """Add (POST), list (GET) or clear (DELETE) proxies."""
    if request.method == "GET":
        return {"status": "ok", "proxies": _proxy_rotation.get_pool()}
    if request.method == "DELETE":
        _proxy_rotation.clear()
        return {"status": "ok"}
    # POST — add proxy(es)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid JSON body")
    proxies = body.get("proxies") if isinstance(body, dict) else None
    if not isinstance(proxies, list):
        raise HTTPException(status_code=422, detail="Field 'proxies' is required")
    ids: list[str] = []
    for p in proxies:
        if not isinstance(p, dict) or not p.get("url"):
            raise HTTPException(status_code=422, detail="Each proxy entry requires a 'url'")
        try:
            pid = _proxy_rotation.add_proxy(
                p["url"],
                proxy_type=p.get("type"),
                tags=p.get("tags"),
            )
        except ValueError as exc:
            return _api_error(400, f"Invalid proxy URL {p['url']!r}: {exc}")
        ids.append(pid)
    return {"status": "ok", "ids": ids}


# ===================================================================
# v1.8.0 Anti-Detection API — /api/v1/fingerprints/*
# ===================================================================


@app.api_route("/api/v1/fingerprints", methods=["GET", "POST"])
async def api_fingerprints_collection(request: Request):
    """List (GET) or add (POST) fingerprint templates."""
    if request.method == "GET":
        return {"status": "ok", "templates": _fingerprint_db.list_templates()}
    # POST — add a template
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid JSON body")
    name = body.get("name") if isinstance(body, dict) else None
    if not name:
        raise HTTPException(status_code=422, detail="Field 'name' is required")
    if _fingerprint_db.get_template(name) is not None:
        return _api_error(400, f"Template already exists: {name}")
    from anti_detection.fingerprint_database import FingerprintTemplate

    tpl = FingerprintTemplate(
        name=name,
        browser=body.get("browser", "chrome"),
        signals=body.get("signals", {}),
        config=body.get("config", {}),
        metadata=body.get("metadata", {"version": 1, "created_at": time.time(), "description": ""}),
    )
    _fingerprint_db.add_template(tpl)
    # Persist immediately so API-created templates survive restart (review H1)
    _fingerprint_db.save()
    return {"status": "ok", "name": tpl.name}


@app.api_route("/api/v1/fingerprints/{name}", methods=["GET", "PUT", "DELETE"])
async def api_fingerprints_item(request: Request, name: str):
    """Get (GET), update (PUT) or delete (DELETE) a template by name."""
    if request.method == "DELETE":
        if not _fingerprint_db.delete_template(name):
            return _api_error(404, f"Template not found: {name}")
        # Persist deletion (review H1)
        _fingerprint_db.save()
        return {"status": "ok"}
    if request.method == "PUT":
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not _fingerprint_db.update_template(name, body):
            return _api_error(404, f"Template not found: {name}")
        # Persist update (review H1)
        _fingerprint_db.save()
        return {"status": "ok"}
    tpl = _fingerprint_db.get_template(name)
    if tpl is None:
        return _api_error(404, f"Template not found: {name}")
    return {"status": "ok", "template": {
        "name": tpl.name,
        "browser": tpl.browser,
        "metadata": tpl.metadata,
        "signals": tpl.signals,
        "config": tpl.config,
    }}


@app.post("/api/v1/fingerprints/generate")
async def api_fingerprints_generate(body: dict | None = None):
    """Generate a random fingerprint template."""
    body = body or {}
    browser = body.get("browser", "chrome")
    try:
        tpl = _fingerprint_db.generate_template(browser)
    except ValueError:
        return _api_error(400, f"Unknown browser type: {browser}")
    return {
        "status": "ok",
        "template": {
            "name": tpl.name,
            "browser": tpl.browser,
            "metadata": tpl.metadata,
            "signals": tpl.signals,
            "config": tpl.config,
        },
    }


@app.post("/api/v1/fingerprints/{name}/export")
async def api_fingerprints_export(name: str, body: dict | None = None):
    """Export a fingerprint template to a JSON file."""
    body = body or {}
    export_path = body.get("path") or "/tmp/test.json"
    try:
        _fingerprint_db.export_template(name, export_path)
    except KeyError:
        return _api_error(404, f"Template not found: {name}")
    return {"status": "ok", "path": export_path}


@app.post("/api/v1/fingerprints/import")
async def api_fingerprints_import(body: dict):
    """Import a fingerprint template from a JSON file."""
    path = body.get("path") if isinstance(body, dict) else None
    if not path:
        raise HTTPException(status_code=422, detail="Field 'path' is required")
    try:
        name = _fingerprint_db.import_template(path)
    except (FileNotFoundError, OSError):
        return _api_error(404, f"Import file not found: {path}")
    # Persist the imported template (review H1)
    _fingerprint_db.save()
    return {"status": "ok", "name": name}


# ===================================================================
# v1.8.0 Anti-Detection API — /api/v1/session/*
# ===================================================================


async def _create_cdp_client(cdp_url: str) -> tuple[CDPClient | None, str | None]:
    """Create (and try to connect) a real CDPClient from a ws:// URL.

    Returns ``(client, error)``. ``client`` is a real ``CDPClient`` even
    when the connection attempt failed, so callers always pass a real
    client type into session_manager / detection_tester (review C3);
    ``error`` is set when the connection could not be established.

    Raises:
        HTTPException(422): if ``cdp_url`` is not a ws:// or wss:// URL.
    """
    if not cdp_url:
        return None, None
    if not cdp_url.startswith(("ws://", "wss://")):
        raise HTTPException(
            status_code=422,
            detail="Field 'cdp_url' must be a ws:// or wss:// WebSocket URL",
        )
    client = CDPClient()
    try:
        await asyncio.wait_for(client.connect_ws(cdp_url), timeout=5.0)
        return client, None
    except Exception as exc:  # noqa: BLE001 — surface connection failure to the caller
        logger.warning("CDP connection failed for %s: %s", cdp_url, exc)
        return client, str(exc)


@app.post("/api/v1/session/capture")
async def api_session_capture(body: dict):
    """Capture session state.

    Requires a proper CDP WebSocket URL (``ws://``) in ``cdp_url``; a real
    CDPClient is created and passed to the session manager. If the CDP
    endpoint is unreachable the response carries a ``warning`` field instead
    of silently fabricating state.
    """
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=422, detail="Field 'session_id' is required")
    cdp_url = body.get("cdp_url", "")
    client, cdp_error = await _create_cdp_client(cdp_url)
    try:
        state = await _session_mgr.capture(cdp_client=client, session_id=session_id)
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as exc:  # noqa: BLE001 — close is best-effort
                logger.debug("Error closing CDP client: %s", exc)
    response = {
        "status": "ok",
        "session": {
            "session_id": state.session_id,
            "cookies": state.cookies,
            "local_storage": state.local_storage,
            "url": state.url,
            "created_at": state.created_at,
            "last_active": state.last_active,
        },
    }
    if cdp_error:
        response["warning"] = f"CDP unavailable: {cdp_error}"
    return response


@app.post("/api/v1/session/restore")
async def api_session_restore(body: dict):
    """Restore session state.

    Requires a proper CDP WebSocket URL (``ws://``) in ``cdp_url``; a real
    CDPClient is created and passed to the session manager (review C3).
    """
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=422, detail="Field 'session_id' is required")
    state = _session_mgr.load(session_id)
    if state is None:
        return _api_error(404, f"Session not found: {session_id}")
    cdp_url = body.get("cdp_url", "")
    client, cdp_error = await _create_cdp_client(cdp_url)
    try:
        result = await _session_mgr.restore(cdp_client=client, state=state)
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as exc:  # noqa: BLE001 — close is best-effort
                logger.debug("Error closing CDP client: %s", exc)
    response = {"status": "ok", "session_id": result["session_id"]}
    if cdp_error:
        response["warning"] = f"CDP unavailable: {cdp_error}"
    return response


@app.get("/api/v1/session")
async def api_session_list():
    """List all sessions."""
    return {"status": "ok", "sessions": _session_mgr.list_sessions()}


@app.api_route("/api/v1/session/{session_id}", methods=["GET", "DELETE"])
async def api_session_item(request: Request, session_id: str):
    """Get (GET) or delete (DELETE) a session by ID."""
    state = _session_mgr.load(session_id)
    if state is None:
        return _api_error(404, f"Session not found: {session_id}")
    if request.method == "DELETE":
        fpath = Path(_session_mgr._storage_dir) / f"{session_id}.json"
        fpath.unlink(missing_ok=True)
        return {"status": "ok"}
    return {
        "status": "ok",
        "session": {
            "session_id": state.session_id,
            "cookies": state.cookies,
            "local_storage": state.local_storage,
            "session_storage": state.session_storage,
            "url": state.url,
            "created_at": state.created_at,
            "last_active": state.last_active,
        },
    }


@app.post("/api/v1/session/cleanup")
async def api_session_cleanup():
    """Trigger cleanup of expired sessions."""
    removed = await _session_mgr.cleanup()
    return {"status": "ok", "removed": removed}


# ===================================================================
# v1.8.0 Anti-Detection API — /api/v1/compose/*
# ===================================================================


@app.post("/api/v1/compose")
async def api_compose(body: dict):
    """Compose a full anti-detection profile."""
    if not body.get("name"):
        raise HTTPException(status_code=422, detail="Field 'name' is required")
    bundle = AntiDetectProfileBundle(
        name=body.get("name", "default"),
        fingerprint_template=body.get("fingerprint_template", "chrome-120"),
        fingerprint_config=body.get("fingerprint_config", {}),
        proxy_strategy=body.get("proxy_strategy", "round-robin"),
        proxy_group=body.get("proxy_group"),
        stealth_level=body.get("stealth_level", "medium"),
        session_ttl=body.get("session_ttl", 3600.0),
    )
    try:
        result = _compositor.compose(bundle)
    except KeyError as exc:
        return _api_error(400, str(exc))
    except ValueError as exc:
        # Unvalidated fingerprint signals (review H3)
        return _api_error(400, str(exc))
    # The API contract exposes the combined scripts under the "combined" key
    result["combined"] = result.get("combined_js", [])
    return {"status": "ok", "bundle": result}


@app.post("/api/v1/compose/test")
async def api_compose_test(body: dict):
    """Test a composed profile.

    Requires a proper CDP WebSocket URL (``ws://``) in ``cdp_url``; a real
    CDPClient is created and passed to the detection tester. If the CDP
    endpoint is unreachable the per-site results carry explicit errors
    instead of fabricated passes (review C1).
    """
    bundle_data = body.get("bundle")
    cdp_url = body.get("cdp_url")
    if not isinstance(bundle_data, dict):
        raise HTTPException(status_code=422, detail="Field 'bundle' is required")
    if not cdp_url:
        raise HTTPException(status_code=422, detail="Field 'cdp_url' is required")
    bundle = AntiDetectProfileBundle(
        name=bundle_data.get("name", "default"),
        fingerprint_template=bundle_data.get("fingerprint_template", "chrome-120"),
        fingerprint_config=bundle_data.get("fingerprint_config", {}),
        proxy_strategy=bundle_data.get("proxy_strategy", "round-robin"),
        stealth_level=bundle_data.get("stealth_level", "medium"),
        session_ttl=bundle_data.get("session_ttl", 3600.0),
    )
    client, cdp_error = await _create_cdp_client(cdp_url)
    try:
        results = await _compositor.test(bundle, cdp_client=client)
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as exc:  # noqa: BLE001 — close is best-effort
                logger.debug("Error closing CDP client: %s", exc)
    site_results = results.get("results", [])
    response = {
        "status": "ok",
        "results": {
            "sites": site_results,
            "summary": {
                "total": len(site_results),
                "passed": sum(1 for r in site_results if r.get("passed")),
            },
        },
    }
    if cdp_error:
        response["warning"] = f"CDP unavailable: {cdp_error}"
    return response


@app.post("/api/v1/compose/export")
async def api_compose_export(body: dict):
    """Export a bundle to JSON file."""
    if not body.get("name"):
        raise HTTPException(status_code=422, detail="Field 'name' is required")
    bundle = AntiDetectProfileBundle(
        name=body.get("name", "default"),
        fingerprint_template=body.get("fingerprint_template", "chrome-120"),
        fingerprint_config=body.get("fingerprint_config", {}),
        proxy_strategy=body.get("proxy_strategy", "round-robin"),
        stealth_level=body.get("stealth_level", "medium"),
        session_ttl=body.get("session_ttl", 3600.0),
    )
    out_path = body.get("path") or f"/tmp/{bundle.name}.json"
    _compositor.export_bundle(bundle, out_path)
    return {"status": "ok", "path": out_path}


@app.post("/api/v1/compose/import")
async def api_compose_import(body: dict):
    """Import a bundle from JSON file."""
    path = body.get("path") if isinstance(body, dict) else None
    if not path:
        raise HTTPException(status_code=422, detail="Field 'path' is required")
    try:
        bundle = _compositor.import_bundle(path)
    except (FileNotFoundError, OSError):
        return _api_error(404, f"Bundle file not found: {path}")
    return {"status": "ok", "bundle": bundle.to_dict()}


@app.post("/api/v1/compose/resolve")
async def api_compose_resolve(body: dict):
    """Resolve a fingerprint template."""
    template_name = body.get("template_name", "chrome-120")
    try:
        result = _compositor.resolve_fingerprint(
            template_name,
            overrides=body.get("overrides"),
        )
    except KeyError as exc:
        return _api_error(400, str(exc))
    except ValueError as exc:
        # Unvalidated fingerprint signals (review H3)
        return _api_error(400, str(exc))
    return {
        "status": "ok",
        "config": result.get("config", {}),
        "js_patches": result.get("js_patches", []),
    }


@app.post("/api/v1/compose/resolve-stealth")
async def api_compose_resolve_stealth(body: dict):
    """Resolve stealth patches for a given level."""
    level = body.get("level", "medium")
    try:
        result = _compositor.resolve_stealth_patches(level)
    except ValueError as exc:
        return _api_error(400, str(exc))
    return {"status": "ok", "patches": result.get("patches", {})}


# ===================================================================
# v1.8.0 — /tools/fingerprint-test
# ===================================================================


@app.post("/tools/fingerprint-test")
async def api_fingerprint_test(body: dict | None = None):
    """Run fingerprint detection tests on all known test sites.

    Accepts an optional ``cdp_url`` body field (a ws:// CDP WebSocket URL).
    When provided, a real CDPClient is created and used for navigation; when
    absent or unreachable the endpoint returns explicit per-site failures
    (503 on hard errors) instead of fabricated passes (review C1).
    """
    body = body or {}
    cdp_url = body.get("cdp_url") if isinstance(body, dict) else None
    try:
        if cdp_url:
            client, _ = await _create_cdp_client(cdp_url)
            try:
                results = await _detection_tester.run_all(
                    cdp_client=client, timeout_per_site=30
                )
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception as exc:  # noqa: BLE001 — close is best-effort
                        logger.debug("Error closing CDP client: %s", exc)
        else:
            results = await _detection_tester.run_all(
                cdp_client=None, timeout_per_site=30
            )
    except Exception as exc:  # noqa: BLE001 — any detection failure must surface as 503, not 500
        return JSONResponse(
            status_code=503,
            content={"error": f"Detection test failed: {exc}", "detail": str(exc)},
        )
    return [
        {"site": r.site, "passed": r.passed, "details": r.details, "errors": r.errors}
        for r in results
    ]
