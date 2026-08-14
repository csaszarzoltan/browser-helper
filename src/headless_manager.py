"""
Headless Chrome session manager.

Manages a pool of headless Chrome instances with resource limits,
timeout guards, and session lifecycle (launch, navigate, evaluate, screenshot).
"""

import asyncio
import base64
import json
import logging
import os
import platform
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
import websockets

from artifact_store import ArtifactStore
from resource_monitor import ResourceMonitor

logger = logging.getLogger("browser-helper.headless")

# ── Defaults ──────────────────────────────────────────────────────
DEFAULT_MAX_SESSIONS = 5
DEFAULT_SESSION_TIMEOUT = 300  # seconds
DEFAULT_CPU_THRESHOLD = 80.0  # percent
DEFAULT_MEMORY_LIMIT_MB = 512.0


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is already bound."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def _detect_chrome_on_port(port: int) -> bool:
    """Try CDP /json/version — if it responds it's Chrome."""
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
        return False


def _find_free_port(start: int = 19222) -> int:
    """Find a free TCP port starting from *start*."""
    port = start
    while _is_port_in_use(port) and port < start + 100:
        port += 1
    return port


def _kill_process(pid: int) -> None:
    """Kill a process by PID (cross-platform)."""
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=5, check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _find_chrome_path() -> str:
    """Auto-detect Chrome executable path."""
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    elif platform.system() == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "chrome"


@dataclass
class SessionHandle:
    """Represents a single headless Chrome session."""
    session_id: str
    chrome_pid: int
    cdp_url: str
    port: int
    created_at: float
    last_active: float
    status: str  # "active", "idle", "closing", "closed"
    profile_name: str | None = None
    resource_monitor: ResourceMonitor | None = None
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)


class SessionPool:
    """Manages concurrent headless Chrome sessions with a max limit."""

    def __init__(self, max_sessions: int = DEFAULT_MAX_SESSIONS):
        self.max_sessions = max_sessions
        self._sessions: dict[str, SessionHandle] = {}

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.status in ("active", "idle"))

    def can_launch(self) -> bool:
        return self.active_count < self.max_sessions

    def add(self, session: SessionHandle) -> None:
        self._sessions[session.session_id] = session

    def get(self, session_id: str) -> SessionHandle | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> SessionHandle | None:
        return self._sessions.pop(session_id, None)

    def all_sessions(self) -> list[SessionHandle]:
        return list(self._sessions.values())

    def active_sessions(self) -> list[SessionHandle]:
        return [s for s in self._sessions.values() if s.status in ("active", "idle")]


class HeadlessManager:
    """Manages headless Chrome sessions with resource limits and timeout guards."""

    def __init__(
        self,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        session_timeout: float = DEFAULT_SESSION_TIMEOUT,
        cpu_threshold: float = DEFAULT_CPU_THRESHOLD,
        memory_limit_mb: float = DEFAULT_MEMORY_LIMIT_MB,
        chrome_path: str | None = None,
    ):
        self.session_timeout = session_timeout
        self.cpu_threshold = cpu_threshold
        self.memory_limit_mb = memory_limit_mb
        self._chrome_path = chrome_path or _find_chrome_path()
        self._pool = SessionPool(max_sessions)
        self._timeout_task: asyncio.Task | None = None
        self.artifacts = ArtifactStore()
        self._command_id = 0

    @property
    def pool(self) -> SessionPool:
        return self._pool

    # ── Session lifecycle ─────────────────────────────────────────

    async def launch_session(
        self,
        profile_dir: str | None = None,
        port: int | None = None,
        profile: str | None = None,
        extensions: list[str] | None = None,
        proxy_url: str | None = None,
        proxy_strategy: str | None = None,
        proxy_group: str | None = None,
    ) -> dict:
        """Launch a new headless Chrome session.

        Args:
            profile_dir: Optional explicit path to a Chrome user data directory.
            port: Optional explicit debug port.
            profile: Optional profile name (resolved via ProfileManager's
                     data directory). Takes precedence when both it and
                     profile_dir are given.
            extensions: Optional list of extension paths to load.
            proxy_url: Explicit proxy URL (takes precedence over strategy).
            proxy_strategy: Rotation strategy ("round-robin", "random", "sticky", "by-tag").
            proxy_group: Tag group filter for by-tag strategy.

        Returns session info dict with session_id, port, cdp_url, etc.
        """
        if not self._pool.can_launch():
            return {
                "status": "error",
                "error": f"Max concurrent sessions ({self._pool.max_sessions}) reached.",
            }

        # Find a port
        actual_port = port or _find_free_port()
        if _is_port_in_use(actual_port):
            actual_port = _find_free_port(actual_port + 1)

        # Build Chrome command
        cmd = [
            self._chrome_path,
            f"--remote-debugging-port={actual_port}",
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            "--disable-gpu",
            "--no-sandbox",
        ]

        # Resolve profile data dir
        resolved_profile_name: str | None = profile
        if profile:
            # Lazy import to avoid circular dependency at module level
            from profile_manager import ProfileManager
            pm = ProfileManager()
            data_dir = pm.get_data_dir(profile)
            if data_dir is None:
                return {
                    "status": "error",
                    "error": f"Profile {profile!r} not found",
                }
            cmd.append(f"--user-data-dir={data_dir}")
            # If extensions weren't passed explicitly, look them up from profile
            if extensions is None:
                exts = pm.get_extensions(profile)
                if exts:
                    for ext_path in exts:
                        cmd.append(f"--load-extension={ext_path}")
        elif profile_dir:
            cmd.append(f"--user-data-dir={profile_dir}")
        else:
            # Use a temp profile dir for headless sessions
            import tempfile
            tmpdir = tempfile.mkdtemp(prefix="bh-headless-")
            cmd.append(f"--user-data-dir={tmpdir}")

        # Add explicit extensions
        if extensions and not profile:
            for ext_path in extensions:
                cmd.append(f"--load-extension={ext_path}")

        # ── Proxy resolution ─────────────────────────────
        resolved_proxy_url: str | None = None
        if proxy_url:
            resolved_proxy_url = proxy_url
        elif proxy_strategy or proxy_group:
            from proxy_manager import ProxyPool
            pool = ProxyPool()
            strategy = proxy_strategy or "round-robin"
            entry = pool.get_proxy(strategy=strategy, group=proxy_group)
            if entry:
                resolved_proxy_url = entry["url"]

        if resolved_proxy_url:
            cmd.append(f"--proxy-server={resolved_proxy_url}")

        # Redact proxy credentials in log
        _safe_cmd = []
        for arg in cmd:
            if arg.startswith("--proxy-server="):
                val = arg[len("--proxy-server="):]
                try:
                    parsed = urlparse(val)
                    if parsed.username or parsed.password:
                        netloc = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname or ""
                        val = f"{parsed.scheme}://***:***@{netloc}"
                except (ValueError, TypeError, AttributeError):  # fall through with original val if parsing fails
                    pass
                _safe_cmd.append(f"--proxy-server={val}")
            else:
                _safe_cmd.append(arg)
        logger.info("Launching headless Chrome: %s", " ".join(_safe_cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return {
                "status": "error",
                "error": f"Chrome executable not found: {self._chrome_path}",
            }
        except (httpx.HTTPError, OSError) as exc:
            return {"status": "error", "error": str(exc)}

        # Wait for CDP to be ready
        ready = False
        for _ in range(20):
            if _is_port_in_use(actual_port) and _detect_chrome_on_port(actual_port):
                ready = True
                break
            await asyncio.sleep(0.25)

        if not ready:
            _kill_process(proc.pid)
            return {
                "status": "error",
                "error": f"Chrome started but CDP not responding on port {actual_port}",
            }

        # Create session
        session_id = str(uuid.uuid4())[:8]
        now = time.time()
        handle = SessionHandle(
            session_id=session_id,
            chrome_pid=proc.pid,
            cdp_url=f"http://127.0.0.1:{actual_port}",
            port=actual_port,
            created_at=now,
            last_active=now,
            status="active",
            profile_name=resolved_profile_name,
            resource_monitor=ResourceMonitor(proc.pid),
            process=proc,
        )

        self._pool.add(handle)

        # ── Fingerprint injection (bot-detection bypass) ──────────
        # If the resolved profile carries a fingerprint_config, generate the
        # stealth scripts via FingerprintEngine and inject them into the new
        # session's page so every navigation carries the profile's fingerprint.
        if resolved_profile_name:
            try:
                from fingerprint_engine import FingerprintEngine
                from profile_manager import ProfileManager

                _pm = ProfileManager()
                _fp_cfg = _pm.get_fingerprint_config(resolved_profile_name)
                if _fp_cfg:
                    engine = FingerprintEngine()
                    engine.config = _fp_cfg
                    scripts = engine.generate_all_scripts()
                    if scripts:
                        await self._inject_fingerprint_scripts(session_id, scripts)
                        logger.info(
                            "Session %s: %d fingerprint script(s) injected (profile %r)",
                            session_id, len(scripts), resolved_profile_name,
                        )
            except Exception as exc:  # noqa: BLE001 - fingerprint is best-effort
                logger.warning("Fingerprint injection skipped: %s", exc)

        # Start timeout guard if not running
        if self._timeout_task is None or self._timeout_task.done():
            self._timeout_task = asyncio.create_task(self._timeout_guard())

        logger.info(
            "Headless session %s launched: PID=%d, port=%d",
            session_id, proc.pid, actual_port,
        )

        return {
            "status": "ok",
            "session_id": session_id,
            "port": actual_port,
            "pid": proc.pid,
            "cdp_url": handle.cdp_url,
            "proxy": resolved_proxy_url if resolved_proxy_url else None,
        }

    async def close_session(self, session_id: str) -> dict:
        """Close a headless Chrome session by ID."""
        handle = self._pool.get(session_id)
        if handle is None:
            return {"status": "error", "error": f"Session {session_id} not found"}

        handle.status = "closing"
        _kill_process(handle.chrome_pid)

        # Wait briefly for process to exit
        if handle.process:
            try:
                await asyncio.wait_for(handle.process.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError):
                pass

        handle.status = "closed"
        self._pool.remove(session_id)

        logger.info("Headless session %s closed (PID %d)", session_id, handle.chrome_pid)
        return {"status": "ok", "session_id": session_id, "killed_pid": handle.chrome_pid}

    def get_sessions(self) -> list[dict]:
        """Return info about all active sessions."""
        sessions = []
        for s in self._pool.all_sessions():
            info = {
                "session_id": s.session_id,
                "port": s.port,
                "pid": s.chrome_pid,
                "cdp_url": s.cdp_url,
                "status": s.status,
                "profile_name": s.profile_name,
                "created_at": s.created_at,
                "last_active": s.last_active,
                "age_seconds": round(time.time() - s.created_at, 1),
            }
            if s.resource_monitor:
                info["resources"] = s.resource_monitor.check_limits(
                    self.cpu_threshold, self.memory_limit_mb
                )
            sessions.append(info)
        return sessions

    # ── CDP operations via HTTP ───────────────────────────────────

    async def navigate(self, session_id: str, url: str) -> dict:
        """Navigate a session to a URL."""
        handle = self._pool.get(session_id)
        if handle is None:
            return {"status": "error", "error": f"Session {session_id} not found"}

        handle.last_active = time.time()
        handle.status = "active"

        try:
            async with httpx.AsyncClient() as http:
                # Get the first tab
                tabs_resp = await http.get(f"{handle.cdp_url}/json", timeout=5)
                tabs = tabs_resp.json()
                if not tabs:
                    return {"status": "error", "error": "No tabs found"}

                tab_ws_url = tabs[0].get("webSocketDebuggerUrl")
                if not tab_ws_url:
                    return {"status": "error", "error": "No WebSocket URL for tab"}

                # Use HTTP endpoint for navigation
                nav_resp = await http.put(
                    f"{handle.cdp_url}/json/navigate/{tabs[0]['id']}",
                    json={"url": url},
                    timeout=10,
                )
                return {"status": "ok", "result": nav_resp.json()}
        except (httpx.HTTPError, OSError) as exc:
            return {"status": "error", "error": str(exc)}

    async def _tab_websocket_url(self, handle: SessionHandle) -> str:
        async with httpx.AsyncClient() as http:
            response = await http.get(f"{handle.cdp_url}/json", timeout=5)
            response.raise_for_status()
            tabs = response.json()
        if not tabs:
            raise RuntimeError("No tabs found")
        ws_url = tabs[0].get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("No WebSocket debugger URL for tab")
        return ws_url

    async def _cdp_command(self, handle: SessionHandle, method: str, params: dict | None = None) -> dict:
        self._command_id += 1
        command_id = self._command_id
        ws_url = await self._tab_websocket_url(handle)
        async with websockets.connect(ws_url, open_timeout=5, close_timeout=2, max_size=32 * 1024 * 1024) as ws:
            await ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if message.get("id") != command_id:
                    continue
                if "error" in message:
                    raise RuntimeError(message["error"].get("message", str(message["error"])))
                return message.get("result", {})

    async def evaluate(self, session_id: str, expression: str) -> dict:
        """Evaluate JavaScript through the session tab's CDP WebSocket."""
        handle = self._pool.get(session_id)
        if handle is None:
            return {"status": "error", "code": "session_not_found", "error": f"Session {session_id} not found"}
        handle.last_active = time.time()
        try:
            result = await self._cdp_command(handle, "Runtime.evaluate", {
                "expression": expression, "returnByValue": True, "awaitPromise": True,
            })
            remote = result.get("result", {})
            if remote.get("subtype") == "error":
                return {"status": "error", "code": "javascript_error", "error": remote.get("description", "JavaScript evaluation failed")}
            return {
                "status": "ok", "session_id": session_id,
                "value": remote.get("value"), "type": remote.get("type"),
                "description": remote.get("description"),
            }
        except (OSError, TimeoutError, RuntimeError, websockets.WebSocketException) as exc:
            return {"status": "error", "code": "cdp_error", "error": str(exc)}

    async def _inject_fingerprint_scripts(
        self, session_id: str, scripts: list[str]
    ) -> dict:
        """Register fingerprint-injection scripts on the session's page.

        Uses ``Page.addScriptToEvaluateOnNewDocument`` so the scripts run on
        every future navigation (persistent bot-fingerprint masking), and
        also evaluates each script immediately on the current document.

        Args:
            session_id: The headless session to inject into.
            scripts:    List of JavaScript source strings to inject.

        Returns:
            ``{"status": "ok", "registered": n}`` or an error dict.
        """
        handle = self._pool.get(session_id)
        if handle is None:
            return {"status": "error", "code": "session_not_found",
                    "error": f"Session {session_id} not found"}
        handle.last_active = time.time()
        if not scripts:
            return {"status": "ok", "registered": 0}

        registered = 0
        errors: list[str] = []
        for script in scripts:
            try:
                # Persistent: runs on every new document (navigations)
                await self._cdp_command(
                    handle, "Page.addScriptToEvaluateOnNewDocument",
                    {"source": script},
                )
                registered += 1
            except Exception as exc:  # noqa: BLE001 - continue on per-script failure
                errors.append(str(exc))
        return {
            "status": "ok" if not errors else "partial",
            "registered": registered,
            "errors": errors,
            "session_id": session_id,
        }

    async def _apply_fingerprint_config(self, session_id: str, config: dict) -> dict:
        """Generate and inject fingerprint scripts from a config dict.

        Convenience wrapper: builds the stealth script set from a
        fingerprint config (e.g. WebGL vendor/renderer, timezone, platform)
        and injects them via :meth:`_inject_fingerprint_scripts`.
        """
        scripts: list[str] = []
        vendor = config.get("webgl_vendor") or "Google Inc. (NVIDIA)"
        renderer = config.get("webgl_renderer") or "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060)"
        _tz = config.get("timezone") or "America/New_York"
        platform = config.get("platform") or "Win32"

        if config.get("screen_width") and config.get("screen_height"):
            scripts.append(
                f"Object.defineProperty(screen, 'width', {{get: () => {config['screen_width']}}});"
                f"Object.defineProperty(screen, 'height', {{get: () => {config['screen_height']}}});"
            )
        scripts.append(
            f"Object.defineProperty(navigator, 'platform', {{get: () => '{platform}'}});"
        )
        scripts.append(
            f"(() => {{"
            f"var op = WebGLRenderingContext.prototype.getParameter;"
            f"WebGLRenderingContext.prototype.getParameter = function(p) {{"
            f"if (p === 37445) return '{vendor}';"
            f"if (p === 37446) return '{renderer}';"
            f"return op.call(this, p);}};}})()"
        )
        return await self._inject_fingerprint_scripts(session_id, scripts)

    async def screenshot(self, session_id: str, quality: int = 80) -> dict:
        """Capture a real JPEG screenshot and persist it as an artifact."""
        handle = self._pool.get(session_id)
        if handle is None:
            return {"status": "error", "code": "session_not_found", "error": f"Session {session_id} not found"}
        handle.last_active = time.time()
        try:
            result = await self._cdp_command(handle, "Page.captureScreenshot", {
                "format": "jpeg", "quality": min(max(int(quality), 1), 100), "fromSurface": True,
            })
            data = base64.b64decode(result["data"], validate=True)
            artifact = self.artifacts.put(data, "image/jpeg", ".jpg", {"session_id": session_id})
            return {"status": "ok", "session_id": session_id, "artifact": artifact}
        except (KeyError, ValueError, OSError, TimeoutError, RuntimeError, websockets.WebSocketException) as exc:
            return {"status": "error", "code": "cdp_error", "error": str(exc)}

    async def batch_screenshot(self, session_id: str, urls: list[str]) -> dict:
        """Navigate to each URL and take a screenshot.

        Returns list of results for each URL.
        """
        handle = self._pool.get(session_id)
        if handle is None:
            return {"status": "error", "error": f"Session {session_id} not found"}

        results = []
        for url in urls:
            nav_result = await self.navigate(session_id, url)
            if nav_result.get("status") == "ok":
                ss_result = await self.screenshot(session_id)
                ss_result["url"] = url
                results.append(ss_result)
            else:
                results.append({"status": "error", "url": url, "error": nav_result.get("error")})

        return {"status": "ok", "session_id": session_id, "results": results}

    # ── Health & resource check ───────────────────────────────────

    def health_check(self) -> dict:
        """Return pool stats and per-session resource usage."""
        sessions = self.get_sessions()
        active = [s for s in sessions if s["status"] in ("active", "idle")]

        return {
            "status": "ok",
            "pool": {
                "max_sessions": self._pool.max_sessions,
                "active_count": len(active),
                "total_count": len(sessions),
            },
            "limits": {
                "session_timeout": self.session_timeout,
                "cpu_threshold": self.cpu_threshold,
                "memory_limit_mb": self.memory_limit_mb,
            },
            "sessions": sessions,
        }

    # ── Timeout guard ─────────────────────────────────────────────

    async def _timeout_guard(self):
        """Background task that kills sessions exceeding timeout."""
        while True:
            await asyncio.sleep(10)  # Check every 10 seconds
            now = time.time()
            expired = []

            for session in self._pool.all_sessions():
                if session.status not in ("active", "idle"):
                    continue

                age = now - session.created_at
                if age > self.session_timeout:
                    expired.append(session.session_id)
                    continue

                # Check resource limits
                if session.resource_monitor:
                    limits = session.resource_monitor.check_limits(
                        self.cpu_threshold, self.memory_limit_mb
                    )
                    if not limits["ok"]:
                        expired.append(session.session_id)
                        logger.warning(
                            "Session %s exceeded resource limits: %s",
                            session.session_id, limits["details"],
                        )

            for sid in expired:
                logger.info("Auto-closing expired session %s", sid)
                await self.close_session(sid)

    async def shutdown(self):
        """Close all sessions and cancel timeout guard."""
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass

        for session in self._pool.all_sessions():
            await self.close_session(session.session_id)
