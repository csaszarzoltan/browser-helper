"""MCP memory tool handlers — pre-dev stub.

Each handler follows the existing tool pattern: async def, Context | None param, str return.
Raises NotImplementedError so the developer knows which methods to implement.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context


async def memory_remember(
    key: str,
    content: str,
    metadata: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Remember a fact: key=identifier, content=text, metadata=JSON (optional).

    Upserts by key — if key exists, the entry is updated.
    Capability: memory.persistent, READY.
    """
    raise NotImplementedError


async def memory_recall(
    query: str,
    limit: int = 10,
    ctx: Context | None = None,
) -> str:
    """Recall memories by keyword search with relevance ranking.

    Returns JSON list of matching entries ordered by relevance.
    """
    raise NotImplementedError


async def memory_forget(
    key_or_id: str,
    ctx: Context | None = None,
) -> str:
    """Forget a memory entry by key or id.

    Returns JSON status with removed=True/False.
    """
    raise NotImplementedError


async def memory_list(
    filter: str | None = None,
    ctx: Context | None = None,
) -> str:
    """List all stored memories, optionally filtered.

    Returns JSON list of all entries.
    """
    raise NotImplementedError
