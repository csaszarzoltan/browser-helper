"""MCP server configuration (pre-dev stub).

Owns: ``MCPTransport`` enum, ``MCPSettings`` dataclass, ``load_mcp_settings()``
(spec §2.1 / §3.2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class MCPTransport(Enum):
    """Valid FastMCP transports (spec D5 — ``http`` is not one of them)."""

    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


@dataclass
class MCPSettings:
    """MCP server settings (spec §3.2)."""

    transport: str = "stdio"
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    server_name: str = "browser-helper"
    instructions: str = ""


def load_mcp_settings(overrides: dict[str, Any] | None = None) -> MCPSettings:
    """Load MCP settings from SettingsManager + env + CLI overrides.

    Precedence: CLI > env > settings.json > defaults (spec §3.2).

    Pure configuration lookup — no engine, no SDK — so the interface contract
    (``MCPServer()`` construction, ``create_mcp_server()`` factory) holds in the
    RED phase. Reading a settings key lazily never mutates persistence.
    """
    from settings_manager import SettingsManager

    sm = SettingsManager()

    def _pick(name: str, default: Any, cast: Callable[[Any], Any]) -> Any:
        v = overrides.get(name) if overrides else None
        if v is None:
            v = {"enabled": "MCP_ENABLED", "port": "MCP_PORT"}.get(name, None)
            if v is not None and v in __import__("os").environ:
                v = __import__("os").environ[v]
            else:
                v = sm.get(name, default)
        return cast(v)

    return MCPSettings(
        transport=str(_pick("transport", "stdio", str)),
        enabled=bool(_pick("enabled", False, lambda x: str(x).lower() in ("1", "true", "yes"))),
        host=str(_pick("host", "127.0.0.1", str)),
        port=int(_pick("port", 8765, lambda x: int(str(x).strip()))),
        server_name=str(_pick("server_name", "browser-helper", str)),
        instructions=_pick("instructions", "", str) or "",
    )
