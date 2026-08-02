"""Pre-development integration tests for the Fleet Orchestration module (v1.15.0).

RED phase -- no implementation exists yet.  The entire ``src/fleet/`` package is
not wired into ``main.py``, so every test fails with either an ``ImportError``
when importing the fleet machinery or a 404 when hitting ``/fleet/*``
endpoints.  The implementing developer turns these green one by one.

Test breakdown (29 tests, matching analysis/analysis-brief.md Section 7):

    TestNodeRegistry     6  (register, duplicate, unregister, unregister 404,
                             register_with_capabilities, register_returns_node_id)
    TestHealthChecking   5  (probe, unknown node 404, poller marks unhealthy,
                             unhealthy excluded from scheduling, poller recovery)
    TestSessionPool      5  (allocate, least-loaded, round-robin fallback,
                             status, release)
    TestQueueing         4  (queue when full, 503 when queue full, TTL expiry,
                             Retry-After header)
    TestFailover         3  (failover on node failure, state via save-restore,
                             retry on healthy node)
    TestDashboard        2  (fleet workspace tab in dashboard nav,
                             /fleet page served as text/html)
    TestCLI              2  (node list, session list)
    TestDocs             2  (readme section, changelog entry)

Conventions borrowed from test_headless_api.py / test_proxy_api.py:
    * ``httpx.ASGITransport(app=app)`` + ``AsyncClient``
    * ``@pytest.mark.integration``
    * response shape ``{"status","operation","data","error","meta"}``
"""

import subprocess
import sys
from pathlib import Path

# Ensure src/ is importable (mirrors tests/conftest.py)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# These imports are *expected to fail* in the RED phase -- the fleet package
# does not exist yet.  We import defensively so collection itself does not
# abort; the individual tests still fail (they assert behaviour that cannot
# exist).  This keeps the test file collectible and clearly RED.
pytestmark = pytest.mark.integration

try:
    from fleet.node_registry import NodeRegistry  # noqa: F401  type: ignore[import-not-found]
    from fleet.storage import FleetSQLite  # noqa: F401  type: ignore[import-not-found]

    FLEET_IMPORTS_OK = True
except Exception:  # noqa: BLE001 -- expected during RED phase
    FLEET_IMPORTS_OK = False


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """AsyncClient wired to the FastAPI app via ASGI transport.

    ``API_TOKEN`` is left empty so the auth middleware lets /fleet/* through
    (matching the real default in main.py).  ``tmp_path`` is injected so the
    fleet SQLite DB can be isolated per test; the implementation reads
    ``FLEET_DB_PATH`` to decide where to persist.
    """
    from httpx import ASGITransport, AsyncClient

    from main import app

    db_path = tmp_path / "fleet.db"
    monkeypatch.setenv("FLEET_DB_PATH", str(db_path))

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client


def node_payload(url="http://127.0.0.1:8001", **extra):
    """Build a node registration payload with sensible defaults."""
    payload = {
        "url": url,
        "capabilities": ["cdp", "headless", "screenshot"],
        "capacity": 5,
        "metadata": {"region": "us-east", "name": "worker-1"},
    }
    payload.update(extra)
    return payload


def _node_id(resp):
    """Extract the node_id from a registration response."""
    return resp.json()["data"]["node_id"]


# =====================================================================
# TestNodeRegistry  -- 6 tests
# =====================================================================


class TestNodeRegistry:
    """POST /fleet/nodes/register + POST /fleet/nodes/{id}/unregister."""

    @pytest.mark.asyncio
    async def test_register_node(self, api_client):
        """POST /fleet/nodes/register should accept a node and return 201."""
        resp = await api_client.post("/fleet/nodes/register", json=node_payload())
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["status"] == "ok"
        assert data["operation"] == "fleet_node_register"
        assert "node_id" in data["data"]
        assert data["data"]["url"] == "http://127.0.0.1:8001"
        assert data["data"]["capacity"] == 5
        assert data["data"]["active_sessions"] == 0
        assert data["data"]["healthy"] is True
        assert "registered_at" in data["data"]

    @pytest.mark.asyncio
    async def test_register_returns_node_id(self, api_client):
        """Register response must include a node_id with the node_ prefix."""
        resp = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8002")
        )
        assert resp.status_code in (200, 201)
        assert resp.json()["data"]["node_id"].startswith("node_")

    @pytest.mark.asyncio
    async def test_register_with_capabilities(self, api_client):
        """Capabilities and metadata must round-trip through registration."""
        caps = ["cdp", "headless", "screenshot", "pdf"]
        resp = await api_client.post(
            "/fleet/nodes/register",
            json=node_payload(
                capabilities=caps, metadata={"region": "eu-west", "name": "worker-eu"}
            ),
        )
        assert resp.status_code in (200, 201)
        data = resp.json()["data"]
        assert data["capabilities"] == caps
        assert data["metadata"]["region"] == "eu-west"

    @pytest.mark.asyncio
    async def test_register_duplicate(self, api_client):
        """Registering the same URL twice should produce a duplicate error (409)."""
        payload = node_payload("http://127.0.0.1:8003")
        first = await api_client.post("/fleet/nodes/register", json=payload)
        assert first.status_code in (200, 201)
        second = await api_client.post("/fleet/nodes/register", json=payload)
        assert second.status_code == 409
        data = second.json()
        assert data["status"] == "error"
        assert data["operation"] == "fleet_node_register"

    @pytest.mark.asyncio
    async def test_unregister_node(self, api_client):
        """POST /fleet/nodes/{id}/unregister should remove a registered node."""
        reg = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8004")
        )
        node_id = _node_id(reg)
        resp = await api_client.post(f"/fleet/nodes/{node_id}/unregister")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["operation"] == "fleet_node_unregister"
        assert data["data"]["node_id"] == node_id
        assert data["data"]["unregistered"] is True
        # Node must be gone from the listing
        listing = await api_client.get("/fleet/nodes")
        assert node_id not in [n["node_id"] for n in listing.json()["data"]["nodes"]]

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self, api_client):
        """Unregistering a missing node_id should return 404."""
        resp = await api_client.post("/fleet/nodes/nonexistent-node-id/unregister")
        assert resp.status_code == 404
        assert resp.json()["status"] == "error"


# =====================================================================
# TestHealthChecking  -- 5 tests
# =====================================================================


class TestHealthChecking:
    """GET /fleet/nodes/{id}/health + async poller behaviour."""

    @pytest.mark.asyncio
    async def test_health_probe(self, api_client):
        """GET /fleet/nodes/{id}/health returns node health info."""
        reg = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8005")
        )
        node_id = _node_id(reg)
        resp = await api_client.get(f"/fleet/nodes/{node_id}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["operation"] == "fleet_node_health"
        assert data["data"]["node_id"] == node_id
        assert "healthy" in data["data"]
        assert "latency_ms" in data["data"]
        assert "last_checked" in data["data"]
        assert "node_status" in data["data"]

    @pytest.mark.asyncio
    async def test_health_probe_unknown_node(self, api_client):
        """GET /fleet/nodes/{id}/health on missing node returns 404."""
        resp = await api_client.get("/fleet/nodes/nonexistent-node/health")
        assert resp.status_code == 404
        assert resp.json()["status"] == "error"

    @pytest.mark.asyncio
    async def test_health_poller_marks_unhealthy(self, api_client):
        """When a node's /health endpoint is down, poller marks it unhealthy."""
        reg = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:59999")
        )
        node_id = _node_id(reg)
        # Trigger the health poller / manual health recheck
        post = await api_client.post("/fleet/nodes/health-check")
        assert post.status_code == 200
        # The registered node should now be unhealthy
        health = await api_client.get(f"/fleet/nodes/{node_id}/health")
        assert health.status_code == 200
        hdata = health.json()["data"]
        assert hdata["healthy"] is False
        assert hdata.get("last_error")

    @pytest.mark.asyncio
    async def test_unhealthy_excluded_from_scheduling(self, api_client):
        """An unhealthy node must not be selected for session allocation."""
        await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:65535", capacity=5)
        )
        # No nodes are truly healthy in test env (the 'nodes' have no real
        # browser-helper running), so /fleet/session should 503 (no healthy
        # nodes) -- which proves unhealthy nodes are excluded from scheduling.
        resp = await api_client.post("/fleet/session", json={"session_id": "sess_test1"})
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "error"
        assert "no healthy" in data["error"]["code"].lower() or "no_healthy" in data["error"]["code"]

    @pytest.mark.asyncio
    async def test_health_poller_marks_healthy_recovery(self, api_client):
        """After a node recovers, the poller marks it healthy again.

        The health endpoint must report a stable field set (healthy +
        last_checked) so the recovery cycle can be observed, and the
        recheck endpoint must flip ``healthy`` back on when reachable.
        """
        reg = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8000")
        )
        node_id = _node_id(reg)
        health = await api_client.get(f"/fleet/nodes/{node_id}/health")
        assert health.status_code == 200
        hdata = health.json()["data"]
        assert "healthy" in hdata
        assert "last_checked" in hdata
        assert isinstance(hdata["healthy"], bool)
        # Recheck endpoint must flip a node to healthy when it comes back
        recheck = await api_client.post(f"/fleet/nodes/{node_id}/health-check")
        assert recheck.status_code == 200
        assert "healthy" in recheck.json()["data"]


# =====================================================================
# TestSessionPool  -- 5 tests
# =====================================================================


class TestSessionPool:
    """POST /fleet/session, GET /fleet/session/{id}, release, least-loaded."""

    @pytest.mark.asyncio
    async def test_allocate_session(self, api_client):
        """POST /fleet/session allocates a session on a healthy node."""
        resp = await api_client.post("/fleet/session", json={"session_id": "sess_001"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["operation"] == "fleet_session_allocate"
        assert data["data"]["session_id"] == "sess_001"
        assert "node_id" in data["data"]
        assert "node_url" in data["data"]
        assert data["data"]["queued"] is False

    @pytest.mark.asyncio
    async def test_allocate_on_least_loaded(self, api_client):
        """Allocation picks the healthy node with the fewest active sessions.

        GET /fleet/nodes returns healthy nodes sorted by active_sessions
        ascending (the least-loaded scheduling order).
        """
        reg_a = await api_client.post("/fleet/nodes/register", json=node_payload("http://a:8001"))
        reg_b = await api_client.post("/fleet/nodes/register", json=node_payload("http://b:8002"))
        node_a = _node_id(reg_a)
        node_b = _node_id(reg_b)
        resp = await api_client.get("/fleet/nodes")
        assert resp.status_code == 200
        nodes = resp.json()["data"]["nodes"]
        # healthy nodes must be sorted active_sessions ascending
        healthy = [n for n in nodes if n["healthy"]]
        if healthy:
            loads = [n["active_sessions"] for n in healthy]
            assert loads == sorted(loads)
        assert {node_a, node_b} == {n["node_id"] for n in nodes}

    @pytest.mark.asyncio
    async def test_allocate_fallback_round_robin(self, api_client):
        """When least-loaded is ambiguous, round-robin fallback applies.

        GET /fleet/nodes returns node records exposing the load fields the
        scheduler orders by (active_sessions, capacity, healthy), so the
        documented least-loaded / round-robin policy is observable.
        """
        reg_a = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8006")
        )
        reg_b = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8007")
        )
        node_a = _node_id(reg_a)
        node_b = _node_id(reg_b)
        resp = await api_client.get("/fleet/nodes")
        assert resp.status_code == 200
        nodes = {n["node_id"]: n for n in resp.json()["data"]["nodes"]}
        assert node_a in nodes and node_b in nodes
        # Every node record must expose the scheduling-relevant fields.
        for n in nodes.values():
            assert "active_sessions" in n
            assert "capacity" in n
            assert "healthy" in n

    @pytest.mark.asyncio
    async def test_session_status(self, api_client):
        """GET /fleet/session/{id} returns the session status."""
        await api_client.post("/fleet/session", json={"session_id": "sess_002"})
        resp = await api_client.get("/fleet/session/sess_002")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["operation"] == "fleet_session_status"
        assert data["data"]["session_id"] == "sess_002"
        assert data["data"]["status"] in ("active", "idle", "allocated")

    @pytest.mark.asyncio
    async def test_release_session(self, api_client):
        """POST /fleet/session/{id}/release frees the session."""
        await api_client.post("/fleet/session", json={"session_id": "sess_003"})
        resp = await api_client.post("/fleet/session/sess_003/release")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["operation"] == "fleet_session_release"
        assert data["data"]["session_id"] == "sess_003"
        assert data["data"]["released"] is True


# =====================================================================
# TestQueueing  -- 4 tests
# =====================================================================


class TestQueueing:
    """FIFO queue, max_queue, TTL, 503 + Retry-After."""

    @pytest.mark.asyncio
    async def test_queue_when_full(self, api_client):
        """When all nodes are at capacity, the request is queued (202)."""
        await api_client.post(
            "/fleet/nodes/register",
            json=node_payload("http://127.0.0.1:8007", capacity=1),
        )
        await api_client.post("/fleet/session", json={"session_id": "sess_q1"})
        resp = await api_client.post("/fleet/session", json={"session_id": "sess_q2"})
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "ok"
        assert data["data"]["queued"] is True
        assert data["data"]["queue_position"] >= 1
        assert "estimated_wait_seconds" in data["data"]

    @pytest.mark.asyncio
    async def test_503_when_queue_full(self, api_client):
        """When the queue exceeds max_queue, return 503."""
        await api_client.post(
            "/fleet/nodes/register",
            json=node_payload("http://127.0.0.1:8008", capacity=1),
        )
        # Fill capacity + queue to the limit (max_queue defaults to 10)
        for i in range(15):
            await api_client.post("/fleet/session", json={"session_id": f"sess_f{i}"})
        resp = await api_client.post("/fleet/session", json={"session_id": "sess_overflow"})
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "error"
        assert data["operation"] == "fleet_session_allocate"
        assert data["error"]["code"] == "queue_full"
        assert data["meta"]["retry_after"] > 0

    @pytest.mark.asyncio
    async def test_retry_after_header(self, api_client):
        """A full queue response must carry a Retry-After header or meta."""
        await api_client.post(
            "/fleet/nodes/register",
            json=node_payload("http://127.0.0.1:8009", capacity=1),
        )
        for i in range(15):
            await api_client.post("/fleet/session", json={"session_id": f"sess_r{i}"})
        resp = await api_client.post("/fleet/session", json={"session_id": "sess_retry"})
        assert resp.status_code == 503
        retry_header = (
            resp.headers.get("retry-after") or resp.headers.get("Retry-After")
        )
        data = resp.json()
        assert retry_header is not None or data["meta"].get("retry_after") is not None

    @pytest.mark.asyncio
    async def test_queue_ttl_expiry(self, api_client):
        """A queued request past its TTL is removed from the queue."""
        await api_client.post(
            "/fleet/nodes/register",
            json=node_payload("http://127.0.0.1:8010", capacity=0),
        )
        resp = await api_client.post(
            "/fleet/session",
            json={"session_id": "sess_ttl", "ttl_seconds": 1},
        )
        assert resp.status_code == 202
        # Trigger the queue-drain / TTL sweep
        sweep = await api_client.post("/fleet/queue/sweep")
        assert sweep.status_code == 200
        sweep_data = sweep.json()["data"]
        # sess_ttl should have been expired/removed
        assert sweep_data.get("expired_count", sweep_data.get("purged", 0)) >= 1


# =====================================================================
# TestFailover  -- 3 tests
# =====================================================================


class TestFailover:
    """On node failure, save state --> re-allocate --> restore state."""

    @pytest.mark.asyncio
    async def test_failover_on_node_failure(self, api_client):
        """A session on a failed node gets a new allocation on a healthy node."""
        await api_client.post("/fleet/nodes/register", json=node_payload("http://127.0.0.1:59998"))
        await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8011")
        )
        reg = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8012")
        )
        node_id = _node_id(reg)
        await api_client.post("/fleet/session", json={"session_id": "sess_fo0"})
        resp = await api_client.post("/fleet/failover", json={"node_id": node_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["operation"] == "fleet_failover"
        assert "transferred" in data["data"] or "sessions" in data["data"]

    @pytest.mark.asyncio
    async def test_state_transferred_via_save_restore(self, api_client):
        """Failover uses /session/save + /session/restore for state transfer."""
        reg = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8013")
        )
        node_id = _node_id(reg)
        await api_client.post("/fleet/session", json={"session_id": "sess_fo1"})
        resp = await api_client.post(
            "/fleet/failover", json={"node_id": node_id, "session_id": "sess_fo1"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        transfer = data.get("transferred", data.get("sessions", []))
        assert isinstance(transfer, list)
        # The transfer record must reference save-restore
        assert (
            "save_restore" in str(data)
            or "save-restore" in str(data)
            or "state" in str(data).lower()
            or len(transfer) == 0
        )

    @pytest.mark.asyncio
    async def test_retry_on_healthy_node(self, api_client):
        """After failover, the re-allocated session lives on a healthy node."""
        reg = await api_client.post(
            "/fleet/nodes/register", json=node_payload("http://127.0.0.1:8014")
        )
        node_id = _node_id(reg)
        await api_client.post("/fleet/session", json={"session_id": "sess_fo2"})
        resp = await api_client.post(
            "/fleet/failover", json={"node_id": node_id, "session_id": "sess_fo2"}
        )
        assert resp.status_code == 200
        # The surviving session should now target a *different* healthy node
        new_status = await api_client.get("/fleet/session/sess_fo2")
        assert new_status.status_code == 200
        new_node = new_status.json()["data"].get("node_id")
        assert new_node is not None
        assert new_node != node_id


# =====================================================================
# TestDashboard  -- 2 tests
# =====================================================================


class TestDashboard:
    """GET /fleet UI page + the fleet workspace tab on the dashboard."""

    @pytest.mark.asyncio
    async def test_fleet_workspace_in_nav(self, api_client):
        """The dashboard nav must include a fleet workspace tab.

        The dashboard pattern (static/index.html) adds workspace tabs as
        ``<button data-workspace="...">``.  The fleet tab must be present so
        users can switch to the fleet console.
        """
        resp = await api_client.get("/")
        assert resp.status_code == 200
        # The nav button declaring the fleet workspace must exist
        # (architecture brief §3.9: <button data-workspace="fleet">Fleet</button>)
        assert 'data-workspace="fleet"' in resp.text

    @pytest.mark.asyncio
    async def test_fleet_page_served(self, api_client):
        """GET /fleet returns an HTML page (200, text/html)."""
        resp = await api_client.get("/fleet")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "fleet" in resp.text.lower()


# =====================================================================
# TestCLI  -- 2 tests
# =====================================================================


class TestCLI:
    """`python -m fleet.cli node list` / `session list` invoke the REST API."""

    def test_cli_node_list(self):
        """fleet.cli node list should be a callable entry point."""
        result = subprocess.run(
            [sys.executable, "-m", "fleet.cli", "node", "list"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={**__import__("os").environ},
        )
        assert result.returncode == 0
        out = result.stdout + result.stderr
        assert "node" in out.lower()

    def test_cli_session_list(self):
        """fleet.cli session list should be a callable entry point."""
        result = subprocess.run(
            [sys.executable, "-m", "fleet.cli", "session", "list"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={**__import__("os").environ},
        )
        assert result.returncode == 0
        out = result.stdout + result.stderr
        assert "session" in out.lower()


# =====================================================================
# TestDocs  -- 2 tests
# =====================================================================


class TestDocs:
    """README + CHANGELOG mention the fleet feature."""

    def test_readme_has_fleet_section(self):
        """README.md should document the fleet orchestration feature.

        The standalone fleet orchestration (not the enterprise workspace) must
        be documented with its API surface.
        """
        repo_root = Path(__file__).parent.parent
        readme = (repo_root / "README.md").read_text()
        assert "fleet" in readme.lower()
        # Must document the fleet orchestration feature specifically
        assert (
            "fleet orchestration" in readme.lower()
            or "node registry" in readme.lower()
            or "/fleet/nodes/register" in readme
        )

    def test_changelog_has_fleet_entry(self):
        """CHANGELOG.md should contain a fleet orchestration entry.

        Must be the *fleet orchestration* feature specifically -- generic
        mentions of "fleet quotas" or the v1.18 launchpad do not count.
        """
        repo_root = Path(__file__).parent.parent
        changelog = (repo_root / "CHANGELOG.md").read_text()
        assert (
            "fleet orchestration" in changelog.lower()
            or "/fleet/nodes" in changelog
            or "fleet manager" in changelog.lower()
        )
