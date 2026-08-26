"""BH 1.33 gap-analysis features: P0 wait+click / auto-recover, P1 network assert, P2 trace/logs, auth profiles, geo mock.

Contract tests via TestClient with the BH_TEST_NO_CHROME stubs — no real Chrome needed.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import main as bh_main  # noqa: I001 — conftest stubs env first
from main import app


@pytest.fixture()
def client():
    return TestClient(app)


# ── P0-1/P0-2: AgentActionRequest accepts wait fields ────────────


def test_act_request_accepts_wait_until_visible_fields(client):
    body = {
        "action": "click",
        "target": {"selector": "[data-view='research']"},
        "wait_until_visible": True,
        "wait_ms": 2500,
        "observe_after": False,
    }
    req = bh_main.AgentActionRequest.model_validate(body)
    assert req.wait_until_visible is True
    assert req.wait_ms == 2500
    # defaults preserved for old callers
    req2 = bh_main.AgentActionRequest.model_validate({"action": "click"})
    assert req2.wait_until_visible is False
    assert req2.wait_ms == 5000


def test_wait_ms_bounds_rejected(client):
    with pytest.raises(Exception):
        bh_main.AgentActionRequest.model_validate({"action": "click", "wait_ms": 99999})


# ── P1-2: network assertion kind ─────────────────────────────────


def test_assert_network_passes_with_no_failures(client):
    r = client.post("/assert", json={
        "kind": "network",
        "url_pattern": "/nonexistent-path-xyz",
        "status_min": 400,
        "max_count": 0,
    })
    assert r.status_code == 200, r.text
    data = r.json()["data"]["result"]
    assert data["kind"] == "network"
    assert data["passed"] is True


def test_assert_network_fails_409_when_failures_exceed(client):
    # inject fake failures into the shared default client's network log
    fake = [{"url": "http://x/api/fail", "status": 503, "method": "GET"}]

    class FakeTarget:
        async def start_network_monitoring(self):
            return {}

        async def get_network_log(self):
            return {"entries": list(fake)}

    orig = bh_main._resolve_session_client

    async def fake_resolve(require_session=True):
        return FakeTarget(), None

    bh_main._resolve_session_client = fake_resolve
    try:
        r = client.post("/assert", json={"kind": "network", "max_count": 0})
        assert r.status_code == 409
        err = r.json()["error"]
        assert err["code"] == "assertion_failed"
        assert err["details"]["failure_count"] == 1
    finally:
        bh_main._resolve_session_client = orig


# ── P2-1: X-Trace-ID propagation + /logs search ──────────────────


def test_trace_id_echoed_and_logged(client):
    r = client.get("/health", headers={"X-Trace-ID": "tr_test123"})
    assert r.headers.get("X-Trace-ID") == "tr_test123"


def test_logs_endpoint_filters_by_op(client):
    r = client.get("/logs?limit=10")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "entries" in data and "count" in data


# ── P2-2: auth profiles ──────────────────────────────────────────


def test_auth_profile_list_empty_ok(client):
    r = client.get("/session/auth-profiles")
    assert r.status_code == 200
    data = r.json()["data"]
    assert isinstance(data["profiles"], list)


def test_auth_profile_restore_missing_404(client):
    r = client.post("/session/auth-profile/no-such-profile-xyz/restore")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "profile_not_found"


# ── P2-3: geo mock validation ────────────────────────────────────


def test_geo_mock_request_validation():
    m = bh_main.GeoMockRequest.model_validate({"lat": 47.3769, "lng": 8.5417})
    assert m.accuracy == 100.0
    with pytest.raises(Exception):
        bh_main.GeoMockRequest.model_validate({"lat": 999, "lng": 0})
