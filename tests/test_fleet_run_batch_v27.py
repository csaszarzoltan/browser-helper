"""F4 — Fleet run-batch (v1.27.0).

Covers:
- /fleet/run-batch endpoint: validation (empty, too many)
- Per-task isolation: one failing task doesn't fail the batch
- Aggregated report shape
- MCP registry has fleet_run_batch
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_client(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    return TestClient(main.app)


class TestRunBatchValidation:
    def test_empty_tasks_rejected(self, app_client):
        c = app_client
        r = c.post("/fleet/run-batch", json={"tasks": [], "concurrency": 2})
        assert r.status_code == 422

    def test_too_many_tasks_rejected(self, app_client):
        c = app_client
        r = c.post("/fleet/run-batch", json={"tasks": [{"url": "https://x.com"}] * 51})
        assert r.status_code == 422

    def test_concurrency_cap(self, app_client):
        c = app_client
        r = c.post("/fleet/run-batch", json={"tasks": [{"url": "https://x.com"}], "concurrency": 99})
        assert r.status_code == 422


class TestRunBatchExecution:
    def test_batch_runs_tasks_and_aggregates(self, app_client, monkeypatch):
        import main

        c = app_client
        created = []

        class FakeSession:
            def __init__(self, sid):
                self.session_id = sid
                self.tab_id = "tab" + sid
                self.client = FakeClient()

        class FakeClient:
            async def navigate(self, url):
                return {"status": "ok", "url": url}

            async def wait_for_ready(self, timeout=30, quiet_ms=800):
                return {"status": "ok"}

            async def evaluate(self, js):
                return {"result": "Fake Title"}

            async def assert_elements(self, kind, value, condition, expected=None):
                return {"status": "ok", "result": {"passed": True, "count": 1}}

        async def fake_create(cdp_url, url="about:blank", profile_dir=None):
            sid = f"batch{len(created)}"
            s = FakeSession(sid)
            created.append(s)
            main.session_registry._sessions[sid] = s
            return s

        async def fake_destroy(sid):
            main.session_registry._sessions.pop(sid, None)
            return True

        async def fake_launch(**kwargs):
            return {"status": "ok"}

        async def fake_run_op(op, fn, *args, **kwargs):
            return await fn(*args, **kwargs)

        monkeypatch.setattr(main.chrome_mgr, "launch", fake_launch)
        monkeypatch.setattr(main.session_registry, "create", fake_create)
        monkeypatch.setattr(main.session_registry, "destroy", fake_destroy)
        monkeypatch.setattr(main, "run_op", fake_run_op)

        r = c.post("/fleet/run-batch", json={
            "tasks": [
                {"url": "https://a.example", "action": "title"},
                {"url": "https://b.example", "assert_selector": "#main"},
                {"url": "https://c.example", "assert_text": "hello"},
            ],
            "concurrency": 2,
        })
        assert r.status_code == 200
        body = r.json()
        data = body["data"]
        assert data["total"] == 3
        assert data["ok"] == 3
        assert data["failed"] == 0
        assert data["concurrency"] == 2
        assert len(data["results"]) == 3
        assert len(created) == 3  # each task got its own session
        # Sessions destroyed after the batch
        assert main.session_registry.get("batch0") is None

    def test_batch_per_task_error_isolation(self, app_client, monkeypatch):
        import main

        c = app_client

        class FakeClient:
            async def navigate(self, url):
                if "bad" in url:
                    raise RuntimeError("navigate exploded")
                return {"status": "ok"}

            async def wait_for_ready(self, timeout=30, quiet_ms=800):
                return {"status": "ok"}

        class FakeSession:
            def __init__(self, sid):
                self.session_id = sid
                self.client = FakeClient()

        async def fake_create(cdp_url, url="about:blank", profile_dir=None):
            s = FakeSession("s" + str(len(main.session_registry._sessions)))
            main.session_registry._sessions[s.session_id] = s
            return s

        async def fake_destroy(sid):
            main.session_registry._sessions.pop(sid, None)
            return True

        async def fake_launch(**kwargs):
            return {"status": "ok"}

        async def fake_run_op(op, fn, *args, **kwargs):
            return await fn(*args, **kwargs)

        monkeypatch.setattr(main.chrome_mgr, "launch", fake_launch)
        monkeypatch.setattr(main.session_registry, "create", fake_create)
        monkeypatch.setattr(main.session_registry, "destroy", fake_destroy)
        monkeypatch.setattr(main, "run_op", fake_run_op)

        r = c.post("/fleet/run-batch", json={
            "tasks": [
                {"url": "https://good.example"},
                {"url": "https://bad.example"},
            ],
            "concurrency": 2,
        })
        body = r.json()
        data = body["data"]
        assert data["total"] == 2
        assert data["ok"] == 1
        assert data["failed"] == 1
        statuses = {res["status"] for res in data["results"]}
        assert statuses == {"ok", "error"}
        err = next(res for res in data["results"] if res["status"] == "error")
        assert "exploded" in err["error"]


class TestMCPRegistry:
    def test_fleet_run_batch_registered(self):
        from mcp_server.registry import build_tool_defs

        reg = build_tool_defs()
        names = {t.name for t in reg}
        assert "fleet_run_batch" in names
