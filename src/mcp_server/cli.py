"""MCP server CLI (spec §7.2).

``main(argv=None) -> int``: argparse for ``--transport`` / ``--host`` /
``--port`` / ``--enabled``, startup banner, ``asyncio.run``.
Also directly runnable as ``python -m mcp_server.cli``.
"""

from __future__ import annotations

import argparse
import asyncio


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args and run the MCP server.

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

    from .config import load_mcp_settings
    from .registry import build_tool_defs
    from .server import MCPServer

    settings = load_mcp_settings(overrides=overrides)
    tool_count = len(list(build_tool_defs()))
    print(
        f"Browser Helper MCP server — transport={settings.transport} "
        f"tools={tool_count} host={settings.host} port={settings.port}",
        flush=True,
    )
    asyncio.run(MCPServer(settings=settings).run(settings.transport))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
