"""F5 — Download helper (v1.27.0).

Covers:
- CDPClient.download_file contract (mocked CDP)
- REST /page/download endpoint (stubbed client)
- MCP registry has download
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    return TestClient(main.app)


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_download_file_ok(self, monkeypatch, tmp_path):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        dl_dir = str(tmp_path / "dl")
        sent = {}

        async def fake_activate():
            return None

        async def fake_send(cmd, params=None):
            sent["cmd"] = cmd
            sent["params"] = params
            return {}

        async def fake_navigate(url):
            # Simulate the download: write a file into the download dir
            import os

            os.makedirs(dl_dir, exist_ok=True)
            (tmp_path / "dl" / "report.pdf").write_bytes(b"%PDF-1.4 fake")
            return {"status": "ok"}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "_send_command", fake_send)
        monkeypatch.setattr(client, "navigate", fake_navigate)
        res = await client.download_file("https://x.com/r.pdf", dl_dir, timeout=5)
        assert res["status"] == "ok"
        assert res["name"] == "report.pdf"
        assert sent["cmd"] == "Browser.setDownloadBehavior"
        assert sent["params"]["behavior"] == "allow"
        assert sent["params"]["downloadPath"] == dl_dir

    @pytest.mark.asyncio
    async def test_download_file_timeout(self, monkeypatch, tmp_path):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")
        dl_dir = str(tmp_path / "dl")

        async def fake_activate():
            return None

        async def fake_send(cmd, params=None):
            return {}

        async def fake_navigate(url):
            return {"status": "ok"}

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "_send_command", fake_send)
        monkeypatch.setattr(client, "navigate", fake_navigate)
        res = await client.download_file("https://x.com/none.pdf", dl_dir, timeout=1)
        assert res["status"] == "error"
        assert "timeout" in res["error"]

    @pytest.mark.asyncio
    async def test_download_file_setbehavior_error(self, monkeypatch):
        from cdp_client import CDPClient

        client = CDPClient(cdp_http_url="http://127.0.0.1:1")

        async def fake_activate():
            return None

        async def fake_send(cmd, params=None):
            raise RuntimeError("no browser")

        monkeypatch.setattr(client, "_activate_current", fake_activate)
        monkeypatch.setattr(client, "_send_command", fake_send)
        res = await client.download_file("https://x.com/f.pdf", "/tmp/nonexistent-x", timeout=1)
        assert res["status"] == "error"
        assert "setDownloadBehavior" in res["error"]


class TestDownloadRest:
    def test_page_download_ok(self, app_client, monkeypatch, tmp_path):
        import main

        c = app_client
        # Fake download_file writes a file and returns ok
        async def fake_download(url, dl_dir, timeout):
            import os

            os.makedirs(dl_dir, exist_ok=True)
            p = os.path.join(dl_dir, "data.csv")
            with open(p, "wb") as f:
                f.write(b"a,b,c\n1,2,3\n")
            return {"status": "ok", "path": p, "name": "data.csv", "size_bytes": 10}

        monkeypatch.setattr(main.client, "download_file", fake_download)
        r = c.post("/page/download", json={"url": "https://x.com/data.csv", "timeout": 5})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["data"]["file_name"] == "data.csv"
        assert body["data"]["artifact"]["artifact_id"].startswith("art_")
        assert body["data"]["artifact"]["metadata"]["source_url"] == "https://x.com/data.csv"

    def test_page_download_failure(self, app_client, monkeypatch):
        import main

        c = app_client

        async def fake_download(url, dl_dir, timeout):
            return {"status": "error", "error": "download timeout after 1s"}

        monkeypatch.setattr(main.client, "download_file", fake_download)
        r = c.post("/page/download", json={"url": "https://x.com/nope", "timeout": 1})
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "download_failed"

    def test_page_download_missing_url(self, app_client):
        c = app_client
        r = c.post("/page/download", json={})
        assert r.status_code == 422


class TestMCPRegistry:
    def test_download_registered(self):
        from mcp_server.registry import build_tool_defs

        reg = build_tool_defs()
        names = {t.name for t in reg}
        assert "download" in names
