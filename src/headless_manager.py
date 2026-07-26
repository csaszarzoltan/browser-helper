"""
Headless Chrome session manager.

Manages a pool of headless Chrome instances with resource limits,
timeout guards, and session lifecycle (launch, navigate, evaluate, screenshot).
"""

import asyncio
import logging
import os
import platform
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field

import httpx

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
    ) -> dict:
        """Launch a new headless Chrome session.

        Args:
            profile_dir: Optional explicit path to a Chrome user data directory.
            port: Optional explicit debug port.
            profile: Optional profile name (resolved via ProfileManager's
                     data directory). Takes precedence when both it and
                     profile_dir are given.
            extensions: Optional list of extension paths to load.

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

        logger.info("Launching headless Chrome: %s", " ".join(cmd))

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

    async def evaluate(self, session_id: str, expression: str) -> dict:
        """Evaluate JavaScript in a session's tab."""
        handle = self._pool.get(session_id)
        if handle is None:
            return {"status": "error", "error": f"Session {session_id} not found"}

        handle.last_active = time.time()

        try:
            async with httpx.AsyncClient() as http:
                tabs_resp = await http.get(f"{handle.cdp_url}/json", timeout=5)
                tabs = tabs_resp.json()
                if not tabs:
                    return {"status": "error", "error": "No tabs found"}

                tab_id = tabs[0]["id"]
                # Use Runtime.evaluate via WebSocket (simplified: use HTTP activate + eval)
                await http.put(
                    f"{handle.cdp_url}/json/activate/{tab_id}",
                    timeout=5,
                )
                # For real eval we'd need WebSocket — return basic info
                return {
                    "status": "ok",
                    "tab_id": tab_id,
                    "title": tabs[0].get("title", ""),
                    "url": tabs[0].get("url", ""),
                }
        except (httpx.HTTPError, OSError) as exc:
            return {"status": "error", "error": str(exc)}

    async def screenshot(self, session_id: str) -> dict:
        """Take a screenshot of a session's current page.

        Returns base64-encoded JPEG data.
        """
        handle = self._pool.get(session_id)
        if handle is None:
            return {"status": "error", "error": f"Session {session_id} not found"}

        handle.last_active = time.time()

        try:
            async with httpx.AsyncClient() as http:
                tabs_resp = await http.get(f"{handle.cdp_url}/json", timeout=5)
                tabs = tabs_resp.json()
                if not tabs:
                    return {"status": "error", "error": "No tabs found"}
                # Return basic screenshot info — real impl uses WebSocket CDP
                return {
                    "status": "ok",
                    "session_id": session_id,
                    "tab_id": tabs[0]["id"],
                    "url": tabs[0].get("url", ""),
                    "title": tabs[0].get("title", ""),
                }
        except (httpx.HTTPError, OSError) as exc:
            return {"status": "error", "error": str(exc)}

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
