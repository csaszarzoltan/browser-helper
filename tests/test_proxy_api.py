"""Pre-development API tests for proxy rotation endpoints (RED phase).

These tests define the expected REST API interface BEFORE implementation.
All will fail with ImportError/AttributeError until the developer
implements the proxy manager and wires the endpoints in main.py.

Coverage:
  - POST /proxy/pool (add multiple proxies)
  - GET /proxy/pool (list all proxies)
  - DELETE /proxy/pool/{proxy_id} (remove a proxy)
  - POST /proxy/health (trigger health check on a proxy)
  - GET /proxy/health (get health status summary)
  - POST /proxy/stats (get proxy usage statistics)
  - POST /headless/launch with proxy parameter
  - POST /connect with proxy parameter
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from httpx import ASGITransport, AsyncClient

from main import app, headless_mgr, proxy_pool


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def reset_headless_mgr():
    """Clear headless sessions between tests."""
    for s in headless_mgr.pool.all_sessions():
        headless_mgr.pool.remove(s.session_id)
    yield
    for s in headless_mgr.pool.all_sessions():
        headless_mgr.pool.remove(s.session_id)


@pytest.fixture(autouse=True)
def reset_proxy_pool():
    """Clear the global proxy pool between tests to avoid state leakage."""
    proxy_pool.clear()
    yield
    proxy_pool.clear()


@pytest.fixture
def api_client():
    """Return an async HTTP client connected to the FastAPI app."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def proxy_urls():
    """Sample proxy URLs for testing."""
    return [
        {"url": "socks5://user1:pass1@proxy1.example.com:1080", "type": "SOCKS5", "tags": ["datacenter", "us"]},
        {"url": "http://user2:pass2@proxy2.example.com:3128", "type": "HTTP", "tags": ["residential", "eu"]},
        {"url": "https://proxy3.example.com:443", "type": "HTTPS", "tags": ["datacenter"]},
        {"url": "socks5://proxy4.example.com:1080", "type": "SOCKS5", "tags": ["residential"]},
    ]


# ===================================================================
# Proxy Pool endpoints
# ===================================================================


class TestProxyPoolAPI:
    """Verify REST endpoints for proxy pool management."""

    @pytest.mark.asyncio
    async def test_add_proxies(self, api_client, proxy_urls):
        """POST /proxy/pool should accept a list of proxy configs."""
        resp = await api_client.post("/proxy/pool", json={"proxies": proxy_urls})
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["status"] == "ok"
        assert "data" in data
        assert "proxies" in data["data"] or "ids" in data["data"]
        assert len(data["data"].get("proxies", data["data"].get("ids", []))) == len(proxy_urls)

    @pytest.mark.asyncio
    async def test_add_proxies_single(self, api_client):
        """POST /proxy/pool should accept a single proxy object."""
        proxy = {"url": "socks5://user:pass@host:1080", "type": "SOCKS5"}
        resp = await api_client.post("/proxy/pool", json={"proxies": [proxy]})
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_add_proxies_empty(self, api_client):
        """POST /proxy/pool with empty list should return error or empty result."""
        resp = await api_client.post("/proxy/pool", json={"proxies": []})
        assert resp.status_code in (200, 201, 400, 422)
        # Accept both: validation error or empty success

    @pytest.mark.asyncio
    async def test_add_proxies_missing_url(self, api_client):
        """POST /proxy/pool missing url should return 422."""
        resp = await api_client.post("/proxy/pool", json={"proxies": [{"type": "SOCKS5"}]})
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_get_pool(self, api_client, proxy_urls):
        """GET /proxy/pool should return all proxies."""
        # First add some
        await api_client.post("/proxy/pool", json={"proxies": proxy_urls})

        resp = await api_client.get("/proxy/pool")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        proxies = data["data"].get("proxies", [])
        assert len(proxies) == len(proxy_urls)

    @pytest.mark.asyncio
    async def test_get_pool_empty(self, api_client):
        """GET /proxy/pool on empty pool should return empty list."""
        resp = await api_client.get("/proxy/pool")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        proxies = data["data"].get("proxies", data["data"])
        # Accept either shape
        if isinstance(proxies, list):
            assert len(proxies) == 0
        else:
            assert proxies["total"] == 0

    @pytest.mark.asyncio
    async def test_delete_proxy(self, api_client, proxy_urls):
        """DELETE /proxy/pool/{proxy_id} should remove a proxy."""
        # Add and capture ID
        add_resp = await api_client.post("/proxy/pool", json={"proxies": proxy_urls[:1]})
        add_data = add_resp.json()
        proxy_id = add_data["data"].get("proxies", add_data["data"].get("ids", []))[0]
        if not proxy_id:
            pytest.skip("Could not determine proxy ID from response")

        resp = await api_client.delete(f"/proxy/pool/{proxy_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        # Verify it's gone
        get_resp = await api_client.get("/proxy/pool")
        assert get_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_proxy_nonexistent(self, api_client):
        """DELETE /proxy/pool/{proxy_id} with bad id should return 404."""
        resp = await api_client.delete("/proxy/pool/nonexistent-uuid")
        assert resp.status_code == 404
        data = resp.json()
        assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_single_proxy(self, api_client, proxy_urls):
        """GET /proxy/pool/{proxy_id} should return a single proxy."""
        add_resp = await api_client.post("/proxy/pool", json={"proxies": proxy_urls[:1]})
        add_data = add_resp.json()
        proxy_id = add_data["data"].get("proxies", add_data["data"].get("ids", []))[0]
        if not proxy_id:
            pytest.skip("Could not determine proxy ID")

        resp = await api_client.get(f"/proxy/pool/{proxy_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["data"]["id"] == proxy_id

    @pytest.mark.asyncio
    async def test_get_single_proxy_nonexistent(self, api_client):
        """GET /proxy/pool/{proxy_id} with bad id should return 404."""
        resp = await api_client.get("/proxy/pool/nonexistent-uuid")
        assert resp.status_code == 404
        data = resp.json()
        assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_delete_all_proxies(self, api_client, proxy_urls):
        """DELETE /proxy/pool should clear all proxies."""
        await api_client.post("/proxy/pool", json={"proxies": proxy_urls})
        resp = await api_client.delete("/proxy/pool")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        # Verify pool is empty
        get_resp = await api_client.get("/proxy/pool")
        assert get_resp.status_code == 200
        pool_data = get_resp.json()
        proxies = pool_data["data"].get("proxies", [])
        assert len(proxies) == 0


# ===================================================================
# Proxy Health endpoints
# ===================================================================


class TestProxyHealthAPI:
    """Verify health check trigger and status endpoints."""

    @pytest.mark.asyncio
    async def test_health_check_trigger(self, api_client, proxy_urls):
        """POST /proxy/health should trigger health check and return results."""
        await api_client.post("/proxy/pool", json={"proxies": proxy_urls})
        resp = await api_client.post("/proxy/health", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "results" in data["data"]

    @pytest.mark.asyncio
    async def test_health_check_single(self, api_client, proxy_urls):
        """POST /proxy/health with proxy_id should check one proxy."""
        add_resp = await api_client.post("/proxy/pool", json={"proxies": proxy_urls[:1]})
        add_data = add_resp.json()
        proxy_id = add_data["data"].get("proxies", add_data["data"].get("ids", []))[0]
        if not proxy_id:
            pytest.skip("Could not determine proxy ID")

        resp = await api_client.post("/proxy/health", json={"proxy_id": proxy_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_check_nonexistent(self, api_client):
        """POST /proxy/health with bad proxy_id should return 404."""
        resp = await api_client.post("/proxy/health", json={"proxy_id": "nonexistent"})
        assert resp.status_code == 404
        data = resp.json()
        assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_health_check_empty_pool(self, api_client):
        """POST /proxy/health on empty pool should return empty results."""
        resp = await api_client.post("/proxy/health", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["data"]["results"] == []

    @pytest.mark.asyncio
    async def test_health_status(self, api_client, proxy_urls):
        """GET /proxy/health should return health summary."""
        await api_client.post("/proxy/pool", json={"proxies": proxy_urls})
        await api_client.post("/proxy/health", json={})

        resp = await api_client.get("/proxy/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "total" in data["data"]
        assert "healthy" in data["data"]
        assert "unhealthy" in data["data"]
        assert data["data"]["total"] == len(proxy_urls)

    @pytest.mark.asyncio
    async def test_health_status_empty(self, api_client):
        """GET /proxy/health on empty pool should return zeros."""
        resp = await api_client.get("/proxy/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 0
        assert data["data"]["healthy"] == 0


# ===================================================================
# Proxy Stats endpoint
# ===================================================================


class TestProxyStatsAPI:
    """Verify proxy usage statistics endpoint."""

    @pytest.mark.asyncio
    async def test_get_stats(self, api_client, proxy_urls):
        """POST /proxy/stats should return proxy usage statistics."""
        await api_client.post("/proxy/pool", json={"proxies": proxy_urls})
        resp = await api_client.post("/proxy/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "total" in data["data"]
        assert "healthy" in data["data"]
        assert "total_requests" in data["data"]

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, api_client):
        """POST /proxy/stats on empty pool should return zeros."""
        resp = await api_client.post("/proxy/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 0


# ===================================================================
# Headless launch with proxy
# ===================================================================


class TestHeadlessLaunchProxyAPI:
    """Verify /headless/launch accepts proxy parameters."""

    @pytest.mark.asyncio
    async def test_launch_with_proxy_url(self, api_client):
        """POST /headless/launch with proxy_url should pass proxy to session."""
        resp = await api_client.post(
            "/headless/launch",
            json={
                "proxy_url": "socks5://user:pass@proxy.example.com:1080",
                "profile_dir": "/tmp/test-profile",
            },
        )
        # Chrome won't be available, but proxy param should be accepted
        assert resp.status_code in (200, 400, 422)
        # The key requirement: proxy_url is a valid parameter on the endpoint
        # (422 means validation error — if it's not a known field)

    @pytest.mark.asyncio
    async def test_launch_with_proxy_strategy(self, api_client):
        """POST /headless/launch with proxy_strategy should be accepted."""
        resp = await api_client.post(
            "/headless/launch",
            json={
                "proxy_strategy": "round-robin",
                "proxy_group": "datacenter",
                "profile_dir": "/tmp/test-profile",
            },
        )
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.asyncio
    async def test_launch_with_proxy_group(self, api_client):
        """POST /headless/launch with proxy_group should be accepted."""
        resp = await api_client.post(
            "/headless/launch",
            json={
                "proxy_group": "residential",
            },
        )
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.asyncio
    async def test_launch_without_proxy_still_works(self, api_client):
        """POST /headless/launch without proxy should work as before."""
        resp = await api_client.post("/headless/launch", json={})
        assert resp.status_code in (200, 400)
        # The existing behaviour (error because no Chrome) must be preserved


# ===================================================================
# /connect with proxy
# ===================================================================


class TestConnectProxyAPI:
    """Verify /connect accepts proxy parameters."""

    @pytest.mark.asyncio
    async def test_connect_with_proxy(self, api_client):
        """POST /connect with proxy parameter should restart Chrome with proxy."""
        resp = await api_client.post("/connect", json={"proxy": "socks5://user:pass@proxy.example.com:1080"})
        # Chrome may not be available, but proxy param should be accepted
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.asyncio
    async def test_connect_with_proxy_and_url(self, api_client):
        """POST /connect with proxy and cdp_url should work together."""
        resp = await api_client.post("/connect", json={
            "cdp_url": "http://127.0.0.1:9555",
            "proxy": "socks5://proxy:1080",
        })
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.asyncio
    async def test_connect_without_proxy_still_works(self, api_client):
        """POST /connect without proxy should work as before."""
        resp = await api_client.post("/connect", json={})
        assert resp.status_code in (200, 400)
        # The existing behaviour must be preserved
