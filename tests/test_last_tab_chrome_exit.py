"""v1.36.10: closing the last tab kills headed Chrome — and we cause it.

THE DEFECT (found 2026-10-03 by reading the v1.36.9 diagnostics, not a guess)

Chrome has been dying and relaunching on a ~30-minute cycle for months.  The
new lifecycle log proved it was NOT a crash:

    139 launch lines, 138 exit lines, every single one ``exit status 0``,
    and 8/8 exits landing within 20s of our own ``Session ... destroyed``.

The cycle, from the journal:

    00:37:13  Session 57f6f7ea destroyed      <- 30-min session TTL expired
    00:37:13  exit status 0                   <- one second later Chrome is gone
    00:38:31  watchdog probe failed (1/2)
    00:43:48  Chrome not running -> relaunch
    00:47:01  Keep-warm session ensured        -> and round we go

``SessionRegistry.destroy()`` closes the session's tab.  When that was the
only page tab open, headed Chrome exits cleanly — that is Chrome's documented
behaviour, not a bug in Chrome.

THE ORDERING BUG

``cleanup()`` reaps stale sessions FIRST and only then tries to mint a
keep-warm tab.  By the time the mint runs, Chrome is already dead, the CDP
call gets ``All connection attempts failed``, and that failure is swallowed at
``logger.debug`` — so the protection never fires and, worse, never even says
it failed.  The guard has to come BEFORE the close, not after it.

These tests pin the ordering.  They must fail on the pre-fix code.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from session_registry import SessionRegistry


def _registry_with_one_session() -> tuple[SessionRegistry, MagicMock]:
    """A registry holding exactly one session on one tab."""
    reg = SessionRegistry(ttl=1800.0)
    sess = MagicMock()
    sess.tab_id = "TAB0001"
    sess.last_seen = 0.0            # ancient -> stale
    sess.client.close_tab = AsyncMock(return_value={})
    sess.client.close = AsyncMock()
    reg._sessions = {"sess-1": sess}
    return reg, sess


# ── the regression this file exists for ──────────────────────────────────────


@pytest.mark.asyncio
async def test_closing_the_last_tab_does_not_exhaust_the_browser(monkeypatch):
    """An anchor tab must exist BEFORE the last session tab is closed.

    This is the whole bug in one test: destroying the final tab without an
    anchor takes the browser down with it, which is what has been relaunching
    Chrome every 30 minutes.
    """
    reg, sess = _registry_with_one_session()

    minted: list[str] = []

    async def fake_new_tab(*, doomed_tab_id: str | None = None) -> str:
        minted.append(doomed_tab_id)
        return "ANCHOR"

    async def fake_page_count() -> int:
        return 1                     # this session's tab is the only page

    monkeypatch.setattr(reg, "_count_page_tabs", fake_page_count, raising=False)
    monkeypatch.setattr(reg, "_ensure_anchor_tab", fake_new_tab, raising=False)

    await reg.destroy("sess-1")

    assert minted, "destroy() closed the last tab with no anchor minted first"
    sess.client.close_tab.assert_awaited_once_with("TAB0001")


@pytest.mark.asyncio
async def test_anchor_is_not_minted_when_other_tabs_remain(monkeypatch):
    """No wasted tab: only mint when the close would actually be fatal."""
    reg, _sess = _registry_with_one_session()

    async def fake_page_count() -> int:
        return 2                     # the session's tab plus another page

    monkeypatch.setattr(reg, "_count_page_tabs", fake_page_count, raising=False)

    minted: list[str] = []

    async def fake_new_tab(*, doomed_tab_id: str | None = None) -> str:
        minted.append(doomed_tab_id)
        return "ANCHOR"

    monkeypatch.setattr(reg, "_ensure_anchor_tab", fake_new_tab, raising=False)

    await reg.destroy("sess-1")

    assert minted == [], "minted a needless anchor tab while pages remained"


@pytest.mark.asyncio
async def test_shutdown_does_not_mint_an_anchor(monkeypatch):
    """close_all() must NOT mint: we are killing the browser on purpose.

    Minting on shutdown would be a pointless CDP round trip that fights the
    teardown, and it briefly resurrects the browser we are closing.
    """
    reg = SessionRegistry(ttl=1800.0)
    minted: list[str] = []

    async def fake_new_tab(*, doomed_tab_id: str | None = None) -> str:
        minted.append(doomed_tab_id)
        return "ANCHOR"

    async def fake_page_count() -> int:
        return 1

    monkeypatch.setattr(reg, "_count_page_tabs", fake_page_count, raising=False)
    monkeypatch.setattr(reg, "_ensure_anchor_tab", fake_new_tab, raising=False)

    s1 = MagicMock()
    s1.tab_id = "T1"
    s1.last_seen = 0.0
    s1.client.close_tab = AsyncMock(return_value={})
    s1.client.close = AsyncMock()
    s2 = MagicMock()
    s2.tab_id = "T2"
    s2.last_seen = 0.0
    s2.client.close_tab = AsyncMock(return_value={})
    s2.client.close = AsyncMock()
    reg._sessions = {"a": s1, "b": s2}

    await reg.close_all()

    assert minted == [], "shutdown minted a keep-warm anchor while closing the browser"
    s1.client.close_tab.assert_awaited_once_with("T1")
    s2.client.close_tab.assert_awaited_once_with("T2")


@pytest.mark.asyncio
async def test_orphan_sweep_never_closes_the_anchor(monkeypatch):
    """The keep-warm anchor must survive the sweep even when sessions exist.

    Found in review (2026-10-03): the anchor is UNOWNED, so the sweep sees it
    as an orphan.  The "never close the last tab" guard only fires when EVERY
    page tab is an orphan — with a live session tab present the guard is
    skipped and the sweep closes the anchor.  That reopens the original hole:
    the anchor exists precisely to keep the browser up, and something in our
    own cleanup closes it.

    The guard must protect the anchor by IDENTITY, not by counting.
    """
    reg = SessionRegistry(ttl=1800.0)

    owned_tab = "SESSIONTAB"
    anchor = "ANCHORTAB"

    tabs = [
        {"id": owned_tab, "type": "page"},
        {"id": anchor, "type": "page"},
    ]
    closed: list[str] = []

    class _CDP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def get(self, url, *a, **k):
            if "/json/close/" in str(url):
                closed.append(str(url).rsplit("/", 1)[-1])

            class _R:
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self):
                    return tabs

            return _R()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _CDP)
    # The sweep reads this as a plain attribute, so set it directly.
    reg._anchor_tab_id = anchor

    reaped = await reg._reap_orphan_tabs("http://cdp")

    assert anchor not in closed, (
        "the keep-warm anchor was reaped as an orphan; the browser would then "
        "exit the moment the last session tab closes"
    )
    assert reaped == 1, f"expected exactly the foreign orphan reaped, got {reaped}"


@pytest.mark.asyncio
async def test_adopted_anchor_is_recorded_for_the_sweep(monkeypatch):
    """Adopting an existing page tab must still register it as the anchor.

    Regression found by the LIVE sweep check (2026-10-03).  `_ensure_anchor_tab`
    returned early when a page tab already existed, without recording its id —
    so `_anchor_tab_id` stayed None, the sweep had nothing to spare, and it
    closed the very tab holding the browser up.  Unit tests could not see it:
    they only exercised the mint branch.
    """
    reg = SessionRegistry(ttl=1800.0)
    existing = "EXISTINGTAB"

    class _Resp:
        status_code = 200

        def json(self):
            return [{"id": existing, "type": "page"}]

    class _HTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def get(self, *a, **k):
            return _Resp()

        async def put(self, *a, **k):
            raise AssertionError("must not mint when a page tab already exists")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _HTTP)

    got = await reg._ensure_anchor_tab()

    assert got == existing
    assert reg._anchor_tab_id == existing, (
        "the adopted tab was not recorded, so the orphan sweep will close it"
    )


def _cdp_with(existing: list[str], minted: list[str] | None = None):
    """An httpx stub whose /json returns `existing` and whose PUT records mints."""
    minted = minted if minted is not None else []

    class _Resp:
        def __init__(self, payload):
            self._p = payload
            self.status_code = 200

        def json(self):
            return self._p

    class _HTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def get(self, *a, **k):
            return _Resp([{"id": i, "type": "page"} for i in existing])

        async def put(self, *a, **k):
            nid = f"MINTED{len(minted)}"
            minted.append(nid)
            return _Resp({"id": nid})

    return _HTTP, minted


@pytest.mark.asyncio
async def test_doomed_tab_is_never_adopted_as_the_anchor(monkeypatch):
    """destroy() must NOT adopt the very tab it is about to close.

    Review finding (2026-10-03).  When the session's tab is the only page
    tab, `_ensure_anchor_tab()` saw a page tab, returned it — and `destroy()`
    closed it one line later.  Chrome exits: the exact 30-minute loop this
    whole change set exists to stop, reintroduced by the fix.
    """
    reg, _sess = _registry_with_one_session()
    import httpx

    _HTTP, minted = _cdp_with(existing=["TAB0001"])   # the doomed tab is the only one
    monkeypatch.setattr(httpx, "AsyncClient", _HTTP)

    async def count_one() -> int:
        return 1

    monkeypatch.setattr(reg, "_count_page_tabs", count_one, raising=False)

    await reg.destroy("sess-1")

    assert minted, (
        "destroy() adopted the tab it was about to close instead of minting an "
        "anchor, so the browser still exits"
    )
    assert reg._anchor_tab_id == minted[0], (
        "the anchor recorded the doomed tab; the sweep would spare the wrong one"
    )


@pytest.mark.asyncio
async def test_sweep_never_adopts_a_session_owned_tab(monkeypatch):
    """_ensure_anchor_tab must not register a live session's tab as the anchor.

    Otherwise the sweep spares that session tab and reaps the real anchor.
    """
    reg = SessionRegistry(ttl=1800.0)
    live = MagicMock()
    live.tab_id = "SESSIONTAB"
    live.last_seen = time.monotonic()
    live.client.close_tab = AsyncMock(return_value={})
    live.client.close = AsyncMock()
    reg._sessions = {"live": live}

    import httpx

    _HTTP, _m = _cdp_with(existing=["SESSIONTAB"])
    monkeypatch.setattr(httpx, "AsyncClient", _HTTP)

    await reg._ensure_anchor_tab()

    assert reg._anchor_tab_id != "SESSIONTAB", (
        "a session-owned tab was recorded as the keep-warm anchor; the sweep "
        "would spare it and reap the real anchor instead"
    )


# ── the keep-warm mint must stop hiding its failures ─────────────────────────


@pytest.mark.asyncio
async def test_cleanup_reports_a_failed_keep_warm_mint(monkeypatch, caplog):
    """A dead browser during cleanup must be visible, not swallowed at debug.

    The mint runs against a browser that may already be gone.  When that
    happens the operator needs to see it — that log line is the only clue
    that the whole watchdog cycle is about to start over.
    """
    reg, _sess = _registry_with_one_session()

    import httpx

    class _DeadBrowser:
        """An httpx client whose every request fails the way a dead CDP does."""

        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("All connection attempts failed")

        async def put(self, *a, **k):
            raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(httpx, "AsyncClient", _DeadBrowser)

    with caplog.at_level("WARNING"):
        reaped = await reg.cleanup()

    assert reaped == 1, "the stale session should still have been reaped"
    assert any(
        "keep-warm" in r.message.lower() and r.levelname in ("WARNING", "ERROR")
        for r in caplog.records
    ), f"the failed mint was not surfaced; records={[(r.levelname, r.message) for r in caplog.records]}"
