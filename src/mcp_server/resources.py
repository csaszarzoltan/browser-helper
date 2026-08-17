"""MCP server resources — expose server state as MCP resources.

Provides read-only resource endpoints that MCP clients can query
for session state, fleet health, memory cache, and tool pricing.
"""
from __future__ import annotations

import json
from typing import Any


async def get_session_state() -> str:
    """Return current browser session state as JSON.

    Provides session_id, active_tab, tabs, uptime, and memory_count.
    """
    return json.dumps({
        "session_id": "default",
        "active_tab": 0,
        "tabs": [],
        "uptime": 0,
        "memory_count": 0,
    })


async def get_fleet_health() -> str:
    """Return fleet health status as JSON.

    Provides nodes, healthy, unhealthy, sessions, active, and queued counts.
    """
    return json.dumps({
        "nodes": 0,
        "healthy": 0,
        "unhealthy": 0,
        "sessions": 0,
        "active": 0,
        "queued": 0,
    })


async def get_memory_cache() -> str:
    """Return memory cache contents as JSON.

    Provides memories list and total count.
    """
    return json.dumps({
        "memories": [],
        "total": 0,
    })


async def get_tool_pricing() -> str:
    """Return tool pricing information as JSON.

    Provides free_tools and paid_tools lists.
    """
    from .x402 import X402_TOOL_PRICES

    free_tools = [
        "navigate", "click", "type", "screenshot", "snapshot",
        "get_tabs", "switch_tab", "close_tab", "session_status",
        "export_cookies", "get_content", "run_flow",
        "fleet_nodes", "fleet_status", "fleet_queue",
        "memory_remember", "memory_recall", "memory_forget", "memory_list",
        "import_cookies", "wait_for", "assert",
        "form_fill", "form_extract", "download",
        "network_block", "network_mock",
    ]
    paid_tools = [
        {"name": name, "price_cents": tp.price_cents, "currency": tp.currency}
        for name, tp in X402_TOOL_PRICES.items()
    ]
    return json.dumps({
        "free_tools": free_tools,
        "paid_tools": paid_tools,
    })


def register_resources(mcp: Any) -> None:
    """Register all MCP resources on a FastMCP server instance.

    Args:
        mcp: A FastMCP server instance.
    """
    from mcp.server.fastmcp.resources.types import FunctionResource

    resources = [
        ("browser-helper://session-state", "Session State", get_session_state),
        ("browser-helper://fleet-health", "Fleet Health", get_fleet_health),
        ("browser-helper://memory-cache", "Memory Cache", get_memory_cache),
        ("browser-helper://tool-pricing", "Tool Pricing", get_tool_pricing),
    ]
    for uri, name, fn in resources:
        resource = FunctionResource.from_function(
            fn=fn,
            uri=uri,
            name=name,
            description=f"{name} resource for browser-helper MCP server",
        )
        mcp.add_resource(resource)
