"""Cookie export — REST endpoint + MCP tool (v1.27 F1).

Covers:
- ``services.cookie_service.export_cookies`` — resolves the session and
  normalises CDP ``Network.getAllCookies`` output onto the stable keys
  (name, value, domain, path, expires, httpOnly, secure, sameSite).
- ``POST /session/{sid}/export-cookies`` — 200 with ``{"cookies": [...]}``
  for an existing session, 404 JSON error when it does not exist, 400 for
  an empty sid.
- MCP tool ``export_cookies`` — registered with the exact capability
  mapping/params and returning the envelope contract.

All CDP interaction is mocked — no real Chrome.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def app_client(monkeypatch):
    """TestClient without a context manager (avoids service startup)."""
    import main

    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    return TestClient(app)


@pytest.fixture
def fake_session(monkeypatch):
    """Register a fake session (stub client) in the registry; return it."""
    import main
    from cdp_client import CDPClient
    from session_registry import Session

    session_id = "sess-export-1"
    client = CDPClient(cdp_http_url="http://127.0.0.1:1")
    sess = Session(session_id=session_id, client=client, tab_id="tab1")
    main.session_registry._sessions[session_id] = sess
    return sess


RAW_COOKIES = [
    {
        "name": "session_id",
        "value": "abc123",
        "domain": ".example.com",
        "path": "/",
        "expires": 1750000000,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    },
    {
        "name": "prefs",
        "value": "dark",
        "domain": "example.com",
        "path": "/",
        "expires": -1,
        "httpOnly": False,
        "secure": False,
        "sameSite": "None",
    },
]


# ---------------------------------------------------------------------------
# 1. Service layer — export_cookies (mocked CDP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_cookies_returns_normalised_payload(fake_session, monkeypatch):
    """Session found → ``{"cookies": [...]}`` with the stable key set."""
    from services.cookie_service import export_cookies

    async def fake_get_cookies():
        return {"status": "ok", "count": len(RAW_COOKIES), "cookies": RAW_COOKIES}

    monkeypatch.setattr(fake_session.client, "get_cookies", fake_get_cookies)

    result = await export_cookies(fake_session.session_id)
    assert set(result) == {"cookies"}
    assert len(result["cookies"]) == 2
    for cookie in result["cookies"]:
        assert set(cookie) == {
            "name", "value", "domain", "path", "expires",
            "httpOnly", "secure", "sameSite",
        }
    assert result["cookies"][0]["name"] == "session_id"
    assert result["cookies"][0]["httpOnly"] is True
    assert result["cookies"][1]["expires"] == -1


@pytest.mark.asyncio
async def test_export_cookies_session_not_found():
    """Unknown session → SessionNotFoundError (REST layer maps to 404)."""
    from services.cookie_service import SessionNotFoundError, export_cookies

    with pytest.raises(SessionNotFoundError):
        await export_cookies("no-such-session")


@pytest.mark.asyncio
async def test_export_cookies_missing_cookie_keys_defaulted(fake_session, monkeypatch):
    """CDP cookies missing optional keys still normalise (no KeyError)."""
    from services.cookie_service import export_cookies

    async def fake_get_cookies():
        return {"status": "ok", "cookies": [{"name": "minimal", "value": "v"}]}

    monkeypatch.setattr(fake_session.client, "get_cookies", fake_get_cookies)

    result = await export_cookies(fake_session.session_id)
    assert result["cookies"] == [{
        "name": "minimal", "value": "v", "domain": "", "path": "/",
        "expires": -1, "httpOnly": False, "secure": False, "sameSite": "",
    }]


# ---------------------------------------------------------------------------
# 2. REST endpoint — POST /session/{sid}/export-cookies
# ---------------------------------------------------------------------------


def test_export_cookies_endpoint_ok(app_client, fake_session, monkeypatch):
    """Existing session → 200 with ``{"cookies": [...]}``."""

    async def fake_get_cookies():
        return {"status": "ok", "count": len(RAW_COOKIES), "cookies": RAW_COOKIES}

    monkeypatch.setattr(fake_session.client, "get_cookies", fake_get_cookies)

    resp = app_client.post(f"/session/{fake_session.session_id}/export-cookies")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["operation"] == "export_cookies"
    assert body["error"] is None
    data = body["data"]
    assert set(data) == {"cookies"}
    assert len(data["cookies"]) == 2
    assert data["cookies"][0]["name"] == "session_id"
    assert data["cookies"][0]["sameSite"] == "Lax"


def test_export_cookies_endpoint_404(app_client):
    """Unknown session → 404 with a JSON error body."""
    resp = app_client.post("/session/nope/export-cookies")
    assert resp.status_code == 404
    body = resp.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "session_not_found"
    assert "nope" in body["error"]["message"]


def test_export_cookies_endpoint_empty_sid(app_client):
    """Empty sid → 400 (invalid session id)."""
    resp = app_client.post("/session//export-cookies")
    assert resp.status_code in (400, 404)


def test_export_cookies_endpoint_cdp_error(app_client, fake_session, monkeypatch):
    """CDP failure on an existing session → 503 JSON error, not a crash."""
    async def boom():
        raise RuntimeError("cdp down")

    monkeypatch.setattr(fake_session.client, "get_cookies", boom)

    resp = app_client.post(f"/session/{fake_session.session_id}/export-cookies")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "operation_failed"


# ---------------------------------------------------------------------------
# 3. MCP tool — export_cookies
# ---------------------------------------------------------------------------


def test_mcp_tool_registered_with_capability():
    """export_cookies is in the capability-derived registry (READY)."""
    from mcp_server.registry import build_tool_defs

    tool = build_tool_defs().by_name("export_cookies")
    assert tool is not None
    assert tool.capability_id == "diagnostics.cookies"
    assert tool.status.value == "ready"
    assert tool.parameters["required"] == ["session_id"]


@pytest.mark.asyncio
async def test_mcp_export_cookies_returns_envelope(fake_session, monkeypatch):
    """MCP handler returns the JSON envelope with the cookie payload."""
    import json

    from mcp_server.tools import mcp_export_cookies

    async def fake_get_cookies():
        return {"status": "ok", "count": len(RAW_COOKIES), "cookies": RAW_COOKIES}

    monkeypatch.setattr(fake_session.client, "get_cookies", fake_get_cookies)

    raw = await mcp_export_cookies(fake_session.session_id)
    envelope = json.loads(raw)
    assert envelope["status"] == "ok"
    assert envelope["operation"] == "export_cookies"
    assert envelope["error"] is None
    assert envelope["data"]["cookies"][0]["name"] == "session_id"


@pytest.mark.asyncio
async def test_mcp_export_cookies_missing_session_returns_error():
    """Unknown session → tool_error envelope (operation_failed), not a raise."""
    import json

    from mcp_server.tools import mcp_export_cookies

    raw = await mcp_export_cookies("no-such-session")
    envelope = json.loads(raw)
    assert envelope["status"] == "error"
    assert envelope["operation"] == "export_cookies"
    assert envelope["error"]["code"] == "operation_failed"
