"""Fleet orchestration package — distributed browser node management.

Implements the v1.18.0 fleet design (see ``analysis/analysis-brief.md`` and
``analysis/architecture-brief.md``): a coordinator manages a pool of
browser-helper worker nodes, schedules sessions across them, queues when at
capacity, and fails sessions over on node loss.

Module layout::

    fleet/
        __init__.py        public API (this module)
        storage.py         FleetSQLite — WAL SQLite backend (nodes/sessions/queue)
        node_registry.py   Node dataclass + NodeRegistry
        health_checker.py  FleetHealthChecker — async periodic /health polling
        session_pool.py    FleetSessionPool — least-loaded allocation + failover
        queue_manager.py   FleetQueueManager — FIFO queue, TTL, 503 + Retry-After
        failover.py        FailoverManager — state transfer on node failure
        api.py             FleetCoordinator facade + FastAPI router (/fleet/*)
        cli.py             ``python -m fleet.cli node list`` / ``session list``
"""

from fleet.api import FleetCoordinator
from fleet.failover import FailoverManager
from fleet.health_checker import FleetHealthChecker
from fleet.node_registry import DuplicateNodeError, Node, NodeRegistry
from fleet.queue_manager import DEFAULT_MAX_QUEUE, FleetQueueManager, QueueFullError
from fleet.session_pool import FleetSessionPool
from fleet.storage import (
    FleetSQLite,
    default_db_path,
    new_node_id,
    new_request_id,
    new_session_id,
)

__all__ = [
    "DEFAULT_MAX_QUEUE",
    "DuplicateNodeError",
    "FailoverManager",
    "FleetCoordinator",
    "FleetHealthChecker",
    "FleetQueueManager",
    "FleetSQLite",
    "FleetSessionPool",
    "Node",
    "NodeRegistry",
    "QueueFullError",
    "default_db_path",
    "new_node_id",
    "new_request_id",
    "new_session_id",
]
