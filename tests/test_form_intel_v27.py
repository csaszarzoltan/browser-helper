"""F3 — Form-intelligence (v1.27.0).

Covers:
- CDPClient.form_extract contract (mocked CDP)
- REST /form/extract endpoint
- MCP registry has form_fill + form_extract
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    return TestClient(main.app)


class TestFormExtract:
    @pytest.mark.asyncio
    async def test_form_extract_sends_js(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        captured = {}

        async def fake_activate():
            return None

        async def fake_evaluate(js):
            captured["js"] = js
            return {"result": '{"forms": 1, "form_count": 1, "forms_list": [{"form_id": "f1", "fields": [{"tag": "input", "type": "text", "name": "email"}]}]}'}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "evaluate", fake_evaluate)
        res = await client.form_extract()
        assert res["status"] == "ok"
        assert res["result"]["forms"] == 1
        assert "querySelectorAll" in captured["js"]
        assert "forms_list" in captured["js"]

    @pytest.mark.asyncio
    async def test_form_extract_parse_failure(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")

        async def fake_activate():
            return None

        async def fake_evaluate(js):
            return {"result": "not-json"}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "evaluate", fake_evaluate)
        res = await client.form_extract()
        assert res["status"] == "ok"
        assert "error" in res["result"]


class TestFormExtractRest:
    def test_form_extract_rest_ok(self, app_client, monkeypatch):
        import main

        c = app_client

        async def fake_extract():
            return {"status": "ok", "result": {"forms": 1, "forms_list": []}}

        monkeypatch.setattr(main.client, "form_extract", fake_extract)
        r = c.post("/form/extract")
        assert r.status_code == 200
        assert r.json()["data"]["result"]["forms"] == 1


class TestMCPRegistry:
    def test_form_tools_registered(self):
        from mcp_server.registry import build_tool_defs

        reg = build_tool_defs()
        names = {t.name for t in reg}
        assert "form_fill" in names
        assert "form_extract" in names

    def test_f1_f2_tools_registered(self):
        from mcp_server.registry import build_tool_defs

        reg = build_tool_defs()
        names = {t.name for t in reg}
        for expected in ("export_cookies", "import_cookies", "clone_session",
                         "wait_for", "assert"):
            assert expected in names, f"{expected} missing"
