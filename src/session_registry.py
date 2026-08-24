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
    profile_dir: str | None = None

    def touch(self) -> None:
        self.last_seen = time.monotonic()


class SessionRegistry:
    """Mint, resolve and reap per-client browser sessions."""

    def __init__(self, ttl: float = 1800.0, max_sessions: int = 15):
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl
        self._max_sessions = max_sessions
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._sessions)

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    def get(self, session_id: str | None) -> Session | None:
        """Return the session for *session_id*, or None."""
        if not session_id:
            return None
        sess = self._sessions.get(session_id)
        if sess is not None:
            sess.touch()
        return sess

    async def _evict_lru(self) -> Session | None:
        """Close the least-recently-used session to make room.

        Safe: the client's session id stays valid; on its next call the
        auto-heal path recreates the tab transparently.  Returns the evicted
        session (or None when under the cap).
        """
        if len(self._sessions) < self._max_sessions:
            # Early-warning at 80% capacity so operators see churn coming
            # before eviction starts (rate-limited: only on crossing).
            if len(self._sessions) >= int(self._max_sessions * 0.8):
                if not getattr(self, "_cap_warned", False):
                    self._cap_warned = True
                    logger.warning(
                        "Session count %d approaching cap %d — expect LRU eviction soon",
                        len(self._sessions), self._max_sessions,
                    )
            else:
                self._cap_warned = False
            return None
        victim_id = min(self._sessions, key=lambda sid: self._sessions[sid].last_seen)
        victim = self._sessions[victim_id]
        await self.destroy(victim_id)
        logger.warning(
            "Session cap %d reached — evicted LRU session %s (tab %s) to make room; "
            "client's next call will auto-heal a fresh tab",
            self._max_sessions, victim_id[:8], victim.tab_id[:8],
        )
        return victim

    async def _reap_orphan_tabs(self, cdp_http_url: str) -> int:
        """Close browser tabs not owned by any live session.

        Tabs accumulate when a client never echoes its session cookie (each
        call mints a fresh session+tab) or when an evicted tab's close failed
        (WS gone).  This reaps those orphans so the tab count stays bounded
        even for cookie-less clients.
        """
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(f"{cdp_http_url.rstrip('/')}/json")
                resp.raise_for_status()
                tabs = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("orphan-tab scan failed: %s", exc)
            return 0
        owned = {s.tab_id for s in self._sessions.values()}
        orphans = [t.get("id") for t in tabs if t.get("type") == "page" and t.get("id") not in owned]
        reaped = 0
        for tid in orphans:
            try:
                async with httpx.AsyncClient(timeout=3.0) as http:
                    await http.get(f"{cdp_http_url.rstrip('/')}/json/close/{tid}")
                reaped += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("close orphan tab %s failed: %s", tid, exc)
        if reaped:
            logger.info("Reaped %d orphan tab(s) not owned by live sessions", reaped)
        return reaped

    async def create(self, cdp_http_url: str, url: str = "about:blank",
                     profile_dir: str | None = None) -> Session:
        """Create a new session: mint id, open a dedicated tab, attach CDP.

        The Chrome browser must already be running (callers ensure this via
        the auto-launch path).  Raises CDPError if the tab cannot be created.
        When the session cap is reached, the least-recently-used session is
        evicted first (its tab closed) so the tab count never exceeds the cap.

        *profile_dir*: optional Chrome user-data dir for the new tab.  When
        set, the tab is created with that profile's cookies/storage (cookie
        isolation between sessions); when omitted the tab shares the default
        profile (current behaviour).
        """
        async with self._lock:
            # Reap tabs left behind by cookie-less clients / failed evictions,
            # so the physical tab count stays bounded even under churn.
            try:
                await self._reap_orphan_tabs(cdp_http_url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("reap orphan tabs failed: %s", exc)
            # Enforce the cap: evict LRU before minting a new one.
            await self._evict_lru()
            sid = uuid.uuid4().hex
            client = CDPClient(cdp_http_url=cdp_http_url)
            # Point the fresh client at the running Chrome and open its own tab
            # via the HTTP /json/new endpoint (needs no WebSocket yet).
            client.cdp_http_url = cdp_http_url.rstrip("/")
            tab_id = await self._open_tab_http(client, url, profile_dir=profile_dir)
            # Fix-7 (2026-08-12): discover_tabs() caches up to 5s, so the
            # freshly opened tab may be missing from the cached list — then
            # connect_to_target would either fail ("Tab not found") or bind
            # _ws_tab_id to a stale/other tab.  Drop the cache so the new
            # session's WS binds to the tab we actually just created.
            client._tabs_cache = []
            client._tabs_cache_ts = 0
            await client.connect_to_target(tab_id)
            sess = Session(session_id=sid, client=client, tab_id=tab_id)
            sess.profile_dir = profile_dir
            self._sessions[sid] = sess
            # Attach a behavioral engine with a human profile seeded from
            # the session id — makes click/type/scroll automatically use
            # human-like input patterns without any opt-in from the client.
            try:
                from behavioral_engine import HumanProfile

                client.enable_behavioral(HumanProfile.from_session(sid))
            except Exception as exc:  # noqa: BLE001
                logger.debug("behavioral engine init failed: %s", exc)
            logger.info("Session %s created (tab %s, total %d)", sid[:8], tab_id, len(self._sessions))
            return sess

    async def _open_tab_http(self, client: CDPClient, url: str = "about:blank",
                             profile_dir: str | None = None) -> str:
        """Open a new tab via CDP HTTP endpoint (no WS connection needed).

        When *profile_dir* is set, the tab is created in a fresh browser
        context using that Chrome user-data dir (cookie isolation).  Falls
        back to the default context when the endpoint doesn't support it.
        """
        import httpx

        # A fresh user-data dir needs a dedicated Chrome instance; the running
        # browser cannot switch profiles per-tab.  For real isolation we'd
        # launch a second Chrome with --user-data-dir.  For now: if a profile
        # is requested and it differs from the default, launch a dedicated
        # headless Chrome on a free port and use that CDP endpoint instead.
        if profile_dir:
            from headless_manager import _find_free_port

            port = _find_free_port()
            try:
                # If a Chrome already runs with THIS profile dir, reuse it.
                import re as _re

                existing = None
                try:
                    pgrep = await asyncio.create_subprocess_exec(
                        "pgrep", "-af", "user-data-dir=" + profile_dir,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout_data, _ = await asyncio.wait_for(
                        pgrep.communicate(), timeout=5
                    )
                    out_text = stdout_data.decode() if stdout_data else ""
                    m = _re.search(r"remote-debugging-port=(\d+)", out_text)
                    if m:
                        existing = int(m.group(1))
                except Exception as exc:  # noqa: BLE001
                    logger.debug("pgrep for existing Chrome failed: %s", exc)

                if existing is not None:
                    port = existing
                    proc = None
                else:
                    proc = await asyncio.create_subprocess_exec(
                        "/usr/bin/google-chrome",
                        f"--remote-debugging-port={port}",
                        "--headless=new",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-gpu",
                        "--no-sandbox",
                        f"--user-data-dir={profile_dir}",
                        "about:blank",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                # Wait for CDP to come up.
                import time as _time

                deadline = _time.time() + 15
                while _time.time() < deadline:
                    try:
                        async with httpx.AsyncClient(timeout=3) as h:
                            r = await h.get(f"http://127.0.0.1:{port}/json/version")
                            if r.status_code == 200:
                                break
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("CDP readiness probe failed: %s", exc)
                    await asyncio.sleep(0.3)
                client.cdp_http_url = f"http://127.0.0.1:{port}"
                client._profile_proc = proc
                client._profile_port = port
            except Exception as exc:  # noqa: BLE001
                logger.warning("Profile launch failed, falling back to default tab: %s", exc)
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
        except Exception:  # noqa: BLE001
            logger.debug("close_tab failed for session %s", session_id[:8])
        # If this session ran on a dedicated profile Chrome, shut it down too.
        profile_proc = getattr(sess.client, "_profile_proc", None)
        if profile_proc is not None:
            try:
                profile_proc.terminate()
            except Exception as exc:  # noqa: BLE001
                logger.debug("terminate profile proc failed: %s", exc)
        try:
            await sess.client.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("close client failed: %s", exc)
        logger.info("Session %s destroyed", session_id[:8])
        return True

    async def cleanup(self) -> int:
        """Reap sessions idle longer than TTL. Returns count reaped."""
        now = time.monotonic()
        # P3: tombstone for GC debugging — reaped session ids kept so a later
        # debug endpoint can list what was cleaned.  Bounded at 100.
        if not hasattr(self, "_last_reaped"):
            self._last_reaped: list[dict] = []
        stale = [sid for sid, s in self._sessions.items() if now - s.last_seen > self._ttl]
        for sid in stale:
            tab = self._sessions.get(sid).tab_id[:8] if sid in self._sessions else "?"
            await self.destroy(sid)
            self._last_reaped.append({"sid": sid[:12] + "…", "tab": tab, "at": now})
            if len(self._last_reaped) > 100:
                self._last_reaped = self._last_reaped[-100:]
        if stale:
            logger.info("Reaped %d stale session(s), %d remain", len(stale), len(self._sessions))
        # P3: also reap orphan tabs (about:blank accumulation) while we're here.
        # The per-create reap only runs on session creation; long-lived sessions
        # that accumulate about:blank tabs (e.g. old cross-origin roam leftovers)
        # need a periodic sweep too.  This is best-effort — never block the reaper.
        try:
            import os as _os
            cdp_url = f"http://127.0.0.1:{_os.environ.get('CHROME_AUTO_PORT') or _os.environ.get('BH_PORT') or '9557'}"
            # Use the first live session's cdp_http_url when available.
            for _sess in self._sessions.values():
                cdp_url = _sess.client.cdp_http_url
                break
            reaped_orphans = await self._reap_orphan_tabs(cdp_url)
            if reaped_orphans:
                logger.info("Periodic orphan-tab sweep: reaped %d about:blank orphan(s)", reaped_orphans)
        except Exception as exc:  # noqa: BLE001 — best-effort sweep must never crash the reaper
            logger.debug("orphan-tab sweep failed: %s", exc)
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
