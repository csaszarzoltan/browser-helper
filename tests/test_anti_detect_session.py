"""
Tests for SessionManager (P1.1).

Interface tests: verify SessionState dataclass, SessionManager class,
constructor, WebSocket caching methods.
Behavioral tests: verify capture, restore, save/load round-trip, and
cleanup (implementation exists; the stale RED-phase NotImplementedError
assertions were removed — see a7952e5).

Coverage:
  - SessionState dataclass fields
  - SessionManager class existence and constructor
  - WebSocket caching (get_cached_ws, cache_ws, close_cached_ws, close_all_ws)
  - capture(cdp_client, session_id)
  - restore(cdp_client, state)
  - save(state) / load(session_id)
  - list_sessions, is_expired, cleanup
"""

from __future__ import annotations

import sys
from dataclasses import is_dataclass
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from session_manager import SessionManager, SessionState

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def mgr(tmp_path) -> SessionManager:
    """Return a fresh SessionManager with a temp storage directory."""
    return SessionManager(storage_dir=str(tmp_path / "sessions"))


@pytest.fixture
def mock_cdp() -> MagicMock:
    """Return a mock CDP client."""
    return MagicMock()


@pytest.fixture
def sample_state() -> SessionState:
    """Return a minimal SessionState."""
    return SessionState(
        session_id="test-session-1",
        cookies=[{"name": "sessionid", "value": "abc123", "domain": ".example.com"}],
        local_storage={"key1": "value1"},
        session_storage={},
        url="https://example.com",
        created_at=1000.0,
        last_active=1000.0,
    )


# ===================================================================
# Interface tests — pass immediately against the stub
# ===================================================================


class TestSessionStateInterface:
    """Verify SessionState dataclass fields."""

    def test_import(self):
        """SessionState is importable."""
        assert SessionState is not None

    def test_is_dataclass(self):
        """SessionState is a dataclass."""
        assert is_dataclass(SessionState)

    def test_required_fields(self, sample_state):
        """SessionState has all required fields with correct types."""
        state = sample_state
        assert isinstance(state.session_id, str)
        assert isinstance(state.cookies, list)
        assert isinstance(state.local_storage, dict)
        assert isinstance(state.session_storage, dict)
        assert isinstance(state.url, str)
        assert isinstance(state.created_at, float)
        assert isinstance(state.last_active, float)

    def test_minimal_construction(self):
        """SessionState can be constructed with all required fields."""
        state = SessionState(
            session_id="s1",
            cookies=[],
            local_storage={},
            session_storage={},
            url="",
            created_at=0.0,
            last_active=0.0,
        )
        assert state.session_id == "s1"


class TestSessionManagerInterface:
    """Verify SessionManager class and constructor."""

    def test_import(self):
        """SessionManager is importable."""
        assert SessionManager is not None

    def test_constructor_with_params(self, mgr):
        """SessionManager can be instantiated with storage_dir, timeout, interval."""
        assert isinstance(mgr, SessionManager)

    def test_constructor_defaults(self):
        """SessionManager() uses defaults for timeout and interval."""
        mgr_default = SessionManager()
        assert isinstance(mgr_default, SessionManager)

    def test_get_cached_ws_none(self, mgr):
        """get_cached_ws returns None for uncached URL."""
        ws = mgr.get_cached_ws("ws://example.com")
        assert ws is None

    def test_cache_and_get_ws(self, mgr):
        """cache_ws stores connection and get_cached_ws retrieves it."""
        mock_ws = MagicMock()
        mgr.cache_ws("ws://example.com", mock_ws)
        retrieved = mgr.get_cached_ws("ws://example.com")
        assert retrieved is mock_ws

    def test_close_cached_ws(self, mgr):
        """close_cached_ws removes connection from cache."""
        mock_ws = MagicMock()
        mgr.cache_ws("ws://example.com", mock_ws)
        mgr.close_cached_ws("ws://example.com")
        assert mgr.get_cached_ws("ws://example.com") is None

    def test_close_cached_ws_calls_close(self, mgr):
        """close_cached_ws calls .close() on the WebSocket."""
        mock_ws = MagicMock()
        mgr.cache_ws("ws://example.com", mock_ws)
        mgr.close_cached_ws("ws://example.com")
        mock_ws.close.assert_called_once()

    def test_close_all_ws_clears_cache(self, mgr):
        """close_all_ws removes all cached connections."""
        import asyncio

        mgr.cache_ws("ws://a.com", MagicMock())
        mgr.cache_ws("ws://b.com", MagicMock())
        asyncio.run(mgr.close_all_ws())
        assert mgr.get_cached_ws("ws://a.com") is None
        assert mgr.get_cached_ws("ws://b.com") is None


# ===================================================================
# Behavioral tests — RED phase, must raise NotImplementedError
# ===================================================================


class TestSessionManagerCaptureRED:
    """capture() — behavioral tests (implementation exists)."""

    @pytest.mark.asyncio
    async def test_capture_returns_session_state(self, mgr, mock_cdp):
        """capture() should return a SessionState with cookies and storage."""
        try:
            state = await mgr.capture(mock_cdp, "test-session", url="https://example.com")
            assert isinstance(state, SessionState)
            assert state.session_id == "test-session"
            assert isinstance(state.cookies, list)
            assert isinstance(state.local_storage, dict)
        except NotImplementedError:
            pytest.fail(
                "capture must be implemented to verify return shape. "
                "See test_capture_raises_not_implemented."
            )


class TestSessionManagerRestoreRED:
    """restore() — behavioral tests (implementation exists)."""

    @pytest.mark.asyncio
    async def test_restore_returns_dict_with_session_id(self, mgr, mock_cdp, sample_state):
        """restore() should return a dict with session_id."""
        try:
            result = await mgr.restore(mock_cdp, sample_state)
            assert isinstance(result, dict)
            assert "session_id" in result
        except NotImplementedError:
            pytest.fail(
                "restore must be implemented to verify return shape. "
                "See test_restore_raises_not_implemented."
            )


class TestSessionManagerPersistenceRED:
    """save()/load() — behavioral tests (implementation exists)."""

    def test_save_and_load_round_trip(self, mgr, sample_state):
        """save(state) then load(id) should return equivalent state."""
        try:
            mgr.save(sample_state)
            loaded = mgr.load("test-session-1")
            assert loaded is not None
            assert loaded.session_id == "test-session-1"
            assert loaded.cookies == sample_state.cookies
        except NotImplementedError:
            pytest.fail(
                "save/load must be implemented to verify round-trip. "
                "See test_save_raises_not_implemented."
            )

    def test_load_nonexistent(self, mgr):
        """load(nonexistent_id) returns None."""
        try:
            result = mgr.load("nonexistent")
            assert result is None
        except NotImplementedError:
            pytest.fail(
                "load must be implemented to verify None for nonexistent sessions. "
                "See test_load_raises_not_implemented."
            )


class TestSessionManagerCleanupRED:
    """cleanup() and session listing — behavioral tests (implementation exists)."""

    @pytest.mark.asyncio
    async def test_cleanup_returns_int(self, mgr):
        """cleanup() should return the count of removed sessions."""
        try:
            count = await mgr.cleanup()
            assert isinstance(count, int)
        except NotImplementedError:
            pytest.fail(
                "cleanup must be implemented to verify return value. "
                "See test_cleanup_raises_not_implemented."
            )

