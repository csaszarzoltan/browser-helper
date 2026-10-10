"""MCP token-efficiency contracts: tool profiles, usage hints, and serverInfo version."""
import asyncio
import os
import re
from pathlib import Path

import pytest

from mcp_server.registry import build_tool_defs

REPO = Path(__file__).resolve().parents[1]


def _names(defs):
    return {t.name for t in defs}


def _project_version():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


def test_default_profile_is_full_78(monkeypatch):
    monkeypatch.delenv("MCP_PROFILE", raising=False)
    assert len(build_tool_defs()) == 78


def test_core_profile_is_small_subset_of_full(monkeypatch):
    monkeypatch.setenv("MCP_PROFILE", "core")
    core = _names(build_tool_defs())
    monkeypatch.delenv("MCP_PROFILE")
    full = _names(build_tool_defs())
    assert 12 <= len(core) <= 15, sorted(core)
    assert core <= full


def test_core_profile_excludes_snapshot_and_keeps_observe_act(monkeypatch):
    monkeypatch.setenv("MCP_PROFILE", "core")
    core = _names(build_tool_defs())
    assert {"navigate", "observe", "act", "screenshot"} <= core
    assert "snapshot" not in core


def test_unknown_profile_is_rejected(monkeypatch):
    monkeypatch.setenv("MCP_PROFILE", "bogus")
    with pytest.raises(ValueError):
        build_tool_defs()


def test_snapshot_description_says_it_is_not_an_accessibility_tree(monkeypatch):
    monkeypatch.delenv("MCP_PROFILE", raising=False)
    desc = {t.name: t.description for t in build_tool_defs()}
    assert "not an accessibility tree" in desc["snapshot"].lower()
    assert "observe" in desc["snapshot"].lower()


def test_observe_description_names_element_refs(monkeypatch):
    monkeypatch.delenv("MCP_PROFILE", raising=False)
    desc = {t.name: t.description for t in build_tool_defs()}
    assert "element_id" in desc["observe"]


def test_server_info_version_matches_pyproject():
    from mcp_server.server import MCPServer

    server = MCPServer()
    assert server.mcp._mcp_server.version == _project_version()
