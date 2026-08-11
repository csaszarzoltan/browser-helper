"""F2 — Wait-for / assertion engine (v1.27.0).

Covers:
- CDPClient.wait_for_condition contract (mocked CDP)
- CDPClient.assert_elements contract (mocked CDP)
- REST /wait/for + /assert endpoints (TestClient)
- 409 on failed assertion
- Invalid kind/condition rejection
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    return TestClient(main.app)


class TestWaitForCondition:
    @pytest.mark.asyncio
    async def test_unknown_kind(self):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        res = await client.wait_for_condition("bogus", "x")
        assert res["status"] == "error"
        assert "unknown kind" in res["error"]

    @pytest.mark.asyncio
    async def test_unknown_condition(self):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        res = await client.wait_for_condition("selector", "#btn", "bogus")
        assert res["status"] == "error"
        assert "unknown condition" in res["error"]

    @pytest.mark.asyncio
    async def test_wait_selector_present(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        captured = {}

        async def fake_activate():
            return None

        async def fake_evaluate(js):
            captured["js"] = js
            return {"result": '{"status": "ok", "condition": "present", "kind": "selector"}'}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "evaluate", fake_evaluate)
        res = await client.wait_for_condition("selector", "#btn", "present", 5)
        assert res["status"] == "ok"
        assert res["result"]["status"] == "ok"
        assert "#btn" in captured["js"]
        assert "5000" in captured["js"]  # timeout in ms

    @pytest.mark.asyncio
    async def test_wait_text_gone(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")

        async def fake_activate():
            return None

        async def fake_evaluate(js):
            return {"result": '{"status": "ok", "condition": "gone"}'}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "evaluate", fake_evaluate)
        res = await client.wait_for_condition("text", "Loading...", "gone", 5)
        assert res["status"] == "ok"
        assert res["condition"] == "gone"


class TestAssertElements:
    @pytest.mark.asyncio
    async def test_assert_count_requires_expected(self):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        res = await client.assert_elements("selector", ".btn", "count")
        assert res["status"] == "error"
        assert "expected" in res["error"]

    @pytest.mark.asyncio
    async def test_assert_exists_passed(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")

        async def fake_activate():
            return None

        async def fake_evaluate(js):
            return {"result": '{"passed": true, "found": true, "count": 3}'}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "evaluate", fake_evaluate)
        res = await client.assert_elements("selector", ".btn", "exists")
        assert res["status"] == "ok"
        assert res["result"]["passed"] is True

    @pytest.mark.asyncio
    async def test_assert_count_failed(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")

        async def fake_activate():
            return None

        async def fake_evaluate(js):
            return {"result": '{"passed": false, "found": true, "count": 2}'}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "evaluate", fake_evaluate)
        res = await client.assert_elements("selector", ".btn", "count", 3)
        assert res["status"] == "ok"
        assert res["result"]["passed"] is False


class TestWaitAssertRest:
    def test_wait_for_rest_ok(self, app_client, monkeypatch):
        import main

        c = app_client

        async def fake_wait(kind, value, condition, timeout):
            return {"status": "ok", "kind": kind, "value": value,
                    "condition": condition, "timeout": timeout,
                    "result": {"status": "ok"}}

        monkeypatch.setattr(main.client, "wait_for_condition", fake_wait)
        r = c.post("/wait/for", json={"kind": "selector", "value": "#btn",
                                      "condition": "present", "timeout": 5})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["data"]["result"]["status"] == "ok"

    def test_assert_rest_passed(self, app_client, monkeypatch):
        import main

        c = app_client

        async def fake_assert(kind, value, condition, expected):
            return {"status": "ok", "result": {"passed": True, "count": 1}}

        monkeypatch.setattr(main.client, "assert_elements", fake_assert)
        r = c.post("/assert", json={"kind": "selector", "value": "#btn",
                                    "condition": "exists"})
        assert r.status_code == 200
        assert r.json()["data"]["result"]["passed"] is True

    def test_assert_rest_failed_409(self, app_client, monkeypatch):
        import main

        c = app_client

        async def fake_assert(kind, value, condition, expected):
            return {"status": "ok", "result": {"passed": False, "count": 2}}

        monkeypatch.setattr(main.client, "assert_elements", fake_assert)
        r = c.post("/assert", json={"kind": "selector", "value": ".btn",
                                    "condition": "count", "expected": 3})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "assertion_failed"

    def test_wait_for_rest_validation(self, app_client):
        c = app_client
        # Missing value → 422
        r = c.post("/wait/for", json={"kind": "selector"})
        assert r.status_code == 422
