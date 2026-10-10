"""
Settings manager for browser-helper.

Persists user preferences (Chrome profile dir, debug port, Chrome path)
to a JSON file so that settings survive restarts.
"""

import json
import logging
import os
import platform
from typing import ClassVar

logger = logging.getLogger("browser-helper.settings")

# Default paths for Chrome auto-detection per platform
CHROME_PATHS_WIN = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
CHROME_PATHS_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
CHROME_PATHS_LINUX = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
]

DEFAULT_SETTINGS = {
    "chrome_profile_dir": "",
    "chrome_debug_port": 9555,
    "chrome_path": "",
    "chrome_launched_port": 0,
    "chrome_pid": 0,
    "mcp_enabled": False,
    "mcp_port": 8765,
    "domain_min_interval_sec": 4.0,
}


def _auto_detect_chrome_path() -> str:
    """Detect Chrome/Chromium/Edge/Brave on the current platform."""
    if platform.system() == "Windows":
        paths = CHROME_PATHS_WIN
    elif platform.system() == "Darwin":
        paths = CHROME_PATHS_MAC
    else:
        paths = CHROME_PATHS_LINUX

    for p in paths:
        expanded = os.path.expandvars(p)
        if os.path.exists(expanded):
            return expanded
    return ""


def _guess_data_root() -> str:
    """Return the platform-specific Chrome User Data root (parent of profiles)."""
    if platform.system() == "Windows":
        return os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    elif platform.system() == "Darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Google/Chrome"
        )
    else:
        return os.path.expanduser("~/.config/google-chrome")


class SettingsManager:
    """Load, save, and provide access to browser-helper settings."""

    # Environment overrides for an isolated agent instance (MCP server): a dedicated
    # Chrome profile and debug port, so agent sessions never attach to the user's
    # logged-in browser. Overrides live in memory only; the shared settings file is
    # left alone, so the 8020 service keeps its own profile and port.
    _ENV_OVERRIDES: ClassVar[dict[str, tuple[str, type]]] = {
        "BH_CHROME_PROFILE_DIR": ("chrome_profile_dir", str),
        "BH_CHROME_DEBUG_PORT": ("chrome_debug_port", int),
        "BH_CHROME_LAUNCHED_PORT": ("chrome_launched_port", int),
    }

    def __init__(self, path: str | None = None):
        if path is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
        self.path = path
        self._data: dict = {}
        self._overrides: dict = {}
        for env_name, (key, cast) in self._ENV_OVERRIDES.items():
            raw = os.environ.get(env_name, "").strip()
            if raw:
                self._overrides[key] = cast(raw)

        # Load or create defaults
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load settings from %s: %s", self.path, exc)
                self._data = {}
        else:
            # Auto-detect sensible defaults
            self._data = dict(DEFAULT_SETTINGS)
            detected = _auto_detect_chrome_path()
            if detected:
                self._data["chrome_path"] = detected
                logger.info("Auto-detected Chrome at: %s", detected)
            data_root = _guess_data_root()
            def_profile = os.path.join(data_root, "Default")
            if os.path.exists(def_profile):
                self._data["chrome_profile_dir"] = def_profile
            else:
                self._data["chrome_profile_dir"] = data_root
            self._save()
            logger.info("Created default settings at %s", self.path)

    def _save(self) -> None:
        """Persist current settings to disk (never from an isolated instance with overrides)."""
        if self._overrides:
            return
        try:
            dirname = os.path.dirname(self.path)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.error("Failed to save settings: %s", exc)

    # ── Accessors ────────────────────────────────────────────────

    def get(self, key: str, default=None):
        if key in self._overrides:
            return self._overrides[key]
        return self._data.get(key, default)

    def get_all(self) -> dict:
        return dict(self._data)

    def set(self, **kwargs) -> None:
        """Update one or more settings and persist."""
        self._data.update(kwargs)
        self._save()

    def update(self, d: dict) -> None:
        self._data.update(d)
        self._save()
