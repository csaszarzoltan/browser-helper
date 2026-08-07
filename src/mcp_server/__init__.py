"""MCP server package — FastMCP front for the browser-helper engine.

Implements the MCP (Model Context Protocol) server that fronts the
browser-helper engine per ``docs/architecture/mcp-server-design.md``: a
capability-derived tool registry, direct in-process engine bindings
(never HTTP, never an LLM), and stdio / sse / streamable-http transports.

Contract (spec §2 / §8):
- ``create_mcp_server(settings=None) -> MCPServer`` — module factory.
- ``MCPServer`` — lazy FastMCP lifecycle + tool registration.
- ``__version__`` — package version string.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .server import MCPServer, create_mcp_server

__all__ = ["MCPServer", "__version__", "create_mcp_server"]
