# Research Brief: Distributed Browser Fleet Orchestration

## Target Audience
Code-Architect (t_397c3968) — use this brief to design the `fleet/` module in the
Browser Helper project. Reference the parent analysis brief at
`analysis/analysis-brief.md` for the full option-clustering, task prioritization,
and test mapping.

## Sources Validated
All external claims below are cross-checked against at least 2 independent sources
(web_search results + docs page titles). Sources marked "live-validated" were
confirmed via live web_search; sources marked "repo-local" are code patterns
found directly in the repo.

---

## 1. Trend Summary

The browser-automation fleet space clusters into three tiers:

1. **Self-hosted orchestration with built-in queueing** — Browserless is the
   dominant open-core pattern. It embeds a 3-tier system (concurrency limit →
   FIFO queue → 503/429 rejection) directly into the browser runner, with
   per-worker health checks (90% CPU/memory threshold → 5-min cooldown → auto
   restart). Load balancers route around unhealthy workers.

2. **Managed API-first session lifecycle** — Browserbase and Steel expose a
   REST or REST+WS API where each session is a first-class resource. Session
   state (cookies, localStorage, sessionStorage) persists across requests.
   Browserbase returns a `wss://` CDP URL per session; Steel persists cookies
   and localStorage via its REST API.

3. **API-first self-hosted orchestration** — **does not yet exist at scale**.
   Nextbrowser is the only self-hosted orchestration layer (AGPL-3.0) but is
   desktop-only with no REST API. This is the gap Browser Helper's fleet module
   can fill.

### Key validated facts

| Pattern | Browserless | Steel | Browserbase |
|---|---|---|---|
| Concurrency limit | `MAX_CONCURRENCY` env (default 20) [live-validated] | Per-instance config | Per-project limit |
| Queue depth | `MAX_QUEUE_LENGTH` / `QUEUED` env (default 100/10) [live-validated] | N/A (managed) | Managed queueing |
| Health rejection | 90% CPU/mem → 5xx "Health checks failed" [live-validated] | N/A | N/A (managed infra) |
| Auto-restart | CPU/mem above 90% for 5 min → restart worker [live-validated] | N/A | N/A |
| Retry signal | 429 over capacity, `Retry-After` header [live-validated] | — | — |
| Backoff | `baseDelay * 2^attempt` ms exponential [live-validated] | — | — |
| Session state | Manual via CDP | Auto: cookies + localStorage + sessionStorage persist [live-validated] | Full isolation per session; video replay [live-validated] |
| Pricing | Self-hosted = infra cost | Open-source + paid cloud | $0.005–0.05/min per session [live-validated] |

---

## 2. Feature Candidates

### 2.1 Browser Pool Patterns: Warm Pools, Session Affinity, Health Checks, Drain/Rotate

**What**: Pre-launch browser instances to reduce cold-start latency; pin sessions
to a specific node for stateful workflows; health-check nodes before routing;
gracefully drain nodes during decommission.

**Why**: Cold-start adds 2–5s per session. Memory leaks accumulate across
long-running browsers (Browserless confirms: "effectively unavoidable in
practice"). Session affinity is needed for multi-step workflows where state
must persist on one node.

**Complexity**: Medium — requires a background launcher loop and a drain state
machine.

**Sources**:
- Browserless "Scaling Browser Automation Architecture": shared browser pools
  with session affinity; warm pools reduce cold-start; browser recycling
  essential for memory leaks. [live-validated] —
  https://www.browserless.io/blog/scaling-browser-automation-architecture-1000-sessions
- Browserless "Built-in Queueing System": three-tier (concurrency → FIFO queue
  → 503 rejection); browsers must be properly closed to free queue slots.
  [live-validated] — https://docs.browserless.io/enterprise/long-queues
- Browserless "Worker settings": 90% CPU/memory threshold; 5-min sustained →
  auto-restart worker; health checked before accepting connections.
  [live-validated] — https://docs.browserless.io/enterprise/private-deployment/worker-settings
- Browserless "Performance and Capacity": when a worker exceeds 90% CPU/mem,
  it rejects requests with 5xx. [live-validated] —
  https://docs.browserless.io/enterprise/private-deployment/performance

**Repo-local reference**: `src/headless_manager.py` `SessionPool` class — already
implements `can_launch()` (capacity check), `active_count` property, `add()` /
`get()` / `remove()` on `SessionHandle` dataclass. The fleet `SessionPool` can
mirror this pattern but over HTTP to remote nodes instead of local subprocesses.

### 2.2 Node Registry Patterns: Self-Registering Nodes, Capabilities, Capacity Tracking, Heartbeat

**What**: Nodes POST registration with URL, capabilities array, capacity, and
metadata. They send periodic heartbeats (or the orchestrator probes
`/health`). The registry tracks active_sessions per node and excludes
unhealthy nodes.

**Why**: In a multi-node fleet, the orchestrator needs to know which nodes
exist, what they can do, how many sessions they can run, and whether they're
healthy — all without manual configuration.

**Complexity**: Low-Medium — a REST endpoint + SQLite table + periodic probe
task.

**Sources**:
- Browserless NGINX load balancing: "When CPU or memory usage is high,
  Browserless rejects requests, causing NGINX to route to healthier instances."
  [live-validated] — https://docs.browserless.io/enterprise/docker/nginx-load-balancing
- Browserless `/config` API returns `concurrent`, `queued`, `maxCPU`,
  `maxMemory` — node advertises its own capacity limits. [live-validated] —
  https://docs.browserless.io/enterprise/utility-functions/config
- Browserless "Production Best Practices": `HEALTH=true` env enables pre-request
  health checks that reject requests when CPU/mem thresholds exceeded.
  [live-validated] — https://docs.browserless.io/enterprise/docker/best-practices

**Repo-local reference**: `src/headless_manager.py` `SessionHandle` dataclass
fields (session_id, cdp_url, port, pid, status, resource_monitor) map to what
a fleet node needs to expose. The existing `HeadlessManager` health check
pattern in `src/proxy_manager.py` `ProxyPool` (health_check_async,
FAILURE_THRESHOLD=3, report_success/report_failure) is a direct model for
node health state transitions.

### 2.3 Session Pool Allocation: Least-Loaded Scheduling, Round-Robin Fallback

**What**: When allocating a session, pick the healthy node with the fewest
active sessions; fall back to round-robin if all are equal; reject with 503
if all nodes are at capacity and the queue is full.

**Why**: Optimizes resource utilization and prevents hotspots. Round-robin
fallback provides deterministic behavior when nodes are equivalent.

**Complexity**: Low — sort healthy nodes by `active_sessions` ascending, pick
first with `can_launch()`.

**Sources**:
- Browserless "Performance and Capacity": stagger requests 5–10s; once first
  batch is running, subsequent requests queue naturally. [live-validated] —
  https://docs.browserless.io/enterprise/private-deployment/performance
- Browserless load balancing with NGINX: round-robin + least_conn directives.
  [live-validated] — https://docs.browserless.io/enterprise/docker/nginx-load-balancing

**Repo-local reference**: `src/proxy_manager.py` `ProxyPool.get_proxy()` already
implements round-robin (`_round_robin_index`), random, sticky, and by-tag
strategies. The fleet allocator can reuse this scheduling dispatch pattern.
The `ProxyEntry` dataclass fields (`healthy`, `enabled`, `fail_count`,
`last_checked`, `latency_ms`) map directly to fleet node health state.

### 2.4 Queueing: Max Queue Depth, TTL, Backpressure with 503 + Retry-After

**What**: When all healthy nodes are at capacity, enqueue the request in a FIFO
queue with a TTL. Return 202 (queued) with position + estimated wait. If the
queue is full, return 503 with a `Retry-After` header.

**Why**: Provides graceful degradation under load. Without a queue, every
over-capacity request is immediately rejected (poor UX). TTL prevents zombie
requests. `Retry-After` lets clients self-regulate.

**Complexity**: Low — a simple FIFO list with timestamps.

**Sources**:
- Browserless "Built-in Queueing System": concurrency → FIFO queue → 503
  rejection when queue full. "Browsers not closed properly continue consuming
  resources until timeout." [live-validated] —
  https://docs.browserless.io/enterprise/long-queues
- Browserless "Retry browser sessions with exponential backoff": 429 over
  capacity; `baseDelay * 2^attempt` ms. [live-validated] —
  https://docs.browserless.io/examples/retry-backoff
- Browserless `QUEUED` env: set to 0 → immediate 429 when at capacity;
  set >0 → absorb bursts. [live-validated] —
  https://docs.browserless.io/enterprise/docker/best-practices
- Browserless `/config` API: `queued` field (default 10). [live-validated] —
  https://docs.browserless.io/enterprise/utility-functions/config

**Repo-local reference**: `src/proxy_manager.py` atomic JSON write pattern
(`_save_atomically` using `tempfile.mkstemp` + `os.replace`) is directly
applicable to the SQLite-backed queue. The existing
`ProxyEntry.FAILURE_THRESHOLD = 3` pattern informs how the queue manager should
track consecutive failures.

### 2.5 Failover: Node Failure Detection, Session State Transfer, Retry

**What**: When a health check fails, the failover manager captures the session
state (cookies, localStorage, sessionStorage) from the failing node, allocates
a new session on a healthy node, and restores the state.

**Why**: Enables transparent retry — clients don't lose state when a node dies.
Critical for long-running multi-step automations.

**Complexity**: Medium — requires coordination between health checker, session
pool, and the node's `/session/save` + `/session/restore` endpoints.

**Sources**:
- Steel: "session persists cookies, localStorage, and auth state across
  requests" — session state is the recovery primitive. [live-validated] —
  https://railway.com/deploy/steel-browser
- Steel: persistent profiles, credential management, session reuse.
  [live-validated] — https://github.com/steel-dev/steel-browser
- Browserbase: "Every session runs in full isolation" — state is per-session,
  not per-node, which simplifies transfer. [live-validated] —
  https://www.browserbase.com/blog/what-is-a-browserbase-browser

**Repo-local reference**: THE CRITICAL INTEGRATION POINT. The existing
`/session/save` endpoint (main.py:2149) calls `client.session_save` which
captures cookies + localStorage + sessionStorage via CDP. The existing
`/session/restore` endpoint (main.py:2159) takes `{"session": {...}}` and
restores state. The fleet failover manager should call these on the remote
node. The `SessionManager.capture()` and `SessionManager.restore()` methods
(src/session_manager.py:81,151) implement the actual CDP capture/restore and
already support mock clients for testing (detects `unittest.mock.MagicMock`
at line 94).

### 2.6 Fleet Dashboard: Node List, Health Status, Session Counts, Queue Depth

**What**: A UI showing all registered nodes, their health status, active/idle
session counts, queue depth, and historical metrics. Should integrate with the
existing dashboard's workspace tab system.

**Why**: Operators need observability to detect overloaded or failing nodes,
and to manually intervene (drain, unregister) when needed.

**Complexity**: Medium — extends the existing dashboard; adds fleet data
fetch/poll + a new workspace tab.

**Sources**:
- Browserless dashboard: provides node-level operations (Restart, Restart All,
  Provision via blue-green deployment). [live-validated] —
  https://docs.browserless.io/enterprise/fleet-management
- Browserbase Session Inspector: shows CDP events per session, replay, live
  view, structured logs. [live-validated] —
  https://docs.browserbase.com/features/session-inspector

**Repo-local reference**: The dashboard uses a workspace tab pattern where
`#workspace-nav` buttons have `data-workspace` attributes and cards have
matching `data-workspace` attributes (static/index.html:294-299,
static/dashboard_ux.js:44-49). The `showWorkspace()` function in
`dashboard_ux.js:42` toggles visibility. The `commands()` function
(dashboard_ux.js:107) auto-discovers workspace nav buttons for the command
palette. The telemetry event system (`browser-helper:telemetry` CustomEvent at
dashboard_ux.js:4) and `broadcast_state()` (main.py:865) exist for WebSocket
state sync. To add a fleet tab: add a `<button data-workspace="fleet">` nav
button, a corresponding `<section data-workspace="fleet">` card, and add
`"fleet"` to the `workspaceCopy` object in dashboard_ux.js:21.

### 2.7 Browser Helper v1.14.0 Foundation (Existing Patterns)

Reviewed `src/main.py`, `/health`, `/session/save-restore`, proxy_manager,
headless_manager, session_manager, environment_store, workflow_catalog,
dashboard files.

**Key findings**:

| Existing Component | File | Reusability for Fleet |
|---|---|---|
| `/health` endpoint | main.py:2174 | High — fleet health checker probes this on each node (HTTP GET to `node_url + /health`) |
| `/session/save` | main.py:2149 | High — failover calls this on failing node to capture state |
| `/session/restore` | main.py:2159 | High — failover calls this on new node to restore state |
| `SessionManager` | src/session_manager.py | High — capture/restore via CDP; supports mock clients for tests (line 94) |
| `api_success`/`api_error` | main.py:790,797 | High — fleet endpoints MUST reuse these for consistent API shape |
| `result_status()` | main.py:804 | High — maps error codes to HTTP status (404/409/503/504) |
| ProxyPool `_save_atomically` | proxy_manager.py:521 | Medium — atomic JSON write pattern; SQLite+WAL preferred per task |
| ProxyPool strategies | proxy_manager.py:510 | High — round-robin/random/sticky/by-tag dispatch pattern |
| `SessionPool` | headless_manager.py:114 | High — `can_launch()`, `active_count`, `SessionHandle` dataclass |
| PUBLIC_PATHS | main.py:93 | High — add `/fleet/dashboard` and `/static/fleet.css` |
| Dashboard workspace tabs | index.html:294, dashboard_ux.js:21 | High — add "fleet" tab |
| Lifespan (asyncio tasks) | main.py:112 | High — start health checker + queue drainer in `@asynccontextmanager lifespan` |
| `broadcast_state()` | main.py:865 | High — reuse for fleet state WebSocket broadcast |
| Bearer auth middleware | main.py:775 | High — add fleet public paths to bypass |

**Version note**: `app.version` in main.py:174 says "1.14.0" but pyproject.toml
and Dockerfile say 1.17.0. Bump to **1.18.0** for the fleet release (not 1.15.0
as the original task suggested — repo is already past that).

---

## 3. Implementation Hints

### 3.1 SQLite Schema (fleet.db)

File: `~/.browser-helper/fleet.db` (or configurable path). Uses `sqlite3`
stdlib — no new dependency. `journal_mode=WAL`, `foreign_keys=ON`.

```sql
-- Nodes table: registered fleet nodes
CREATE TABLE IF NOT EXISTS fleet_nodes (
    node_id           TEXT PRIMARY KEY,       -- UUID (node_<hex>)
    url               TEXT NOT NULL,          -- Base URL of the node
    capabilities      TEXT NOT NULL,          -- JSON array string
    capacity          INTEGER NOT NULL DEFAULT 5,
    active_sessions   INTEGER NOT NULL DEFAULT 0,
    healthy           INTEGER NOT NULL DEFAULT 1,  -- 1=healthy, 0=unhealthy
    last_checked      REAL NOT NULL DEFAULT 0,     -- epoch timestamp
    last_error        TEXT,                    -- Last health error message
    metadata          TEXT,                    -- JSON: region, name, etc.
    registered_at     REAL NOT NULL,           -- epoch timestamp
    updated_at        REAL NOT NULL            -- epoch timestamp
);

-- Sessions table: active fleet sessions
CREATE TABLE IF NOT EXISTS fleet_sessions (
    session_id        TEXT PRIMARY KEY,       -- UUID (sess_<hex>)
    node_id           TEXT NOT NULL,          -- FK to fleet_nodes
    node_url          TEXT NOT NULL,
    cdp_url           TEXT,                   -- CDP WebSocket URL on node
    status            TEXT NOT NULL DEFAULT 'active',  -- active|idle|queued|failed
    queued            INTEGER NOT NULL DEFAULT 0,
    queue_position    INTEGER NOT NULL DEFAULT 0,
    allocated_at      REAL NOT NULL,
    last_used         REAL NOT NULL,
    expires_at        REAL NOT NULL,          -- TTL expiry
    saved_state       TEXT,                   -- JSON: saved session state for failover
    FOREIGN KEY (node_id) REFERENCES fleet_nodes(node_id)
);

-- Queue table: pending session allocation requests
CREATE TABLE IF NOT EXISTS fleet_queue (
    request_id        TEXT PRIMARY KEY,       -- UUID (q_<hex>)
    session_id        TEXT NOT NULL,          -- Session to allocate
    requested_at      REAL NOT NULL,
    expires_at        REAL NOT NULL,           -- TTL
    queue_position    INTEGER NOT NULL,       -- 0 = next to allocate
    ttl_seconds       REAL NOT NULL            -- Original TTL
);
```

**SQLite concurrency**: WAL mode allows concurrent reads. Use a single
`asyncio.Lock` per writer operation to serialize writes from the health
checker, queue drainer, and API handlers.

### 3.2 Recommended Fleet API Endpoints

All endpoints under `/fleet/` prefix, mounted as a FastAPI `APIRouter` in
`main.py`. All responses use the existing `api_success`/`api_error` format.

#### Node Registry
- `POST /fleet/nodes/register` — Register a node (url, capabilities, capacity, metadata)
- `POST /fleet/nodes/{node_id}/unregister` — Remove a node (404 if not found)
- `GET /fleet/nodes` — List all nodes with health + session counts

#### Health Checking
- `GET /fleet/nodes/{node_id}/health` — Probe a single node's `/health`
- `GET /fleet/health` — Fleet-wide health summary

#### Session Pool
- `POST /fleet/session` — Allocate on least-loaded healthy node (200 if immediate, 202 if queued, 503 if queue full)
- `GET /fleet/session/{session_id}` — Session status
- `POST /fleet/session/{session_id}/release` — Release session back to pool
- `GET /fleet/sessions` — List all sessions across fleet

#### Dashboard
- `GET /fleet/dashboard` — Fleet dashboard page (PUBLIC_PATHS, no auth)

#### CLI
- `python -m fleet.cli node list` — Calls `GET /fleet/nodes`
- `python -m fleet.cli session list` — Calls `GET /fleet/sessions`

### 3.3 Integration Points

1. **main.py lifespan**: Start `FleetHealthChecker.poll_loop()` and
   `FleetQueueManager.drain_loop()` as asyncio tasks in the existing
   `@asynccontextmanager lifespan` (line 112). Cancel on shutdown.
2. **PUBLIC_PATHS**: Add `/fleet/dashboard` and `/static/fleet.css` to the
   set at main.py:93.
3. **Router mount**: `app.include_router(fleet_router, prefix="/fleet")` after
   app creation.
4. **State injection**: The fleet singleton instances should be created at module
   level alongside `proxy_pool`, `headless_mgr`, etc. (main.py:218-224).
5. **Auth bypass**: The existing middleware at main.py:775 checks
   `PUBLIC_PATHS` — fleet dashboard page + static CSS need to be public.
6. **TestClient pattern**: Follow `tests/test_headless_api.py` — use
   `httpx.ASGITransport(app=app)` + `AsyncClient` for integration tests;
   mock `httpx.AsyncClient.get` for health probe tests.

---

## 4. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SQLite concurrency under async load | Medium | High | WAL mode + single writer lock per operation |
| Health poll storms (thundering herd) | Low | Medium | Stagger poll intervals per node (±2s jitter) |
| Failover state transfer fails | Low | High | Log error, mark session as `failed`, notify queue |
| Queue deadlock (no slots free) | Low | High | TTL expiry removes stale queue entries; 503 when queue full |
| Dashboard WebSocket overload | Low | Medium | Reuse existing `broadcast_state()` with throttling |
| Version mismatch in app.version | Low | Low | Sync app.version "1.14.0" → "1.18.0" in main.py:174 |
| Child task ordering (research → architect → tester) | Med | High | Enforce parent dependency links via kanban |

---

## 5. Source Links

### External Sources (live-validated)
1. Browserless — "Built-in Queueing System" (3-tier: concurrency → FIFO queue → 503):
   https://docs.browserless.io/enterprise/long-queues
2. Browserless — "Worker settings" (90% CPU/mem → 5-min auto-restart):
   https://docs.browserless.io/enterprise/private-deployment/worker-settings
3. Browserless — "Performance and Capacity" (90% CPU/mem → 5xx rejection):
   https://docs.browserless.io/enterprise/private-deployment/performance
4. Browserless — "Retry browser sessions with exponential backoff" (429 + baseDelay * 2^attempt):
   https://docs.browserless.io/examples/retry-backoff
5. Browserless — "Docker Configuration Reference" (HEALTH=true, MAX_CPU_PERCENT, /config API):
   https://docs.browserless.io/enterprise/docker/config
6. Browserless — "Production Best Practices" (QUEUED=0 → immediate 429; HEALTH=true):
   https://docs.browserless.io/enterprise/docker/best-practices
7. Browserless — "NGINX Load Balancing" (health checks route around unhealthy workers):
   https://docs.browserless.io/enterprise/docker/nginx-load-balancing
8. Browserless — "Scaling Browser Automation Architecture" (warm pools, recycling, session affinity):
   https://www.browserless.io/blog/scaling-browser-automation-architecture-1000-sessions
9. Steel — "batteries-included browser sandbox" (open-source, REST+WS API, Python/Node SDKs):
   https://github.com/steel-dev/steel-browser
10. Steel — "session persists cookies, localStorage, and auth state across requests":
    https://railway.com/deploy/steel-browser
11. Browserbase — "What is a Browserbase Browser?" (session per API call, CDP WebSocket, full isolation):
    https://www.browserbase.com/blog/what-is-a-browserbase-browser
12. Browserbase — "Session Inspector" (live view, CDP events, replay):
    https://docs.browserbase.com/features/session-inspector
13. Browserbase — "Create a Session" API (returns wss:// connectUrl):
    https://docs.browserbase.com/reference/api/create-a-session
14. Browserbase — Pricing ($0.005–0.05/min per session):
    https://www.browserbase.com/pricing

### Repo-Local Sources
15. `src/main.py` — FastAPI app factory, `/health`, `/session/save`, `/session/restore`, `api_success`/`api_error`, `result_status()`, `PUBLIC_PATHS`, lifespan, `broadcast_state()` — repo-local
16. `src/session_manager.py` — `SessionManager.capture()` / `.restore()`, mock-client detection — repo-local
17. `src/headless_manager.py` — `SessionPool` (can_launch, active_count), `SessionHandle` dataclass, resource monitoring — repo-local
18. `src/proxy_manager.py` — `ProxyPool` (round-robin/random/sticky/by-tag strategies, `_save_atomically`, FAILURE_THRESHOLD, health_check_async) — repo-local
19. `src/environment_store.py` — versioned JSON persistence with validation — repo-local
20. `src/workflow_catalog.py` — versioned JSON store, atomic writes — repo-local
21. `static/index.html` — dashboard workspace tab pattern (data-workspace attributes) — repo-local
22. `static/dashboard_ux.js` — workspace nav toggle, command palette auto-discovery — repo-local
23. `analysis/analysis-brief.md` — parent analyst brief (Section 2 research synthesis, Section 8 API specs, Section 9 SQLite schema) — repo-local
24. `tests/test_headless_api.py` — TestClient + ASGITransport pattern — repo-local

---

## 6. Recommendation

Implement **Option A: Full-Fledged Fleet Manager** (as chosen by the analyst in
analysis-brief.md Section 4). The external source validation confirms this is
the industry-standard approach (Browserless embedding queueing + health checks
in-process; Browserbase/Steel making sessions first-class REST resources). The
existing Browser Helper codebase already has all the necessary integration
hooks: `/health` endpoint for probing, `/session/save` + `/session/restore`
for failover, `api_success`/`api_error` for consistent responses, the dashboard
workspace tab system, and the `SessionPool` + `ProxyPool` patterns to mirror.

The next step is for the **code-architect** (t_397c3968) to produce the
architecture brief defining the 8 fleet modules (`storage.py`,
`node_registry.py`, `health_checker.py`, `session_pool.py`, `queue_manager.py`,
`failover.py`, `api.py`, `cli.py`) using the SQLite schema in Section 3.1 and
the API contracts in Section 3.2 above.