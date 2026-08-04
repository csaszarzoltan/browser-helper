"""Unit tests for src/fleet/storage.py — FleetSQLite persistence layer.

These exercise the storage foundation directly (no HTTP): table creation,
JSON round-tripping, atomic capacity counters, and the FIFO+TTL queue.
The 29 HTTP-level tests in tests/test_fleet_v115.py are the API contract
and belong to the API-wiring task.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

import pytest

from fleet.storage import FleetSQLite, default_db_path, new_session_id

pytestmark = pytest.mark.quick


def _storage(tmp_path) -> FleetSQLite:
    return FleetSQLite(db_path=str(tmp_path / "fleet.db"))


async def _must_get_node(db: FleetSQLite, node_id: str) -> dict[str, Any]:
    node = await db.get_node(node_id)
    assert node is not None
    return node


async def _must_get_session(db: FleetSQLite, session_id: str) -> dict[str, Any]:
    session = await db.get_session(session_id)
    assert session is not None
    return session


async def test_default_db_path_honors_fleet_db_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEET_DB_PATH", str(tmp_path / "env.db"))
    assert default_db_path() == str(tmp_path / "env.db")


async def test_creates_all_three_tables(tmp_path):
    db = _storage(tmp_path)
    try:
        names = {
            r["name"]
            for r in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"fleet_nodes", "fleet_sessions", "fleet_queue"} <= names
        (mode,) = db._conn.execute("PRAGMA journal_mode").fetchone()
        assert mode == "wal"
    finally:
        db.close()


async def test_add_and_get_node_round_trip(tmp_path):
    db = _storage(tmp_path)
    try:
        node = await db.add_node(
            url="http://127.0.0.1:8001",
            capabilities=["cdp", "headless"],
            capacity=5,
            metadata={"region": "us-east", "name": "worker-1"},
        )
        assert node["node_id"].startswith("node_")
        assert node["capabilities"] == ["cdp", "headless"]
        assert node["metadata"]["region"] == "us-east"
        assert node["capacity"] == 5
        assert node["active_sessions"] == 0
        assert node["healthy"] is True
        assert "registered_at" in node

        again = await _must_get_node(db, node["node_id"])
        assert again == node
    finally:
        db.close()


async def test_duplicate_url_raises_integrity_error(tmp_path):
    db = _storage(tmp_path)
    try:
        await db.add_node(url="http://127.0.0.1:8003")
        with pytest.raises(sqlite3.IntegrityError):
            await db.add_node(url="http://127.0.0.1:8003")
    finally:
        db.close()


async def test_same_url_can_register_after_unregister(tmp_path):
    db = _storage(tmp_path)
    try:
        first = await db.add_node(url="http://127.0.0.1:8004")
        assert await db.unregister_node(first["node_id"]) is True
        second = await db.add_node(url="http://127.0.0.1:8004")
        assert second["node_id"] != first["node_id"]
    finally:
        db.close()


async def test_unregister_soft_deletes_and_hides_from_listing(tmp_path):
    db = _storage(tmp_path)
    try:
        node = await db.add_node(url="http://127.0.0.1:8005")
        node_id = node["node_id"]
        assert await db.unregister_node(node_id) is True
        # hidden from live listings but still readable by id (audit)
        assert node_id not in [n["node_id"] for n in await db.list_nodes()]
        assert await db.get_node(node_id) is not None
        # repeat unregister returns False (maps to 404)
        assert await db.unregister_node(node_id) is False
    finally:
        db.close()


async def test_list_healthy_nodes_sorted_by_load(tmp_path):
    db = _storage(tmp_path)
    try:
        idle = await db.add_node(url="http://a:8001", capacity=5)
        busy = await db.add_node(url="http://b:8002", capacity=5)
        await db.add_session(
            session_id=new_session_id(),
            node_id=busy["node_id"],
            node_url="http://b:8002",
        )
        healthy = await db.list_healthy_nodes()
        loads = [n["active_sessions"] for n in healthy]
        assert loads == sorted(loads)
        assert [n["node_id"] for n in healthy] == [idle["node_id"], busy["node_id"]]
    finally:
        db.close()


async def test_update_node_health_and_capacity(tmp_path):
    db = _storage(tmp_path)
    try:
        node = await db.add_node(url="http://127.0.0.1:8006")
        node_id = node["node_id"]
        assert (
            await db.update_node_health(node_id, healthy=False, last_error="boom")
            is True
        )
        updated = await _must_get_node(db, node_id)
        assert updated["healthy"] is False
        assert updated["last_error"] == "boom"
        assert updated["last_checked"] > 0

        assert await db.update_node_capacity(node_id, 10) is True
        assert (await _must_get_node(db, node_id))["capacity"] == 10
        assert await db.update_node_health("missing", healthy=True) is False
        assert await db.update_node_capacity("missing", 10) is False
    finally:
        db.close()


async def test_add_session_increments_node_load_and_active_count(tmp_path):
    db = _storage(tmp_path)
    try:
        node = await db.add_node(url="http://127.0.0.1:8007", capacity=5)
        node_id = node["node_id"]
        session = await db.add_session(
            session_id=new_session_id(),
            node_id=node_id,
            node_url="http://127.0.0.1:8007",
        )
        assert session["status"] == "active"
        assert (await _must_get_node(db, node_id))["active_sessions"] == 1
        assert await db.active_count(node_id) == 1
        # release frees the slot
        assert await db.release_session(session["session_id"]) is True
        assert (await _must_get_node(db, node_id))["active_sessions"] == 0
        assert await db.active_count(node_id) == 0
    finally:
        db.close()


async def test_release_unknown_session_returns_false(tmp_path):
    db = _storage(tmp_path)
    try:
        assert await db.release_session("sess_nope") is False
    finally:
        db.close()


async def test_update_session_and_save_state(tmp_path):
    db = _storage(tmp_path)
    try:
        node = await db.add_node(url="http://127.0.0.1:8008")
        session = await db.add_session(
            session_id=new_session_id(),
            node_id=node["node_id"],
            node_url="http://127.0.0.1:8008",
        )
        assert (
            await db.save_session_state(
                session["session_id"], {"cookies": [{"name": "sid", "value": "x"}]}
            )
            is True
        )
        stored = await _must_get_session(db, session["session_id"])
        assert stored["saved_state"]["cookies"][0]["name"] == "sid"

        assert await db.update_session(session["session_id"], status="failed") is True
        assert (await _must_get_session(db, session["session_id"]))["status"] == "failed"
        with pytest.raises(ValueError):
            await db.update_session(session["session_id"], bogus_field=1)
    finally:
        db.close()


async def test_reassign_session_moves_counters(tmp_path):
    db = _storage(tmp_path)
    try:
        node_a = await db.add_node(url="http://a:8001")
        node_b = await db.add_node(url="http://b:8002")
        session = await db.add_session(
            session_id=new_session_id(),
            node_id=node_a["node_id"],
            node_url="http://a:8001",
        )
        assert (
            await db.reassign_session(
                session["session_id"], node_b["node_id"], "http://b:8002"
            )
            is True
        )
        assert (await _must_get_node(db, node_a["node_id"]))["active_sessions"] == 0
        assert (await _must_get_node(db, node_b["node_id"]))["active_sessions"] == 1
        stored = await _must_get_session(db, session["session_id"])
        assert stored["node_id"] == node_b["node_id"]
        assert stored["status"] == "active"
    finally:
        db.close()


async def test_enqueue_dequeue_fifo_order(tmp_path):
    db = _storage(tmp_path)
    try:
        first = await db.enqueue_request("sess_1", ttl_seconds=60)
        second = await db.enqueue_request("sess_2", ttl_seconds=60)
        assert first["queue_position"] >= 1
        assert second["queue_position"] > first["queue_position"]
        assert await db.queue_size() == 2

        popped = await db.dequeue_ready()
        assert popped is not None
        assert popped["session_id"] == "sess_1"
        assert await db.queue_size() == 1
        second_popped = await db.dequeue_ready()
        assert second_popped is not None
        assert second_popped["session_id"] == "sess_2"
        assert await db.dequeue_ready() is None
    finally:
        db.close()


async def test_dequeue_skips_expired_and_prune_purges(tmp_path):
    db = _storage(tmp_path)
    try:
        await db.enqueue_request("sess_ttl", ttl_seconds=0.05)
        await asyncio.sleep(0.1)
        # expired entry must not be popped
        assert await db.dequeue_ready() is None
        # but the sweep purges it
        assert await db.prune_expired() >= 1
        assert await db.queue_size() == 0
    finally:
        db.close()
