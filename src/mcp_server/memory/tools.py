"""MCP memory tool handlers — persistent agent memory.

Each handler follows the existing tool pattern: async def, Context | None
param, str return (JSON envelope built by ``mcp_server.serialization``).

Envelope contract (mirrors ``tools.py`` / ``serialization.py``)::

    {"status": "ok", "operation": ..., "data": ..., "error": None, "meta": {...}}
    {"status": "error", "operation": ..., "data": None, "error": {"code", "message", "details"}, "meta": {}}

Store lifecycle: handlers lazily open a module-level :class:`MemoryStore`
bound to the configured store path (``load_memory_settings``) and reuse it
for the process lifetime. Validation errors and store failures are
normalized to error envelopes — handlers never raise into FastMCP.

Concurrency note (for the tech-lead): the sqlite3 calls are synchronous and
run on the event loop thread. They are short local-file operations with a
5s busy timeout, and the store methods are also safe to call from
``asyncio.to_thread``; a future refactor could move them off-loop with
``to_thread`` without changing the public contract.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context

from ..serialization import tool_error, tool_result
from .config import load_memory_settings
from .store import MemoryStore

#: Process-scoped store — opened lazily on first tool call, reused after.
_STORE: MemoryStore | None = None
#: Path the process-scoped store was opened on — the singleton is keyed by
#: store path so a caller that points the tools at a different DB (e.g. an
#: env override in tests) gets a store bound to that path, not a stale one.
_STORE_PATH: str | None = None


async def _log(ctx: Context | None, message: str) -> None:
    """Log a progress message through the MCP Context if one is available."""
    if ctx is not None:
        await ctx.info(message)


async def _get_store() -> MemoryStore:
    """Return the process-scoped MemoryStore, opening it on first use.

    The store is bound to ``load_memory_settings().store_path`` (which
    honours the ``BROWSER_HELPER_MEMORY_DB`` env override -- CLI > env >
    settings > default precedence). If the configured path changes between
    calls (e.g. an env override set after first use), a fresh store is
    opened for the new path; the old one is left to the process.

    On corrupt/unopenable databases, raises sqlite3.DatabaseError with a
    clear message. Handlers catch this and return a clean error envelope.
    """
    global _STORE, _STORE_PATH
    path = load_memory_settings().store_path
    if _STORE is None or _STORE_PATH != path:
        store = MemoryStore(db_path=path)
        await store.open()  # raises sqlite3.DatabaseError on corrupt file
        _STORE = store
        _STORE_PATH = path
    return _STORE


def _error(operation: str, code: str, message: str) -> str:
    return tool_error(operation, code, message)


def _parse_metadata(raw: str | None) -> dict[str, Any] | None:
    """Parse the optional JSON metadata string into a dict.

    Returns None when *raw* is falsy; raises ValueError on invalid JSON or
    a non-dict payload (the caller turns it into an error envelope).
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metadata must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TypeError("metadata must be a JSON object")
    return parsed


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
    if ctx is not None:
        await _log(ctx, f"memory_remember key={key!r} content_len={len(content or '')}")
    if not isinstance(key, str) or not key.strip():
        return _error("memory_remember", "invalid_params", "key must be a non-empty string")
    if not isinstance(content, str) or not content.strip():
        return _error("memory_remember", "invalid_params", "content must be a non-empty string")
    try:
        meta = _parse_metadata(metadata)
    except ValueError as exc:
        return _error("memory_remember", "invalid_params", str(exc))
    try:
        store = await _get_store()
        entry = await store.remember(key=key, content=content, metadata=meta, source_session="")
        return tool_result("memory_remember", entry)
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return _error("memory_remember", "operation_failed", str(exc))


async def memory_recall(
    query: str,
    limit: int = 10,
    ctx: Context | None = None,
) -> str:
    """Recall memories by keyword search with relevance ranking.

    Returns JSON list of matching entries ordered by relevance.
    Capability: memory.persistent, READY.
    """
    if ctx is not None:
        await _log(ctx, f"memory_recall query={query!r} limit={limit}")
    if not isinstance(query, str) or not query.strip():
        return _error("memory_recall", "invalid_params", "query must be a non-empty string")
    if not isinstance(limit, int):
        return _error("memory_recall", "invalid_params", "limit must be an integer")
    if limit <= 0:
        return _error("memory_recall", "invalid_params", "limit must be positive")
    try:
        store = await _get_store()
        entries = await store.recall(query=query, limit=limit)
        return tool_result(
            "memory_recall",
            {"results": entries, "count": len(entries)},
        )
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return _error("memory_recall", "operation_failed", str(exc))


async def memory_forget(
    key_or_id: str,
    ctx: Context | None = None,
) -> str:
    """Forget a memory entry by key or id.

    Returns JSON status with removed=True/False.
    Capability: memory.persistent, READY.
    """
    if ctx is not None:
        await _log(ctx, f"memory_forget key_or_id={key_or_id!r}")
    if not isinstance(key_or_id, str) or not key_or_id.strip():
        return _error("memory_forget", "invalid_params", "key_or_id must be a non-empty string")
    try:
        store = await _get_store()
        removed = await store.forget(key_or_id)
        return tool_result("memory_forget", {"removed": removed})
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return _error("memory_forget", "operation_failed", str(exc))


async def memory_list(
    filter: str | None = None,
    ctx: Context | None = None,
) -> str:
    """List all stored memories, optionally filtered.

    Returns JSON list of all entries.
    Capability: memory.persistent, READY.
    """
    if ctx is not None:
        await _log(ctx, f"memory_list filter={filter!r}")
    if filter is not None and not isinstance(filter, str):
        return _error("memory_list", "invalid_params", "filter must be a string or None")
    try:
        store = await _get_store()
        entries = await store.list_entries(filter_expr=filter)
        return tool_result(
            "memory_list",
            {"entries": entries, "count": len(entries)},
        )
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return _error("memory_list", "operation_failed", str(exc))
