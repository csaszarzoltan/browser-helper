"""Fleet health checker — async periodic polling of node ``/health`` endpoints.

``FleetHealthChecker`` probes every registered node's ``/health`` endpoint on a
configurable interval (default 15s, ``±jitter_s`` of random offset to avoid
poll storms — mirroring the ``ProxyPool`` health-check pattern in
``src/proxy_manager.py``) and persists healthy/unhealthy state plus
``last_error`` through :class:`~fleet.node_registry.NodeRegistry`.

Cooldown semantics
------------------
A node that just flipped unhealthy is not re-probed by the periodic loop for
``cooldown_s`` (default 30s): a down worker is not hammered, and the
``on_node_unhealthy`` callback (wired by the coordinator to trigger
:class:`~fleet.failover.FailoverManager`) fires exactly once per unhealthy
episode.  Manual probes — :meth:`probe` (the API's ``GET
/fleet/nodes/{id}/health``) and :meth:`check_all` (``POST
/fleet/nodes/health-check``) — always run and bypass the cooldown, so an
operator can force a recheck at any time.

Probe result shape (mirrors ``ProxyPool.health_check``):
``{node_id, healthy, latency_ms, last_checked, node_status, last_error}``.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from fleet.node_registry import Node, NodeRegistry

logger = logging.getLogger("browser-helper.fleet.health")


class FleetHealthChecker:
    """Poll registered nodes' ``/health`` endpoints and track their state.

    The checker is a thin service over :class:`NodeRegistry` — health state is
    persisted in SQLite (``fleet_nodes.healthy / last_checked / last_error``),
    never held in a parallel in-memory copy.  :meth:`start` spawns a single
    asyncio task that loops until :meth:`stop`; the API's lifespan handler is
    responsible for calling those two methods.
    """

    def __init__(
        self,
        registry: NodeRegistry | None = None,
        db_path: str | None = None,
        poll_interval_s: float = 15.0,
        timeout_s: float = 5.0,
        cooldown_s: float = 30.0,
        jitter_s: float = 2.0,
        http_client: httpx.AsyncClient | None = None,
        on_node_unhealthy: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Wrap a registry (or open a new one at ``db_path``) and configure polling.

        ``on_node_unhealthy`` is an optional async callback invoked once per
        unhealthy episode with the node_id — the coordinator injects the
        failover manager's entry point here.
        """
        self.registry = registry or NodeRegistry(db_path=db_path)
        self.poll_interval_s = float(poll_interval_s)
        self.timeout_s = float(timeout_s)
        self.cooldown_s = float(cooldown_s)
        self.jitter_s = float(jitter_s)
        self._http = http_client
        self._owns_http = http_client is None
        self.on_node_unhealthy = on_node_unhealthy
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        #: node_id -> epoch until which the periodic loop skips the node.
        self._cooldown_until: dict[str, float] = {}
        #: node_id -> last health flag we persisted (for transition detection).
        self._last_healthy: dict[str, bool] = {}

    # -- HTTP plumbing ----------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        """Return the shared AsyncClient, creating it lazily if not injected."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout_s)
            self._owns_http = True
        return self._http

    # -- probing ----------------------------------------------------------

    async def _probe_node(self, node: Node) -> dict[str, Any]:
        """Run one live probe against ``node`` and persist the result.

        Returns the probe result dict; ``healthy`` is True only on HTTP 200.
        On any transport/HTTP failure the node is marked unhealthy with a
        ``last_error`` message and ``node_status`` is ``{}``.
        """
        url = node.url.rstrip("/") + "/health"
        started = time.perf_counter()
        healthy = False
        node_status: dict[str, Any] = {}
        last_error: str | None = None
        try:
            resp = await self._client().get(url)
            latency_ms = (time.perf_counter() - started) * 1000.0
            if resp.status_code == 200:
                healthy = True
                try:
                    body = resp.json()
                    node_status = body if isinstance(body, dict) else {"status": body}
                except Exception:  # noqa: BLE001 — non-JSON bodies are fine
                    node_status = {"status_code": resp.status_code}
            else:
                last_error = f"HTTP {resp.status_code} from {url}"
        except Exception as exc:  # noqa: BLE001 — network failures mark the node down
            latency_ms = (time.perf_counter() - started) * 1000.0
            last_error = f"{type(exc).__name__}: {exc}"
            node_status = {}

        now = time.time()
        await self.registry.update_health(
            node.node_id,
            healthy=healthy,
            last_error=last_error,
            last_checked=now,
        )
        return {
            "node_id": node.node_id,
            "healthy": healthy,
            "latency_ms": round(latency_ms, 1),
            "last_checked": now,
            "node_status": node_status,
            "last_error": last_error,
        }

    async def probe(self, node_id: str) -> dict[str, Any] | None:
        """Probe a single node on demand; ``None`` when the node is unknown.

        Backs the API endpoint ``GET /fleet/nodes/{id}/health``.  Always runs
        (bypasses the cooldown) and persists the result via the registry.
        """
        node = await self.registry.get(node_id)
        if node is None:
            return None
        result = await self._probe_node(node)
        await self._handle_transition(node_id, result["healthy"])
        return result

    async def check_all(self) -> dict[str, Any]:
        """Probe every live registered node and return a summary.

        Backs the manual recheck endpoint ``POST /fleet/nodes/health-check``.
        Unlike the periodic loop this probes unconditionally — it is the
        operator's "recheck now" lever.
        """
        results: list[dict[str, Any]] = []
        for node in await self.registry.list():
            result = await self._probe_node(node)
            results.append(result)
            await self._handle_transition(node.node_id, result["healthy"])
        healthy = sum(1 for r in results if r["healthy"])
        return {
            "checked": len(results),
            "healthy": healthy,
            "unhealthy": len(results) - healthy,
            "results": results,
        }

    # -- transition handling ----------------------------------------------

    async def _handle_transition(self, node_id: str, healthy: bool) -> None:
        """Track healthy→unhealthy transitions, cooldown, and the failover hook.

        The cooldown only gates the *periodic* loop: once a node is marked
        unhealthy the loop leaves it alone for ``cooldown_s`` (no hammering a
        down worker).  The ``on_node_unhealthy`` callback fires exactly once
        per unhealthy episode — when the node flips from healthy (or unknown)
        to unhealthy — so the failover path is not re-triggered while a node
        stays down.  A recovery clears the cooldown.
        """
        previous = self._last_healthy.get(node_id)
        self._last_healthy[node_id] = healthy
        if not healthy:
            self._cooldown_until[node_id] = time.time() + self.cooldown_s
            if previous is not False and self.on_node_unhealthy is not None:
                try:
                    await self.on_node_unhealthy(node_id)
                except Exception:
                    logger.exception("on_node_unhealthy hook failed for %s", node_id)
        else:
            self._cooldown_until.pop(node_id, None)

    # -- lifecycle --------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodic probe loop with jitter and per-node cooldown."""
        while not self._stop_event.is_set():
            try:
                for node in await self.registry.list():
                    if self._stop_event.is_set():
                        break
                    if time.time() < self._cooldown_until.get(node.node_id, 0.0):
                        continue  # node is in cooldown — skip until it expires
                    result = await self._probe_node(node)
                    await self._handle_transition(node.node_id, result["healthy"])
            except Exception:
                logger.exception("fleet health poll cycle failed")
            delay = max(
                0.5,
                self.poll_interval_s + random.uniform(-self.jitter_s, self.jitter_s),
            )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass

    def start(self) -> None:
        """Spawn the periodic polling task (idempotent)."""
        if self._task is None or self._task.done():
            self._stop_event = asyncio.Event()
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the periodic polling task and release the HTTP client."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # expected — stop() cancels the poll loop
            except Exception:
                logger.exception("fleet health poll task exited with an error")
            self._task = None
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None
