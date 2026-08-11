"""F1 — Auth-session clone / cookie porting (v1.27.0).

Covers:
- CDPClient.set_cookies bulk import (contract)
- REST export/import/clone endpoints (integration via TestClient)
- 404 when the session does not exist
- Invalid payload rejection
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_client(monkeypatch):
    """TestClient without a context manager (avoids service startup)."""
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    return TestClient(main.app)


class TestSetCookiesContract:
    """CDPClient.set_cookies bulk import (unit, mocked CDP)."""

    @pytest.mark.asyncio
    async def test_set_cookies_empty_ok(self):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        res = await client.set_cookies([])
        assert res["status"] == "ok"
        assert res["imported"] == 0

    @pytest.mark.asyncio
    async def test_set_cookies_sends_command(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        sent = {}

        async def fake_activate():
            return None

        async def fake_send(cmd, params=None):
            sent["cmd"] = cmd
            sent["params"] = params
            return {}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "_send_command", fake_send)

        cookies = [{"name": "cf_clearance", "value": "abc", "domain": ".example.com"}]
        res = await client.set_cookies(cookies)
        assert res["status"] == "ok"
        assert res["imported"] == 1
        assert sent["cmd"] == "Network.setCookies"
        assert sent["params"]["cookies"] == cookies


class TestCookieRestEndpoints:
    """REST export/import/clone via TestClient."""

    def _fake_session(self, main, session_id="sess123"):
        """Register a fake session in the registry with a stub client."""
        from cdp_client import CDPClient

        sess = main.session_registry.get(session_id)
        if sess is None:
            from session_registry import Session

            client = CDPClient(cdp_http_url="http://127.0.0.1:1")
            sess = Session(session_id=session_id, client=client, tab_id="tab1")
            main.session_registry._sessions[session_id] = sess
        return sess

    def test_export_cookies_ok(self, app_client, monkeypatch):
        import main

        c = app_client
        sess = self._fake_session(main)

        async def fake_get_cookies():
            return {"status": "ok", "count": 2, "cookies": [
                {"name": "a", "value": "1", "domain": ".x.com"},
                {"name": "b", "value": "2", "domain": ".x.com"},
            ]}

        monkeypatch.setattr(sess.client, "get_cookies", fake_get_cookies)
        r = c.get("/session/sess123/export-cookies")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["data"]["count"] == 2
        assert body["data"]["cookies"][0]["name"] == "a"

    def test_export_cookies_404(self, app_client):
        c = app_client
        r = c.get("/session/nope/export-cookies")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "session_not_found"

    def test_import_cookies_ok(self, app_client, monkeypatch):
        import main

        c = app_client
        sess = self._fake_session(main)

        async def fake_set_cookies(cookies):
            return {"status": "ok", "imported": len(cookies)}

        monkeypatch.setattr(sess.client, "set_cookies", fake_set_cookies)
        r = c.post("/session/sess123/import-cookies", json={"cookies": [
            {"name": "cf_clearance", "value": "x", "domain": ".example.com"},
        ]})
        assert r.status_code == 200
        assert r.json()["data"]["imported"] == 1

    def test_import_cookies_invalid_payload(self, app_client):
        c = app_client
        r = c.post("/session/sess123/import-cookies", json={"cookies": "not-a-list"})
        assert r.status_code == 400
        assert "invalid_payload" in r.json()["error"]["code"]

    def test_clone_session_ok(self, app_client, monkeypatch):
        import main

        c = app_client
        src = self._fake_session(main)
        imported = {}

        async def fake_get_cookies():
            return {"status": "ok", "count": 1, "cookies": [
                {"name": "cf_clearance", "value": "xyz", "domain": ".example.com"},
            ]}

        async def fake_create(cdp_url, url="about:blank", profile_dir=None):
            from cdp_client import CDPClient
            from session_registry import Session

            new_client = CDPClient(cdp_http_url=cdp_url)
            new_sess = Session(session_id="new123", client=new_client, tab_id="tab2")
            # The cloned session's client gets the stub set_cookies right away
            monkeypatch.setattr(new_client, "set_cookies", fake_set_cookies)
            main.session_registry._sessions["new123"] = new_sess
            return new_sess

        async def fake_set_cookies(cookies):
            imported["n"] = len(cookies)
            return {"status": "ok", "imported": len(cookies)}

        monkeypatch.setattr(src.client, "get_cookies", fake_get_cookies)
        monkeypatch.setattr(main.session_registry, "create", fake_create)

        r = c.post("/session/sess123/clone")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["data"]["session_id"] == "new123"
        assert body["data"]["cookies_copied"] == 1

    def test_clone_session_404(self, app_client):
        c = app_client
        r = c.post("/session/nope/clone")
        assert r.status_code == 404
