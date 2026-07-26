"""Tests for browser-helper headless manager."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from headless_manager import (
    HeadlessManager,
    SessionHandle,
    SessionPool,
    _find_free_port,
    _kill_process,
)


class TestSessionPool:
    def test_initial_state(self):
        """Empty pool should have zero active sessions."""
        pool = SessionPool(max_sessions=3)
        assert pool.active_count == 0
        assert pool.can_launch() is True

    def test_add_and_get_session(self):
        """Should store and retrieve sessions by ID."""
        pool = SessionPool(max_sessions=3)
        handle = SessionHandle(
            session_id="test-1",
            chrome_pid=1234,
            cdp_url="http://127.0.0.1:19222",
            port=19222,
            created_at=0.0,
            last_active=0.0,
            status="active",
        )
        pool.add(handle)
        assert pool.active_count == 1
        assert pool.can_launch() is True
        assert pool.get("test-1") is handle

    def test_max_sessions_limit(self):
        """Should not allow launching when max sessions reached."""
        pool = SessionPool(max_sessions=2)
        for i in range(2):
            pool.add(SessionHandle(
                session_id=f"s{i}",
                chrome_pid=100 + i,
                cdp_url=f"http://127.0.0.1:{19222 + i}",
                port=19222 + i,
                created_at=0.0,
                last_active=0.0,
                status="active",
            ))
        assert pool.can_launch() is False

    def test_remove_session(self):
        """Should remove session and decrease active count."""
        pool = SessionPool(max_sessions=3)
        pool.add(SessionHandle(
            session_id="rm-1",
            chrome_pid=1234,
            cdp_url="http://127.0.0.1:19222",
            port=19222,
            created_at=0.0,
            last_active=0.0,
            status="active",
        ))
        removed = pool.remove("rm-1")
        assert removed is not None
        assert pool.active_count == 0
        assert pool.get("rm-1") is None

    def test_remove_nonexistent_returns_none(self):
        """Removing non-existent session should return None."""
        pool = SessionPool()
        assert pool.remove("nope") is None

    def test_active_sessions_filter(self):
        """active_sessions should only return active/idle sessions."""
        pool = SessionPool(max_sessions=5)
        pool.add(SessionHandle(
            session_id="a1", chrome_pid=1, cdp_url="", port=0,
            created_at=0, last_active=0, status="active",
        ))
        pool.add(SessionHandle(
            session_id="c1", chrome_pid=2, cdp_url="", port=0,
            created_at=0, last_active=0, status="closed",
        ))
        active = pool.active_sessions()
        assert len(active) == 1
        assert active[0].session_id == "a1"


class TestHeadlessManager:
    def test_default_config(self):
        """HeadlessManager should have correct defaults."""
        mgr = HeadlessManager()
        assert mgr.session_timeout == 300
        assert mgr.cpu_threshold == 80.0
        assert mgr.memory_limit_mb == 512.0
        assert mgr.pool.max_sessions == 5

    def test_custom_config(self):
        """HeadlessManager should accept custom config."""
        mgr = HeadlessManager(
            max_sessions=10,
            session_timeout=600,
            cpu_threshold=90.0,
            memory_limit_mb=1024.0,
        )
        assert mgr.pool.max_sessions == 10
        assert mgr.session_timeout == 600
        assert mgr.cpu_threshold == 90.0
        assert mgr.memory_limit_mb == 1024.0

    @pytest.mark.asyncio
    async def test_launch_session_max_reached(self):
        """Should fail when max sessions reached."""
        mgr = HeadlessManager(max_sessions=0)
        result = await mgr.launch_session()
        assert result["status"] == "error"
        assert "Max concurrent sessions" in result["error"]

    @pytest.mark.asyncio
    async def test_close_nonexistent_session(self):
        """Closing non-existent session should return error."""
        mgr = HeadlessManager()
        result = await mgr.close_session("nope")
        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_get_sessions_empty(self):
        """Should return empty list when no sessions."""
        mgr = HeadlessManager()
        sessions = mgr.get_sessions()
        assert sessions == []

    def test_health_check(self):
        """Health check should return pool stats and limits."""
        mgr = HeadlessManager()
        health = mgr.health_check()
        assert health["status"] == "ok"
        assert health["pool"]["max_sessions"] == 5
        assert health["pool"]["active_count"] == 0
        assert health["limits"]["session_timeout"] == 300
        assert health["limits"]["cpu_threshold"] == 80.0
        assert health["limits"]["memory_limit_mb"] == 512.0
        assert health["sessions"] == []

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """Shutdown should complete without error."""
        mgr = HeadlessManager()
        await mgr.shutdown()  # No sessions to close


class TestHelpers:
    def test_find_free_port(self):
        """Should find a port number."""
        port = _find_free_port()
        assert isinstance(port, int)
        assert port > 0

    def test_kill_process_nonexistent(self):
        """Killing non-existent process should not raise."""
        _kill_process(999999999)  # Should not raise
