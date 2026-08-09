"""MemoryStore — SQLite persistent store with FTS5 search — pre-dev stub.

All methods raise NotImplementedError so the developer knows exactly what
to implement. This module is the SOURCE OF TRUTH for the public API contract
that tests/test_memory.py validates against.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class MemoryStore:
    """Persistent SQLite memory store with FTS5 keyword search.

    Default DB location: ~/.browser-helper/memory.db
    WAL mode for concurrent access.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(Path(db_path).expanduser()) if db_path is not None else str(
            Path.home() / ".browser-helper" / "memory.db"
        )

    async def open(self) -> None:
        """Open the database connection and create tables if needed."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the database connection."""
        raise NotImplementedError

    async def remember(
        self,
        key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        source_session: str = "",
    ) -> dict[str, Any]:
        """Store a memory entry. Upserts by key (updates if key exists).

        Returns a dict with: id, key, content, metadata, created_at, updated_at, source_session.
        """
        raise NotImplementedError

    async def recall(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories by keyword (FTS5) with recency tie-breaking.

        Returns a list of dicts ordered by relevance: keyword match ranks above
        non-match; among equal matches, newer entries rank higher.
        Each dict has: id, key, content, metadata, created_at, updated_at, source_session.
        """
        raise NotImplementedError

    async def forget(self, key_or_id: str) -> bool:
        """Remove a memory by key or id. Idempotent — returns True if anything was removed."""
        raise NotImplementedError

    async def list_entries(
        self,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all memories, optionally filtered by metadata prefix/pattern.

        Returns all entries if filter_expr is None.
        Each dict has: id, key, content, metadata, created_at, updated_at, source_session.
        """
        raise NotImplementedError
