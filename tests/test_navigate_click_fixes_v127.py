"""Regression tests for the 2026-08-11 agent-incident fixes:

1. POST /navigate accepts the URL in the JSON body (not just ?url= query)
2. POST /navigate with NO url → 422 with a CLEAR message
3. POST /click with a selector that matches nothing → 404 (not misleading 200)
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    return TestClient(main.app)


class TestNavigateBodyUrl:
    def test_navigate_accepts_json_body(self, app_client, monkeypatch):
        """POST /navigate with {\"url\": ...} body works (was 422-only via query)."""
        import main

        c = app_client
        called = {}

        async def fake_navigate(url):
            called["url"] = url
            return {"status": "ok", "frame_id": "f1", "url": url}

        monkeypatch.setattr(main.client, "navigate", fake_navigate)
        r = c.post("/navigate", json={"url": "https://example.com"})
        assert r.status_code == 200
        assert called["url"] == "https://example.com"
        assert r.json()["data"]["url"] == "https://example.com"

    def test_navigate_still_accepts_query_param(self, app_client, monkeypatch):
        """Legacy ?url= query param keeps working."""
        import main

        c = app_client
        called = {}

        async def fake_navigate(url):
            called["url"] = url
            return {"status": "ok", "frame_id": "f1", "url": url}

        monkeypatch.setattr(main.client, "navigate", fake_navigate)
        r = c.post("/navigate?url=https://example.org")
        assert r.status_code == 200
        assert called["url"] == "https://example.org"

    def test_navigate_missing_url_clear_422(self, app_client):
        """No url anywhere → 422 with an actionable message (was bare 422)."""

        c = app_client
        r = c.post("/navigate", json={})
        assert r.status_code == 422
        detail = r.json().get("detail", "")
        assert "url" in str(detail).lower()


class TestClickNotFound404:
    def test_click_missing_element_returns_404(self, app_client, monkeypatch):
        """CDP click {status: error, error: 'Element not found'} → HTTP 404."""
        import main

        c = app_client

        async def fake_click(selector):
            return {"status": "error", "error": f"Element not found: {selector}"}

        monkeypatch.setattr(main.client, "click", fake_click)
        r = c.post("/click", json={"selector": "#nope"})
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_click_success_still_200(self, app_client, monkeypatch):
        """Successful click stays 200 with the wrapped data."""
        import main

        c = app_client

        async def fake_click(selector):
            return {"status": "ok", "selector": selector, "position": {"x": 1, "y": 2}}

        monkeypatch.setattr(main.client, "click", fake_click)
        r = c.post("/click", json={"selector": "#btn"})
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "ok"
