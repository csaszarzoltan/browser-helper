"""act can click a text target inside a container and pick one of several matches.

Found 2026-10-13: click_by_text already takes container_selector and nth, but act dropped them.
AgentTarget had a `within` field that nothing read, so an agent that set it got a click on the
first match anywhere on the page, with no error. Now `within` scopes a text click, `nth` picks
the match, and either one on a selector or backend target is refused instead of ignored.
"""

from unittest.mock import AsyncMock


def _act_click(monkeypatch, target):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(type(main.client), "is_connected", property(lambda self: True))
    click_by_text = AsyncMock(return_value={"status": "ok", "tag": "BUTTON", "text": "Edit"})
    click = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(main.client, "click_by_text", click_by_text, raising=False)
    monkeypatch.setattr(main.client, "click", click, raising=False)
    response = TestClient(main.app).post("/agent/act", json={
        "action": "click", "target": target, "observe_after": False})
    return response, click_by_text, click


def test_act_click_by_text_is_scoped_to_the_container_and_picks_the_nth_match(monkeypatch):
    response, click_by_text, _ = _act_click(monkeypatch, {"text": "Edit", "within": "#list-b", "nth": 1})
    assert response.status_code == 200
    kwargs = click_by_text.await_args.kwargs
    assert kwargs["container_selector"] == "#list-b"
    assert kwargs["nth"] == 1


def test_act_click_refuses_within_and_nth_on_a_selector_target(monkeypatch):
    response, _, click = _act_click(monkeypatch, {"selector": "#save", "within": "#list-b"})
    assert response.status_code >= 400
    assert "within" in response.text
    click.assert_not_awaited()
