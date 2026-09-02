"""Serialization helpers — envelope normalization (spec §5.10).

Owns: ``json_dumps()``, ``tool_result()``, ``tool_error()`` — REST envelope
shapes serialized to JSON strings. Handlers never raise into FastMCP; they
normalize to the ``status``/``error`` vocabulary so MCP clients see the same
contract as the REST API.
"""

from __future__ import annotations

import json
from typing import Any


def _unwrap(payload: Any) -> Any:
    """Normalize a handler result to a JSON-serializable object.

    ``main.run_op``'s error path returns a Starlette ``JSONResponse`` (REST
    parity).  MCP handlers handed that straight to :func:`json_dumps`, which
    raised ``Object of type JSONResponse is not JSON serializable`` and hid
    the real error (observed 2026-09-02: navigate 503 surfaced as a
    serialization crash).  Unwrap ``.body`` back to a dict here so every
    handler stays a thin wrapper.
    """
    if isinstance(payload, (str, bytes, bytearray)) or payload is None or isinstance(
        payload, (bool, int, float, list, tuple, dict)
    ):
        return payload
    body = getattr(payload, "body", None)
    if body is not None:
        try:
            return json.loads(bytes(body))
        except Exception as exc:  # noqa: BLE001 — fall back to generic envelope
            return {"status": "error", "operation": getattr(payload, "operation", "unknown"),
                    "data": None, "error": {"code": "operation_failed", "message": f"{exc}"[:300]},
                    "meta": {}}
    return {"status": "error", "operation": getattr(payload, "operation", "unknown"),
            "data": None, "error": {"code": "operation_failed", "message": str(payload)},
            "meta": {}}


def json_dumps(payload: Any) -> str:
    """Serialize a payload to a JSON string (``ensure_ascii=False``)."""
    return json.dumps(_unwrap(payload), ensure_ascii=False)


def tool_result(operation: str, data: Any, meta: dict[str, Any] | None = None) -> str:
    """Build a success envelope ``{"status": "ok", ...}`` JSON string.

    Mirrors the REST ``api_success`` shape (spec §5.10): ``status``,
    ``operation``, ``data``, ``error``, ``meta``.
    """
    return json_dumps(
        {
            "status": "ok",
            "operation": operation,
            "data": data,
            "error": None,
            "meta": meta or {},
        }
    )


def tool_error(
    operation: str,
    code: str = "mcp_tool_error",
    message: str = "",
) -> str:
    """Build an error envelope ``{"status": "error", ...}`` JSON string.

    Matches the REST ``api_error`` payload shape (spec §5.10) so agents can
    branch on ``error.code`` / ``error.message`` uniformly.
    """
    return json_dumps(
        {
            "status": "error",
            "operation": operation,
            "data": None,
            "error": {"code": code, "message": message, "details": None},
            "meta": {},
        }
    )
