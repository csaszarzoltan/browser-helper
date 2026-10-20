"""A disabled control says why, and a suggestion can be picked by its text (2026-10-20)."""

import json
from unittest.mock import AsyncMock

import pytest

import page_hints


class Page:
    def __init__(self, result):
        self._result = result
        self.js = None

    async def evaluate(self, js):
        self.js = js
        return self._result


@pytest.mark.asyncio
async def test_disabled_reason_returns_the_page_text():
    page = Page({"status": "ok", "result": "the form has invalid fields: email [Please fill out this field.]"})
    out = await page_hints.disabled_reason(page, selector="#save")
    assert out.startswith("the form has invalid fields")
    assert '"#save"' in page.js


@pytest.mark.asyncio
async def test_disabled_reason_is_empty_when_the_page_cannot_answer():
    class Frozen:
        async def evaluate(self, js):
            raise RuntimeError("frozen")

    assert await page_hints.disabled_reason(Frozen(), text="Save") == ""
    assert await page_hints.disabled_reason(Page({"status": "error", "result": None}), text="Save") == ""


@pytest.mark.asyncio
async def test_find_suggestion_parses_the_probe():
    page = Page({"status": "ok", "result": json.dumps({"status": "ok", "x": 10, "y": 20, "text": "python"})})
    assert (await page_hints.find_suggestion(page, "Python"))["x"] == 10


@pytest.mark.asyncio
async def test_find_suggestion_without_an_answer_is_not_found():
    assert (await page_hints.find_suggestion(Page({"status": "ok", "result": None}), "x"))["code"] == "not_found"


def _act(monkeypatch, body, find=None, disabled=None):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(type(main.client), "is_connected", property(lambda self: True))
    click_xy = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(main.client, "click_coordinates", click_xy, raising=False)
    monkeypatch.setattr(main.client, "click_by_text",
                        AsyncMock(return_value={"status": "error", "code": "not_actionable"}), raising=False)
    monkeypatch.setattr(page_hints, "find_suggestion", AsyncMock(return_value=find))
    monkeypatch.setattr(page_hints, "disabled_reason", AsyncMock(return_value=disabled or ""))
    r = TestClient(main.app).post("/agent/act", json={**body, "observe_after": False})
    return r, click_xy


def test_pick_suggestion_clicks_the_matching_option(monkeypatch):
    r, click_xy = _act(monkeypatch, {"action": "pick_suggestion", "value": "Python"},
                       find={"status": "ok", "x": 40, "y": 50, "text": "python"})
    assert r.status_code == 200
    click_xy.assert_awaited_once_with(40, 50)
    assert r.json()["data"]["result"]["picked"] == "python"


def test_pick_suggestion_with_two_matches_is_refused(monkeypatch):
    r, click_xy = _act(monkeypatch, {"action": "pick_suggestion", "value": "Py"},
                       find={"status": "error", "code": "ambiguous", "error": "2 suggestions match"})
    assert r.status_code >= 400
    assert "2 suggestions match" in r.text
    click_xy.assert_not_awaited()


def test_pick_suggestion_not_found_lists_what_is_visible(monkeypatch):
    r, _ = _act(monkeypatch, {"action": "pick_suggestion", "value": "Rust"},
                find={"status": "error", "code": "not_found", "error": "no visible suggestion matches; visible: go | java"})
    assert r.status_code >= 400
    assert "visible: go | java" in r.text


def test_disabled_click_carries_the_reason(monkeypatch):
    r, _ = _act(monkeypatch, {"action": "click", "target": {"text": "Save"}},
                disabled="the form has invalid fields: email")
    assert r.status_code >= 400
    assert "is disabled; it was not clicked (the form has invalid fields: email)" in r.text
