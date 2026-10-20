"""A click that changed nothing on the page says so (2026-10-20).

chrome-devtools-mcp #2199 (2026-06-11) reports clicks whose input never reached the page while the
tool answered "Successfully clicked"; a user's own agent saw the same ("ok", but no modal and no
way to tell). The result now carries effect "none" when the page fingerprint is unchanged.
"""

from unittest.mock import AsyncMock

import pytest


def _click(monkeypatch, before, after, dialog=None, tabs=None):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(type(main.client), "is_connected", property(lambda self: True))
    monkeypatch.setattr(main.client, "click_by_text", AsyncMock(return_value={"status": "ok"}), raising=False)
    monkeypatch.setattr(main.client, "_open_dialog", dialog, raising=False)
    seq = iter([before, after])
    monkeypatch.setattr(main, "_page_fingerprint", AsyncMock(side_effect=lambda tc: next(seq)))
    if tabs is not None:
        tab_seq = iter(tabs)
        monkeypatch.setattr(main, "_page_tabs", AsyncMock(side_effect=lambda tc: next(tab_seq)))
    monkeypatch.setattr(main.session_registry, "owned_tab_ids", lambda: set())
    return TestClient(main.app).post("/agent/act", json={
        "action": "click", "target": {"text": "Save"}, "observe_after": False}).json()["data"]


def test_unchanged_page_reports_no_effect(monkeypatch):
    data = _click(monkeypatch, "u|a|10|5|1|0|0|0", "u|a|10|5|1|0|0|0")
    assert data["effect"] == "none"
    assert "observe again" in data["effect_hint"]


def test_changed_page_reports_nothing_extra(monkeypatch):
    data = _click(monkeypatch, "u|a|10|5|1|0|0|0", "u|a|11|9|2|0|0|0")
    assert "effect" not in data


def test_unreadable_page_reports_nothing_extra(monkeypatch):
    data = _click(monkeypatch, None, None)
    assert "effect" not in data


def test_a_new_tab_is_an_effect(monkeypatch):
    data = _click(monkeypatch, "same", "same", tabs=[{"t1": ""}, {"t1": "", "t2": "https://x.test/"}])
    assert "effect" not in data
    assert data["opened_tabs"]


def test_an_open_dialog_is_an_effect(monkeypatch):
    data = _click(monkeypatch, "same", "same", dialog={"type": "alert", "message": "Hi"})
    assert "effect" not in data


@pytest.mark.asyncio
async def test_fingerprint_is_none_when_the_page_cannot_answer():
    import main

    class Frozen:
        async def evaluate(self, expr):
            raise RuntimeError("frozen")

    assert await main._page_fingerprint(Frozen()) is None


@pytest.mark.asyncio
async def test_fingerprint_unwraps_the_evaluate_envelope():
    import main

    class Page:
        async def evaluate(self, expr):
            return {"status": "ok", "result": "u|a|1", "type": "string"}

    class Broken:
        async def evaluate(self, expr):
            return {"status": "error", "error": "boom", "result": None}

    assert await main._page_fingerprint(Page()) == "u|a|1"
    assert await main._page_fingerprint(Broken()) is None
