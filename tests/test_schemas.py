"""Tests for event schema (src/schemas.py).

Tests verify that every factory function produces correct message dicts
with the expected structure and field types.
"""

import inspect
from typing import get_type_hints

import pytest

from src.schemas import (
    WsMessage,
    make_hello,
    make_state_update,
    make_console_log,
    make_navigation,
    make_operation,
    make_ping,
    make_pong,
    make_error,
    utc_timestamp,
)


def _return_is_dict(hints: dict) -> bool:
    """Return True if the return annotation is dict, dict[str, ...], or absent."""
    ret = hints.get("return")
    if ret is None:
        return True
    return ret is dict or (hasattr(ret, "__origin__") and ret.__origin__ is dict)


# ---------------------------------------------------------------------------
# Interface tests
# ---------------------------------------------------------------------------


class TestMessageFactoryInterface:
    """Verify each factory function has the right signature."""

    def test_make_hello_signature(self):
        sig = inspect.signature(make_hello)
        assert "state" in sig.parameters
        assert "recent_log" in sig.parameters
        hints = get_type_hints(make_hello)
        assert _return_is_dict(hints)

    def test_make_state_update_signature(self):
        sig = inspect.signature(make_state_update)
        assert "state" in sig.parameters
        assert "recent_log" in sig.parameters
        hints = get_type_hints(make_state_update)
        assert _return_is_dict(hints)

    def test_make_console_log_signature(self):
        sig = inspect.signature(make_console_log)
        assert "level" in sig.parameters
        assert "message" in sig.parameters
        hints = get_type_hints(make_console_log)
        assert _return_is_dict(hints)

    def test_make_navigation_signature(self):
        sig = inspect.signature(make_navigation)
        assert "url" in sig.parameters
        assert "frame_id" in sig.parameters
        hints = get_type_hints(make_navigation)
        assert _return_is_dict(hints)

    def test_make_operation_signature(self):
        sig = inspect.signature(make_operation)
        assert "operation" in sig.parameters
        assert "status" in sig.parameters
        assert "duration_ms" in sig.parameters
        hints = get_type_hints(make_operation)
        assert _return_is_dict(hints)

    def test_make_ping_signature(self):
        sig = inspect.signature(make_ping)
        hints = get_type_hints(make_ping)
        assert _return_is_dict(hints)

    def test_make_pong_signature(self):
        sig = inspect.signature(make_pong)
        hints = get_type_hints(make_pong)
        assert _return_is_dict(hints)

    def test_make_error_signature(self):
        sig = inspect.signature(make_error)
        assert "message" in sig.parameters
        hints = get_type_hints(make_error)
        assert _return_is_dict(hints)

    def test_utc_timestamp_signature(self):
        sig = inspect.signature(utc_timestamp)
        hints = get_type_hints(utc_timestamp)
        assert hints.get("return") is str or hints.get("return") is None


class TestWsMessageInterface:
    """Verify the WsMessage envelope class."""

    def test_class_exists(self):
        assert WsMessage.__module__ == "src.schemas"

    def test_constructor_signature(self):
        sig = inspect.signature(WsMessage.__init__)
        assert "msg_type" in sig.parameters
        assert "payload" in sig.parameters

    def test_to_dict_method(self):
        assert callable(WsMessage.to_dict)
        hints = get_type_hints(WsMessage.to_dict)
        assert _return_is_dict(hints)

    def test_ws_message_can_be_created(self):
        msg = WsMessage("hello", {"state": {}})
        assert msg.msg_type == "hello"
        assert msg.payload == {"state": {}}


# ---------------------------------------------------------------------------
# Behavioral tests — verify factories produce correct structures
# ---------------------------------------------------------------------------


class TestMessageFactoryBehavior:
    """Verify every factory produces correct message structures."""

    def test_make_hello(self):
        result = make_hello({"connected": True}, [{"op": "test"}])
        assert result["type"] == "hello"
        assert result["state"]["connected"] is True
        assert result["recent_log"] == [{"op": "test"}]
        assert "timestamp" in result

    def test_make_state_update(self):
        result = make_state_update({"connected": True}, [])
        assert result["type"] == "state_update"
        assert result["state"]["connected"] is True
        assert "timestamp" in result

    def test_make_console_log(self):
        result = make_console_log("info", "page loaded")
        assert result["type"] == "console_log"
        assert result["level"] == "info"
        assert result["message"] == "page loaded"
        assert "timestamp" in result

    def test_make_console_log_with_timestamp(self):
        result = make_console_log("warn", "timeout", timestamp="2026-01-01T00:00:00")
        assert result["timestamp"] == "2026-01-01T00:00:00"

    def test_make_navigation(self):
        result = make_navigation("https://example.com", "frame-1")
        assert result["type"] == "navigation"
        assert result["url"] == "https://example.com"
        assert result["frame_id"] == "frame-1"
        assert "timestamp" in result

    def test_make_operation(self):
        result = make_operation("navigate", "success", 150.5, "OK")
        assert result["type"] == "operation"
        assert result["operation"] == "navigate"
        assert result["status"] == "success"
        assert result["duration_ms"] == 150.5
        assert result["details"] == "OK"
        assert "timestamp" in result

    def test_make_ping(self):
        result = make_ping()
        assert result["type"] == "ping"
        assert "timestamp" in result

    def test_make_pong(self):
        result = make_pong()
        assert result["type"] == "pong"
        assert "timestamp" in result

    def test_make_error(self):
        result = make_error("something went wrong")
        assert result["type"] == "error"
        assert result["message"] == "something went wrong"
        assert "timestamp" in result

    def test_make_error_with_code(self):
        result = make_error("not found", code="ERR_404")
        assert result["code"] == "ERR_404"

    def test_utc_timestamp(self):
        ts = utc_timestamp()
        assert isinstance(ts, str)
        assert "T" in ts  # ISO-8601 format
        assert ts.endswith("+00:00") or ts.endswith("Z")

    def test_ws_message_to_dict(self):
        msg = WsMessage("hello", {"state": {}})
        d = msg.to_dict()
        assert d["type"] == "hello"
        assert "timestamp" in d
        assert d["state"] == {}
