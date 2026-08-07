"""MCP server CLI (spec §7.2).

``main(argv=None) -> int``: argparse for ``--transport`` / ``--host`` /
``--port`` / ``--enabled``, startup banner, ``asyncio.run``.
Also directly runnable as ``python -m mcp_server.cli``.

``mcp()``: Click command with ``--http`` / ``--sse`` / ``--stdio``,
``--host`` / ``--port``, ``--enabled``. Registered as entry points
``bh-mcp`` / ``browser-helper-mcp``.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Literal

import click

from .config import load_mcp_settings
from .registry import build_tool_defs
from .server import MCPServer

TransportMode = Literal["stdio", "sse", "streamable-http"]


def _resolve_transport(
    http: bool,
    sse: bool,
    stdio: bool,
    explicit: str | None,
) -> TransportMode:
    """Resolve transport from flags + explicit --transport (precedence: explicit > http/sse/stdio > default)."""
    if explicit is not None:
        return explicit  # type: ignore[return-value]
    if http:
        return "streamable-http"
    if sse:
        return "sse"
    if stdio:
        return "stdio"
    return "stdio"


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args and run the MCP server (argparse, for ``python -m browser_helper.mcp``).

    ``argparse`` errors exit non-zero before any import of ``mcp`` or ``main``
    (spec §7.2). Returns 0 on clean exit.
    """
    parser = argparse.ArgumentParser(
        prog="python -m browser_helper.mcp",
        description="Browser Helper MCP server",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default=None,
        help="MCP transport: stdio (default), sse, or streamable-http",
    )
    parser.add_argument("--host", default=None, help="bind address (sse/http)")
    parser.add_argument("--port", type=int, default=None, help="bind port (sse/http)")
    parser.add_argument(
        "--enabled", action="store_true", help="explicitly enable the server"
    )
    args = parser.parse_args(argv)

    # Build overrides for load_mcp_settings: argparse's ``None`` defaults must
    # not override settings/env values (CLI > env > settings.json precedence).
    overrides: dict[str, object] = {}
    if args.transport is not None:
        overrides["transport"] = args.transport
    if args.host is not None:
        overrides["host"] = args.host
    if args.port is not None:
        overrides["port"] = args.port
    if args.enabled:
        overrides["enabled"] = True

    settings = load_mcp_settings(overrides=overrides)
    tool_count = len(list(build_tool_defs()))
    print(
        f"Browser Helper MCP server — transport={settings.transport} "
        f"tools={tool_count} host={settings.host} port={settings.port}",
        flush=True,
    )
    asyncio.run(MCPServer(settings=settings).run(settings.transport))
    return 0


# ──────────────────────────────────────────────────────────────
# Click command (entry points: bh-mcp, browser-helper-mcp)
# ──────────────────────────────────────────────────────────────

@click.command(name="mcp", help="Start the Browser Helper MCP server")
@click.option(
    "--http/--no-http",
    default=False,
    help="Run with streamable-http transport (default: stdio)",
)
@click.option(
    "--sse/--no-sse",
    default=False,
    help="Run with SSE transport",
)
@click.option(
    "--stdio/--no-stdio",
    default=False,
    help="Run with stdio transport (default)",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default=None,
    help="Explicit transport (overrides --http/--sse/--stdio)",
)
@click.option("--host", default=None, help="Bind address for HTTP/SSE")
@click.option("--port", type=int, default=None, help="Bind port for HTTP/SSE")
@click.option("--enabled/--no-enabled", default=False, help="Enable the server")
def mcp(
    http: bool,
    sse: bool,
    stdio: bool,
    transport: str | None,
    host: str | None,
    port: int | None,
    enabled: bool,
) -> None:
    """Click entry point for MCP server (registered as bh-mcp / browser-helper-mcp)."""
    t = _resolve_transport(http, sse, stdio, transport)
    overrides: dict[str, object] = {"transport": t}
    if host is not None:
        overrides["host"] = host
    if port is not None:
        overrides["port"] = port
    if enabled:
        overrides["enabled"] = True

    settings = load_mcp_settings(overrides=overrides)
    tool_count = len(list(build_tool_defs()))
    click.echo(
        f"Browser Helper MCP server — transport={settings.transport} "
        f"tools={tool_count} host={settings.host} port={settings.port}",
        err=True,
    )
    asyncio.run(MCPServer(settings=settings).run(settings.transport))


# Export Click app for entry points
app = click.Group()
app.add_command(mcp)


if __name__ == "__main__":
    # Allow ``python -m mcp_server.cli`` to work with Click too
    app()
