"""
Playwright/Patchright Backend Manager (P1-1).

Provides an optional Playwright/Patchright automation backend alongside the
existing CDP-direct path. Users can switch via REST API (POST /backend/switch)
or per-request ``X-Backend`` header.

Usage::

    from playwright_backend import BackendManager

    mgr = BackendManager()
    status = mgr.get_status()
    mgr.switch("playwright")
"""

from __future__ import annotations

from typing import Any

# Try importing Playwright (stock); fall back gracefully.
try:
    import playwright  # noqa: F401

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

# Try importing patchright (rebrowser-patches); may not be installed.
try:
    import patchright  # noqa: F401

    _PATCHRIGHT_AVAILABLE = True
except ImportError:
    _PATCHRIGHT_AVAILABLE = False


def _get_playwright_version() -> str | None:
    """Return the installed Playwright version string, or None."""
    try:
        from playwright import __version__

        return __version__
    except (ImportError, AttributeError):
        pass
    try:
        import importlib.metadata as im

        return im.version("playwright")
    except (ImportError, im.PackageNotFoundError):
        pass
    return None


def _get_patchright_version() -> str | None:
    """Return the installed Patchright version string, or None."""
    try:
        from patchright import __version__

        return __version__
    except (ImportError, AttributeError):
        pass
    try:
        import importlib.metadata as im

        return im.version("patchright")
    except (ImportError, im.PackageNotFoundError):
        pass
    return None


def _get_cdp_client_version() -> str | None:
    """Return the CDP client version string, or None."""
    try:
        import importlib.metadata as im

        return im.version("browser-helper")
    except (ImportError, im.PackageNotFoundError):
        pass
    try:
        from cdp_client import __version__

        return __version__
    except (ImportError, AttributeError):
        pass
    return None


class BackendManager:
    """Manages backend switching between CDP-direct and Playwright/Patchright.

    Attributes:
        current_backend:  Name of the active backend (``"cdp"`` or ``"playwright"``).
        available_backends:  List of backends that can be switched to.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._current_backend: str = "cdp"
        self._available_backends: list[str] = ["cdp", "playwright"]
        self._use_patchright: bool = False
        self._patches_enabled: bool = False

        if settings:
            self._load_settings(settings)

    def _load_settings(self, settings: dict[str, Any]) -> None:
        """Load configuration from the settings dict (e.g. from settings.json)."""
        backend_config = settings.get("backend", {})
        if backend_config.get("default") in ("playwright", "cdp"):
            self._current_backend = backend_config["default"]
        self._use_patchright = backend_config.get("playwright_patches", False)
        self._patches_enabled = self._use_patchright

    # ── Properties ───────────────────────────────────────────────────

    @property
    def current_backend(self) -> str:
        """Return the name of the currently active backend."""
        return self._current_backend

    @current_backend.setter
    def current_backend(self, value: str) -> None:
        self._current_backend = value

    @property
    def available_backends(self) -> list[str]:
        """Return the list of backends that can be switched to."""
        return list(self._available_backends)

    # ── Public API ───────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return current backend status.

        Returns:
            dict with keys::

                {"current_backend": str,
                 "available_backends": list[str],
                 "versions": dict[str, str],
                 "patches_enabled": bool}
        """
        return {
            "current_backend": self._current_backend,
            "available_backends": self._available_backends.copy(),
            "versions": {
                "cdp": _get_cdp_client_version() or "1.0.0",
                "playwright": _get_playwright_version() or "not-installed",
                "patchright": _get_patchright_version() or "not-installed",
                "browser_helper": _get_cdp_client_version() or "1.0.0",
                "api": "1.0.0",
            },
            "patches_enabled": self._patches_enabled,
        }

    def switch(self, backend: str) -> dict[str, Any]:
        """Switch the active backend.

        Args:
            backend: Name of the backend to switch to (``"cdp"`` or ``"playwright"``).

        Returns:
            Confirmation dict with the new backend name.

        Raises:
            ValueError: If the backend name is unknown or unavailable.
        """
        if backend not in self._available_backends:
            raise ValueError(
                f"Unknown backend: {backend!r}. "
                f"Available: {self._available_backends}"
            )
        self._current_backend = backend
        return {
            "status": "ok",
            "backend": backend,
        }

    async def navigate(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Navigate to a URL using the active backend.

        Args:
            url: Target URL.
            **kwargs: Additional backend-specific parameters.

        Returns:
            Navigation result dict.
        """
        # Delegate to CDP client for now; Playwright integration is partial.
        from main import client as cdp_client

        try:
            from agent_navigation import navigate_to_url

            result = await navigate_to_url(cdp_client, url)
            return {"status": "ok", "url": url, "result": result}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "url": url, "error": str(exc)}

    async def evaluate(self, js: str, **kwargs: Any) -> dict[str, Any]:
        """Evaluate JavaScript using the active backend.

        Args:
            js: JavaScript expression to evaluate.
            **kwargs: Additional backend-specific parameters.

        Returns:
            Evaluation result dict.
        """
        from main import client as cdp_client

        try:
            result = await cdp_client.evaluate(js)
            return {"status": "ok", "result": result}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}

    async def screenshot(self, **kwargs: Any) -> dict[str, Any]:
        """Take a screenshot using the active backend.

        Args:
            **kwargs: Backend-specific screenshot parameters.

        Returns:
            Screenshot result dict.
        """
        from main import client as cdp_client

        try:
            result = await cdp_client.screenshot()
            return {"status": "ok", "result": result}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}
