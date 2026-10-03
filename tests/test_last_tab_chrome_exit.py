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

    async def fake_new_tab(url: str = "about:blank") -> str:
        minted.append(url)
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

    async def fake_new_tab(url: str = "about:blank") -> str:
        minted.append(url)
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

    async def fake_new_tab(url: str = "about:blank") -> str:
        minted.append(url)
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
