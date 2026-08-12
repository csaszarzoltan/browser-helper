"""Tests for the 7 agent-support fixes (v1.27.3): /mcp-status + session create tab-cache.

Fix-6: GET /mcp-status reports MCP readiness + per-session tool visibility.
Fix-7: session_registry.create() drops the tab cache so connect_to_target
       binds _ws_tab_id to the freshly created tab.
"""
from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "src")

from cdp_client import CDPClient  # noqa: E402
from mcp_server.registry import ToolDef  # noqa: E402
from session_registry import Session, SessionRegistry  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────


def _fake_tab():
    return {"id": "tab-1", "type": "page", "webSocketDebuggerUrl": "ws://fake/1"}


def _make_fake_client(tab_id: str = "tab-1", connected: bool = True) -> MagicMock:
    client = MagicMock(spec=CDPClient)
    client.tab_id = tab_id
    client.is_connected = connected
    client._ws_tab_id = tab_id
    client._tabs_cache = []
    client._tabs_cache_ts = 0
    return client


def _mock_tool_defs(*names: str) -> list[ToolDef]:
    """Create a minimal list of ToolDef objects with the given names."""
    defs = []
    for name in names:
        defs.append(
            ToolDef(
                name=name,
                description=f"Mock {name}",
                parameters={"type": "object", "properties": {}},
                capability_id="browser.core",
                status="READY",
                handler=AsyncMock(),
            )
        )
    return defs


# ── Fix-6: /mcp-status ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_status_reports_sessions_and_tools():
    """GET /mcp-status returns mcp_enabled + per-session mcp_connected + tools."""
    from main import app

    sess = Session(
        session_id="sess-1",
        client=_make_fake_client(),
        tab_id="tab-1",
    )
    registry = MagicMock()
    registry._sessions = {"sess-1": sess}
    registry.max_sessions = 15

    with patch("main.session_registry", registry), \
         patch("mcp_server.registry.build_tool_defs") as mock_build:
        # Return a ToolDefRegistry-like iterable of ToolDef objects
        mock_build.return_value = iter(_mock_tool_defs("navigate", "click"))
        from main import mcp_status

        resp = await mcp_status()
        data = resp["data"]
        assert data["mcp_enabled"] is False
        assert data["tool_count"] == 2
        assert data["sessions"] == [
            {
                "id": "sess-1",
                "tab_id": "tab-1",
                "mcp_connected": True,
                "tools": ["navigate", "click"],
            }
        ]


@pytest.mark.asyncio
async def test_mcp_status_empty_registry():
    """GET /mcp-status with no sessions returns empty list, not 500."""
    from main import app  # noqa: F401 — ensure app importable

    registry = MagicMock()
    registry._sessions = {}

    with patch("main.session_registry", registry):
        from main import mcp_status

        resp = await mcp_status()
        data = resp["data"]
        assert data["sessions"] == []
        assert data["mcp_enabled"] is False


# ── Fix-7: session create tab-cache ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_drops_tab_cache_before_connect():
    """create() must reset the client tab cache so connect_to_target sees
    the freshly opened tab (not a stale cached list)."""
    reg = SessionRegistry()
    fake_client = _make_fake_client()

    with patch.object(reg, "_open_tab_http", AsyncMock(return_value="tab-42")), \
         patch.object(reg, "_reap_orphan_tabs", AsyncMock(return_value=0)), \
         patch.object(reg, "_evict_lru", AsyncMock(return_value=None)), \
         patch("session_registry.CDPClient", return_value=fake_client), \
         patch("session_registry.uuid.uuid4", return_value=types.SimpleNamespace(hex="sess-42")):
        fake_client._tabs_cache = [{"id": "stale-tab", "type": "page"}]
        fake_client._tabs_cache_ts = 123.0
        await reg.create("http://127.0.0.1:9999")

    # The cache must be dropped BEFORE connect_to_target.
    connect_calls = fake_client.connect_to_target.await_args_list
    assert len(connect_calls) == 1
    assert connect_calls[0].args[0] == "tab-42"
    assert fake_client._tabs_cache == []
    assert fake_client._tabs_cache_ts == 0
    assert reg.get("sess-42") is not None
    assert reg.get("sess-42").tab_id == "tab-42"


@pytest.mark.asyncio
async def test_create_sets_ws_tab_id_to_new_tab():
    """After create(), the client's WS binding must point at the new tab."""
    reg = SessionRegistry()
    fake_client = _make_fake_client()

    async def fake_connect(tab_id: str):
        fake_client._ws_tab_id = tab_id
        fake_client.is_connected = True

    with patch.object(reg, "_open_tab_http", AsyncMock(return_value="tab-99")), \
         patch.object(reg, "_reap_orphan_tabs", AsyncMock(return_value=0)), \
         patch.object(reg, "_evict_lru", AsyncMock(return_value=None)), \
         patch("session_registry.CDPClient", return_value=fake_client), \
         patch("session_registry.uuid.uuid4", return_value=types.SimpleNamespace(hex="sess-99")):
        fake_client.connect_to_target = AsyncMock(side_effect=fake_connect)
        await reg.create("http://127.0.0.1:9999")

    sess = reg.get("sess-99")
    assert sess is not None
    assert sess.tab_id == "tab-99"
    assert fake_client._ws_tab_id == "tab-99"
    assert fake_client.is_connected is True


def test_run_async_wrapper():
    """Wrap the async tests so plain pytest (no anyio plugin) runs them."""
    for name in dir(sys.modules[__name__]):
        obj = getattr(sys.modules[__name__], name)
        if name.startswith("test_") and asyncio.iscoroutinefunction(obj):
            setattr(
                sys.modules[__name__],
                name,
                lambda _obj=obj: asyncio.run(_obj()),
            )


test_run_async_wrapper()
