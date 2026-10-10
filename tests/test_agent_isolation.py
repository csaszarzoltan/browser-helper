"""Agent instance isolation and the MCP tab/navigation contract."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_env_overrides_point_the_instance_at_its_own_profile_and_port(tmp_path, monkeypatch):
    from settings_manager import SettingsManager

    monkeypatch.setenv("BH_CHROME_PROFILE_DIR", str(tmp_path / "agent-profile"))
    monkeypatch.setenv("BH_CHROME_DEBUG_PORT", "9560")
    mgr = SettingsManager(path=str(tmp_path / "settings.json"))
    assert mgr.get("chrome_profile_dir") == str(tmp_path / "agent-profile")
    assert mgr.get("chrome_debug_port") == 9560


def test_isolated_instance_never_writes_the_shared_settings_file(tmp_path, monkeypatch):
    from settings_manager import SettingsManager

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"chrome_profile_dir": "/user/profile", "chrome_debug_port": 9557}))
    monkeypatch.setenv("BH_CHROME_PROFILE_DIR", str(tmp_path / "agent-profile"))
    mgr = SettingsManager(path=str(path))
    mgr.set(chrome_pid=123, chrome_launched_port=9560)  # what a Chrome launch does
    assert json.loads(path.read_text()) == {"chrome_profile_dir": "/user/profile", "chrome_debug_port": 9557}


def test_without_overrides_the_shared_file_is_unchanged_behaviour(tmp_path, monkeypatch):
    from settings_manager import SettingsManager

    monkeypatch.delenv("BH_CHROME_PROFILE_DIR", raising=False)
    monkeypatch.delenv("BH_CHROME_DEBUG_PORT", raising=False)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"chrome_profile_dir": "/user/profile", "chrome_debug_port": 9557}))
    mgr = SettingsManager(path=str(path))
    assert mgr.get("chrome_debug_port") == 9557
    mgr.set(chrome_pid=7)
    assert json.loads(path.read_text())["chrome_pid"] == 7


def test_navigate_schema_offers_wait_for():
    from mcp_server.registry import build_tool_defs

    props = {d.name: d for d in build_tool_defs()}["navigate"].parameters["properties"]
    assert "wait_for" in props and "timeout" in props


def test_tab_not_open_message_says_why_and_what_to_do(monkeypatch):
    import asyncio

    import main

    class _Client:
        async def discover_tabs(self):
            return [{"id": "other", "type": "page", "title": "x", "url": "https://x"}]

    monkeypatch.setattr(main, "client", _Client())
    result = asyncio.run(main._assert_tab_exists("gone-tab"))
    message = json.loads(bytes(result.body))["error"]["message"]
    assert "is not open" in message and "get_tabs" in message
