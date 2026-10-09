"""MCPServer — FastMCP lifecycle + tool registration (spec §6).

Owns: lazy FastMCP creation, ``register_tools()`` loop over the ToolDefRegistry,
``run(transport)`` dispatching to the real SDK runners (spec §6.1).
"""

from __future__ import annotations

import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import MCPSettings, MCPTransport, load_mcp_settings
from .registry import build_tool_defs


def project_version() -> str:
    """Project version from the repo's pyproject.toml (single source of truth).

    ``serverInfo.version`` used to report the MCP SDK's own version (1.29.0);
    the installed ``browser-helper`` metadata is stale in editable installs, so
    the pyproject file is read directly. Returns ``"unknown"`` if it is absent.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "unknown"


class MCPServer:
    """FastMCP server wrapper (spec §6.1)."""

    def __init__(self, settings: MCPSettings | None = None) -> None:
        self.settings = settings or load_mcp_settings()
        self._mcp: FastMCP | None = None

    @property
    def mcp(self) -> FastMCP:
        """Memoized FastMCP builder — constructs once, registers all tools."""
        if self._mcp is None:
            self._mcp = FastMCP(
                name=self.settings.server_name,
                instructions=self._build_instructions(),
                host=self.settings.host,
                port=self.settings.port,
                log_level="INFO",
            )
            # FastMCP has no version kwarg; serverInfo.version comes from the
            # low-level Server, which reads ``version`` at initialize time.
            self._mcp._mcp_server.version = project_version()
            self.register_tools(self._mcp)
        return self._mcp

    def register_tools(self, mcp: FastMCP) -> None:
        """Register every ToolDef in the capability-derived registry."""
        for tool in build_tool_defs():
            mcp.add_tool(
                tool.handler,
                name=tool.name,
                description=tool.description,
            )

    def _build_instructions(self) -> str:
        """Build the server instructions from CapabilityRegistry (spec §4.6)."""
        from capability_registry import CapabilityRegistry, CapabilityStatus

        registry = CapabilityRegistry.default()
        ready = [c.id for c in registry.capabilities if c.status is CapabilityStatus.READY]
        experimental = [
            c.id
            for c in registry.capabilities
            if c.status is CapabilityStatus.EXPERIMENTAL
        ]
        tools = [t.name for t in build_tool_defs()]
        return (
            "Browser Helper MCP server. Backed by the browser-helper engine; "
            "tool availability follows the capability registry "
            f"(READY: {', '.join(ready) or 'none'}; EXPERIMENTAL: "
            f"{', '.join(experimental) or 'none'}). "
            f"Tools: {', '.join(tools)}."
        )

    async def run(self, transport: MCPTransport | str | None = None) -> None:
        """Run the server on the selected transport (spec §6.2)."""
        value = self.settings.transport if transport is None else transport
        chosen = value.value if isinstance(value, MCPTransport) else value
        if chosen not in {item.value for item in MCPTransport}:
            raise ValueError(f"invalid transport: {chosen!r}")
        t = MCPTransport(chosen)
        if t is MCPTransport.STDIO:
            await self.mcp.run_stdio_async()
        elif t is MCPTransport.SSE:
            await self.mcp.run_sse_async()
        else:
            await self.mcp.run_streamable_http_async()


def create_mcp_server(settings: MCPSettings | None = None) -> MCPServer:
    """Expose a module-level factory (spec §6.3)."""
    return MCPServer(settings=settings)
