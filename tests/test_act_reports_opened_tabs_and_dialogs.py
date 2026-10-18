"""A click that opens a tab or a dialog says so; a navigation blocked by a dialog says why.

Competitors added the same: chrome-devtools-mcp v1.11.0 (2026-10-15) "report pages opened by
input actions", playwright-mcp v0.0.83 (2026-09-28) "navigate and reload report a dialog opened
during page load instead of timing out".
"""

import asyncio
from unittest.mock import AsyncMock

import pytest


def _act(monkeypatch, tabs_before, tabs_after, dialog=None):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(type(main.client), "is_connected", property(lambda self: True))
    monkeypatch.setattr(main.client, "click_by_text", AsyncMock(return_value={"status": "ok"}), raising=False)
    monkeypatch.setattr(main.client, "_open_dialog", dialog, raising=False)
    seq = iter([tabs_before, tabs_after])
    monkeypatch.setattr(main, "_page_tabs", AsyncMock(side_effect=lambda tc: next(seq)))
    monkeypatch.setattr(main.session_registry, "owned_tab_ids", lambda: {"other-session-tab"})
    return TestClient(main.app).post("/agent/act", json={
        "action": "click", "target": {"text": "Open"}, "observe_after": False}).json()


def test_a_new_tab_is_reported_with_its_url(monkeypatch):
    body = _act(monkeypatch, {"t1": "https://a.test/"}, {"t1": "https://a.test/", "t2": "https://b.test/popup"})
    assert body["data"]["opened_tabs"] == [{"tab_id": "t2", "url": "https://b.test/popup"}]
    assert "switch_tab" in body["data"]["opened_tabs_hint"]


def test_another_sessions_tab_is_not_blamed_on_this_click(monkeypatch):
    body = _act(monkeypatch, {"t1": ""}, {"t1": "", "other-session-tab": "https://c.test/"})
    assert "opened_tabs" not in body["data"]


def test_no_new_tab_adds_nothing(monkeypatch):
    body = _act(monkeypatch, {"t1": ""}, {"t1": ""})
    assert "opened_tabs" not in body["data"]


def test_an_open_dialog_after_a_click_is_reported(monkeypatch):
    body = _act(monkeypatch, {"t1": ""}, {"t1": ""}, dialog={"type": "confirm", "message": "Delete?"})
    assert body["data"]["dialog_open"] == {"type": "confirm", "message": "Delete?"}
    assert "dialog_handle" in body["data"]["dialog_hint"]


def test_tab_list_failure_does_not_fail_the_click(monkeypatch):
    body = _act(monkeypatch, None, None)
    assert body["status"] == "ok"
    assert "opened_tabs" not in body["data"]


@pytest.mark.asyncio
async def test_wait_for_document_names_the_open_dialog_instead_of_timing_out():
    from cdp_client import CDPClient, CDPError

    c = CDPClient()
    c._open_dialog = {"type": "alert", "message": "Saved"}
    c._document_state = AsyncMock(side_effect=AssertionError("must not wait on a frozen page"))
    with pytest.raises(CDPError, match="alert dialog is open.*dialog_handle"):
        await asyncio.wait_for(c._wait_for_document("load", 0.0, 15.0), timeout=2)


@pytest.mark.asyncio
async def test_navigate_refuses_at_once_while_a_dialog_is_open():
    """Live 2026-10-18: Page.navigate itself hangs behind a confirm, so the check must come first."""
    from cdp_client import CDPClient, CDPError

    c = CDPClient()
    c._open_dialog = {"type": "confirm", "message": "Delete?"}
    c._send_command = AsyncMock(side_effect=AssertionError("must not send Page.navigate"))
    with pytest.raises(CDPError, match="confirm dialog is open"):
        await asyncio.wait_for(c.navigate("https://x.test/"), timeout=2)


def test_navigate_route_returns_a_run_op_error_without_polling_the_frozen_page(monkeypatch):
    """Live 2026-10-18: the ready wait polled a page frozen by a dialog and held the 400 for 30 s."""
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(type(main.client), "is_connected", property(lambda self: True))
    err = main.api_error("navigate", "operation_failed", "a JavaScript confirm dialog is open", 400)
    monkeypatch.setattr(main, "run_op", AsyncMock(return_value=err))
    poll = AsyncMock(side_effect=AssertionError("must not poll readyState after an error"))
    monkeypatch.setattr(main.client, "evaluate", poll, raising=False)
    r = TestClient(main.app).post("/navigate?url=https://x.test/")
    assert r.status_code == 400
    assert "dialog is open" in r.text
    poll.assert_not_awaited()
