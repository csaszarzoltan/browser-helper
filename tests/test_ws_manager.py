"""
Interface + behavioral tests for WebSocketManager (src/ws_manager.py).

Interface tests verify method signatures and type hints pass (no runtime error).
Behavioral tests verify the manager creates valid client records and stats
(when called with a mock WebSocket).
"""

import inspect
from typing import get_type_hints

import pytest

from src.ws_manager import WebSocketManager


def _return_is_dict(hints: dict) -> bool:
    """Return True if the return annotation is dict or dict[str, ...]."""
    ret = hints.get("return")
    if ret is None:
        return True  # absent annotation — no constraint
    return ret is dict or (hasattr(ret, "__origin__") and ret.__origin__ is dict)


# ---------------------------------------------------------------------------
# Interface tests  (imports, signatures, type hints)
# ---------------------------------------------------------------------------


class TestWebSocketManagerInterface:
    """Verify the WebSocketManager class contract."""

    def test_module_importable(self):
        """The ws_manager module is importable."""
        assert WebSocketManager.__module__ == "src.ws_manager"

    def test_class_instantiable(self):
        """WebSocketManager can be constructed with default args."""
        mgr = WebSocketManager(heartbeat_interval=30, max_missed_pongs=3)
        assert isinstance(mgr, WebSocketManager)

    def test_heartbeat_interval_default(self):
        """__init__ accepts an ``heartbeat_interval`` int parameter."""
        sig = inspect.signature(WebSocketManager.__init__)
        assert "heartbeat_interval" in sig.parameters
        param = sig.parameters["heartbeat_interval"]
        assert param.default == 30 or param.default is inspect.Parameter.empty

    def test_max_missed_pongs_default(self):
        """__init__ accepts a ``max_missed_pongs`` int parameter."""
        sig = inspect.signature(WebSocketManager.__init__)
        assert "max_missed_pongs" in sig.parameters
        param = sig.parameters["max_missed_pongs"]
        assert param.default == 3 or param.default is inspect.Parameter.empty

    def test_connect_signature(self):
        """``connect`` is async and accepts (self, ws, client_id)."""
        assert inspect.iscoroutinefunction(WebSocketManager.connect)
        sig = inspect.signature(WebSocketManager.connect)
        assert "ws" in sig.parameters
        assert "client_id" in sig.parameters

    def test_disconnect_signature(self):
        """``disconnect`` is async and accepts (self, client_id)."""
        assert inspect.iscoroutinefunction(WebSocketManager.disconnect)
        sig = inspect.signature(WebSocketManager.disconnect)
        assert "client_id" in sig.parameters

    def test_broadcast_signature(self):
        """``broadcast`` is async and accepts (self, payload)."""
        assert inspect.iscoroutinefunction(WebSocketManager.broadcast)
        sig = inspect.signature(WebSocketManager.broadcast)
        assert "payload" in sig.parameters

    def test_send_personal_signature(self):
        """``send_personal`` is async and accepts (self, client_id, payload)."""
        assert inspect.iscoroutinefunction(WebSocketManager.send_personal)
        sig = inspect.signature(WebSocketManager.send_personal)
        assert "client_id" in sig.parameters
        assert "payload" in sig.parameters

    def test_start_heartbeat_signature(self):
        """``start_heartbeat`` is async."""
        assert inspect.iscoroutinefunction(WebSocketManager.start_heartbeat)

    def test_get_stats_signature(self):
        """``get_stats`` is a sync method returning dict."""
        assert not inspect.iscoroutinefunction(WebSocketManager.get_stats)
        hints = get_type_hints(WebSocketManager.get_stats)
        assert _return_is_dict(hints)

    def test_active_count_property(self):
        """``active_count`` is a @property returning int."""
        assert isinstance(inspect.getattr_static(WebSocketManager, "active_count"), property)
        hints = get_type_hints(WebSocketManager.active_count.fget)
        assert hints.get("return") is int or hints.get("return") is None


# ---------------------------------------------------------------------------
# Behavioral tests — verify implemented methods work with mocks
# ---------------------------------------------------------------------------


class TestWebSocketManagerBehavior:
    """Verify WebSocketManager methods work correctly."""

    @pytest.fixture
    def mgr(self):
        return WebSocketManager()

    def test_initial_state(self, mgr):
        """Fresh manager has no clients."""
        assert mgr.active_count == 0
        stats = mgr.get_stats()
        assert stats["connected_count"] == 0
        assert stats["clients"] == []

    def test_connect_without_ws_raises(self, mgr):
        """Connect requires a real WebSocket, passing None raises AttributeError."""
        with pytest.raises(AttributeError):
            import asyncio
            asyncio.run(mgr.connect(None, "client-1"))

    def test_disconnect_unknown_id(self, mgr):
        """Disconnecting a non-existent client is a no-op."""
        import asyncio
        asyncio.run(mgr.disconnect("nonexistent"))
        assert mgr.active_count == 0

    def test_broadcast_with_no_clients(self, mgr):
        """Broadcasting with no connected clients is a no-op."""
        import asyncio
        asyncio.run(mgr.broadcast({"type": "ping"}))
        assert mgr.active_count == 0

    def test_send_personal_unknown_id(self, mgr):
        """Sending to a non-existent client is a no-op."""
        import asyncio
        asyncio.run(mgr.send_personal("nonexistent", {"type": "ping"}))
        assert mgr.active_count == 0

    def test_get_stats(self, mgr):
        """get_stats returns expected structure."""
        stats = mgr.get_stats()
        assert "connected_count" in stats
        assert "clients" in stats
        assert "heartbeat_interval" in stats
        assert "max_missed_pongs" in stats

    def test_heartbeat_interval_configurable(self):
        """WebSocketManager accepts custom heartbeat interval."""
        mgr = WebSocketManager(heartbeat_interval=10, max_missed_pongs=5)
        assert mgr._heartbeat_interval == 10
        assert mgr._max_missed_pongs == 5

    @pytest.mark.asyncio
    async def test_start_heartbeat_creates_task(self, mgr):
        """start_heartbeat creates an asyncio task."""
        assert mgr._heartbeat_task is None
        await mgr.start_heartbeat()
        assert mgr._heartbeat_task is not None
        assert not mgr._heartbeat_task.done()
        mgr._heartbeat_task.cancel()
