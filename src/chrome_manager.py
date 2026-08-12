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
import time

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


def _find_chrome_with_profile(profile_dir: str) -> int | None:
    """Find a running Chrome that already holds ``profile_dir``.

    Scans every process's ``--remote-debugging-port`` + ``--user-data-dir``
    flags. Returns the debug port of the first match, or ``None``. This
    prevents the "too many browsers" problem: launching again with the
    same profile hands off to the existing instance (Chrome's
    SingletonLock), so a second process would be useless — and if the
    port scan above missed it (e.g. TIME_WAIT), a NEW instance on a new
    port would be spawned needlessly.
    """
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,args"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except Exception:
        return None
    import re as _re

    port_re = _re.compile(r"--remote-debugging-port=(\d+)")
    for line in out.splitlines():
        if "chrome" not in line.lower() or "--user-data-dir" not in line:
            continue
        if profile_dir not in line:
            continue
        m = port_re.search(line)
        if m:
            return int(m.group(1))
    return None


def _clear_stale_singleton(profile_dir: str) -> None:
    """Remove Chrome's SingletonLock/SingletonSocket/SingletonCookie.

    These files are created by a running Chrome instance. If the instance
    crashed, the lock remains and blocks a fresh launch with the same
    profile (Chrome exits immediately thinking another instance owns it).
    Called only when no Chrome process actually holds the profile.
    """
    import glob as _glob

    for pattern in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        for path in _glob.glob(os.path.join(profile_dir, pattern)):
            try:
                if os.path.islink(path) or os.path.isfile(path):
                    os.unlink(path)
                    logger.info("Cleared stale %s: %s", pattern, path)
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning("Could not clear %s: %s", path, exc)


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
        # Soft-start tracking: when this manager launched the browser it
        # records the moment; requests arriving before the warm-up window
        # has elapsed are held back so the proxy extension is ready before
        # the first navigation (avoids the proxy-auth dialog flash).
        self._launched_at: float = 0.0
        self._warmup_sec: float = 0.0
        # Launch-in-progress flag: set while `launch()` is awaiting the CDP
        # port + extension warm-up, cleared when it returns.  The health
        # watchdog checks this before deciding to launch a "fresh" Chrome —
        # without it, a watchdog tick landing inside the warm-up window sees
        # a momentarily-unreachable port and spawns a SECOND Chrome, which
        # fights the first over the profile SingletonLock and both die
        # (observed 2026-08-11: json/new 500s, double launch storm).
        self._launch_in_progress: bool = False

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
        env_port = os.environ.get("CHROME_AUTO_PORT")
        if env_port:
            port = int(env_port)
        else:
            port = port or self.settings.get("chrome_debug_port", 9555)
        self._chrome_path = chrome_path or _find_chrome_path_from_settings(self.settings)

        if not profile_dir:
            return {
                "status": "error",
                "error": "No Chrome profile directory configured. "
                         "Set it via POST /settings or edit settings.json.",
            }

        # ── Guard against concurrent launches ──
        # If another task is already inside launch() (awaiting the CDP port
        # or the extension warm-up), do NOT start a second Chrome — wait for
        # that launch to finish and reuse its result.  Prevents the double-
        # launch storm where two instances fight over the SingletonLock.
        if self._launch_in_progress:
            logger.info("Chrome launch already in progress — waiting for it to finish")
            deadline = time.monotonic() + 30.0
            while self._launch_in_progress and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
            if _is_port_in_use(port) and _detect_chrome_on_port(port):
                self._port = port
                self.settings.set(chrome_launched_port=port)
                self._launch_in_progress = False
                return {
                    "status": "ok",
                    "message": "Chrome already running (launched concurrently)",
                    "port": port,
                    "already_running": True,
                }
        self._launch_in_progress = True

        # ── Check if Chrome is already running on this port ──
        if _is_port_in_use(port) and _detect_chrome_on_port(port):
            self._port = port
            self._pid = 0  # We don't own the process
            self.settings.set(chrome_launched_port=port)
            self._launch_in_progress = False
            return {
                "status": "ok",
                "message": "Chrome is already running",
                "port": port,
                "already_running": True,
            }

        # ── Clear stale SingletonLock before launching ──
        # If a previous Chrome instance crashed, Chrome's SingletonLock
        # (a symlink pointing at a dead PID) remains. A fresh launch with
        # the same profile sees the lock, assumes another instance owns
        # the profile, and exits immediately — the browser never comes up
        # and CDP never answers. Only remove it when no Chrome actually
        # holds the profile (checked via process scan).
        if profile_dir and _find_chrome_with_profile(profile_dir) is None:
            _clear_stale_singleton(profile_dir)

        # ── Already running with the SAME profile on another port? ──
        # A second Chrome instance with the same --user-data-dir silently
        # hands off to the first one and exits — so a fresh launch here
        # would "start" a browser that immediately dies, or worse, the
        # auto-increment below spawns a NEW profile-less instance. Find
        # any Chrome that already holds this profile dir and reuse it.
        if profile_dir:
            existing = _find_chrome_with_profile(profile_dir)
            if existing is not None:
                self._port = existing
                self._pid = 0
                self.settings.set(chrome_launched_port=existing)
                logger.info(
                    "Chrome already running with profile %s on port %d — reusing",
                    profile_dir, existing,
                )
                self._launch_in_progress = False
                return {
                    "status": "ok",
                    "message": "Chrome already running with this profile",
                    "port": existing,
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
                self._launch_in_progress = False
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
            # Anti-bot: without this flag Chrome sets navigator.webdriver=true
            # and exposes other automation signals that sites (perplexity.ai,
            # etc.) use to block headless/automated browsers.
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
        ]

        # Headless mode: --headless=new (Chrome 112+), fallback --headless for older
        if headless:
            cmd.append("--headless=new")

        # Proxy server
        if proxy:
            cmd.append(f"--proxy-server={proxy}")

        logger.info("Launching: %s", " ".join(cmd))

        # ── X display for Chrome ──
        # The systemd unit passes --display :1 (via CHROME_DISPLAY env) so
        # Chrome can attach to the VNC X server. Without DISPLAY set in the
        # child env, Chrome exits immediately with "Missing X server or
        # $DISPLAY" — the CDP port never opens.
        child_env = os.environ.copy()
        display = os.environ.get("CHROME_DISPLAY") or self.settings.get("chrome_display") or ""
        if display:
            child_env["DISPLAY"] = display
            child_env["CHROME_DISPLAY"] = display
        # Xauthority: a systemd unit a /tmp/.Xauthority-zoltan-t hozza létre
        # (root Xauthority másolat). Enélkül a Chrome "Invalid MIT-MAGIC-
        # COOKIE-1" hibával nem tud csatlakozni az X serverhez, ha a VNC
        # újraindult (a cookie elévült).
        xauth_candidates = [
            os.environ.get("XAUTHORITY", ""),
            "/tmp/.Xauthority-zoltan",
            os.path.expanduser("~/.Xauthority"),
        ]
        for xa in xauth_candidates:
            if xa and os.path.isfile(xa):
                child_env["XAUTHORITY"] = xa
                break

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_env,
            )
        except FileNotFoundError:
            self._launch_in_progress = False
            return {
                "status": "error",
                "error": f"Chrome executable not found: {self._chrome_path}",
            }
        except Exception as exc:
            self._launch_in_progress = False
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

        # Soft-start: wait for proxy extension to initialise.
        # Chrome extensions (especially proxy switchers) need ~2-3 s after the
        # browser window appears to finish their background script initialisation,
        # load proxy lists and authenticate.  Without this delay the first
        # navigation may route through the default (non-proxy) connection.
        extension_warmup = self.settings.get("extension_warmup_sec", 10)
        if extension_warmup:
            logger.info(
                "Extension warm-up: waiting %.1fs for proxy extension init",
                extension_warmup,
            )
            await asyncio.sleep(extension_warmup)

        # Record the launch moment + warm-up window so the request path can
        # force-hold early calls (see `await_chrome_ready`).
        self._launched_at = time.monotonic()
        self._warmup_sec = float(extension_warmup or 0)

        # Save to settings
        self.settings.set(
            chrome_launched_port=actual_port,
            chrome_pid=proc.pid,
            chrome_profile_dir=profile_dir,
        )

        cdp_url = f"http://127.0.0.1:{actual_port}"
        ws_url = f"ws://127.0.0.1:{actual_port}/devtools/browser/"

        self._launch_in_progress = False
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

    async def await_chrome_ready(self, timeout: float = 20.0) -> None:
        """Block until the proxy-extension warm-up window has elapsed.

        If this manager launched Chrome (``_launched_at`` set) and the warm-up
        window has not yet passed, wait for the remainder.  This force-holds
        requests that race the soft-start so the first navigation does not
        flash the proxy-auth dialog (extension not ready yet).

        When Chrome was already running (reused from another process) the
        warm-up does not apply — the extension is long since initialised.
        """
        if self._launched_at <= 0 or self._warmup_sec <= 0:
            return
        elapsed = time.monotonic() - self._launched_at
        remain = self._warmup_sec - elapsed
        if remain > 0:
            logger.info("Chrome soft-start: holding %.1fs (warm-up)", remain)
            await asyncio.sleep(remain)

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
