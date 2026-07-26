"""Tests for browser-helper headless REST API endpoints."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from httpx import AsyncClient, ASGITransport

# Import the FastAPI app and headless manager
from main import app, headless_mgr


@pytest.fixture(autouse=True)
def reset_headless_mgr():
    """Reset headless manager state between tests."""
    # Clear any leftover sessions
    for s in headless_mgr.pool.all_sessions():
        headless_mgr.pool.remove(s.session_id)
    yield
    # Cleanup after test
    for s in headless_mgr.pool.all_sessions():
        headless_mgr.pool.remove(s.session_id)


@pytest.mark.asyncio
async def test_headless_launch_no_chrome():
    """POST /headless/launch should fail gracefully when Chrome not available."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/headless/launch")
        # Chrome may not be available in test env, so we accept error or ok
        assert resp.status_code in (200, 400)
        data = resp.json()
        assert "status" in data


@pytest.mark.asyncio
async def test_headless_sessions_empty():
    """GET /headless/sessions should return empty list initially."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/headless/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["sessions"] == []


@pytest.mark.asyncio
async def test_headless_close_nonexistent():
    """POST /headless/close with bad session_id should return 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/headless/close",
            json={"session_id": "nonexistent"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["status"] == "error"


@pytest.mark.asyncio
async def test_headless_health():
    """GET /headless/health should return pool stats."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/headless/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "pool" in data
        assert "limits" in data
        assert "sessions" in data
        assert data["pool"]["max_sessions"] == 5


@pytest.mark.asyncio
async def test_headless_navigate_nonexistent():
    """POST /headless/navigate with bad session_id should return 400."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/headless/navigate",
            json={"session_id": "nope", "url": "http://example.com"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["status"] == "error"
        assert "not found" in data["error"]
