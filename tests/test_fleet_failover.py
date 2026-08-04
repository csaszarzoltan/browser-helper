"""Unit tests for src/fleet/failover.py — FailoverManager state transfer."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from fleet.failover import FailoverManager
from fleet.node_registry import NodeRegistry
from fleet.queue_manager import FleetQueueManager
from fleet.session_pool import FleetSessionPool

pytestmark = pytest.mark.quick


class FakeSessionManager:
    """Test double for the coordinator's SessionManager (capture/restore)."""

    def __init__(self) -> None:
        self.captured: list[tuple[str, str]] = []
        self.restored: list[Any] = []

    async def capture(self, cdp_client: Any, session_id: str, url: str = "") -> dict:
        self.captured.append((session_id, url))
        return {
            "session_id": session_id,
            "cookies": [{"name": "sessionid", "value": "abc", "domain": ".x.com"}],
            "local_storage": {"key": "value"},
            "session_storage": {},
            "url": url,
            "created_at": 1.0,
            "last_active": 1.0,
        }

    async def restore(self, cdp_client: Any, state: Any) -> dict[str, Any]:
        self.restored.append(state)
        return {"session_id": getattr(state, "session_id", None)}


class LaunchTransport:
    """MockTransport with per-host kill switch (simulates node death)."""

    def __init__(self) -> None:
        self.dead: set[str] = set()

    def kill(self, host: str, port: int) -> None:
        self.dead.add(f"{host}:{port}")

    def handler(self, request: httpx.Request) -> httpx.Response:
        key = f"{request.url.host}:{request.url.port}"
        if key in self.dead:
            raise httpx.ConnectError(f"connection refused for {key}", request=request)
        if request.url.path.rstrip("/").endswith("/health"):
            return httpx.Response(200, json={"status": "ok", "healthy": True})
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {"cdp_http_url": f"ws://{request.url.host}/devtools/browser"},
            },
        )


def _failover(tmp_path, transport: LaunchTransport) -> tuple[FailoverManager, FakeSessionManager]:
    registry = NodeRegistry(db_path=str(tmp_path / "fleet.db"))
    queue = FleetQueueManager(registry=registry, max_queue=10)
    pool = FleetSessionPool(
        registry=registry,
        queue=queue,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(transport.handler), timeout=1.0
        ),
    )
    session_mgr = FakeSessionManager()
    return FailoverManager(pool=pool, session_manager=session_mgr), session_mgr


async def test_failover_moves_session_to_healthy_node(tmp_path):
    transport = LaunchTransport()
    fm, _ = _failover(tmp_path, transport)
    pool = fm.pool
    try:
        node_a = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        node_b = await pool.registry.register(url="http://worker-b:8002", capacity=5)
        allocated = await pool.allocate(session_id="sess_fo", node_id=node_a.node_id)
        assert allocated["decision"] == "allocated"
        assert allocated["session"]["node_id"] == node_a.node_id

        transport.kill("worker-a", 8001)
        report = await fm.failover(node_id=node_a.node_id, session_id="sess_fo")
        assert report["save_restore"] is True
        assert len(report["transferred"]) == 1
        record = report["transferred"][0]
        assert record["from_node_id"] == node_a.node_id
        assert record["to_node_id"] == node_b.node_id
        assert record["method"] == "save_restore"
        # The session row now lives on the healthy node
        status = await pool.status("sess_fo")
        assert status is not None
        assert status["node_id"] == node_b.node_id
        assert status["status"] == "active"
        # Capacity counters moved atomically
        a_after = await pool.registry.get(node_a.node_id)
        b_after = await pool.registry.get(node_b.node_id)
        assert a_after is not None and a_after.active_sessions == 0
        assert b_after is not None and b_after.active_sessions == 1
    finally:
        await pool.aclose()


async def test_failover_falls_back_to_coordinator_when_alone(tmp_path):
    transport = LaunchTransport()
    fm, _ = _failover(tmp_path, transport)
    pool = fm.pool
    try:
        node_a = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        await pool.allocate(session_id="sess_fo", node_id=node_a.node_id)
        transport.kill("worker-a", 8001)
        report = await fm.failover(node_id=node_a.node_id, session_id="sess_fo")
        assert len(report["transferred"]) == 1
        record = report["transferred"][0]
        assert record["to_node_id"] == "node_local"
        # The relocated session must NOT still target the dead node
        status = await pool.status("sess_fo")
        assert status is not None and status["node_id"] == "node_local"
        assert status["node_id"] != node_a.node_id
    finally:
        await pool.aclose()


async def test_failover_uses_save_restore_state_flow(tmp_path):
    transport = LaunchTransport()
    fm, session_mgr = _failover(tmp_path, transport)
    pool = fm.pool
    try:
        node_a = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        await pool.registry.register(url="http://worker-b:8002", capacity=5)
        await pool.allocate(session_id="sess_state", node_id=node_a.node_id)
        transport.kill("worker-a", 8001)
        report = await fm.failover(node_id=node_a.node_id, session_id="sess_state")
        record = report["transferred"][0]
        # State was captured (via the SessionManager) and restored on the target
        assert session_mgr.captured == [("sess_state", "http://worker-a:8001")]
        assert len(session_mgr.restored) == 1
        assert record["state_transferred"] is True
        # The captured state was persisted into fleet_sessions.saved_state
        status = await pool.status("sess_state")
        assert status is not None and status.get("saved_state") is not None
        assert status["saved_state"]["session_id"] == "sess_state"
    finally:
        await pool.aclose()


async def test_failover_no_active_sessions_is_noop(tmp_path):
    transport = LaunchTransport()
    fm, _ = _failover(tmp_path, transport)
    pool = fm.pool
    try:
        node_a = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        transport.kill("worker-a", 8001)
        report = await fm.failover(node_id=node_a.node_id)
        assert report["transferred"] == []
        assert report["failed"] == []
        assert report["save_restore"] is True
    finally:
        await pool.aclose()


async def test_failover_creates_row_for_never_allocated_session(tmp_path):
    transport = LaunchTransport()
    fm, _ = _failover(tmp_path, transport)
    pool = fm.pool
    try:
        node_a = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        transport.kill("worker-a", 8001)
        report = await fm.failover(node_id=node_a.node_id, session_id="sess_ghost")
        assert len(report["transferred"]) == 1
        record = report["transferred"][0]
        assert record["from_node_id"] == node_a.node_id
        assert record["to_node_id"] is not None
        assert record["to_node_id"] != node_a.node_id
        # The row now exists and points away from the dead node
        status = await pool.status("sess_ghost")
        assert status is not None and status["node_id"] == record["to_node_id"]
    finally:
        await pool.aclose()
