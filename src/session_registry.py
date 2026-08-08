"""Session registry — per-client tab isolation.

Every HTTP client (Hermes agent, cron job, external tool) that talks to
Browser Helper can hold its own browser tab without interfering with other
clients.  The server mints a session id (UUID) on first contact, stores it in
a cookie (``bh_session``) and an ``X-Session-ID`` response header; the client
merely echoes it back.  No client-side id generation is required.

Each session owns:
  - one :class:`CDPClient` instance with its own WebSocket to Chrome
  - one dedicated browser tab (created via ``Target.createTarget``)

Sessions that stay idle longer than *ttl* seconds are cleaned up (tab closed,
WS closed) by :meth:`cleanup` / the background reaper.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from cdp_client import CDPClient, CDPError

logger = logging.getLogger("browser-helper.session_registry")


@dataclass
class Session:
    """One client's isolated browser context."""

    session_id: str
    client: CDPClient
    tab_id: str
    created: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_seen = time.monotonic()


class SessionRegistry:
    """Mint, resolve and reap per-client browser sessions."""

    def __init__(self, ttl: float = 1800.0):
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._sessions)

    def get(self, session_id: str | None) -> Session | None:
        """Return the session for *session_id*, or None."""
        if not session_id:
            return None
        sess = self._sessions.get(session_id)
        if sess is not None:
            sess.touch()
        return sess

    async def create(self, cdp_http_url: str, url: str = "about:blank") -> Session:
        """Create a new session: mint id, open a dedicated tab, attach CDP.

        The Chrome browser must already be running (callers ensure this via
        the auto-launch path).  Raises CDPError if the tab cannot be created.
        """
        async with self._lock:
            sid = uuid.uuid4().hex
            client = CDPClient(cdp_http_url=cdp_http_url)
            # Point the fresh client at the running Chrome and open its own tab
            # via the HTTP /json/new endpoint (needs no WebSocket yet).
            client.cdp_http_url = cdp_http_url.rstrip("/")
            tab_id = await self._open_tab_http(client, url)
            await client.connect_to_target(tab_id)
            sess = Session(session_id=sid, client=client, tab_id=tab_id)
            self._sessions[sid] = sess
            logger.info("Session %s created (tab %s, total %d)", sid[:8], tab_id, len(self._sessions))
            return sess

    async def _open_tab_http(self, client: CDPClient, url: str = "about:blank") -> str:
        """Open a new tab via CDP HTTP endpoint (no WS connection needed)."""
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.put(
                f"{client.cdp_http_url}/json/new",
                params={"url": url},
            )
            resp.raise_for_status()
            target = resp.json()
        tab_id = target.get("id") or target.get("targetId")
        if not tab_id:
            raise CDPError(f"Tab creation returned no id: {target}")
        return tab_id

    async def destroy(self, session_id: str) -> bool:
        """Close a session's tab + WS and forget it."""
        sess = self._sessions.pop(session_id, None)
        if sess is None:
            return False
        try:
            await sess.client.close_tab(sess.tab_id)
        except Exception:
            logger.debug("close_tab failed for session %s", session_id[:8])
        try:
            await sess.client.close()
        except Exception:
            pass
        logger.info("Session %s destroyed", session_id[:8])
        return True

    async def cleanup(self) -> int:
        """Reap sessions idle longer than TTL. Returns count reaped."""
        now = time.monotonic()
        stale = [sid for sid, s in self._sessions.items() if now - s.last_seen > self._ttl]
        for sid in stale:
            await self.destroy(sid)
        if stale:
            logger.info("Reaped %d stale session(s), %d remain", len(stale), len(self._sessions))
        return len(stale)

    async def close_all(self) -> None:
        """Destroy every session (server shutdown)."""
        for sid in list(self._sessions):
            await self.destroy(sid)
        if self._reaper_task:
            self._reaper_task.cancel()
            self._reaper_task = None

    # ── Background reaper ─────────────────────────────────────────

    def start_reaper(self) -> None:
        """Start the periodic TTL reaper (idempotent)."""
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(min(self._ttl, 60.0))
            try:
                await self.cleanup()
            except Exception:
                logger.exception("Session reaper error")
