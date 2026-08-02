# Architecture Brief: Distributed Browser Fleet Orchestration (v1.18.0)

> Status: **DESIGN** — produced by code-architect (t_397c3968), refines analysis-brief.md (t_ca117834).
> Target release: v1.18.0. The pre-tester (t_7db54f52) builds `tests/test_fleet_v118.py` against this spec.

## 1. Overview

Browser Helper is currently single-node: one FastAPI process wrapping a CDP client
that controls a single Chrome instance. The Fleet layer (v1.18.0) adds **distributed,
multi-node orchestration** so that a Browser Helper coordinator can manage a pool of
Browser Helper worker nodes, schedule sessions across them, queue when at capacity,
and fail over sessions on node loss.

The design reuses four existing patterns and introduces **no new dependencies** beyond
the Python stdlib (`sqlite3`, `httpx` already present):

| Existing pattern | Reused for |
|---|---|
| `api_success` / `api_error` response envelope | All Fleet API responses |
| `@app.middleware("http")` auth + `PUBLIC_PATHS` | Fleet dashboard page excluded from auth |
| `EnvironmentStore` / `WorkflowCatalog` atomic-write persistence | FleetSQLite WAL-mode writes |
| `HeadlessManager.SessionPool` (max_sessions / can_launch / active_count) | FleetSessionPool capacity model |
| `ProxyPool` async `health_check_async` | FleetHealthChecker probe pattern |
| `SessionManager.capture` / `restore` | Failover state transfer (cookies + localStorage + sessionStorage) |
| `static/index.html` workspace tabs + `static/dashboard_ux.js` | Fleet dashboard workspace extension |
| `httpx.ASGITransport(app=app)` + `AsyncClient` | Fleet API testing (test_fleet_v118.py) |

## 2. Module Structure

All fleet code lives under `src/fleet/` (no top-level src package collision — the
`conftest.py` already inserts `src/` on `sys.path`).

```
src/fleet/
  __init__.py          Package facade: exports FleetCoordinator, FleetSQLite
  storage.py           FleetSQLite: SQLite backend for nodes/sessions/queue
  node_registry.py     NodeRegistry: register/unregister, capacity, Node dataclass
  health_checker.py    FleetHealthChecker: async periodic health polling
  session_pool.py      FleetSessionPool: least-loaded allocation, capacity checks
  queue_manager.py     FleetQueueManager: FIFO queue, TTL, 503 + Retry-After
  failover.py          FailoverManager: state transfer on node failure
  api.py               FleetAPI: FastAPI APIRouter (7 endpoints — see §6)
  cli.py               CLI entry: `python -m fleet.cli node list`, `... session list`
  dashboard.py         FleetDashboard: renders /fleet HTML + static asset wiring
```

`src/main.py` changes (single integration point):

1. Import + instantiate the Fleet coordinator singleton:

   ```python
   from fleet import FleetCoordinator
   fleet = FleetCoordinator(db_path=Path.home() / ".browser-helper" / "fleet.db")
   ```

2. `app.include_router(fleet.api_router, prefix="/fleet", tags=["fleet"])`

3. Background task in `lifespan`: start `fleet.start()` (health poller) on startup,
   `fleet.stop()` on shutdown.

4. Add `"/fleet/dashboard"` and `"/static/fleet.css"` to `PUBLIC_PATHS`.

5. Bump `app.version` from `1.14.0` → `1.18.0` (sync with `pyproject.toml` `1.17.0` → `1.18.0`).

## 3. Component Responsibilities

### 3.1 FleetSQLite (`storage.py`)

Owned wrapper around `sqlite3.Connection` with `check_same_thread=False` (async-safe
via an internal `asyncio.Lock`). Creates the three tables from §4 on init. Exposes
typed CRUD methods used by the other components — `add_node`, `get_node`,
`update_node_health`, `list_healthy_nodes`, `add_session`, `get_session`,
`release_session`, `enqueue_request`, `dequeue_ready`, `prune_expired`, etc.

Design notes (matching `EnvironmentStore`/`WorkflowCatalog` conventions):

- `PRAGMA journal_mode=WAL` for concurrent read resilience.
- `PRAGMA foreign_keys=ON` so `fleet_sessions.node_id` → `fleet_nodes.node_id`
  cascades on unregister.
- Every write is wrapped in `with self._lock:` + `conn.commit()`.
- Timestamps stored as `REAL` epoch floats (like `ProxyEntry.last_checked`).
- JSON columns (`capabilities`, `metadata`, `saved_state`) stored as `TEXT` and
  round-tripped with `json.loads`/`json.dumps` — no new dependency.

### 3.2 NodeRegistry (`node_registry.py`)

Holds a `Node` dataclass mirroring `ProxyEntry`'s field style:

```python
@dataclass
class Node:
    node_id: str           # "node_<hex>"  (uuid hex prefix)
    url: str               # base URL, e.g. http://host:8000
    capabilities: list[str]  # ["cdp","screenshot",...]
    capacity: int          # max concurrent sessions
    active_sessions: int   # maintained via session allocate/release
    healthy: bool = True
    last_checked: float = 0.0
    last_error: str | None = None
    metadata: dict = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
```

`register(url, capabilities, capacity, metadata)` → generates ID, inserts, returns
`Node` dict. `unregister(node_id)` → soft-delete (marks `healthy=False`,
`active_sessions` forced to 0). `list()` / `get()` read from storage.
`active_count(node_id)` delegates to the sessions table.

### 3.3 FleetHealthChecker (`health_checker.py`)

Async poller spawned as a single `asyncio.Task` in `lifespan`. Iterates registered
nodes every `poll_interval_s` (default 15s, ±2s jitter to avoid herding) and does
`httpx.AsyncClient(timeout=5s).get(node.url + "/health")`. On HTTP 200, sets
`healthy=True`, records `last_checked` + latency. On failure (timeout/non-200),
sets `healthy=False`, records `last_error`, and triggers `FailoverManager` for any
sessions currently on that node. Mirrors `ProxyPool.health_check_async` signature.

Exposes `probe(node_id)` for the manual `GET /fleet/nodes/{id}/health` endpoint.

### 3.4 FleetSessionPool (`session_pool.py`)

Allocation policy: **least-loaded first, round-robin tie-break** — directly mirrors
`HeadlessManager.SessionPool.can_launch` / `active_count`. Given a request body
(`session_id?`, `ttl_seconds?`, `node_id?` for affinity):

1. Query healthy nodes sorted by `active_sessions ASC`.
2. If a requested `node_id` is given and healthy + under capacity → allocate there.
3. If no healthy node has capacity → delegate to `FleetQueueManager.enqueue()`.
4. Otherwise pick least-loaded, POST to that node's `/headless/launch` (or
   `/browser/launch`) to create the remote session, record the session in
   `fleet_sessions`, return `cdp_url` + `node_id`.

`release(session_id)` → marks session inactive in storage, decrements node
`active_sessions`, deletes the `fleet_sessions` row (or soft-marks `status='closed'`).

### 3.5 FleetQueueManager (`queue_manager.py`)

FIFO queue backed by `fleet_queue` table. `enqueue(session_id, ttl_seconds)` →
inserts row with `queue_position = max+1`, `expires_at = now + ttl`. Returns queue
position + `Retry-After` hint. `dequeue_ready(node_id)` → pops the lowest-position
non-expired request. `prune_expired()` removes rows past `expires_at`.

When queue is full (`fleet_queue` row count ≥ `max_queue`, default 100) the
`POST /fleet/session` endpoint returns **503** with `Retry-After` header (matching
Browserless' 3-tier model: concurrency → queue → 503).

### 3.6 FailoverManager (`failover.py`)

Triggered by the health checker when a node goes unhealthy with active sessions:

1. For each `active` session on the dead node: call `SessionManager.capture()`
   (via the coordinator's injected `_session_mgr` singleton) to snapshot cookies +
   localStorage + sessionStorage into `fleet_sessions.saved_state` (JSON).
2. Mark that session `status='failed'` and queue a re-allocation.
3. On the next healthy node with capacity: `SessionManager.restore()` to replay
   state, update `node_id`, `cdp_url`, `status='active'`.

The capture/restore calls reuse the *exact* `session_manager` singleton already
instantiated in `main.py` (`_session_mgr`), so the integration is a direct import —
no CDP client re-instantiation.

### 3.7 FleetAPI (`api.py`)

A `fastapi.APIRouter` mounted at `/fleet` in `main.py`. All endpoints use the
imported `api_success` / `api_error` helpers (passed in via a small dependency or
imported from the top-level module). See §6 for the full contract.

### 3.8 CLI (`cli.py`)

Thin `argparse` entry point invoked as `python -m fleet.cli`. Reads
`BROWSER_HELPER_URL` (default `http://localhost:8000`) and `API_TOKEN` from env,
calls the Fleet REST endpoints with `httpx`. Commands:

- `fleet node list` → `GET /fleet/nodes` → table of id/url/capacity/active/healthy
- `fleet session list` → `GET /fleet/sessions` → table of id/node/status/queued

### 3.9 Dashboard (`dashboard.py`)

Not a separate HTML file — extends the *existing* dashboard per the research brief:
adds a `<button data-workspace="fleet">Fleet</button>` to `#workspace-nav` in
`static/index.html`, adds a `data-workspace="fleet"` card section, and registers
handlers in `static/dashboard_ux.js` (fetch `/fleet/dashboard` summary, render nodes
/ sessions / queue as live cards, hook into the existing WebSocket
`browser-helper:telemetry` CustomEvent broadcast). New CSS lives in
`static/fleet.css` (mounted via the existing `/static` route).

## 4. SQLite Schema

File: `~/.browser-helper/fleet.db` (configurable via `FLEET_DB_PATH` env / coordinator
constructor arg — enables `tmp_path` injection in tests).

```sql
-- Nodes table: registered fleet worker nodes
CREATE TABLE IF NOT EXISTS fleet_nodes (
    node_id           TEXT PRIMARY KEY,        -- "node_<hex>"
    url               TEXT NOT NULL,           -- Base URL, e.g. http://192.168.1.100:8000
    capabilities      TEXT NOT NULL DEFAULT '[]',  -- JSON array string
    capacity          INTEGER NOT NULL DEFAULT 5,  -- Max concurrent sessions
    active_sessions   INTEGER NOT NULL DEFAULT 0,
    healthy           INTEGER NOT NULL DEFAULT 1,  -- 1 = healthy, 0 = unhealthy
    last_checked      REAL NOT NULL DEFAULT 0,   -- epoch timestamp
    last_error        TEXT,                     -- Last health error message
    metadata          TEXT,                     -- JSON: region, name, etc.
    registered_at     REAL NOT NULL,            -- epoch timestamp
    updated_at        REAL NOT NULL             -- epoch timestamp
);

-- Sessions table: active fleet sessions (across all nodes)
CREATE TABLE IF NOT EXISTS fleet_sessions (
    session_id        TEXT PRIMARY KEY,        -- "sess_<hex>"
    node_id           TEXT NOT NULL,           -- FK → fleet_nodes.node_id
    node_url          TEXT NOT NULL,           -- Denormalized for resilience
    cdp_url           TEXT,                    -- CDP WebSocket URL on the node
    status            TEXT NOT NULL DEFAULT 'active',  -- active|idle|queued|failed|closed
    queued            INTEGER NOT NULL DEFAULT 0,
    queue_position    INTEGER NOT NULL DEFAULT 0,
    allocated_at      REAL NOT NULL,           -- epoch timestamp
    last_used         REAL NOT NULL,           -- epoch timestamp
    expires_at        REAL NOT NULL,           -- TTL expiry (epoch)
    saved_state       TEXT,                    -- JSON: captured session state for failover
    FOREIGN KEY (node_id) REFERENCES fleet_nodes(node_id) ON DELETE SET NULL
);

-- Queue table: pending session allocation requests
CREATE TABLE IF NOT EXISTS fleet_queue (
    request_id        TEXT PRIMARY KEY,        -- "q_<hex>"
    session_id        TEXT NOT NULL,           -- Session to allocate
    requested_at      REAL NOT NULL,           -- epoch timestamp
    expires_at        REAL NOT NULL,           -- TTL (epoch)
    queue_position    INTEGER NOT NULL,        -- 0 = next to allocate
    ttl_seconds       REAL NOT NULL            -- Original TTL
);

-- Indexes for scheduling performance
CREATE INDEX IF NOT EXISTS idx_fleet_sessions_node ON fleet_sessions(node_id);
CREATE INDEX IF NOT EXISTS idx_fleet_sessions_status ON fleet_sessions(status);
CREATE INDEX IF NOT EXISTS idx_fleet_queue_pos ON fleet_queue(queue_position);
CREATE INDEX IF NOT EXISTS idx_fleet_queue_expires ON fleet_queue(expires_at);
```

**PRAGMA settings**: `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000ms`.

## 5. Data Flow & Lifecycle

```
  ┌────────────────┐   1.register   ┌──────────────┐
  │ Worker Node    │ ─────────────► │ NodeRegistry │
  │ (browser-helper│   (persist)    │ (SQLite)     │
  │  instance)     │                └──────┬───────┘
  └────────────────┘                       │
                           2. health poll  │
  ┌──────────────┐ ◄──────────────────────┘
  │ HealthChecker│   mark healthy/unhealthy
  └──────┬───────┘
         │ 3. unhealthy → trigger failover
         ▼
  ┌──────────────┐
  │ FailoverMgr  │── capture state (SessionMgr)
  └──────┬───────┘── re-allocate on healthy node
         │
  ┌──────▼──────────────────┐   4.allocate   ┌──────────────┐
  │ FleetSessionPool        │ ──────────────► │ node /headless│
  │ least-loaded            │   cdp_url       │  /launch     │
  └──────┬──────────────────┘                  └──────┬──────┘
         │ 5. at capacity                6. session active
         ▼                                                │
  ┌──────────────┐    7. release / queue drain            ▼
  │ QueueManager │ ─── dequeue_ready ─────────────────►  │
  └──────────────┘                                      ▼
                                                ┌─────────────┐
                                                │ CDP / WS to │
                                                │ browser     │
                                                └─────────────┘
```

**Lifespan wiring** (added to the existing `@asynccontextmanager lifespan`):

```python
# startup
fleet = FleetCoordinator(...)
fleet_task = asyncio.create_task(fleet.start())   # starts health poller + queue drainer

# shutdown
fleet_task.cancel()
await fleet.stop()
```

## 6. API Endpoint Specifications (Contracts)

All endpoints under `/fleet/`, mounted with `tags=["fleet"]`. Responses use the
`api_success` `/ `api_error` envelope:
`{"status":"ok"|"error","operation":str,"data":Any,"error":Any,"meta":dict}`.

### 6.1 POST /fleet/nodes/register

Register a worker node in the fleet.

**Request** (`201 Created`):
```json
{ "url": "http://192.168.1.100:8000", "capabilities": ["cdp","headless","screenshot"], "capacity": 10, "metadata": {"region":"us-east","name":"worker-1"} }
```
**Response (201)**:
```json
{ "status":"ok", "operation":"fleet_node_register", "data":{ "node_id":"node_abc123","url":"http://192.168.1.100:8000","capabilities":["cdp","headless","screenshot"],"capacity":10,"active_sessions":0,"healthy":true,"registered_at":"2026-08-02T12:00:00Z" }, "meta":{"node_id":"node_abc123"} }
```

### 6.2 POST /fleet/nodes/{node_id}/unregister

Remove a node from the fleet (drains to 0 active_sessions).

**Response (200)**: `{ "status":"ok","operation":"fleet_node_unregister","data":{"node_id":"node_abc123","unregistered":true} }`
**404** if not found.

### 6.3 GET /fleet/nodes/{node_id}/health

Probe the node's `/health` endpoint via httpx (on-demand, single probe).

**Response (200)**:
```json
{ "status":"ok","operation":"fleet_node_health","data":{ "node_id":"node_abc123","healthy":true,"latency_ms":12.3,"last_checked":"2026-08-02T12:00:00Z","node_status":{...} } }
```

### 6.4 POST /fleet/session

Allocate a session on the least-loaded healthy node.

**Request (optional)**: `{ "session_id":"sess_xyz789","ttl_seconds":300,"node_id":"node_abc123" }`
**Response**:
- `200` immediate: `{ "status":"ok","operation":"fleet_session_allocate","data":{ "session_id":"sess_xyz789","node_id":"node_abc123","node_url":"...","cdp_url":"ws://...","queued":false,"allocated_at":"..." } }`
- `202` queued: `{ "status":"ok","operation":"fleet_session_allocate","data":{ "session_id":"sess_xyz789","queued":true,"queue_position":2,"estimated_wait_seconds":45 } }`
- `503` queue full: `{ "status":"error","operation":"fleet_session_allocate","error":{"code":"queue_full","message":"Fleet queue is full"},"meta":{"retry_after":30} }` + `Retry-After: 30` header.

### 6.5 GET /fleet/session/{session_id}

**Response (200)**: `{ "status":"ok","operation":"fleet_session_status","data":{ "session_id":"...","node_id":"...","node_url":"...","status":"active","queued":false,"allocated_at":"...","last_used":"..." } }`
**404** if not found.

### 6.6 POST /fleet/session/{session_id}/release

Release a fleet session, decrementing node `active_sessions`.

**Response (200)**: `{ "status":"ok","operation":"fleet_session_release","data":{"session_id":"sess_xyz789","released":true} }`
**404** if not found.

### 6.7 GET /fleet/dashboard

Aggregated dashboard summary (served to the fleet workspace tab).

**Response (200)**:
```json
{ "status":"ok","operation":"fleet_dashboard","data":{ "nodes":[{...}],"sessions":[{...}],"queue":{...},"total_nodes":N,"healthy_nodes":M,"active_sessions":K,"queued_requests":Q } }
```

> Note: `GET /fleet/nodes` and `GET /fleet/sessions` are **additional** read-only
> list endpoints used by the CLI commands (§7) and the dashboard; they follow the
> same envelope. The 7 endpoints required by the task spec are 6.1–6.7.

## 7. CLI Commands

`python -m fleet.cli` (thin httpx wrapper — no new deps).

| Command | Underlying | Description |
|---|---|---|
| `fleet node list` | `GET /fleet/nodes` | Table: node_id / url / capacity / active / healthy / last_checked |
| `fleet session list` | `GET /fleet/sessions` | Table: session_id / node_id / status / queued / expires_at |

Env: `BROWSER_HELPER_URL` (default `http://localhost:8000`), `API_TOKEN` (optional
bearer). Uses the same `api_success` envelope shape as all REST responses.

## 8. Integration Points

| Fleet component | Existing module | Integration method |
|---|---|---|
| Health probe | `/health` (main.py L2174) | `httpx.AsyncClient.get(node.url + "/health")` — public, no auth |
| Session save | `SessionManager.capture` (L81) | `FailoverManager` calls `_session_mgr.capture(cdp_client, sid, url)` on a node |
| Session restore | `SessionManager.restore` (L140) | `FailoverManager` calls `_session_mgr.restore(cdp_client, state)` on destination node |
| API response format | `api_success`/`api_error` (L790, L797) | `FleetAPI` router imports these from the top-level module |
| Auth middleware | `auth_middleware` (L771) + `PUBLIC_PATHS` (L93) | Add `"/fleet/dashboard"`, `"/static/fleet.css"` to `PUBLIC_PATHS` |
| Auth-protected endpoints | Bearer token check | `POST /fleet/nodes/register`, `POST /fleet/session` etc. require `Authorization: Bearer <token>` |
| Dashboard pattern | Workspace tabs (index.html L293–300) | Add `<button data-workspace="fleet">` + `data-workspace="fleet"` card |
| WebSocket telemetry | `broadcast_state()` (L865) | `state` dict extended with `fleet` key; existing `browser-helper:telemetry` CustomEvent picks it up |
| Persistence pattern | `ProxyPool._save_atomically` (L100+, atomic tempfile+replace) | `FleetSQLite` uses WAL mode + `asyncio.Lock` |
| SessionPool capacity | `HeadlessManager.SessionPool.can_launch` (L125) | `FleetSessionPool` mirrors `active_count < capacity` check |
| TestClient pattern | `tests/test_headless_api.py`, `tests/test_proxy_api.py` | `httpx.ASGITransport(app=app)` + `AsyncClient` |

## 9. Integration Diagram

```
                       Browser Helper v1.18.0 (coordinator)
                            src/main.py + src/fleet/
                   ┌──────────────────────────────────────────────┐
                   │  FastAPI app (router mounted at /fleet)      │
                   │  PUBLIC_PATHS += /fleet/dashboard            │
                   │  lifespan: start HealthChecker + QueueMgr    │
                   │                                              │
                   │  ┌────────────┐  ┌───────────┐  ┌─────────┐ │
            register    NodeRegistry   HealthChk    SessionPool│ │
          ───────────►   (SQLite)      (httpx poll) (least-load)   │
                   │        ▲               │              │      │
                   │        │ updates       │ unhealthy    │      │
                   │  ┌─────┴──────┐  ┌──────┴──────┐     │      │
                   │  │ FleetSQLite│  │FailoverMgr│◄────┘      │
                   │  │ (fleet.db) │  │(SessionMgr)│                │
                   │  └─────┬──────┘  └───────────┘                │
                   │        │                                      │
                   │  ┌─────▼────────┐                              │
                   │  │ FleetAPI     │  (7 endpoints + 2 list)      │
                   │  │ (APIRouter)  │                              │
                   │  └──────────────┘                              │
                   │                                              │
                   │  ┌────────────┐  ┌─────────┐  ┌──────────┐   │
                   │  │ FleetCLI   │  │FleetDash│  │dashboard │   │
                   │  │ (argparse) │  │ (render)│  │ exts     │   │
                   │  └────────────┘  └─────────┘  └──────────┘   │
                   └──────────────────────────────────────────────┘
                           │            │         │        │
                   ┌───────┼────────────┼─────────┼────────┼──────┐
                   ▼       ▼            ▼         ▼        ▼      │
               Worker    Worker      Worker   Static   WS broadcast
               node A    node B      node C   files   browser-helper:
               (8000)    (8001)      (8002)  (index,  telemetry event
                                             fleet.css,
                                             dashboard_ux.js)

Existing:  /health  /session/save  /session/restore  → reused by fleet
           api_success / api_error envelope          → reused by fleet API
           ProxyPool atomic-write pattern            → adapted (SQLite WAL)
           HeadlessManager.SessionPool capacity model → mirrored by FleetSessionPool
```

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SQLite write contention under concurrent async access | Medium | Medium | WAL mode + `asyncio.Lock` in `FleetSQLite`; single writer per coordinator |
| Health-poll thundering herd on large fleets | Low | Medium | ±2s jitter on per-node poll interval; `httpx` 5s timeout per probe |
| Failover state transfer races (capture then restore while node flaps) | Low | High | Mark session `status='failed'` immediately on node loss; re-allocation is idempotent on `session_id` |
| Queue deadlock if no node ever frees capacity | Low | High | TTL expiry (`prune_expired`) + 503 when `fleet_queue` ≥ `max_queue`; drainer task runs every 2s |
| Dashboard WebSocket broadcast overload | Low | Medium | Fleet state folded into existing `state` dict; existing `broadcast_state()` throttling reused |
| Version drift (`app.version` vs `pyproject.toml`) | Low | Low | Bump both to `1.18.0` in the same PR |
| Pre-tester expects endpoints not in this brief | Low | Medium | This brief lists **all 7 required** + 2 list endpoints + `GET /fleet/nodes` + `GET /fleet/sessions`; CLI commands map 1:1 to those list endpoints |

## 11. Testing Contract (for pre-tester t_7db54f52)

Tests live in `tests/test_fleet_v118.py`, using the repo's established patterns
(`conftest.py` adds `src/` to `sys.path`; `@pytest.mark.quick` / `@pytest.mark.integration`;
`httpx.ASGITransport(app=app)` + `AsyncClient`).

`FleetCoordinator` constructor accepts a `db_path` argument so tests inject
`tmp_path / "fleet.db"` — the same injectable-path pattern used by `EnvironmentStore(path=...)`.

Test groups (29 tests — see analysis-brief.md §7 for the per-test breakdown):

1. **TestNodeRegistry** (6) — register, duplicate-key error, unregister, unregister-nonexistent, capabilities, node_id format
2. **TestHealthChecking** (5) — on-demand probe, unknown-node 404, poller marks unhealthy, unhealthy excluded from allocation, recovery marks healthy
3. **TestSessionPool** (5) — allocate, least-loaded, round-robin fallback, status, release
4. **TestQueueing** (4) — queue-when-full, 503-when-queue-full, TTL-expiry, Retry-After header
5. **TestFailover** (3) — failover on node failure, state transferred via save/restore, retry on healthy node
6. **TestDashboard** (2) — `/fleet/dashboard` served, fleet workspace in nav
7. **TestCLI** (2) — `node list` / `session list` output
8. **TestDocs** (2) — README has fleet section, CHANGELOG has v1.18.0 entry

All tests use the `api_success`/`api_error` envelope assertions: check
`result["status"] == "ok"` and `result["operation"] == "..."`.

## 12. Version & Release Notes

- **Target version**: v1.18.0
- `pyproject.toml`: `1.17.0` → `1.18.0`
- `src/main.py`: `app.version` `"1.14.0"` → `"1.18.0"`
- `Dockerfile` LABEL: `1.17.0` → `1.18.0`
- Commit message: `feat(fleet): distributed browser fleet orchestration — node registry, session pool, queue, failover, dashboard`
- `CHANGELOG.md` `[Unreleased]` → `[1.18.0]` section with fleet feature block
- Tag: `v1.18.0`
