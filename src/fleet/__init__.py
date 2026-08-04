"""Fleet orchestration package — distributed browser node management.

Implements the v1.18.0 fleet design (see ``analysis/analysis-brief.md`` and
``analysis/architecture-brief.md``): a coordinator manages a pool of
browser-helper worker nodes, schedules sessions across them, queues when at
capacity, and fails sessions over on node loss.

This package currently ships the persistence and node-registry foundation
(P0 modules 1–2 of the analysis brief)::

    fleet/
        __init__.py        public API (this module)
        storage.py         FleetSQLite — WAL SQLite backend (nodes/sessions/queue)
        node_registry.py   Node dataclass + NodeRegistry

The health checker, session pool, queue manager, failover manager, API
router, and CLI land in follow-up tasks; they consume the exports below.
"""

from fleet.node_registry import DuplicateNodeError, Node, NodeRegistry
from fleet.storage import (
    FleetSQLite,
    default_db_path,
    new_node_id,
    new_request_id,
    new_session_id,
)

__all__ = [
    "DuplicateNodeError",
    "FleetSQLite",
    "Node",
    "NodeRegistry",
    "default_db_path",
    "new_node_id",
    "new_request_id",
    "new_session_id",
]
