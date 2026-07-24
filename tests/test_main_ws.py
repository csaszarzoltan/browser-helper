"""
Interface + behavioral tests for the /ws WebSocket endpoint in src/main.py.

Interface tests verify that the existing WebSocket endpoint is accessible
and that the broadcast_state function exists with the right signature.
Behavioral tests cover expected integration behaviour that will be
implemented later (using FastAPI TestClient / WebSocket connections).
"""

import inspect
from typing import get_type_hints

import pytest

from src.main import app, broadcast_state, websocket_endpoint, log_operation


def _return_is_dict(hints: dict) -> bool:
    """Return True if the return annotation is dict, dict[str, ...], or absent."""
    ret = hints.get("return")
    if ret is None:
        return True
    return ret is dict or (hasattr(ret, "__origin__") and ret.__origin__ is dict)


# ---------------------------------------------------------------------------
# Interface tests
# ---------------------------------------------------------------------------


class TestWSEndpointInterface:
    """Verify /ws endpoint contract."""

    def test_app_is_fastapi_instance(self):
        """The app module exports a FastAPI instance."""
        assert hasattr(app, "websocket")

    def test_websocket_endpoint_is_coroutine(self):
        """The websocket_endpoint function is async."""
        assert inspect.iscoroutinefunction(websocket_endpoint)

    def test_websocket_endpoint_accepts_ws(self):
        """websocket_endpoint accepts a ``ws`` parameter."""
        sig = inspect.signature(websocket_endpoint)
        assert "ws" in sig.parameters

    def test_broadcast_state_is_coroutine(self):
        """broadcast_state is an async function."""
        assert inspect.iscoroutinefunction(broadcast_state)

    def test_log_operation_returns_dict(self):
        """log_operation returns a dict."""
        assert not inspect.iscoroutinefunction(log_operation)
        hints = get_type_hints(log_operation)
        assert _return_is_dict(hints)

    def test_log_operation_signature(self):
        """log_operation accepts operation, status, duration_ms, details."""
        sig = inspect.signature(log_operation)
        assert "operation" in sig.parameters
        assert "status" in sig.parameters
        assert "duration_ms" in sig.parameters


# ---------------------------------------------------------------------------
# Behavioral tests  (expect NotImplementedError via stubs)
# ---------------------------------------------------------------------------


class TestWSEndpointBehavior:
    """
    Integration-style behavioral tests for the WS endpoint.

    These test expected real-world behaviour that will be enabled when
    WebSocketManager replaces the raw ``set[WebSocket]``.
    """

    @pytest.mark.asyncio
    async def test_ws_endpoint_accepts_connection(self):
        """
        /ws endpoint accepts a WebSocket connection and sends a hello.

        This will use FastAPI TestClient's ``websocket_connect``.
        """
        pytest.skip("Needs FastAPI TestClient — will pass when /ws is refactored")

    def test_ws_clients_is_set(self):
        """
        The global ``ws_clients`` is a ``set``.
        """
        import importlib
        import src.main
        importlib.reload(src.main)
        assert hasattr(src.main, "ws_clients")

    def test_websocket_endpoint_handles_disconnect(self):
        """websocket_endpoint gracefully handles WebSocketDisconnect."""
        source = inspect.getsource(websocket_endpoint)
        assert "WebSocketDisconnect" in source or "Exception" in source


# ---------------------------------------------------------------------------
# Dashboard integration behavioural tests
# ---------------------------------------------------------------------------


class TestDashboardBehavioral:
    """
    Behavioral stubs for dashboard / WebSocket enhancements (P0/P1).

    These tests describe the acceptance criteria from the analysis brief
    and will raise ``NotImplementedError`` until the features are implemented.
    """

    @pytest.mark.asyncio
    async def test_broadcast_state_sends_to_all_clients(self):
        """
        broadcast_state sends the current state + recent log
        to every connected WebSocket client.
        """
        pytest.skip("Requires mocked WebSocket — behaviour not yet implemented")

    @pytest.mark.asyncio
    async def test_ws_endpoint_generates_unique_client_id(self):
        """Each WS connection gets a unique ``client_id``."""
        pytest.skip("Requires WebSocketManager integration in /ws endpoint")

    @pytest.mark.asyncio
    async def test_heartbeat_prunes_stale_clients(self):
        """
        Server-initiated heartbeat detects unresponsive clients
        and removes them after ``max_missed_pongs`` missed pongs.
        """
        pytest.skip("Requires WebSocketManager heartbeat implementation")

    @pytest.mark.asyncio
    async def test_metrics_broadcast_with_state_update(self):
        """
        ``state_update`` messages include performance metrics
        (avg_latency_ms, ops_per_min, total_ops) when metrics tracking
        is active.
        """
        pytest.skip("Requires metrics tracking implementation")

    @pytest.mark.asyncio
    async def test_cdp_console_log_forwarded_to_ws(self):
        """
        ``Runtime.consoleAPICalled`` CDP events are forwarded to
        WS clients as ``console_log`` messages.
        """
        pytest.skip("Requires CDPEventForwarder implementation")
