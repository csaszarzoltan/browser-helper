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


def _as_tool_result(handler):
    """Wrap a handler so an error envelope becomes a tool error (isError true).

    The wrapper keeps the handler's signature (functools.wraps), so FastMCP still
    injects the Context argument. Success envelopes and non-JSON text pass through.
    """
    import functools
    import json

    from mcp.server.fastmcp.exceptions import ToolError

    @functools.wraps(handler)
    async def wrapper(*args, **kwargs):
        out = await handler(*args, **kwargs)
        if isinstance(out, str):
            try:
                env = json.loads(out)
            except ValueError:
                return out
            if isinstance(env, dict) and env.get("status") == "error":
                raise ToolError(out)
        return out

    return wrapper


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
        """Register every ToolDef in the capability-derived registry.

        Two things the agent depends on are set here:
        - the registry's input schema (enums, defaults, descriptions) replaces the one
          generated from the handler signature, so the agent sees the hints;
        - a failed call (an envelope with status "error") is raised as a tool error,
          so the MCP ``isError`` flag is set. The envelope text is kept as the message.
        """
        for tool in build_tool_defs():
            mcp.add_tool(
                _as_tool_result(tool.handler),
                name=tool.name,
                description=tool.description,
            )
            registered = mcp._tool_manager.get_tool(tool.name)
            if registered is not None and tool.parameters:
                registered.parameters = tool.parameters

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
            await self._run_streamable_http()

    async def _run_streamable_http(self) -> None:
        """Serve the streamable-http transport behind a bearer-token check.

        ``BH_MCP_TOKEN`` is required for any non-loopback bind, so a remote agent
        can reach the server through a tunnel or the network only with the token.
        """
        import os

        import uvicorn

        token = os.environ.get("BH_MCP_TOKEN", "").strip()
        host = self.settings.host
        if host not in {"127.0.0.1", "localhost", "::1"} and not token:
            raise ValueError(
                f"refusing to serve MCP on {host!r} without BH_MCP_TOKEN; "
                "set a token or bind to 127.0.0.1"
            )
        app = self.mcp.streamable_http_app()
        if token:
            app = bearer_token_app(app, token)

        config = uvicorn.Config(app, host=host, port=self.settings.port, log_level="info")
        await uvicorn.Server(config).serve()


def create_mcp_server(settings: MCPSettings | None = None) -> MCPServer:
    """Expose a module-level factory (spec §6.3)."""
    return MCPServer(settings=settings)


def bearer_token_app(app, token: str):
    """Wrap an ASGI app so every HTTP request must carry ``Authorization: Bearer <token>``.

    Lifespan and other non-HTTP scopes pass through, so the MCP session manager still starts.
    """
    import hmac

    expected = token.encode()

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"").decode("latin-1")
            supplied = auth[len("Bearer "):].encode() if auth.startswith("Bearer ") else b""
            if not hmac.compare_digest(supplied, expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body",
                            "body": b'{"detail":"Invalid or missing MCP token"}'})
                return
        await app(scope, receive, send)

    return guarded
