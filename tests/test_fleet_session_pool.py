"""Unit tests for src/fleet/session_pool.py — FleetSessionPool allocation."""

from __future__ import annotations

import httpx
import pytest

from fleet.node_registry import NodeRegistry
from fleet.queue_manager import FleetQueueManager
from fleet.session_pool import FleetSessionPool

pytestmark = pytest.mark.quick


class LaunchTransport:
    """MockTransport: healthy nodes answer launch 200; dead ones raise."""

    def __init__(self) -> None:
        self.dead: set[str] = set()

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


def _pool(tmp_path, transport: LaunchTransport, max_queue: int = 10) -> FleetSessionPool:
    registry = NodeRegistry(db_path=str(tmp_path / "fleet.db"))
    queue = FleetQueueManager(registry=registry, max_queue=max_queue)
    return FleetSessionPool(
        registry=registry,
        queue=queue,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(transport.handler), timeout=1.0
        ),
    )


async def test_allocate_creates_session_on_healthy_node(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport)
    try:
        node = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        result = await pool.allocate(session_id="sess_001")
        assert result["decision"] == "allocated"
        session = result["session"]
        assert session["session_id"] == "sess_001"
        assert session["node_id"] == node.node_id
        assert session["node_url"] == "http://worker-a:8001"
        assert session["status"] == "active"
        assert session["queued"] is False
        assert session["cdp_url"] == "ws://worker-a/devtools/browser"
        # Capacity counter moved
        after = await pool.registry.get(node.node_id)
        assert after is not None and after.active_sessions == 1
    finally:
        await pool.aclose()


async def test_allocate_zero_nodes_falls_back_to_local(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport)
    try:
        result = await pool.allocate(session_id="sess_local")
        assert result["decision"] == "local"
        session = result["session"]
        assert session["node_id"] == "node_local"
        assert session["node_url"] == "http://localhost:8000"
        assert session["queued"] is False
        # The coordinator node stays hidden from listings
        ids = [n.node_id for n in await pool.registry.list()]
        assert "node_local" not in ids
        # ...but the session row is readable
        status = await pool.status("sess_local")
        assert status is not None and status["node_id"] == "node_local"
    finally:
        await pool.aclose()


async def test_allocate_dead_node_returns_no_healthy(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport)
    try:
        node = await pool.registry.register(url="http://worker-dead:59999", capacity=5)
        transport.dead.add("worker-dead:59999")
        result = await pool.allocate(session_id="sess_dead")
        assert result["decision"] == "no_healthy"
        assert result["error"]["code"] == "no_healthy_nodes"
        # The unreachable node was marked unhealthy and excluded from scheduling
        after = await pool.registry.get(node.node_id)
        assert after is not None and after.healthy is False
    finally:
        await pool.aclose()


async def test_allocate_distributes_round_robin(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport)
    try:
        a = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        b = await pool.registry.register(url="http://worker-b:8002", capacity=5)
        r1 = await pool.allocate(session_id="sess_r1")
        r2 = await pool.allocate(session_id="sess_r2")
        assert r1["decision"] == r2["decision"] == "allocated"
        # Two allocations at equal load must land on different nodes (round-robin)
        assert {r1["session"]["node_id"], r2["session"]["node_id"]} == {
            a.node_id,
            b.node_id,
        }
    finally:
        await pool.aclose()


async def test_allocate_at_capacity_queues(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport)
    try:
        await pool.registry.register(url="http://worker-a:8001", capacity=1)
        first = await pool.allocate(session_id="sess_q1")
        assert first["decision"] == "allocated"
        second = await pool.allocate(session_id="sess_q2")
        assert second["decision"] == "queued"
        queue = second["queue"]
        assert queue["session_id"] == "sess_q2"
        assert queue["queue_position"] >= 1
        assert queue["estimated_wait_seconds"] >= 1
    finally:
        await pool.aclose()


async def test_allocate_queue_full_returns_503_shape(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport, max_queue=2)
    try:
        await pool.registry.register(url="http://worker-a:8001", capacity=1)
        assert (await pool.allocate(session_id="sess_f0"))["decision"] == "allocated"
        assert (await pool.allocate(session_id="sess_f1"))["decision"] == "queued"
        assert (await pool.allocate(session_id="sess_f2"))["decision"] == "queued"
        full = await pool.allocate(session_id="sess_f3")
        assert full["decision"] == "queue_full"
        assert full["error"]["code"] == "queue_full"
        assert full["retry_after"] > 0
    finally:
        await pool.aclose()


async def test_allocate_node_affinity(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport)
    try:
        a = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        b = await pool.registry.register(url="http://worker-b:8002", capacity=5)
        result = await pool.allocate(session_id="sess_aff", node_id=b.node_id)
        assert result["decision"] == "allocated"
        assert result["session"]["node_id"] == b.node_id
        assert result["session"]["node_id"] != a.node_id
    finally:
        await pool.aclose()


async def test_allocate_duplicate_session_id_returns_error(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport)
    try:
        await pool.registry.register(url="http://worker-a:8001", capacity=5)
        first = await pool.allocate(session_id="sess_dup")
        assert first["decision"] == "allocated"
        second = await pool.allocate(session_id="sess_dup")
        assert second["decision"] == "error"
        assert second["error"]["code"] == "session_exists"
    finally:
        await pool.aclose()


async def test_release_session_frees_capacity(tmp_path):
    transport = LaunchTransport()
    pool = _pool(tmp_path, transport)
    try:
        node = await pool.registry.register(url="http://worker-a:8001", capacity=5)
        await pool.allocate(session_id="sess_rel")
        assert await pool.release("sess_rel") is True
        status = await pool.status("sess_rel")
        assert status is not None and status["status"] == "closed"
        after = await pool.registry.get(node.node_id)
        assert after is not None and after.active_sessions == 0
        # Releasing an unknown session reports False (API maps to 404)
        assert await pool.release("sess_missing") is False
    finally:
        await pool.aclose()
