"""Fleet queue manager — FIFO allocation queue with TTL and 503 + Retry-After.

``FleetQueueManager`` implements the queueing tier of the fleet orchestration
design (``analysis/architecture-brief.md`` §3.5, matching Browserless' 3-tier
model: concurrency → queue → 503).  When every healthy node is at capacity,
``POST /fleet/session`` enqueues the allocation request (HTTP 202); once the
queue holds ``max_queue`` entries the next request is rejected with HTTP 503
and a ``Retry-After`` hint (``analysis-brief.md`` §8.3).

Queue entries live in the ``fleet_queue`` table:

* ``enqueue()`` appends with a monotonically increasing 1-based
  ``queue_position`` and ``expires_at = now + ttl_seconds``;
* ``dequeue_ready()`` pops the lowest-position non-expired entry (the queue
  drainer allocates the session right after the pop);
* ``prune_expired()`` / ``sweep()`` purge entries past their TTL (the
  ``POST /fleet/queue/sweep`` endpoint).

``max_queue`` defaults to 10 — the test contract's comment in
``test_fleet_v115.py::TestQueueing::test_503_when_queue_full`` ("max_queue
defaults to 10") overrides the architecture brief's suggested 100, and the
queue-full tests depend on that exact threshold.
"""

from __future__ import annotations

import logging
from typing import Any

from fleet.node_registry import NodeRegistry

logger = logging.getLogger("browser-helper.fleet.queue")

#: Default max concurrent queued allocation requests (test contract, §8.3).
DEFAULT_MAX_QUEUE = 10
#: Assumed seconds a session occupies a node — used for wait estimation.
AVG_SESSION_SECONDS = 30.0


class QueueFullError(Exception):
    """Raised when the allocation queue is at ``max_queue`` depth.

    Carries ``retry_after`` (seconds) — the API layer surfaces it as the
    ``Retry-After`` header / ``meta.retry_after`` on the HTTP 503 response.
    """

    def __init__(self, retry_after: float, message: str = "Fleet queue is full") -> None:
        super().__init__(message)
        self.retry_after = float(retry_after)


class FleetQueueManager:
    """FIFO allocation queue backed by ``fleet_queue`` (via NodeRegistry)."""

    def __init__(
        self,
        registry: NodeRegistry | None = None,
        db_path: str | None = None,
        max_queue: int = DEFAULT_MAX_QUEUE,
        default_ttl_seconds: float = 600.0,
        avg_session_seconds: float = AVG_SESSION_SECONDS,
    ) -> None:
        """Wrap a registry (or open one at ``db_path``) and set queue limits."""
        self.registry = registry or NodeRegistry(db_path=db_path)
        self.max_queue = int(max_queue)
        self.default_ttl_seconds = float(default_ttl_seconds)
        self.avg_session_seconds = float(avg_session_seconds)

    # -- capacity helpers -------------------------------------------------

    async def _total_capacity(self) -> int:
        """Sum of healthy nodes' capacity — the drain rate for wait estimates."""
        nodes = await self.registry.storage.list_healthy_nodes()
        return sum(int(n["capacity"]) for n in nodes)

    async def estimated_wait_seconds(self, position: int) -> float:
        """Estimate seconds until the request at ``position`` is allocated.

        Approximates the fleet's drain rate as ``total_capacity / avg session
        length``; position 1 on a single-slot node yields ~30s.
        """
        capacity = await self._total_capacity()
        if capacity <= 0:
            return max(1.0, float(position) * self.avg_session_seconds)
        return max(
            1.0,
            float(position) * self.avg_session_seconds / float(capacity),
        )

    async def retry_after(self) -> float:
        """Seconds a full-queue client should wait before retrying."""
        size = await self.registry.storage.queue_size()
        capacity = await self._total_capacity()
        if capacity <= 0:
            return max(1.0, float(size) * self.avg_session_seconds)
        return max(1.0, float(size) * self.avg_session_seconds / float(capacity))

    # -- queue operations -------------------------------------------------

    async def enqueue(
        self,
        session_id: str,
        ttl_seconds: float | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Append an allocation request to the FIFO queue.

        Returns ``{request_id, session_id, queue_position, requested_at,
        expires_at, ttl_seconds, estimated_wait_seconds}``.  Raises
        :class:`QueueFullError` (with ``retry_after``) when the queue already
        holds ``max_queue`` entries.
        """
        ttl = self.default_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        size = await self.registry.storage.queue_size()
        if size >= self.max_queue:
            raise QueueFullError(retry_after=await self.retry_after())
        record = await self.registry.storage.enqueue_request(
            session_id=session_id,
            ttl_seconds=ttl,
            request_id=request_id,
        )
        record["estimated_wait_seconds"] = round(
            await self.estimated_wait_seconds(int(record["queue_position"])), 1
        )
        return record

    async def dequeue_ready(self, node_id: str | None = None) -> dict[str, Any] | None:
        """Pop the lowest-position non-expired request, or None when empty.

        The node target is chosen by the caller *after* the pop (the design's
        ``dequeue_ready(node_id)`` signature is preserved for compatibility;
        the node hint is not used for filtering here).
        """
        return await self.registry.storage.dequeue_ready(node_id=node_id)

    async def prune_expired(self) -> int:
        """Remove queue entries past their TTL; return how many were purged."""
        return await self.registry.storage.prune_expired()

    async def sweep(self) -> dict[str, Any]:
        """Purge expired entries and report queue depth (``POST /fleet/queue/sweep``).

        Returns ``{"expired_count", "purged", "queued"}`` — both spellings of
        the purged count are provided so the contract's
        ``sweep_data.get("expired_count", sweep_data.get("purged", 0))``
        assertion works regardless of which key the API layer forwards.
        """
        purged = await self.prune_expired()
        return {
            "expired_count": purged,
            "purged": purged,
            "queued": await self.registry.storage.queue_size(),
        }

    async def size(self) -> int:
        """Return the number of pending queue entries."""
        return await self.registry.storage.queue_size()

    async def peek(self) -> list[dict[str, Any]]:
        """Return the queue in FIFO order without consuming it."""
        return await self.registry.storage.peek_queue()

    async def is_full(self) -> bool:
        """Return True when the queue is at ``max_queue`` depth."""
        return await self.registry.storage.queue_size() >= self.max_queue

    def max_queue_depth(self) -> int:
        """Return the configured ``max_queue`` limit (informational)."""
        return self.max_queue
