"""v1.36.5: ``BH_MAX_TABS`` — hard server-side stop on runaway tab creation.

Context: agents (Claude via MCP, hermes) kept opening dozens of real Chrome
tabs.  Two independent causes were found on 2026-09-27/28:

  1. ``/home/zoltan/.claude/mcp-browser-helper.json`` set
     ``BH_SESSION_AUTO=1`` in the MCP child env, which made every
     header-less browser op auto-mint a fresh tab (config fix, no code).
  2. Even with that removed, a client that repeatedly calls
     ``POST /session/new`` without echoing ``X-Session-ID`` still opens one
     real tab per call.  ``BH_MAX_TABS`` is the server-side backstop.

Contract: when the budget is spent, ``/session/new`` returns **429** with a
``remedy`` message and **no new tab is opened** — unlike ``max_sessions``
(which evicts the LRU tab to make room, keeping the count flat).
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.responses import JSONResponse

sys.path.insert(0, "src")
sys.path.insert(0, ".")


@pytest.fixture
def registry_cls(monkeypatch):
    """Import ``session_registry`` with a controllable ``BH_MAX_TABS``."""
    import importlib

    import session_registry as sr

    importlib.reload(sr)
    return sr


def _make_registry(sr, budget):
    """Build a SessionRegistry whose ``create`` never touches real Chrome."""
    reg = sr.SessionRegistry(ttl=1800.0, max_sessions=30)
    reg._tab_budget = budget
    # Neutralise everything create() does around the budget check.
    reg._reap_orphan_tabs = AsyncMock(return_value=0)
    reg._evict_lru = AsyncMock(return_value=None)
    return reg


def _fake_session(sid="s1", tab="t1"):
    s = MagicMock()
    s.session_id = sid
    s.tab_id = tab
    s.target_url = "about:blank"
    s.last_seen = 0.0
    return s


def test_tab_budget_off_by_default(registry_cls):
    """BH_MAX_TABS unset (or 0) must not refuse anything."""
    reg = _make_registry(registry_cls, 0)
    assert reg.tab_budget == 0


@pytest.mark.asyncio
async def test_tab_budget_exceeded_refuses_without_opening_tab(registry_cls):
    """The 3rd tab on a budget of 2 raises and leaves the count at 2."""
    sr = registry_cls
    reg = _make_registry(sr, 2)
    reg._sessions = {"a": _fake_session("a", "ta"), "b": _fake_session("b", "tb")}

    opened = []

    async def _never_called(*a, **k):
        opened.append(a)
        raise AssertionError("no tab may be opened past the budget")

    with patch.object(sr.SessionRegistry, "_open_tab_http", _never_called):
        with pytest.raises(sr.TabBudgetExceeded) as exc:
            await reg.create("http://127.0.0.1:9557", url="https://example.com/")

    assert exc.value.in_use == 2
    assert exc.value.budget == 2
    assert reg.tabs_in_use() == 2, "count must not grow past the budget"
    assert not opened


@pytest.mark.asyncio
async def test_tab_budget_allows_exactly_budget_tabs(registry_cls):
    """With budget=2 and 1 tab in use, creating another is allowed."""
    sr = registry_cls
    reg = _make_registry(sr, 2)
    reg._sessions = {"a": _fake_session("a", "ta")}

    async def _open(self, client, url, profile_dir=None):
        return "tNEW"

    fake_client = MagicMock()
    fake_client.connect_to_target = AsyncMock()
    fake_client.discover_tabs = AsyncMock(return_value=[])

    with patch.object(sr.SessionRegistry, "_open_tab_http", _open):
        with patch.object(sr, "CDPClient", MagicMock(return_value=fake_client)):
            sess = await reg.create("http://127.0.0.1:9557", url="https://example.com/")

    assert sess.tab_id == "tNEW"
    assert reg.tabs_in_use() == 2


def test_tab_budget_reads_env_at_init(monkeypatch):
    """BH_MAX_TABS is honoured when the registry is constructed."""
    monkeypatch.setenv("BH_MAX_TABS", "3")
    import importlib

    import session_registry as sr

    importlib.reload(sr)
    reg = sr.SessionRegistry(ttl=1.0, max_sessions=5)
    assert reg.tab_budget == 3
    assert reg.tabs_in_use() == 0


def test_tab_budget_env_empty_means_unlimited(monkeypatch):
    """A blank BH_MAX_TABS must parse to 0, not crash."""
    monkeypatch.setenv("BH_MAX_TABS", "")
    import importlib

    import session_registry as sr

    importlib.reload(sr)
    reg = sr.SessionRegistry(ttl=1.0, max_sessions=5)
    assert reg.tab_budget == 0


def test_api_error_returns_jsonresponse_not_dict():
    """Regression: the 429 branch once double-wrapped api_error's result.

    ``api_error`` already returns a ``JSONResponse``; re-wrapping it in
    ``JSONResponse(content=...)`` raised
    ``TypeError: Object of type JSONResponse is not JSON serializable``,
    turning the intended 429 into a 500 (observed live 2026-09-28).
    """
    from main import api_error

    resp = api_error("session_new", "tab_budget_exhausted", "boom", 429, {"a": 1})
    assert isinstance(resp, JSONResponse), "api_error must return a response object"
    assert resp.status_code == 429
    # A JSONResponse cannot be re-wrapped as content — guard the exact trap.
    with pytest.raises(TypeError):
        JSONResponse(content=resp)
