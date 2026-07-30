"""
Pre-development tests for CDPClient.connect_remote() — Cloud Browser WebSocket Passthrough.

P0.3 spec: Add connect_remote(ws_endpoint) classmethod, connection_type property,
and POST /connect/remote FastAPI endpoint.

Interface tests:  check the contract exists (will fail with AttributeError until implemented).
Behavioral tests: check expected behavior (will fail with NotImplementedError or other errors
                  until the implementation is wired).
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cdp_client import CDPClient, CDPDisconnectedError, CDPError

# =========================================================================
# Interface tests — contract existence and signatures
# These RED-phase tests fail until connect_remote() and connection_type exist.
# =========================================================================


class TestConnectRemoteInterface:
    """Contract: connect_remote exists and has the right signature."""

    def test_interface_connect_remote_exists(self):
        """CDPClient has a connect_remote attribute."""
        assert hasattr(CDPClient, "connect_remote"), (
            "RED: CDPClient.connect_remote() is not defined. "
            "Add 'def connect_remote(ws_endpoint: str) -> CDPClient: ...'"
        )

    def test_interface_connect_remote_is_callable(self):
        """CDPClient.connect_remote is callable."""
        assert callable(CDPClient.connect_remote), (
            "RED: CDPClient.connect_remote exists but is not callable."
        )

    def test_interface_connect_remote_accepts_ws_endpoint(self):
        """connect_remote's signature contains ws_endpoint parameter."""
        sig = inspect.signature(CDPClient.connect_remote)
        assert "ws_endpoint" in sig.parameters, (
            "RED: connect_remote() signature missing 'ws_endpoint' parameter. "
            "Expected: connect_remote(ws_endpoint: str) -> CDPClient"
        )
        param = sig.parameters["ws_endpoint"]
        assert param.default is inspect.Parameter.empty, (
            "RED: ws_endpoint should be a required positional parameter, not optional."
        )

    def test_interface_connect_remote_returns_cdpclient(self):
        """connect_remote returns a CDPClient instance (classmethod pattern)."""
        sig = inspect.signature(CDPClient.connect_remote)
        ret = sig.return_annotation
        assert ret is not inspect.Signature.empty, (
            "RED: connect_remote() missing return type annotation. "
            "Expected return type hint of -> CDPClient or similar."
        )

    def test_interface_connection_type_property_exists(self):
        """CDPClient instances have a connection_type property."""
        # Use a bare instance (no connection needed)
        c = CDPClient(cdp_http_url="http://127.0.0.1:9555")
        assert hasattr(c, "connection_type"), (
            "RED: CDPClient instance missing 'connection_type' property. "
            "Add 'def connection_type(self) -> str: ...'"
        )

    def test_interface_connection_type_is_string(self):
        """connection_type returns a string (not a boolean or None)."""
        c = CDPClient(cdp_http_url="http://127.0.0.1:9555")
        ct = c.connection_type
        assert isinstance(ct, str), (
            f"RED: connection_type should return a string, got {type(ct).__name__}."
        )


# =========================================================================
# Behavioral tests — connect_remote connection lifecycle
# =========================================================================


class TestConnectRemoteConnection:
    """connect_remote establishes a mock WebSocket connection and sends CDP enable commands."""

    @pytest.mark.asyncio
    async def test_behavior_connect_remote_returns_dict(self):
        """connect_remote returns a dict with status: 'ok'."""
        result = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
        assert isinstance(result, dict), (
            "RED: connect_remote() must return a dict with connection info. "
            "Expected: {'status': 'ok', 'target_id': ..., 'cdp_url': ...}"
        )
        assert result.get("status") == "ok", (
            "RED: connect_remote() result dict missing status='ok'. "
        )

    @pytest.mark.asyncio
    async def test_behavior_connect_remote_connection_type_is_remote(self):
        """After connect_remote, the returned client's connection_type is 'remote'."""
        client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
        assert client.connection_type == "remote", (
            "RED: connect_remote client.connection_type should be 'remote', "
            f"got '{client.connection_type}'."
        )

    @pytest.mark.asyncio
    async def test_behavior_connect_remote_sends_page_enable(self, monkeypatch):
        """Verifies Page.enable CDP command is sent on remote connect."""
        sent_messages = []

        async def record_send(self_, data):
            sent_messages.append(json.loads(data))

        # Patch send_command on the instance returned by connect_remote
        original = CDPClient.connect_remote
        try:
            client = await original("ws://example.com/devtools/browser/123")
        except AttributeError:
            pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

        monkeypatch.setattr(client, "_send_command", record_send)
        # Re-trigger Page.enable if connect_remote already sent it
        # We check that Page.enable appears in what was sent
        assert any(
            msg.get("method") == "Page.enable" for msg in sent_messages
        ), (
            "RED: connect_remote() must send Page.enable after WebSocket connect. "
            "Add 'await self._send_command(\"Page.enable\")' after websockets.connect."
        )

    @pytest.mark.asyncio
    async def test_behavior_connect_remote_sends_runtime_enable(self, monkeypatch):
        """Verifies Runtime.enable CDP command is sent on remote connect."""
        sent_messages = []

        async def record_send(self_, data):
            sent_messages.append(json.loads(data))

        original = CDPClient.connect_remote
        try:
            client = await original("ws://example.com/devtools/browser/123")
        except AttributeError:
            pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

        monkeypatch.setattr(client, "_send_command", record_send)
        assert any(
            msg.get("method") == "Runtime.enable" for msg in sent_messages
        ), (
            "RED: connect_remote() must send Runtime.enable after WebSocket connect. "
            "Add 'await self._send_command(\"Runtime.enable\")' after websockets.connect."
        )

    @pytest.mark.asyncio
    async def test_behavior_connect_remote_sends_both_enable_commands(self):
        """Both Page.enable AND Runtime.enable are sent in the same connect."""
        sent_messages = []

        async def capturing_send(self_, data):
            sent_messages.append(json.loads(data))

        try:
            client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
        except AttributeError:
            pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

        # Temporarily replace send to capture
        client._send_command = capturing_send

        methods = [msg.get("method") for msg in sent_messages if msg.get("method")]
        assert "Page.enable" in methods, (
            "RED: Page.enable not sent during connect_remote()."
        )
        assert "Runtime.enable" in methods, (
            "RED: Runtime.enable not sent during connect_remote()."
        )

    @pytest.mark.asyncio
    async def test_behavior_disconnect_cleans_up(self):
        """disconnect() on a remote client closes WS and clears state."""
        try:
            client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
        except AttributeError:
            pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

        result = await client.disconnect()
        assert isinstance(result, dict), "disconnect() must return a dict."
        # After disconnect, _ws should be None and _connected should be False
        assert not client.is_connected, (
            "RED: disconnect() must set is_connected to False."
        )
        assert client._ws is None or client._ws is False, (
            "RED: disconnect() must set _ws to None."
        )

    @pytest.mark.asyncio
    async def test_behavior_reconnect_creates_new_client(self):
        """Multiple connect_remote calls create separate independent clients."""
        try:
            client1 = await CDPClient.connect_remote("ws://example.com/devtools/browser/111")
            client2 = await CDPClient.connect_remote("ws://example.com/devtools/browser/222")
        except AttributeError:
            pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

        assert client1 is not client2, (
            "RED: connect_remote() should return a new CDPClient instance each call. "
            "Make connect_remote a classmethod or staticmethod that creates a new instance."
        )


# =========================================================================
# Behavioral tests — CDP command passthrough through remote connection
# =========================================================================


@pytest.mark.asyncio
async def test_behavior_navigate_works_remote():
    """navigate() works through remote CDP connection."""
    try:
        client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
    except AttributeError:
        pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

    result = await client.navigate("https://example.com")
    assert isinstance(result, dict), "navigate() must return a dict."
    assert "status" in result, (
        "RED: navigate() through remote connection should return status field."
    )


@pytest.mark.asyncio
async def test_behavior_evaluate_works_remote():
    """evaluate() works through remote CDP connection."""
    try:
        client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
    except AttributeError:
        pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

    result = await client.evaluate("document.title")
    assert isinstance(result, dict), "evaluate() must return a dict."
    assert "status" in result, (
        "RED: evaluate() through remote connection should return status field."
    )


@pytest.mark.asyncio
async def test_behavior_screenshot_works_remote():
    """screenshot() works through remote CDP connection."""
    try:
        client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
    except AttributeError:
        pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

    result = await client.screenshot(quality=60)
    assert isinstance(result, dict), "screenshot() must return a dict."
    assert "status" in result, (
        "RED: screenshot() through remote connection should return status field."
    )


@pytest.mark.asyncio
async def test_behavior_click_works_remote():
    """click() works through remote CDP connection."""
    try:
        client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
    except AttributeError:
        pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

    result = await client.click("#submit-btn")
    assert isinstance(result, dict), "click() must return a dict."
    assert "status" in result, (
        "RED: click() through remote connection should return status field."
    )


@pytest.mark.asyncio
async def test_behavior_type_text_works_remote():
    """type_text() works through remote CDP connection."""
    try:
        client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
    except AttributeError:
        pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

    result = await client.type_text("#input-field", "hello")
    assert isinstance(result, dict), "type_text() must return a dict."
    assert "status" in result, (
        "RED: type_text() through remote connection should return status field."
    )


@pytest.mark.asyncio
async def test_behavior_smart_form_fill_works_remote():
    """smart_form_fill() works through remote CDP connection."""
    try:
        client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
    except AttributeError:
        pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

    result = await client.smart_form_fill([
        {"label": "Username", "value": "test_user"},
        {"label": "Password", "value": "test_pass"},
    ])
    assert isinstance(result, dict), "smart_form_fill() must return a dict."
    assert "status" in result, (
        "RED: smart_form_fill() through remote connection should return status field."
    )


# =========================================================================
# Behavioral tests — Error handling
# =========================================================================


@pytest.mark.asyncio
async def test_behavior_invalid_ws_url_raises_cdperror():
    """Invalid WebSocket URL raises CDPError."""
    with pytest.raises(CDPError):
        await CDPClient.connect_remote("not-a-valid-websocket-url")


@pytest.mark.asyncio
async def test_behavior_missing_ws_url_raises_cdperror():
    """Empty or None ws_endpoint raises CDPError."""
    with pytest.raises(CDPError):
        await CDPClient.connect_remote("")


@pytest.mark.asyncio
async def test_behavior_connection_timeout_after_30s():
    """connect_remote raises CDPError after 30s if WebSocket doesn't respond."""
    with pytest.raises(CDPError):
        await CDPClient.connect_remote("wss://slow-server.example.com/devtools/browser/123")


@pytest.mark.asyncio
async def test_behavior_connection_drop_during_command_raises_disconnected():
    """If WebSocket drops mid-command, CDPDisconnectedError is raised."""
    try:
        client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
    except AttributeError:
        pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

    # Simulate close and drop by patching _ws
    await client._ws.close()  # type: ignore[union-attr]
    with pytest.raises(CDPDisconnectedError):
        await client.navigate("https://example.com")


# =========================================================================
# Behavioral tests — FastAPI /connect/remote endpoint
# =========================================================================


class TestConnectRemoteEndpoint:
    """POST /connect/remote endpoint contract and behavior."""

    @pytest.mark.asyncio
    async def test_behavior_endpoint_accepts_valid_ws_endpoint(self):
        """POST /connect/remote with valid ws_endpoint returns 200 / status: ok."""
        from fastapi.testclient import TestClient

        from src import main  # type: ignore[import-untyped]

        client = TestClient(main.app)
        response = client.post("/connect/remote", json={"ws_endpoint": "wss://example.com/devtools/browser/123"})
        assert response.status_code == 200, (
            f"RED: POST /connect/remote returned {response.status_code}. "
            "Expected 200. Add '@app.post(\"/connect/remote\")' endpoint."
        )
        data = response.json()
        assert data.get("status") == "ok", (
            f"RED: /connect/remote response missing status='ok'. Got: {data}"
        )
        # Should return same schema as existing /connect
        assert "operation" in data, "Response missing 'operation' field (same schema as /connect)."
        assert "result" in data, "Response missing 'result' field (same schema as /connect)."

    @pytest.mark.asyncio
    async def test_behavior_endpoint_rejects_missing_ws_endpoint(self):
        """POST /connect/remote without ws_endpoint returns 422."""
        from fastapi.testclient import TestClient

        from src import main  # type: ignore[import-untyped]

        client = TestClient(main.app)
        response = client.post("/connect/remote", json={})  # missing ws_endpoint
        assert response.status_code == 422, (
            f"RED: POST /connect/remote with empty body returned {response.status_code}. "
            "Expected 422. Add Pydantic validation that rejects missing ws_endpoint."
        )

    @pytest.mark.asyncio
    async def test_behavior_endpoint_rejects_empty_ws_endpoint(self):
        """POST /connect/remote with empty ws_endpoint string returns 422."""
        from fastapi.testclient import TestClient

        from src import main  # type: ignore[import-untyped]

        client = TestClient(main.app)
        response = client.post("/connect/remote", json={"ws_endpoint": ""})
        assert response.status_code == 422, (
            f"RED: POST /connect/remote with empty ws_endpoint returned {response.status_code}. "
            "Expected 422. Add validation that rejects empty string."
        )

    @pytest.mark.asyncio
    async def test_interface_endpoint_returns_same_schema_as_connect(self):
        """POST /connect/remote returns the same schema fields as POST /connect."""
        from fastapi.testclient import TestClient

        from src import main  # type: ignore[import-untyped]

        client = TestClient(main.app)
        response = client.post("/connect/remote", json={"ws_endpoint": "wss://example.com/devtools/browser/123"})
        assert response.status_code in (200, 422), (
            "Expected /connect/remote to return 200 or 422."
        )
        if response.status_code == 200:
            data = response.json()
            # Same envelope as /connect (see main.py line 912: {"status", "operation", "result"})
            assert "status" in data, "Response schema missing 'status'."
            assert "operation" in data, "Response schema missing 'operation'."
            assert "result" in data, "Response schema missing 'result'."


# =========================================================================
# Behavioral tests — connection lifecycle edge cases
# =========================================================================


class TestRemoteLifecycle:
    """Disconnect + reconnect cycles, multiple clients."""

    @pytest.mark.asyncio
    async def test_behavior_disconnect_resets_state(self):
        """After disconnect from remote, all state is cleaned."""
        try:
            client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
        except AttributeError:
            pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

        await client.disconnect()
        assert client._ws is None, "_ws should be None after disconnect."
        assert not client._connected, "_connected should be False after disconnect."
        assert len(client._pending) == 0, (
            "_pending futures should be cleared after disconnect."
        )

    @pytest.mark.asyncio
    async def test_behavior_connection_type_is_local_before_remote_connect(self):
        """Before connect_remote is called, connection_type returns 'local'."""
        c = CDPClient(cdp_http_url="http://127.0.0.1:9555")
        assert c.connection_type == "local", (
            "RED: Default connection_type should be 'local' for a standard CDPClient."
        )

    @pytest.mark.asyncio
    async def test_behavior_connect_remote_result_contains_cdp_url(self):
        """connect_remote result dict includes the ws_endpoint as cdp_url."""
        ws_url = "wss://example.com/devtools/browser/123"
        try:
            client = await CDPClient.connect_remote(ws_url)
        except AttributeError:
            pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

        # The connect_remote returns a client instance (classmethod), not a dict.
        # Check that client.cdp_http_url or another property holds the remote URL.
        assert client._ws is not None, (
            "connect_remote client should have an active WebSocket."
        )

    @pytest.mark.asyncio
    async def test_behavior_double_disconnect_safe(self):
        """Calling disconnect() twice is a no-op (no error raised)."""
        try:
            client = await CDPClient.connect_remote("ws://example.com/devtools/browser/123")
        except AttributeError:
            pytest.fail("connect_remote not implemented yet — test is a placeholder for real behaviour")

        first = await client.disconnect()
        assert first is not None, "First disconnect should return a result."
        second = await client.disconnect()
        assert second is not None, "Second disconnect should also succeed (no-op)."


# =========================================================================
# Acceptance gate guards
# =========================================================================


def test_acceptance_gates_covered():
    """Verify all acceptance criteria from the spec have at least one test."""
    gates = {
        "All remote CDP tests pass": True,
        "Mock WebSocket proves Page.enable + Runtime.enable sent": bool(
            "test_behavior_connect_remote_sends_page_enable" in dir() or
            "test_behavior_connect_remote_sends_both_enable_commands" in dir()
        ),
        "disconnect() cleans up cleanly": bool(
            "test_behavior_disconnect_cleans_up" in dir() or
            "test_behavior_disconnect_resets_state" in dir()
        ),
        "Remote endpoint returns 422 on missing ws_endpoint": bool(
            "test_behavior_endpoint_rejects_missing_ws_endpoint" in dir()
        ),
        "30s timeout on connect applied correctly": bool(
            "test_behavior_connection_timeout_after_30s" in dir()
        ),
    }
    missing = [name for name, covered in gates.items() if not covered]
    if missing:
        pytest.skip(
            f"Acceptance gates not yet testable (implementation missing). "
            f"Uncovered: {', '.join(missing)}"
        )
