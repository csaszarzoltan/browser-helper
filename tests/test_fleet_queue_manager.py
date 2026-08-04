"""Unit tests for src/fleet/queue_manager.py — FleetQueueManager."""

from __future__ import annotations

import asyncio

import pytest

from fleet.node_registry import NodeRegistry
from fleet.queue_manager import FleetQueueManager, QueueFullError

pytestmark = pytest.mark.quick


def _manager(tmp_path, max_queue: int = 10) -> FleetQueueManager:
    return FleetQueueManager(
        registry=NodeRegistry(db_path=str(tmp_path / "fleet.db")),
        max_queue=max_queue,
        avg_session_seconds=30.0,
    )


async def test_enqueue_assigns_fifo_positions(tmp_path):
    mgr = _manager(tmp_path)
    try:
        r1 = await mgr.enqueue("sess_a", ttl_seconds=600)
        r2 = await mgr.enqueue("sess_b", ttl_seconds=600)
        r3 = await mgr.enqueue("sess_c", ttl_seconds=600)
        assert r1["queue_position"] == 1
        assert r2["queue_position"] == 2
        assert r3["queue_position"] == 3
        assert [r["session_id"] for r in await mgr.peek()] == [
            "sess_a",
            "sess_b",
            "sess_c",
        ]
        assert await mgr.size() == 3
    finally:
        mgr.registry.close()


async def test_enqueue_records_ttl_expiry(tmp_path):
    mgr = _manager(tmp_path)
    try:
        record = await mgr.enqueue("sess_ttl", ttl_seconds=60)
        assert record["ttl_seconds"] == 60
        assert record["expires_at"] == pytest.approx(record["requested_at"] + 60)
        assert record["estimated_wait_seconds"] >= 1
    finally:
        mgr.registry.close()


async def test_dequeue_ready_pops_fifo(tmp_path):
    mgr = _manager(tmp_path)
    try:
        await mgr.enqueue("sess_a", ttl_seconds=600)
        await mgr.enqueue("sess_b", ttl_seconds=600)
        first = await mgr.dequeue_ready()
        assert first is not None and first["session_id"] == "sess_a"
        second = await mgr.dequeue_ready()
        assert second is not None and second["session_id"] == "sess_b"
        assert await mgr.dequeue_ready() is None
    finally:
        mgr.registry.close()


async def test_dequeue_ready_skips_expired(tmp_path):
    mgr = _manager(tmp_path)
    try:
        await mgr.enqueue("sess_old", ttl_seconds=0.01)
        await mgr.enqueue("sess_new", ttl_seconds=600)
        await asyncio.sleep(0.05)
        # The expired entry is not popped; the fresh one still is.
        popped = await mgr.dequeue_ready()
        assert popped is not None and popped["session_id"] == "sess_new"
        assert await mgr.dequeue_ready() is None
    finally:
        mgr.registry.close()


async def test_enqueue_when_full_raises_queue_full(tmp_path):
    mgr = _manager(tmp_path, max_queue=2)
    try:
        await mgr.enqueue("sess_a", ttl_seconds=600)
        await mgr.enqueue("sess_b", ttl_seconds=600)
        with pytest.raises(QueueFullError) as exc_info:
            await mgr.enqueue("sess_c", ttl_seconds=600)
        assert exc_info.value.retry_after > 0
        assert await mgr.is_full() is True
    finally:
        mgr.registry.close()


async def test_sweep_purges_expired_entries(tmp_path):
    mgr = _manager(tmp_path)
    try:
        await mgr.enqueue("sess_old", ttl_seconds=0.01)
        await mgr.enqueue("sess_fresh", ttl_seconds=600)
        await asyncio.sleep(0.05)
        sweep = await mgr.sweep()
        assert sweep["expired_count"] >= 1
        assert sweep["purged"] == sweep["expired_count"]
        assert sweep["queued"] == 1  # only the fresh entry remains
    finally:
        mgr.registry.close()


async def test_estimated_wait_grows_with_position(tmp_path):
    mgr = _manager(tmp_path)
    try:
        # No healthy nodes -> wait estimate scales linearly with position.
        w1 = await mgr.estimated_wait_seconds(1)
        w3 = await mgr.estimated_wait_seconds(3)
        assert w1 >= 1
        assert w3 > w1
    finally:
        mgr.registry.close()


async def test_estimated_wait_uses_fleet_capacity(tmp_path):
    mgr = _manager(tmp_path)
    reg = mgr.registry
    try:
        await reg.register(url="http://worker-a:8001", capacity=4)
        # With 4 parallel slots, position 1 waits ~30/4 = 7.5s (>=1).
        assert await mgr.estimated_wait_seconds(1) == pytest.approx(7.5, rel=0.2)
    finally:
        reg.close()
