# Analysis Brief: Distributed Browser Fleet Orchestration

## 1. Current State Assessment

### 1.1 Project Overview
Browser Helper (/home/zoltan/browser-helper) is a FastAPI-based remote Chrome
control proxy with REST API + GUI dashboard. It wraps a CDP client and provides
HTTP/WS endpoints for browser automation. Current version in `pyproject.toml`
and Dockerfile is **1.17.0** (FastAPI `app.version` still says 1.14.0 — minor
drift, acceptable). The task targets v1.15.0 conceptually but the repo is
already past that in version-bump mechanics.

### 1.2 Existing Relevant Modules
| Module | Role | Reusability for Fleet |
|---|---|---|
| `src/main.py` | FastAPI app factory, all REST endpoints, `api_success`/`api_error` helpers, `run_op` wrapper, middleware, lifespan | High — fleet endpoints integrate here; reuse `api_success`/`api_error` pattern |
| `src/session_manager.py` | SessionManager: capture/restore cookies, localStorage, sessionStorage via CDP; UUID-keyed JSON files in `~/.browser-helper/sessions/` | High — failover reuses `/session/save` + `/session/restore` for state transfer |
| `src/browser_providers/session_pool.py` | CloudSessionPool: warm pools, TTL eviction, fallback chain for Browserbase/Steel/Camofox providers | Partial — cloud-provider pool; fleet is local-node pool, but data model patterns apply |
| `src/browser_providers/base.py` | BaseProvider ABC: launch_sandbox, get_cdp_endpoint, health_check, ProviderHealth dataclass | Moderate — NodeRegistry health-check pattern can mirror ProviderHealth |
| `src/headless_manager.py` | HeadlessManager: SessionPool with SessionHandle (session_id, cdp_url, port, pid, status, resource_monitor), launch/close/navigate/eval/screenshot | High — SessionPool pattern (active_count, can_launch, max_sessions) directly informs fleet session allocation |
| `src/proxy_manager.py` | ProxyPool: JSON atomic-write persistence, round-robin/random/sticky/by-tag strategies, health checks, circuit breaker | High — persistence pattern (atomic JSON), health-check polling, scheduling strategies |
| `src/environment_store.py` | EnvironmentStore: versioned JSON persistence, validation, no-secret policy | Moderate — JSON-store pattern, validation approach |
| `src/workflow_catalog.py` | WorkflowCatalog: versioned JSON store, atomic writes | Moderate — persistence pattern |
| `static/index.html` + `static/dashboard_ux.js` | Dashboard with workspace tabs (overview, browser, automation, environments, diagnostics, agent), WebSocket state sync via `browser-helper:telemetry` CustomEvent | High — fleet dashboard extends this; add a "fleet" workspace tab |

### 1.3 Key Codebase Conventions
- **API response format**: `{"status": "ok"|"error", "operation": str, "data": Any, "error": Any, "meta": dict}`
  via `api_success()` / `api_error()`.
- **TestClient pattern**: Tests use `httpx.ASGITransport(app=app)` + `AsyncClient`
  for async tests, or `fastapi.testclient.TestClient` for sync. See
  `tests/test_headless_api.py`, `tests/test_proxy_api.py`.
- **Test markers**: `@pytest.mark.quick` (fast unit, no external deps),
  `@pytest.mark.integration` (uses TestClient/real API paths).
- **Persistence**: JSON files with atomic writes (tempfile + os.replace),
  stored under `~/.browser-helper/`. Some modules use SQLite-compatible
  patterns — but the task explicitly requests SQLite (`fleet.db`).
- **Concurrency**: asyncio-native; FastAPI with `@asynccontextmanager` lifespan.
- **Auth**: Bearer token middleware; `/health`, `/ready`, `/`, `/ws`,
  `/api/v1/capabilities` are in `PUBLIC_PATHS`.

### 1.4 Version/Deps Status
- `pyproject.toml`: version=1.17.0, Python>=3.10, deps: fastapi, uvicorn,
  websockets, httpx, Pillow, python-multipart, playwright, psutil
- `sqlite3` is in Python stdlib — no new dependency needed for fleet.db
- `conftest.py` exists at repo root, adds `src/` to `sys.path`

### 1.5 Gaps / Open Questions
- The task says v1.15.0 but repo is at 1.17.0 — version bump should target
  **1.18.0** to avoid regression (or the version in app.version should be synced).
  RECOMMENDATION: bump to 1.18.0, not 1.15.0.
- No existing CLI in the main process — `tests/test_headless_api.py` etc. test
  via HTTP. The CLI commands (`fleet node list`, `fleet session list`) need
  a thin Python CLI entry point (argparse-based) or httpx-based calls to the
  REST API. Recommend httpx-based CLI for simplicity.

---

## 2. Research Findings

### 2.1 Browser Pool Patterns (Browserless)

**Source**: https://www.browserless.io/blog/scaling-browser-automation-architecture-1000-sessions

Key patterns confirmed:
1. **Shared browser pools with session affinity**: Reusing browser instances
   across jobs reduces startup overhead and increases utilization. Session
   affinity introduces coupling between jobs and browsers — acceptable for
   stateful workflows.
2. **Three-tier request handling**:
   - Concurrency limit: if within limit, browser starts immediately
   - Queueing: once concurrency is exceeded, new requests enter a FIFO queue
     (not rejected)
   - Request rejection: if queue is full, requests are rejected with 503/429
3. **Health checks detect partially degraded sessions**: Not just process-alive
   checks, but actual browser health (memory growth, CPU spikes during
   rendering, resource exhaustion).
4. **Warm pools**: Browsers pre-launched before needed to reduce cold-start
   latency. Trade-off: idle resource usage vs. latency predictability.
5. **Browser recycling**: Memory leaks are "effectively unavoidable in practice
   at this scale" — recycling strategies are essential rather than expecting
   perfect cleanup.
6. **Multi-region deployments**: Regional load balancers route traffic; failover
   strategies needed when regions degrade.

### 2.2 Worker Settings & Concurrency (Browserless Private Deployment)

**Source**: https://docs.browserless.io/enterprise/private-deployment/worker-settings,
https://docs.browserless.io/enterprise/private-deployment/load-balancing

Key patterns:
- **Concurrency and queue limits**: Adjustable via UI slider or env vars
  (`MAX_CONCURRENCY`, `MAX_QUEUE_LENGTH`, `SESSION_TIMEOUT`). Defaults:
  concurrency=20, queue=100, timeout=60s.
- **Session health checks**: 90% CPU/memory threshold; health check fails →
  returns HTTP 500 "Health checks have failed, rejecting".
- **Automatic health restarts**: If CPU/memory stays above 90% for 5 minutes,
  the worker restarts automatically.
- **Pre-boot Chrome**: Launches browsers proactively — helps only when
  concurrency is ≤3, otherwise increases memory pressure.
- **Queue tips**: If using external queue, set queue length to 0 (reject
  immediately when at capacity). Occasional requests may still enter queue
  even at limit 0 — "expected behavior".
- **Health check on worker**: "When session health checks are enabled,
  Browserless checks worker health before accepting each connection. If the
  worker cannot handle another request, it returns a 5xx response."

### 2.3 Built-in Queueing System (Browserless)

**Source**: https://docs.browserless.io/enterprise/long-queues

Three-tier system:
1. **Concurrency Limit**: Check if within limit → start browser immediately
2. **Queueing**: Exceed concurrency → requests enter FIFO queue, processed
   in order as slots free up
3. **Request Rejection**: Queue full → request rejected with error message

Key insight: "The queueing system relies on browsers being properly closed
to free up slots for queued requests. When browsers aren't closed correctly,
they continue consuming resources until they hit the default timeout."

**Retry/backoff pattern**: Browserless returns 429 when over capacity.
Exponential backoff: `baseDelay * 2^attempt` ms between retries.
"Browserless queues REST requests automatically when below MAX_QUEUE_LENGTH,
so most capacity issues resolve without client-side retry. Network failures
and 429s above the queue limit still need handling."

### 2.4 Steel Browser API

**Source**: https://steel.dev/, https://github.com/steel-dev/steel-browser

Key patterns:
- **Session persistence**: Steel provides "session management" with
  persistent browser sessions. Sessions carry cookies, localStorage,
  sessionStorage across requests.
- **Open-source**: Apache 2.0 license, REST + WebSocket API, Python/Node SDKs
- **Built for AI agents**: Designed specifically for AI agent browser control
- **Proxy support**: Basic proxy management and rotation
- **Basic anti-detection**: stealth plugins, fingerprint management

### 2.5 Browserbase

**Source**: https://www.browserbase.com/, https://www.browserbase.com/blog/what-is-a-browserbase-browser,
https://docs.browserbase.com/platform/browser/getting-started/create-browser-session

Key patterns:
- **Session-based browser allocation**: POST to create a browser session,
  returns a WebSocket CDP URL
- **Full isolation**: "Every session runs in full isolation"
- **Video replay + DOM snapshots + network logs + clickable timeline** for
  debugging
- **Multi-region**: "one API handles it" — no fleet management by user
- **Usage-based browser-minute pricing**: $0.005-0.05/min
- **Functions**: Serverless browser sessions that auto-create/manage sessions
- **Persistent sessions**: Cookies and file download support

### 2.6 Nextbrowser — Self-Hosted Orchestration

**Source**: https://nextbrowser.com/blog/self-hosted-browser-automation-guide-2026/

Key findings:
- **Only self-hosted orchestration layer**: "NextBrowser is the only self-hosted
  tool that sits in this category [orchestration]. It's an open-source
  orchestration layer (AGPL-3.0-only) that coordinates Clawbrowser, Camoufox,
  Playwright and your proxies as a system."
- **Limitation**: "macOS and Windows desktop app" — no REST API, desktop-only
- **Gap**: API-first, self-hosted, multi-node browser orchestration does NOT
  exist — confirmed
- **Features**: Multi-account profiles, fallback chains, Solution Memory
- **Orchestration category**: Coordinates browsers, proxies, and AI agents with
  automatic fallback

### 2.7 Fleet Operations (Browserless)

The Browserless dashboard provides three fleet operations:
- **Restart**: restarts Browserless service on a single worker (same hardware)
- **Restart All**: restarts all workers simultaneously (same hardware)
- **Provision**: provisions new VMs via blue-green deployment (IP changes,
  5-10 min)

### 2.8 Synthesis: Industry Standard Patterns

From all sources, the industry-standard patterns for distributed browser
fleet orchestration are:

1. **Node Registry**: Self-registering nodes with URL, capabilities, capacity;
   periodic heartbeat; health probes via HTTP endpoint
2. **Least-Loaded Scheduling**: Route requests to the node with the fewest
   active sessions; round-robin as fallback
3. **Capacity-Based Admission**: Each node reports its max capacity; total
   capacity across fleet determines concurrent session limit
4. **Queueing with Backpressure**: FIFO queue when all nodes at capacity;
   configurable max queue length; 503 with Retry-After when queue full
5. **Health Checking**: Periodic async polling of node `/health` endpoint;
   exclude unhealthy nodes from scheduling; auto-retry after cooldown
6. **Failover**: On node failure, save session state (cookies/localStorage),
   allocate on healthy node, restore session state
7. **Session Affinity**: Optional pinning of a session to a specific node
   (for stateful workflows that can't fail over)
8. **Browser Recycling**: TTL-based or health-based recycling of browser
   instances to reclaim resources from memory leaks

---

## 3. Current State Assessment (Browser Helper Specific)

### 3.1 What Exists
- `/health` endpoint: Returns version, uptime, memory_mb, connected,
  tabs_count, operation_count. Public (no auth).
- `/ready` endpoint: Returns 200 if CDP connected, 503 if not.
- `/status` endpoint: Returns connected, tabs_count.
- `/session/save`: Captures cookies + localStorage + sessionStorage via CDP.
  Returns session dict.
- `/session/restore`: Restores cookies + localStorage + sessionStorage.
  Takes `{"session": {...}}` body.
- ProxyPool: Full CRUD, health checks, rotation strategies, JSON persistence.
- HeadlessManager: SessionPool with SessionHandle, launch/close/navigate/eval/screenshot.
- EnvironmentStore: Versioned JSON store with validation.
- Dashboard: Workspace tabs (overview, browser, automation, environments,
  diagnostics, agent), WebSocket state sync, telemetry hooks.

### 3.2 What's Missing
- No multi-node concept — browser-helper is single-node only
- No node registry or fleet management
- No shared session pool across nodes
- No queueing/backpressure for session allocation
- No failover mechanism for node failures
- No fleet dashboard or CLI commands

### 3.3 Integration Opportunities
- Fleet health checker reuses the existing `/health` endpoint pattern on each
  node
- Failover reuses existing `/session/save` + `/session/restore` endpoints
- Fleet dashboard extends the existing dashboard workspace/tab pattern
- SQLite persistence for fleet state (nodes, sessions, queue) — new dependency
  on `sqlite3` stdlib, consistent with the task's requirement

---

## 4. Clustered Options

### Option A: Full-Fledged Fleet Manager (Recommended)
**Scope**: Complete fleet orchestration with registry, pool, queue, failover,
dashboard, CLI, and SQLite persistence.

**Pros**:
- Addresses all 10 acceptance criteria
- Differentiates Browser Helper as the only API-first, self-hosted,
  multi-node browser orchestration
- Builds on existing `/health`, `/session/save-restore`, HeadlessManager
  patterns
- SQLite persistence is robust and queryable

**Cons**:
- Most complex option (~8-10 source files, 25+ tests)
- Requires careful async coordination

**Modules**:
- `src/fleet/__init__.py`
- `src/fleet/node_registry.py` — NodeRegistry: register/unregister, capacity tracking, health state
- `src/fleet/health_checker.py` — FleetHealthChecker: async periodic health polling
- `src/fleet/session_pool.py` — FleetSessionPool: least-loaded allocation, failover
- `src/fleet/queue_manager.py` — FleetQueueManager: FIFO queue, TTL, 503+Retry-After
- `src/fleet/failover.py` — FailoverManager: session state transfer on node failure
- `src/fleet/api.py` — FleetAPI: FastAPI router with all fleet endpoints
- `src/fleet/storage.py` — FleetSQLite: SQLite backend for nodes/sessions/queue
- `src/fleet/cli.py` — `fleet node list`, `fleet session list` commands
- `src/fleet/dashboard.py` — Fleet dashboard UI extensions

### Option B: Minimal Fleet (Registry + Health Only)
**Scope**: Just node registry and health checking, no session pool/queue/failover.

**Pros**: Simpler, fewer tests needed

**Cons**: Doesn't meet AC4 (queueing), AC5 (failover), AC3 (session pool)
— **REJECTED**

### Option C: Fleet as Extension of HeadlessManager
**Scope**: Extend HeadlessManager with multi-node awareness.

**Pros**: Fewer new files, reuses existing SessionPool pattern

**Cons**: Blurs concerns (headless = local process management, fleet =
multi-node orchestration); HeadlessManager is synchronous subprocess-focused
while fleet needs async HTTP probing; **REJECTED** — separation of concerns
is cleaner.

---

## 5. Chosen Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language | Python 3.11 | Matches `pyproject.toml` (`target-version = "py311"`) |
| Framework | FastAPI | Already used; `api_success`/`api_error` helpers, TestClient support |
| Persistence | SQLite (`sqlite3` stdlib) | Task requirement; no new dependency; `fleet.db` under `~/.browser-helper/` |
| Concurrency | asyncio | Matches existing async patterns; `httpx.AsyncClient` for health probes |
| Health probes | `httpx.AsyncClient` | Already a dependency; used in proxy_manager and headless_manager |
| Session transfer | Reuses `SessionManager` + `/session/save` + `/session/restore` | Existing CDP-based capture/restore |
| Dashboard | Extends `static/index.html` + `static/dashboard_ux.js` + new `static/fleet.css` | Matches existing workspace pattern |
| CLI | `httpx` + `argparse` (thin wrapper over REST API) | No new deps; simple, testable |
| Testing | `pytest` + `httpx.ASGITransport` / `TestClient` | Matches existing test patterns (`test_headless_api.py`, `test_proxy_api.py`) |

### Existing patterns to reuse (not reinvent):
1. **`api_success`/`api_error`** response format — all fleet endpoints use these
2. **Atomic JSON persistence** — proxy_manager.py pattern; for SQLite, use
   `sqlite3` with `PRAGMA journal_mode=WAL` for safety
3. **`@app.middleware("http")`** auth bypass — add `/fleet/dashboard` and
   `/static/fleet.css` to `PUBLIC_PATHS`
4. **Workspace tab pattern** in dashboard — add "fleet" to nav buttons and
   card data-workspace attributes
5. **Error response codes via `result_status()`** — map fleet errors to
   appropriate HTTP codes (404 for not-found, 503 for no healthy nodes)

---

## 6. Prioritized Task List

### P0 (Must-have for v1.18.0)
1. **SQLite persistence layer** (`src/fleet/storage.py`): FleetSQLite class
   with nodes, sessions, queue tables; atomic operations, WAL mode
2. **Node registry** (`src/fleet/node_registry.py`): Node dataclass,
   register/unregister, capacity tracking, active session counts
3. **Health checker** (`src/fleet/health_checker.py`): Async periodic polling
   of node `/health` endpoint, mark healthy/unhealthy, cooldown timer
4. **Session pool** (`src/fleet/session_pool.py`): Allocate on least-loaded
   healthy node, round-robin fallback, capacity exhaustion detection
5. **Queue manager** (`src/fleet/queue_manager.py`): FIFO queue with TTL,
   max_queue depth, 503+Retry-After when full
6. **Failover manager** (`src/fleet/failover.py`): Save session state via
   SessionManager on node failure, re-allocate on healthy node, restore state
7. **Fleet API** (`src/fleet/api.py`): FastAPI router with all 7 endpoints
8. **Integration**: Wire fleet router + lifespan task into `src/main.py`

### P1 (High-value)
9. **Dashboard extension**: Add fleet workspace tab, node list, health status,
   session counts, queue depth, live metrics
10. **CLI**: `fleet node list`, `fleet session list` using httpx to REST API
11. **README section**: Fleet orchestration documentation
12. **CHANGELOG entry**: v1.18.0 fleet features

### P2 (Nice-to-have / stretch)
13. **WebSocket streaming**: Broadcast fleet state changes to dashboard
    (extends existing `broadcast_state()` pattern)
14. **Node drain**: Graceful decommission (stop accepting new sessions,
    wait for active to finish)
15. **Session affinity**: Pin specific sessions to specific nodes

---

## 7. Acceptance Criteria → Implementation Mapping

| AC # | Criterion | Implementation Location | Tests Target |
|---|---|---|---|
| 1 | Node registry: POST /fleet/nodes/register + /fleet/nodes/{id}/unregister | `node_registry.py` + `api.py` | `test_fleet_v115.py::TestNodeRegistry` (6 tests) |
| 2 | Health checking: GET /fleet/nodes/{id}/health, async poller, exclude unhealthy | `health_checker.py` + `api.py` | `test_fleet_v115.py::TestHealthChecking` (5 tests) |
| 3 | Session pool: POST /fleet/session, GET /fleet/session/{id}, POST /fleet/session/{id}/release | `session_pool.py` + `queue_manager.py` + `api.py` | `test_fleet_v115.py::TestSessionPool` (5 tests) |
| 4 | Queueing: FIFO queue, max_queue, TTL, 503+Retry-After | `queue_manager.py` + `api.py` | `test_fleet_v115.py::TestQueueing` (4 tests) |
| 5 | Failover: node failure → save state, re-allocate, restore | `failover.py` + `api.py` | `test_fleet_v115.py::TestFailover` (3 tests) |
| 6 | Fleet dashboard: /fleet UI page | `static/index.html` + `static/dashboard_ux.js` | `test_fleet_v115.py::TestDashboard` (2 tests) |
| 7 | CLI: fleet node list, fleet session list | `src/fleet/cli.py` | `test_fleet_v115.py::TestCLI` (2 tests) |
| 8 | Tests: 25+ tests, TestClient, no mock-only | `tests/test_fleet_v115.py` | — |
| 9 | Docs: README + CHANGELOG | Root docs | `test_fleet_v115.py::TestDocs` (2 tests) |
| 10 | Release: v1.18.0, git tag, GitHub release | `pyproject.toml`, Dockerfile, `app.version` | — |

**Total tests target: 29 tests** (exceeds minimum of 25)

### Test breakdown (29 tests):
- TestNodeRegistry: 6 tests (register, register_duplicate, unregister,
  unregister_nonexistent, register_with_capabilities, register_returns_node_id)
- TestHealthChecking: 5 tests (health_probe, health_probe_unknown_node,
  health_poller_marks_unhealthy, unhealthy_excluded_from_scheduling,
  health_poller_marks_healthy_recovery)
- TestSessionPool: 5 tests (allocate_session, allocate_on_least_loaded,
  allocate_fallback_round_robin, session_status, release_session)
- TestQueueing: 4 tests (queue_when_full, 503_when_queue_full, queue_ttl_expiry,
  retry_after_header)
- TestFailover: 3 tests (failover_on_node_failure, state_transferred_via_save_restore,
  retry_on_healthy_node)
- TestDashboard: 2 tests (fleet_page_served, fleet_workspace_in_nav)
- TestCLI: 2 tests (cli_node_list, cli_session_list)
- TestDocs: 2 tests (readme_has_fleet_section, changelog_has_fleet_entry)

---

## 8. API Endpoint Specifications

All endpoints are under `/fleet/` prefix, mounted as a FastAPI router in `main.py`.

### 8.1 Node Registry

#### POST /fleet/nodes/register
**Request Body:**
```json
{
    "url": "http://192.168.1.100:8000",
    "capabilities": ["cdp", "headless", "screenshot"],
    "capacity": 10,
    "metadata": {"region": "us-east", "name": "worker-1"}
}
```
**Response (201):**
```json
{
    "status": "ok",
    "operation": "fleet_node_register",
    "data": {
        "node_id": "node_abc123",
        "url": "http://192.168.1.100:8000",
        "capabilities": ["cdp", "headless", "screenshot"],
        "capacity": 10,
        "active_sessions": 0,
        "healthy": true,
        "registered_at": "2026-08-02T12:00:00Z"
    },
    "meta": {"node_id": "node_abc123"}
}
```

#### POST /fleet/nodes/{node_id}/unregister
**Response (200):**
```json
{
    "status": "ok",
    "operation": "fleet_node_unregister",
    "data": {"node_id": "node_abc123", "unregistered": true}
}
```
**404 if node not found.**

### 8.2 Health Checking

#### GET /fleet/nodes/{node_id}/health
Probes the node's `/health` endpoint via httpx.
**Response (200):**
```json
{
    "status": "ok",
    "operation": "fleet_node_health",
    "data": {
        "node_id": "node_abc123",
        "healthy": true,
        "latency_ms": 12.3,
        "last_checked": "2026-08-02T12:00:00Z",
        "node_status": {...} // raw /health response
    }
}
```

#### GET /fleet/nodes
List all nodes with health status and active session counts.
**Response (200):**
```json
{
    "status": "ok",
    "operation": "fleet_nodes_list",
    "data": {"nodes": [...], "total": N, "healthy": M, "unhealthy": K}
}
```

### 8.3 Session Pool

#### POST /fleet/session
Allocates a session on the least-loaded healthy node.
**Request Body (optional):**
```json
{
    "session_id": "sess_xyz789",  // optional; auto-generated if omitted
    "ttl_seconds": 300            // optional; default 600
}
```
**Response (200 or 202 if queued, 503 if queue full):**
```json
// Immediate allocation
{
    "status": "ok",
    "operation": "fleet_session_allocate",
    "data": {
        "session_id": "sess_xyz789",
        "node_id": "node_abc123",
        "node_url": "http://192.168.1.100:8000",
        "cdp_url": "http://192.168.1.100:8000/devtools/...",
        "queued": false,
        "allocated_at": "2026-08-02T12:00:00Z"
    }
}
```
```json
// Queued (when all nodes at capacity)
{
    "status": "ok",
    "operation": "fleet_session_allocate",
    "data": {
        "session_id": "sess_xyz789",
        "queued": true,
        "queue_position": 2,
        "estimated_wait_seconds": 45
    }
}
```
```json
// Queue full (503)
{
    "status": "error",
    "operation": "fleet_session_allocate",
    "error": {"code": "queue_full", "message": "Fleet queue is full"},
    "meta": {"retry_after": 30}
}
```

#### GET /fleet/session/{session_id}
**Response (200):**
```json
{
    "status": "ok",
    "operation": "fleet_session_status",
    "data": {
        "session_id": "sess_xyz789",
        "node_id": "node_abc123",
        "node_url": "http://192.168.1.100:8000",
        "status": "active",
        "queued": false,
        "allocated_at": "2026-08-02T12:00:00Z",
        "last_used": "2026-08-02T12:01:00Z"
    }
}
```

#### POST /fleet/session/{session_id}/release
**Response (200):**
```json
{
    "status": "ok",
    "operation": "fleet_session_release",
    "data": {"session_id": "sess_xyz789", "released": true}
}
```

#### GET /fleet/sessions
List all sessions across the fleet.
**Response (200):**
```json
{
    "status": "ok",
    "operation": "fleet_sessions_list",
    "data": {"sessions": [...], "total": N, "active": M, "queued": K}
}
```

### 8.4 Fleet Dashboard

#### GET /fleet
Serves a fleet dashboard page (can be a dedicated HTML page or extend the
existing dashboard with a fleet workspace tab).

### 8.5 CLI Commands

```bash
# List all fleet nodes
python -m fleet.cli node list
# → http://localhost:8000/fleet/nodes  (via httpx, default API_TOKEN from env)

# List all fleet sessions
python -m fleet.cli session list
# → http://localhost:8000/fleet/sessions
```

---

## 9. SQLite Schema

File: `~/.browser-helper/fleet.db` (or configurable path)

```sql
-- Nodes table: registered fleet nodes
CREATE TABLE IF NOT EXISTS fleet_nodes (
    node_id        TEXT PRIMARY KEY,       -- UUID (node_<hex>)
    url            TEXT NOT NULL,          -- Base URL of the node
    capabilities   TEXT NOT NULL,          -- JSON array string
    capacity       INTEGER NOT NULL DEFAULT 5,  -- Max concurrent sessions
    active_sessions INTEGER NOT NULL DEFAULT 0,
    healthy        INTEGER NOT NULL DEFAULT 1,  -- 1=healthy, 0=unhealthy
    last_checked   REAL NOT NULL DEFAULT 0,  -- epoch timestamp
    last_error     TEXT,                    -- Last health error message
    metadata       TEXT,                    -- JSON: region, name, etc.
    registered_at  REAL NOT NULL,           -- epoch timestamp
    updated_at     REAL NOT NULL            -- epoch timestamp
);

-- Sessions table: active fleet sessions
CREATE TABLE IF NOT EXISTS fleet_sessions (
    session_id     TEXT PRIMARY KEY,       -- UUID (sess_<hex>)
    node_id        TEXT NOT NULL,          -- FK to fleet_nodes
    node_url       TEXT NOT NULL,
    cdp_url        TEXT,                   -- CDP WebSocket URL on node
    status         TEXT NOT NULL DEFAULT 'active',  -- active|idle|queued|failed
    queued         INTEGER NOT NULL DEFAULT 0,
    queue_position INTEGER NOT NULL DEFAULT 0,
    allocated_at   REAL NOT NULL,
    last_used      REAL NOT NULL,
    expires_at     REAL NOT NULL,          -- TTL expiry
    saved_state    TEXT,                   -- JSON: saved session state for failover
    FOREIGN KEY (node_id) REFERENCES fleet_nodes(node_id)
);

-- Queue table: pending session allocation requests
CREATE TABLE IF NOT EXISTS fleet_queue (
    request_id     TEXT PRIMARY KEY,       -- UUID (q_<hex>)
    session_id     TEXT NOT NULL,          -- Session to allocate
    requested_at   REAL NOT NULL,
    expires_at     REAL NOT NULL,           -- TTL
    queue_position INTEGER NOT NULL,       -- 0 = next to allocate
    ttl_seconds    REAL NOT NULL            -- Original TTL
);
```

**PRAGMA settings**: `journal_mode=WAL`, `foreign_keys=ON`

---

## 10. Implementation Architecture

```
src/fleet/
  __init__.py          — Package exports
  storage.py           — FleetSQLite: SQLite backend (nodes, sessions, queue)
  node_registry.py     — NodeRegistry: register/unregister, capacity tracking
  health_checker.py    — FleetHealthChecker: async periodic polling
  session_pool.py      — FleetSessionPool: least-loaded allocation, failover
  queue_manager.py     — FleetQueueManager: FIFO queue, TTL, 503+Retry-After
  failover.py          — FailoverManager: state transfer via SessionManager
  api.py               — FleetAPI: FastAPI APIRouter with all endpoints
  cli.py               — CLI: fleet node list, fleet session list

src/main.py            — Mounts fleet router, starts health checker in lifespan
tests/test_fleet_v115.py — 29 tests (RED phase)
static/index.html      — Add fleet workspace tab
static/dashboard_ux.js — Add fleet JS handlers
```

### Data Flow

1. **Node registers** → `POST /fleet/nodes/register` → NodeRegistry adds to SQLite
2. **Health poller** (asyncio task in lifespan) → polls `http://node_url/health` →
   updates `healthy` field in SQLite → unhealthy nodes excluded from allocation
3. **Session request** → `POST /fleet/session` → FleetSessionPool checks
   healthy nodes sorted by active_sessions asc → picks least-loaded →
   if all at capacity → FleetQueueManager enqueues with TTL → 202 response
   with queue position
4. **Queue drain** → Background task dequeues as slots free → allocates session
5. **Node failure** → Health poller marks unhealthy → FailoverManager saves
   active sessions via SessionManager → re-allocates on healthy node →
   restores session state via SessionManager
6. **Dashboard** → WebSocket broadcasts fleet state (nodes, sessions, queue)
   → fleet workspace tab renders live metrics

### Integration Points with Existing Code

| Fleet Component | Existing Module | Integration Method |
|---|---|---|
| Health probe | `/health` endpoint | httpX GET to `node_url + /health` |
| Session save | SessionManager.capture | Call `_session_mgr.capture(cdp_client, sid, url)` on node |
| Session restore | SessionManager.restore | Call `_session_mgr.restore(cdp_client, state)` on node |
| API response format | `api_success`/`api_error` | FleetAPI router uses same helpers |
| Auth middleware | `auth_middleware` | Add `/fleet/dashboard` to PUBLIC_PATHS |
| Dashboard pattern | Workspace tabs | Add "fleet" data-workspace tab |
| Persistence pattern | ProxyPool atomic writes | Use SQLite instead for fleet.db |
| TestClient | ASGITransport + AsyncClient | Same pattern as test_headless_api.py |

---

## 11. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SQLite concurrency under async load | Medium | High | Use WAL mode; single writer pattern; `asyncio.Lock` per operation |
| Health poll storms (thundering herd) | Low | Medium | Stagger poll intervals per node (±2s jitter) |
| Failover state transfer fails | Low | High | Log error, mark session as failed, notify via queue |
| Queue deadlock (no slots free) | Low | High | TTL expiry removes stale queue entries; 503 when queue full |
| Dashboard WebSocket overload | Low | Medium | Reuse existing `broadcast_state()` pattern with throttling |
| Version mismatch in app.version | Low | Low | Sync `main.py` app.version with `pyproject.toml` |
| Child task ordering (research → architect → tester) | Med | High | Enforce parent dependency links via kanban_create parents |

---

## 12. Version & Release Notes

- **Target version**: v1.18.0 (repo is already at 1.17.0 in pyproject.toml/Dockerfile)
- `app.version` in `main.py` currently says 1.14.0 — must sync to 1.18.0
- Dockerfile LABEL already at 1.17.0 — bump to 1.18.0
- Commit message: `feat(fleet): distributed browser fleet orchestration — node registry, session pool, health, queue, failover`
- GitHub release: tag `v1.18.0`

---

## 13. Recommendations for Child Tasks

### For Researcher (t_59fa3bcd — if not already completed)
- Research brief should cover: Browserless 3-tier queueing, Steel session persistence,
  Browserbase isolation, Nextbrowser orchestration gap
- SQLite schema for nodes/sessions/queue tables
- API endpoint contracts (above)
- **STATUS**: Research is complete; researcher can reference this brief's Section 2

### For Code-Architect (t_397c3968)
- Use the module structure in Section 10
- Use the SQLite schema in Section 9
- Use the API specifications in Section 8
- Integrate with existing `api_success`/`api_error`, `api_error` patterns
- Add fleet endpoints to PUBLIC_PATHS where appropriate (dashboard page)
- Start health checker as background task in `@asynccontextmanager lifespan`
- **Dependencies**: None (this analysis brief is complete)

### For Pre-Tester (t_7db54f52)
- Write `tests/test_fleet_v115.py` with 29 tests (Section 7 breakdown)
- Use `httpx.ASGITransport(app=app)` + `AsyncClient` pattern (see test_headless_api.py)
- Use `@pytest.mark.quick` for unit tests, `@pytest.mark.integration` for API tests
- RED phase: all tests should fail (ImportError or endpoint not found) —
  no implementation exists yet
- Reuse `api_success`/`api_error` response format assertions
- Test SQLite persistence by pointing fleet.db to tmp_path
- **Dependencies**: Architecture brief from code-architect (t_397c3968)
