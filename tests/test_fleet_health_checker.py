"""Unit tests for src/fleet/health_checker.py — FleetHealthChecker."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from fleet.health_checker import FleetHealthChecker
from fleet.node_registry import NodeRegistry

pytestmark = pytest.mark.quick


class StatefulTransport:
    """MockTransport handler: healthy nodes answer 200, dead ones raise."""

    def __init__(self) -> None:
        self.dead: set[str] = set()  # "host:port" keys
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.url.host}:{request.url.port}"
        if key in self.dead:
            raise httpx.ConnectError(f"connection refused for {key}", request=request)
        if request.url.path.rstrip("/").endswith("/health"):
            return httpx.Response(200, json={"status": "ok", "healthy": True})
        return httpx.Response(200, json={"status": "ok"})

    def make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler), timeout=1.0)


def _checker(tmp_path, transport: StatefulTransport) -> FleetHealthChecker:
    return FleetHealthChecker(
        registry=NodeRegistry(db_path=str(tmp_path / "fleet.db")),
        http_client=transport.make_client(),
        poll_interval_s=0.05,
        cooldown_s=0.01,
        jitter_s=0.0,
    )


async def test_probe_healthy(tmp_path):
    transport = StatefulTransport()
    checker = _checker(tmp_path, transport)
    reg = checker.registry
    try:
        node = await reg.register(url="http://worker-a:8001", capacity=5)
        result = await checker.probe(node.node_id)
        assert result is not None
        assert result["healthy"] is True
        assert "latency_ms" in result and result["latency_ms"] >= 0
        assert result["last_checked"] > 0
        assert result["node_status"] == {"status": "ok", "healthy": True}
        assert result["last_error"] is None
        # Persisted through the registry
        stored = await reg.get(node.node_id)
        assert stored is not None and stored.healthy is True
        assert stored.last_checked > 0
    finally:
        await checker.stop()


async def test_probe_unhealthy_marks_node_down(tmp_path):
    transport = StatefulTransport()
    checker = _checker(tmp_path, transport)
    reg = checker.registry
    try:
        node = await reg.register(url="http://worker-dead:59999", capacity=5)
        transport.dead.add("worker-dead:59999")
        result = await checker.probe(node.node_id)
        assert result is not None
        assert result["healthy"] is False
        assert result["last_error"]
        stored = await reg.get(node.node_id)
        assert stored is not None and stored.healthy is False
        assert stored.last_error
    finally:
        await checker.stop()


async def test_probe_unknown_node_returns_none(tmp_path):
    transport = StatefulTransport()
    checker = _checker(tmp_path, transport)
    try:
        assert await checker.probe("node_nope") is None
    finally:
        await checker.stop()


async def test_check_all_summarises_mixed_fleet(tmp_path):
    transport = StatefulTransport()
    checker = _checker(tmp_path, transport)
    reg = checker.registry
    try:
        await reg.register(url="http://worker-ok:8001", capacity=5)
        dead = await reg.register(url="http://worker-down:59998", capacity=5)
        transport.dead.add("worker-down:59998")
        summary = await checker.check_all()
        assert summary["checked"] == 2
        assert summary["healthy"] == 1
        assert summary["unhealthy"] == 1
        dead_after = await reg.get(dead.node_id)
        assert dead_after is not None and dead_after.healthy is False
    finally:
        await checker.stop()


async def test_on_node_unhealthy_fires_once_per_episode(tmp_path):
    transport = StatefulTransport()
    checker = _checker(tmp_path, transport)
    reg = checker.registry
    fired: list[str] = []

    async def hook(node_id: str) -> None:
        fired.append(node_id)

    checker.on_node_unhealthy = hook
    try:
        node = await reg.register(url="http://worker-flap:8001", capacity=5)
        transport.dead.add("worker-flap:8001")
        # Episode 1: healthy -> unhealthy fires once.
        await checker.probe(node.node_id)
        await checker.probe(node.node_id)  # still down -> no re-fire
        assert fired == [node.node_id]
        # Recovery: node comes back, then dies again -> a new episode fires.
        transport.dead.discard("worker-flap:8001")
        await checker.probe(node.node_id)
        transport.dead.add("worker-flap:8001")
        await checker.probe(node.node_id)
        assert fired == [node.node_id, node.node_id]
    finally:
        await checker.stop()


async def test_poll_loop_marks_dead_node_unhealthy(tmp_path):
    transport = StatefulTransport()
    checker = _checker(tmp_path, transport)
    reg = checker.registry
    try:
        node = await reg.register(url="http://worker-loop:8001", capacity=5)
        transport.dead.add("worker-loop:8001")
        checker.start()
        await asyncio.sleep(0.25)  # several poll cycles
        await checker.stop()
        stored = await reg.get(node.node_id)
        assert stored is not None and stored.healthy is False
        assert stored.last_error
    finally:
        await checker.stop()


async def test_poll_loop_keeps_healthy_node_healthy(tmp_path):
    transport = StatefulTransport()
    checker = _checker(tmp_path, transport)
    reg = checker.registry
    try:
        node = await reg.register(url="http://worker-stable:8001", capacity=5)
        checker.start()
        await asyncio.sleep(0.2)
        await checker.stop()
        stored = await reg.get(node.node_id)
        assert stored is not None and stored.healthy is True
        assert stored.last_checked > 0
    finally:
        await checker.stop()
