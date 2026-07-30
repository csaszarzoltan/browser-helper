"""
Playwright/Patchright Backend Manager (P1-1).

Provides an optional Playwright/Patchright automation backend alongside the
existing CDP-direct path. Users can switch via REST API (POST /backend/switch)
or per-request ``X-Backend`` header.

PRE-DEV STUB — All behavioral methods raise NotImplementedError.

Usage::

    from playwright_backend import BackendManager

    mgr = BackendManager()
    status = mgr.get_status()
    mgr.switch("playwright")
"""

from __future__ import annotations

from typing import Any


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
        raise NotImplementedError("BackendManager.get_status — not implemented yet")

    def switch(self, backend: str) -> dict[str, Any]:
        """Switch the active backend.

        Args:
            backend: Name of the backend to switch to (``"cdp"`` or ``"playwright"``).

        Returns:
            Confirmation dict with the new backend name.

        Raises:
            ValueError: If the backend name is unknown or unavailable.
        """
        raise NotImplementedError("BackendManager.switch — not implemented yet")

    async def navigate(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Navigate to a URL using the active backend.

        Args:
            url: Target URL.
            **kwargs: Additional backend-specific parameters.

        Returns:
            Navigation result dict.
        """
        raise NotImplementedError("BackendManager.navigate — not implemented yet")

    async def evaluate(self, js: str, **kwargs: Any) -> dict[str, Any]:
        """Evaluate JavaScript using the active backend.

        Args:
            js: JavaScript expression to evaluate.
            **kwargs: Additional backend-specific parameters.

        Returns:
            Evaluation result dict.
        """
        raise NotImplementedError("BackendManager.evaluate — not implemented yet")

    async def screenshot(self, **kwargs: Any) -> dict[str, Any]:
        """Take a screenshot using the active backend.

        Args:
            **kwargs: Backend-specific screenshot parameters.

        Returns:
            Screenshot result dict.
        """
        raise NotImplementedError("BackendManager.screenshot — not implemented yet")
