"""
Chrome process manager for browser-helper.

Launches and stops Chrome with remote debugging enabled, auto-detecting
a free port if the configured one is in use.
"""

import asyncio
import logging
import os
import platform
import signal
import socket
import subprocess

logger = logging.getLogger("browser-helper.chrome")

try:
    import httpx
except ImportError:
    httpx = None  # fallback: we'll try socket-based check


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is already bound on the given host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def _detect_chrome_on_port(port: int) -> bool:
    """Try to reach the CDP /json/version endpoint — if it responds it's Chrome."""
    if httpx is None:
        # Can't easily verify, just assume not-Chrome
        return False
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
        return False


def _kill_process(pid: int) -> None:
    """Kill a process by PID.  Works cross-platform."""
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                timeout=5,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _find_chrome_path_from_settings(settings) -> str:
    """Return the chrome_path from settings, or auto-detect."""
    path = settings.get("chrome_path", "")
    if path and os.path.exists(os.path.expandvars(path)):
        return os.path.expandvars(path)

    # Auto-detect
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
    elif platform.system() == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
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
        expanded = os.path.expandvars(c)
        if os.path.exists(expanded):
            return expanded
    return "chrome"  # last resort — hope it's on PATH


class ChromeManager:
    """Manages Chrome process lifecycle with CDP debugging enabled."""

    def __init__(self, settings_manager):
        self.settings = settings_manager
        self._process: asyncio.subprocess.Process | None = None
        self._pid: int = 0
        self._port: int = 0
        self._chrome_path: str = ""

    # ── Public API ───────────────────────────────────────────────

    async def launch(
        self,
        profile_dir: str | None = None,
        port: int | None = None,
        chrome_path: str | None = None,
        headless: bool = False,
        proxy: str | None = None,
    ) -> dict:
        """
        Launch Chrome with remote debugging.

        - *profile_dir* overrides the saved setting (must be a path to a
          Chrome User Data directory or a named profile dir within User Data).
        - *port* overrides the saved debug port; if busy the next free port
          is tried (up to +10).
        - *chrome_path* overrides the saved Chrome executable path.
        - *headless* when True, launches Chrome in headless mode (--headless=new).
          Falls back to --headless for Chrome < 112.
        - *proxy* when set, passes --proxy-server flag to Chrome.
        """
        # Resolve parameters: use override or fall back to saved settings
        profile_dir = profile_dir or self.settings.get("chrome_profile_dir") or ""
        port = port or self.settings.get("chrome_debug_port", 9555)
        self._chrome_path = chrome_path or _find_chrome_path_from_settings(self.settings)

        if not profile_dir:
            return {
                "status": "error",
                "error": "No Chrome profile directory configured. "
                         "Set it via POST /settings or edit settings.json.",
            }

        # ── Check if Chrome is already running on this port ──
        if _is_port_in_use(port) and _detect_chrome_on_port(port):
            self._port = port
            self._pid = 0  # We don't own the process
            self.settings.set(chrome_launched_port=port)
            return {
                "status": "ok",
                "message": "Chrome is already running",
                "port": port,
                "already_running": True,
            }

        # ── Port in use but not Chrome → find next free port ──
        actual_port = port
        if _is_port_in_use(port) and not _detect_chrome_on_port(port):
            for attempt in range(1, 11):
                candidate = port + attempt
                if not _is_port_in_use(candidate):
                    actual_port = candidate
                    break
            else:
                return {
                    "status": "error",
                    "error": f"Port {port} through {port + 10} all in use — "
                             "no free port available.",
                }
            logger.info("Port %d busy (not Chrome), trying port %d", port, actual_port)

        # ── Build launch command ──
        cmd = [
            self._chrome_path,
            f"--remote-debugging-port={actual_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
        ]

        # Headless mode: --headless=new (Chrome 112+), fallback --headless for older
        if headless:
            cmd.append("--headless=new")

        # Proxy server
        if proxy:
            cmd.append(f"--proxy-server={proxy}")

        logger.info("Launching: %s", " ".join(cmd))

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
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        self._process = proc
        self._pid = proc.pid
        self._port = actual_port

        # Wait briefly for Chrome to start CDP
        for _ in range(20):
            if _is_port_in_use(actual_port) and _detect_chrome_on_port(actual_port):
                break
            await asyncio.sleep(0.25)
        else:
            logger.warning("Chrome started but CDP not responding on port %d", actual_port)

        # Save to settings
        self.settings.set(
            chrome_launched_port=actual_port,
            chrome_pid=proc.pid,
            chrome_profile_dir=profile_dir,
        )

        cdp_url = f"http://127.0.0.1:{actual_port}"
        ws_url = f"ws://127.0.0.1:{actual_port}/devtools/browser/"

        return {
            "status": "ok",
            "port": actual_port,
            "pid": proc.pid,
            "cdp_http_url": cdp_url,
            "cdp_debugger_url": ws_url,
            "chrome_path": self._chrome_path,
            "profile_dir": profile_dir,
            "proxy": proxy if proxy else None,
        }

    async def stop(self) -> dict:
        """Gracefully stop the managed Chrome process."""
        if not self._pid and not self._port:
            return {"status": "ok", "message": "Chrome was not running (no managed process)."}

        pid = self._pid or self.settings.get("chrome_pid", 0)
        if pid:
            _kill_process(pid)

        self._process = None
        self._pid = 0
        self._port = 0
        self.settings.set(chrome_launched_port=0, chrome_pid=0)

        logger.info("Chrome process %d stopped", pid)
        return {
            "status": "ok",
            "message": "Chrome stopped",
            "killed_pid": pid,
        }

    def status(self) -> dict:
        """Return current Chrome status (without contacting CDP)."""
        port = self._port or self.settings.get("chrome_launched_port", 0)
        pid = self._pid or self.settings.get("chrome_pid", 0)

        running = False
        if port > 0 and _is_port_in_use(port):
            running = _detect_chrome_on_port(port) or True

        return {
            "running": running,
            "port": port,
            "pid": pid,
            "profile_dir": self.settings.get("chrome_profile_dir", ""),
            "chrome_path": self._chrome_path or self.settings.get("chrome_path", ""),
            "settings_path": self.settings.path,
        }
