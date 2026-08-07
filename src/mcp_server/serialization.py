"""Serialization helpers — envelope normalization (spec §5.10).

Owns: ``json_dumps()``, ``tool_result()``, ``tool_error()`` — REST envelope
shapes serialized to JSON strings. Handlers never raise into FastMCP; they
normalize to the ``status``/``error`` vocabulary so MCP clients see the same
contract as the REST API.
"""

from __future__ import annotations

import json
from typing import Any


def json_dumps(payload: Any) -> str:
    """Serialize a payload to a JSON string (``ensure_ascii=False``)."""
    return json.dumps(payload, ensure_ascii=False)


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
