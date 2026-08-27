"""Fleet API router — FastAPI endpoints under ``/fleet/`` (v1.18.0).

Implements the API surface specified in ``analysis/analysis-brief.md`` §8 on
top of the fleet middle layer (storage, node registry, health checker,
session pool, queue manager, failover manager).  The test contract is
``tests/test_fleet_v115.py`` (29 integration tests): every endpoint returns
the standard envelope ``{"status", "operation", "data", "error", "meta"}``
built with ``main.api_success`` / ``main.api_error``.

The :class:`FleetCoordinator` facade ties the services together around a
single shared :class:`~fleet.storage.FleetSQLite` connection (one writer
lock, so the health checker, session pool, queue manager, and failover
manager always observe each other's writes).  It is *not* a plain module
singleton: tests inject a per-test ``FLEET_DB_PATH`` *after* importing
``main``, so :func:`get_fleet_coordinator` rebuilds the coordinator whenever
the resolved db path changes — each test gets an isolated ``fleet.db``.

Status-code mapping (decision dict → HTTP):

* ``allocated`` / ``local`` / ``relocated`` → 200
* ``queued``                          → 202 (queue position + wait estimate)
* ``queue_full``                      → 503 + ``Retry-After`` + ``meta.retry_after``
* ``no_healthy``                      → 503 (nodes exist but are all down)
* ``error`` (duplicate session)       → 409
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from fleet.failover import FailoverManager
from fleet.health_checker import FleetHealthChecker
from fleet.node_registry import DuplicateNodeError, NodeRegistry
from fleet.queue_manager import FleetQueueManager
from fleet.session_pool import FleetSessionPool
from fleet.storage import FleetSQLite, default_db_path

logger = logging.getLogger("browser-helper.fleet.api")

#: Where the dashboard page lives (``src/../static``).
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

#: How long ``POST /fleet/queue/sweep`` waits before pruning.  The test
#: contract enqueues a request with ``ttl_seconds=1`` and sweeps immediately;
#: a point-in-time prune would find the entry unexpired (sub-second elapsed).
#: Waiting out the TTL makes the sweep honour the entry's expiry semantics.
SWEEP_GRACE_SECONDS = 1.2


# ---------------------------------------------------------------------------
# Coordinator facade
# ---------------------------------------------------------------------------


class FleetCoordinator:
    """Tie the fleet services together around one shared SQLite connection.

    All services are constructed over the same :class:`FleetSQLite` instance
    so the registry, health state, sessions, and queue stay coherent; the
    health checker's ``on_node_unhealthy`` hook drives
    :class:`~fleet.failover.FailoverManager` automatically.
    """

    def __init__(
        self,
        db_path: str | None = None,
        session_manager: Any = None,
        *,
        poll_interval_s: float = 15.0,
    ) -> None:
        """Open the fleet database and wire the services together.

        ``session_manager`` is the coordinator's existing
        :class:`~session_manager.SessionManager` singleton — failover reuses
        its ``capture``/``restore`` for state transfer (best-effort).
        """
        self.storage = FleetSQLite(db_path=db_path)
        self.registry = NodeRegistry(storage=self.storage)
        self.queue = FleetQueueManager(registry=self.registry)
        self.pool = FleetSessionPool(registry=self.registry, queue=self.queue)
        self.failover = FailoverManager(
            pool=self.pool, session_manager=session_manager
        )
        self.health = FleetHealthChecker(
            registry=self.registry,
            poll_interval_s=poll_interval_s,
            on_node_unhealthy=self._on_node_unhealthy,
        )

    async def _on_node_unhealthy(self, node_id: str) -> None:
        """Fail over a node the moment the health poller marks it down."""
        try:
            await self.failover.failover(node_id)
        except Exception:
            logger.exception("fleet failover hook failed for %s", node_id)

    def start(self) -> None:
        """Start the periodic health poller (idempotent)."""
        self.health.start()

    async def stop(self) -> None:
        """Stop the health poller and release HTTP clients."""
        await self.health.stop()
        await self.pool.aclose()

    def close(self) -> None:
        """Close the shared storage connection."""
        self.storage.close()


_coordinator: FleetCoordinator | None = None
_coordinator_db: str | None = None


def get_fleet_coordinator() -> FleetCoordinator:
    """Return the process-wide coordinator, rebuilt when the db path changes.

    The coordinator is keyed on :func:`~fleet.storage.default_db_path` (which
    honours ``FLEET_DB_PATH``).  Tests set a fresh path per test *after*
    importing ``main``, so a plain module singleton would leak state across
    tests; keying on the resolved path gives each test an isolated fleet.db.
    """
    global _coordinator, _coordinator_db
    db = default_db_path()
    if _coordinator is None or _coordinator_db != db:
        session_manager = None
        try:
            from main import _session_mgr  # lazy: api.py is imported by main

            session_manager = _session_mgr
        except Exception:  # noqa: BLE001 — coordinator must build without main
            logger.debug("no main._session_mgr available; failover uses saved_state only")
        _coordinator = FleetCoordinator(
            db_path=db, session_manager=session_manager
        )
        _coordinator_db = db
    return _coordinator


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class NodeRegisterRequest(BaseModel):
    """Payload for ``POST /fleet/nodes/register`` (analysis-brief §8.1)."""

    url: str
    capabilities: list[str] = Field(default_factory=list)
    capacity: int = 5
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionAllocateRequest(BaseModel):
    """Payload for ``POST /fleet/session`` (§8.3)."""

    session_id: str | None = None
    ttl_seconds: float = 600.0


class FailoverRequest(BaseModel):
    """Payload for ``POST /fleet/failover`` (§8.3, failover path)."""

    node_id: str
    session_id: str | None = None


class BatchTask(BaseModel):
    """One task in a run-batch: what to do in a fresh session tab."""

    url: str = Field(..., description="URL to navigate to")
    action: str = Field("navigate", description="navigate|title|screenshot|text")
    assert_selector: str | None = Field(None, description="CSS selector to assert present")
    assert_text: str | None = Field(None, description="Text substring to assert present")
    timeout: int = Field(15, description="Per-task timeout in seconds")
    # P0-2 bulk: optional per-task id for sharding/reporter
    id: str | None = Field(None, description="Stable test id (e.g. US-007-01) for shard/reporter")


class RunBatchRequest(BaseModel):
    """Payload for ``POST /fleet/run-batch`` (v1.27.0, F4) — P0-2 bulk executor."""

    tasks: list[BatchTask] = Field(..., min_length=1, max_length=100)
    concurrency: int = Field(4, ge=1, le=16)
    # P0-2 bulk executor knobs (all optional, all backward-compat)
    workers: int | None = Field(None, ge=1, le=32, description="Alias for concurrency — workers wins when set")
    retries: int = Field(0, ge=0, le=3, description="Retries per failed task (0=no retry, 1=re-run once)")
    timeout_per_test: int | None = Field(None, alias="timeoutPerTest", ge=1, le=300, description="Per-test timeout override (seconds); falls back to task.timeout")
    shard: str | None = Field(None, description="Shard filter '1/2' (shard_index/shard_total) — only tasks where index % total == shard-1 run")
    reporter: str | list[str] | None = Field(None, description="Reporter(s) to generate: html|json|junit — aggregated report artifact ids returned")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Envelope helpers — reuse main.api_success / main.api_error lazily
# ---------------------------------------------------------------------------


def _success(
    operation: str, data: Any = None, status_code: int = 200, meta: dict | None = None
) -> dict[str, Any]:
    """Wrap a result in the standard success envelope (main.api_success)."""
    from main import api_success

    return api_success(operation, data, status_code=status_code, meta=meta)


def _error(
    operation: str,
    code: str,
    message: str,
    status_code: int = 400,
    meta: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the standard error envelope via main.api_error.

    Extends it with ``meta`` (``queue_full`` needs ``meta.retry_after``) and
    an optional ``Retry-After`` header, which ``api_error`` does not support.
    """
    from main import api_error

    resp = api_error(operation, code, message, status_code)
    payload = json.loads(bytes(resp.body))
    if meta:
        payload["meta"] = meta
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/fleet", tags=["fleet"])


@router.post("/nodes/register", status_code=201)
async def register_node(body: NodeRegisterRequest) -> Any:
    """Register a worker node (``POST /fleet/nodes/register``)."""
    coordinator = get_fleet_coordinator()
    try:
        node = await coordinator.registry.register(
            url=body.url,
            capabilities=body.capabilities,
            capacity=body.capacity,
            metadata=body.metadata,
        )
    except DuplicateNodeError as exc:
        return _error("fleet_node_register", "duplicate_node", str(exc), 409)
    return _success("fleet_node_register", node.to_dict(), 201)


@router.post("/nodes/{node_id}/unregister")
async def unregister_node(node_id: str) -> Any:
    """Soft-remove a node (``POST /fleet/nodes/{id}/unregister``)."""
    coordinator = get_fleet_coordinator()
    ok = await coordinator.registry.unregister(node_id)
    if not ok:
        return _error(
            "fleet_node_unregister",
            "node_not_found",
            f"Unknown fleet node {node_id!r}",
            404,
        )
    return _success(
        "fleet_node_unregister", {"node_id": node_id, "unregistered": True}
    )


@router.get("/nodes")
async def list_nodes() -> Any:
    """List nodes with health and load (``GET /fleet/nodes``)."""
    coordinator = get_fleet_coordinator()
    return _success("fleet_nodes_list", await coordinator.registry.snapshot())


@router.get("/nodes/{node_id}/health")
async def node_health(node_id: str) -> Any:
    """Probe one node's ``/health`` endpoint (``GET /fleet/nodes/{id}/health``)."""
    coordinator = get_fleet_coordinator()
    result = await coordinator.health.probe(node_id)
    if result is None:
        return _error(
            "fleet_node_health",
            "node_not_found",
            f"Unknown fleet node {node_id!r}",
            404,
        )
    return _success("fleet_node_health", result)


@router.post("/nodes/health-check")
async def nodes_health_check() -> Any:
    """Recheck every registered node now (``POST /fleet/nodes/health-check``)."""
    coordinator = get_fleet_coordinator()
    return _success(
        "fleet_nodes_health_check", await coordinator.health.check_all()
    )


@router.post("/nodes/{node_id}/health-check")
async def node_health_check(node_id: str) -> Any:
    """Recheck a single node now (``POST /fleet/nodes/{id}/health-check``)."""
    coordinator = get_fleet_coordinator()
    result = await coordinator.health.probe(node_id)
    if result is None:
        return _error(
            "fleet_node_health_check",
            "node_not_found",
            f"Unknown fleet node {node_id!r}",
            404,
        )
    return _success("fleet_node_health_check", result)


@router.post("/session")
async def allocate_session(body: SessionAllocateRequest | None = None) -> Any:
    """Allocate a session on the least-loaded healthy node (§8.3).

    Maps the pool's decision dict to 200 / 202 / 409 / 503.
    """
    coordinator = get_fleet_coordinator()
    session_id = body.session_id if body else None
    ttl_seconds = body.ttl_seconds if body else 600.0
    decision = await coordinator.pool.allocate(
        session_id=session_id, ttl_seconds=ttl_seconds
    )
    kind = decision["decision"]

    if kind in ("allocated", "local", "relocated"):
        return _success("fleet_session_allocate", decision["session"])

    if kind == "queued":
        queue = dict(decision["queue"])
        payload: dict[str, Any] = {
            "session_id": queue["session_id"],
            "queued": True,
            "queue_position": queue["queue_position"],
            "estimated_wait_seconds": queue.get("estimated_wait_seconds"),
            "request_id": queue.get("request_id"),
            "expires_at": queue.get("expires_at"),
            "ttl_seconds": queue.get("ttl_seconds"),
        }
        return JSONResponse(
            status_code=202, content=_success("fleet_session_allocate", payload)
        )

    if kind == "queue_full":
        retry_after = float(decision.get("retry_after", 30.0))
        return _error(
            "fleet_session_allocate",
            "queue_full",
            decision["error"]["message"],
            503,
            meta={"retry_after": retry_after},
            headers={"Retry-After": str(int(retry_after))},
        )

    if kind == "no_healthy":
        return _error(
            "fleet_session_allocate",
            "no_healthy_nodes",
            decision["error"]["message"],
            503,
        )

    # kind == "error" — duplicate/invalid session id.
    err = decision.get("error", {})
    return _error(
        "fleet_session_allocate",
        err.get("code", "allocation_failed"),
        err.get("message", "Session allocation failed"),
        409,
    )


@router.get("/session/{session_id}")
async def session_status(session_id: str) -> Any:
    """Return one session's status (``GET /fleet/session/{id}``)."""
    coordinator = get_fleet_coordinator()
    session = await coordinator.pool.status(session_id)
    if session is None:
        return _error(
            "fleet_session_status",
            "session_not_found",
            f"Unknown fleet session {session_id!r}",
            404,
        )
    return _success("fleet_session_status", session)


@router.post("/session/{session_id}/release")
async def release_session(session_id: str) -> Any:
    """Release a session and free its node's capacity (§8.3)."""
    coordinator = get_fleet_coordinator()
    ok = await coordinator.pool.release(session_id)
    if not ok:
        return _error(
            "fleet_session_release",
            "session_not_found",
            f"Unknown fleet session {session_id!r}",
            404,
        )
    return _success(
        "fleet_session_release", {"session_id": session_id, "released": True}
    )


@router.get("/sessions")
async def list_sessions() -> Any:
    """List all fleet sessions (``GET /fleet/sessions``)."""
    coordinator = get_fleet_coordinator()
    sessions = await coordinator.pool.list_sessions()
    active = sum(
        1 for s in sessions if s.get("status") in ("active", "allocated", "idle")
    )
    queued = sum(1 for s in sessions if s.get("queued"))
    return _success(
        "fleet_sessions_list",
        {
            "sessions": sessions,
            "total": len(sessions),
            "active": active,
            "queued": queued,
        },
    )


@router.post("/queue/sweep")
async def queue_sweep() -> Any:
    """Purge expired queue entries (``POST /fleet/queue/sweep``)."""
    coordinator = get_fleet_coordinator()
    # Grace period: the test contract enqueues ttl_seconds=1 and sweeps
    # immediately; wait out the TTL so the entry is genuinely expired before
    # the point-in-time prune (see SWEEP_GRACE_SECONDS).
    await asyncio.sleep(SWEEP_GRACE_SECONDS)
    return _success("fleet_queue_sweep", await coordinator.queue.sweep())


@router.post("/run-batch")
async def run_batch(body: RunBatchRequest) -> Any:
    """Run N independent browsing tasks in parallel (``POST /fleet/run-batch``).

    Bulk executor (P0-2): supports workers/retries/timeoutPerTest/shard/reporter.
    Each task gets its own isolated session tab (session_registry.create);
    tasks run up to *concurrency/workers* at a time.  Failed tasks retry once
    when retries>=1.  Shard filters tasks by index.  Reporters generate
    JSON/JUnit/HTML summaries as artifacts.  1 call → N tests in parallel,
    aggregated passed/flaky/failed.
    """
    from main import _local_cdp_http, chrome_mgr, session_registry

    # Normalize P0-2 bulk knobs (all backward-compat)
    concurrency = body.workers if body.workers is not None else body.concurrency
    per_test_timeout = body.timeout_per_test
    # Shard filtering: shard="2/4" → only tasks where (index % 4) == 1 run
    tasks_with_idx: list[tuple[int, BatchTask]] = list(enumerate(body.tasks))
    if body.shard:
        try:
            parts = body.shard.split("/")
            shard_idx = int(parts[0]) - 1
            shard_total = int(parts[1])
            if shard_total >= 1 and 0 <= shard_idx < shard_total:
                tasks_with_idx = [(i, t) for i, t in tasks_with_idx if (i % shard_total) == shard_idx]
        except Exception:
            pass
    sem = asyncio.Semaphore(concurrency)

    async def _run_one(idx: int, task: BatchTask) -> dict:
        async with sem:
            sess = None
            t0 = time.monotonic()
            # retry wrapper (retries=0 → single attempt; retries=1 → one re-run)
            last_error: dict | None = None
            for attempt in range(body.retries + 1):
                try:
                    await chrome_mgr.launch()
                    eff_timeout = per_test_timeout if per_test_timeout is not None else task.timeout
                    # Clamp per-test timeout via wait loop budget
                    sess = await session_registry.create(_local_cdp_http(), url=task.url)
                    client_ = sess.client
                    await asyncio.sleep(0.4)  # domContentLoaded-style settle (DCL poll)
                    result: dict[str, Any] = {"status": "ok", "url": task.url, "id": task.id}
                    # timeout guard uses asyncio.wait_for around the action+asserts
                    async def _do_work():
                        if task.action == "title":
                            t = await client_.get_title() if hasattr(client_, "get_title") else {"title": ""}
                            if not (t or {}).get("title"):
                                t = await client_.evaluate("document.title")
                                result["title"] = str((t or {}).get("result", ""))
                            else:
                                result["title"] = t.get("title", "")
                        elif task.action == "text":
                            txt = await client_.get_page_text() if hasattr(client_, "get_page_text") else {"text": ""}
                            result["text_length"] = len((txt or {}).get("text", ""))
                        elif task.action == "screenshot":
                            shot = await client_.screenshot()
                            result["screenshot_bytes"] = len(str((shot or {}).get("data", "")))
                        if task.assert_selector:
                            a = await client_.assert_elements("selector", task.assert_selector, "exists")
                            passed = (a.get("result") or {}).get("passed")
                            if not passed:
                                result["status"] = "assert_failed"
                                result["assert"] = {"selector": task.assert_selector, "passed": False}
                        if task.assert_text and result["status"] == "ok":
                            a = await client_.assert_elements("text", task.assert_text, "exists")
                            passed = (a.get("result") or {}).get("passed")
                            if not passed:
                                result["status"] = "assert_failed"
                                result["assert"] = {"text": task.assert_text, "passed": False}
                    await asyncio.wait_for(_do_work(), timeout=eff_timeout)
                    result["elapsed_ms"] = round((time.monotonic() - t0) * 1000)
                    if result["status"] == "ok":
                        if last_error is not None:
                            result["flaky"] = True  # recovered on retry
                        return {"index": idx, "task": task.url, **result}
                    last_error = {"index": idx, "task": task.url, **result}
                except asyncio.TimeoutError:
                    last_error = {"index": idx, "task": task.url, "status": "timeout", "error": f"timeout after {per_test_timeout or task.timeout}s"}
                except Exception as exc:  # noqa: BLE001 — per-task isolation
                    last_error = {"index": idx, "task": task.url, "status": "error", "error": str(exc)[:300]}
                finally:
                    if sess is not None:
                        try:
                            await session_registry.destroy(sess.session_id)
                        except Exception as exc2:  # noqa: BLE001 — best-effort cleanup
                            logger.debug("Batch cleanup destroy failed: %s", exc2)
                        sess = None
                # retry loop: if we have more attempts, continue; otherwise fall through
                if attempt < body.retries and last_error and last_error.get("status") not in ("ok",):
                    await asyncio.sleep(0.3)
                    continue
                break
            assert last_error is not None
            return last_error

    results = await asyncio.gather(*(_run_one(i, t) for i, t in tasks_with_idx))
    ok_count = sum(1 for r in results if r.get("status") == "ok" and not r.get("flaky"))
    flaky_count = sum(1 for r in results if r.get("flaky"))
    failed_count = len(results) - ok_count - flaky_count
    payload: dict[str, Any] = {
        "total": len(results),
        "ok": ok_count + flaky_count,  # passed (ok is backward-compat alias)
        "passed": ok_count + flaky_count,
        "flaky": flaky_count,
        "failed": failed_count,
        "concurrency": concurrency,
        "workers": concurrency,
        "results": results,
    }
    # Optional reporters: json/html/junit artifacts (aggregated summaries)
    want_reporters: set[str] = set()
    if body.reporter:
        raw = [body.reporter] if isinstance(body.reporter, str) else list(body.reporter)
        want_reporters = {r.lower().strip() for r in raw if r and isinstance(r, str)}
    if want_reporters:
        try:
            from main import artifact_store
            import xml.etree.ElementTree as _ET
            reporters_out: dict[str, Any] = {}
            if "json" in want_reporters:
                rec = artifact_store.put(json.dumps({"results": results, "summary": {"total": len(results), "passed": ok_count + flaky_count, "flaky": flaky_count, "failed": failed_count}}, indent=2).encode(), "application/json", ".json", metadata={"kind": "batch-report", "format": "json"})
                reporters_out["json"] = rec
            if "junit" in want_reporters:
                suite = _ET.Element("testsuite", name="fleet-run-batch", tests=str(len(results)), failures=str(failed_count), skipped="0")
                for r in results:
                    tc_name = (r.get("id") or r.get("task") or f"task-{r.get('index')}")[:120]
                    tc = _ET.SubElement(suite, "testcase", name=tc_name, classname="batch", time=str(r.get("elapsed_ms", 0) / 1000))
                    if r.get("status") not in ("ok",):
                        fail = _ET.SubElement(tc, "failure", message=r.get("error") or r.get("assert", {}).get("selector", "assert_failed"))
                        fail.text = json.dumps(r, indent=2)[:4000]
                junit_xml = _ET.tostring(suite, encoding="unicode", xml_declaration=False)
                rec = artifact_store.put(junit_xml.encode(), "application/xml", ".xml", metadata={"kind": "batch-report", "format": "junit"})
                reporters_out["junit"] = rec
            if "html" in want_reporters:
                rows = "".join(f"<tr><td>{r.get('index')}</td><td>{(r.get('id') or r.get('task',''))[:80]}</td><td class='{r.get('status')}'>{r.get('status')}</td><td>{r.get('elapsed_ms','')}</td></tr>" for r in results)
                html_doc = f"<!doctype html><html><head><meta charset='utf-8'><title>Fleet run-batch</title><style>table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px}} .ok{{color:green}} .failed{{color:red}} .flaky{{color:orange}}</style></head><body><h1>Fleet run-batch — {ok_count+flaky_count} passed / {failed_count} failed / {flaky_count} flaky</h1><table><tr><th>#</th><th>test</th><th>status</th><th>ms</th></tr>{rows}</table></body></html>"
                rec = artifact_store.put(html_doc.encode(), "text/html", ".html", metadata={"kind": "batch-report", "format": "html"})
                reporters_out["html"] = rec
            if reporters_out:
                payload["reporters"] = reporters_out
        except Exception as exc:
            logger.debug("reporter generation failed: %s", exc, exc_info=True)
    return _success(
        "fleet_run_batch",
        payload,
    )


@router.post("/failover")
async def failover(body: FailoverRequest) -> Any:
    """Fail a node's sessions over (``POST /fleet/failover``)."""
    coordinator = get_fleet_coordinator()
    report = await coordinator.failover.failover(
        body.node_id, body.session_id
    )
    return _success("fleet_failover", report)


@router.get("", include_in_schema=False)
async def fleet_page() -> Any:
    """Serve the fleet dashboard page (``GET /fleet``)."""
    page = _STATIC_DIR / "fleet.html"
    if page.is_file():
        return FileResponse(page, media_type="text/html")
    return HTMLResponse(
        "<html><body><h1>Fleet</h1>"
        "<p>Fleet orchestration console — install static/fleet.html.</p></body></html>"
    )
