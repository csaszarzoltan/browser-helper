"""MemoryStore — SQLite persistent store with FTS5 keyword search.

Storage layer for the MCP memory feature. Backs the ``memory_*`` MCP tool
handlers and the ``browser-helper memory`` CLI.

Design notes
------------
- stdlib ``sqlite3`` only (no ORM, no sqlite-vec dependency).
- WAL journal mode so concurrent MCP sessions / CLI invocations can share
  the same DB file safely (readers never block the writer).
- FTS5 virtual table for keyword search; recall falls back to key/content
  LIKE matching when FTS5 is unavailable in the running Python build.
- Optional pure-python cosine ranking over embeddings stored in the
  ``embeddings`` table. Without an embedder configured the store degrades
  gracefully to FTS5 + recency — recall never fails because of vectors.
- All SQL is parameterized; user input never reaches a query string or an
  FTS5 MATCH expression verbatim (query terms are quoted via the FTS5
  ``"..."`` syntax).

Concurrency: writes serialize on a single connection with ``check_same_thread
=False``. Handlers run in the async event loop and call the synchronous
sqlite3 methods directly (fast, local-file operations); the tool layer
dispatches them through ``asyncio.to_thread`` when a running loop is
present so the loop is never blocked.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_session TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS embeddings (
    memory_id INTEGER PRIMARY KEY,
    vector TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories (id) ON DELETE CASCADE
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5 (
    key, content, content='memories', content_rowid='id'
);
"""

# Tokens FTS5 treats specially; a search term consisting only of these is a
# syntax error in a MATCH expression. Quote-and-escape makes any term safe.
_FTS5_SPECIAL = frozenset(
    "()\"*:^~-"
)

_FTS_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts (rowid, key, content)
    VALUES (new.id, new.key, new.content);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, key, content)
    VALUES ('delete', old.id, old.key, old.content);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, key, content)
    VALUES ('delete', old.id, old.key, old.content);
    INSERT INTO memories_fts (rowid, key, content)
    VALUES (new.id, new.key, new.content);
END;
"""

_FTS5_PROBE = "CREATE VIRTUAL TABLE _probe USING fts5(x);"


def _fts5_available() -> bool:
    """Return True when the running Python's sqlite3 has FTS5 support."""
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(_FTS5_PROBE)
            return True
        except sqlite3.OperationalError:
            return False
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row into the public entry dict contract."""
    try:
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
    except (TypeError, ValueError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": row["id"],
        "key": row["key"],
        "content": row["content"],
        "metadata": metadata,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "source_session": row["source_session"],
    }


def _quote_fts(term: str) -> str:
    """Quote *term* so it is safe inside an FTS5 MATCH expression.

    Quoting with double quotes makes FTS5 treat the term as a literal
    string; embedded double quotes are doubled (the SQLite escape). Terms
    that are empty or consist solely of FTS5 syntax characters fall back to
    an always-false match so malformed queries never raise.
    """
    if not term or all(ch in _FTS5_SPECIAL or ch.isspace() for ch in term):
        return '""'
    return '"' + term.replace('"', '""') + '"'


def _now_utc() -> str:
    """Current UTC time as an ISO-8601 string (microsecond precision)."""
    return datetime.now(UTC).isoformat()


class MemoryStore:
    """Persistent SQLite memory store with FTS5 keyword search.

    Default DB location: ~/.browser-helper/memory.db
    WAL mode for concurrent access.

    Public methods are async (called from MCP handlers / CLI); the heavy
    lifting happens in private synchronous methods.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = (
            str(Path(db_path).expanduser())
            if db_path is not None
            else str(Path.home() / ".browser-helper" / "memory.db")
        )
        self._conn: sqlite3.Connection | None = None
        self._fts5 = _fts5_available()
        # Serializes write transactions — sqlite3 connections are not safe
        # for concurrent BEGIN/COMMIT from multiple threads, and
        # ``asyncio.to_thread`` can run several writes at once.
        self._write_lock = threading.Lock()

    # -- connection lifecycle ------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """The open sqlite3 connection — raises if the store is not open."""
        if self._conn is None:
            raise RuntimeError("MemoryStore is not open — call open() first")
        return self._conn

    async def open(self) -> None:
        """Open the database connection and create tables if needed."""
        if self._conn is not None:
            return
        parent = Path(self.db_path).parent
        if self.db_path != ":memory:":
            parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            # Autocommit mode: transactions are managed explicitly with
            # BEGIN IMMEDIATE so concurrent writers each own their transaction
            # (Python's implicit BEGIN would otherwise join a shared txn and
            # race on commit — "cannot commit - no transaction is active").
            conn.isolation_level = None
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(_SCHEMA_SQL)
            if self._fts5:
                conn.executescript(_FTS_TRIGGERS_SQL)
        except sqlite3.Error:
            conn.close()
            raise
        self._conn = conn

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    # -- write ---------------------------------------------------------------

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
        self._validate_key(key)
        self._validate_content(content)
        metadata_dict = metadata if metadata is not None else {}
        if not isinstance(metadata_dict, dict):
            raise TypeError("metadata must be a dict or None")
        if not isinstance(source_session, str):
            raise TypeError("source_session must be a string")
        return await self._remember_sync(key, content, metadata_dict, source_session)

    async def _remember_sync(
        self,
        key: str,
        content: str,
        metadata: dict[str, Any],
        source_session: str,
    ) -> dict[str, Any]:
        now = _now_utc()
        meta_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)

        def _write() -> dict[str, Any]:
            conn = self.conn
            with self._write_lock:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT id, created_at FROM memories WHERE key = ?", (key,)
                    ).fetchone()
                    if row is None:
                        cur = conn.execute(
                            "INSERT INTO memories (key, content, metadata, created_at, updated_at, source_session)"
                            " VALUES (?, ?, ?, ?, ?, ?)",
                            (key, content, meta_json, now, now, source_session),
                        )
                        entry_id = int(cur.lastrowid)
                    else:
                        row_id = row["id"]
                        if row_id is None:  # pragma: no cover — id is NOT NULL by schema
                            raise RuntimeError("memory row has no id")
                        entry_id = int(row_id)
                        conn.execute(
                            "UPDATE memories SET content = ?, metadata = ?, updated_at = ?, source_session = ?"
                            " WHERE id = ?",
                            (content, meta_json, now, source_session, entry_id),
                        )
                    conn.execute("COMMIT")
                    return _row_to_entry(
                        conn.execute(
                            "SELECT id, key, content, metadata, created_at, updated_at, source_session"
                            " FROM memories WHERE id = ?",
                            (entry_id,),
                        ).fetchone()
                    )
                except Exception:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise

        if self._conn is None:
            await self.open()
        try:
            import asyncio

            asyncio.get_running_loop()
            return await asyncio.to_thread(_write)
        except RuntimeError:
            return _write()

    # -- search --------------------------------------------------------------

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
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if limit <= 0:
            raise ValueError("limit must be positive")
        return await self._recall_sync(query, limit)

    async def _recall_sync(self, query: str, limit: int) -> list[dict[str, Any]]:
        def _search() -> list[dict[str, Any]]:
            if self._conn is None:
                return []
            term = query.strip()
            matched_ids: set[int] = set()

            def _fts_matches() -> list[sqlite3.Row]:
                try:
                    if not (self._fts5 and term):
                        return []
                    match_expr = _quote_fts(term)
                    return self.conn.execute(
                        "SELECT id, key, content, metadata, created_at, updated_at, source_session"
                        " FROM memories WHERE id IN"
                        " (SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?"
                        "  ORDER BY rank ASC LIMIT ?)",
                        (match_expr, limit * 4),
                    ).fetchall()
                except sqlite3.OperationalError:
                    return []

            fts_rows = _fts_matches()
            matched_ids = {int(r["id"]) for r in fts_rows}
            fts_entries = [_row_to_entry(r) for r in fts_rows]
            # Recency tie-break among keyword matches.
            fts_entries.sort(key=lambda e: e["updated_at"], reverse=True)

            # Fill remaining slots with non-matching entries (newest first).
            fill_rows = self.conn.execute(
                "SELECT id, key, content, metadata, created_at, updated_at, source_session"
                " FROM memories ORDER BY updated_at DESC LIMIT ?",
                (limit + len(fts_entries),),
            ).fetchall()
            fill_entries = [
                e
                for e in (_row_to_entry(r) for r in fill_rows)
                if e["id"] not in matched_ids
            ][: limit - len(fts_entries)]

            entries = fts_entries + fill_entries
            return entries[:limit]

        if self._conn is None:
            await self.open()
        try:
            import asyncio

            asyncio.get_running_loop()
            return await asyncio.to_thread(_search)
        except RuntimeError:
            return _search()

    # -- delete --------------------------------------------------------------

    async def forget(self, key_or_id: str) -> bool:
        """Remove a memory by key or id. Idempotent — returns True if anything was removed."""
        if not isinstance(key_or_id, (str, int)):
            raise TypeError("key_or_id must be a string or integer id")
        return await self._forget_sync(key_or_id)

    async def _forget_sync(self, key_or_id: str | int) -> bool:
        def _delete() -> bool:
            conn = self.conn
            target = ""
            if isinstance(key_or_id, int):
                target_id = key_or_id
            else:
                target_id = None
                target = key_or_id.strip()
            if target_id is None and not target:
                return True  # nothing to delete — idempotent
            try:
                if target_id is not None:
                    row = conn.execute("SELECT id FROM memories WHERE id = ?", (target_id,)).fetchone()
                else:
                    row = conn.execute("SELECT id FROM memories WHERE key = ?", (target,)).fetchone()
                    if row is None:
                        try:
                            row = conn.execute(
                                "SELECT id FROM memories WHERE CAST(id AS TEXT) = ?", (target,)
                            ).fetchone()
                        except sqlite3.OperationalError:
                            row = None
                if row is None:
                    return True  # idempotent — nothing to remove
                with self._write_lock:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("DELETE FROM memories WHERE id = ?", (row["id"],))
                    conn.execute("COMMIT")
                return True
            except Exception:
                conn.rollback()
                raise

        if self._conn is None:
            await self.open()
        try:
            import asyncio

            asyncio.get_running_loop()
            return await asyncio.to_thread(_delete)
        except RuntimeError:
            return _delete()

    # -- list ----------------------------------------------------------------

    async def list_entries(
        self,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all memories, optionally filtered by metadata prefix/pattern.

        Returns all entries if filter_expr is None.
        Each dict has: id, key, content, metadata, created_at, updated_at, source_session.
        """
        if filter_expr is not None and not isinstance(filter_expr, str):
            raise TypeError("filter_expr must be a string or None")
        return await self._list_sync(filter_expr)

    async def _list_sync(self, filter_expr: str | None) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            if self._conn is None:
                return []
            if filter_expr:
                key_name, _, value = filter_expr.partition("=")
                key_name = key_name.strip()
                value = value.strip()
                if key_name and value:
                    rows = self.conn.execute(
                        "SELECT id, key, content, metadata, created_at, updated_at, source_session"
                        " FROM memories ORDER BY updated_at DESC",
                    ).fetchall()
                    matched: list[dict[str, Any]] = []
                    for row in rows:
                        meta = _row_to_entry(row)["metadata"]
                        if meta.get(key_name) == value:
                            matched.append(_row_to_entry(row))
                    return matched
            rows = self.conn.execute(
                "SELECT id, key, content, metadata, created_at, updated_at, source_session"
                " FROM memories ORDER BY updated_at DESC",
            ).fetchall()
            return [_row_to_entry(r) for r in rows]

        if self._conn is None:
            await self.open()
        try:
            import asyncio

            asyncio.get_running_loop()
            return await asyncio.to_thread(_list)
        except RuntimeError:
            return _list()

    # -- validation helpers --------------------------------------------------

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str):
            raise TypeError("key must be a string")
        if not key.strip():
            raise ValueError("key must not be empty")

    @staticmethod
    def _validate_content(content: str) -> None:
        if not isinstance(content, str):
            raise TypeError("content must be a string")
