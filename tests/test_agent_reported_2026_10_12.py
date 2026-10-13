"""Defects an agent hit on the MCP tool surface (reported 2026-10-12), each pinned to its cause.

The browser-facing parts (the element click by identity, the key events in Chrome) were
checked live against the isolated test browser; the tests here cover the decisions and the
wire parameters that do not need a browser.
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _page(*names):
    nodes = [{"nodeId": "1", "role": {"value": "main"}, "name": {"value": "Page"},
              "childIds": [str(i) for i in range(2, 2 + len(names))], "backendDOMNodeId": 101}]
    for i, name in enumerate(names, start=2):
        nodes.append({"nodeId": str(i), "role": {"value": "button"}, "name": {"value": name},
                      "childIds": [], "backendDOMNodeId": 100 + i})
    return {"nodes": nodes}


def _build(raw):
    from agent_navigation import AccessibilityTreeBuilder

    return AccessibilityTreeBuilder().build(raw, page={"url": "https://a.test/", "title": "t"}, scope="page")


# Typing: a punctuation key sent with a virtual key code is read by Chrome as a
# navigation or editing key (ord(".") is Delete, ord("%") is Left arrow).

def test_punctuation_is_dispatched_without_a_virtual_key_code():
    from behavioral_typing import BehavioralTyping

    for char in ".%&'()-/:,":
        params = BehavioralTyping._key_identifier(char)
        assert params["text"] == char
        assert not params.get("windowsVirtualKeyCode"), char
        assert not params.get("nativeVirtualKeyCode"), char


def test_a_key_event_for_punctuation_carries_no_virtual_key_code():
    from behavioral_typing import BehavioralTyping

    class _Client:
        def __init__(self):
            self.sent = []

        async def _send_command(self, method, params=None, **_):
            self.sent.append(params)
            return {}

    client = _Client()
    asyncio.run(BehavioralTyping._dispatch_char_sequence(client, "."))
    assert [p["type"] for p in client.sent] == ["keyDown", "keyUp"]
    assert all("windowsVirtualKeyCode" not in p and "nativeVirtualKeyCode" not in p for p in client.sent)


# Verification: text that was already on the page does not show that the action worked.

def test_text_already_on_the_page_does_not_satisfy_text_visible():
    from agent_navigation import validate_expectations

    before = _build(_page("Edit description", "Add"))
    after = _build(_page("Edit description", "Add"))
    result = validate_expectations(before, after, {"text_visible": "Add"})
    assert result["satisfied"] is False
    assert result["already_visible"] == ["Add"]


def test_text_visible_matches_a_whole_phrase_and_new_text_satisfies_it():
    from agent_navigation import validate_expectations

    before = _build(_page("Edit"))
    assert validate_expectations(before, _build(_page("Edit", "Address")), {"text_visible": "Add"})["satisfied"] is False
    assert validate_expectations(before, _build(_page("Edit", "Add new")), {"text_visible": "Add"})["satisfied"] is True


# Disabled controls: a click on one must not be reported as done.

def test_a_click_on_a_disabled_element_is_refused_and_no_mouse_event_is_sent(monkeypatch):
    from cdp_client import CDPClient

    client = CDPClient(cdp_http_url="http://127.0.0.1:1")
    sent = []

    async def fake_activate():
        return None

    async def fake_evaluate(js):
        return {"status": "ok", "result": {"x": 10, "y": 10, "tag": "BUTTON", "disabled": True}}

    async def fake_send(method, params=None, **_):
        sent.append(method)
        return {}

    monkeypatch.setattr(client, "_activate_current", fake_activate)
    monkeypatch.setattr(client, "evaluate", fake_evaluate)
    monkeypatch.setattr(client, "_send_command", fake_send)
    out = asyncio.run(client.click("#next"))
    assert out["status"] == "error" and out["code"] == "not_actionable"
    assert "Input.dispatchMouseEvent" not in sent


# Type read-back: the caller learns whether the field holds what was typed, without the value being echoed.

def _type_target(stored):
    class _Target:
        async def type_text(self, selector, text):
            return {"status": "ok"}

        async def evaluate(self, js):
            return {"status": "ok", "result": stored}

    return _Target()


def _run_op_passthrough(op, fn, *args, **kwargs):
    return fn(*args, **kwargs)


def test_type_reports_a_read_back_match_without_echoing_the_value(monkeypatch):
    from mcp_server import tools

    async def fake_target(target):
        return target, _run_op_passthrough

    monkeypatch.setattr(tools, "_target", lambda: fake_target(_type_target("https://github.com/a.b")))
    out = json.loads(asyncio.run(tools.type(selector="#web", text="https://github.com/a.b")))
    assert out["meta"]["readback"] == {"matches": True}
    assert "github.com" not in json.dumps(out["meta"])


def test_type_reports_a_read_back_mismatch(monkeypatch):
    from mcp_server import tools

    async def fake_target(target):
        return target, _run_op_passthrough

    monkeypatch.setattr(tools, "_target", lambda: fake_target(_type_target("githubcom")))
    out = json.loads(asyncio.run(tools.type(selector="#web", text="https://github.com/")))
    assert out["status"] == "ok" and out["meta"]["readback"] == {"matches": False}


# Build identity: the MCP process says which commit it runs and whether the checkout has moved on.

def test_session_status_reports_the_commit_this_process_runs_and_whether_it_is_behind(monkeypatch):
    from mcp_server import tools

    monkeypatch.setattr(tools, "_repo_head", lambda: ("abc1234", 2))
    out = json.loads(asyncio.run(tools.session_status()))
    build = out["data"]["build"]
    assert build["code_commit"] == tools._CODE_COMMIT
    assert build["checkout_head"] == "abc1234"
    assert build["commits_behind_checkout"] == 2 and build["stale"] is True
    assert build["started_at"]


def test_session_status_is_not_stale_when_the_checkout_has_not_moved(monkeypatch):
    from mcp_server import tools

    monkeypatch.setattr(tools, "_repo_head", lambda: (tools._CODE_COMMIT, 0))
    build = json.loads(asyncio.run(tools.session_status()))["data"]["build"]
    assert build["stale"] is False


def test_screenshot_returns_a_file_path_and_no_copy_of_the_image(monkeypatch, tmp_path):
    import main
    from mcp_server import tools

    class _Store:
        root = tmp_path

        def put(self, raw, mime, ext, meta):
            return {"artifact_id": "art_test", "size_bytes": len(raw), "expires_at": 0}

    class _Target:
        async def screenshot(self, **_):
            return {"status": "ok", "data": "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="}

    async def fake_target():
        async def run_op(op, fn, *args, **kwargs):
            return main.api_success(op, await fn(*args, **kwargs))

        return _Target(), run_op

    monkeypatch.setattr(main, "artifact_store", _Store())
    monkeypatch.setattr(tools, "_target", fake_target)
    raw = asyncio.run(tools.screenshot())
    out = json.loads(raw)
    assert out["data"]["path"].endswith("art_test.jpg")
    assert "QUJD" not in raw  # neither data nor the deprecated result alias carries the image


# Fill: each field is read back, but the act result must also say whether every field kept its value.

def _act_fill(monkeypatch, field_results):
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(type(main.client), "is_connected", property(lambda self: True))
    fill = AsyncMock(return_value={"status": "ok", "fields": [{"selector": "#email", "value": "a@b.test"}],
                                   "result": {"fields_filled": len(field_results), "results": field_results}})
    monkeypatch.setattr(main.client, "smart_form_fill", fill, raising=False)
    response = TestClient(main.app).post("/agent/act", json={
        "action": "fill", "target": {"selector": "#email"}, "value": "a@b.test", "observe_after": False})
    assert response.status_code == 200
    return response.json()["data"]["result"]


def test_act_fill_reports_a_field_that_did_not_keep_its_value(monkeypatch):
    result = _act_fill(monkeypatch, [{"field": "#email", "status": "ok", "verified": False, "value_after": "a@b"}])
    assert result["verified"] is False
    assert result["not_kept"] == ["#email"]


def test_act_fill_reports_all_fields_kept(monkeypatch):
    result = _act_fill(monkeypatch, [{"field": "#email", "status": "ok", "verified": True, "value_after": "a@b.test"}])
    assert result["verified"] is True
    assert "not_kept" not in result
