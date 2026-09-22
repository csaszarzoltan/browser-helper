"""v1.36.2: ``/session/new?url=...`` must really open the requested page.

Root cause found live on 2026-09-22: Chrome's ``PUT /json/new`` only honours
the BARE-QUERY form (``/json/new?https://example.com/``).  The
``?url=https://example.com/`` form is silently ignored and the target opens
as ``about:blank`` — verified against Chrome 153.0.8010.52:

    PUT /json/new?url=https://example.com/  → url 'about:blank'
    PUT /json/new?https://example.com/      → url 'https://example.com/'

``session_registry._open_tab_http`` used httpx ``params={"url": url}``, which
encodes the dropped form, so EVERY session tab was blank.  Consequences in
the field: the keep-warm probe never matched its URL and minted another blank
tab every cycle (300 s), and an agent that opened one real page saw a pile of
empty ``about:blank`` tabs beside it.

These tests pin the URL-building contract without needing a live Chrome.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from session_registry import SessionRegistry


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _patch_httpx(monkeypatch, captured, payload):
    """Capture the exact URL passed to ``httpx.AsyncClient.put``.

    ``_open_tab_http`` imports httpx locally (``import httpx`` inside the
    function body), so the patch target is the real module attribute.
    """
    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def put(self, url, *a, **kw):
            captured.append({"url": url, "kwargs": kw})
            return _Resp(payload)

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


def test_open_tab_uses_bare_query_form(monkeypatch):
    """The URL must be appended raw — NOT as ``?url=`` (Chrome drops that)."""
    captured: list[dict] = []
    _patch_httpx(monkeypatch, captured, {"id": "TAB1", "url": "http://127.0.0.1:8080/"})

    reg = SessionRegistry()
    client = MagicMock()
    client.cdp_http_url = "http://127.0.0.1:9557"
    client.navigate = AsyncMock(return_value={"status": "ok"})

    tab_id = asyncio.run(reg._open_tab_http(client, "http://127.0.0.1:8080/"))

    assert tab_id == "TAB1"
    requested = captured[0]["url"]
    assert requested == "http://127.0.0.1:9557/json/new?http://127.0.0.1:8080/", (
        f"wrong /json/new form: {requested}"
    )
    assert "url=" not in requested, (
        "the ?url= form is silently ignored by Chrome — the tab opens blank"
    )
    assert captured[0]["kwargs"] == {}, (
        "params= re-encodes into the dropped ?url= form"
    )


def test_open_tab_about_blank_has_no_query(monkeypatch):
    """about:blank needs no query string at all."""
    captured: list[dict] = []
    _patch_httpx(monkeypatch, captured, {"id": "TAB2", "url": "about:blank"})

    reg = SessionRegistry()
    client = MagicMock()
    client.cdp_http_url = "http://127.0.0.1:9557"
    client.navigate = AsyncMock(return_value={"status": "ok"})

    asyncio.run(reg._open_tab_http(client, "about:blank"))

    assert captured[0]["url"] == "http://127.0.0.1:9557/json/new"
    client.navigate.assert_not_awaited()


def test_open_tab_falls_back_to_navigate_when_still_blank(monkeypatch):
    """If Chrome ignores the URL anyway, navigate explicitly on the new tab."""
    captured: list[dict] = []
    # Chrome answers with a blank tab despite the raw query.
    _patch_httpx(monkeypatch, captured, {"id": "TAB3", "url": "about:blank"})

    reg = SessionRegistry()
    client = MagicMock()
    client.cdp_http_url = "http://127.0.0.1:9557"
    client.navigate = AsyncMock(return_value={"status": "ok"})

    asyncio.run(reg._open_tab_http(client, "https://example.com/"))

    client.navigate.assert_awaited_once_with("https://example.com/")
    assert client._ws_tab_id == "TAB3", (
        "the fallback navigate must target the tab we just created"
    )


def test_open_tab_no_fallback_when_url_already_applied(monkeypatch):
    """No redundant navigate when the tab already carries the URL."""
    captured: list[dict] = []
    _patch_httpx(monkeypatch, captured, {"id": "TAB4", "url": "https://example.com/"})

    reg = SessionRegistry()
    client = MagicMock()
    client.cdp_http_url = "http://127.0.0.1:9557"
    client.navigate = AsyncMock(return_value={"status": "ok"})

    asyncio.run(reg._open_tab_http(client, "https://example.com/"))

    client.navigate.assert_not_awaited()
