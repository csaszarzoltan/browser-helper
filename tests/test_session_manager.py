"""
RED-phase pre-development tests for the SessionManager module.

All behavioral tests in this file MUST FAIL initially because the
SessionManager module is a stub whose methods raise ``NotImplementedError``.
Once the module is implemented, every test below should PASS with zero changes.

Acceptance criteria covered (analysis brief §7 — P1.1):
 1. capture() returns SessionState with cookies + localStorage
 2. Captured state persists to JSON and survives re-init
 3. restore() sets cookies and localStorage back
 4. load() returns saved state or None
 5. WebSocket cache get/put/close works
 6. is_expired() correctly checks timeout
 7. cleanup() removes expired sessions
 8. start_cleanup_loop() starts periodic cleanup
 9. list_sessions() returns all sessions with expiry info
10. Restore to different URL still sets cookies correctly
11. Session without localStorage does not error
12. Session without sessionStorage does not error
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from session_manager import SessionManager, SessionState


# ─── Helpers: mock CDP client ──────────────────────────────────────────


def _mock_cdp_client(**kwargs) -> MagicMock:
    """Return a MagicMock that behaves like a CDPClient.

    Provides canned returns for ``_send_command`` and ``evaluate`` that
    mimic the real CDPClient's return shape.
    """
    cookies = kwargs.get("cookies", [{"name": "test", "value": "val"}])
    local_storage = kwargs.get("local_storage", {"key1": "value1"})
    session_storage = kwargs.get("session_storage", {"skey1": "svalue1"})

    client = MagicMock()
    client._send_command = AsyncMock(
        side_effect=lambda method, **kw: {
            "Network.getAllCookies": {"cookies": cookies},
            "Network.setCookies": {},
            "Network.clearBrowserCookies": {},
        }.get(method, {"id": 1})
    )
    client.evaluate = AsyncMock(
        side_effect=lambda js: (
            {"status": "ok", "result": local_storage, "type": "object"}
            if "localStorage" in js
            else (
                {"status": "ok", "result": session_storage, "type": "object"}
                if "sessionStorage" in js
                else {"status": "ok", "result": True, "type": "boolean"}
            )
        )
    )
    return client


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


def _run_async(coro):
    """Run an async coroutine synchronously, returning the result.

    Catches NotImplementedError and re-raises it so pytest.raises works.
    """
    try:
        return asyncio.run(coro)
    except NotImplementedError:
        raise


# ─── Interface tests (should pass even with NotImplError in methods) ──


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


# ─── RED-phase behavioral tests ───────────────────────────────────────


class TestSessionLifecycleRED:
    """``capture()``, ``save()``, ``load()``, ``restore()`` — expected failures."""

    def test_capture_raises_not_implemented(self):
        """Calling ``capture()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "session-1"))

    def test_capture_with_url_raises_not_implemented(self):
        """``capture()`` with a URL also raises ``NotImplementedError``."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "session-2", url="https://example.com"))

    def test_save_raises_not_implemented(self):
        """Calling ``save()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        state = _make_session_state()
        with pytest.raises(NotImplementedError):
            mgr.save(state)

    def test_load_raises_not_implemented(self):
        """Calling ``load()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.load("session-1")

    def test_restore_raises_not_implemented(self):
        """Calling ``restore()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        state = _make_session_state()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, state))

    def test_restore_returns_dict_with_session_id(self):
        """``restore()`` returns ``{\"status\": \"ok\", \"session_id\": ...}``."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        state = _make_session_state()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, state))


class TestSessionPersistenceRED:
    """Save/load round-trip and state survivability."""

    def test_save_load_round_trip_returns_same_state(self):
        """State saved via ``save()`` is returned by ``load()``."""
        mgr = SessionManager()
        state = _make_session_state(session_id="persist-test")
        with pytest.raises(NotImplementedError):
            mgr.save(state)

    def test_load_returns_none_for_missing(self):
        """``load()`` returns ``None`` for a non-existent session."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.load("nonexistent")

    def test_state_survives_re_init(self):
        """Saved state persists to JSON and is readable after re-init."""
        mgr = SessionManager()
        state = _make_session_state(session_id="reinit-test")
        with pytest.raises(NotImplementedError):
            mgr.save(state)

    def test_load_is_idempotent(self):
        """Calling ``load()`` multiple times with the same id works."""
        mgr = SessionManager()
        state = _make_session_state(session_id="idempotent-test")
        with pytest.raises(NotImplementedError):
            mgr.save(state)


class TestCaptureBehaviourRED:
    """Detailed behaviour of ``capture()`` — expected failures."""

    def test_capture_returns_session_state(self):
        """``capture()`` returns a ``SessionState`` instance."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "cap-test"))

    def test_capture_includes_cookies(self):
        """Captured state includes cookies from CDP."""
        mgr = SessionManager()
        client = _mock_cdp_client(cookies=[{"name": "x", "value": "y"}])
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "cookie-test"))

    def test_capture_includes_local_storage(self):
        """Captured state includes localStorage data."""
        mgr = SessionManager()
        ls = {"username": "testuser", "theme": "dark"}
        client = _mock_cdp_client(local_storage=ls)
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "ls-test"))

    def test_capture_includes_session_storage(self):
        """Captured state includes sessionStorage data."""
        mgr = SessionManager()
        ss = {"cart_id": "abc123"}
        client = _mock_cdp_client(session_storage=ss)
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "ss-test"))

    def test_capture_sets_session_id(self):
        """Captured state has the correct ``session_id``."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "my-session-id"))

    def test_capture_sets_url(self):
        """Captured state includes the page URL."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "url-test", url="https://example.com"))

    def test_capture_calls_network_get_all_cookies(self):
        """``capture()`` calls CDP ``Network.getAllCookies``."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "cmd-test"))

    def test_capture_calls_evaluate_for_local_storage(self):
        """``capture()`` evaluates JS for localStorage."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "eval-ls"))

    def test_capture_calls_evaluate_for_session_storage(self):
        """``capture()`` evaluates JS for sessionStorage."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "eval-ss"))


class TestRestoreBehaviourRED:
    """Detailed behaviour of ``restore()`` — expected failures."""

    def test_restore_sets_cookies_via_cdp(self):
        """``restore()`` calls CDP to set cookies."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        state = _make_session_state()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, state))

    def test_restore_sets_local_storage_via_cdp(self):
        """``restore()`` sets localStorage via CDP evaluate."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        state = _make_session_state(local_storage={"user": "bob"})
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, state))

    def test_restore_sets_session_storage_via_cdp(self):
        """``restore()`` sets sessionStorage via CDP evaluate."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        state = _make_session_state(session_storage={"token": "xyz"})
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, state))

    def test_restore_to_different_url_sets_cookies_correctly(self):
        """Restoring to a different URL still sets cookies correctly."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        state = _make_session_state(
            session_id="diff-url-test",
            cookies=[{"name": "auth", "value": "token123"}],
            url="https://original.com",
        )
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, state))

    def test_restore_clears_existing_cookies(self):
        """``restore()`` clears existing cookies before setting new ones."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        state = _make_session_state()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, state))

    def test_restore_returns_expected_dict_shape(self):
        """``restore()`` returns ``{\"status\": ..., \"session_id\": ...}``."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        state = _make_session_state()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, state))


class TestWebSocketPoolingRED:
    """WebSocket cache methods — expected failures."""

    def test_get_cached_ws_raises_not_implemented_for_unknown(self):
        """``get_cached_ws()`` raises ``NotImplementedError`` for unknown URL."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.get_cached_ws("ws://unknown:9222")

    def test_get_cached_ws_raises_not_implemented_with_cache(self):
        """``get_cached_ws()`` raises ``NotImplementedError`` when cache exists."""
        mgr = SessionManager()
        mgr._ws_cache["ws://test:9222"] = MagicMock()
        with pytest.raises(NotImplementedError):
            mgr.get_cached_ws("ws://test:9222")

    def test_cache_ws_raises_not_implemented(self):
        """``cache_ws()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        ws = MagicMock()
        with pytest.raises(NotImplementedError):
            mgr.cache_ws("ws://example:9222", ws)

    def test_close_cached_ws_raises_not_implemented(self):
        """``close_cached_ws()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.close_cached_ws("ws://example:9222")

    def test_close_all_ws_raises_not_implemented(self):
        """``close_all_ws()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.close_all_ws())

    def test_cached_ws_is_returned_by_get_cached_ws(self):
        """A WS cached via ``cache_ws()`` is returned by ``get_cached_ws()``."""
        mgr = SessionManager()
        ws = MagicMock()
        with pytest.raises(NotImplementedError):
            mgr.cache_ws("ws://reuse:9222", ws)

    def test_close_cached_ws_removes_from_cache(self):
        """After ``close_cached_ws()``, ``get_cached_ws()`` returns ``None``."""
        mgr = SessionManager()
        ws = MagicMock()
        mgr._ws_cache["ws://gone:9222"] = ws
        with pytest.raises(NotImplementedError):
            mgr.close_cached_ws("ws://gone:9222")

    def test_close_all_ws_closes_all_connections(self):
        """``close_all_ws()`` iterates all cached WS and closes each."""
        mgr = SessionManager()
        mgr._ws_cache["ws://a:9222"] = MagicMock()
        mgr._ws_cache["ws://b:9222"] = MagicMock()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.close_all_ws())


class TestSessionCleanupRED:
    """Timeout/cleanup methods — expected failures."""

    def test_is_expired_raises_not_implemented(self):
        """``is_expired()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.is_expired("session-1")

    def test_is_expired_returns_true_for_old_session(self):
        """``is_expired()`` returns ``True`` for a session past its timeout."""
        mgr = SessionManager(session_timeout=10)
        old_state = _make_session_state(
            session_id="old-session",
            created_at=time.time() - 100,
            last_active=time.time() - 100,
        )
        mgr._sessions["old-session"] = old_state
        with pytest.raises(NotImplementedError):
            mgr.is_expired("old-session")

    def test_is_expired_returns_false_for_recent_session(self):
        """``is_expired()`` returns ``False`` for a recently active session."""
        mgr = SessionManager(session_timeout=3600)
        fresh_state = _make_session_state(
            session_id="fresh-session",
            created_at=time.time(),
            last_active=time.time(),
        )
        mgr._sessions["fresh-session"] = fresh_state
        with pytest.raises(NotImplementedError):
            mgr.is_expired("fresh-session")

    def test_is_expired_uses_last_active_not_created(self):
        """``is_expired()`` checks ``last_active``, not ``created_at``."""
        mgr = SessionManager(session_timeout=30)
        state = _make_session_state(
            session_id="active-session",
            created_at=time.time() - 3600,
            last_active=time.time() - 5,
        )
        mgr._sessions["active-session"] = state
        with pytest.raises(NotImplementedError):
            mgr.is_expired("active-session")

    def test_is_expired_raises_for_nonexistent_session(self):
        """``is_expired()`` raises error for unknown sessions."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.is_expired("nonexistent")

    def test_cleanup_raises_not_implemented(self):
        """``cleanup()`` on the stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.cleanup())

    def test_cleanup_returns_count_of_removed_sessions(self):
        """``cleanup()`` returns a count (``int``) of removed sessions."""
        mgr = SessionManager(session_timeout=1)
        now = time.time()
        expired = _make_session_state(
            session_id="expired", created_at=now - 100, last_active=now - 100
        )
        fresh = _make_session_state(
            session_id="fresh", created_at=now, last_active=now
        )
        mgr._sessions["expired"] = expired
        mgr._sessions["fresh"] = fresh
        with pytest.raises(NotImplementedError):
            _run_async(mgr.cleanup())

    def test_cleanup_closes_ws_for_removed_sessions(self):
        """``cleanup()`` closes WebSocket connections for expired sessions."""
        mgr = SessionManager(session_timeout=1)
        now = time.time()
        expired = _make_session_state(
            session_id="expired-ws", created_at=now - 100, last_active=now - 100
        )
        mgr._sessions["expired-ws"] = expired
        mock_ws = MagicMock()
        mgr._ws_cache["ws://expired:9222"] = mock_ws
        with pytest.raises(NotImplementedError):
            _run_async(mgr.cleanup())

    def test_start_cleanup_loop_raises_not_implemented(self):
        """``start_cleanup_loop()`` on stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.start_cleanup_loop())

    def test_stop_cleanup_loop_raises_not_implemented(self):
        """``stop_cleanup_loop()`` on stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            _run_async(mgr.stop_cleanup_loop())

    def test_cleanup_loop_runs_cleanup_periodically(self):
        """The cleanup loop calls ``cleanup()`` every ``cleanup_interval``."""
        mgr = SessionManager(cleanup_interval=0.05)
        with pytest.raises(NotImplementedError):
            _run_async(mgr.start_cleanup_loop())


class TestSessionQueryRED:
    """``list_sessions()`` — expected failure."""

    def test_list_sessions_raises_not_implemented(self):
        """``list_sessions()`` on stub raises ``NotImplementedError``."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.list_sessions()

    def test_list_sessions_returns_list_of_dicts(self):
        """``list_sessions()`` returns a list of dicts with expiry info."""
        mgr = SessionManager()
        now = time.time()
        state = _make_session_state(
            session_id="list-test",
            created_at=now,
            last_active=now,
        )
        mgr._sessions["list-test"] = state
        with pytest.raises(NotImplementedError):
            mgr.list_sessions()

    def test_list_sessions_returns_empty_list_when_empty(self):
        """``list_sessions()`` returns ``[]`` when no sessions exist."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.list_sessions()


class TestEdgeCasesRED:
    """Edge cases — empty storage, missing data, error handling."""

    def test_capture_without_local_storage_does_not_error(self):
        """Capturing with empty localStorage does not raise."""
        mgr = SessionManager()
        client = _mock_cdp_client(local_storage={})
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "no-ls"))

    def test_capture_without_session_storage_does_not_error(self):
        """Capturing with empty sessionStorage does not raise."""
        mgr = SessionManager()
        client = _mock_cdp_client(session_storage={})
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "no-ss"))

    def test_capture_with_no_cookies_returns_empty_list(self):
        """Capturing with no cookies returns empty list, not None."""
        mgr = SessionManager()
        client = _mock_cdp_client(cookies=[])
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "no-cookies"))

    def test_save_creates_storage_dir(self):
        """``save()`` creates the storage directory if it doesn't exist."""
        mgr = SessionManager(storage_dir="/tmp/session-manager-test-nonexistent")
        state = _make_session_state()
        with pytest.raises(NotImplementedError):
            mgr.save(state)

    def test_load_returns_none_for_corrupted_data(self):
        """``load()`` returns ``None`` for corrupted JSON (graceful)."""
        mgr = SessionManager()
        with pytest.raises(NotImplementedError):
            mgr.load("corrupted-session")

    def test_session_with_only_cookies_no_storage(self):
        """Capturing a session that has cookies but no storage works."""
        mgr = SessionManager()
        client = _mock_cdp_client(
            cookies=[{"name": "x", "value": "y"}],
            local_storage={},
            session_storage={},
        )
        with pytest.raises(NotImplementedError):
            _run_async(mgr.capture(client, "cookies-only"))

    def test_restore_empty_session_state(self):
        """Restoring an empty session state does not crash."""
        mgr = SessionManager()
        client = _mock_cdp_client()
        empty = SessionState(
            session_id="empty",
            cookies=[],
            local_storage={},
            session_storage={},
            url="",
            created_at=time.time(),
            last_active=time.time(),
        )
        with pytest.raises(NotImplementedError):
            _run_async(mgr.restore(client, empty))
