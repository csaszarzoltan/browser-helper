"""
Pre-development interface tests for the SessionManager module (P1.1).

The original RED-phase behavioral tests asserted ``NotImplementedError``
for every SessionManager method. Those assertions are mutually exclusive
with the implemented module (a real implementation cannot raise
``NotImplementedError``), so the stale RED-phase tests were removed —
see commit a7952e5 for the same treatment applied to the compositor
tests. Behavioral coverage for SessionManager lives in
``tests/test_anti_detect_session.py`` (paired RED/GREEN file).

Acceptance criteria covered (analysis brief §7 — P1.1) via the
behavioral suite: capture/restore, save/load round-trip, WebSocket
pooling, is_expired/cleanup, list_sessions, and edge cases.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


from session_manager import SessionManager, SessionState

import pytest



# ─── Helpers ───────────────────────────────────────────────────────────



# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

def _make_session_state(**overrides) -> SessionState:
    """Build a ``SessionState`` with sensible defaults."""
    now = time.time()
    state = SessionState(
        session_id="test-session",
        cookies=[{"name": "session", "value": "abc123"}],
        local_storage={"user": "alice"},
        session_storage={"cart": "items"},
        url="https://example.com",
        created_at=now,
        last_active=now,
    )
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


# ─── Interface tests ───────────────────────────────────────────────────


class TestSessionStateInterface:
    """Contract tests for the ``SessionState`` dataclass."""

    def test_session_state_has_all_fields(self):
        """``SessionState`` has all expected fields."""
        state = _make_session_state()
        assert hasattr(state, "session_id")
        assert hasattr(state, "cookies")
        assert hasattr(state, "local_storage")
        assert hasattr(state, "session_storage")
        assert hasattr(state, "url")
        assert hasattr(state, "created_at")
        assert hasattr(state, "last_active")

    def test_session_state_typed_correctly(self):
        """Fields hold the expected types."""
        state = _make_session_state()
        assert isinstance(state.session_id, str)
        assert isinstance(state.cookies, list)
        assert isinstance(state.local_storage, dict)
        assert isinstance(state.session_storage, dict)
        assert isinstance(state.url, str)
        assert isinstance(state.created_at, float)
        assert isinstance(state.last_active, float)

    def test_session_state_custom_values(self):
        """``SessionState`` accepts custom field values via constructor."""
        state = SessionState(
            session_id="my-id",
            cookies=[{"a": "b"}],
            local_storage={"k": "v"},
            session_storage={"sk": "sv"},
            url="https://other.com",
            created_at=100.0,
            last_active=200.0,
        )
        assert state.session_id == "my-id"
        assert state.cookies == [{"a": "b"}]
        assert state.local_storage == {"k": "v"}
        assert state.session_storage == {"sk": "sv"}
        assert state.url == "https://other.com"
        assert state.created_at == 100.0
        assert state.last_active == 200.0

    def test_session_state_empty_storage(self):
        """``SessionState`` allows empty storage dicts."""
        state = _make_session_state(local_storage={}, session_storage={})
        assert state.local_storage == {}
        assert state.session_storage == {}
        assert state.cookies == [{"name": "session", "value": "abc123"}]


class TestSessionManagerInterface:
    """Contract tests for ``SessionManager`` constructor & defaults."""

    def test_constructor_creates_instance(self):
        """``SessionManager`` can be instantiated with defaults."""
        mgr = SessionManager()
        assert isinstance(mgr, SessionManager)

    def test_constructor_accepts_custom_storage_dir(self):
        """Custom ``storage_dir`` is honoured."""
        mgr = SessionManager(storage_dir="/tmp/my-sessions")
        assert str(mgr.storage_dir) == "/tmp/my-sessions"

    def test_constructor_accepts_custom_timeout(self):
        """Custom ``session_timeout`` is honoured."""
        mgr = SessionManager(session_timeout=7200)
        assert mgr.session_timeout == 7200

    def test_constructor_accepts_custom_cleanup_interval(self):
        """Custom ``cleanup_interval`` is honoured."""
        mgr = SessionManager(cleanup_interval=60.0)
        assert mgr.cleanup_interval == 60.0

    def test_default_timeout_is_one_hour(self):
        """Default ``session_timeout`` is 3600 seconds (1 hour)."""
        mgr = SessionManager()
        assert mgr.session_timeout == 3600

    def test_default_cleanup_interval_is_five_minutes(self):
        """Default ``cleanup_interval`` is 300 seconds (5 minutes)."""
        mgr = SessionManager()
        assert mgr.cleanup_interval == 300

    def test_default_storage_dir_is_dot_browser_helper(self):
        """Default ``storage_dir`` ends with ``.browser-helper/sessions``."""
        mgr = SessionManager()
        assert ".browser-helper" in str(mgr.storage_dir)
        assert "sessions" in str(mgr.storage_dir)

    def test_ws_cache_is_empty_dict(self):
        """``_ws_cache`` is initialised as an empty dict."""
        mgr = SessionManager()
        assert isinstance(mgr._ws_cache, dict)
        assert len(mgr._ws_cache) == 0

    def test_sessions_is_empty_dict(self):
        """``_sessions`` is initialised as an empty dict."""
        mgr = SessionManager()
        assert isinstance(mgr._sessions, dict)
        assert len(mgr._sessions) == 0

    def test_cleanup_task_is_none(self):
        """``_cleanup_task`` is ``None`` initially."""
        mgr = SessionManager()
        assert mgr._cleanup_task is None

    def test_cleanup_running_is_false(self):
        """``_cleanup_running`` is ``False`` initially."""
        mgr = SessionManager()
        assert mgr._cleanup_running is False
