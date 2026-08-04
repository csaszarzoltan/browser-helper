"""Unit tests for src/fleet/node_registry.py — Node dataclass + NodeRegistry."""

from __future__ import annotations

import pytest

from fleet.node_registry import DuplicateNodeError, Node, NodeRegistry

pytestmark = pytest.mark.quick


def _registry(tmp_path) -> NodeRegistry:
    return NodeRegistry(db_path=str(tmp_path / "fleet.db"))


async def test_register_returns_node_with_node_prefix(tmp_path):
    reg = _registry(tmp_path)
    try:
        node = await reg.register(
            url="http://127.0.0.1:8001",
            capabilities=["cdp", "headless", "screenshot"],
            capacity=5,
            metadata={"region": "us-east", "name": "worker-1"},
        )
        assert node.node_id.startswith("node_")
        assert node.capabilities == ["cdp", "headless", "screenshot"]
        assert node.metadata["region"] == "us-east"
        assert node.active_sessions == 0
        assert node.healthy is True
        assert node.registered_at > 0
    finally:
        reg.close()


async def test_register_duplicate_url_raises(tmp_path):
    reg = _registry(tmp_path)
    try:
        await reg.register(url="http://127.0.0.1:8003")
        with pytest.raises(DuplicateNodeError):
            await reg.register(url="http://127.0.0.1:8003")
    finally:
        reg.close()


async def test_get_unknown_returns_none(tmp_path):
    reg = _registry(tmp_path)
    try:
        assert await reg.get("node_doesnotexist") is None
    finally:
        reg.close()


async def test_list_and_unregister(tmp_path):
    reg = _registry(tmp_path)
    try:
        node_a = await reg.register(url="http://127.0.0.1:8004")
        node_b = await reg.register(url="http://127.0.0.1:8005")
        ids = {n.node_id for n in await reg.list()}
        assert {node_a.node_id, node_b.node_id} == ids

        assert await reg.unregister(node_a.node_id) is True
        remaining = {n.node_id for n in await reg.list()}
        assert node_a.node_id not in remaining
        assert await reg.unregister(node_a.node_id) is False  # already gone
        assert await reg.unregister("node_missing") is False
    finally:
        reg.close()


async def test_least_loaded_picks_fewest_sessions_and_skips_full(tmp_path):
    reg = _registry(tmp_path)
    try:
        node_a = await reg.register(url="http://a:8001", capacity=5)
        node_b = await reg.register(url="http://b:8002", capacity=5)
        # occupy one slot on node_b
        await reg.storage.add_session(
            session_id="sess_1", node_id=node_b.node_id, node_url="http://b:8002"
        )
        pick = await reg.least_loaded()
        assert pick is not None
        assert pick.node_id == node_a.node_id

        # full node is never selected
        await reg.storage.add_session(
            session_id="sess_2", node_id=node_a.node_id, node_url="http://a:8001"
        )
        await reg.storage.add_session(
            session_id="sess_3", node_id=node_a.node_id, node_url="http://a:8001"
        )
        await reg.storage.add_session(
            session_id="sess_4", node_id=node_a.node_id, node_url="http://a:8001"
        )
        await reg.storage.add_session(
            session_id="sess_5", node_id=node_a.node_id, node_url="http://a:8001"
        )
        await reg.storage.add_session(
            session_id="sess_6", node_id=node_a.node_id, node_url="http://a:8001"
        )
        # node_a now at capacity 5; node_b at 1 → least_loaded is node_b
        pick2 = await reg.least_loaded()
        assert pick2 is not None
        assert pick2.node_id == node_b.node_id

        # unhealthy node excluded entirely
        await reg.update_health(node_b.node_id, healthy=False, last_error="down")
        assert await reg.least_loaded() is None
        assert await reg.has_capacity() is False
    finally:
        reg.close()


async def test_least_loaded_excludes_failed_node(tmp_path):
    reg = _registry(tmp_path)
    try:
        node_a = await reg.register(url="http://a:8001", capacity=5)
        node_b = await reg.register(url="http://b:8002", capacity=5)
        pick = await reg.least_loaded(exclude={node_a.node_id})
        assert pick is not None
        assert pick.node_id == node_b.node_id
    finally:
        reg.close()


async def test_update_health_and_capacity(tmp_path):
    reg = _registry(tmp_path)
    try:
        node = await reg.register(url="http://127.0.0.1:8006", capacity=5)
        updated = await reg.update_health(
            node.node_id, healthy=False, last_error="timeout"
        )
        assert updated is not None
        assert updated.healthy is False
        assert updated.last_error == "timeout"
        assert updated.last_checked > 0

        resized = await reg.update_capacity(node.node_id, 20)
        assert resized is not None
        assert resized.capacity == 20

        assert await reg.update_health("node_missing", healthy=True) is None
        assert await reg.update_capacity("node_missing", 20) is None
    finally:
        reg.close()


async def test_active_count_delegates_to_sessions(tmp_path):
    reg = _registry(tmp_path)
    try:
        node = await reg.register(url="http://127.0.0.1:8007", capacity=5)
        assert await reg.active_count(node.node_id) == 0
        await reg.storage.add_session(
            session_id="sess_a1", node_id=node.node_id, node_url="http://127.0.0.1:8007"
        )
        assert await reg.active_count(node.node_id) == 1
        await reg.storage.release_session("sess_a1")
        assert await reg.active_count(node.node_id) == 0
    finally:
        reg.close()


async def test_snapshot_summary(tmp_path):
    reg = _registry(tmp_path)
    try:
        await reg.register(url="http://a:8001")
        node_b = await reg.register(url="http://b:8002")
        await reg.update_health(node_b.node_id, healthy=False, last_error="x")
        snap = await reg.snapshot()
        assert snap["total"] == 2
        assert snap["healthy"] == 1
        assert snap["unhealthy"] == 1
        assert {n["node_id"] for n in snap["nodes"]} == {
            n.node_id for n in await reg.list()
        }
    finally:
        reg.close()


async def test_node_to_dict_and_from_row_round_trip(tmp_path):
    reg = _registry(tmp_path)
    try:
        node = await reg.register(
            url="http://127.0.0.1:8008",
            capabilities=["cdp"],
            capacity=3,
            metadata={"name": "w"},
        )
        as_dict = node.to_dict()
        assert as_dict["node_id"] == node.node_id
        rebuilt = Node.from_row(as_dict)
        assert rebuilt == node
    finally:
        reg.close()
