"""Fleet tool handlers — read-only (spec §5.9).

fleet_nodes / fleet_status / fleet_queue. All three use
``get_fleet_coordinator()`` — the same process-wide singleton the REST router
uses — and call **read-only** methods only (AC#5: no register/unregister/
allocate/release/sweep anywhere). Envelopes are built via
:mod:`mcp_server.serialization` with ``meta.read_only: true``.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context  # typing only

from .serialization import tool_error, tool_result


async def fleet_nodes(ctx: Context | None = None) -> str:
    """List fleet worker nodes (capability ``workflow.local``, READY).

    ``{nodes, total, healthy, unhealthy}`` from ``coordinator.registry.snapshot()``.
    Pure read. Mirrors ``GET /fleet/nodes``.
    """
    from fleet.api import get_fleet_coordinator  # lazy import

    if ctx is not None:
        ctx.info("reading fleet nodes")
    try:
        coordinator = get_fleet_coordinator()
        data = await coordinator.registry.snapshot()
        return tool_result("fleet_nodes", data, meta={"read_only": True})
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return tool_error("fleet_nodes", "operation_failed", str(exc))


async def fleet_status(ctx: Context | None = None) -> str:
    """Report fleet session status (capability ``workflow.local``, READY).

    ``{sessions, total, active, queued}`` from ``coordinator.pool.list_sessions()``
    + ``coordinator.registry.snapshot()``. Pure read. Mirrors ``GET /fleet/sessions``.
    """
    from fleet.api import get_fleet_coordinator  # lazy import

    if ctx is not None:
        ctx.report_progress(0, 1, message="reading fleet sessions")
    try:
        coordinator = get_fleet_coordinator()
        sessions = await coordinator.pool.list_sessions()
        active = sum(
            1 for s in sessions if s.get("status") in ("active", "allocated", "idle")
        )
        queued = sum(1 for s in sessions if s.get("queued"))
        return tool_result(
            "fleet_status",
            {
                "sessions": sessions,
                "total": len(sessions),
                "active": active,
                "queued": queued,
            },
            meta={"read_only": True},
        )
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return tool_error("fleet_status", "operation_failed", str(exc))


async def fleet_queue(ctx: Context | None = None) -> str:
    """Peek the fleet allocation queue without consuming it (capability ``workflow.local``, READY).

    ``{queue, size, max_queue}`` from ``coordinator.queue.peek()`` +
    ``coordinator.queue.size()``. Pure read.
    """
    from fleet.api import get_fleet_coordinator  # lazy import

    if ctx is not None:
        ctx.report_progress(0, 1, message="peeking fleet queue")
    try:
        coordinator = get_fleet_coordinator()
        queue = await coordinator.queue.peek()
        size = await coordinator.queue.size()
        return tool_result(
            "fleet_queue",
            {
                "queue": queue,
                "size": size,
                "max_queue": coordinator.queue.max_queue,
            },
            meta={"read_only": True},
        )
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return tool_error("fleet_queue", "operation_failed", str(exc))


async def fleet_run_batch(tasks: list[dict], concurrency: int = 4,
                          ctx: Context | None = None) -> str:
    """Run N independent browsing tasks in parallel (capability ``workflow.local``, READY).

    Each task: {url, action?, assert_selector?, assert_text?, timeout?}.
    Tasks run in isolated session tabs up to *concurrency* at a time; one
    failing task does not affect the others.  Returns an aggregated report.
    """

    if ctx is not None:
        ctx.info(f"fleet_run_batch tasks={len(tasks or [])} concurrency={concurrency}")
    if not tasks:
        return tool_error("fleet_run_batch", "invalid_params", "tasks is required")
    try:
        # Route through the REST handler so the batch logic lives in one place.
        from fastapi.testclient import TestClient

        import main

        with TestClient(main.app) as c:
            resp = c.post("/fleet/run-batch", json={
                "tasks": tasks, "concurrency": concurrency,
            })
            body = resp.json()
            if resp.status_code != 200:
                return tool_error("fleet_run_batch", "batch_failed",
                                  body.get("error", {}).get("message", str(body))[:300])
            return tool_result("fleet_run_batch", body.get("data", {}))
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return tool_error("fleet_run_batch", "operation_failed", str(exc))
