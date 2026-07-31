"""
RED-phase pre-development tests for v1.8.0 REST API endpoints (P2.1).

Interface tests: verify main module imports, app fixture.
Behavioral tests: verify /api/v1/ endpoints return correct JSON shapes
once implemented. All will fail with 404 / AssertionError until the
developer wires the new routes in main.py.

Coverage:
  - ProxyRotationManager endpoints: POST /api/v1/proxy/load-from-env, POST/GET/DELETE /api/v1/proxy, health, stats
  - FingerprintDatabase endpoints: GET/POST /api/v1/fingerprints, PUT/DELETE, generate, export/import
  - SessionManager endpoints: POST /api/v1/session/capture, POST /api/v1/session/restore, GET/DELETE, cleanup
  - AntiDetectCompositor endpoints: POST /api/v1/compose, compose/test, compose/export, compose/import, compose/resolve, compose/resolve-stealth
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# Mark as integration (uses TestClient)
pytestmark = pytest.mark.integration

from httpx import ASGITransport, AsyncClient

from main import app

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def api_client():
    """Return an async HTTP client connected to the FastAPI app."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ===================================================================
# Interface tests — pass immediately (app import + client creation)
# ===================================================================


class TestApiInterface:
    """Verify the FastAPI app can be imported and a test client created."""

    def test_app_import(self):
        """main.app is importable."""
        assert app is not None

    def test_api_client_creation(self, api_client):
        """An ASGI test client can be created from the app."""
        assert api_client is not None

    @pytest.mark.asyncio
    async def test_app_root_responds(self, api_client):
        """The app responds at root (endpoint exists)."""
        resp = await api_client.get("/")
        assert resp.status_code in (200, 307, 404)
        # Accept any response — we just need the app to be live


# ===================================================================
# Behavioral tests — /api/v1/proxy/* endpoints (RED phase)
# ===================================================================


class TestApiProxyV1RED:
    """POST/GET/DELETE /api/v1/proxy — expected to return 200 when implemented."""

    @pytest.mark.asyncio
    async def test_proxy_load_from_env(self, api_client):
        """POST /api/v1/proxy/load-from-env returns {status, added}."""
        resp = await api_client.post("/api/v1/proxy/load-from-env")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. "
            "Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "added" in data
        assert isinstance(data["added"], int)

    @pytest.mark.asyncio
    async def test_proxy_list(self, api_client):
        """GET /api/v1/proxy returns {status, proxies}."""
        resp = await api_client.get("/api/v1/proxy")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "proxies" in data

    @pytest.mark.asyncio
    async def test_proxy_add(self, api_client):
        """POST /api/v1/proxy accepts proxy array and returns ids."""
        resp = await api_client.post(
            "/api/v1/proxy",
            json={"proxies": [{"url": "socks5://test:1080", "type": "SOCKS5"}]},
        )
        assert resp.status_code in (200, 201), (
            f"Expected 200/201, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "ids" in data
        assert isinstance(data["ids"], list)

    @pytest.mark.asyncio
    async def test_proxy_health_check(self, api_client):
        """POST /api/v1/proxy/health returns {status, results}."""
        resp = await api_client.post("/api/v1/proxy/health", json={})
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "results" in data

    @pytest.mark.asyncio
    async def test_proxy_health_summary(self, api_client):
        """GET /api/v1/proxy/health returns {status, total, healthy, unhealthy}."""
        resp = await api_client.get("/api/v1/proxy/health")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        for key in ("total", "healthy", "unhealthy"):
            assert key in data, f"Missing key: {key}"
            assert isinstance(data[key], int)

    @pytest.mark.asyncio
    async def test_proxy_stats(self, api_client):
        """GET /api/v1/proxy/stats returns {status, stats}."""
        resp = await api_client.get("/api/v1/proxy/stats")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "stats" in data


# ===================================================================
# Behavioral tests — /api/v1/fingerprints/* endpoints (RED phase)
# ===================================================================


class TestApiFingerprintV1RED:
    """GET/POST/PUT/DELETE /api/v1/fingerprints — expected to return 200 when implemented."""

    @pytest.mark.asyncio
    async def test_fingerprints_list(self, api_client):
        """GET /api/v1/fingerprints returns {status, templates}."""
        resp = await api_client.get("/api/v1/fingerprints")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "templates" in data
        assert isinstance(data["templates"], list)

    @pytest.mark.asyncio
    async def test_fingerprints_get_by_name(self, api_client):
        """GET /api/v1/fingerprints/{name} returns {status, template}."""
        resp = await api_client.get("/api/v1/fingerprints/chrome-120")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "template" in data

    @pytest.mark.asyncio
    async def test_fingerprints_add(self, api_client):
        """POST /api/v1/fingerprints adds template and returns {status, name}."""
        resp = await api_client.post(
            "/api/v1/fingerprints",
            json={"name": "test-chrome", "browser": "chrome", "signals": {}, "config": {}},
        )
        assert resp.status_code in (200, 201), (
            f"Expected 200/201, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "name" in data

    @pytest.mark.asyncio
    async def test_fingerprints_update(self, api_client):
        """PUT /api/v1/fingerprints/{name} updates template and returns {status}."""
        resp = await api_client.put(
            "/api/v1/fingerprints/chrome-120",
            json={"signals": {"canvas": {"noise_enabled": False}}},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_fingerprints_delete(self, api_client):
        """DELETE /api/v1/fingerprints/{name} removes template and returns {status}."""
        resp = await api_client.delete("/api/v1/fingerprints/chrome-120")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_fingerprints_generate(self, api_client):
        """POST /api/v1/fingerprints/generate returns {status, template}."""
        resp = await api_client.post(
            "/api/v1/fingerprints/generate", json={"browser": "chrome"}
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "template" in data

    @pytest.mark.asyncio
    async def test_fingerprints_export(self, api_client):
        """POST /api/v1/fingerprints/{name}/export returns {status, path}."""
        resp = await api_client.post("/api/v1/fingerprints/chrome-120/export")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "path" in data

    @pytest.mark.asyncio
    async def test_fingerprints_import(self, api_client):
        """POST /api/v1/fingerprints/import returns {status, name}."""
        resp = await api_client.post(
            "/api/v1/fingerprints/import", json={"path": "/tmp/test.json"}
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "name" in data


# ===================================================================
# Behavioral tests — /api/v1/session/* endpoints (RED phase)
# ===================================================================


class TestApiSessionV1RED:
    """POST/GET/DELETE /api/v1/session — expected to return 200 when implemented."""

    @pytest.mark.asyncio
    async def test_session_capture(self, api_client):
        """POST /api/v1/session/capture returns {status, session}."""
        resp = await api_client.post(
            "/api/v1/session/capture",
            json={"session_id": "test-session", "cdp_url": "ws://localhost:9222"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "session" in data

    @pytest.mark.asyncio
    async def test_session_restore(self, api_client):
        """POST /api/v1/session/restore returns {status, session_id}."""
        resp = await api_client.post(
            "/api/v1/session/restore",
            json={"session_id": "test-session", "cdp_url": "ws://localhost:9222"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "session_id" in data

    @pytest.mark.asyncio
    async def test_session_list(self, api_client):
        """GET /api/v1/session returns {status, sessions}."""
        resp = await api_client.get("/api/v1/session")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "sessions" in data

    @pytest.mark.asyncio
    async def test_session_get_by_id(self, api_client):
        """GET /api/v1/session/{session_id} returns {status, session}."""
        resp = await api_client.get("/api/v1/session/test-session")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "session" in data

    @pytest.mark.asyncio
    async def test_session_delete(self, api_client):
        """DELETE /api/v1/session/{session_id} returns {status}."""
        resp = await api_client.delete("/api/v1/session/test-session")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_session_cleanup(self, api_client):
        """POST /api/v1/session/cleanup returns {status, removed}."""
        resp = await api_client.post("/api/v1/session/cleanup")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "removed" in data
        assert isinstance(data["removed"], int)


# ===================================================================
# Behavioral tests — /api/v1/compose/* endpoints (RED phase)
# ===================================================================


class TestApiComposeV1RED:
    """POST /api/v1/compose — expected to return 200 when implemented."""

    @pytest.mark.asyncio
    async def test_compose(self, api_client):
        """POST /api/v1/compose returns {status, bundle}."""
        resp = await api_client.post(
            "/api/v1/compose",
            json={
                "name": "test-profile",
                "fingerprint_template": "chrome-120",
                "proxy_strategy": "round-robin",
                "stealth_level": "medium",
                "session_ttl": 3600,
            },
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "bundle" in data

    @pytest.mark.asyncio
    async def test_compose_test(self, api_client):
        """POST /api/v1/compose/test returns {status, results}."""
        resp = await api_client.post(
            "/api/v1/compose/test",
            json={
                "bundle": {
                    "name": "test",
                    "fingerprint_template": "chrome-120",
                },
                "cdp_url": "ws://localhost:9222",
            },
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "results" in data

    @pytest.mark.asyncio
    async def test_compose_export(self, api_client):
        """POST /api/v1/compose/export returns {status, path}."""
        resp = await api_client.post(
            "/api/v1/compose/export",
            json={"name": "test-profile", "path": "/tmp/bundle.json"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "path" in data

    @pytest.mark.asyncio
    async def test_compose_import(self, api_client):
        """POST /api/v1/compose/import returns {status, bundle}."""
        resp = await api_client.post(
            "/api/v1/compose/import",
            json={"path": "/tmp/bundle.json"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "bundle" in data

    @pytest.mark.asyncio
    async def test_compose_resolve(self, api_client):
        """POST /api/v1/compose/resolve returns {status, config, js_patches}."""
        resp = await api_client.post(
            "/api/v1/compose/resolve",
            json={"template_name": "chrome-120"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "config" in data
        assert "js_patches" in data

    @pytest.mark.asyncio
    async def test_compose_resolve_stealth(self, api_client):
        """POST /api/v1/compose/resolve-stealth returns {status, patches}."""
        resp = await api_client.post(
            "/api/v1/compose/resolve-stealth",
            json={"level": "medium"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Route not wired yet (RED phase)."
        )
        data = resp.json()
        assert data["status"] == "ok"
        assert "patches" in data
