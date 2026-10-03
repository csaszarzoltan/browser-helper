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
import os
import time
import uuid
from dataclasses import dataclass, field

from cdp_client import CDPClient, CDPError

logger = logging.getLogger("browser-helper.session_registry")


def _build_new_tab_url(cdp_http_url: str, url: str | None) -> str:
    """Build the CDP ``PUT /json/new`` URL for opening *url* in a new tab.

    v1.36.7: Chrome takes the ENTIRE remainder of the request line after
    ``/json/new?`` as the target URL.  v1.36.2 therefore appended the URL raw —
    which works for a bare URL but silently truncates any URL that carries its
    own query string at the first ``&``:

        PUT /json/new?https://example.com/?a=1&b=2  ->  opens .../?a=1

    (verified live on Chrome 154.0.8037.57: ``b=2`` never reaches the page.)

    Percent-encoding the whole URL fixes it and also keeps control characters
    out of the request line.  ``about:blank``/empty is the CDP default and gets
    no query at all.
    """
    base = f"{cdp_http_url.rstrip('/')}/json/new"
    if not url or url == "about:blank":
        return base
    import urllib.parse

    return f"{base}?{urllib.parse.quote(url, safe='')}"


class TabBudgetExceeded(Exception):
    """Raised when ``BH_MAX_TABS`` is spent — no new tab is opened.

    v1.36.5.  Carries the current/budget numbers so the API layer can tell
    the caller exactly what to do (reuse an existing session, or close one)
    instead of silently opening tab number N+1.
    """

    def __init__(self, in_use: int, budget: int):
        self.in_use = in_use
        self.budget = budget
        super().__init__(f"Tab budget exhausted: {in_use}/{budget} tabs in use")


@dataclass
class Session:
    """One client's isolated browser context."""
    session_id: str
    client: CDPClient
    tab_id: str
    created: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    profile_dir: str | None = None
    # v1.36.2: the URL this session was created for.  A fresh tab reports
    # ``about:blank`` for a few seconds while the page loads — the keep-warm
    # probe uses this to recognise a still-loading warm tab as present.
    target_url: str = "about:blank"

    def touch(self) -> None:
        self.last_seen = time.monotonic()


class SessionRegistry:
    """Mint, resolve and reap per-client browser sessions."""

    def __init__(self, ttl: float = 1800.0, max_sessions: int = 15):
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl
        self._max_sessions = max_sessions
        # v1.36.5: hard cap on concurrently open session TABS.  Distinct from
        # max_sessions (which is the LRU-eviction ceiling): this one REFUSES a
        # new tab outright so a runaway client cannot keep opening tabs.
        self._tab_budget = int(os.environ.get("BH_MAX_TABS", "0") or 0)
        # v1.36.10: the id of the keep-warm anchor we minted, so the orphan-tab
        # sweep can spare it BY IDENTITY.  Counting alone was not enough: with
        # a live session tab present the "never close the last tab" guard is
        # skipped entirely, so the sweep would close the very anchor that
        # exists to keep the browser alive.
        self._anchor_tab_id: str | None = None
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._sessions)

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    @property
    def tab_budget(self) -> int:
        """Hard cap on how many session tabs may exist at once (0 = off).

        v1.36.5: a caller that keeps opening fresh sessions (or a client whose
        auto-mint env is set) can still fill the browser with tabs even when
        it echoes no session id.  ``BH_MAX_TABS`` turns that into a hard
        server-side stop: creating a session beyond the budget is refused
        with 429/400 instead of opening another real Chrome tab.
        """
        return self._tab_budget

    def tabs_in_use(self) -> int:
        """Number of live sessions, i.e. real Chrome tabs owned by us."""
        return len(self._sessions)

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
        # v1.36.10: the keep-warm anchor is unowned by definition, so it looks
        # exactly like an orphan to this sweep.  Spare it BY ID, not by count:
        # counting only protected it when it happened to be the last tab, and
        # closing it would reopen the 30-minute relaunch loop the anchor
        # exists to prevent.
        anchor = self._anchor_tab_id
        orphans = [
            t.get("id")
            for t in tabs
            if t.get("type") == "page"
            and t.get("id") not in owned
            and t.get("id") != anchor
        ]
        # CRITICAL (2026-09-02): never close the LAST page tab. Closing the
        # final tab makes headed Chrome exit cleanly (no crash, no signal —
        # silent disappearance), which the watchdog then "fixed" by
        # relaunching, minting another unowned tab the next sweep would
        # close again → endless launch/kill loop. Keep ≥1 page tab alive.
        if len(orphans) == len([t for t in tabs if t.get("type") == "page"]) and orphans:
            orphans = orphans[1:]  # spare one tab as the keep-warm anchor
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

        v1.36.5: ``TabBudgetExceeded`` when ``BH_MAX_TABS`` is set and the
        budget is already spent.  Unlike ``max_sessions`` (which evicts the
        LRU tab to make room), this REFUSES the new tab outright — a runaway
        client gets an error instead of one more real Chrome tab.
        """
        async with self._lock:
            # Reap tabs left behind by cookie-less clients / failed evictions,
            # so the physical tab count stays bounded even under churn.
            try:
                await self._reap_orphan_tabs(cdp_http_url)
            except Exception as exc:  # noqa: BLE001
                logger.debug("reap orphan tabs failed: %s", exc)
            # v1.36.5: hard tab budget — refuse BEFORE opening any tab so a
            # runaway client cannot grow the tab count at all.
            if self._tab_budget and len(self._sessions) >= self._tab_budget:
                logger.warning(
                    "Tab budget exhausted: %d/%d tabs in use — refusing new session",
                    len(self._sessions), self._tab_budget,
                )
                raise TabBudgetExceeded(len(self._sessions), self._tab_budget)
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
            sess = Session(session_id=sid, client=client, tab_id=tab_id, target_url=url)
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
        # v1.36.2: Chrome's /json/new only honours the BARE-QUERY form
        # (``PUT /json/new?https://example.com/``) — the documented-looking
        # ``?url=...`` form is silently IGNORED and the tab opens as
        # about:blank (verified live on Chrome 153.0.8010.52: ``?url=X`` →
        # ``about:blank``, ``?X`` → ``X``).  That is why /session/new?url=…
        # never navigated: every session tab stayed blank, so the keep-warm
        # probe never matched its URL and minted a fresh blank tab every
        # cycle, and agents saw a pile of empty tabs next to the real page.
        #
        # v1.36.7: the bare form must still be used, but the URL is now
        # percent-encoded — appended raw, a URL with its own query string was
        # cut at the first ``&`` (verified live on Chrome 154.0.8037.57:
        # ``/json/new?https://example.com/?a=1&b=2`` opened only ``?a=1``).
        new_tab_url = _build_new_tab_url(client.cdp_http_url, url)
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.put(new_tab_url)
            resp.raise_for_status()
            target = resp.json()
        tab_id = target.get("id") or target.get("targetId")
        if not tab_id:
            raise CDPError(f"Tab creation returned no id: {target}")
        # Chrome may still hand back a blank tab (older/newer builds, or a
        # rejected URL) — navigate explicitly so the session really owns the
        # requested page.  Best-effort: the caller can still navigate later.
        if url and url != "about:blank" and not str(target.get("url", "")).startswith(url.split("#")[0][:24]):
            try:
                client._ws_tab_id = tab_id
                await client.navigate(url)
            except Exception as exc:  # noqa: BLE001 — caller can retry navigate
                logger.debug("post-create navigate to %s failed: %s", url, exc)
        return tab_id

    async def _count_page_tabs(self) -> int:
        """How many page tabs the browser currently has (0 if unreachable)."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                resp = await http.get(f"{self._cdp_base_url()}/json")
                if resp.status_code != 200:
                    return 0
                return sum(1 for t in resp.json() if t.get("type") == "page")
        except Exception as exc:  # noqa: BLE001
            logger.debug("page tab count failed: %s", exc)
            return 0

    @staticmethod
    def _cdp_base_url() -> str:
        import os as _os

        port = (
            _os.environ.get("CHROME_AUTO_PORT")
            or _os.environ.get("BH_PORT")
            or "9557"
        )
        return f"http://127.0.0.1:{port}"

    async def _ensure_anchor_tab(
        self, *, doomed_tab_id: str | None = None
    ) -> str | None:
        """Guarantee a page tab that is NOT about to be closed.

        Adopting an existing tab is only safe when that tab is genuinely
        free-standing.  Two cases make it unsafe, both found in review
        (2026-10-03):

        * ``doomed_tab_id`` — ``destroy()`` is about to close exactly that
          tab.  Adopting it would mint nothing and then close the browser's
          last page tab, which is the 30-minute relaunch loop this whole
          change exists to stop.
        * a tab owned by a live session — recording it as the anchor makes
          the sweep spare that session's tab and reap the real anchor.

        So: adopt only a page tab that is neither doomed nor session-owned;
        otherwise mint a fresh one.  The id of what we returned is always
        recorded, because the sweep spares the anchor by identity, not by
        counting (a count-based guard is skipped as soon as any live session
        tab exists).
        """
        import httpx

        owned = {s.tab_id for s in self._sessions.values()}
        base = self._cdp_base_url()
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(f"{base}/json")
                adoptable: str | None = None
                if resp.status_code == 200:
                    for t in resp.json():
                        if t.get("type") != "page":
                            continue
                        tid = t.get("id")
                        if not tid or tid == doomed_tab_id or tid in owned:
                            continue
                        adoptable = tid
                        break
                if adoptable:
                    self._anchor_tab_id = adoptable
                    return adoptable
                resp2 = await http.put(f"{base}/json/new", params={"url": "about:blank"})
                if resp2.status_code < 400:
                    logger.info("Keep-warm anchor tab minted before a closing tab")
                    new_id = resp2.json().get("id")
                    self._anchor_tab_id = new_id
                    return new_id
                logger.warning(
                    "Could not mint keep-warm anchor: CDP answered %s", resp2.status_code
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not mint keep-warm anchor: %s", exc)
        return None

    async def destroy(self, session_id: str, *, keep_alive: bool = True) -> bool:
        """Close the session's tab + WS and forget it.

        Closing the LAST page tab makes headed Chrome exit cleanly — that is
        Chrome's behaviour, and it is what relaunched our browser every 30
        minutes (v1.36.10, diagnosed from the v1.36.9 lifecycle log: 138 exits,
        all ``status 0``, 8/8 within 20s of our own ``Session ... destroyed``).
        So mint the anchor tab BEFORE the close, not after: ``cleanup()`` used
        to reap first and mint afterwards, by which time the browser was
        already dead and the mint silently failed at debug level.

        ``keep_alive=False`` skips the anchor: on server shutdown we are
        closing the browser on purpose, so minting a tab to preserve it would
        be a pointless CDP round trip that fights the shutdown.
        """
        sess = self._sessions.pop(session_id, None)
        if sess is None:
            return False
        # Anchor first — this is the whole point of the reordering.
        if keep_alive:
            try:
                if await self._count_page_tabs() <= 1:
                    # Pass the doomed id: it must never become the anchor.
                    await self._ensure_anchor_tab(doomed_tab_id=sess.tab_id)
            except Exception as exc:  # noqa: BLE001 — never block the close
                logger.warning("Could not mint a keep-warm anchor before close: %s", exc)
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
        # v1.36.10: the anchor is now minted inside ``destroy()`` BEFORE each
        # close, so this post-loop sweep is only a safety net for the case
        # where the reap closed tabs without going through ``destroy()``.
        # It stays because a silent debug-level failure here is what hid the
        # 30-minute relaunch loop for months.
        if stale:
            await self._ensure_anchor_tab()
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
        """Destroy every session (server shutdown).

        ``keep_alive=False``: we are shutting the browser down on purpose, so
        no keep-warm anchor is minted — the last tab SHOULD close here.
        """
        for sid in list(self._sessions):
            await self.destroy(sid, keep_alive=False)
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
