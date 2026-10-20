"""A session can answer JavaScript dialogs by itself (2026-10-20).

Default stays manual (an agent must answer a confirm on purpose). `policy:dismiss` or
`policy:accept` answers each later dialog at once and reports it as `dialogs_auto_handled`.
"""

import asyncio

import pytest

from cdp_client import CDPClient


def _client():
    c = CDPClient.__new__(CDPClient)
    c._open_dialog = None
    c.dialog_policy = "manual"
    c.auto_handled_dialogs = []
    sent = []

    async def send(method, **params):
        sent.append((method, params))
        return {}

    c._send_command = send
    return c, sent


def test_default_policy_is_manual():
    c = CDPClient()
    assert c.dialog_policy == "manual"
    assert c.auto_handled_dialogs == []


def test_unknown_policy_is_refused():
    c, _ = _client()
    with pytest.raises(ValueError):
        asyncio.run(c.set_dialog_policy("always"))


def test_dismiss_policy_answers_with_accept_false_and_records_it():
    c, sent = _client()
    asyncio.run(c.set_dialog_policy("dismiss"))
    asyncio.run(c._auto_answer_dialog({"type": "confirm", "message": "Delete?"}, None))
    assert sent == [("Page.handleJavaScriptDialog", {"accept": False})]
    assert c.auto_handled_dialogs == [{"type": "confirm", "message": "Delete?", "answered": "dismiss"}]


def test_accept_policy_keeps_the_default_prompt_text():
    c, sent = _client()
    asyncio.run(c.set_dialog_policy("accept"))
    asyncio.run(c._auto_answer_dialog({"type": "prompt", "message": "Name?"}, "anon"))
    assert sent == [("Page.handleJavaScriptDialog", {"accept": True, "promptText": "anon"})]


def test_a_vanished_dialog_does_not_raise():
    c, _ = _client()

    async def boom(method, **params):
        raise RuntimeError("no dialog showing")

    c._send_command = boom
    asyncio.run(c.set_dialog_policy("dismiss"))
    asyncio.run(c._auto_answer_dialog({"type": "alert", "message": "x"}, None))
    assert c.auto_handled_dialogs == []


@pytest.mark.asyncio
async def test_mcp_dialog_handle_sets_the_policy(monkeypatch):
    import json

    from mcp_server import tools

    c, _ = _client()

    async def fake_target():
        return c, None

    monkeypatch.setattr(tools, "_target", fake_target)
    out = json.loads(await tools.dialog_handle("policy:dismiss"))
    assert c.dialog_policy == "dismiss"
    assert "invalid" not in json.dumps(out)
    bad = await tools.dialog_handle("policy:sometimes")
    assert "invalid_action" in bad
