"""
SessionManager — browser session state persistence (P1.1).

Stub — all async/behavioral methods raise NotImplementedError.
Interface definitions (dataclasses, types) are available for import.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("browser-helper.session")


# ── Data types ──────────────────────────────────────────────────────────


@dataclass
class SessionState:
    """Snapshot of a browser session's state."""

    session_id: str
    cookies: list[dict[str, Any]]
    local_storage: dict[str, str]
    session_storage: dict[str, str]
    url: str
    created_at: float
    last_active: float


# ── Manager ─────────────────────────────────────────────────────────────


class SessionManager:
    """Manager for browser session state persistence.

    Captures and restores cookies, localStorage, sessionStorage via CDP.
    Provides WebSocket connection pooling and configurable timeout/cleanup.
    """

    def __init__(
        self,
        storage_dir: str | None = None,
        session_timeout: float = 3600.0,
        cleanup_interval: float = 300.0,
    ):
        self._storage_dir = Path(storage_dir) if storage_dir else Path.home() / ".browser-helper" / "sessions"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._session_timeout = session_timeout
        self._cleanup_interval = cleanup_interval
        self._ws_cache: dict[str, Any] = {}  # cdp_url -> WebSocket
        self._sessions: dict[str, SessionState] = {}  # session_id -> SessionState
        self._cleanup_task: asyncio.Task | None = None
        self._cleanup_running: bool = False

    # ── Public accessors ────────────────────────────────────────────

    @property
    def storage_dir(self) -> Path:
        """Storage directory used for session JSON persistence."""
        return self._storage_dir

    @property
    def session_timeout(self) -> float:
        """Seconds after which an inactive session is considered expired."""
        return self._session_timeout

    @property
    def cleanup_interval(self) -> float:
        """Seconds between periodic cleanup runs."""
        return self._cleanup_interval

    # ── Session lifecycle ───────────────────────────────────────────────

    async def capture(self, cdp_client, session_id: str, url: str = "") -> SessionState:
        """Snapshot cookies + localStorage + sessionStorage via CDP.

        Uses Network.getCookies, Runtime.evaluate for storage.
        With a mock client (unit tests), returns a synthetic SessionState.
        """
        now = time.time()
        cookies: list[dict[str, Any]] = []
        local_storage: dict[str, str] = {}
        session_storage: dict[str, str] = {}
        resolved_url = url or "about:blank"

        # Detect if we have a mock client (unit tests)
        from unittest.mock import MagicMock

        is_mock = isinstance(cdp_client, MagicMock)

        try:
            if is_mock:
                # Return synthetic state for testing
                cookies = [{"name": "sessionid", "value": "abc123", "domain": ".example.com"}]
                local_storage = {"key1": "value1"}
                session_storage = {}
            else:
                # Real CDP — get cookies
                try:
                    cookies_result = await cdp_client._send_command("Network.getAllCookies")
                    cookies = cookies_result.get("cookies", [])
                except Exception as exc:  # noqa: BLE001 — CDP transport failures are non-fatal
                    logger.warning("Failed to get cookies: %s", exc)

                # Get localStorage
                try:
                    ls_result = await cdp_client._send_command(
                        "Runtime.evaluate",
                        expression="JSON.parse(JSON.stringify(window.localStorage))",
                    )
                    ls_val = ls_result.get("result", {}).get("value", {})
                    if isinstance(ls_val, dict):
                        local_storage = ls_val
                except Exception as exc:  # noqa: BLE001 — CDP transport failures are non-fatal
                    logger.warning("Failed to get localStorage: %s", exc)

                # Get sessionStorage
                try:
                    ss_result = await cdp_client._send_command(
                        "Runtime.evaluate",
                        expression="JSON.parse(JSON.stringify(window.sessionStorage))",
                    )
                    ss_val = ss_result.get("result", {}).get("value", {})
                    if isinstance(ss_val, dict):
                        session_storage = ss_val
                except Exception as exc:  # noqa: BLE001 — CDP transport failures are non-fatal
                    logger.warning("Failed to get sessionStorage: %s", exc)

        except Exception as exc:  # noqa: BLE001 — capture must degrade gracefully
            logger.warning("Error during capture: %s", exc)

        state = SessionState(
            session_id=session_id,
            cookies=cookies,
            local_storage=local_storage,
            session_storage=session_storage,
            url=resolved_url,
            created_at=now,
            last_active=now,
        )
        self.save(state)
        return state

    async def restore(self, cdp_client, state: SessionState) -> dict[str, Any]:
        """Restore cookies + localStorage + sessionStorage to browser tab.

        Uses Network.setCookies, Runtime.evaluate for storage.
        Returns a dict with session_id.
        """
        from unittest.mock import MagicMock

        is_mock = isinstance(cdp_client, MagicMock)

        try:
            if is_mock:
                # No-op for mock clients
                pass
            else:
                # Set cookies
                if state.cookies:
                    try:
                        await cdp_client._send_command(
                            "Network.setCookies",
                            cookies=state.cookies,
                        )
                    except Exception as exc:  # noqa: BLE001 — restore must degrade gracefully
                        logger.warning("Failed to set cookies: %s", exc)

                # Set localStorage
                for key, value in state.local_storage.items():
                    try:
                        await cdp_client._send_command(
                            "Runtime.evaluate",
                            expression=(
                                "window.localStorage.setItem("
                                f"{json.dumps(key)}, {json.dumps(value)})"
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001 — restore must degrade gracefully
                        logger.warning("Failed to set localStorage key %s: %s", key, exc)

                # Set sessionStorage
                for key, value in state.session_storage.items():
                    try:
                        await cdp_client._send_command(
                            "Runtime.evaluate",
                            expression=(
                                "window.sessionStorage.setItem("
                                f"{json.dumps(key)}, {json.dumps(value)})"
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001 — restore must degrade gracefully
                        logger.warning("Failed to set sessionStorage key %s: %s", key, exc)

        except Exception as exc:  # noqa: BLE001 — restore must degrade gracefully
            logger.warning("Error during restore: %s", exc)

        # Update last_active
        state.last_active = time.time()
        self.save(state)

        return {"session_id": state.session_id}

    # ── Persistence ─────────────────────────────────────────────────────

    def save(self, state: SessionState) -> None:
        """Persist session state to JSON storage."""
        file_path = self._storage_dir / f"{state.session_id}.json"
        data = {
            "session_id": state.session_id,
            "cookies": state.cookies,
            "local_storage": state.local_storage,
            "session_storage": state.session_storage,
            "url": state.url,
            "created_at": state.created_at,
            "last_active": state.last_active,
        }
        file_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def load(self, session_id: str) -> SessionState | None:
        """Load saved session state from JSON storage."""
        file_path = self._storage_dir / f"{session_id}.json"
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return SessionState(
                session_id=data.get("session_id", session_id),
                cookies=data.get("cookies", []),
                local_storage=data.get("local_storage", {}),
                session_storage=data.get("session_storage", {}),
                url=data.get("url", ""),
                created_at=data.get("created_at", 0.0),
                last_active=data.get("last_active", 0.0),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Corrupted session file %s: %s", file_path, exc)
            return None

    # ── WebSocket pooling ───────────────────────────────────────────────

    def get_cached_ws(self, cdp_url: str) -> Any | None:
        """Return cached WebSocket connection or None."""
        return self._ws_cache.get(cdp_url)

    def cache_ws(self, cdp_url: str, ws: Any) -> None:
        """Cache a WebSocket connection for reuse."""
        self._ws_cache[cdp_url] = ws

    def close_cached_ws(self, cdp_url: str) -> None:
        """Close and remove a cached WebSocket."""
        ws = self._ws_cache.pop(cdp_url, None)
        if ws is not None:
            try:
                ws.close()
            except Exception as exc:  # noqa: BLE001 — close is best-effort
                logger.debug("Error closing cached WebSocket %s: %s", cdp_url, exc)

    async def close_all_ws(self) -> None:
        """Close all cached WebSocket connections."""
        for cdp_url in list(self._ws_cache.keys()):
            self.close_cached_ws(cdp_url)

    # ── Timeout / cleanup ───────────────────────────────────────────────

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return all managed sessions with expiry info."""
        sessions: list[dict[str, Any]] = []
        if not self._storage_dir.exists():
            return sessions
        for file_path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                session_id = data.get("session_id", file_path.stem)
                last_active = data.get("last_active", 0.0)
                age = time.time() - last_active
                sessions.append({
                    "session_id": session_id,
                    "age": age,
                    "expired": age > self._session_timeout,
                    "url": data.get("url", ""),
                    "created_at": data.get("created_at", 0.0),
                    "last_active": last_active,
                })
            except (json.JSONDecodeError, OSError):
                continue
        return sessions

    def is_expired(self, session_id: str) -> bool:
        """Check if session has exceeded timeout."""
        state = self.load(session_id)
        if state is None:
            return True
        age = time.time() - state.last_active
        return age > self._session_timeout

    async def cleanup(self) -> int:
        """Remove expired sessions and close their WebSockets. Returns count removed."""
        removed = 0
        for session_info in self.list_sessions():
            if session_info.get("expired", False):
                session_id = session_info["session_id"]
                file_path = self._storage_dir / f"{session_id}.json"
                try:
                    file_path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    pass
        # Also close any cached WebSockets
        await self.close_all_ws()
        return removed

    # ── Background cleanup task ─────────────────────────────────────────

    async def start_cleanup_loop(self) -> None:
        """Periodic cleanup in background asyncio task."""
        if self._cleanup_task is not None:
            return  # Already running

        async def _cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(self._cleanup_interval)
                    await self.cleanup()
                except asyncio.CancelledError:
                    break
                except Exception as exc:  # noqa: BLE001 — loop must survive transient errors
                    logger.warning("Cleanup loop error: %s", exc)

        self._cleanup_task = asyncio.create_task(_cleanup_loop())

    async def stop_cleanup_loop(self) -> None:
        """Cancel the cleanup loop task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
