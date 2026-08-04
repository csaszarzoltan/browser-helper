"""Node registry for the fleet orchestration module.

Holds the :class:`Node` dataclass (mirroring ``ProxyEntry``'s field style in
``src/proxy_manager.py``) and :class:`NodeRegistry`, the register/unregister
and capacity-tracking facade consumed by the health checker, session pool,
queue manager, failover manager, and fleet API.

The SQLite database is the source of truth; ``NodeRegistry`` is a thin,
storage-backed service — it never keeps a parallel in-memory copy of node
state.  All methods are ``async`` and delegate to :class:`FleetSQLite`.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fleet.storage import FleetSQLite, new_node_id

logger = logging.getLogger("browser-helper.fleet.registry")


class DuplicateNodeError(Exception):
    """Raised when registering a node whose URL is already registered.

    The fleet API layer maps this to HTTP 409
    (``test_fleet_v115.py::TestNodeRegistry::test_register_duplicate``).
    """


@dataclass
class Node:
    """A registered fleet worker node (mirrors ``ProxyEntry`` field style).

    Field order and defaults follow ``analysis/architecture-brief.md`` §3.2:
    ``node_id`` and ``url`` are required; capacity/health metadata carry
    defaults.  ``active_sessions`` is maintained by session allocate/release
    (and read back from the sessions table via ``active_count()``).
    """

    node_id: str
    url: str
    capabilities: list[str]
    capacity: int
    active_sessions: int
    healthy: bool = True
    last_checked: float = 0.0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict (the API node payload shape)."""
        return {
            "node_id": self.node_id,
            "url": self.url,
            "capabilities": list(self.capabilities),
            "capacity": self.capacity,
            "active_sessions": self.active_sessions,
            "healthy": self.healthy,
            "last_checked": self.last_checked,
            "last_error": self.last_error,
            "metadata": dict(self.metadata),
            "registered_at": self.registered_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Node:
        """Build a Node from a storage row dict (JSON columns already parsed)."""
        return cls(
            node_id=row["node_id"],
            url=row["url"],
            capabilities=list(row.get("capabilities") or []),
            capacity=int(row["capacity"]),
            active_sessions=int(row["active_sessions"]),
            healthy=bool(row["healthy"]),
            last_checked=float(row.get("last_checked") or 0.0),
            last_error=row.get("last_error"),
            metadata=dict(row.get("metadata") or {}),
            registered_at=float(row["registered_at"]),
            updated_at=float(row["updated_at"]),
        )


class NodeRegistry:
    """Register/unregister fleet nodes and track capacity and health.

    Adds registry semantics on top of :class:`FleetSQLite`: node_id
    generation, duplicate-URL detection (:class:`DuplicateNodeError`),
    least-loaded selection with round-robin tie-break, and snapshot
    summarisation for the dashboard/API.
    """

    def __init__(
        self,
        storage: FleetSQLite | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        """Wrap an existing storage instance or open a new one at ``db_path``.

        Passing a shared ``storage`` lets the session pool / queue manager /
        health checker all read and write through the same WAL connection.
        """
        self.storage = storage or FleetSQLite(db_path=db_path)
        self._round_robin_index = 0

    # -- registration ------------------------------------------------------

    async def register(
        self,
        url: str,
        capabilities: list[str] | None = None,
        capacity: int = 5,
        metadata: dict[str, Any] | None = None,
        node_id: str | None = None,
    ) -> Node:
        """Register a node and return its :class:`Node`.

        Generates a ``node_<hex>`` id when ``node_id`` is omitted.  Raises
        :class:`DuplicateNodeError` if a live node already uses ``url``.
        """
        node_id = node_id or new_node_id()
        try:
            await self.storage.add_node(
                node_id=node_id,
                url=url,
                capabilities=list(capabilities or []),
                capacity=int(capacity),
                metadata=dict(metadata or {}),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateNodeError(
                f"A fleet node with url {url!r} is already registered"
            ) from exc
        node = await self.get(node_id)
        if node is None:  # pragma: no cover - defensive; insert just succeeded
            raise RuntimeError(f"Node {node_id} was registered but could not be read")
        return node

    async def unregister(self, node_id: str) -> bool:
        """Remove a node from the registry (soft-delete in storage).

        Returns False when the node is unknown or already deregistered
        (the API layer maps that to HTTP 404).
        """
        return await self.storage.unregister_node(node_id)

    # -- reads -------------------------------------------------------------

    async def get(self, node_id: str) -> Node | None:
        """Return a registered node by id, or None."""
        row = await self.storage.get_node(node_id)
        return Node.from_row(row) if row is not None else None

    async def list(self) -> list[Node]:
        """Return all live nodes in scheduling order (healthy first, load asc)."""
        return [Node.from_row(r) for r in await self.storage.list_nodes()]

    async def list_healthy(self) -> list[Node]:
        """Return healthy nodes sorted by active_sessions ascending.

        This is the least-loaded scheduling order the session pool iterates.
        """
        return [Node.from_row(r) for r in await self.storage.list_healthy_nodes()]

    async def active_count(self, node_id: str) -> int:
        """Return the node's live session count (delegates to the sessions table)."""
        return await self.storage.active_count(node_id)

    # -- health / capacity -------------------------------------------------

    async def update_health(
        self,
        node_id: str,
        healthy: bool,
        last_error: str | None = None,
        last_checked: float | None = None,
    ) -> Node | None:
        """Persist a health check result; return the updated Node or None."""
        ok = await self.storage.update_node_health(
            node_id, healthy=healthy, last_error=last_error, last_checked=last_checked
        )
        return await self.get(node_id) if ok else None

    async def update_capacity(self, node_id: str, capacity: int) -> Node | None:
        """Change a node's max concurrent sessions; return the updated Node or None."""
        ok = await self.storage.update_node_capacity(node_id, capacity)
        return await self.get(node_id) if ok else None

    # -- scheduling helpers -------------------------------------------------

    async def least_loaded(
        self, exclude: set[str] | None = None
    ) -> Node | None:
        """Pick the healthy node with free capacity and the fewest sessions.

        Ties are broken round-robin (the design's fallback policy, §3.4).
        ``exclude`` lists node_ids that must not be selected — the failover
        path passes the failed node so a session lands elsewhere.  Returns
        None when no healthy node has capacity.
        """
        exclude = exclude or set()
        candidates = [
            n
            for n in await self.list_healthy()
            if n.node_id not in exclude and n.active_sessions < n.capacity
        ]
        if not candidates:
            return None
        min_load = min(n.active_sessions for n in candidates)
        tied = [n for n in candidates if n.active_sessions == min_load]
        self._round_robin_index += 1
        return tied[self._round_robin_index % len(tied)]

    async def has_capacity(self) -> bool:
        """Return True when some healthy node can take a new session."""
        return await self.least_loaded() is not None

    async def snapshot(self) -> dict[str, Any]:
        """Return ``{nodes, total, healthy, unhealthy}`` for dashboard/API."""
        nodes = await self.list()
        return {
            "nodes": [n.to_dict() for n in nodes],
            "total": len(nodes),
            "healthy": sum(1 for n in nodes if n.healthy),
            "unhealthy": sum(1 for n in nodes if not n.healthy),
        }

    def close(self) -> None:
        """Close the underlying storage connection."""
        self.storage.close()
