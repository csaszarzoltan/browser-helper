"""Tests for WebSocket endpoint, broadcast_state, log_operation in main.py.

Covers:
- log_operation() — ring buffer append, state sync, 100-entry cap
- broadcast_state() — sends to all ws_clients, removes stale connections
- /ws endpoint — connect, hello, ping/pong, JSON actions, error handling, disconnect
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ─── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_main_state():
    """Reset module-level state after each test to prevent cross-test leakage.

    Imports main *after* we've cleared the module cache so each test gets a
    fresh copy of ws_clients, operation_log, state, and start_time.
    """
    # Remove any cached main module
    for key in list(sys.modules.keys()):
        if "main" in key and "uvicorn" not in key:
            del sys.modules[key]
    yield


def _import_main():
    """Import and return the main module, forcing a fresh load."""
    for key in list(sys.modules.keys()):
        if "main" in key and "uvicorn" not in key:
            del sys.modules[key]
    import main as m
    return m


# ─── Tests: log_operation() ───────────────────────────────────────────

class TestLogOperation:
    """log_operation() appends entries to the ring buffer and syncs state."""

    def test_appends_entry(self):
        main = _import_main()
        entry = main.log_operation("navigate", "success", 123.45, "Navigated to example.com")
        assert entry["operation"] == "navigate"
        assert entry["status"] == "success"
        assert entry["duration_ms"] == 123.45
        assert "timestamp" in entry
        assert entry["details"] == "Navigated to example.com"
        assert len(main.operation_log) == 1
        assert main.operation_log[-1] is entry

    def test_updates_state(self):
        main = _import_main()
        main.log_operation("connect", "success", 50.0)
        assert main.state["last_operation"] == "connect"
        assert main.state["last_operation_time"] is not None
        # state.connected reflects client.is_connected (False for fresh client)
        assert main.state["connected"] is False

    def test_ring_buffer_cap_at_100(self):
        main = _import_main()
        for i in range(110):
            main.log_operation(f"op_{i}", "success", float(i))
        assert len(main.operation_log) == 100
        # First entry popped — oldest should be op_10
        assert main.operation_log[0]["operation"] == "op_10"
        assert main.operation_log[-1]["operation"] == "op_109"

    def test_empty_details_defaults_to_empty_string(self):
        main = _import_main()
        entry = main.log_operation("eval", "error", 0.5)
        assert entry["details"] == ""

    def test_duration_rounding(self):
        main = _import_main()
        entry = main.log_operation("test", "success", 123.45678)
        assert entry["duration_ms"] == 123.46  # round to 2 decimal places


# ─── Tests: broadcast_state() ─────────────────────────────────────────

class TestBroadcastState:
    """broadcast_state() pushes state to all connected WS clients."""

    @pytest.mark.asyncio
    async def test_sends_to_all_clients(self):
        main = _import_main()
        # Reset ws_clients to empty
        main.ws_clients.clear()
        main.log_operation("connect", "success", 10.0)

        mock_ws_1 = AsyncMock()
        mock_ws_2 = AsyncMock()
        main.ws_clients.add(mock_ws_1)
        main.ws_clients.add(mock_ws_2)

        await main.broadcast_state()

        assert mock_ws_1.send_json.called
        assert mock_ws_2.send_json.called
        # Verify the payload shape
        call_args = mock_ws_1.send_json.call_args[0][0]
        assert call_args["type"] == "state_update"
        assert "state" in call_args
        assert "recent_log" in call_args
        assert call_args["state"]["connected"] is False

    @pytest.mark.asyncio
    async def test_removes_stale_clients(self):
        main = _import_main()
        main.ws_clients.clear()
        main.log_operation("test", "success", 1.0)

        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_json.side_effect = RuntimeError("Connection lost")
        main.ws_clients.add(good_ws)
        main.ws_clients.add(bad_ws)

        await main.broadcast_state()

        # stale client should be removed
        assert bad_ws not in main.ws_clients
        assert good_ws in main.ws_clients

    @pytest.mark.asyncio
    async def test_no_clients_does_not_raise(self):
        main = _import_main()
        main.ws_clients.clear()
        # Should not raise with empty set
        await main.broadcast_state()

    @pytest.mark.asyncio
    async def test_log_slice_in_payload(self):
        main = _import_main()
        main.ws_clients.clear()
        for i in range(15):
            main.log_operation(f"op_{i}", "success", float(i))
        mock_ws = AsyncMock()
        main.ws_clients.add(mock_ws)

        await main.broadcast_state()

        payload = mock_ws.send_json.call_args[0][0]
        assert len(payload["recent_log"]) == 10  # last 10 entries
        assert payload["recent_log"][0]["operation"] == "op_5"
        assert payload["recent_log"][-1]["operation"] == "op_14"


# ─── Tests: ws_clients set management ─────────────────────────────────

class TestWsClientsSet:
    """ws_clients is properly scoped and initialised."""

    def test_initialised_as_empty_set(self):
        main = _import_main()
        assert isinstance(main.ws_clients, set)
        assert len(main.ws_clients) == 0


# ─── Tests: WebSocket endpoint (via TestClient) ───────────────────────

class TestWebSocketEndpoint:
    """Test /ws WebSocket endpoint lifecycle and message handling."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Import and prepare the app for WS testing, patching the CDP client.

        Stores the module reference as ``self.main`` so test methods see the
        *same* ws_clients / operation_log / state as the app under test.
        """
        main = _import_main()
        main.ws_clients.clear()
        main.operation_log.clear()
        self.main = main
        # Patch the module-level `client` so WS actions don't touch real CDP
        self._patcher = patch.object(main, "client", autospec=True)
        self._mock_client = self._patcher.start()
        self._mock_client.is_connected = False
        self._mock_client.tabs_count = 0
        self.app = main.app
        yield
        self._patcher.stop()

    @pytest.mark.asyncio
    async def test_connect_receives_hello(self):
        from fastapi.testclient import TestClient
        client = TestClient(self.app)
        with client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert "state" in hello
            assert "recent_log" in hello

    @pytest.mark.asyncio
    async def test_connect_adds_to_ws_clients(self):
        from fastapi.testclient import TestClient
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()  # hello
            assert len(self.main.ws_clients) == 1
            websocket_instance = list(self.main.ws_clients)[0]
            assert websocket_instance is not None

    @pytest.mark.asyncio
    async def test_ping_pong(self):
        from fastapi.testclient import TestClient
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()  # hello
            ws.send_text("ping")
            pong = ws.receive_json()
            assert pong["type"] == "pong"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        from fastapi.testclient import TestClient
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()  # hello
            ws.send_text("this is not json")
            err = ws.receive_json()
            assert err["type"] == "error"
            assert "Invalid JSON" in err["message"]

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        from fastapi.testclient import TestClient
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()  # hello
            ws.send_text(json.dumps({"action": "nonexistent"}))
            err = ws.receive_json()
            assert err["type"] == "error"
            assert "nonexistent" in err["message"]

    @pytest.mark.asyncio
    async def test_status_action(self):
        from fastapi.testclient import TestClient
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()  # hello
            ws.send_text(json.dumps({"action": "status"}))
            resp = ws.receive_json()
            assert resp["type"] == "status"
            assert "connected" in resp
            assert "tabs_count" in resp

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_clients(self):
        from fastapi.testclient import TestClient
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()  # hello
            assert len(self.main.ws_clients) == 1
        # After context manager exit, client should be removed
        assert len(self.main.ws_clients) == 0

    @pytest.mark.asyncio
    async def test_multiple_connections(self):
        from fastapi.testclient import TestClient
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws1:
            _ = ws1.receive_json()  # hello
            with tc.websocket_connect("/ws") as ws2:
                _ = ws2.receive_json()  # hello
                assert len(self.main.ws_clients) == 2
        assert len(self.main.ws_clients) == 0

    @pytest.mark.asyncio
    async def test_action_screenshot_returns_error_when_disconnected(self):
        from fastapi.testclient import TestClient
        self._mock_client.screenshot = AsyncMock(side_effect=Exception("Not connected"))
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()  # hello
            ws.send_text(json.dumps({"action": "screenshot"}))
            # The endpoint catches the exception and sends an error
            resp = ws.receive_json()
            assert resp["type"] == "error"

    @pytest.mark.asyncio
    async def test_action_screenshot_success(self):
        from fastapi.testclient import TestClient
        self._mock_client.screenshot = AsyncMock(
            return_value={"data": "abcdef", "format": "jpeg", "size": 6}
        )
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()  # hello
            ws.send_text(json.dumps({"action": "screenshot"}))
            resp = ws.receive_json()
            assert resp["type"] == "screenshot"
            assert resp["data"] == "abcdef"

    @pytest.mark.asyncio
    async def test_action_eval(self):
        from fastapi.testclient import TestClient
        self._mock_client.evaluate = AsyncMock(
            return_value={"status": "ok", "result": 42, "type": "number"}
        )
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()
            ws.send_text(json.dumps({"action": "eval", "js": "1+1"}))
            resp = ws.receive_json()
            assert resp["type"] == "eval_result"
            assert resp["result"]["result"] == 42

    @pytest.mark.asyncio
    async def test_action_navigate(self):
        from fastapi.testclient import TestClient
        self._mock_client.navigate = AsyncMock(
            return_value={"status": "ok", "frame_id": "f1", "url": "https://example.com"}
        )
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()
            ws.send_text(json.dumps({"action": "navigate", "url": "https://example.com"}))
            resp = ws.receive_json()
            assert resp["type"] == "navigate_result"
            assert resp["result"]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_action_click(self):
        from fastapi.testclient import TestClient
        self._mock_client.click = AsyncMock(
            return_value={"status": "ok", "selector": ".btn", "position": {"x": 100, "y": 200}}
        )
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()
            ws.send_text(json.dumps({"action": "click", "selector": ".btn"}))
            resp = ws.receive_json()
            assert resp["type"] == "click_result"
            assert resp["result"]["selector"] == ".btn"

    @pytest.mark.asyncio
    async def test_action_get_text(self):
        from fastapi.testclient import TestClient
        self._mock_client.get_page_text = AsyncMock(
            return_value={"status": "ok", "text": "Hello world", "length": 11}
        )
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()
            ws.send_text(json.dumps({"action": "get_text"}))
            resp = ws.receive_json()
            assert resp["type"] == "text_result"
            assert resp["result"]["text"] == "Hello world"

    @pytest.mark.asyncio
    async def test_action_get_cookies(self):
        from fastapi.testclient import TestClient
        self._mock_client.get_cookies = AsyncMock(
            return_value={"status": "ok", "cookies": [], "count": 0}
        )
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()
            ws.send_text(json.dumps({"action": "get_cookies"}))
            resp = ws.receive_json()
            assert resp["type"] == "cookies_result"
            assert resp["result"]["count"] == 0

    @pytest.mark.asyncio
    async def test_action_batch(self):
        from fastapi.testclient import TestClient
        self._mock_client.navigate = AsyncMock(
            return_value={"status": "ok", "frame_id": "f1", "url": "https://example.com"}
        )
        self._mock_client.get_page_text = AsyncMock(
            return_value={"status": "ok", "text": "content", "length": 7}
        )
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()
            ws.send_text(json.dumps({
                "action": "batch",
                "steps": [
                    {"action": "navigate", "url": "https://example.com"},
                    {"action": "get_text"},
                ],
            }))
            resp = ws.receive_json()
            assert resp["type"] == "batch_result"
            assert resp["steps"] == 2
            assert resp["results"][0]["status"] == "ok"
            assert resp["results"][1]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_action_batch_unknown_action(self):
        from fastapi.testclient import TestClient
        tc = TestClient(self.app)
        with tc.websocket_connect("/ws") as ws:
            _ = ws.receive_json()
            ws.send_text(json.dumps({
                "action": "batch",
                "steps": [{"action": "nonexistent_action"}],
            }))
            resp = ws.receive_json()
            assert resp["type"] == "batch_result"
            assert resp["results"][0]["status"] == "ok"  # caught as 'error' result
            assert "Unknown action" in resp["results"][0]["result"]["error"]
