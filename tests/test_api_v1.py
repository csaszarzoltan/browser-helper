"""
Pre-development TDD tests (RED phase) for v1.8.0 REST API routes.

Tests all 29 endpoints under /api/v1/ across 4 groups:
  - /api/v1/proxy/*         (9 endpoints) — ProxyRotationManager (P0.3)
  - /api/v1/fingerprints/*  (8 endpoints) — FingerprintDatabase   (P0.1)
  - /api/v1/session/*       (6 endpoints) — SessionManager        (P1.1)
  - /api/v1/compose/*       (6 endpoints) — AntiDetectCompositor  (P1.2)

Interface tests (route registration — fail RED until routes are wired).
Behavioral tests     (response shapes — fail RED until routes are implemented).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_routes() -> dict[str, set[str]]:
    """Return {path: frozenset_of_http_methods} for all registered API routes."""
    result: dict[str, set[str]] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            # methods is a set like {'GET', 'POST'} — normalise to uppercase
            result[route.path] = {m.upper() for m in route.methods if m != "HEAD"}
    return result


def _get_path_params(path: str) -> list[str]:
    """Extract {param_name} path params from a route template."""
    import re
    return re.findall(r"\{(\w+)\}", path)


# ═══════════════════════════════════════════════════════════════════════════
# 1.  Interface — route registration (RED phase: all fail until routes exist)
# ═══════════════════════════════════════════════════════════════════════════

class TestApiV1RoutesExist:
    """Verify every expected /api/v1/ route is registered with the correct method.

    These tests fail (RED) until the developer wires the routes in main.py.
    """

    # ── Proxy endpoints (9) ──────────────────────────────────────────

    def test_proxy_load_from_env_registered(self):
        routes = _get_routes()
        assert "/api/v1/proxy/load-from-env" in routes, \
            "POST /api/v1/proxy/load-from-env is not registered"
        assert "POST" in routes["/api/v1/proxy/load-from-env"]

    def test_proxy_add_registered(self):
        routes = _get_routes()
        assert "/api/v1/proxy" in routes, \
            "POST /api/v1/proxy is not registered"
        assert "POST" in routes["/api/v1/proxy"]

    def test_proxy_list_registered(self):
        routes = _get_routes()
        # Also accept /api/v1/proxy/ with trailing slash
        assert any(
            p in routes for p in ("/api/v1/proxy", "/api/v1/proxy/")
        ), "GET /api/v1/proxy is not registered"
        for p in ("/api/v1/proxy", "/api/v1/proxy/"):
            if p in routes:
                assert "GET" in routes[p]

    def test_proxy_get_by_id_registered(self):
        routes = _get_routes()
        assert "/api/v1/proxy/{proxy_id}" in routes, \
            "GET /api/v1/proxy/{proxy_id} is not registered"
        assert "GET" in routes["/api/v1/proxy/{proxy_id}"]

    def test_proxy_delete_by_id_registered(self):
        routes = _get_routes()
        assert "/api/v1/proxy/{proxy_id}" in routes, \
            "DELETE /api/v1/proxy/{proxy_id} is not registered"
        assert "DELETE" in routes["/api/v1/proxy/{proxy_id}"]

    def test_proxy_clear_registered(self):
        routes = _get_routes()
        assert "/api/v1/proxy" in routes or "/api/v1/proxy/" in routes, \
            "DELETE /api/v1/proxy is not registered"
        for p in ("/api/v1/proxy", "/api/v1/proxy/"):
            if p in routes:
                assert "DELETE" in routes[p]

    def test_proxy_health_post_registered(self):
        routes = _get_routes()
        assert "/api/v1/proxy/health" in routes, \
            "POST /api/v1/proxy/health is not registered"
        assert "POST" in routes["/api/v1/proxy/health"]

    def test_proxy_health_get_registered(self):
        routes = _get_routes()
        assert "/api/v1/proxy/health" in routes, \
            "GET /api/v1/proxy/health is not registered"
        assert "GET" in routes["/api/v1/proxy/health"]

    def test_proxy_stats_registered(self):
        routes = _get_routes()
        assert "/api/v1/proxy/stats" in routes, \
            "GET /api/v1/proxy/stats is not registered"
        assert "GET" in routes["/api/v1/proxy/stats"]

    # ── Fingerprint endpoints (8) ────────────────────────────────────

    def test_fingerprints_list_registered(self):
        routes = _get_routes()
        assert "/api/v1/fingerprints" in routes or "/api/v1/fingerprints/" in routes, \
            "GET /api/v1/fingerprints is not registered"
        for p in ("/api/v1/fingerprints", "/api/v1/fingerprints/"):
            if p in routes:
                assert "GET" in routes[p]

    def test_fingerprints_get_registered(self):
        routes = _get_routes()
        assert "/api/v1/fingerprints/{name}" in routes, \
            "GET /api/v1/fingerprints/{name} is not registered"
        assert "GET" in routes["/api/v1/fingerprints/{name}"]

    def test_fingerprints_add_registered(self):
        routes = _get_routes()
        assert "/api/v1/fingerprints" in routes or "/api/v1/fingerprints/" in routes, \
            "POST /api/v1/fingerprints is not registered"
        for p in ("/api/v1/fingerprints", "/api/v1/fingerprints/"):
            if p in routes:
                assert "POST" in routes[p]

    def test_fingerprints_update_registered(self):
        routes = _get_routes()
        assert "/api/v1/fingerprints/{name}" in routes, \
            "PUT /api/v1/fingerprints/{name} is not registered"
        assert "PUT" in routes["/api/v1/fingerprints/{name}"]

    def test_fingerprints_delete_registered(self):
        routes = _get_routes()
        assert "/api/v1/fingerprints/{name}" in routes, \
            "DELETE /api/v1/fingerprints/{name} is not registered"
        assert "DELETE" in routes["/api/v1/fingerprints/{name}"]

    def test_fingerprints_generate_registered(self):
        routes = _get_routes()
        assert "/api/v1/fingerprints/generate" in routes, \
            "POST /api/v1/fingerprints/generate is not registered"
        assert "POST" in routes["/api/v1/fingerprints/generate"]

    def test_fingerprints_export_registered(self):
        routes = _get_routes()
        assert "/api/v1/fingerprints/{name}/export" in routes, \
            "POST /api/v1/fingerprints/{name}/export is not registered"
        assert "POST" in routes["/api/v1/fingerprints/{name}/export"]

    def test_fingerprints_import_registered(self):
        routes = _get_routes()
        assert "/api/v1/fingerprints/import" in routes, \
            "POST /api/v1/fingerprints/import is not registered"
        assert "POST" in routes["/api/v1/fingerprints/import"]

    # ── Session endpoints (6) ────────────────────────────────────────

    def test_session_capture_registered(self):
        routes = _get_routes()
        assert "/api/v1/session/capture" in routes, \
            "POST /api/v1/session/capture is not registered"
        assert "POST" in routes["/api/v1/session/capture"]

    def test_session_restore_registered(self):
        routes = _get_routes()
        assert "/api/v1/session/restore" in routes, \
            "POST /api/v1/session/restore is not registered"
        assert "POST" in routes["/api/v1/session/restore"]

    def test_session_list_registered(self):
        routes = _get_routes()
        assert "/api/v1/session" in routes or "/api/v1/session/" in routes, \
            "GET /api/v1/session is not registered"
        for p in ("/api/v1/session", "/api/v1/session/"):
            if p in routes:
                assert "GET" in routes[p]

    def test_session_get_by_id_registered(self):
        routes = _get_routes()
        assert "/api/v1/session/{session_id}" in routes, \
            "GET /api/v1/session/{session_id} is not registered"
        assert "GET" in routes["/api/v1/session/{session_id}"]

    def test_session_delete_by_id_registered(self):
        routes = _get_routes()
        assert "/api/v1/session/{session_id}" in routes, \
            "DELETE /api/v1/session/{session_id} is not registered"
        assert "DELETE" in routes["/api/v1/session/{session_id}"]

    def test_session_cleanup_registered(self):
        routes = _get_routes()
        assert "/api/v1/session/cleanup" in routes, \
            "POST /api/v1/session/cleanup is not registered"
        assert "POST" in routes["/api/v1/session/cleanup"]

    # ── Compose endpoints (6) ────────────────────────────────────────

    def test_compose_registered(self):
        routes = _get_routes()
        assert "/api/v1/compose" in routes or "/api/v1/compose/" in routes, \
            "POST /api/v1/compose is not registered"
        for p in ("/api/v1/compose", "/api/v1/compose/"):
            if p in routes:
                assert "POST" in routes[p]

    def test_compose_test_registered(self):
        routes = _get_routes()
        assert "/api/v1/compose/test" in routes, \
            "POST /api/v1/compose/test is not registered"
        assert "POST" in routes["/api/v1/compose/test"]

    def test_compose_export_registered(self):
        routes = _get_routes()
        assert "/api/v1/compose/export" in routes, \
            "POST /api/v1/compose/export is not registered"
        assert "POST" in routes["/api/v1/compose/export"]

    def test_compose_import_registered(self):
        routes = _get_routes()
        assert "/api/v1/compose/import" in routes, \
            "POST /api/v1/compose/import is not registered"
        assert "POST" in routes["/api/v1/compose/import"]

    def test_compose_resolve_registered(self):
        routes = _get_routes()
        assert "/api/v1/compose/resolve" in routes, \
            "POST /api/v1/compose/resolve is not registered"
        assert "POST" in routes["/api/v1/compose/resolve"]

    def test_compose_resolve_stealth_registered(self):
        routes = _get_routes()
        assert "/api/v1/compose/resolve-stealth" in routes, \
            "POST /api/v1/compose/resolve-stealth is not registered"
        assert "POST" in routes["/api/v1/compose/resolve-stealth"]


# ═══════════════════════════════════════════════════════════════════════════
# 2.  Behavior — Proxy endpoints  (RED phase: all fail until implemented)
# ═══════════════════════════════════════════════════════════════════════════

class TestProxyEndpoints:
    """Behavioral tests for /api/v1/proxy/* endpoints.

    RED phase — these fail because the routes aren't wired in main.py yet.
    Once wired, they validate HTTP status codes and response shape.
    """

    PROXY_PATH = "/api/v1/proxy"

    def test_proxy_load_from_env(self):
        """POST /api/v1/proxy/load-from-env → {"status": "ok", "added": int}"""
        response = client.post(f"{self.PROXY_PATH}/load-from-env")
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("added"), int)

    def test_proxy_add(self):
        """POST /api/v1/proxy → {"status": "ok", "ids": [...]}"""
        response = client.post(
            self.PROXY_PATH,
            json={"proxies": [{"url": "socks5://user:pass@127.0.0.1:1080", "tags": ["test"]}]},
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("ids"), list)

    def test_proxy_add_invalid_url_returns_400(self):
        """POST /api/v1/proxy with invalid URL → 400 error"""
        response = client.post(
            self.PROXY_PATH,
            json={"proxies": [{"url": "not-a-proxy"}]},
        )
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"
        assert "error" in data

    def test_proxy_add_empty_body_returns_422(self):
        """POST /api/v1/proxy with empty body → 422"""
        response = client.post(self.PROXY_PATH, json={})
        assert response.status_code == 422, \
            f"Expected 422, got {response.status_code}"

    def test_proxy_add_missing_url_returns_422(self):
        """POST /api/v1/proxy with missing url field → 422"""
        response = client.post(
            self.PROXY_PATH,
            json={"proxies": [{"tags": ["test"]}]},
        )
        assert response.status_code == 422, \
            f"Expected 422, got {response.status_code}"

    def test_proxy_list(self):
        """GET /api/v1/proxy → {"status": "ok", "proxies": [...]}"""
        response = client.get(self.PROXY_PATH)
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("proxies"), list)

    def test_proxy_get_by_id_found(self):
        """GET /api/v1/proxy/{exists} → {"status": "ok", "proxy": {...}}"""
        # First add a proxy, then retrieve it
        add_resp = client.post(
            self.PROXY_PATH,
            json={"proxies": [{"url": "http://test-proxy:3128"}]},
        )
        # Route not implemented yet — skip if 404
        if add_resp.status_code in (404, 405):
            pytest.skip("Route not implemented yet (RED phase)")
        ids = add_resp.json().get("ids", [])
        if not ids:
            pytest.skip("No proxy ID returned")
        proxy_id = ids[0]
        response = client.get(f"{self.PROXY_PATH}/{proxy_id}")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("proxy"), dict)

    def test_proxy_get_by_id_not_found_returns_404(self):
        """GET /api/v1/proxy/{nonexistent} → 404 error"""
        response = client.get(f"{self.PROXY_PATH}/nonexistent-id-12345")
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"
        assert "error" in data

    def test_proxy_delete_by_id_found(self):
        """DELETE /api/v1/proxy/{exists} → {"status": "ok"}"""
        # First add a proxy
        add_resp = client.post(
            self.PROXY_PATH,
            json={"proxies": [{"url": "http://delete-test:3128"}]},
        )
        if add_resp.status_code in (404, 405):
            pytest.skip("Route not implemented yet (RED phase)")
        ids = add_resp.json().get("ids", [])
        if not ids:
            pytest.skip("No proxy ID returned")
        proxy_id = ids[0]
        response = client.delete(f"{self.PROXY_PATH}/{proxy_id}")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"

    def test_proxy_delete_by_id_not_found_returns_404(self):
        """DELETE /api/v1/proxy/{nonexistent} → 404 error"""
        response = client.delete(f"{self.PROXY_PATH}/nonexistent-id-99999")
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_proxy_clear(self):
        """DELETE /api/v1/proxy → {"status": "ok"}"""
        response = client.delete(self.PROXY_PATH)
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"

    def test_proxy_health_post(self):
        """POST /api/v1/proxy/health → {"status": "ok", "results": [...]}"""
        response = client.post(f"{self.PROXY_PATH}/health", json={})
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("results"), list)

    def test_proxy_health_post_with_id(self):
        """POST /api/v1/proxy/health with proxy_id → single result"""
        response = client.post(
            f"{self.PROXY_PATH}/health",
            json={"proxy_id": "some-id"},
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"

    def test_proxy_health_get(self):
        """GET /api/v1/proxy/health → {"status": "ok", "total": N, "healthy": N, "unhealthy": N}"""
        response = client.get(f"{self.PROXY_PATH}/health")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("total"), int)
        assert isinstance(data.get("healthy"), int)
        assert isinstance(data.get("unhealthy"), int)
        # total should equal healthy + unhealthy
        assert data["total"] == data["healthy"] + data["unhealthy"], \
            f"total ({data['total']}) != healthy ({data['healthy']}) + unhealthy ({data['unhealthy']})"

    def test_proxy_stats(self):
        """GET /api/v1/proxy/stats → {"status": "ok", "stats": {...}}"""
        response = client.get(f"{self.PROXY_PATH}/stats")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("stats"), dict)


# ═══════════════════════════════════════════════════════════════════════════
# 3.  Behavior — Fingerprint endpoints  (RED phase)
# ═══════════════════════════════════════════════════════════════════════════

class TestFingerprintEndpoints:
    """Behavioral tests for /api/v1/fingerprints/* endpoints."""

    BASE = "/api/v1/fingerprints"

    def test_fingerprints_list(self):
        """GET /api/v1/fingerprints → {"status": "ok", "templates": [...]}"""
        response = client.get(self.BASE)
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        templates = data.get("templates", data.get("data", {}).get("templates"))
        assert isinstance(templates, list)

    def test_fingerprints_get_found(self):
        """GET /api/v1/fingerprints/{name} → {"status": "ok", "template": {...}}"""
        response = client.get(f"{self.BASE}/chrome-120")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        template = data.get("template")
        assert isinstance(template, dict)
        assert template.get("name") == "chrome-120"

    def test_fingerprints_get_not_found_returns_404(self):
        """GET /api/v1/fingerprints/{nonexistent} → 404 error"""
        response = client.get(f"{self.BASE}/nonexistent-template")
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"
        assert "error" in data

    def test_fingerprints_add(self):
        """POST /api/v1/fingerprints → {"status": "ok", "name": "..."}"""
        template = {
            "name": "test-template",
            "browser": "chrome",
            "signals": {"canvas": {"noise_enabled": True}},
            "config": {"canvas_noise_seed": 42},
        }
        response = client.post(self.BASE, json=template)
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("name"), str)

    def test_fingerprints_add_missing_name_returns_422(self):
        """POST /api/v1/fingerprints without name → 422"""
        response = client.post(self.BASE, json={"browser": "chrome"})
        assert response.status_code == 422, \
            f"Expected 422, got {response.status_code}"

    def test_fingerprints_add_duplicate_returns_400(self):
        """POST /api/v1/fingerprints with existing name → 400 conflict"""
        # Add once
        template = {
            "name": "duplicate-test",
            "browser": "chrome",
            "signals": {},
            "config": {},
        }
        client.post(self.BASE, json=template)
        # Add again — should fail
        response = client.post(self.BASE, json=template)
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_fingerprints_update(self):
        """PUT /api/v1/fingerprints/{name} → {"status": "ok"}"""
        # Pre-add a template
        template = {
            "name": "update-test",
            "browser": "chrome",
            "signals": {},
            "config": {},
        }
        client.post(self.BASE, json=template)

        response = client.put(
            f"{self.BASE}/update-test",
            json={"signals": {"canvas": {"noise_enabled": False}}},
        )
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"

    def test_fingerprints_update_not_found_returns_404(self):
        """PUT /api/v1/fingerprints/{nonexistent} → 404"""
        response = client.put(
            f"{self.BASE}/nonexistent-update",
            json={"signals": {}},
        )
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_fingerprints_delete_found(self):
        """DELETE /api/v1/fingerprints/{name} → {"status": "ok"}"""
        # Pre-add a template
        template = {
            "name": "delete-test",
            "browser": "chrome",
            "signals": {},
            "config": {},
        }
        client.post(self.BASE, json=template)

        response = client.delete(f"{self.BASE}/delete-test")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"

    def test_fingerprints_delete_not_found_returns_404(self):
        """DELETE /api/v1/fingerprints/{nonexistent} → 404"""
        response = client.delete(f"{self.BASE}/nonexistent-delete")
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_fingerprints_generate(self):
        """POST /api/v1/fingerprints/generate → {"status": "ok", "template": {...}}"""
        response = client.post(f"{self.BASE}/generate", json={"browser": "chrome"})
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        template = data.get("template")
        assert isinstance(template, dict)
        assert template.get("browser") == "chrome"

    def test_fingerprints_generate_invalid_browser_returns_400(self):
        """POST /api/v1/fingerprints/generate with bad browser → 400"""
        response = client.post(f"{self.BASE}/generate", json={"browser": "netscape"})
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_fingerprints_export(self):
        """POST /api/v1/fingerprints/{name}/export → {"status": "ok", "path": "..."}"""
        # Pre-add a template
        template = {
            "name": "export-test",
            "browser": "chrome",
            "signals": {},
            "config": {},
        }
        client.post(self.BASE, json=template)

        response = client.post(f"{self.BASE}/export-test/export", json={})
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        # path should be a string pointing to a file
        assert isinstance(data.get("path"), str)
        assert Path(data["path"]).suffix in (".json",)

    def test_fingerprints_export_not_found_returns_404(self):
        """POST /api/v1/fingerprints/{nonexistent}/export → 404"""
        response = client.post(f"{self.BASE}/nonexistent-export/export", json={})
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        # Must be API error shape, not FastAPI default {"detail": "..."}
        assert "error" in data, \
            f"Response is not API error shape: {data}"
        assert data.get("status") == "error"

    def test_fingerprints_import(self):
        """POST /api/v1/fingerprints/import → {"status": "ok", "name": "..."}"""
        # First export a template, then import it
        template = {
            "name": "import-cycle-test",
            "browser": "firefox",
            "signals": {},
            "config": {},
        }
        add_resp = client.post(self.BASE, json=template)
        if add_resp.status_code in (404, 405):
            pytest.skip("Route not implemented yet (RED phase)")

        export_resp = client.post(f"{self.BASE}/import-cycle-test/export", json={})
        if export_resp.status_code in (404, 405):
            pytest.skip("Export route not implemented yet (RED phase)")

        export_path = export_resp.json().get("path", "")
        if not export_path:
            pytest.skip("No export path returned")

        response = client.post(f"{self.BASE}/import", json={"path": export_path})
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("name"), str)

    def test_fingerprints_import_not_found_returns_404(self):
        """POST /api/v1/fingerprints/import with bad path → 404"""
        response = client.post(
            f"{self.BASE}/import",
            json={"path": "nonexistent-template-file.json"},
        )
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert "error" in data, \
            f"Response is not API error shape: {data}"
        assert data.get("status") == "error"

    def test_fingerprints_import_rejects_escaping_path(self):
        """POST /api/v1/fingerprints/import with path outside transfer dir → 400 (M6)"""
        response = client.post(
            f"{self.BASE}/import",
            json={"path": "/etc/passwd"},
        )
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "error" in data, \
            f"Response is not API error shape: {data}"

    def test_fingerprints_list_after_add(self):
        """CRUD: add a template, then list should include it."""
        unique_name = f"crud-list-test-{id(self)}"
        template = {
            "name": unique_name,
            "browser": "edge",
            "signals": {},
            "config": {},
        }
        add_resp = client.post(self.BASE, json=template)
        if add_resp.status_code in (404, 405):
            pytest.skip("Route not implemented yet (RED phase)")

        list_resp = client.get(self.BASE)
        if list_resp.status_code in (404, 405):
            pytest.skip("List route not implemented yet (RED phase)")

        templates_data = list_resp.json()
        templates = templates_data.get("templates", templates_data.get("data", {}).get("templates", []))
        names = [t.get("name") for t in templates]
        assert unique_name in names, \
            f"Added template {unique_name!r} not found in list: {names}"


# ═══════════════════════════════════════════════════════════════════════════
# 4.  Behavior — Session endpoints  (RED phase)
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionEndpoints:
    """Behavioral tests for /api/v1/session/* endpoints."""

    BASE = "/api/v1/session"

    def test_session_capture(self):
        """POST /api/v1/session/capture → {"status": "ok", "session": {...}}"""
        response = client.post(
            f"{self.BASE}/capture",
            json={"session_id": "test-session", "cdp_url": "ws://localhost:9222/devtools/browser/12345"},
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        session = data.get("session", {})
        assert isinstance(session, dict)

    def test_session_capture_missing_session_id_returns_422(self):
        """POST /api/v1/session/capture without session_id → 422"""
        response = client.post(
            f"{self.BASE}/capture",
            json={},
        )
        assert response.status_code == 422, \
            f"Expected 422, got {response.status_code}"

    def test_session_restore(self):
        """POST /api/v1/session/restore → {"status": "ok", "session_id": "..."}"""
        # First capture
        capture_resp = client.post(
            f"{self.BASE}/capture",
            json={"session_id": "restore-test", "cdp_url": "ws://localhost:9222/devtools/browser/12345"},
        )
        if capture_resp.status_code in (404, 405):
            pytest.skip("Route not implemented yet (RED phase)")

        response = client.post(
            f"{self.BASE}/restore",
            json={"session_id": "restore-test", "cdp_url": "ws://localhost:9222/devtools/browser/12345"},
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"

    def test_session_restore_not_found_returns_404(self):
        """POST /api/v1/session/restore with bad session_id → 404"""
        response = client.post(
            f"{self.BASE}/restore",
            json={"session_id": "nonexistent-session", "cdp_url": "ws://localhost:9222"},
        )
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        # Must be API error shape, not FastAPI default {"detail": "..."}
        assert "error" in data, \
            f"Response is not API error shape: {data}"
        assert data["status"] == "error"

    def test_session_list(self):
        """GET /api/v1/session → {"status": "ok", "sessions": [...]}"""
        response = client.get(self.BASE)
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        sessions = data.get("sessions", [])
        assert isinstance(sessions, list)

    def test_session_list_includes_captured(self):
        """CRUD: capture a session, then list should include it."""
        session_id = f"list-test-{id(self)}"
        capture_resp = client.post(
            f"{self.BASE}/capture",
            json={"session_id": session_id, "cdp_url": "ws://localhost:9222"},
        )
        if capture_resp.status_code in (404, 405):
            pytest.skip("Route not implemented yet (RED phase)")

        list_resp = client.get(self.BASE)
        if list_resp.status_code in (404, 405):
            pytest.skip("List route not implemented yet (RED phase)")

        sessions = list_resp.json().get("sessions", [])
        session_ids = [s.get("session_id") for s in sessions if isinstance(s, dict)]
        assert session_id in session_ids, \
            f"Session {session_id!r} not in list: {session_ids}"

    def test_session_get_by_id_found(self):
        """GET /api/v1/session/{session_id} → {"status": "ok", "session": {...}}"""
        session_id = f"get-test-{id(self)}"
        capture_resp = client.post(
            f"{self.BASE}/capture",
            json={"session_id": session_id, "cdp_url": "ws://localhost:9222"},
        )
        if capture_resp.status_code in (404, 405):
            pytest.skip("Route not implemented yet (RED phase)")

        response = client.get(f"{self.BASE}/{session_id}")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        session = data.get("session", {})
        assert isinstance(session, dict)

    def test_session_get_by_id_not_found_returns_404(self):
        """GET /api/v1/session/{nonexistent} → 404"""
        response = client.get(f"{self.BASE}/nonexistent-session-99999")
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_session_delete_by_id_found(self):
        """DELETE /api/v1/session/{session_id} → {"status": "ok"}"""
        session_id = f"delete-test-{id(self)}"
        capture_resp = client.post(
            f"{self.BASE}/capture",
            json={"session_id": session_id, "cdp_url": "ws://localhost:9222"},
        )
        if capture_resp.status_code in (404, 405):
            pytest.skip("Route not implemented yet (RED phase)")

        response = client.delete(f"{self.BASE}/{session_id}")
        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"

    def test_session_delete_by_id_not_found_returns_404(self):
        """DELETE /api/v1/session/{nonexistent} → 404"""
        response = client.delete(f"{self.BASE}/nonexistent-session-99999")
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_session_cleanup(self):
        """POST /api/v1/session/cleanup → {"status": "ok", "removed": N}"""
        response = client.post(f"{self.BASE}/cleanup", json={})
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("removed"), int)


# ═══════════════════════════════════════════════════════════════════════════
# 5.  Behavior — Compose endpoints  (RED phase)
# ═══════════════════════════════════════════════════════════════════════════

class TestComposeEndpoints:
    """Behavioral tests for /api/v1/compose/* endpoints."""

    BASE = "/api/v1/compose"

    def _sample_bundle(self) -> dict:
        return {
            "name": "test-profile",
            "fingerprint_template": "chrome-120",
            "proxy_strategy": "round-robin",
            "stealth_level": "medium",
            "session_ttl": 3600.0,
        }

    def test_compose(self):
        """POST /api/v1/compose → {"status": "ok", "bundle": {...}}"""
        response = client.post(self.BASE, json=self._sample_bundle())
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        bundle = data.get("bundle", {})
        assert isinstance(bundle, dict)
        # Should contain the five key sub-sections
        for key in ("fingerprint", "proxy", "stealth", "session", "combined"):
            assert key in bundle, \
                f"Composed bundle missing key {key!r}: {list(bundle.keys())}"

    def test_compose_invalid_template_returns_400(self):
        """POST /api/v1/compose with nonexistent template → 400"""
        bundle = self._sample_bundle()
        bundle["fingerprint_template"] = "nonexistent-template"
        response = client.post(self.BASE, json=bundle)
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_compose_missing_name_returns_422(self):
        """POST /api/v1/compose without name → 422"""
        bundle = self._sample_bundle()
        del bundle["name"]
        response = client.post(self.BASE, json=bundle)
        assert response.status_code == 422, \
            f"Expected 422, got {response.status_code}"

    def test_compose_test(self):
        """POST /api/v1/compose/test → {"status": "ok", "results": {...}}"""
        response = client.post(
            f"{self.BASE}/test",
            json={
                "bundle": self._sample_bundle(),
                "cdp_url": "ws://localhost:9222",
            },
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        results = data.get("results", {})
        assert isinstance(results, dict)

    def test_compose_test_missing_cdp_url_returns_422(self):
        """POST /api/v1/compose/test without cdp_url → 422"""
        response = client.post(
            f"{self.BASE}/test",
            json={"bundle": self._sample_bundle()},
        )
        assert response.status_code == 422, \
            f"Expected 422, got {response.status_code}"

    def test_compose_export(self):
        """POST /api/v1/compose/export → {"status": "ok", "path": "..."}"""
        response = client.post(
            f"{self.BASE}/export",
            json={
                "name": "export-test-profile",
                "path": "test-export-bundle.json",
            },
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("path"), str)

    def test_compose_import(self):
        """POST /api/v1/compose/import → {"status": "ok", "bundle": {...}}"""
        # First export a bundle
        export_resp = client.post(
            f"{self.BASE}/export",
            json={"name": "import-test", "path": "import-test-bundle.json"},
        )
        if export_resp.status_code in (404, 405):
            pytest.skip("Export route not implemented yet (RED phase)")

        response = client.post(
            f"{self.BASE}/import",
            json={"path": "import-test-bundle.json"},
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        bundle = data.get("bundle", {})
        assert isinstance(bundle, dict)

    def test_compose_import_not_found_returns_404(self):
        """POST /api/v1/compose/import with bad path → 404"""
        response = client.post(
            f"{self.BASE}/import",
            json={"path": "nonexistent-bundle.json"},
        )
        assert response.status_code == 404, \
            f"Expected 404, got {response.status_code}"
        data = response.json()
        assert "error" in data, \
            f"Response is not API error shape: {data}"
        assert data.get("status") == "error"

    def test_compose_import_rejects_escaping_path(self):
        """POST /api/v1/compose/import with path outside transfer dir → 400 (M6)"""
        response = client.post(
            f"{self.BASE}/import",
            json={"path": "/etc/passwd"},
        )
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "error" in data, \
            f"Response is not API error shape: {data}"

    def test_compose_resolve(self):
        """POST /api/v1/compose/resolve → {"status": "ok", "config": {...}, "js_patches": [...]}"""
        response = client.post(
            f"{self.BASE}/resolve",
            json={"template_name": "chrome-120"},
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        assert isinstance(data.get("config"), dict)
        assert isinstance(data.get("js_patches"), list)

    def test_compose_resolve_with_overrides(self):
        """POST /api/v1/compose/resolve with overrides → config includes override"""
        response = client.post(
            f"{self.BASE}/resolve",
            json={
                "template_name": "chrome-120",
                "overrides": {"canvas_noise_seed": 42},
            },
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        # Override should be reflected
        config = data.get("config", {})
        assert config.get("canvas_noise_seed") == 42, \
            f"Override not reflected: {config}"

    def test_compose_resolve_nonexistent_template_returns_400(self):
        """POST /api/v1/compose/resolve with bad template → 400"""
        response = client.post(
            f"{self.BASE}/resolve",
            json={"template_name": "nonexistent-template"},
        )
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"

    def test_compose_resolve_stealth(self):
        """POST /api/v1/compose/resolve-stealth → {"status": "ok", "patches": {...}}"""
        response = client.post(
            f"{self.BASE}/resolve-stealth",
            json={"level": "medium"},
        )
        assert response.status_code in (200, 201), \
            f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        patches = data.get("patches", {})
        assert isinstance(patches, dict)

    def test_compose_resolve_stealth_invalid_level_returns_400(self):
        """POST /api/v1/compose/resolve-stealth with bad level → 400"""
        response = client.post(
            f"{self.BASE}/resolve-stealth",
            json={"level": "invalid-level"},
        )
        assert response.status_code == 400, \
            f"Expected 400, got {response.status_code}"
        data = response.json()
        assert data["status"] == "error"
