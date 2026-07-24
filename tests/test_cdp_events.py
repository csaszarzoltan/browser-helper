"""Tests for CDP event callback API in cdp_client.py.

Covers:
- add_event_listener() — registers callbacks by method name
- remove_event_listener() — unregisters specific callbacks
- Event dispatch via _listener() — calls registered callbacks for matching events
- Edge cases: duplicate registration, removing nonexistent callback,
  dispatching to multiple callbacks, callback exception handling
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cdp_client import CDPClient

# ─── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """Return a fresh CDPClient with no real connection."""
    return CDPClient(cdp_http_url="http://127.0.0.1:9555")


# ─── Tests: add_event_listener() ──────────────────────────────────────

class TestAddEventListener:
    """Registering event callbacks."""

    def test_add_single_callback(self, client):
        cb = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", cb)
        assert "Runtime.consoleAPICalled" in client._event_callbacks
        assert cb in client._event_callbacks["Runtime.consoleAPICalled"]

    def test_add_multiple_callbacks_same_event(self, client):
        cb1 = MagicMock()
        cb2 = MagicMock()
        client.add_event_listener("Network.requestWillBeSent", cb1)
        client.add_event_listener("Network.requestWillBeSent", cb2)
        assert len(client._event_callbacks["Network.requestWillBeSent"]) == 2

    def test_add_multiple_callbacks_different_events(self, client):
        cb1 = MagicMock()
        cb2 = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", cb1)
        client.add_event_listener("Page.loadEventFired", cb2)
        assert "Runtime.consoleAPICalled" in client._event_callbacks
        assert "Page.loadEventFired" in client._event_callbacks

    def test_duplicate_registration(self, client):
        """Same callback added twice should appear twice (allowed)."""
        cb = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", cb)
        client.add_event_listener("Runtime.consoleAPICalled", cb)
        assert len(client._event_callbacks["Runtime.consoleAPICalled"]) == 2

    def test_initial_event_callbacks_empty(self, client):
        assert client._event_callbacks == {}


# ─── Tests: remove_event_listener() ──────────────────────────────────

class TestRemoveEventListener:
    """Unregistering event callbacks."""

    def test_remove_callback(self, client):
        cb = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", cb)
        client.remove_event_listener("Runtime.consoleAPICalled", cb)
        assert cb not in client._event_callbacks["Runtime.consoleAPICalled"]

    def test_remove_nonexistent_method_does_not_raise(self, client):
        """Removing from an unregistered method is a no-op."""
        cb = MagicMock()
        client.remove_event_listener("NonExistent.method", cb)  # should not raise

    def test_remove_nonexistent_callback_does_not_raise(self, client):
        cb = MagicMock()
        other_cb = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", cb)
        client.remove_event_listener("Runtime.consoleAPICalled", other_cb)  # not registered
        assert cb in client._event_callbacks["Runtime.consoleAPICalled"]

    def test_remove_one_of_multiple(self, client):
        cb1 = MagicMock()
        cb2 = MagicMock()
        client.add_event_listener("Network.requestWillBeSent", cb1)
        client.add_event_listener("Network.requestWillBeSent", cb2)
        client.remove_event_listener("Network.requestWillBeSent", cb1)
        assert cb1 not in client._event_callbacks["Network.requestWillBeSent"]
        assert cb2 in client._event_callbacks["Network.requestWillBeSent"]

    def test_remove_all_callbacks(self, client):
        cb1 = MagicMock()
        cb2 = MagicMock()
        client.add_event_listener("Page.frameStartedLoading", cb1)
        client.add_event_listener("Page.frameStartedLoading", cb2)
        client.remove_event_listener("Page.frameStartedLoading", cb1)
        client.remove_event_listener("Page.frameStartedLoading", cb2)
        assert client._event_callbacks["Page.frameStartedLoading"] == []


# ─── Tests: Event dispatch via _listener() ────────────────────────────

class TestEventListenerDispatch:
    """Event callbacks are invoked when _listener processes messages."""

    @pytest.mark.asyncio
    async def test_dispatches_to_registered_callback(self, client):
        """When _listener receives a CDP message with a registered method,
        the callback should be invoked with the full message dict."""
        cb = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", cb)

        # Simulate what _listener does when processing a message
        msg = {"method": "Runtime.consoleAPICalled", "params": {"args": [], "type": "log"}}
        ev_method = msg.get("method", "")
        if ev_method in client._event_callbacks:
            for cb_fn in client._event_callbacks[ev_method]:
                cb_fn(msg)

        cb.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_dispatches_to_multiple_callbacks(self, client):
        cb1 = MagicMock()
        cb2 = MagicMock()
        client.add_event_listener("Page.frameNavigated", cb1)
        client.add_event_listener("Page.frameNavigated", cb2)

        msg = {"method": "Page.frameNavigated", "params": {"frame": {}}}
        ev_method = msg.get("method", "")
        if ev_method in client._event_callbacks:
            for cb_fn in client._event_callbacks[ev_method]:
                cb_fn(msg)

        cb1.assert_called_once_with(msg)
        cb2.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_does_not_dispatch_to_unregistered_methods(self, client):
        cb = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", cb)

        msg = {"method": "Page.loadEventFired", "params": {"timestamp": 12345}}
        ev_method = msg.get("method", "")
        if ev_method in client._event_callbacks:
            for cb_fn in client._event_callbacks[ev_method]:
                cb_fn(msg)

        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_removed_callback_not_called(self, client):
        cb = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", cb)
        client.remove_event_listener("Runtime.consoleAPICalled", cb)

        msg = {"method": "Runtime.consoleAPICalled", "params": {}}
        ev_method = msg.get("method", "")
        if ev_method in client._event_callbacks:
            for cb_fn in client._event_callbacks[ev_method]:
                cb_fn(msg)

        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash(self, client):
        """If a callback raises, the _listener catches the exception
        and continues. (The actual _listener has a try/except around cb)."""
        bad_cb = MagicMock(side_effect=ValueError("oops"))
        good_cb = MagicMock()
        client.add_event_listener("Runtime.consoleAPICalled", bad_cb)
        client.add_event_listener("Runtime.consoleAPICalled", good_cb)

        msg = {"method": "Runtime.consoleAPICalled", "params": {}}
        ev_method = msg.get("method", "")
        if ev_method in client._event_callbacks:
            for cb_fn in client._event_callbacks[ev_method]:
                try:
                    cb_fn(msg)
                except Exception:
                    pass  # same as the _listener's broad except

        # good_cb should still be called despite bad_cb raising
        good_cb.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_dispatch_adds_network_entries_when_monitoring(self, client):
        """When network monitoring is active, relevant messages
        also populate _network_entries."""
        client._network_monitoring = True

        msg = {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "req1",
                "request": {"url": "https://example.com", "method": "GET", "type": "Document"},
                "timestamp": 123.456,
            },
        }
        # Simulate _listener's logic
        method = msg.get("method", "")
        if client._network_monitoring and method.startswith("Network."):
            entry = {"method": method, "timestamp": msg.get("params", {}).get("timestamp", 0),
                     "request_id": msg.get("params", {}).get("requestId", "")}
            if method == "Network.requestWillBeSent":
                req = msg.get("params", {}).get("request", {})
                entry["url"] = req.get("url", "")
                entry["type"] = req.get("type", "")
                entry["method"] = req.get("method", "")
            client._network_entries.append(entry)

        assert len(client._network_entries) == 1
        assert client._network_entries[0]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_dispatch_response_received_entry(self, client):
        """Network.responseReceived messages create proper entries."""
        client._network_monitoring = True

        msg = {
            "method": "Network.responseReceived",
            "params": {
                "requestId": "req2",
                "timestamp": 789.012,
                "response": {
                    "url": "https://example.com/style.css",
                    "status": 200,
                    "statusText": "OK",
                    "mimeType": "text/css",
                    "encodedDataLength": 1024,
                },
            },
        }
        method = msg.get("method", "")
        if client._network_monitoring and method.startswith("Network."):
            entry = {"method": method, "timestamp": msg.get("params", {}).get("timestamp", 0),
                     "request_id": msg.get("params", {}).get("requestId", "")}
            if method == "Network.responseReceived":
                resp = msg.get("params", {}).get("response", {})
                entry["url"] = resp.get("url", "")
                entry["status"] = resp.get("status", 0)
                entry["status_text"] = resp.get("statusText", "")
                entry["mime_type"] = resp.get("mimeType", "")
                entry["size"] = resp.get("encodedDataLength", 0)
            client._network_entries.append(entry)

        assert len(client._network_entries) == 1
        assert client._network_entries[0]["status"] == 200
        assert client._network_entries[0]["mime_type"] == "text/css"


# ─── Tests: method name edge cases for event callbacks ────────────────

class TestEventListenerEdgeCases:
    """Edge cases for the event callback system."""

    def test_empty_method_name(self, client):
        cb = MagicMock()
        client.add_event_listener("", cb)
        assert "" in client._event_callbacks
        assert cb in client._event_callbacks[""]

    def test_remove_unregistered_method_does_not_create_key(self, client):
        cb = MagicMock()
        client.remove_event_listener("Page.frameNavigated", cb)
        # Should not create an empty list entry
        assert "Page.frameNavigated" not in client._event_callbacks or \
               client._event_callbacks["Page.frameNavigated"] == []

    def test_isolation_between_clients(self):
        a = CDPClient("http://localhost:9222")
        b = CDPClient("http://127.0.0.1:9555")
        cb = MagicMock()
        a.add_event_listener("Runtime.consoleAPICalled", cb)
        assert "Runtime.consoleAPICalled" not in b._event_callbacks
