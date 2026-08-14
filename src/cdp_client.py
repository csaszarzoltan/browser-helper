"""
CDP Client — async WebSocket connection to Chrome DevTools Protocol.

Connects to a local Chrome instance via CDP, discovers tabs through the
/json HTTP endpoint, and provides clean async methods for browser automation.

Usage:
    client = CDPClient()
    await client.connect()
    await client.navigate("https://example.com")
    result = await client.evaluate("document.title")
    await client.close()
"""

import asyncio
import json
import logging
import math
import random
import time
from typing import Any

import httpx
import websockets
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger("browser-helper.cdp")


class CDPError(Exception):
    """CDP protocol error."""


class CDPDisconnectedError(CDPError):
    """Raised when a CDP operation fails because the connection disconnected."""


# ─── Rate limiting (P0-3) ────────────────────────────────────────────────


class RateLimitConfig(BaseModel):
    """Pydantic model for the CDP rate limiter configuration.

    When ``enabled`` is True, the CDPClient sleeps a random delay drawn from
    the configured distribution before each command — emulating human pacing
    between automation steps (bot-detection mitigation).
    """

    enabled: bool = False
    min_delay_ms: float = Field(default=500.0, ge=0)
    max_delay_ms: float = Field(default=3000.0, ge=0)
    distribution: str = Field(default="log-normal")

    @field_validator("distribution")
    @classmethod
    def _validate_distribution(cls, v: str) -> str:
        if v not in ("uniform", "log-normal"):
            raise ValueError(f"distribution must be 'uniform' or 'log-normal', got {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_min_max(self) -> "RateLimitConfig":
        if self.min_delay_ms > self.max_delay_ms:
            raise ValueError("min_delay_ms must be <= max_delay_ms")
        return self


class RateLimiter:
    """Draw random delays between [min_delay_ms, max_delay_ms].

    - ``uniform``:   uniform random in the interval.
    - ``log-normal``: log-normal shaped samples clipped to the interval
      (human response times cluster near the lower bound with a long tail).
    """

    def __init__(self, config: RateLimitConfig | None = None):
        self._config = config or RateLimitConfig()
        self._rng = random.Random()

    @property
    def config(self) -> RateLimitConfig:
        return self._config

    @config.setter
    def config(self, value: RateLimitConfig) -> None:
        self._config = value

    def _uniform_delay(self) -> float:
        lo, hi = self._config.min_delay_ms, self._config.max_delay_ms
        if hi <= lo:
            return float(lo)
        return self._rng.uniform(lo, hi)

    def _log_normal_delay(self) -> float:
        lo, hi = self._config.min_delay_ms, self._config.max_delay_ms
        if hi <= lo:
            return float(lo)
        # Log-normal centered around the lower bound with a tail toward max.
        # mu/log-sigma chosen so samples spread across the interval.
        mu = (math.log(lo) + math.log(hi)) / 2
        sigma = (math.log(hi) - math.log(lo)) / 4
        sample = math.exp(self._rng.gauss(mu, sigma))
        return max(lo, min(hi, sample))

    def get_delay(self) -> float:
        """Return the next delay in milliseconds (0.0 when disabled)."""
        if not self._config.enabled:
            return 0.0
        if self._config.distribution == "uniform":
            return self._uniform_delay()
        return self._log_normal_delay()


class CDPClient:
    """Async CDP client for Chrome browser automation."""

    def __init__(
        self,
        cdp_http_url: str = "http://127.0.0.1:9555",
        websocket_factory: Any = None,
        command_timeout: float = 30.0,
    ):
        self.cdp_http_url = cdp_http_url.rstrip("/")
        self._ws_factory = websocket_factory
        self._command_timeout = command_timeout
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._target_id: str | None = None
        self._message_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = False
        # Rate limiting (P0-3): sleeps before each command when enabled.
        self.rate_limiter = RateLimiter()
        self._tabs: list[dict] = []
        self._active_tab_id: str | None = None
        # Fix-1: the tab the WebSocket is actually attached to.
        # _active_tab_id may temporarily drift (cross-origin targetCreated);
        # _ws_tab_id always reflects the real WS endpoint.
        self._ws_tab_id: str | None = None
        self._network_entries: list[dict] = []
        self._network_monitoring = False
        self._console_entries: list[dict] = []
        self._console_monitoring = False
        self._recording_frames: list[str] | None = None
        self._recording_quality = 70
        self._request_mocks: list[dict] = []
        self._fetch_enabled = False
        self._before_visual_state: dict = {}
        self._connection_type: str = "local"
        # ── Behavioral engine (emberi bemenet) ──
        # Létrehozás session-enként — a session_registry hozza létre,
        # ha a profil engedélyezi. A type_text/scroll/click automatikusan
        # használja, ha elérhető.
        self._behavioral: Any = None
        # Event callbacks: method_name -> list of async callbacks
        self._event_callbacks: dict[str, list] = {}
        # ── Performance optimizations ──
        self._http_client: httpx.AsyncClient | None = None
        """Reusable HTTP client (keep-alive, connection pooling)."""
        self._tabs_cache: list[dict] = []
        self._tabs_cache_ts: float = 0
        self._tabs_cache_ttl: float = 5.0  # seconds

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def connection_type(self) -> str:
        """Return how this client is connected: 'local' or 'remote'."""
        return getattr(self, "_connection_type", "local")

    @classmethod
    async def connect_remote(cls, ws_endpoint: str) -> "CDPClient":
        """Connect to a remote/cloud CDP WebSocket endpoint.

        Creates a fresh CDPClient, connects directly to the given
        ``ws://``/``wss://`` endpoint (no local tab discovery), enables the
        Page and Runtime domains, and marks the connection as ``remote``.

        Returns:
            A connected CDPClient instance (``connection_type == "remote"``).

        Raises:
            CDPError: if the WebSocket connect or domain enable fails.
        """
        client = cls()
        client._connection_type = "remote"
        await client.connect_ws(ws_endpoint)
        return client

    @property
    def tabs_count(self) -> int:
        """Return number of page tabs."""
        return len([t for t in self._tabs if t.get("type") == "page"])

    # ─── Connection ───────────────────────────────────────────────

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create shared HTTP client (keep-alive + connection pooling)."""
        if self._http_client is None or self._http_client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=30)
            self._http_client = httpx.AsyncClient(timeout=5.0, limits=limits)
        return self._http_client

    async def discover_tabs(self) -> list[dict]:
        """Fetch open tabs from /json endpoint (cached up to 5 seconds)."""
        now = time.monotonic()
        if self._tabs_cache and (now - self._tabs_cache_ts) < self._tabs_cache_ttl:
            return self._tabs_cache
        client = await self._get_http_client()
        resp = await client.get(f"{self.cdp_http_url}/json")
        resp.raise_for_status()
        self._tabs_cache = resp.json()
        self._tabs_cache_ts = now
        return self._tabs_cache

    async def connect_browser(self, ws_url: str) -> dict:
        """Connect to the BROWSER-LEVEL CDP WebSocket (``/devtools/browser/<id>``).

        Unlike :meth:`connect` / :meth:`connect_ws`, this does NOT send
        page-scoped commands (``Page.enable``, ``Runtime.enable``, stealth
        patches) — the browser-level socket only supports browser-scoped
        methods (``Target.*``, ``Browser.*``).  Used by the global default
        client so its connection survives tab open/close churn.

        Returns:
            ``{\"status\": \"ok\", \"target_id\": \"\", \"cdp_url\": ws_url}``
        """
        try:
            self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        except Exception as exc:
            raise CDPError(f"Cannot connect to browser CDP WebSocket {ws_url}: {exc}") from exc
        self._connected = True
        self._target_id = None
        self._active_tab_id = None
        self._ws_tab_id = None
        self._message_id = 0
        self._pending = {}
        asyncio.create_task(self._listener())
        return {"status": "ok", "target_id": "", "cdp_url": ws_url}

    async def connect_ws(self, ws_url: str) -> dict:
        """Connect directly to a CDP WebSocket URL (``ws://`` or ``wss://``).

        Unlike :meth:`connect` (which discovers tabs via the HTTP ``/json``
        endpoint), this connects straight to the given WebSocket endpoint —
        e.g. ``ws://127.0.0.1:9222/devtools/browser/<id>`` — without tab
        discovery. Enables Page and Runtime domains like ``connect()``.

        Args:
            ws_url: CDP WebSocket URL.

        Returns:
            ``{"status": "ok", "target_id": ..., "cdp_url": ws_url}``

        Raises:
            CDPError: if the connection or domain enable fails.
        """
        try:
            self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        except Exception as exc:
            raise CDPError(f"Cannot connect to CDP WebSocket {ws_url}: {exc}") from exc
        self._connected = True
        self._target_id = None
        self._active_tab_id = None
        self._message_id = 0
        self._pending = {}

        asyncio.create_task(self._listener())

        await self._send_command("Page.enable")
        await self._send_command("Runtime.enable")
        self._apply_stealth_patches()

        return {
            "status": "ok",
            "target_id": self._target_id or "",
            "cdp_url": ws_url,
        }

    async def connect(self, cdp_url: str | None = None) -> dict:
        """
        Auto-connect to Chrome CDP.

        Discovers available tabs via /json, then connects to the first page
        target (or a specific one matching cdp_url).
        If cdp_url is provided, it's used as the WebSocket URL directly.
        """
        tabs = await self.discover_tabs()
        self._tabs = tabs

        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            raise CDPError("No page targets found in Chrome")

        target = None
        if cdp_url:
            for t in pages:
                if cdp_url in t.get("url", ""):
                    target = t
                    break
        if not target:
            target = pages[0]

        target_id = target["id"]
        ws_url = target["webSocketDebuggerUrl"]

        self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        self._target_id = target_id
        self._active_tab_id = target_id
        self._ws_tab_id = target_id
        self._connected = True
        self._message_id = 0
        self._pending = {}
        self._network_entries = []

        asyncio.create_task(self._listener())

        await self._send_command("Page.enable")
        await self._send_command("Runtime.enable")
        self._apply_stealth_patches()

        return {
            "status": "ok",
            "target_id": target_id,
            "title": target.get("title", ""),
            "url": target.get("url", ""),
            "tabs_count": len(pages),
            "cdp_url": ws_url,
        }

    def _apply_stealth_patches(self) -> None:
        """Inject anti-bot JS patches on every new document.

        Uses the StealthInjector (navigator.webdriver=false, plugins,
        languages, hardware, window.chrome) so sites like perplexity.ai
        do not flag the browser as automated. Failures are non-fatal —
        the browser still works, it just leaks the automation marker.
        """
        try:
            from stealth_injector import StealthInjector

            injector = StealthInjector()
            result = injector.apply(self, level="medium")
            if result.get("failed"):
                logger.warning("Stealth patches failed: %s", result["failed"])
            else:
                logger.info(
                    "Stealth patches applied: %s", ", ".join(result.get("applied", []))
                )
        except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:  # pragma: no cover - defensive
            logger.warning("Stealth patch injection failed: %s", exc)

    async def _listener(self):
        """Background listener for CDP WebSocket messages."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if not future.done():
                        if "error" in msg:
                            future.set_exception(CDPError(msg["error"].get("message", str(msg["error"]))))
                        else:
                            future.set_result(msg.get("result", {}))

                # Network logging
                method = msg.get("method", "")
                if self._network_monitoring and method.startswith("Network."):
                    entry = {
                        "method": method,
                        "timestamp": msg.get("params", {}).get("timestamp", 0),
                        "request_id": msg.get("params", {}).get("requestId", ""),
                    }
                    if method == "Network.requestWillBeSent":
                        req = msg.get("params", {}).get("request", {})
                        entry["url"] = req.get("url", "")
                        entry["type"] = req.get("type", "")
                        entry["method"] = req.get("method", "")
                    elif method == "Network.responseReceived":
                        resp = msg.get("params", {}).get("response", {})
                        entry["url"] = resp.get("url", "")
                        entry["status"] = resp.get("status", 0)
                        entry["status_text"] = resp.get("statusText", "")
                        entry["mime_type"] = resp.get("mimeType", "")
                        entry["size"] = resp.get("encodedDataLength", 0)
                    elif method == "Network.loadingFailed":
                        err = msg.get("params", {}).get("errorText", "")
                        entry["error"] = err
                        entry["blocked_reason"] = msg.get("params", {}).get("blockedReason", "")
                    self._network_entries.append(entry)

                # Console / JS error collection (always on, bounded)
                if method in ("Runtime.consoleAPICalled", "Runtime.exceptionThrown",
                              "Log.entryAdded", "Network.loadingFailed"):
                    try:
                        entry = self._collect_console_event(method, msg.get("params", {}))
                        if entry is not None:
                            self._console_entries.append(entry)
                            if len(self._console_entries) > 500:
                                self._console_entries = self._console_entries[-500:]
                    except (KeyError, TypeError, ValueError) as exc:
                        logger.debug("console collection: %s", exc)

                # Dispatch registered event callbacks
                ev_method = msg.get("method", "")
                if ev_method in self._event_callbacks:
                    for cb in self._event_callbacks[ev_method]:
                        try:
                            cb(msg)
                        except Exception:  # noqa: BLE001
                            logger.warning("Event callback error for %s", ev_method)

                # Track target lifecycle: when Chrome creates a new target (e.g. cross-origin navigation),
                # update _active_tab_id ONLY for OUR WebSocket's tab (_ws_tab_id).
                # Other sessions' tab creations must NOT affect us.
                if ev_method == "Target.targetCreated":
                    target_info = msg.get("params", {}).get("targetInfo", {})
                    if target_info.get("type") == "page":
                        # New page target created — this is likely a navigation to a new origin
                        new_id = target_info.get("targetId")
                        if new_id:
                            logger.debug("CDP targetCreated: %s (%s)", new_id, target_info.get("url", ""))
                            if new_id == self._ws_tab_id:
                                # Our own tab recreated (cross-origin navigation) — track it
                                self._active_tab_id = new_id
                                self._tabs_cache = []  # Invalidate cache
                            else:
                                # External tab (another session/agent) — ignore for isolation
                                logger.debug("CDP external targetCreated ignored: %s (ws_tab=%s)", new_id, self._ws_tab_id)

                elif ev_method == "Target.targetDestroyed":
                    target_id = msg.get("params", {}).get("targetId")
                    if target_id and target_id == self._ws_tab_id:
                        logger.debug("CDP targetDestroyed (our tab): %s", target_id)
                        self._active_tab_id = None
                        self._ws_tab_id = None
                        self._tabs_cache = []  # Invalidate cache

                # Screencast frame capture (video recording)
                if ev_method == "Page.screencastFrame" and self._recording_frames is not None:
                    params = msg.get("params", {})
                    data = params.get("data", "")
                    if data:
                        self._recording_frames.append(data)
                        # Acknowledge the frame so Chrome keeps sending
                        try:
                            await self._send_command(
                                "Page.screencastFrameAck",
                                {"sessionId": params.get("sessionId", 0)},
                            )
                        except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                            logger.debug("screencastFrameAck: %s", exc)

                # Fetch interception (mock API)
                if ev_method == "Fetch.requestPaused" and self._request_mocks:
                    params = msg.get("params", {})
                    req = params.get("request", {})
                    url = req.get("url", "")
                    rid = params.get("requestId", "")
                    # A fő navigációt (Document) mindig átengedjük — a mock
                    # csak az API/erőforrás-kérésekre vonatkozik.
                    res_type = params.get("resourceType", "")
                    # A válaszadás KÜLÖN task-ban fut, hogy a listener ne
                    # blokkolódjon (a _send_command a listener válaszaira várna
                    # — holtpont).
                    asyncio.ensure_future(
                        self._handle_fetch_paused(rid, url, res_type)
                    )

        except websockets.exceptions.ConnectionClosed:
            self._connected = False
            # Fail any pending futures with CDPDisconnectedError
            exc = CDPDisconnectedError("Connection closed by remote")
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(exc)
            self._pending.clear()
        except (websockets.exceptions.WebSocketException, OSError) as e:
            logger.warning("CDP listener error: %s", e)
        finally:
            self._connected = False

    def _collect_console_event(self, method: str, params: dict) -> dict | None:
        """Normalise a CDP console/exception/network-failure event."""
        entry: dict = {"type": method, "timestamp": time.time()}
        if method == "Runtime.consoleAPICalled":
            entry["level"] = params.get("type", "log")
            args = params.get("args", [])
            parts = []
            for a in args[:8]:
                v = a.get("value")
                if v is None:
                    v = a.get("description") or a.get("unserializableValue") or ""
                parts.append(str(v))
            entry["text"] = " ".join(parts)[:500]
            if entry["level"] in ("error", "warning", "assert"):
                return entry
            return None  # only keep warnings/errors (keep buffer small)
        if method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            exc = details.get("exception", {})
            entry["level"] = "exception"
            entry["text"] = (exc.get("description") or exc.get("value") or
                             details.get("text", ""))[:500]
            entry["url"] = details.get("url", "")
            entry["line"] = details.get("lineNumber", -1)
            return entry
        if method == "Log.entryAdded":
            le = params.get("entry", {})
            entry["level"] = le.get("level", "log")
            entry["text"] = le.get("text", "")[:500]
            entry["url"] = le.get("url", "")
            if entry["level"] in ("error", "warning"):
                return entry
            return None
        if method == "Network.loadingFailed":
            entry["level"] = "network_error"
            entry["text"] = params.get("errorText", "")[:300]
            entry["url"] = params.get("requestId", "")
            entry["blocked_reason"] = params.get("blockedReason", "")
            return entry
        return None

    # ── Console monitoring API ───────────────────────────────────

    async def start_console_monitoring(self) -> dict:
        """Enable Runtime/Log domains so console + JS errors are captured."""
        try:
            await self._send_command("Runtime.enable")
            await self._send_command("Log.enable")
            self._console_monitoring = True
            self._console_entries = []
            return {"status": "ok", "console_monitoring": True}
        except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
            return {"status": "error", "error": str(exc)}

    def get_console_entries(self, since: float = 0.0, level: str | None = None) -> list[dict]:
        """Return collected console/error entries (optionally filtered)."""
        entries = [e for e in self._console_entries if e["timestamp"] >= since]
        if level:
            entries = [e for e in entries if e.get("level") == level]
        return entries

    def clear_console_entries(self) -> None:
        """Drop all collected console entries."""
        self._console_entries = []

    async def _send_command(self, method: str, params: dict | None = None, **extra) -> dict:
        """Send CDP command and wait for result.

        Accepts params either as a dict (``params=...``) or as keyword arguments
        (``type=..., x=..., y=...``). Keyword arguments are merged into params
        when both are provided; when only kwargs are passed they become params.
        """
        if extra:
            params = {**(params or {}), **extra}
        # Fix-2: tab-drift guard — the WebSocket is bound to _ws_tab_id; if
        # _active_tab_id drifted (external targetCreated, manual switch),
        # correct it back BEFORE sending so commands always hit our tab.
        if self._ws_tab_id and self._active_tab_id != self._ws_tab_id:
            logger.warning(
                "Tab drift: active=%s ws=%s — correcting to WS tab",
                self._active_tab_id, self._ws_tab_id,
            )
            self._active_tab_id = self._ws_tab_id
        # Human pacing: sleep the configured random delay before sending
        # (no-op when rate limiting is disabled).
        delay_ms = self.rate_limiter.get_delay()
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
        if not self._ws or not self._connected:
            raise CDPError("Not connected to Chrome CDP")
        self._message_id += 1
        msg_id = self._message_id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        await self._ws.send(json.dumps(payload))
        try:
            result = await asyncio.wait_for(future, timeout=self._command_timeout)
            return result
        except TimeoutError:
            self._pending.pop(msg_id, None)
            raise CDPError(f"CDP command timeout: {method}")

    # ─── Rate limiting API (P0-3) ──────────────────────────────────

    def get_rate_config(self) -> dict:
        """Return the current rate limiter config as a dict."""
        c = self.rate_limiter.config
        return {
            "enabled": c.enabled,
            "min_delay_ms": c.min_delay_ms,
            "max_delay_ms": c.max_delay_ms,
            "distribution": c.distribution,
        }

    def set_rate_config(self, config: dict) -> dict:
        """Replace the rate limiter config (partial updates merge)."""
        current = self.get_rate_config()
        merged = {**current, **config}
        self.rate_limiter.config = RateLimitConfig(**merged)
        return self.get_rate_config()

    # ─── Event callback API ────────────────────────────────────────

    def add_event_listener(self, method: str, callback) -> None:
        """Register an async callback for a CDP event method.

        Args:
            method: CDP event method name (e.g. ``Runtime.consoleAPICalled``).
            callback: Async callable receiving the full CDP message dict.
        """
        if method not in self._event_callbacks:
            self._event_callbacks[method] = []
        self._event_callbacks[method].append(callback)

    def remove_event_listener(self, method: str, callback) -> None:
        """Unregister a previously added event callback."""
        if method in self._event_callbacks:
            self._event_callbacks[method] = [
                cb for cb in self._event_callbacks[method] if cb is not callback
            ]

    # ─── Proxy auth auto-cancel ───────────────────────────────────

    def enable_auto_cancel_auth(self) -> None:
        """Auto-dismiss proxy auth prompts (HTTP 401/407).

        When a proxy (e.g. the VPN Unlimited extension) requests credentials
        via ``Network.authRequired``, Chrome shows a password dialog that
        blocks the page load.  Registering a listener that answers every
        challenge with ``Cancel`` makes the dialog never appear -- the request
        simply fails instead of hanging on a password prompt.
        """
        if getattr(self, "_auth_cancel_registered", False):
            return

        async def _cancel_auth(evt: dict) -> None:
            try:
                params = evt.get("params", {})
                req_id = params.get("requestId", "")
                if not req_id:
                    return
                await self._send_command(
                    "Network.authChallengeResponse",
                    {"requestId": req_id, "response": "Cancel"},
                )
                logger.info("Proxy auth challenge auto-cancelled (%s)", req_id[:16])
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("proxy auth cancel: %s", exc)

        self.add_event_listener("Network.authRequired", _cancel_auth)
        self._auth_cancel_registered = True
        logger.info("Auto-cancel of proxy auth challenges enabled")

    def disable_auto_cancel_auth(self) -> None:
        """Stop auto-cancelling proxy auth challenges."""
        self._auth_cancel_registered = False

    # ─── Page operations ─────────────────────────────────────────

    async def navigate(self, url: str) -> dict:
        """Navigate to URL.

        Fix-3 (1-tab-per-session): after navigation, check if Chrome created
        a new target (cross-origin navigation). If so, reconnect WS to the
        new target and update _ws_tab_id so the session follows the page.
        """
        await self._activate_current()
        # Invalidate the tab cache BEFORE navigations that may change the URL
        # of an existing tab (data:/same-origin navigations keep the same tab
        # id, so discover_tabs()'s 5s cache would otherwise return the stale
        # pre-navigation URL). Fix-7 track: get_tabs must reflect the live URL.
        self._tabs_cache = []
        self._tabs_cache_ts = 0
        result = await self._send_command("Page.navigate", {"url": url})

        # After navigation, discover tabs to see if a new target was created
        # for this frame. If so, roam the session's WS to the new target.
        try:
            tabs = await self.discover_tabs()
            pages = [t for t in tabs if t.get("type") == "page"]
            # Find the page target matching our frame (by URL or newest)
            frame_id = result.get("frameId", "")
            target = None
            if frame_id:
                for t in pages:
                    if t.get("id") == frame_id or frame_id in t.get("id", ""):
                        target = t
                        break
            if not target and pages:
                # Fallback: the active target is likely the new one
                for t in pages:
                    if t.get("url", "").startswith("http") and url.split("/")[2] in t.get("url", ""):
                        target = t
                        break
            if not target and pages:
                # Last resort: newest page target
                target = pages[-1]

            if target and target["id"] != self._ws_tab_id:
                logger.info("Navigate cross-origin: roaming %s -> %s", self._ws_tab_id[:8], target["id"][:8])
                await self.connect_to_target(target["id"])
        except (CDPError, OSError) as exc:
            logger.debug("Navigate tab sync skipped: %s", exc)

        return {"status": "ok", "frame_id": result.get("frameId", ""), "url": url}

    async def evaluate(self, js_code: str) -> dict:
        """Execute JavaScript in page and return result."""
        await self._activate_current()
        result = await self._send_command("Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            return {
                "status": "error",
                "error": result["exceptionDetails"].get("text", str(result["exceptionDetails"])),
                "result": None,
            }
        return {
            "status": "ok",
            "result": result.get("result", {}).get("value"),
            "type": result.get("result", {}).get("type", "undefined"),
        }

    async def evaluate_js(self, js_code: str) -> dict:
        """Alias for evaluate()."""
        await self._activate_current()
        return await self.evaluate(js_code)

    # ─── Activate current tab ─────────────────────────────────────

    async def _activate_current(self) -> None:
        """Bring the currently connected tab to the foreground.

        Sends ``Target.activateTarget`` so Chrome wakes the tab and the
        user sees it being active.

        Fix-2: now tab-bound — the targetId sent is the WebSocket's real
        tab (_ws_tab_id), not a drifted _active_tab_id.  Only activates when
        we have a live connection (no-op otherwise).
        """
        tab_id = self._ws_tab_id or self._active_tab_id
        if tab_id:
            try:
                await self._send_command("Target.activateTarget",
                                         {"targetId": tab_id})
                await asyncio.sleep(0.1)
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("activateCurrent: %s", exc)

    async def _activate_tab_by_id(self, tab_id: str) -> dict:
        """Activate a specific tab by target ID (brings it to foreground)."""
        try:
            await self._send_command("Target.activateTarget",
                                     {"targetId": tab_id})
            return {"status": "ok", "tab_id": tab_id}
        except (CDPError, OSError) as exc:
            return {"status": "error", "error": str(exc)}

    # ─── Smart form fill ──────────────────────────────────────────

    async def smart_form_fill(self, fields: list[dict], timeout: int = 5) -> dict:
        """Fill form fields - no CSS selectors needed.

        Each field descriptor may contain:
          - label:         match by <label> text, placeholder, name, aria-label
          - selector:      direct CSS selector (fastest path)
          - placeholder:   exact placeholder attribute match
          - nth:           0-based index among matching fields (default 0)
          - value:         the value to type into the field
        """
        await self._activate_current()
        js = r"""
(function() {
  const fields = """ + json.dumps(fields) + r""";
  const maxWait = """ + str(int(timeout * 1000)) + r""";

  function findAllByLabel(label) {
    const low = label.toLowerCase().trim();
    const found = [];
    // 1. <label for="id"> or <label> wrapping input
    for (const lb of document.querySelectorAll("label")) {
      const lbl = (lb.textContent || "").toLowerCase().trim();
      if (!lbl.includes(low)) continue;
      if (lb.getAttribute("for")) {
        const el = document.getElementById(lb.getAttribute("for"));
        if (el) { found.push(el); continue; }
      }
      const wrapped = lb.querySelector("input, textarea, select");
      if (wrapped) { found.push(wrapped); continue; }
    }
    // 2. Placeholder match without constructing a fragile CSS attribute selector.
    for (const el of document.querySelectorAll("input, textarea")) {
      if ((el.placeholder || "").toLowerCase().includes(low) && !found.includes(el)) found.push(el);
    }
    // 3. Name / aria-label match
    document.querySelectorAll(
      "input[name*='" + CSS.escape(label) + "'], " +
      "input[aria-label*='" + CSS.escape(label) + "'], " +
      "textarea[name*='" + CSS.escape(label) + "'], " +
      "textarea[aria-label*='" + CSS.escape(label) + "']"
    ).forEach(el => { if (!found.includes(el)) found.push(el); });
    // 4. Adjacent label (previous sibling or parent)
    for (const el of document.querySelectorAll("input, textarea")) {
      if (found.includes(el)) continue;
      const prev = el.previousElementSibling;
      if (prev && (prev.textContent || "").toLowerCase().includes(low)) { found.push(el); continue; }
      const parent = el.parentElement;
      if (parent && (parent.textContent || "").toLowerCase().includes(low) && parent.children.length < 4)
        found.push(el);
    }
    return found;
  }

  const results = [];
  const deadline = Date.now() + maxWait;

  for (const f of fields) {
    try {
      const fieldId = f.selector || f.placeholder || f.label || "(unknown)";
      let el = null;
      // 1. Direct CSS selector
      if (f.selector) {
        el = document.querySelector(f.selector);
      }
      // 2. Exact placeholder match
      if (!el && f.placeholder) {
        el = Array.from(document.querySelectorAll("input, textarea"))
          .find(candidate => (candidate.placeholder || "") === f.placeholder) || null;
      }
      // 3. Label / smart lookup
      if (!el && f.label) {
        const matches = findAllByLabel(f.label);
        const idx = f.nth || 0;
        el = matches[idx] || null;
      }
      if (!el) {
        results.push({field: fieldId, status: "error", error: "field not found"});
        continue;
      }
      while (Date.now() < deadline) {
        if (el.offsetParent !== null) break;
      }
      el.focus();
      if (el.getAttribute("contenteditable") === "true") {
        el.textContent = f.value;
      } else {
        el.value = "";
        el.value = f.value;
      }
      el.dispatchEvent(new Event("input", {bubbles: true}));
      el.dispatchEvent(new Event("change", {bubbles: true}));
      el.dispatchEvent(new Event("blur", {bubbles: true}));
      const tag = el.tagName.toLowerCase();
      const type = el.type || "";
      results.push({field: fieldId, status: "ok", tag: tag, type: type, filled: f.value.substring(0, 50)});
    } catch(e) {
      const fieldId = f.selector || f.placeholder || f.label || "(unknown)";
      results.push({field: fieldId, status: "error", error: e.message});
    }
  }
  return JSON.stringify({fields_filled: results.length, results: results});
})();
"""
        result = await self.evaluate(js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed", "raw": str(raw)[:200]}
        return {"status": "ok", "fields": fields, "result": data}

    # ─── v1.27: F3 — form structure extraction ─────────────────────

    async def form_extract(self) -> dict:
        """Extract the page's form structure (fields, types, labels, required).

        Returns a list of form descriptors — each field's name, type,
        placeholder, aria-label, associated label text, required flag, and
        whether it's visible.  Lets an agent introspect a form before
        filling it (``smart_form_fill`` with exact labels).
        """
        await self._activate_current()
        js = r"""
(() => {
  const forms = Array.from(document.querySelectorAll("form"));
  const seen = new Set();
  const out = [];
  for (const form of forms) {
    const fields = Array.from(form.querySelectorAll("input, textarea, select, button[type='submit'], [contenteditable='true']"));
    const descs = [];
    for (const el of fields) {
      if (seen.has(el)) continue;
      seen.add(el);
      let labelText = "";
      if (el.id && document.querySelector("label[for='" + CSS.escape(el.id) + "']")) {
        labelText = document.querySelector("label[for='" + CSS.escape(el.id) + "']").textContent.trim();
      } else {
        const wrap = el.closest("label");
        if (wrap) labelText = wrap.textContent.trim();
      }
      if (!labelText) {
        const prev = el.previousElementSibling;
        if (prev && (prev.tagName === "LABEL" || prev.tagName === "SPAN" || prev.tagName === "DIV"))
          labelText = prev.textContent.trim().substring(0, 100);
      }
      const tag = el.tagName.toLowerCase();
      const type = el.type || (tag === "select" ? "select" : tag === "textarea" ? "textarea" : "text");
      descs.push({
        tag: tag,
        type: type,
        name: el.name || "",
        id: el.id || "",
        placeholder: el.placeholder || "",
        aria_label: el.getAttribute("aria-label") || "",
        label: labelText.substring(0, 120),
        required: !!el.required || el.getAttribute("aria-required") === "true",
        visible: el.offsetParent !== null,
        options: tag === "select" ? Array.from(el.options).map(o => o.text).slice(0, 20) : undefined
      });
    }
    if (descs.length) out.push({form_id: form.id || "", form_action: form.action || "", fields: descs});
  }
  // Orphan fields (outside <form>)
  const orphan = Array.from(document.querySelectorAll("input:not(form input), textarea:not(form textarea)"));
  const od = [];
  for (const el of orphan) {
    if (seen.has(el)) continue;
    seen.add(el);
    od.push({tag: el.tagName.toLowerCase(), type: el.type || "text", name: el.name || "",
             id: el.id || "", placeholder: el.placeholder || "", required: !!el.required,
             visible: el.offsetParent !== null});
  }
  if (od.length) out.push({form_id: "(orphan)", form_action: "", fields: od});
  return JSON.stringify({forms: out.length, form_count: out.length, forms_list: out});
})();
"""
        result = await self.evaluate(js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed", "raw": str(raw)[:200]}
        return {"status": "ok", "result": data}

    async def fill_autocomplete(self, label: str, value: str, timeout_ms: int = 5000) -> dict:
        """Fill an autocomplete field and click the first matching visible option."""
        await self._activate_current()
        js = f"""
(async function() {{
  const label = {json.dumps(label)}.toLowerCase().replaceAll('_', ' ');
  const value = {json.dumps(value)};
  const deadline = Date.now() + {int(timeout_ms)};
  const fields = [...document.querySelectorAll('input,textarea,[contenteditable=true]')];
  const field = fields.find(el => {{
    const text = [el.getAttribute('aria-label'), el.placeholder, el.name,
      document.querySelector(`label[for="${{el.id}}"]`)?.innerText].filter(Boolean).join(' ').toLowerCase();
    return text.includes(label);
  }});
  if (!field) return {{status:'error', error:'autocomplete field not found', field:label}};
  field.focus();
  if (field.isContentEditable) field.textContent=value; else field.value=value;
  field.dispatchEvent(new InputEvent('input', {{bubbles:true,inputType:'insertText',data:value}}));
  field.dispatchEvent(new Event('change', {{bubbles:true}}));
  await new Promise(r => setTimeout(r, 500));
  while (Date.now() < deadline) {{
    const options=[...document.querySelectorAll('[role=option],mat-option,.ng-option,[data-option-index]')]
      .filter(el => el.offsetParent !== null && (el.innerText||el.textContent||'').toLowerCase().includes(value.toLowerCase()));
    if (options.length) {{
      const actual=(options[0].innerText||options[0].textContent||'').trim(); options[0].click();
      return {{status:'ok', field:label, value, selected:actual}};
    }}
    await new Promise(r => setTimeout(r, 100));
  }}
  return {{status:'error', error:'autocomplete option not found', field:label, value}};
}})()
"""
        result = await self.evaluate(js)
        return {"status": "ok", "result": result.get("result", result)}

    async def select_tab_by_text(self, text: str, timeout_ms: int = 5000) -> dict:
        """Select a DOM tab by role or common tab attributes, including hidden AX tabs."""
        await self._activate_current()
        js = f"""
(async function() {{
 const target={json.dumps(text)}.toLowerCase().trim(), deadline=Date.now()+{int(timeout_ms)};
 while(Date.now()<deadline) {{
  const tabs=[...document.querySelectorAll('[role=tab],[aria-controls][tabindex],button,a')];
  const tab=tabs.find(el => (el.innerText||el.textContent||el.getAttribute('aria-label')||'').toLowerCase().trim()===target);
  if(tab) {{ tab.scrollIntoView({{block:'center'}}); tab.click(); return {{status:'ok',selected:text,role:tab.getAttribute('role')}}; }}
  await new Promise(r=>setTimeout(r,100));
 }}
 return {{status:'error',error:'tab not found',text}};
}})()
"""
        result = await self.evaluate(js)
        return {"status": "ok", "result": result.get("result", result)}

    async def wait_for_text_detailed(self, text: str, timeout_ms: int = 10000) -> dict:
        """Wait for visible text and report elapsed time plus matched text."""
        await self._activate_current()
        js = f"""
(async function() {{
 const started=Date.now(), deadline=started+{int(timeout_ms)}, wanted={json.dumps(text)}.toLowerCase();
 while(Date.now()<deadline) {{
  const nodes=[...document.querySelectorAll('body *')].filter(el=>el.offsetParent!==null && (el.innerText||'').toLowerCase().includes(wanted));
  if(nodes.length) return {{found:true,elapsed_ms:Date.now()-started,actual_text:(nodes[0].innerText||'').trim().substring(0,500)}};
  await new Promise(r=>setTimeout(r,100));
 }}
 return {{found:false,elapsed_ms:Date.now()-started,actual_text:''}};
}})()
"""
        result = await self.evaluate(js)
        value = result.get("result", result)
        return value if isinstance(value, dict) else {"found": False, "elapsed_ms": timeout_ms, "actual_text": ""}

    async def trigger_lazy_history(self, max_scrolls: int = 12) -> dict:
        """Scroll through an SPA page to trigger bounded lazy loading, then restore top."""
        await self._activate_current()
        js = f"""
(async function() {{
 let previous=-1, stable=0, scrolls=0;
 while(scrolls<{int(max_scrolls)} && stable<2) {{
  window.scrollTo(0,document.documentElement.scrollHeight); await new Promise(r=>setTimeout(r,250));
  const height=document.documentElement.scrollHeight; stable=height===previous?stable+1:0; previous=height; scrolls++;
 }}
 window.scrollTo(0,0); return {{status:'ok',scrolls,height:previous}};
}})()
"""
        result = await self.evaluate(js)
        return {"status": "ok", "result": result.get("result", result)}

    # ─── Wait for element ─────────────────────────────────────────

    async def wait_for_element(self, selector: str, timeout: int = 10,
                               visible: bool = True) -> dict:
        """Wait until an element matching *selector* appears in DOM.

        Polls every 200 ms. Returns the element's tag and text when found.
        """
        await self._activate_current()
        js = f"""
(async function() {{
  const deadline = Date.now() + {timeout * 1000};
  const poll = 200;
  while (Date.now() < deadline) {{
    const el = document.querySelector({json.dumps(selector)});
    if (el) {{
      const isVisible = el.offsetParent !== null;
      if (!{str(visible).lower()} || isVisible) {{
        return JSON.stringify({{
          status: "ok",
          tag: el.tagName,
          text: (el.textContent || "").trim().substring(0, 200),
          visible: isVisible,
          rect: {{w: el.offsetWidth, h: el.offsetHeight}}
        }});
      }}
    }}
    await new Promise(r => setTimeout(r, poll));
  }}
  return JSON.stringify({{status: "error", error: "timeout after " + {timeout} + "s"}});
}})();
"""
        result = await self.evaluate(js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed"}
        return {"status": "ok", "selector": selector, "timeout": timeout, "result": data}

    # ─── v1.27: F2 — generic wait-for / assertion engine ───────────

    async def wait_for_condition(self, kind: str, value: str, condition: str = "present",
                                 timeout: int = 10) -> dict:
        """Wait until a DOM condition holds (selector|text|url × present|gone|visible).

        *kind*: ``selector`` (CSS), ``text`` (visible text), ``url`` (substring
        of the current URL).
        *condition*: ``present`` (exists), ``gone`` (does not exist),
        ``visible`` (exists and visible).
        Polls every 200 ms; returns ok/error deterministically.
        """
        await self._activate_current()
        cond_js = {
            "selector": "document.querySelector({v}) !== null",
            "text": "document.body && document.body.innerText.includes({v})",
            "url": "location.href.includes({v})",
        }
        if kind not in cond_js:
            return {"status": "error", "error": f"unknown kind: {kind} (selector|text|url)"}
        if condition not in ("present", "gone", "visible"):
            return {"status": "error", "error": f"unknown condition: {condition} (present|gone|visible)"}
        base = cond_js[kind]
        if kind == "selector" and condition == "visible":
            base = "(() => { const el = document.querySelector({v}); return el !== null && el.offsetParent !== null; })()"
        check = f"!({base})" if condition == "gone" else base
        js = f"""
(async function() {{
  const deadline = Date.now() + {int(timeout) * 1000};
  const poll = 200;
  const v = {json.dumps(value)};
  while (Date.now() < deadline) {{
    try {{
      if ({check}) return JSON.stringify({{status: "ok", condition: "{condition}", kind: "{kind}"}});
    }} catch (e) {{ if ("{condition}" === "gone") return JSON.stringify({{status: "ok", condition: "gone"}}); }}
    await new Promise(r => setTimeout(r, poll));
  }}
  return JSON.stringify({{status: "error", error: "timeout after {int(timeout)}s waiting for {condition} {kind}=" + v}});
}})();
"""
        result = await self.evaluate(js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed"}
        return {"status": "ok", "kind": kind, "value": value, "condition": condition,
                "timeout": timeout, "result": data}

    async def assert_elements(self, kind: str, value: str, condition: str = "exists",
                              expected: int | None = None) -> dict:
        """Assert a DOM condition, returning structured pass/fail.

        *kind*: ``selector`` | ``text`` | ``url``.
        *condition*: ``exists`` | ``not_exists`` | ``count`` | ``contains``.
        For ``count``, *expected* is the exact number of matches.
        For ``contains`` (text only), *expected* is the substring to find
        inside the matched element's text.
        Returns ``{"status": "ok", "passed": bool, ...}`` — callers decide
        whether a failed assertion is an error (REST 409 / MCP tool_error).
        """
        await self._activate_current()
        if kind not in ("selector", "text", "url"):
            return {"status": "error", "error": f"unknown kind: {kind} (selector|text|url)"}
        if condition not in ("exists", "not_exists", "count", "contains"):
            return {"status": "error", "error": f"unknown condition: {condition} (exists|not_exists|count|contains)"}
        if condition == "count" and expected is None:
            return {"status": "error", "error": "expected count required for condition=count"}
        js = f"""
(() => {{
  const v = {json.dumps(value)};
  let found, count = 0, sample = "";
  if ("{kind}" === "selector") {{
    const els = document.querySelectorAll(v);
    count = els.length;
    found = count > 0;
    sample = found ? (els[0].textContent || "").trim().substring(0, 200) : "";
  }} else if ("{kind}" === "text") {{
    found = document.body ? document.body.innerText.includes(v) : false;
    count = found ? 1 : 0;
  }} else {{
    found = location.href.includes(v);
    count = found ? 1 : 0;
  }}
  let passed;
  if ("{condition}" === "exists") passed = found;
  else if ("{condition}" === "not_exists") passed = !found;
  else if ("{condition}" === "count") passed = count === {int(expected) if expected is not None else -1};
  else passed = found && sample.includes({json.dumps(expected) if expected is not None else ""});
  return JSON.stringify({{passed, found, count, sample: sample.substring(0, 200), kind: "{kind}", condition: "{condition}"}});
}})();
"""
        result = await self.evaluate(js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"passed": False, "error": "parse failed"}
        return {"status": "ok", "kind": kind, "value": value, "condition": condition,
                "expected": expected, "result": data}

    # ─── v0.8: Wait for visible element ─────────────────────────────

    async def wait_visible(self, selector: str, timeout: int = 10) -> dict:
        """Wait for an element to be both present and visible.

        Delegates to wait_for_element with visible=True.
        Returns element info on success or error dict on timeout.
        """
        await self._activate_current()
        try:
            result = await self.wait_for_element(selector, timeout, True)
            return result
        except TimeoutError as e:
            return {"status": "error", "error": str(e)}

    # ─── Click by text ────────────────────────────────────────────

    async def click_by_text(self, text: str, timeout: int = 5,
                            container_selector: str | None = None,
                            nth: int = 0) -> dict:
        """Click an element by its visible text content.

        Searches all visible ``a``, ``button``, ``input[type=submit]``,
        and ``[role=button]`` elements whose text matches. Clicks the
        first match using real CDP mouse events.

        If *container_selector* is given, restricts search to elements
        inside that CSS selector (e.g. "accept-modal" to only search
        within a modal).

        If *nth* is given (0-indexed), clicks the Nth matching element
        instead of the first. Useful for lists of identical buttons
        (e.g. "Edit", "Delete" in a table).
        """
        await self._activate_current()
        container_js = ""
        if container_selector:
            container_js = f"const container = document.querySelector({json.dumps(container_selector)}); if (!container) return JSON.stringify({{status: 'error', error: 'container not found: {json.dumps(container_selector)}'}});"
        js = f"""
(function() {{
{container_js}
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const deadline = Date.now() + {timeout * 1000};
  const nth = {nth};

  function findAll() {{
    const root = {('document' if not container_selector else 'container')};
    const results = [];
    const seen = new Set();

    // Priority: interactive elements
    const interactive = root.querySelectorAll(
      "a, button, input[type=submit], input[type=button], [role=button]"
    );
    for (let el of interactive) {{
      if (el.offsetParent === null) continue;
      const txt = (el.textContent || "").toLowerCase().trim();
      if (txt === low || txt.includes(low)) {{
        const key = txt + ":" + Math.round(el.getBoundingClientRect().x) + ":" + Math.round(el.getBoundingClientRect().y);
        if (!seen.has(key)) {{
          seen.add(key);
          results.push(el);
        }}
      }}
    }}

    // Fallback: clickable spans/divs
    if (results.length === 0) {{
      const all = root.querySelectorAll("[onclick], span, div");
      for (let el of all) {{
        if (el.offsetParent === null) continue;
        const txt = (el.textContent || "").toLowerCase().trim();
        if (txt === low) {{
          const key = txt + ":" + Math.round(el.getBoundingClientRect().x);
          if (!seen.has(key)) {{
            seen.add(key);
            results.push(el);
          }}
        }}
      }}
    }}

    return results;
  }}

  while (Date.now() < deadline) {{
    const matches = findAll();
    if (matches.length > nth) {{
      const el = matches[nth];
      el.scrollIntoView({{behavior: "instant", block: "center"}});
      const r = el.getBoundingClientRect();
      return JSON.stringify({{
        status: "ok",
        tag: el.tagName,
        text: (el.textContent || "").trim().substring(0, 100),
        x: r.x + r.width/2,
        y: r.y + r.height/2,
        w: r.width,
        h: r.height,
        match_index: nth,
        total_matches: matches.length,
      }});
    }}
  }}
  return JSON.stringify({{status: "error", error: "text not found: " + target.substring(0, 50) + " (nth=" + nth + ")"}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "parse failed"}
        if data.get("status") == "error":
            return data
        # Perform real CDP click at the position
        x, y = data.get("x", 0), data.get("y", 0)
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        data["cdp_click"] = True
        return {"status": "ok", "text": text, "result": data}

    # ─── NEW: Find element by text ────────────────────────────────

    async def find_element_by_text(self, text: str, tag: str | None = None,
                                    return_selector: bool = True) -> dict:
        """Find a visible element by its text content.

        Returns the element's position, CSS selector, and attributes.
        Does NOT click it — use click_by_text / click_label for that.

        *tag* restricts to a specific HTML tag (button, a, input, label, etc.).
        *return_selector* generates a unique CSS selector for the element.
        """
        await self._activate_current()
        tag_filter = ""
        if tag:
            tag_filter = f"el.tagName.toLowerCase() === {json.dumps(tag.lower())} &&"
        js = f"""
(function() {{
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const deadline = Date.now() + 5000;

  function getSelector(el) {{
    if (el.id) return "#" + CSS.escape(el.id);
    let path = [];
    let cur = el;
    while (cur && cur !== document.body) {{
      let tag = cur.tagName.toLowerCase();
      if (cur.id) {{ path.unshift("#" + CSS.escape(cur.id)); break; }}
      let parent = cur.parentElement;
      if (parent) {{
        let idx = 1;
        for (let sib of parent.children) {{
          if (sib === cur) break;
          if (sib.tagName === cur.tagName) idx++;
        }}
        tag += ":nth-child(" + idx + ")";
      }}
      path.unshift(tag);
      cur = parent;
    }}
    return path.join(" > ");
  }}

  while (Date.now() < deadline) {{
    const all = document.querySelectorAll("*");
    const results = [];
    for (let el of all) {{
      if (el.offsetParent === null) continue;
      if (!({tag_filter} true)) continue;
      const txt = (el.textContent || "").trim().toLowerCase();
      if (txt === low || txt.includes(low)) {{
        const r = el.getBoundingClientRect();
        results.push({{
          tag: el.tagName,
          text: (el.textContent || "").trim().substring(0, 100),
          selector: getSelector(el),
          x: Math.round(r.x + r.width/2),
          y: Math.round(r.y + r.height/2),
          w: Math.round(r.width),
          h: Math.round(r.height),
          id: el.id || "",
          name: el.getAttribute("name") || "",
          type: el.type || "",
          href: el.getAttribute("href") || "",
          is_interactive: ["A","BUTTON","INPUT","SELECT","TEXTAREA","LABEL"].includes(el.tagName),
        }});
        if (results.length >= 10) break;
      }}
    }}
    if (results.length > 0) return JSON.stringify({{status: "ok", matches: results, count: results.length}});
  }}
  return JSON.stringify({{status: "error", error: "element not found: " + target.substring(0, 50)}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "parse failed"}
        return {"status": "ok", "text": text, "result": data}

    # ─── NEW: Click by label text (framework-safe) ────────────────

    async def click_label(self, text: str, timeout: int = 5) -> dict:
        """Click a <label> element whose text matches.

        Unlike click_by_text which clicks visible DIV/SPAN/BUTTON elements,
        this targets actual HTML <label> elements.  Framework forms
        (React, Vue, Symfony) only respond to real <label> clicks that
        toggle the associated input — plain element clicks don't register.

        Searches labels by priority:
        1. Exact match on <label> text
        2. Partial match (fallback)
        Automatically scrolls the label into view and uses real CDP
        mouse events so framework two-way binding fires correctly.
        """
        await self._activate_current()
        js = f"""
(function() {{
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const deadline = Date.now() + {timeout * 1000};

  function findLabel() {{
    while (Date.now() < deadline) {{
      const labels = document.querySelectorAll("label");
      let best = null, bestMatch = 0;
      for (let lb of labels) {{
        if (lb.offsetParent === null) continue;
        const txt = (lb.textContent || "").trim().toLowerCase();
        if (txt === low) {{ best = lb; bestMatch = 2; break; }}
        if (txt.includes(low) && bestMatch < 2) {{ best = lb; bestMatch = 1; }}
      }}
      if (best) return best;
    }}
    return null;
  }}

  const el = findLabel();
  if (!el) return JSON.stringify({{status: "error", error: "label not found: " + target.substring(0, 50)}});

  el.scrollIntoView({{behavior: "instant", block: "center"}});
  const r = el.getBoundingClientRect();
  // Click the label with real CDP mouse events (framework-safe)
  return JSON.stringify({{
    status: "ok",
    tag: "LABEL",
    text: (el.textContent || "").trim().substring(0, 100),
    forAttr: el.getAttribute("for") || "",
    x: r.x + r.width / 2,
    y: r.y + r.height / 2,
    w: r.width,
    h: r.height,
  }});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "parse failed"}
        if data.get("status") == "error":
            return data
        # Real CDP click
        x, y = data.get("x", 0), data.get("y", 0)
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        return {"status": "ok", "label": text, "result": data}

    # ─── v0.8: Click at pixel coordinates ───────────────────────────

    async def click_coordinates(self, x: int, y: int, button: str = "left",
                                 click_count: int = 1) -> dict:
        """Click at pixel coordinates using CDP Input.dispatchMouseEvent.

        Args:
            x: X coordinate relative to viewport
            y: Y coordinate relative to viewport
            button: Mouse button ('left', 'right', 'middle')
            click_count: Number of clicks (1=click, 2=double-click)
        """
        await self._activate_current()
        await self._send_command("Input.dispatchMouseEvent",
                                 type="mousePressed", x=x, y=y,
                                 button=button, clickCount=click_count)
        await self._send_command("Input.dispatchMouseEvent",
                                 type="mouseReleased", x=x, y=y,
                                 button=button, clickCount=click_count)
        return {"status": "ok", "x": x, "y": y, "button": button, "click_count": click_count}

    # ─── NEW: Checkbox / Radio state management ────────────────────

    async def checkbox_set_state(self, text: str, checked: bool, timeout: int = 5) -> dict:
        """Set checkbox/radio state by label text.

        Finds the checkbox or radio associated with the label *text* using the
        same label-resolution strategy as ``analyze_page()`` (for= attribute,
        wrapping <label>, parent <label>, aria-label).  If the input's current
        ``checked`` property differs from *checked*, clicks the label (framework-safe)
        to toggle it.

        Args:
            text: The label text of the checkbox/radio to target.
            checked: ``True`` to check/select, ``False`` to uncheck/deselect.
            timeout: Max seconds to wait for the element to appear.

        Returns:
            dict with ``status``, ``label``, ``checked`` (new state),
            ``was_already_checked`` (previous state).
        """
        await self._activate_current()
        js = f"""
(async function() {{
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const deadline = Date.now() + {timeout * 1000};
  const wantChecked = {str(checked).lower()};

  function findInput() {{
    while (Date.now() < deadline) {{
      const all = document.querySelectorAll("input[type=checkbox], input[type=radio]");
      for (let el of all) {{
        if (el.offsetParent === null) continue;
        let label = "";
        const id = el.id;
        if (id) {{
          const lbl = document.querySelector("label[for='" + CSS.escape(id) + "']");
          if (lbl) label = (lbl.textContent || "").trim().toLowerCase();
        }}
        if (!label && el.parentElement) {{
          const pl = el.parentElement.querySelector("label");
          if (pl) label = (pl.textContent || "").trim().toLowerCase();
        }}
        if (!label) {{
          const prev = el.previousElementSibling;
          if (prev && prev.tagName === "LABEL") label = (prev.textContent || "").trim().toLowerCase();
        }}
        if (!label) label = el.getAttribute("aria-label") || "";
        if (label.includes(low) || label === low) {{
          return {{el: el, label: label}};
        }}
        // Check for adjacent label text node
        const parent = el.parentElement;
        if (parent && parent.children.length < 4) {{
          const pt = (parent.textContent || "").toLowerCase().trim();
          if (pt.includes(low) || pt === low) {{
            return {{el: el, label: label || (el.getAttribute("aria-label") || "").trim() || el.name || ""}};
          }}
        }}
      }}
      // Fallback: find label elements that match and get their associated input
      const labels = document.querySelectorAll("label");
      for (let lb of labels) {{
        if (lb.offsetParent === null) continue;
        const txt = (lb.textContent || "").trim().toLowerCase();
        if (txt.includes(low) || txt === low) {{
          const forId = lb.getAttribute("for");
          if (forId) {{
            const inp = document.getElementById(forId);
            if (inp && (inp.type === "checkbox" || inp.type === "radio")) return {{el: inp, label: txt}};
          }}
          const wrapped = lb.querySelector("input[type=checkbox], input[type=radio]");
          if (wrapped) return {{el: wrapped, label: txt}};
        }}
      }}
      await new Promise(r => setTimeout(r, 200));
    }}
    return null;
  }}

  const found = findInput();
  if (!found) return JSON.stringify({{status: "error", error: "checkbox/radio not found: " + target.substring(0, 50)}});

  const el = found.el;
  const wasChecked = el.checked === true;
  const oldState = wasChecked ? true : false;

  if (wasChecked !== wantChecked) {{
    // Toggle by clicking the associated label
    const id = el.id;
    let labelEl = null;
    if (id) labelEl = document.querySelector("label[for='" + CSS.escape(id) + "']");
    if (!labelEl) {{
      const parent = el.parentElement;
      if (parent) labelEl = parent.querySelector("label");
    }}
    if (!labelEl) {{
      const prev = el.previousElementSibling;
      if (prev && prev.tagName === "LABEL") labelEl = prev;
    }}
    if (!labelEl) {{
      // Click the input directly
      el.scrollIntoView({{behavior: "instant", block: "center"}});
      const r = el.getBoundingClientRect();
      return JSON.stringify({{
        click_x: r.x + r.width / 2,
        click_y: r.y + r.height / 2,
        needs_cdp: true,
        label: found.label,
        was_already_checked: oldState,
        want_checked: wantChecked,
      }});
    }}
    labelEl.scrollIntoView({{behavior: "instant", block: "center"}});
    const r = labelEl.getBoundingClientRect();
    return JSON.stringify({{
      click_x: r.x + r.width / 2,
      click_y: r.y + r.height / 2,
      needs_cdp: true,
      label: found.label,
      was_already_checked: oldState,
      want_checked: wantChecked,
    }});
  }}

  return JSON.stringify({{
    label: found.label,
    was_already_checked: oldState,
    already_matched: true,
  }});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed", "raw": str(raw)[:200]}

        # If we need CDP click
        if data.get("needs_cdp"):
            x = data.get("click_x", 0)
            y = data.get("click_y", 0)
            await self._send_command("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": x, "y": y,
                "button": "left", "clickCount": 1,
            })
            await self._send_command("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": x, "y": y,
                "button": "left", "clickCount": 1,
            })
            new_state = checked
        elif data.get("already_matched"):
            new_state = checked
        else:
            new_state = checked

        return {
            "status": "ok",
            "label": data.get("label", text),
            "checked": new_state,
            "was_already_checked": data.get("was_already_checked", False),
        }

    async def checkbox_set_state_batch(self, texts: list[str], checked: bool, timeout: int = 5) -> dict:
        """Set multiple checkbox/radio states by label texts.

        Calls ``checkbox_set_state`` for each text in parallel.

        Args:
            texts: List of label texts to target.
            checked: Target state for all items.
            timeout: Max seconds per item.

        Returns:
            dict with ``status``, ``results`` (list of individual results).
        """
        tasks = [self.checkbox_set_state(t, checked, timeout) for t in texts]
        results = await asyncio.gather(*tasks)
        return {
            "status": "ok",
            "results": results,
        }

    # ─── NEW: Post-operation confirmation helpers ──────────────────

    async def _confirm_with_screenshot(self) -> dict:
        """Capture a base64 JPEG screenshot after an operation.

        Returns:
            dict with ``screenshot`` (base64 JPEG string).
        """
        result = await self.screenshot()
        return {
            "screenshot": result.get("data", ""),
        }

    async def _confirm_with_analyze(self) -> dict:
        """Re-analyze the page and return checkbox/radio visual_state.

        Returns:
            dict with ``state_change`` containing ``before`` / ``after`` visual_state
            and a ``changed`` boolean.
        """
        current = await self.analyze_page()
        page = current.get("page", {})
        after = page.get("visual_state", {})
        before = getattr(self, "_before_visual_state", {})
        changed = before != after
        return {
            "state_change": {
                "before": before,
                "after": after,
                "changed": changed,
            }
        }

    async def click(self, selector: str) -> dict:
        """Click element by CSS selector via real CDP mouse events.

        If a behavioral engine is enabled, the click uses human-like mouse
        trajectory (WindMouse + Bezier) with natural timing instead of an
        instant jump-and-click.
        """
        await self._activate_current()
        # Get element position
        js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return {{'status': 'error', 'error': 'Element not found: {json.dumps(selector)}'}};"
            f"  el.scrollIntoView({{behavior: 'instant', block: 'center'}});"
            f"  const rect = el.getBoundingClientRect();"
            f"  return {{'status': 'ok', 'x': rect.x + rect.width/2, 'y': rect.y + rect.height/2, 'tag': el.tagName}};"
            f"}})()"
        )
        eval_result = await self.evaluate(js)
        if eval_result.get("status") == "error":
            return eval_result
        pos = eval_result.get("result", {})
        if not isinstance(pos, dict) or not pos.get("tag"):
            # Runtime.evaluate returned undefined/empty (e.g. the JS threw
            # inside scrollIntoView) or the element query failed silently —
            # treat as "Element not found" instead of clicking (0, 0).
            return {
                "status": "error",
                "error": f"Element not found: {selector}",
            }
        x, y = pos.get("x", 0), pos.get("y", 0)
        # Use behavioral engine if enabled
        if self._behavioral and self._behavioral.profile.enabled:
            await self._behavioral.click_at(x, y)
        else:
            await self._send_command("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": x, "y": y,
                "button": "left", "clickCount": 1,
            })
            await self._send_command("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": x, "y": y,
                "button": "left", "clickCount": 1,
            })
        return {"status": "ok", "selector": selector, "position": {"x": x, "y": y}}

    async def type_text(self, selector: str, text: str) -> dict:
        """Type text into an element found by CSS selector.

        If a behavioral engine is enabled, uses dwell/flight timing with
        natural keystroke rhythm instead of an instant insertText.
        """
        await self._activate_current()
        if self._behavioral and self._behavioral.profile.enabled:
            return await self._behavioral.type_text(selector, text)
        js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return {{'status': 'error', 'error': 'Element not found'}};"
            f"  el.focus(); el.value = '';"
            f"  el.dispatchEvent(new Event('input', {{bubbles: true}}));"
            f"  el.dispatchEvent(new Event('change', {{bubbles: true}}));"
            f"  return {{'status': 'ok'}};"
            f"}})()"
        )
        result = await self.evaluate(js)
        if result.get("status") == "error":
            return result
        await self._send_command("Input.insertText", {"text": text})
        return {"status": "ok", "selector": selector, "chars": len(text)}

    def enable_behavioral(self, profile: Any = None) -> None:
        """Enable the behavioral engine for this CDPClient.

        When enabled, ``click()`` and ``type_text()`` automatically use
        human-like input patterns (mouse trajectory, dwell/flight timing).
        If no profile is given, a default HumanProfile is used.
        """
        from behavioral_engine import BehavioralEngine, HumanProfile

        if profile is None:
            profile = HumanProfile()
        self._behavioral = BehavioralEngine(self, profile=profile)

    async def screenshot(self, quality: int = 0) -> dict:
        """Take viewport screenshot, return base64 JPEG.

        Quality: 0 = auto (adjusts based on page size), 1-100 = explicit.
        Auto-quality saves 30-50% bandwidth on simple pages.
        """
        await self._activate_current()
        if quality == 0:
            # Auto-quality: detect page complexity
            info = await self.evaluate(
                "(function(){return {textLen:(document.body?.innerText||'').length,"
                "imgs:document.images.length,els:document.querySelectorAll('*').length}})()"
            )
            r = info.get("result", {}) if info.get("status") == "ok" else {}
            el_count = r.get("els", 1000) if r else 1000
            # Simple page (few elements) → lower quality still looks good
            quality = 85 if el_count > 500 else 60
        result = await self._send_command("Page.captureScreenshot", {
            "format": "jpeg", "quality": min(quality, 95), "fromSurface": True,
        })
        data = result.get("data", "")
        return {"status": "ok", "data": data, "format": "jpeg", "size": len(data)}

    async def get_page_text(self) -> dict:
        """Extract main text content from page."""
        await self._activate_current()
        result = await self.evaluate(
            "document.body ? document.body.innerText.substring(0, 10000) : 'no body'"
        )
        text = result.get("result", "") or ""
        return {"status": "ok", "text": text, "length": len(text)}

    async def wait_for_ready(self, timeout: int = 30, quiet_ms: int = 800) -> dict:
        """Wait until the page is *ready*: network idle + stable DOM.

        Polls network idle (no requests for *quiet_ms*) and DOM stability
        (body text stops changing).  Returns the final page text so callers
        never need a separate read.  This replaces the manual ``sleep`` dance
        agents currently do after navigate/submit.
        """
        await self._activate_current()
        deadline = time.monotonic() + timeout
        last_text = ""
        stable_for = 0.0
        try:
            while time.monotonic() < deadline:
                try:
                    await self.wait_for_network_idle(timeout=3, quiet_ms=quiet_ms)
                except (CDPError, websockets.exceptions.WebSocketException, OSError, TimeoutError) as exc:
                    logger.debug("network idle: %s", exc)
                res = await self.evaluate(
                    "document.body ? document.body.innerText.substring(0, 2000) : ''"
                )
                text = res.get("result", "") or ""
                if text and text == last_text:
                    stable_for += 0.5
                    if stable_for >= 1.5:
                        break
                else:
                    stable_for = 0.0
                    last_text = text
                await asyncio.sleep(0.5)
        except (CDPError, websockets.exceptions.WebSocketException, OSError, TimeoutError) as exc:
            logger.debug("waitForStableContent: %s", exc)
        # Final read
        res = await self.evaluate(
            "document.body ? document.body.innerText.substring(0, 10000) : ''"
        )
        text = res.get("result", "") or ""
        return {"status": "ok", "ready": True, "text": text, "length": len(text)}

    async def get_main_content(self) -> dict:
        """Extract the *main* content, filtering nav/sidebar/footer noise.

        Picks the best content container (``<main>``, ``[role=main]``,
        ``article``, or the largest text block) and returns its innerText —
        far cleaner context for LLMs than full-page text.
        """
        await self._activate_current()
        js = r"""
(function() {
  function score(el) {
    if (!el || el.offsetParent === null) return -1;
    var txt = (el.innerText || "").trim();
    if (txt.length < 200) return -1;
    var nav = el.closest("nav, header, footer, aside, [role=navigation]");
    if (nav) return -1;
    var kids = el.querySelectorAll("main, [role=main], article");
    if (kids.length) return -1;  // a wrapper — prefer its children
    return txt.length;
  }
  var best = null, bestScore = -1;
  var candidates = document.querySelectorAll("main, [role=main], article, [class*=content], [class*=article], [id*=content]");
  candidates.forEach(function(el) {
    var s = score(el);
    if (s > bestScore) { bestScore = s; best = el; }
  });
  if (!best) {
    // Fallback: largest text block in body
    var all = document.querySelectorAll("div, section, p");
    all.forEach(function(el) {
      var s = score(el);
      if (s > bestScore) { bestScore = s; best = el; }
    });
  }
  if (!best) return {found: false, text: document.body ? document.body.innerText.substring(0, 5000) : ""};
  return {found: true, selector: (best.tagName || "").toLowerCase(), text: best.innerText.substring(0, 10000)};
})()
"""
        result = await self.evaluate(js)
        data = result.get("result", {})
        if isinstance(data, str):
            import json as _json

            try:
                data = _json.loads(data)
            except (json.JSONDecodeError, ValueError):
                data = {"found": False, "text": data}
        text = data.get("text", "") if isinstance(data, dict) else ""
        return {
            "status": "ok",
            "found": data.get("found", False) if isinstance(data, dict) else False,
            "selector": data.get("selector", "") if isinstance(data, dict) else "",
            "text": text,
            "length": len(text),
        }

    # ─── Context-efficient extractors ─────────────────────────────

    async def get_page_headline(self) -> dict:
        """Extract the page's main headline (h1, or first large heading)."""
        await self._activate_current()
        result = await self.evaluate(
            """(function(){
              var h1 = document.querySelector('h1');
              if (h1 && h1.innerText.trim()) return h1.innerText.trim().substring(0, 300);
              var hs = document.querySelectorAll('h1, h2');
              for (var i=0;i<hs.length;i++){ var t=(hs[i].innerText||'').trim(); if(t) return t.substring(0,300); }
              return '';
            })()"""
        )
        text = result.get("result", "") or ""
        return {"status": "ok", "headline": text}

    async def get_page_links(self, limit: int = 50) -> dict:
        """Extract visible links (text + href) — capped, deduped."""
        await self._activate_current()
        js = f"""(function(){{
          var out = []; var seen = {{}};
          var as = document.querySelectorAll('a[href]');
          for (var i=0;i<as.length && out.length<{int(limit)};i++){{
            var a = as[i];
            if (a.offsetParent === null) continue;
            var t = (a.innerText||'').trim().substring(0,120);
            var h = a.href;
            if (!t || !h || seen[h]) continue;
            seen[h] = 1;
            out.push({{text: t, href: h}});
          }}
          return out;
        }})()"""
        result = await self.evaluate(js)
        links = result.get("result", []) or []
        if isinstance(links, str):
            import json as _json

            try:
                links = _json.loads(links)
            except (json.JSONDecodeError, ValueError):
                links = []
        return {"status": "ok", "count": len(links), "links": links}

    async def get_page_forms(self) -> dict:
        """Extract form fields (label, name, type, placeholder) without the
        heavy full-page analysis."""
        await self._activate_current()
        js = r"""(function(){
          var out = [];
          var fs = document.querySelectorAll('input, textarea, select');
          for (var i=0;i<fs.length;i++){
            var f = fs[i];
            if (f.offsetParent === null) continue;
            var label = '';
            if (f.labels && f.labels[0]) label = f.labels[0].innerText.trim();
            if (!label && f.id) { var l = document.querySelector('label[for="'+f.id+'"]'); if (l) label = l.innerText.trim(); }
            out.push({
              name: f.name || '',
              type: f.type || f.tagName.toLowerCase(),
              placeholder: f.placeholder || '',
              label: label.substring(0, 100),
              required: f.required === true
            });
          }
          return out;
        })()"""
        result = await self.evaluate(js)
        fields = result.get("result", []) or []
        if isinstance(fields, str):
            import json as _json

            try:
                fields = _json.loads(fields)
            except (json.JSONDecodeError, ValueError):
                fields = []
        return {"status": "ok", "count": len(fields), "fields": fields}

    async def get_page_table(self) -> dict:
        """Extract the first/largest table as rows (for data-heavy pages)."""
        await self._activate_current()
        js = r"""(function(){
          var tables = document.querySelectorAll('table');
          if (!tables.length) return {found: false, rows: []};
          var best = tables[0], bestLen = 0;
          for (var i=0;i<tables.length;i++){
            var len = tables[i].innerText.length;
            if (len > bestLen) { bestLen = len; best = tables[i]; }
          }
          var rows = [];
          var trs = best.querySelectorAll('tr');
          for (var r=0;r<trs.length && rows.length<200;r++){
            var cells = [];
            var tds = trs[r].querySelectorAll('th, td');
            for (var c=0;c<tds.length;c++){ cells.push((tds[c].innerText||'').trim().substring(0,200)); }
            if (cells.length) rows.push(cells);
          }
          return {found: true, rows: rows};
        })()"""
        result = await self.evaluate(js)
        data = result.get("result", {})
        if isinstance(data, str):
            import json as _json

            try:
                data = _json.loads(data)
            except (json.JSONDecodeError, ValueError):
                data = {"found": False, "rows": []}
        return {
            "status": "ok",
            "found": data.get("found", False) if isinstance(data, dict) else False,
            "rows": data.get("rows", []) if isinstance(data, dict) else [],
            "row_count": len(data.get("rows", [])) if isinstance(data, dict) else 0,
        }

    # ─── NEW: Full page screenshot ───────────────────────────────

    async def full_page_screenshot(self, quality: int = 0) -> dict:
        """
        Capture full-page screenshot by scrolling and stitching.

        Uses CDP to capture the full rendered page (everything scrollable).
        Quality: 0 = auto (adjusts based on page complexity).
        """
        await self._activate_current()
        if quality == 0:
            info = await self.evaluate(
                "document.querySelectorAll('*').length"
            )
            el_count = info.get("result", 1000) if info.get("status") == "ok" else 1000
            quality = 85 if el_count > 500 else 60
        # Get full page dimensions
        dims = await self.evaluate(
            "(function() { return {"
            "  width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth, document.documentElement.clientWidth),"
            "  height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight, document.documentElement.clientHeight)"
            "}; })()"
        )
        if dims.get("status") == "error":
            return dims
        d = dims.get("result", {})
        viewport = await self.evaluate(
            "(function() { return {w: window.innerWidth, h: window.innerHeight}; })()"
        )
        vp = viewport.get("result", {})

        width = int(d.get("width", 1024))
        height = int(d.get("height", 768))
        vh = int(vp.get("h", 768))

        # Set device metrics to full page height
        await self._send_command("Emulation.setDeviceMetricsOverride", {
            "width": min(width, 1920),
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": False,
        })

        # Now capture
        result = await self._send_command("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": quality,
            "fromSurface": True,
            "captureBeyondViewport": True,
        })

        # Restore viewport
        await self._send_command("Emulation.setDeviceMetricsOverride", {
            "width": min(width, 1280),
            "height": vh,
            "deviceScaleFactor": 1,
            "mobile": False,
        })

        data = result.get("data", "")
        return {"status": "ok", "data": data, "format": "jpeg", "size": len(data),
                "page_width": width, "page_height": height}

    # ─── NEW: Element screenshot ──────────────────────────────────

    async def element_screenshot(self, selector: str, quality: int = 0) -> dict:
        """Capture screenshot of a specific element.

        Quality: 0 = auto (adjusts based on element size).
        """
        await self._activate_current()
        if quality == 0:
            quality = 75  # default auto quality for elements
        js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return null;"
            f"  const r = el.getBoundingClientRect();"
            f"  return {{x: r.x, y: r.y, w: r.width, h: r.height}};"
            f"}})()"
        )
        result = await self.evaluate(js)
        rect = result.get("result")
        if not rect:
            return {"status": "error", "error": f"Element not found: {selector}"}

        clip = await self._send_command("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": quality,
            "clip": {
                "x": rect["x"], "y": rect["y"],
                "width": rect["w"], "height": rect["h"],
                "scale": 1,
            },
        })
        data = clip.get("data", "")
        return {"status": "ok", "data": data, "format": "jpeg", "size": len(data),
                "selector": selector, "rect": rect}

    # ─── NEW: PDF export ──────────────────────────────────────────

    async def pdf(self, options: dict | None = None) -> dict:
        """Generate PDF of current page.

        Options: landscape, printBackground, paperWidth, paperHeight,
                 marginTop, marginBottom, marginLeft, marginRight, scale
        """
        await self._activate_current()
        opts = {
            "printBackground": True,
            "preferCSSPageSize": True,
            "landscape": False,
            "paperWidth": 8.27,
            "paperHeight": 11.69,
            "marginTop": 0.4,
            "marginBottom": 0.4,
            "marginLeft": 0.4,
            "marginRight": 0.4,
            "scale": 1.0,
        }
        if options:
            opts.update(options)
        result = await self._send_command("Page.printToPDF", opts)
        data = result.get("data", "")
        return {"status": "ok", "data": data, "format": "pdf", "size": len(data)}

    # ─── NEW: File upload via CDP ──────────────────────────────────

    async def upload_files(self, selector: str, file_paths: list[str]) -> dict:
        """Upload files by setting the value of a file input element.

        *selector* is a CSS selector for ``<input type="file">``.
        *file_paths* are absolute paths to the files on the local machine.

        Uses the CDP ``DOM.setFileInputFiles`` method which bypasses the
        browser's file dialog — works even when the picker is hidden.
        """
        await self._activate_current()
        # Find the element node via Runtime
        find_js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return null;"
            f"  if (el.tagName !== 'INPUT' || (el.type !== 'file' && !el.getAttribute('capture')))"
            f"    return null;"
            f"  // Resolve backend node ID for CDP"
            f"  return 1;"
            f"}})()"
        )
        result = await self.evaluate(find_js)
        if result.get("status") == "error" or result.get("result") is None:
            return {"status": "error", "error": f"File input not found: {selector}"}

        # Get backend node ID from the element
        _get_node_js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  const backend = window.__backendNodeId;"
            f"  return 1;"
            f"}})()"
        )

        # Use DOM.querySelector to get the backend node ID
        doc_result = await self._send_command("DOM.getDocument", {"depth": 0})
        doc_node_id = doc_result.get("root", {}).get("nodeId", 0)

        query_result = await self._send_command("DOM.querySelector", {
            "nodeId": doc_node_id,
            "selector": selector,
        })
        node_id = query_result.get("nodeId", 0)
        if not node_id:
            return {"status": "error", "error": f"Element not found via DOM: {selector}"}

        # Set file input files using CDP
        await self._send_command("DOM.setFileInputFiles", {
            "nodeId": node_id,
            "files": file_paths,
        })

        # Fire change event for JS frameworks
        await self.evaluate(
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (el) el.dispatchEvent(new Event('change', {{bubbles: true}}));"
            f"}})()"
        )

        return {
            "status": "ok",
            "selector": selector,
            "files": file_paths,
            "count": len(file_paths),
        }

    # ─── NEW: Dropdown select via label or value ─────────────────

    async def form_select(self, by: str, text_or_value: str, option_value: str | None = None) -> dict:
        """Select an option from a <select> dropdown.

        ``by`` is one of:
        - ``\"label\"`` — finds the select by a visible label text, selects option by visible text
        - ``\"name\"`` — finds the select by name attribute
        - ``\"selector\"`` — finds the select by CSS selector

        ``text_or_value`` — label text, name, or CSS selector (depending on ``by``).
        ``option_value`` — optional: if provided, selects by ``option.value`` instead of option text.

        Examples:
          form_select(\"label\", \"Country\", \"Hungary\")
            → finds <select> whose <label> contains \"Country\", selects the <option> with text \"Hungary\"

          form_select(\"selector\", \"#country\", \"HU\")
            → uses CSS selector ``#country``, selects <option value=\"HU\">
        """
        await self._activate_current()

        # Build the JS to find and set the select
        js = f"""
(function() {{
  const by = {json.dumps(by)};
  const target = {json.dumps(text_or_value)};
  const optVal = {json.dumps(option_value)};

  // Find the <select> element
  let select = null;
  if (by === "label") {{
    const labels = document.querySelectorAll("label");
    const low = target.toLowerCase().trim();
    for (let lbl of labels) {{
      const t = (lbl.textContent || "").toLowerCase().trim();
      if (t === low || t.includes(low)) {{
        const inputId = lbl.getAttribute("for");
        if (inputId) {{
          const el = document.getElementById(inputId);
          if (el && el.tagName === "SELECT") {{ select = el; break; }}
        }}
        // Check parent for select
        const parent = lbl.closest(".form-group, .field, div");
        if (parent) {{
          const sel = parent.querySelector("select");
          if (sel) {{ select = sel; break; }}
        }}
      }}
    }}
  }} else if (by === "name") {{
    select = document.querySelector("select[name=" + JSON.stringify(target) + "]");
  }} else if (by === "selector") {{
    select = document.querySelector(target);
  }}

  if (!select) {{
    // Search inside same-origin iframes
    const iframes = document.querySelectorAll("iframe");
    for (let ifr of iframes) {{
      let doc = null;
      try {{ doc = ifr.contentDocument || ifr.contentWindow?.document; }} catch(e) {{}}
      if (!doc) continue;
      if (by === "label") {{
        const labels = doc.querySelectorAll("label");
        const low2 = target.toLowerCase().trim();
        for (let lbl of labels) {{
          const t = (lbl.textContent || "").toLowerCase().trim();
          if (t === low2 || t.includes(low2)) {{
            const inputId = lbl.getAttribute("for");
            if (inputId) {{
              const el = doc.getElementById(inputId);
              if (el && el.tagName === "SELECT") {{ select = el; break; }}
            }}
            const parent = lbl.closest(".form-group, .field, div");
            if (parent) {{
              const sel = parent.querySelector("select");
              if (sel) {{ select = sel; break; }}
            }}
          }}
        }}
      }} else if (by === "name") {{
        select = doc.querySelector("select[name=" + JSON.stringify(target) + "]");
      }} else if (by === "selector") {{
        select = doc.querySelector(target);
      }}
      if (select) break;
    }}
  }}

  if (!select) return JSON.stringify({{"status": "error", "error": "select not found: " + target}});

  // Find and select the option
  const options = Array.from(select.options);
  let found = false;
  if (optVal) {{
    // Match by value
    for (let opt of options) {{
      if (opt.value === optVal) {{
        select.value = optVal;
        found = true;
        break;
      }}
    }}
  }} else {{
    // Match by visible text
    const lowText = target.toLowerCase().trim();
    for (let opt of options) {{
      if ((opt.textContent || "").toLowerCase().trim() === lowText ||
          (opt.textContent || "").toLowerCase().trim().includes(lowText)) {{
        select.value = opt.value;
        found = true;
        break;
      }}
    }}
  }}

  if (!found) {{
    return JSON.stringify({{"status": "error", "error": "option not found: " + (optVal || target)}});
  }}

  // Fire change event for JS frameworks
  select.dispatchEvent(new Event("change", {{bubbles: true}}));
  select.dispatchEvent(new Event("input", {{bubbles: true}}));

  return JSON.stringify({{
    "status": "ok",
    "select_name": select.name || "",
    "select_id": select.id || "",
    "selected_value": select.value,
    "selected_text": select.options[select.selectedIndex].textContent,
  }});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"status": "error", "error": f"parse failed: {str(raw)[:200]}"}
        return data

    # ─── v0.8: Simplified dropdown select ───────────────────────────

    async def dropdown_select(self, label: str, option: str | None = None,
                               option_value: str | None = None,
                               timeout: int = 5) -> dict:
        """Simplified dropdown selection by label text.

        Delegates to form_select with by='label'.
        Either ``option`` (visible text) or ``option_value`` (value attribute) is used.
        Returns ``{\"status\": \"ok\", \"value\": \"<selected>\"}``.
        """
        value = option if option else option_value
        if value is None:
            return {"status": "ok", "value": ""}
        try:
            result = await self.form_select("label", label, value)
        except (CDPError, OSError):
            return {"status": "ok", "value": str(value)}
        if isinstance(result, dict):
            selected = (result.get("selected_value") or
                       result.get("value") or
                       str(value))
            return {"status": "ok", "value": selected}
        return {"status": "ok", "value": str(value)}

    # ─── NEW: Iframe text extraction ──────────────────────────────

    async def get_iframe_text(self, iframe_index: int = 0) -> dict:
        """Extract text content from a specific iframe.

        *iframe_index*: which iframe on the page (0 = first).
        Returns the innerText of the iframe's document body.
        """
        await self._activate_current()
        js = f"""
(function() {{
  const idx = {iframe_index};
  const iframes = document.querySelectorAll("iframe");
  if (idx >= iframes.length) {{
    return JSON.stringify({{"status": "error", "error": "iframe index out of range: " + idx + " / " + iframes.length}});
  }}
  const iframe = iframes[idx];
  let doc = null;
  try {{
    doc = iframe.contentDocument || iframe.contentWindow?.document;
  }} catch(e) {{
    return JSON.stringify({{"status": "error", "error": "cannot access iframe: " + e.message}});
  }}
  if (!doc) {{
    return JSON.stringify({{"status": "error", "error": "iframe document not accessible (cross-origin)"}});
  }}
  const text = doc.body ? doc.body.innerText || "" : "";
  return JSON.stringify({{
    "status": "ok",
    "url": doc.URL || "",
    "title": doc.title || "",
    "text": text.substring(0, 10000),
    "length": text.length,
  }});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"status": "error", "error": f"parse failed: {str(raw)[:200]}"}
        return data

    # ─── NEW: Switch to iframe context ────────────────────────────

    async def switch_to_iframe(self, iframe_index: int = 0) -> dict:
        """Switch the active context to a specific iframe.

        After this, commands like click, type, analyze_page will
        operate inside the iframe. Use iframe_index=-1 to switch back
        to the main page.
        """
        await self._activate_current()
        js = f"""
(function() {{
  const idx = {iframe_index};
  if (idx < 0) {{
    // Switch back to main page (top window focus)
    window.focus();
    return JSON.stringify({{"status": "ok", "context": "main"}});
  }}
  const iframes = document.querySelectorAll("iframe");
  if (idx >= iframes.length) {{
    return JSON.stringify({{"status": "error", "error": "iframe index out of range: " + idx + " / " + iframes.length}});
  }}
  const iframe = iframes[idx];
  try {{
    const iWindow = iframe.contentWindow;
    if (iWindow) {{
      // Focus the iframe's window
      iWindow.focus();
      return JSON.stringify({{
        "status": "ok",
        "context": "iframe",
        "index": idx,
        "src": iframe.src || "",
        "title": iWindow.document?.title || "",
      }});
    }}
  }} catch(e) {{
    return JSON.stringify({{"status": "error", "error": "cannot switch to iframe: " + e.message}});
  }}
  return JSON.stringify({{"status": "error", "error": "iframe window not accessible"}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"status": "error", "error": f"parse failed: {str(raw)[:200]}"}
        return data

    # ─── NEW: Page outline (heading hierarchy) ────────────────────

    async def get_page_outline(self) -> dict:
        """Extract the page's heading hierarchy (h1-h6) as a structured outline.

        Returns headings grouped by level, with each heading's position
        and following paragraph text. Useful for quickly understanding
        long document structure without reading the full text.
        """
        await self._activate_current()
        js = r"""
(function() {
  const result = {h1: [], h2: [], h3: [], h4: [], h5: [], h6: []};
  const tags = ["h1", "h2", "h3", "h4", "h5", "h6"];

  tags.forEach(function(tag) {
    document.querySelectorAll(tag).forEach(function(el) {
      if (el.offsetParent === null) return;
      const text = (el.textContent || "").trim();
      if (!text) return;

      // Get the paragraph/section text immediately following this heading
      let next = el.nextElementSibling;
      let snippet = "";
      while (next && !tags.includes(next.tagName.toLowerCase())) {
        const t = (next.textContent || "").trim();
        if (t) {
          snippet = t.substring(0, 300);
          break;
        }
        next = next.nextElementSibling;
      }

      const r = el.getBoundingClientRect();
      result[tag].push({
        text: text.substring(0, 200),
        snippet: snippet,
        x: Math.round(r.x),
        y: Math.round(r.y),
        id: el.id || "",
      });
    });
  });

  // Count total headings
  result.total = result.h1.length + result.h2.length + result.h3.length +
                 result.h4.length + result.h5.length + result.h6.length;

  // Extract meta info
  result.url = window.location.href;
  result.title = document.title;

  return JSON.stringify(result);
})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"status": "error", "error": f"parse failed: {str(raw)[:200]}"}
        return {"status": "ok", "result": data}

    async def get_cookies(self) -> dict:
        """Get all browser cookies."""
        await self._activate_current()
        result = await self._send_command("Network.getAllCookies")
        cookies = result.get("cookies", [])
        return {"status": "ok", "cookies": cookies, "count": len(cookies)}

    async def set_cookie(self, name: str, value: str, **kwargs) -> dict:
        """Set a cookie with optional domain, path, secure, httpOnly, etc."""
        await self._activate_current()
        params = {"name": name, "value": value, **kwargs}
        try:
            await self._send_command("Network.setCookie", params)
            return {"status": "ok", "cookie": {"name": name, **kwargs}}
        except CDPError as e:
            return {"status": "error", "error": str(e)}

    async def set_cookies(self, cookies: list[dict]) -> dict:
        """Bulk-import cookies into the current tab's context.

        Each cookie dict follows the CDP ``Network.CookieParam`` shape:
        ``name``, ``value``, ``domain``, ``path``, ``expires`` (epoch s),
        ``httpOnly``, ``secure``, ``sameSite``.  Used by the auth-clone
        flow to transfer a logged-in state between sessions.
        """
        if not cookies:
            return {"status": "ok", "imported": 0}
        await self._activate_current()
        try:
            await self._send_command("Network.setCookies", {"cookies": cookies})
            return {"status": "ok", "imported": len(cookies)}
        except CDPError as e:
            return {"status": "error", "error": str(e)}

    async def clear_cookies(self) -> dict:
        """Clear all browser cookies."""
        await self._activate_current()
        await self._send_command("Network.clearBrowserCookies")
        return {"status": "ok"}

    # ─── v1.27: F5 — download helper ───────────────────────────────

    async def download_file(self, url: str, download_dir: str, timeout: int = 30) -> dict:
        """Download a file into *download_dir* via the browser.

        Sets ``Browser.setDownloadBehavior`` (allow + path), navigates the
        current tab to *url*, and waits for the file to appear in
        *download_dir* (polling up to *timeout* seconds).  Returns the
        absolute path of the newest file written.
        """
        import os
        import time as _time
        from pathlib import Path

        await self._activate_current()
        try:
            await self._send_command("Browser.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": download_dir,
                "eventsEnabled": True,
            })
        except (CDPError, OSError) as exc:
            return {"status": "error", "error": f"setDownloadBehavior failed: {exc}"}
        os.makedirs(download_dir, exist_ok=True)
        before = set(Path(download_dir).iterdir()) if Path(download_dir).is_dir() else set()
        await self.navigate(url)
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            try:
                files = set(Path(download_dir).iterdir())
                new = [f for f in files if f not in before and f.is_file() and not f.name.endswith((".crdownload", ".tmp"))]
                if new:
                    newest = max(new, key=lambda f: f.stat().st_mtime)
                    return {"status": "ok", "path": str(newest),
                            "name": newest.name, "size_bytes": newest.stat().st_size}
            except OSError:
                pass
            await asyncio.sleep(0.5)
        return {"status": "error", "error": f"download timeout after {timeout}s"}

    # ─── NEW: DOM query ───────────────────────────────────────────

    async def dom_query(self, selector: str, attribute: str | None = None) -> dict:
        """Query DOM elements by CSS selector.

        Returns text content of each match, or a specific attribute if given.
        """
        await self._activate_current()
        if attribute:
            js = (
                f"Array.from(document.querySelectorAll({json.dumps(selector)})).map(el => el.getAttribute({json.dumps(attribute)}))"
            )
        else:
            js = (
                f"Array.from(document.querySelectorAll({json.dumps(selector)})).map(el => el.textContent.trim())"
            )
        result = await self.evaluate(js)
        items = result.get("result") or []
        return {"status": "ok", "selector": selector, "count": len(items), "items": items,
                "attribute": attribute}

    async def dom_click_all(self, selector: str) -> dict:
        """Click ALL elements matching a selector (e.g. all 'Load more' buttons)."""
        await self._activate_current()
        js = (
            f"Array.from(document.querySelectorAll({json.dumps(selector)})).forEach((el, i) => "
            f"  setTimeout(() => el.click(), i * 200)"
            f");"
        )
        await self.evaluate(js)
        return {"status": "ok", "selector": selector}

    # ─── NEW: Network monitoring ──────────────────────────────────

    async def start_network_monitoring(self) -> dict:
        """Start tracking network requests."""
        if not self._network_monitoring:
            await self._send_command("Network.enable")
            self._network_entries = []
            self._network_monitoring = True
        return {"status": "ok", "monitoring": True}

    async def stop_network_monitoring(self) -> dict:
        """Stop tracking network requests."""
        if self._network_monitoring:
            await self._send_command("Network.disable")
            self._network_monitoring = False
        return {"status": "ok", "monitoring": False}

    async def get_network_log(self) -> dict:
        """Get collected network requests."""
        entries = list(self._network_entries)
        return {"status": "ok", "entries": entries, "count": len(entries)}

    async def clear_network_log(self) -> dict:
        """Clear network log."""
        self._network_entries = []
        return {"status": "ok"}

    # ─── NEW: Request interception (mock API) ─────────────────────

    async def set_request_mocks(self, mocks: list[dict]) -> dict:
        """Install URL-pattern request mocks via CDP Fetch domain.

        Each mock: ``{"pattern": "regex", "status": 200, "body": "...",
        "content_type": "application/json"}``.  When a request URL matches
        the regex, the browser receives the mocked response instead of
        hitting the network (deterministic UI tests without a backend).
        """
        self._request_mocks = list(mocks)
        if not self._request_mocks:
            try:
                await self._send_command("Fetch.disable")
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("cleanup Fetch.disable: %s", exc)
            return {"status": "ok", "mocks": 0}
        if not self._fetch_enabled:
            try:
                await self._send_command("Fetch.enable", {
                    "patterns": [{"urlPattern": "*", "requestStage": "Request"}],
                    "handleAuthRequests": False,
                })
                self._fetch_enabled = True
                logger.info("Fetch.enable OK (%d mocks)", len(self._request_mocks))
            except Exception as exc:
                logger.warning("Fetch.enable failed: %s", exc)
                raise
        return {"status": "ok", "mocks": len(self._request_mocks)}

    def _match_mock(self, url: str) -> dict | None:
        """Return the first mock whose pattern regex matches *url*."""
        import re

        for m in self._request_mocks or []:
            try:
                if re.search(m.get("pattern", ""), url):
                    return m
            except re.error:
                continue
        return None

    async def _handle_fetch_paused(self, rid: str, url: str, res_type: str) -> None:
        """Fulfill or continue a paused Fetch request (runs in its own task).

        Runs outside the listener loop so ``_send_command`` can await the
        response without deadlocking the event dispatch.
        """
        import base64 as _b64

        if res_type == "Document":
            # A fő navigációt mindig átengedjük.
            try:
                await self._send_command("Fetch.continueRequest", {"requestId": rid})
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("continueRequest: %s", exc)
            return
        if self._match_block(url) and rid:
            # Blocked pattern → fail the request (network error path).
            try:
                await self._send_command("Fetch.failRequest", {
                    "requestId": rid,
                    "errorReason": "BlockedByClient",
                })
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("failRequest: %s", exc)
            return
        mock = self._match_mock(url)
        if mock is not None and rid:
            try:
                body_b64 = _b64.b64encode(str(mock.get("body", "")).encode()).decode("ascii")
                await self._send_command("Fetch.fulfillRequest", {
                    "requestId": rid,
                    "responseCode": int(mock.get("status", 200)),
                    "responseHeaders": [
                        {"name": "Content-Type",
                         "value": mock.get("content_type", "application/json")},
                    ],
                    "body": body_b64,
                })
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("fulfillRequest: %s", exc)
        elif rid:
            try:
                await self._send_command("Fetch.continueRequest", {"requestId": rid})
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("continueRequest: %s", exc)

    # ─── v1.27: F6 — network interception (block) ─────────────────

    async def set_network_block(self, patterns: list[str]) -> dict:
        """Block network requests whose URL matches any regex *patterns*.

        Uses the same Fetch domain as request mocks: matching requests are
        failed immediately (``Fetch.failRequest``) so the page sees a
        network error instead of the real response.  Useful for stubbing
        out analytics/trackers or testing error paths.
        """
        self._block_patterns = list(patterns or [])
        if not self._block_patterns:
            # No blocks left — if there are no mocks either, disable Fetch.
            if not getattr(self, "_request_mocks", None):
                try:
                    await self._send_command("Fetch.disable")
                except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                    logger.debug("cleanup Fetch.disable: %s", exc)
                self._fetch_enabled = False
            return {"status": "ok", "blocked": 0}
        if not self._fetch_enabled:
            try:
                await self._send_command("Fetch.enable", {
                    "patterns": [{"urlPattern": "*", "requestStage": "Request"}],
                    "handleAuthRequests": False,
                })
                self._fetch_enabled = True
            except Exception as exc:
                logger.warning("Fetch.enable failed (block): %s", exc)
                raise
        return {"status": "ok", "blocked": len(self._block_patterns)}

    def _match_block(self, url: str) -> bool:
        """Return True when *url* matches any block pattern."""
        import re

        for pat in getattr(self, "_block_patterns", None) or []:
            try:
                if re.search(pat, url):
                    return True
            except re.error:
                continue
        return False

    # ─── NEW: Batch script execution ──────────────────────────────

    async def execute_script(self, steps: list[dict]) -> dict:
        """
        Execute a batch of operations sequentially.

        Each step: {"action": "...", "params": {...}}

        Supported actions: navigate, click, type, eval, screenshot,
        full_page_screenshot, element_screenshot, wait, wait_for_element,
        wait_text, wait_for_navigation, scroll, get_text, pdf,
        click_text, form_fill, analyze_page, close.
        """
        results = []
        for i, step in enumerate(steps):
            action = step.get("action", "")
            params = step.get("params", {})
            try:
                if action == "navigate":
                    res = await self.navigate(params["url"])
                elif action == "click":
                    res = await self.click(params["selector"])
                elif action == "type":
                    res = await self.type_text(params["selector"], params["text"])
                elif action == "eval":
                    res = await self.evaluate(params["js"])
                elif action == "screenshot":
                    res = await self.screenshot(params.get("quality", 70))
                elif action == "full_page_screenshot":
                    res = await self.full_page_screenshot(params.get("quality", 70))
                elif action == "element_screenshot":
                    res = await self.element_screenshot(params["selector"], params.get("quality", 80))
                elif action in ("wait", "sleep"):
                    await asyncio.sleep(params.get("ms", 1000) / 1000)
                    res = {"status": "ok", "waited_ms": params.get("ms", 1000)}
                elif action == "wait_for_element":
                    res = await self.wait_for_element(
                        params["selector"],
                        params.get("timeout", 10),
                        params.get("visible", True),
                    )
                elif action == "wait_text":
                    res = await self.wait_for_text(
                        params["text"],
                        params.get("timeout", 10),
                        params.get("present", True),
                    )
                elif action == "wait_for_navigation":
                    res = await self.wait_for_navigation(
                        params.get("timeout", 10),
                    )
                elif action == "scroll":
                    await self._scroll_by(params.get("x", 0), params.get("y", 0))
                    res = {"status": "ok", "x": params.get("x", 0), "y": params.get("y", 0)}
                elif action == "click_text":
                    res = await self.click_by_text(
                        params["text"],
                        params.get("timeout", 5),
                        params.get("container_selector", None),
                        params.get("nth", 0),
                    )
                elif action == "form_fill":
                    res = await self.smart_form_fill(
                        params["fields"],
                        params.get("timeout", 5),
                    )
                elif action == "analyze_page":
                    res = await self.analyze_page()
                elif action == "click_label":
                    res = await self.click_label(
                        params["text"],
                        params.get("timeout", 5),
                    )
                elif action == "wait_for_network_idle":
                    res = await self.wait_for_network_idle(
                        params.get("timeout", 10),
                        params.get("quiet_ms", 500),
                    )
                elif action == "page_diff":
                    res = await self.page_diff(
                        params.get("previous_snapshot"),
                    )
                elif action == "upload_files":
                    res = await self.upload_files(
                        params["selector"],
                        params["files"],
                    )
                elif action == "find_element":
                    res = await self.find_element_by_text(
                        params["text"],
                        params.get("tag"),
                    )
                elif action == "get_text":
                    res = await self.get_page_text()
                elif action == "pdf":
                    res = await self.pdf(params)
                elif action == "close":
                    await self.close()
                    res = {"status": "ok", "action": "close"}
                elif action == "form_select":
                    res = await self.form_select(
                        params["by"],
                        params["text_or_value"],
                        params.get("option_value"),
                    )
                elif action == "get_iframe_text":
                    res = await self.get_iframe_text(
                        params.get("iframe_index", 0),
                    )
                elif action == "switch_to_iframe":
                    res = await self.switch_to_iframe(
                        params.get("iframe_index", 0),
                    )
                elif action == "get_page_outline":
                    res = await self.get_page_outline()
                else:
                    res = {"status": "error", "error": f"Unknown action: {action}"}
            except (CDPError, OSError) as e:
                res = {"status": "error", "error": str(e), "step": i, "action": action}
            res["step"] = i
            res["action"] = action
            results.append(res)
        return {"status": "ok", "steps": len(steps), "results": results,
                "failed": sum(1 for r in results if r.get("status") == "error")}

    async def _scroll_by(self, x: int = 0, y: int = 0):
        """Scroll page by x, y pixels."""
        await self.evaluate(f"window.scrollBy({x}, {y})")
        await asyncio.sleep(0.1)

    # ─── NEW: Session management ──────────────────────────────────

    async def session_save(self) -> dict:
        """Save browser session (cookies + localStorage)."""
        cookies_result = await self.get_cookies()
        cookies = cookies_result.get("cookies", [])

        ls_result = await self.evaluate(
            "JSON.stringify(window.localStorage || {})"
        )
        try:
            local_storage = json.loads(ls_result.get("result") or "{}")
        except (json.JSONDecodeError, TypeError):
            local_storage = {}

        # Also save sessionStorage
        ss_result = await self.evaluate(
            "JSON.stringify(window.sessionStorage || {})"
        )
        try:
            session_storage = json.loads(ss_result.get("result") or "{}")
        except (json.JSONDecodeError, TypeError):
            session_storage = {}

        session_data = {
            "cookies": cookies,
            "localStorage": local_storage,
            "sessionStorage": session_storage,
            "url": await self._get_current_url(),
        }
        return {"status": "ok", "session": session_data}

    async def session_restore(self, session_data: dict) -> dict:
        """Restore browser session (cookies + localStorage)."""
        restored = {"cookies": 0, "localStorage": 0}

        # Restore URL first
        url = session_data.get("url", "")
        if url:
            await self.navigate(url)
            await asyncio.sleep(1)

        # Restore cookies
        for cookie in session_data.get("cookies", []):
            try:
                await self.set_cookie(
                    cookie.get("name"),
                    cookie.get("value"),
                    domain=cookie.get("domain", ""),
                    path=cookie.get("path", "/"),
                    secure=cookie.get("secure", False),
                    httpOnly=cookie.get("httpOnly", False),
                )
                restored["cookies"] += 1
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("cookie restore failed: %s", exc)

        # Restore localStorage
        ls = session_data.get("localStorage", {})
        for key, value in ls.items():
            escaped_key = json.dumps(key)
            escaped_value = json.dumps(value)
            await self.evaluate(
                f"localStorage.setItem({escaped_key}, {escaped_value})"
            )
            restored["localStorage"] += 1

        # Restore sessionStorage
        ss = session_data.get("sessionStorage", {})
        for key, value in ss.items():
            escaped_key = json.dumps(key)
            escaped_value = json.dumps(value)
            await self.evaluate(
                f"sessionStorage.setItem({escaped_key}, {escaped_value})"
            )

        return {"status": "ok", "restored": restored}

    async def _get_current_url(self) -> str:
        result = await self.evaluate("window.location.href")
        return result.get("result") or ""

    # ─── NEW: Tab management ──────────────────────────────────────

    async def open_new_tab(self, url: str = "about:blank") -> dict:
        """Open a new browser tab via CDP Target.createTarget."""
        await self._activate_current()
        try:
            result = await self._send_command("Target.createTarget", {
                "url": url,
                "newWindow": False,
            })
            target_id = result.get("targetId", "")
            # Refresh tab cache so discover_tabs picks up the new tab
            self._tabs_cache = []
            return {"status": "ok", "tab_id": target_id, "url": url, "title": ""}
        except (CDPError, OSError) as exc:
            return {"status": "error", "error": f"CDP createTarget failed: {exc}"}

    async def start_recording(self, quality: int = 70) -> dict:
        """Start CDP screencast frame capture (video recording).

        Frames are collected in memory as base64 JPEGs; call
        ``stop_recording`` to get an animated GIF built from them.
        """
        self._recording_frames = []
        self._recording_quality = max(1, min(100, quality))
        await self._send_command(
            "Page.startScreencast",
            {"format": "jpeg", "quality": self._recording_quality, "maxWidth": 1280, "maxHeight": 720},
        )
        return {"status": "ok", "recording": True}

    async def stop_recording(self) -> dict:
        """Stop screencast and return an animated GIF (base64) of the frames.

        Falls back to a single JPEG when no frames were captured.
        """
        try:
            await self._send_command("Page.stopScreencast")
        except (CDPError, websockets.exceptions.WebSocketException, OSError) as exc:
            logger.debug("stopScreencast: %s", exc)
        frames = self._recording_frames or []
        self._recording_frames = None
        if not frames:
            return {"status": "ok", "frames": 0, "gif_b64": "", "format": "none"}
        import base64 as _b64
        from io import BytesIO

        from PIL import Image

        images = []
        for f_b64 in frames:
            try:
                img = Image.open(BytesIO(_b64.b64decode(f_b64))).convert("RGB")
                images.append(img)
            except (OSError, ValueError) as exc:
                logger.debug("frame decode: %s", exc)
        if not images:
            return {"status": "ok", "frames": len(frames), "gif_b64": "", "format": "none"}
        # Minden frame 2.5 fps-re (400ms) — kompakt GIF
        buf = BytesIO()
        images[0].save(
            buf, format="GIF", save_all=True, append_images=images[1:],
            duration=400, loop=0, optimize=True,
        )
        gif_b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
        return {"status": "ok", "frames": len(images), "gif_b64": gif_b64, "format": "gif"}

    async def close_tab(self, tab_id: str) -> dict:
        """Close a browser tab via the CDP HTTP endpoint.

        Uses the HTTP ``/json/close/{tab_id}`` endpoint which needs no
        WebSocket — so it works even when the WS connection is gone.
        Activates the current tab first (consistent tab-lifecycle order).
        """
        await self._activate_current()
        import httpx

        base = self.cdp_http_url.rstrip("/")
        async with httpx.AsyncClient(timeout=5.0) as hclient:
            resp = await hclient.get(f"{base}/json/close/{tab_id}")
            resp.raise_for_status()
        return {"status": "ok", "tab_id": tab_id}

    async def get_tabs(self) -> list[dict]:
        """List open page tabs with titles and URLs."""
        tabs = await self.discover_tabs()
        pages = [t for t in tabs if t.get("type") == "page"]
        return [
            {
                "id": t["id"],
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "active": t["id"] == self._active_tab_id,
            }
            for t in pages
        ]

    async def switch_tab(self, tab_id: str) -> dict:
        """Switch to a different tab by target ID.

        Auto-refreshes tab cache on stale-ID miss.
        """
        tabs = await self.discover_tabs()
        target = next((t for t in tabs if t["id"] == tab_id), None)
        if not target:
            # Cache miss — force fresh discovery and retry once
            self._tabs_cache = []
            self._tabs_cache_ts = 0
            tabs = await self.discover_tabs()
            target = next((t for t in tabs if t["id"] == tab_id), None)
        if not target:
            raise CDPError(f"Tab not found: {tab_id}")
        await self.connect_to_target(tab_id)
        await self._activate_current()
        return {"status": "ok", "tab_id": tab_id, "title": target.get("title", "")}

    async def connect_to_target(self, tab_id: str) -> dict:
        """Open a fresh WebSocket to an existing page target (tab).

        Unlike :meth:`switch_tab` this does not activate the tab in the
        foreground; it only attaches a CDP session.  Used by the session
        registry so every client can hold its own connection to its own tab
        without stealing focus from other agents.
        """
        tabs = await self.discover_tabs()
        target = next((t for t in tabs if t["id"] == tab_id), None)
        if not target:
            raise CDPError(f"Tab not found: {tab_id}")
        if self._ws:
            try:
                await self._ws.close()
            except (websockets.exceptions.WebSocketException, OSError) as exc:
                logger.debug("cleanup: %s", exc)
        ws_url = target["webSocketDebuggerUrl"]
        self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        self._target_id = tab_id
        self._active_tab_id = tab_id
        self._ws_tab_id = tab_id
        self._connected = True
        self._message_id = 0
        self._pending = {}
        asyncio.create_task(self._listener())
        await self._send_command("Page.enable")
        await self._send_command("Runtime.enable")
        self._apply_stealth_patches()
        return {"status": "ok", "target_id": tab_id, "cdp_url": ws_url}

    # ─── Multi-tab scan (no tab switch needed) ─────────────────────

    async def get_tab_content_direct(self, target_id: str) -> dict:
        """Extract page text from any tab WITHOUT switching to it.

        Uses a temporary CDP WS connection to Runtime.evaluate
        directly on the target.  Much faster than switch + read.
        Returns partial data on timeout / error.
        """
        client = await self._get_http_client()
        try:
            resp = await client.get(f"{self.cdp_http_url}/json", timeout=5.0)
            all_targets = resp.json()
        except (httpx.HTTPError, OSError) as e:
            return {"status": "error", "error": f"fetch targets: {e}"}

        target = next((t for t in all_targets if t["id"] == target_id), None)
        if not target:
            return {"status": "error", "error": f"Target not found: {target_id}"}
        ws_url = target.get("webSocketDebuggerUrl", "")
        if not ws_url:
            return {"status": "error", "error": "No WS URL"}

        try:
            ws = await asyncio.wait_for(
                websockets.connect(ws_url, max_size=50 * 1024 * 1024, open_timeout=5),
                timeout=8,
            )
        except (websockets.exceptions.WebSocketException, OSError, TimeoutError) as e:
            return {"status": "error", "error": f"WS connect: {e}", "target_id": target_id}

        mid = 1
        pending = {}

        async def _send(method, params=None):
            """Send a CDP command and wait for response."""
            nonlocal mid
            if params is None:
                params = {}
            f = asyncio.get_event_loop().create_future()
            pending[mid] = f
            try:
                await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
                mid += 1
                async with asyncio.timeout(6):
                    async for raw in ws:
                        r = json.loads(raw)
                        if r.get("id") in pending:
                            pending.pop(r["id"]).set_result(r)
                            break
                    return await asyncio.wait_for(f, timeout=5)
            except TimeoutError:
                pending.pop(mid - 1, None)
                return {"error": "timeout", "method": method}
            except (CDPError, websockets.exceptions.WebSocketException, OSError) as e:
                pending.pop(mid - 1, None)
                return {"error": str(e), "method": method}

        async def _eval(expr, timeout=6):
            """Evaluate JS and return result."""
            r = await _send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return r

        try:
            async with asyncio.timeout(12):
                # Step 1: Activate the target to wake it from discarding
                await _send("Target.activateTarget", {"targetId": target_id})

                # Step 2: Small delay for the tab to initialize
                await asyncio.sleep(0.3)

                # Step 3: Now evaluate JS
                t_res = await _eval("document.title")
                title = ""
                if isinstance(t_res, dict):
                    title = t_res.get("result", {}).get("result", {}).get("value", "")

                txt_res = await _eval("document.body ? document.body.innerText.substring(0,5000) : ''")
                page_text = ""
                if isinstance(txt_res, dict):
                    page_text = txt_res.get("result", {}).get("result", {}).get("value", "")

                url_res = await _eval("window.location.href")
                url = ""
                if isinstance(url_res, dict):
                    url = url_res.get("result", {}).get("result", {}).get("value", "")
        except TimeoutError:
            try:
                await ws.close()
            except (websockets.exceptions.WebSocketException, OSError):
                pass
            return {"status": "error", "error": "overall timeout", "target_id": target_id}
        except (CDPError, websockets.exceptions.WebSocketException, OSError) as e:
            try:
                await ws.close()
            except (websockets.exceptions.WebSocketException, OSError):
                pass
            return {"status": "error", "error": str(e), "target_id": target_id}
        finally:
            try:
                await ws.close()
            except (websockets.exceptions.WebSocketException, OSError):
                pass

        return {
            "status": "ok",
            "target_id": target_id,
            "title": title[:200] or "",
            "url": url or "",
            "text": (page_text or "")[:5000],
            "text_length": len(page_text or ""),
        }

    async def scan_all_tabs(self, max_concurrent: int = 5) -> list[dict]:
        """Extract content from ALL open tabs WITHOUT switching active tab.

        Scans tabs in parallel (up to *max_concurrent* at a time).
        Each tab has a hard 12s timeout — unresponsive tabs are skipped.

        Returns structured data for every page tab — title, URL, text preview.
        """
        tabs = await self.discover_tabs()
        page_tabs = [t for t in tabs if t.get("type") == "page"]

        async def _scan_one(tab):
            try:
                async with asyncio.timeout(12):
                    content = await self.get_tab_content_direct(tab["id"])
            except (CDPError, websockets.exceptions.WebSocketException, OSError, TimeoutError):
                content = {"status": "error", "error": "unexpected error", "target_id": tab["id"]}
            return {
                "id": tab["id"],
                "title": content.get("title", tab.get("title", "")),
                "url": content.get("url", tab.get("url", "")),
                "text_preview": (content.get("text") or "")[:500],
                "text_length": content.get("text_length", 0),
                "active": tab["id"] == self._active_tab_id,
                "scan_status": content.get("status", "error"),
            }

        # Run in batches to avoid overloading Chrome's WS endpoint
        results = []
        for i in range(0, len(page_tabs), max_concurrent):
            batch = page_tabs[i: i + max_concurrent]
            batch_results = await asyncio.gather(*[_scan_one(t) for t in batch])
            results.extend(batch_results)

        return results

    # ─── Page analysis: comprehensive page state ─────────────────
    async def get_accessibility_tree(self) -> dict:
        """Return Chrome's full accessibility tree with page metadata.

        The returned ``tree`` is the direct CDP payload.  Keeping transport and
        normalization separate allows the semantic layer to remain deterministic
        and independently testable.
        """
        await self._activate_current()
        await self._send_command("Accessibility.enable")
        tree = await self._send_command("Accessibility.getFullAXTree")
        meta = await self.evaluate(
            "({url: location.href, title: document.title})"
        )
        page = meta.get("result", {}) if meta.get("status") == "ok" else {}
        return {"status": "ok", "tree": tree, "page": page}

    async def click_backend_node(self, backend_node_id: int) -> dict:
        """Click a DOM node referenced by an accessibility backend node ID."""
        await self._activate_current()
        resolved = await self._send_command(
            "DOM.resolveNode", {"backendNodeId": int(backend_node_id)}
        )
        object_id = resolved.get("object", {}).get("objectId")
        if not object_id:
            raise CDPError("Could not resolve accessibility node")
        result = await self._send_command("Runtime.callFunctionOn", {
            "objectId": object_id,
            "functionDeclaration": "function(){this.scrollIntoView({block:'center'});this.click();return true;}",
            "returnByValue": True,
            "awaitPromise": True,
        })
        return {"status": "ok", "backend_node_id": backend_node_id,
                "clicked": result.get("result", {}).get("value", False)}

    async def fill_backend_node(self, backend_node_id: int, value: str) -> dict:
        """Fill a textbox/contenteditable referenced by an AX backend node ID."""
        await self._activate_current()
        resolved = await self._send_command(
            "DOM.resolveNode", {"backendNodeId": int(backend_node_id)}
        )
        object_id = resolved.get("object", {}).get("objectId")
        if not object_id:
            raise CDPError("Could not resolve accessibility node")
        result = await self._send_command("Runtime.callFunctionOn", {
            "objectId": object_id,
            "functionDeclaration": """function(value){
                this.scrollIntoView({block:'center'}); this.focus();
                if (this.isContentEditable) this.textContent=value; else this.value=value;
                this.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:value}));
                this.dispatchEvent(new Event('change',{bubbles:true}));
                this.dispatchEvent(new Event('blur',{bubbles:true}));
                return this.isContentEditable ? this.textContent : this.value;
            }""",
            "arguments": [{"value": value}],
            "returnByValue": True,
            "awaitPromise": True,
        })
        actual = result.get("result", {}).get("value")
        return {"status": "ok" if actual == value else "error",
                "backend_node_id": backend_node_id, "value": actual,
                "confirmed": actual == value}

    async def analyze_page(self) -> dict:
        """Analyze the current page and return structured information.

        Returns URL, title, visible buttons (tag, text, position, disabled, in_modal),
        open modals (with buttons, tabs, state), form fields, and visible text.

        Replaces 3-4 separate eval calls with one comprehensive response.
        """
        await self._activate_current()
        js = r"""
(function() {
  const result = {};

  // Metadata
  result.url = window.location.href;
  result.title = document.title;

  // Visible buttons
  result.buttons = [];
  const interactive = document.querySelectorAll(
    "a, button, input[type=submit], input[type=button], [role=button]"
  );
  interactive.forEach(function(el) {
    if (el.offsetParent === null) return;
    const txt = (el.textContent || "").trim();
    if (!txt && !el.getAttribute("aria-label")) return;
    const r = el.getBoundingClientRect();
    const inModal = el.closest("[class*=modal], [class*=popup], [role=dialog]") !== null;
    result.buttons.push({
      tag: el.tagName,
      text: txt.substring(0, 100) || (el.getAttribute("aria-label") || "").substring(0, 100),
      x: Math.round(r.x + r.width/2),
      y: Math.round(r.y + r.height/2),
      w: Math.round(r.width),
      h: Math.round(r.height),
      disabled: el.disabled === true,
      in_modal: inModal,
    });
  });

  // Open modals
  result.modals = [];
  const modalEls = document.querySelectorAll(
    "[class*=modal][class*=in], [class*=modal].show, [role=dialog]:not([hidden])"
  );
  modalEls.forEach(function(m) {
    if (m.offsetParent === null && !m.classList.contains("in") && !m.classList.contains("show")) return;
    // ── v0.9: Modal type heuristic ──
    var mcls = (m.className || "").toLowerCase();
    var modalType = "classic";
    if (m.getAttribute('role') === 'dialog') modalType = "aria_dialog";
    else if (mcls.indexOf('aria-dialog') >= 0) modalType = "aria_dialog";
    else if (mcls.indexOf('overlay') >= 0) modalType = "overlay";
    else if (mcls.indexOf('focus') >= 0) modalType = "focus_trap";
    // ── v0.9: Focus trap heuristic — outside elements with tabindex="-1" ──
    var isFocusTrap = false;
    var allInteractive = document.querySelectorAll(
      "a, button, input, select, textarea, [tabindex]"
    );
    for (var fi = 0; fi < allInteractive.length; fi++) {
      var outsideEl = allInteractive[fi];
      if (m.contains(outsideEl)) continue;
      if (outsideEl.getAttribute('tabindex') === '-1') { isFocusTrap = true; break; }
    }
    // ── v0.9: Interactive elements inside modal ──
    var interactiveEls = [];
    m.querySelectorAll(
      "button, a, input, select, textarea, [role=button], [tabindex]"
    ).forEach(function(ie) {
      if (ie.offsetParent === null) return;
      var iTag = ie.tagName;
      var iTxt = (ie.textContent || "").trim().substring(0, 100);
      var iType = ie.type || "";
      var iRole = ie.getAttribute('role') || "";
      var iSel = "";
      if (ie.id) iSel = "#" + CSS.escape(ie.id);
      else if (ie.name) iSel = iTag.toLowerCase() + "[name='" + CSS.escape(ie.name) + "']";
      else iSel = iTag.toLowerCase();
      interactiveEls.push({
        tag: iTag,
        text: iTxt,
        type: iType,
        role: iRole,
        selector: iSel,
      });
    });
    var info = {
      id: m.id || "",
      cls: m.className.substring(0, 80),
      role: m.getAttribute('role') || "dialog",
      modal_type: modalType,
      aria_label: m.getAttribute('aria-label') || "",
      focus_trap: isFocusTrap,
      interactive_elements: interactiveEls,
      buttons: [],
      tabs: [],
    };
    // Buttons inside modal
    m.querySelectorAll("button, a[role=button], input[type=submit]").forEach(function(b) {
      if (b.offsetParent === null) return;
      var bt = (b.textContent || "").trim() || (b.getAttribute("aria-label") || "");
      if (bt) info.buttons.push({text: bt.substring(0, 80), disabled: b.disabled === true});
    });
    // Tabs inside modal (tab-unread indicators)
    m.querySelectorAll("li").forEach(function(li) {
      var sp = li.querySelectorAll("span");
      if (sp.length >= 2) {
        info.tabs.push({
          name: (sp[0].textContent || "").trim(),
          has_unread: (sp[1].textContent || "").trim().length > 0,
        });
      }
    });
    info.modal_text = (m.textContent || "").trim().substring(0, 500);
    result.modals.push(info);
  });

  // Form fields — enhanced with label context + error detection
  result.form_fields = [];
  document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select").forEach(function(el) {
  if (el.offsetParent === null) return;
  var label = "";
  var id = el.id;
  if (id) {
    var lbl = document.querySelector("label[for='" + CSS.escape(id) + "']");
    if (lbl) label = (lbl.textContent || "").trim();
  }
  if (!label && el.parentElement) {
    var pl = el.parentElement.querySelector("label");
    if (pl) label = (pl.textContent || "").trim();
  }
  if (!label) label = el.getAttribute("placeholder") || el.getAttribute("aria-label") || el.name || "";

  // ── Section context: find the closest heading or bold text ──
  var section = "";
  var walk = el;
  for (var s = 0; s < 10; s++) {
    walk = walk.parentElement;
    if (!walk) break;
    var found = walk.querySelector("h1, h2, h3, h4, h5, h6, strong, b");
    if (found) { section = (found.textContent || "").trim().substring(0, 80); break; }
  }

  // ── Validation error detection ──
  var hasError = false;
  var errorText = "";
  // Check if the element has validation classes
  var cls = el.className;
  if (cls && (cls.indexOf("error") >= 0 || cls.indexOf("invalid") >= 0 || cls.indexOf("danger") >= 0)) {
    hasError = true;
  }
  // Check parent for error classes
  if (!hasError && walk) {
    var errorEl = walk.querySelector(".has-error, .error, .alert-danger, [class*=error], [class*=invalid], .help-block, .field-error, .form-error");
    if (errorEl) {
      hasError = true;
      errorText = (errorEl.textContent || "").trim().substring(0, 120);
    }
  }
  // Check for error text next to the field
  if (!hasError && el.nextElementSibling) {
    var ns = el.nextElementSibling;
    if (ns.className.indexOf("error") >= 0 || ns.className.indexOf("help") >= 0) {
      hasError = true;
      errorText = (ns.textContent || "").trim().substring(0, 120);
    }
  }

  result.form_fields.push({
    tag: el.tagName,
    type: el.type || "",
    name: el.name || "",
    label: label.substring(0, 80),
    value: (el.value || "").substring(0, 80),
    placeholder: (el.placeholder || "").substring(0, 40),
    section: section,
    required: el.required === true,
    checked: el.checked === true,
    has_error: hasError,
    error_text: errorText,
  });
  });

  // Alert / success / error messages
  result.alerts = [];
  document.querySelectorAll(
    ".alert, .alert-success, .alert-danger, .alert-error, .alert-info, .alert-warning, [class*=message], [class*=toast], [class*=notification]"
  ).forEach(function(a) {
    if (a.offsetParent === null) return;
    var t = (a.textContent || "").trim().substring(0, 300);
    if (t) result.alerts.push(t);
  });

  // Text summary
  result.text_preview = (document.body ? document.body.innerText.substring(0, 2000) : "");
  result.text_length = document.body ? (document.body.innerText || "").length : 0;

  // Iframe detection
  result.iframes = [];
  document.querySelectorAll("iframe").forEach(function(ifr, idx) {
    if (ifr.offsetParent === null) return;
    var src = ifr.src || "";
    var domain = "";
    try { domain = new URL(src).hostname; } catch(e) {}
    result.iframes.push({
      index: idx,
      src: src.substring(0, 200),
      domain: domain,
      title: ifr.title || "",
      width: ifr.clientWidth || 0,
      height: ifr.clientHeight || 0,
      name: ifr.name || "",
      id: ifr.id || "",
    });
  });

  // ── v0.7: Enhanced checkbox/radio state — selected_options + visual_state ──
  result.selected_options = [];
  result.visual_state = {};
  result.form_fields.forEach(function(f) {
    if (f.type === "checkbox" || f.type === "radio") {
      var vs = {checked: f.checked === true, type: f.type, value: f.value};
      result.visual_state[f.label] = vs;
      if (f.checked === true) {
        result.selected_options.push({
          label: f.label,
          type: f.type,
          value: f.value,
          checked: true,
        });
      }
    }
  });

  return JSON.stringify(result);
})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed", "raw": str(raw)[:200]}
        # ── v0.7: Ensure selected_options / visual_state even if JS result is legacy format ──
        if isinstance(data, dict) and "form_fields" in data:
            if "selected_options" not in data:
                data["selected_options"] = [
                    {"label": f["label"], "type": f["type"], "value": f["value"], "checked": True}
                    for f in data["form_fields"]
                    if f.get("type") in ("checkbox", "radio") and f.get("checked") is True
                ]
            if "visual_state" not in data:
                data["visual_state"] = {
                    f["label"]: {"checked": f.get("checked", False), "type": f.get("type", ""), "value": f.get("value", "")}
                    for f in data["form_fields"]
                    if f.get("type") in ("checkbox", "radio")
                }
        return {"status": "ok", "page": data}

    # ─── v0.7: Condensed page analysis ──────────────────────────────

    async def analyze_page_condensed(self) -> dict:
        """Analyze the current page in condensed mode — strips nav/sidebar/footer.

        Returns only main content area (main, article, [role=main], .content, #content)
        with interactive elements. Falls back to excluding navigation/sidebar elements
        when no main container is found (reports condensed_fallback: true).

        Includes enhanced v0.7 fields: selected_options, visual_state, field_count,
        button_count, checkbox_count, radio_count, modal_count.
        """
        await self._activate_current()
        js = r"""
(function() {
  var EXCLUDE = "nav, aside, footer, header, .sidebar, .breadcrumb, .menu";
  var mainContainer = document.querySelector(
    "main, article, [role=main], .content, #content"
  );
  var root = mainContainer || document.body;
  var condensed_fallback = !mainContainer;

  var result = {};
  result.url = window.location.href;
  result.title = document.title;
  result.condensed_fallback = condensed_fallback;

  // ── Helper: is element excluded? ──
  function isExcluded(el) {
    if (!condensed_fallback) return false;
    if (el.matches(EXCLUDE)) return true;
    var p = el.parentElement;
    while (p) {
      if (p.matches(EXCLUDE)) return true;
      p = p.parentElement;
    }
    return false;
  }

  // ── Visible buttons (only from main content area) ──
  result.buttons = [];
  var allInteractive = root.querySelectorAll(
    "a, button, input[type=submit], input[type=button], [role=button]"
  );
  allInteractive.forEach(function(el) {
    if (el.offsetParent === null) return;
    if (isExcluded(el)) return;
    var txt = (el.textContent || "").trim();
    if (!txt && !el.getAttribute("aria-label")) return;
    var r = el.getBoundingClientRect();
    result.buttons.push({
      tag: el.tagName,
      text: txt.substring(0, 100) || (el.getAttribute("aria-label") || "").substring(0, 100),
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      w: Math.round(r.width),
      h: Math.round(r.height),
      disabled: el.disabled === true,
    });
  });

  // ── Open modals ──
  result.modals = [];
  var modalEls = document.querySelectorAll(
    "[class*=modal][class*=in], [class*=modal].show, [role=dialog]:not([hidden])"
  );
  modalEls.forEach(function(m) {
    if (m.offsetParent === null && !m.classList.contains("in") && !m.classList.contains("show")) return;
    // ── v0.9: Modal type heuristic ──
    var mcls = (m.className || "").toLowerCase();
    var modalType = "classic";
    if (m.getAttribute('role') === 'dialog') modalType = "aria_dialog";
    else if (mcls.indexOf('aria-dialog') >= 0) modalType = "aria_dialog";
    else if (mcls.indexOf('overlay') >= 0) modalType = "overlay";
    else if (mcls.indexOf('focus') >= 0) modalType = "focus_trap";
    // ── v0.9: Focus trap heuristic ──
    var isFocusTrap = false;
    var allInteractive = document.querySelectorAll(
      "a, button, input, select, textarea, [tabindex]"
    );
    for (var fi = 0; fi < allInteractive.length; fi++) {
      var outsideEl = allInteractive[fi];
      if (m.contains(outsideEl)) continue;
      if (outsideEl.getAttribute('tabindex') === '-1') { isFocusTrap = true; break; }
    }
    // ── v0.9: Interactive elements inside modal ──
    var interactiveEls = [];
    m.querySelectorAll(
      "button, a, input, select, textarea, [role=button], [tabindex]"
    ).forEach(function(ie) {
      if (ie.offsetParent === null) return;
      interactiveEls.push({
        tag: ie.tagName,
        text: (ie.textContent || "").trim().substring(0, 100),
        type: ie.type || "",
        role: ie.getAttribute('role') || "",
        selector: ie.id ? "#" + CSS.escape(ie.id) : ie.tagName.toLowerCase(),
      });
    });
    var info = {
      id: m.id || "",
      cls: m.className.substring(0, 80),
      role: m.getAttribute('role') || "dialog",
      modal_type: modalType,
      aria_label: m.getAttribute('aria-label') || "",
      focus_trap: isFocusTrap,
      interactive_elements: interactiveEls,
      buttons: [],
    };
    m.querySelectorAll("button, a[role=button], input[type=submit]").forEach(function(b) {
      if (b.offsetParent === null) return;
      var bt = (b.textContent || "").trim() || (b.getAttribute("aria-label") || "");
      if (bt) info.buttons.push({ text: bt.substring(0, 80), disabled: b.disabled === true });
    });
    info.modal_text = (m.textContent || "").trim().substring(0, 500);
    result.modals.push(info);
  });

  // ── Form fields inside main content ──
  result.form_fields = [];
  root.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select").forEach(function(el) {
    if (el.offsetParent === null) return;
    if (isExcluded(el)) return;
    var label = "";
    var id = el.id;
    if (id) {
      var lbl = document.querySelector("label[for='" + CSS.escape(id) + "']");
      if (lbl) label = (lbl.textContent || "").trim();
    }
    if (!label && el.parentElement) {
      var pl = el.parentElement.querySelector("label");
      if (pl) label = (pl.textContent || "").trim();
    }
    if (!label) label = el.getAttribute("placeholder") || el.getAttribute("aria-label") || el.name || "";
    result.form_fields.push({
      tag: el.tagName,
      type: el.type || "",
      name: el.name || "",
      label: label.substring(0, 80),
      value: (el.value || "").substring(0, 80),
      placeholder: (el.placeholder || "").substring(0, 40),
      required: el.required === true,
      checked: el.checked === true,
    });
  });

  // ── v0.7: selected_options + visual_state ──
  result.selected_options = [];
  result.visual_state = {};
  result.form_fields.forEach(function(f) {
    if (f.type === "checkbox" || f.type === "radio") {
      result.visual_state[f.label] = {checked: f.checked === true, type: f.type, value: f.value};
      if (f.checked === true) {
        result.selected_options.push({label: f.label, type: f.type, value: f.value, checked: true});
      }
    }
  });

  // ── Text preview ──
  result.text_preview = (document.body ? document.body.innerText.substring(0, 2000) : "");
  result.text_length = document.body ? (document.body.innerText || "").length : 0;

  // ── Summary counts ──
  result.field_count = result.form_fields.length;
  result.button_count = result.buttons.length;
  result.checkbox_count = result.form_fields.filter(function(f) { return f.type === "checkbox"; }).length;
  result.radio_count = result.form_fields.filter(function(f) { return f.type === "radio"; }).length;
  result.modal_count = result.modals.length;

  return JSON.stringify(result);
})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed", "raw": str(raw)[:200]}
        # ── v0.7: Ensure selected_options / visual_state even if JS result is legacy format ──
        if isinstance(data, dict) and "form_fields" in data:
            if "selected_options" not in data:
                data["selected_options"] = [
                    {"label": f["label"], "type": f["type"], "value": f["value"], "checked": True}
                    for f in data["form_fields"]
                    if f.get("type") in ("checkbox", "radio") and f.get("checked") is True
                ]
            if "visual_state" not in data:
                data["visual_state"] = {
                    f["label"]: {"checked": f.get("checked", False), "type": f.get("type", ""), "value": f.get("value", "")}
                    for f in data["form_fields"]
                    if f.get("type") in ("checkbox", "radio")
                }
        return {"status": "ok", "page": data}

    # ─── Wait for text content ────────────────────────────────────
    async def wait_for_text(self, text: str, timeout: int = 10,
                            present: bool = True) -> dict:
        """Wait until *text* appears (or disappears) from the page.

        Polls every 300ms. Unlike wait_for_element (CSS selector based),
        this watches the visible text content of the page body.
        Use for SPAs where content updates without DOM element changes.
        """
        await self._activate_current()
        js = f"""
(async function() {{
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const present = {str(present).lower()};
  const deadline = Date.now() + {timeout * 1000};
  const poll = 300;

  while (Date.now() < deadline) {{
    const bodyText = (document.body ? document.body.innerText || "" : "").toLowerCase().trim();
    const found = bodyText.includes(low) || document.title.toLowerCase().includes(low);

    if (present && found) {{
      return JSON.stringify({{status: "ok", text: target.substring(0, 100), found: true}});
    }}

    if (!present && !found) {{
      return JSON.stringify({{status: "ok", text: target.substring(0, 100), disappeared: true}});
    }}

    await new Promise(r => setTimeout(r, poll));
  }}

  const msg = present
    ? "text not found after " + {timeout} + "s: " + target.substring(0, 50)
    : "text still present after " + {timeout} + "s: " + target.substring(0, 50);
  return JSON.stringify({{status: "error", error: msg}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed"}
        return {"status": "ok", "text": text, "timeout": timeout, "result": data}

    # ─── Wait for navigation (URL change) ─────────────────────────
    async def wait_for_navigation(self, timeout: int = 10) -> dict:
        """Wait until the page URL changes (SPA navigation).

        Stores the current URL on first call, then polls until it changes.
        Returns the new URL when detected.
        """
        await self._activate_current()
        current = await self.evaluate("window.location.href")
        old_url = current.get("result", "") or ""

        js = f"""
(async function() {{
  const oldUrl = {json.dumps(old_url)};
  const deadline = Date.now() + {timeout * 1000};
  const poll = 200;

  while (Date.now() < deadline) {{
    const newUrl = window.location.href;
    const newTitle = document.title;
    if (newUrl !== oldUrl) {{
      return JSON.stringify({{
        status: "ok",
        old_url: oldUrl,
        new_url: newUrl,
        title: newTitle,
      }});
    }}
    await new Promise(r => setTimeout(r, poll));
  }}

  return JSON.stringify({{status: "error", error: "URL did not change after " + {timeout} + "s"}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed"}
        return {"status": "ok", "timeout": timeout, "result": data}

    # ─── Wait for network idle ────────────────────────────────────

    async def wait_for_network_idle(self, timeout: int = 10,
                                     quiet_ms: int = 500) -> dict:
        """Wait until no network requests have been made for *quiet_ms*.

        Useful after form submissions or button clicks that trigger
        async AJAX calls — ensures the next action won't race with
        in-flight requests.

        Polls CDP Network events.  Returns immediately if the network
        has been quiet for *quiet_ms*; raises timeout error otherwise.
        """
        await self._activate_current()
        # Enable Network domain if not already
        await self._send_command("Network.enable")
        # Keep track of in-flight requests
        requests = set()
        deadline = time.monotonic() + timeout

        # Listen for request/response events
        async def on_request(evt):
            req_id = evt.get("params", {}).get("requestId", "")
            if req_id:
                requests.add(req_id)
        async def on_response(evt):
            req_id = evt.get("params", {}).get("requestId", "")
            if req_id and req_id in requests:
                requests.remove(req_id)
        async def on_loading(evt):
            req_id = evt.get("params", {}).get("requestId", "")
            if req_id and req_id in requests:
                requests.remove(req_id)

        self._event_callbacks.setdefault("Network.requestWillBeSent", []).append(on_request)
        self._event_callbacks.setdefault("Network.responseReceived", []).append(on_response)
        self._event_callbacks.setdefault("Network.loadingFinished", []).append(on_loading)

        try:
            while time.monotonic() < deadline:
                if not requests:
                    # Network is quiet — wait *quiet_ms* to confirm
                    await asyncio.sleep(quiet_ms / 1000)
                    if not requests:
                        return {"status": "ok", "quiet_ms": quiet_ms,
                                "idle": True}
                await asyncio.sleep(0.1)
            return {"status": "ok", "quiet_ms": quiet_ms,
                    "idle": False, "pending": len(requests)}
        finally:
            # Clean up callbacks
            for cb_list in self._event_callbacks.values():
                for cb in (on_request, on_response, on_loading):
                    if cb in cb_list:
                        cb_list.remove(cb)

    # ─── Page diff: detect what changed after an action ────────────

    async def page_diff(self, previous_snapshot: dict | None = None) -> dict:
        """Compare current page state with a previous snapshot.

        Takes an optional *previous_snapshot* (from a prior analyze_page call).
        If omitted, returns the current snapshot as a baseline for future diff
        calls (call twice: first to get baseline, second to detect changes).

        Returns added/removed buttons, new modals, new errors, text changes,
        URL change, etc.  Designed for LLM consumption — tells the agent
        *what happened* without needing to re-analyze the whole page.
        """
        current = await self.analyze_page()
        if previous_snapshot is None:
            return {"status": "ok", "baseline": True, "snapshot": current}

        prev_page = previous_snapshot.get("page") or previous_snapshot
        curr_page = current.get("page") or current

        changes = {}

        # URL change
        old_url = prev_page.get("url", "")
        new_url = curr_page.get("url", "")
        if old_url != new_url:
            changes["url_changed"] = {"from": old_url, "to": new_url}

        # Button changes (by position + text)
        old_btns = {(b["x"], b["y"]): b["text"] for b in prev_page.get("buttons", [])}
        new_btns = {(b["x"], b["y"]): b["text"] for b in curr_page.get("buttons", [])}
        added = [{"text": t, "x": x, "y": y} for (x, y), t in new_btns.items()
                 if (x, y) not in old_btns]
        removed = [{"text": t, "x": x, "y": y} for (x, y), t in old_btns.items()
                   if (x, y) not in new_btns]
        if added:
            changes["buttons_added"] = added
        if removed:
            changes["buttons_removed"] = removed

        # Modal changes
        old_modals = [m["id"] for m in prev_page.get("modals", [])]
        new_modals = [m["id"] for m in curr_page.get("modals", [])]
        opened = [m for m in curr_page.get("modals", []) if m["id"] not in old_modals]
        closed = [m for m in prev_page.get("modals", []) if m["id"] not in new_modals]
        if opened:
            changes["modals_opened"] = opened
        if closed:
            changes["modals_closed"] = closed

        # Error changes
        old_errors = [f for f in prev_page.get("form_fields", []) if f.get("has_error")]
        new_errors = [f for f in curr_page.get("form_fields", []) if f.get("has_error")]
        old_err_count = len(old_errors)
        new_err_count = len(new_errors)
        if old_err_count != new_err_count:
            changes["errors_changed"] = {"before": old_err_count, "after": new_err_count}
            errs = [f for f in new_errors if f.get("error_text")]
            if errs:
                changes["current_errors"] = [f["error_text"] for f in errs[:5]]

        # Alert changes
        old_alerts = set(prev_page.get("alerts", []))
        new_alerts = set(curr_page.get("alerts", []))
        new_alert_msgs = list(new_alerts - old_alerts)
        if new_alert_msgs:
            changes["new_alerts"] = new_alert_msgs[:5]

        # Text length change
        old_len = prev_page.get("text_length", 0)
        new_len = curr_page.get("text_length", 0)
        if old_len != new_len:
            changes["text_length_changed"] = {"from": old_len, "to": new_len}

        if not changes:
            changes["no_changes"] = True

        return {"status": "ok", "changed": len(changes) > 0
                if "no_changes" not in changes else False,
                "changes": changes, "snapshot": current}

    # ─── Deep scan: extract all sub-tabs + iframes ────────────────

    async def deep_scan_tab(self, tab_id: str | None = None) -> dict:
        """Deep-extract ALL content from a tab: sub-tabs, iframes, meta.

        Switches to the tab, then runs a comprehensive JS that:
        - Detects all sub-tab navigation links (hash, data-tab, ARIA)
        - Clicks each one and captures the visible content
        - Extracts iframe content (same-origin) or marks cross-origin
        - Returns everything as structured JSON

        Pass tab_id=None to scan the currently active tab.
        """
        # Step 1: Activate + switch to the tab if specified
        await self._activate_current()
        if tab_id and tab_id != self._active_tab_id:
            await self.switch_tab(tab_id)
        await self._activate_current()  # Re-activate after switch

        # Step 2: Run deep scan JS
        js = r"""
(function() {
  const result = {};
  const MAX_TEXT = 3000;

  // ─── HELPER: collect visible text from a container ───
  function getText(el) {
    if (!el) return "";
    var t = el.innerText || el.textContent || "";
    return t.trim().substring(0, MAX_TEXT);
  }

  // ─── SUB-TAB DETECTION ───
  var tabSources = [];

  // Pattern 1: hash-based links (a[href^="#]"])
  document.querySelectorAll("a[href^='#']").forEach(function(a) {
    var hash = a.getAttribute("href").substring(1);
    if (hash && a.offsetParent !== null && a.textContent.trim()) {
      tabSources.push({el: a, hash: hash, label: a.textContent.trim().substring(0, 40)});
    }
  });

  // Pattern 2: data-tab attributes
  document.querySelectorAll("[data-tab]").forEach(function(el) {
    var tab = el.getAttribute("data-tab");
    if (tab && el.offsetParent !== null) {
      tabSources.push({el: el, hash: tab, label: el.textContent.trim().substring(0, 40) || tab});
    }
  });

  // Pattern 3: ARIA tabs
  document.querySelectorAll("[role=tab]").forEach(function(el) {
    var controls = el.getAttribute("aria-controls");
    if (controls && el.offsetParent !== null) {
      tabSources.push({el: el, hash: controls, label: el.textContent.trim().substring(0, 40)});
    }
  });

  // Deduplicate by label
  var seen = {};
  var tabs = [];
  tabSources.forEach(function(ts) {
    if (!seen[ts.label]) {
      seen[ts.label] = true;
      tabs.push(ts);
    }
  });

  // Limit to 15 tabs max
  if (tabs.length > 15) tabs = tabs.slice(0, 15);

  result._sub_tabs = [];
  tabs.forEach(function(tab) {
    try {
      tab.el.click();
      // Busy-wait up to 1500ms for content update
      var deadline = Date.now() + 1500;
      var content = "";
      var panel = null;
      while (Date.now() < deadline) {
        var p = document.getElementById(tab.hash);
        if (p && p.textContent.trim().length > 20) {
          panel = p;
          content = getText(p);
          break;
        }
        var ap = document.querySelector("[role=tabpanel]:not([hidden])");
        if (ap && ap.textContent.trim().length > 30) {
          panel = ap;
          content = getText(ap);
          break;
        }
        var tc = document.querySelector(".tab-content.active, .tab-pane.active, [class*='tab-pane'][class*='active']");
        if (tc && tc.textContent.trim().length > 30) {
          panel = tc;
          content = getText(tc);
          break;
        }
      }
      if (!content) {
        content = getText(document.body);
      }
      result._sub_tabs.push({
        label: tab.label,
        content: content.substring(0, MAX_TEXT),
        len: content.length
      });
    } catch(e) {
      result._sub_tabs.push({label: tab.label, error: e.message});
    }
  });

  // ─── IFRAMES ───
  result._iframes = [];
  document.querySelectorAll("iframe").forEach(function(f, i) {
    try {
      var doc = f.contentDocument || (f.contentWindow ? f.contentWindow.document : null);
      var txt = "";
      var title = "";
      if (doc) {
        txt = (doc.body ? doc.body.innerText : "").substring(0, 1000);
        title = doc.title || "";
      }
      result._iframes.push({
        idx: i, src: f.src || "", id: f.id || "",
        w: f.offsetWidth, h: f.offsetHeight,
        title: title, text_preview: txt.substring(0, 300),
        text_len: txt.length,
        accessible: !!doc
      });
    } catch(e) {
      result._iframes.push({
        idx: i, src: f.src || "", id: f.id || "",
        w: f.offsetWidth, h: f.offsetHeight,
        accessible: false, error: "cross-origin"
      });
    }
  });

  // ─── CURRENT STATE ───
  var allLinks = document.querySelectorAll("a, button, [role=tab]");
  var interactive = [];
  allLinks.forEach(function(el) {
    if (el.offsetParent !== null && el.textContent.trim()) {
      var tag = el.tagName.toLowerCase();
      var txt = el.textContent.trim().substring(0, 40);
      interactive.push(tag + ":" + txt);
    }
  });

  result._meta = {
    title: document.title,
    url: window.location.href,
    tabsFound: tabs.length,
    tabsExtracted: result._sub_tabs.length,
    iframesFound: document.querySelectorAll("iframe").length,
    interactiveElements: interactive.length,
    readyState: document.readyState
  };

  return JSON.stringify(result);
})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"

        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "JS parse failed", "raw": str(raw)[:500]}

        return {
            "status": "ok",
            "tab_id": tab_id or self._active_tab_id,
            "meta": data.get("_meta", {}),
            "sub_tabs": data.get("_sub_tabs", []),
            "iframes": data.get("_iframes", []),
            "interactive": data.get("_meta", {}).get("interactiveElements", 0),
        }

    # ─── NEW: Disable/enable JS ───────────────────────────────────

    async def disable_javascript(self) -> dict:
        """Disable JavaScript execution on the page."""
        await self._send_command("Emulation.setScriptExecutionDisabled", {"value": True})
        return {"status": "ok"}

    async def enable_javascript(self) -> dict:
        """Re-enable JavaScript execution."""
        await self._send_command("Emulation.setScriptExecutionDisabled", {"value": False})
        return {"status": "ok"}

    async def add_script_to_evaluate_on_new_document(self, source: str) -> dict:
        """Register a script that runs on every new document (navigation).

        Wraps the CDP ``Page.addScriptToEvaluateOnNewDocument`` command —
        used for persistent bot-fingerprint masking (stealth patches that
        survive navigations).
        """
        result = await self._send_command(
            "Page.addScriptToEvaluateOnNewDocument", {"source": source}
        )
        return {"status": "ok", "identifier": result.get("identifier", "")}

    # ─── NEW: Misc helpers ────────────────────────────────────────

    async def get_performance_metrics(self) -> dict:
        """Get page performance metrics."""
        result = await self._send_command("Performance.getMetrics")
        metrics = result.get("metrics", [])
        return {"status": "ok", "metrics": {m["name"]: m["value"] for m in metrics}}

    # ─── Disconnect / Close ───────────────────────────────────────

    async def disconnect(self):
        """Alias for close()."""
        return await self.close()

    async def close(self):
        """Close CDP connection and clean up resources."""
        self._connected = False
        if self._network_monitoring:
            try:
                await self._send_command("Network.disable")
            except (CDPError, websockets.exceptions.WebSocketException, OSError):
                pass
            self._network_monitoring = False
        if self._ws:
            try:
                await self._ws.close()
            except (websockets.exceptions.WebSocketException, OSError):
                pass
            self._ws = None
        # Fix-1: clear WS tab binding on disconnect
        self._ws_tab_id = None
        # Fail all pending futures with CDPDisconnectedError
        exc = CDPDisconnectedError("Connection closed")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()
        self._tabs_cache = []
        self._tabs_cache_ts = 0
        # Close shared HTTP client
        if self._http_client and not self._http_client.is_closed:
            try:
                await self._http_client.aclose()
            except (OSError, httpx.HTTPError):
                pass
            self._http_client = None
        return {"status": "ok"}
        self._target_id = None

    # ─── Reconnect / retry ────────────────────────────────────────

    MAX_RECONNECT_ATTEMPTS = 3
    RECONNECT_BASE_DELAY = 1.0  # seconds

    async def _reconnect_with_backoff(self) -> dict:
        """Attempt to reconnect up to *MAX_RECONNECT_ATTEMPTS* times with
        exponential backoff.

        Returns:
            The connect result dict on success.

        Raises:
            CDPDisconnectedError: If all attempts fail.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_RECONNECT_ATTEMPTS + 1):
            try:
                return await self.connect()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.MAX_RECONNECT_ATTEMPTS:
                    delay = self.RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                    logger.info(
                        "Reconnect attempt %d/%d failed, retrying in %.1fs…",
                        attempt, self.MAX_RECONNECT_ATTEMPTS, delay,
                    )
                    await asyncio.sleep(delay)
        raise CDPDisconnectedError(
            f"Reconnect failed after {self.MAX_RECONNECT_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    async def _run_with_reconnect(self, method, *args, **kwargs) -> dict:
        """Run a CDP operation, automatically reconnecting on disconnect.

        If the operation raises ``CDPDisconnectedError``, attempts to
        reconnect via ``_reconnect_with_backoff`` and retries once.
        """
        try:
            result = await method(*args, **kwargs)
            return result
        except CDPDisconnectedError:
            await self._reconnect_with_backoff()
            return await method(*args, **kwargs)
