"""SQLite persistence layer for the fleet orchestration module.

``FleetSQLite`` is the single owner of the ``fleet.db`` connection: the
nodes, sessions, and queue tables described in
``analysis/architecture-brief.md`` §4.  The connection runs in WAL mode
with foreign keys enabled and a 5s busy timeout; every compound write is
serialised through an internal :class:`asyncio.Lock` so concurrent async
components (health checker, session pool, queue manager, failover manager,
API) cannot interleave multi-statement transactions.

Schema notes
------------
* Timestamps are stored as ``REAL`` epoch floats (matching
  ``ProxyEntry.last_checked`` in ``src/proxy_manager.py``).
* JSON columns (``capabilities``, ``metadata``, ``saved_state``) are stored
  as ``TEXT`` and round-tripped with ``json.loads`` / ``json.dumps`` — no
  new dependency.
* One deliberate addition over the brief's schema: ``fleet_nodes`` carries a
  ``deregistered`` flag instead of a hard delete for unregister.  The API
  contract (``tests/test_fleet_v115.py::TestNodeRegistry``) requires an
  unregistered node to disappear from ``GET /fleet/nodes``; the flag lets
  the row be preserved (audit history) while live listings filter it out,
  and a partial unique index on ``url`` allows the same worker to
  re-register later.

Usage
-----
All mutating methods are ``async`` (they take the writer lock); read
methods are ``async`` too for a uniform call surface.  Callers that need a
plain blocking handle can use :meth:`FleetSQLite.close` at shutdown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("browser-helper.fleet.storage")

#: Session statuses that consume node capacity (drive active_sessions).
_ACTIVE_SESSION_STATUSES = ("active", "allocated", "idle")

#: Column whitelist for FleetSQLite.update_session — guards the dynamic UPDATE.
_ALLOWED_SESSION_FIELDS = frozenset(
    {
        "node_id",
        "node_url",
        "cdp_url",
        "status",
        "queued",
        "queue_position",
        "allocated_at",
        "last_used",
        "expires_at",
        "saved_state",
    }
)

#: DDL — fleet_nodes / fleet_sessions / fleet_queue + scheduling indexes.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS fleet_nodes (
    node_id           TEXT PRIMARY KEY,
    url               TEXT NOT NULL,
    capabilities      TEXT NOT NULL DEFAULT '[]',
    capacity          INTEGER NOT NULL DEFAULT 5,
    active_sessions   INTEGER NOT NULL DEFAULT 0,
    healthy           INTEGER NOT NULL DEFAULT 1,
    last_checked      REAL NOT NULL DEFAULT 0,
    last_error        TEXT,
    metadata          TEXT,
    registered_at     REAL NOT NULL,
    updated_at        REAL NOT NULL,
    deregistered      INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_fleet_nodes_url_live
    ON fleet_nodes(url) WHERE deregistered = 0;

CREATE TABLE IF NOT EXISTS fleet_sessions (
    session_id        TEXT PRIMARY KEY,
    node_id           TEXT NOT NULL,
    node_url          TEXT NOT NULL,
    cdp_url           TEXT,
    status            TEXT NOT NULL DEFAULT 'active',
    queued            INTEGER NOT NULL DEFAULT 0,
    queue_position    INTEGER NOT NULL DEFAULT 0,
    allocated_at      REAL NOT NULL,
    last_used         REAL NOT NULL,
    expires_at        REAL NOT NULL,
    saved_state       TEXT,
    FOREIGN KEY (node_id) REFERENCES fleet_nodes(node_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS fleet_queue (
    request_id        TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL,
    requested_at      REAL NOT NULL,
    expires_at        REAL NOT NULL,
    queue_position    INTEGER NOT NULL,
    ttl_seconds       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fleet_sessions_node ON fleet_sessions(node_id);
CREATE INDEX IF NOT EXISTS idx_fleet_sessions_status ON fleet_sessions(status);
CREATE INDEX IF NOT EXISTS idx_fleet_queue_pos ON fleet_queue(queue_position);
CREATE INDEX IF NOT EXISTS idx_fleet_queue_expires ON fleet_queue(expires_at);
"""


def default_db_path() -> str:
    """Resolve the fleet database location.

    ``FLEET_DB_PATH`` env var wins (tests inject a ``tmp_path`` fleet.db
    through it); otherwise ``~/.browser-helper/fleet.db`` is used.
    """
    env = os.environ.get("FLEET_DB_PATH")
    if env:
        return env
    return str(Path.home() / ".browser-helper" / "fleet.db")


def new_node_id() -> str:
    """Generate a ``node_<hex>`` identifier for a fleet worker node."""
    return f"node_{uuid.uuid4().hex}"


def new_session_id() -> str:
    """Generate a ``sess_<hex>`` identifier for a fleet session."""
    return f"sess_{uuid.uuid4().hex}"


def new_request_id() -> str:
    """Generate a ``q_<hex>`` identifier for a queue entry."""
    return f"q_{uuid.uuid4().hex}"


def _row_to_node(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a fleet_nodes row to an API-facing dict (JSON parsed, bools)."""
    node = dict(row)
    node["capabilities"] = json.loads(node["capabilities"] or "[]")
    node["metadata"] = json.loads(node["metadata"]) if node.get("metadata") else {}
    node["healthy"] = bool(node["healthy"])
    node.pop("deregistered", None)
    return node


def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a fleet_sessions row to an API-facing dict (JSON parsed, bools)."""
    session = dict(row)
    session["queued"] = bool(session["queued"])
    if session.get("saved_state") is not None:
        session["saved_state"] = json.loads(session["saved_state"])
    return session


class FleetSQLite:
    """SQLite backend for fleet nodes, sessions, and the allocation queue.

    Creates the three tables on init (WAL mode, foreign keys on).  All
    writes run inside :attr:`_lock` and are committed atomically; a failed
    write rolls back so compound operations never leave partial state.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path) if db_path is not None else default_db_path()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the connection may be created at import
        # time and used from the asyncio event-loop thread.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Single-writer lock: serialises compound transactions across the
        # async components sharing this instance.
        self._lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    async def _write(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        """Run a sync mutation under the writer lock and commit atomically."""
        async with self._lock:
            try:
                result = fn(self._conn)
                self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise

    def _read(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        """Run a sync read without the writer lock (WAL readers are concurrent)."""
        return fn(self._conn)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # -- nodes -------------------------------------------------------------

    async def add_node(
        self,
        url: str,
        capabilities: list[str] | None = None,
        capacity: int = 5,
        metadata: dict[str, Any] | None = None,
        node_id: str | None = None,
        healthy: bool = True,
    ) -> dict[str, Any]:
        """Insert a node row and return it.

        Raises :class:`sqlite3.IntegrityError` when ``node_id`` already
        exists or a *live* node already uses ``url`` (duplicate
        registration — the API layer maps this to HTTP 409).
        """
        node_id = node_id or new_node_id()
        now = time.time()

        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO fleet_nodes (node_id, url, capabilities, capacity,"
                " active_sessions, healthy, last_checked, last_error, metadata,"
                " registered_at, updated_at) VALUES (?,?,?,?,0,?,0,NULL,?,?,?)",
                (
                    node_id,
                    url,
                    json.dumps(list(capabilities or [])),
                    int(capacity),
                    1 if healthy else 0,
                    json.dumps(metadata) if metadata else None,
                    now,
                    now,
                ),
            )

        await self._write(_do)
        return await self.get_node(node_id)  # type: ignore[return-value]

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return a node dict by id (includes deregistered rows), or None."""

        def _do(conn: sqlite3.Connection) -> sqlite3.Row | None:
            return conn.execute(
                "SELECT * FROM fleet_nodes WHERE node_id = ?", (node_id,)
            ).fetchone()

        row = self._read(_do)
        return _row_to_node(row) if row is not None else None

    async def list_nodes(self) -> list[dict[str, Any]]:
        """List live nodes in scheduling order (healthy first, then load asc)."""

        def _do(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            return conn.execute(
                "SELECT * FROM fleet_nodes WHERE deregistered = 0"
                " ORDER BY healthy DESC, active_sessions ASC, registered_at ASC"
            ).fetchall()

        return [_row_to_node(r) for r in self._read(_do)]

    async def list_healthy_nodes(self) -> list[dict[str, Any]]:
        """List healthy live nodes sorted by active_sessions ascending.

        This is the least-loaded scheduling order consumed by the session
        pool (design §3.1).
        """

        def _do(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            return conn.execute(
                "SELECT * FROM fleet_nodes WHERE deregistered = 0 AND healthy = 1"
                " ORDER BY active_sessions ASC, registered_at ASC"
            ).fetchall()

        return [_row_to_node(r) for r in self._read(_do)]

    async def node_counts(self) -> dict[str, int]:
        """Return ``{total, healthy, unhealthy}`` for live nodes."""
        nodes = await self.list_nodes()
        healthy = sum(1 for n in nodes if n["healthy"])
        return {"total": len(nodes), "healthy": healthy, "unhealthy": len(nodes) - healthy}

    async def update_node_health(
        self,
        node_id: str,
        healthy: bool,
        last_error: str | None = None,
        last_checked: float | None = None,
    ) -> bool:
        """Update a live node's health state; return False when not found."""

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE fleet_nodes SET healthy = ?, last_checked = ?,"
                " last_error = ?, updated_at = ? WHERE node_id = ? AND deregistered = 0",
                (1 if healthy else 0, last_checked if last_checked is not None else time.time(), last_error, time.time(), node_id),
            )
            return cur.rowcount > 0

        return await self._write(_do)

    async def update_node_capacity(self, node_id: str, capacity: int) -> bool:
        """Update a live node's max concurrent sessions; False when not found."""

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE fleet_nodes SET capacity = ?, updated_at = ?"
                " WHERE node_id = ? AND deregistered = 0",
                (int(capacity), time.time(), node_id),
            )
            return cur.rowcount > 0

        return await self._write(_do)

    async def unregister_node(self, node_id: str) -> bool:
        """Soft-delete a node: deregistered, unhealthy, zero active sessions.

        The row stays for history but is excluded from ``list_nodes()``;
        returning False (e.g. already deregistered) maps to HTTP 404.
        """

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE fleet_nodes SET deregistered = 1, healthy = 0,"
                " active_sessions = 0, updated_at = ?"
                " WHERE node_id = ? AND deregistered = 0",
                (time.time(), node_id),
            )
            return cur.rowcount > 0

        return await self._write(_do)

    async def remove_node(self, node_id: str) -> bool:
        """Hard-delete a node row (admin cleanup).

        Refuses (returns False) while the node still hosts active sessions
        so foreign keys and capacity counters stay coherent.
        """

        def _do(conn: sqlite3.Connection) -> bool:
            (active,) = conn.execute(
                "SELECT COUNT(*) FROM fleet_sessions WHERE node_id = ?"
                " AND status IN ('active', 'allocated', 'idle')",
                (node_id,),
            ).fetchone()
            if active:
                return False
            cur = conn.execute("DELETE FROM fleet_nodes WHERE node_id = ?", (node_id,))
            return cur.rowcount > 0

        return await self._write(_do)

    # -- sessions ----------------------------------------------------------

    async def add_session(
        self,
        session_id: str,
        node_id: str,
        node_url: str,
        cdp_url: str | None = None,
        status: str = "active",
        queued: bool = False,
        queue_position: int = 0,
        allocated_at: float | None = None,
        last_used: float | None = None,
        expires_at: float | None = None,
        saved_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a session row and return it.

        When ``status`` is active/allocated/idle the owning node's
        ``active_sessions`` counter is incremented in the same transaction.
        Raises :class:`sqlite3.IntegrityError` on a duplicate session_id or
        a missing node_id (FK).
        """
        now = time.time()
        allocated_at = now if allocated_at is None else allocated_at
        last_used = now if last_used is None else last_used
        expires_at = now + 600.0 if expires_at is None else expires_at

        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO fleet_sessions (session_id, node_id, node_url, cdp_url,"
                " status, queued, queue_position, allocated_at, last_used, expires_at,"
                " saved_state) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    node_id,
                    node_url,
                    cdp_url,
                    status,
                    1 if queued else 0,
                    int(queue_position),
                    allocated_at,
                    last_used,
                    expires_at,
                    json.dumps(saved_state) if saved_state is not None else None,
                ),
            )
            if status in _ACTIVE_SESSION_STATUSES:
                conn.execute(
                    "UPDATE fleet_nodes SET active_sessions = active_sessions + 1"
                    " WHERE node_id = ?",
                    (node_id,),
                )

        await self._write(_do)
        return await self.get_session(session_id)  # type: ignore[return-value]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return a session dict by id, or None."""

        def _do(conn: sqlite3.Connection) -> sqlite3.Row | None:
            return conn.execute(
                "SELECT * FROM fleet_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()

        row = self._read(_do)
        return _row_to_session(row) if row is not None else None

    async def list_sessions(
        self, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List sessions, optionally filtered by status, newest first."""

        def _do(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            if status:
                return conn.execute(
                    "SELECT * FROM fleet_sessions WHERE status = ?"
                    " ORDER BY allocated_at DESC",
                    (status,),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM fleet_sessions ORDER BY allocated_at DESC"
            ).fetchall()

        return [_row_to_session(r) for r in self._read(_do)]

    async def sessions_on_node(
        self, node_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List sessions hosted by one node, optionally filtered by status."""

        def _do(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            if status:
                return conn.execute(
                    "SELECT * FROM fleet_sessions WHERE node_id = ? AND status = ?"
                    " ORDER BY allocated_at DESC",
                    (node_id, status),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM fleet_sessions WHERE node_id = ?"
                " ORDER BY allocated_at DESC",
                (node_id,),
            ).fetchall()

        return [_row_to_session(r) for r in self._read(_do)]

    async def active_count(self, node_id: str) -> int:
        """Count sessions currently occupying a node's capacity.

        This is the ground truth for the registry's ``active_count()``
        (design §3.2) — it reads the sessions table, not the cached
        ``fleet_nodes.active_sessions`` column.
        """

        def _do(conn: sqlite3.Connection) -> int:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM fleet_sessions WHERE node_id = ?"
                " AND status IN ('active', 'allocated', 'idle')",
                (node_id,),
            ).fetchone()
            return int(count)

        return self._read(_do)

    async def release_session(self, session_id: str) -> bool:
        """Release a session: mark ``closed`` and free its node's capacity.

        The status flip and the ``active_sessions`` decrement happen in one
        transaction; a session that was already closed is not double-counted.
        """

        def _do(conn: sqlite3.Connection) -> bool:
            row = conn.execute(
                "SELECT node_id, status FROM fleet_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE fleet_sessions SET status = 'closed', queued = 0"
                " WHERE session_id = ?",
                (session_id,),
            )
            if row["status"] in _ACTIVE_SESSION_STATUSES:
                conn.execute(
                    "UPDATE fleet_nodes SET active_sessions ="
                    " MAX(active_sessions - 1, 0) WHERE node_id = ?",
                    (row["node_id"],),
                )
            return True

        return await self._write(_do)

    async def delete_session(self, session_id: str) -> bool:
        """Permanently remove a session row; False when not found."""

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "DELETE FROM fleet_sessions WHERE session_id = ?", (session_id,)
            )
            return cur.rowcount > 0

        return await self._write(_do)

    async def update_session(self, session_id: str, **fields: Any) -> bool:
        """Update whitelisted session columns; False when the session is missing.

        Supported fields: ``node_id, node_url, cdp_url, status, queued,
        queue_position, allocated_at, last_used, expires_at, saved_state``.
        Capacity counters are NOT adjusted here — use
        :meth:`reassign_session` or :meth:`release_session` for moves that
        change a node's load.
        """
        if not fields:
            return await self.get_session(session_id) is not None
        unknown = set(fields) - _ALLOWED_SESSION_FIELDS
        if unknown:
            raise ValueError(f"Unknown session fields: {sorted(unknown)}")
        updates = dict(fields)
        if "saved_state" in updates:
            state = updates["saved_state"]
            updates["saved_state"] = json.dumps(state) if state is not None else None
        if "queued" in updates:
            updates["queued"] = 1 if updates["queued"] else 0
        assignments = ", ".join(f"{key} = ?" for key in updates)
        params = [*updates.values(), session_id]

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                f"UPDATE fleet_sessions SET {assignments} WHERE session_id = ?",
                params,
            )
            return cur.rowcount > 0

        return await self._write(_do)

    async def save_session_state(
        self, session_id: str, saved_state: dict[str, Any] | None
    ) -> bool:
        """Persist captured session state (cookies/localStorage) for failover."""
        return await self.update_session(session_id, saved_state=saved_state)

    async def reassign_session(
        self,
        session_id: str,
        node_id: str,
        node_url: str,
        cdp_url: str | None = None,
    ) -> bool:
        """Move a session to another node, maintaining both load counters.

        Used by the failover path: the old node's ``active_sessions`` is
        decremented and the new node's incremented atomically with the row
        update.  The session is set back to ``active``.
        """

        def _do(conn: sqlite3.Connection) -> bool:
            row = conn.execute(
                "SELECT node_id, status FROM fleet_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return False
            if row["node_id"] != node_id and row["status"] in _ACTIVE_SESSION_STATUSES:
                conn.execute(
                    "UPDATE fleet_nodes SET active_sessions ="
                    " MAX(active_sessions - 1, 0) WHERE node_id = ?",
                    (row["node_id"],),
                )
                conn.execute(
                    "UPDATE fleet_nodes SET active_sessions = active_sessions + 1"
                    " WHERE node_id = ?",
                    (node_id,),
                )
            conn.execute(
                "UPDATE fleet_sessions SET node_id = ?, node_url = ?, cdp_url = ?,"
                " status = 'active', last_used = ? WHERE session_id = ?",
                (node_id, node_url, cdp_url, time.time(), session_id),
            )
            return True

        return await self._write(_do)

    # -- queue -------------------------------------------------------------

    async def enqueue_request(
        self,
        session_id: str,
        ttl_seconds: float,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Enqueue a session allocation request with a TTL.

        Returns ``{request_id, session_id, queue_position, requested_at,
        expires_at, ttl_seconds}``; ``queue_position`` is monotonically
        increasing (1-based — the API contract asserts ``>= 1``).
        """
        now = time.time()
        request_id = request_id or new_request_id()
        ttl = float(ttl_seconds)
        expires_at = now + ttl

        def _do(conn: sqlite3.Connection) -> int:
            (max_pos,) = conn.execute(
                "SELECT COALESCE(MAX(queue_position), 0) FROM fleet_queue"
            ).fetchone()
            position = int(max_pos) + 1
            conn.execute(
                "INSERT INTO fleet_queue (request_id, session_id, requested_at,"
                " expires_at, queue_position, ttl_seconds) VALUES (?,?,?,?,?,?)",
                (request_id, session_id, now, expires_at, position, ttl),
            )
            return position

        position = await self._write(_do)
        return {
            "request_id": request_id,
            "session_id": session_id,
            "queue_position": position,
            "requested_at": now,
            "expires_at": expires_at,
            "ttl_seconds": ttl,
        }

    async def dequeue_ready(self, node_id: str | None = None) -> dict[str, Any] | None:
        """Atomically pop the lowest-position non-expired request, or None.

        ``node_id`` is accepted for call-site compatibility with the design
        brief (``dequeue_ready(node_id)``); the node target is chosen by the
        queue manager *after* the pop, so it is not used for filtering here.
        """

        def _do(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute(
                "SELECT * FROM fleet_queue WHERE expires_at > ?"
                " ORDER BY queue_position ASC LIMIT 1",
                (time.time(),),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "DELETE FROM fleet_queue WHERE request_id = ?", (row["request_id"],)
            )
            return dict(row)

        return await self._write(_do)

    async def peek_queue(self) -> list[dict[str, Any]]:
        """Return the queue in FIFO order without consuming it."""

        def _do(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            return conn.execute(
                "SELECT * FROM fleet_queue ORDER BY queue_position ASC"
            ).fetchall()

        return [dict(r) for r in self._read(_do)]

    async def queue_size(self) -> int:
        """Return the number of pending queue entries."""

        def _do(conn: sqlite3.Connection) -> int:
            (count,) = conn.execute("SELECT COUNT(*) FROM fleet_queue").fetchone()
            return int(count)

        return self._read(_do)

    async def prune_expired(self, now: float | None = None) -> int:
        """Remove expired queue entries; return how many were purged."""
        cutoff = time.time() if now is None else now

        def _do(conn: sqlite3.Connection) -> int:
            cur = conn.execute(
                "DELETE FROM fleet_queue WHERE expires_at <= ?", (cutoff,)
            )
            return cur.rowcount

        return await self._write(_do)
