"""Guards for the MCP tool guidance pass: real descriptions, the in-process act
path, the envelope-only result, and the new testing tools' registration."""

import json
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def _defs(monkeypatch):
    monkeypatch.delenv("MCP_PROFILE", raising=False)
    from mcp_server.registry import build_tool_defs
    return {d.name: d for d in build_tool_defs()}


def test_every_tool_has_a_real_description(monkeypatch):
    defs = _defs(monkeypatch)
    template = "backed by capability"
    for name, d in defs.items():
        assert template not in d.description, f"{name} still has the placeholder text"
        assert len(d.description.split()) >= 4, f"{name} description too short: {d.description!r}"


def test_overlapping_tools_say_which_to_use_instead(monkeypatch):
    defs = _defs(monkeypatch)
    assert "act" in defs["click"].description
    assert "browser_take_screenshot" in defs["screenshot"].description
    assert "browser_navigate" in defs["navigate"].description


def test_seven_testing_tools_are_registered_on_browser_core(monkeypatch):
    defs = _defs(monkeypatch)
    for name in ["set_viewport", "print_pdf", "set_geolocation", "set_offline",
                 "get_performance_metrics", "drag", "accessibility_audit"]:
        assert name in defs, name
        assert defs[name].capability_id == "browser.core"


def test_act_and_click_advertise_expect(monkeypatch):
    defs = _defs(monkeypatch)
    assert "expect" in defs["act"].parameters["properties"]
    assert "expect" in defs["click"].parameters["properties"]


def test_mcp_result_drops_deprecated_result_alias():
    import sys
    sys.path.insert(0, str(SRC))
    from mcp_server.serialization import json_dumps

    envelope = {"status": "ok", "operation": "navigate", "data": {"url": "x"},
                "error": None, "meta": {}, "result": {"url": "x"}}
    out = json.loads(json_dumps(envelope))
    assert "result" not in out
    assert out["data"] == {"url": "x"}


def test_mcp_result_keeps_result_when_it_differs():
    import sys
    sys.path.insert(0, str(SRC))
    from mcp_server.serialization import json_dumps

    envelope = {"status": "ok", "operation": "x", "data": 1, "error": None,
                "meta": {}, "result": 2}
    assert json.loads(json_dumps(envelope))["result"] == 2


def test_act_no_longer_calls_a_hardcoded_loopback_port():
    source = (SRC / "mcp_server" / "tools.py").read_text(encoding="utf-8")
    assert "127.0.0.1:8020" not in source
    assert "urlopen" not in source
