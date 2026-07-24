"""Structured event types and state schema for WebSocket messages."""

from datetime import UTC, datetime
from typing import Any


class WsMessage:
    """Base WebSocket message envelope."""

    def __init__(self, msg_type: str, payload: dict[str, Any]) -> None:
        self.msg_type = msg_type
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.msg_type, "timestamp": utc_timestamp(), **self.payload}


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def make_hello(state: dict[str, Any], recent_log: list[dict]) -> dict[str, Any]:
    return {"type": "hello", "timestamp": utc_timestamp(), "state": state, "recent_log": recent_log}


def make_state_update(state: dict[str, Any], recent_log: list[dict]) -> dict[str, Any]:
    return {"type": "state_update", "timestamp": utc_timestamp(), "state": state, "recent_log": recent_log}


def make_console_log(level: str, message: str, timestamp: str | None = None) -> dict[str, Any]:
    return {"type": "console_log", "timestamp": timestamp or utc_timestamp(), "level": level, "message": message}


def make_navigation(url: str, frame_id: str, timestamp: str | None = None) -> dict[str, Any]:
    return {"type": "navigation", "timestamp": timestamp or utc_timestamp(), "url": url, "frame_id": frame_id}


def make_operation(operation: str, status: str, duration_ms: float, details: str = "") -> dict[str, Any]:
    return {"type": "operation", "timestamp": utc_timestamp(), "operation": operation, "status": status, "duration_ms": duration_ms, "details": details}


def make_ping() -> dict[str, Any]:
    return {"type": "ping", "timestamp": utc_timestamp()}


def make_pong() -> dict[str, Any]:
    return {"type": "pong", "timestamp": utc_timestamp()}


def make_error(message: str, code: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"type": "error", "timestamp": utc_timestamp(), "message": message}
    if code is not None:
        d["code"] = code
    return d


# ---------------------------------------------------------------------------
# Timestamp utility
# ---------------------------------------------------------------------------


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()
