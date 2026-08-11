"""F6 — Network interception (v1.27.0).

Covers:
- CDPClient.set_network_block contract + _match_block
- REST /network/block endpoint
- MCP registry has network_block + network_mock
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    return TestClient(main.app)


class TestSetNetworkBlock:
    @pytest.mark.asyncio
    async def test_block_ok(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        client._fetch_enabled = False
        sent = {}

        async def fake_send(cmd, params=None):
            sent["cmd"] = cmd
            sent["params"] = params
            return {}

        monkeypatch.setattr(client, "_send_command", fake_send)
        res = await client.set_network_block([r"analytics\.google", "doubleclick"])
        assert res["status"] == "ok"
        assert res["blocked"] == 2
        assert sent["cmd"] == "Fetch.enable"
        assert client._match_block("https://x.com/analytics.google.js")
        assert client._match_block("https://ads.doubleclick.net/f")
        assert not client._match_block("https://example.com/")

    @pytest.mark.asyncio
    async def test_block_clear(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        client._fetch_enabled = True
        client._request_mocks = []
        sent = []

        async def fake_send(cmd, params=None):
            sent.append(cmd)
            return {}

        monkeypatch.setattr(client, "_send_command", fake_send)
        res = await client.set_network_block([])
        assert res["status"] == "ok"
        assert res["blocked"] == 0
        assert "Fetch.disable" in sent
        assert client._fetch_enabled is False

    @pytest.mark.asyncio
    async def test_block_fetch_enable_error(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        client._fetch_enabled = False

        async def fake_send(cmd, params=None):
            raise RuntimeError("no browser")

        monkeypatch.setattr(client, "_send_command", fake_send)
        with pytest.raises(RuntimeError):
            await client.set_network_block(["ads"])


class TestFetchPausedBlock:
    @pytest.mark.asyncio
    async def test_blocked_request_fails(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        client._block_patterns = [r"tracker"]
        sent = []

        async def fake_send(cmd, params=None):
            sent.append((cmd, params))
            return {}

        monkeypatch.setattr(client, "_send_command", fake_send)
        await client._handle_fetch_paused("rid1", "https://x.com/tracker.gif", "Image")
        assert sent[0][0] == "Fetch.failRequest"
        assert sent[0][1]["errorReason"] == "BlockedByClient"

    @pytest.mark.asyncio
    async def test_unblocked_request_continues(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        client._block_patterns = [r"tracker"]
        sent = []

        async def fake_send(cmd, params=None):
            sent.append((cmd, params))
            return {}

        monkeypatch.setattr(client, "_send_command", fake_send)
        await client._handle_fetch_paused("rid2", "https://x.com/ok.js", "Script")
        assert sent[0][0] == "Fetch.continueRequest"

    @pytest.mark.asyncio
    async def test_document_always_passes(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        client._block_patterns = [r".*"]
        sent = []

        async def fake_send(cmd, params=None):
            sent.append((cmd, params))
            return {}

        monkeypatch.setattr(client, "_send_command", fake_send)
        await client._handle_fetch_paused("rid3", "https://x.com/page.html", "Document")
        assert sent[0][0] == "Fetch.continueRequest"


class TestNetworkBlockRest:
    def test_network_block_ok(self, app_client, monkeypatch):
        import main

        c = app_client

        async def fake_block(patterns):
            return {"status": "ok", "blocked": len(patterns)}

        monkeypatch.setattr(main.client, "set_network_block", fake_block)
        r = c.post("/network/block", json={"patterns": ["ads", "tracker"]})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["data"]["blocked"] == 2

    def test_network_block_clear(self, app_client, monkeypatch):
        import main

        c = app_client

        async def fake_block(patterns):
            return {"status": "ok", "blocked": 0}

        monkeypatch.setattr(main.client, "set_network_block", fake_block)
        r = c.post("/network/block", json={"patterns": []})
        assert r.status_code == 200
        assert r.json()["data"]["blocked"] == 0

    def test_network_block_missing_body(self, app_client, monkeypatch):
        import main

        c = app_client
        called = {}

        async def fake_block(patterns):
            called["patterns"] = patterns
            return {"status": "ok", "blocked": 0}

        monkeypatch.setattr(main.client, "set_network_block", fake_block)
        r = c.post("/network/block", json={})
        assert r.status_code == 200
        assert called["patterns"] == []  # default empty list

    def test_network_mock_ok(self, app_client, monkeypatch):
        import main

        c = app_client

        async def fake_mock(mocks):
            return {"status": "ok", "mocks": len(mocks)}

        monkeypatch.setattr(main.client, "set_request_mocks", fake_mock)
        r = c.post("/network/mock", json={
            "mocks": [{"pattern": "api", "status": 200, "body": "{}"}],
        })
        assert r.status_code == 200
        assert r.json()["data"]["mocks"] == 1


class TestMCPRegistryF6:
    def test_network_tools_registered(self):
        from mcp_server.registry import build_tool_defs

        reg = build_tool_defs()
        names = {t.name for t in reg}
        assert "network_block" in names
        assert "network_mock" in names
