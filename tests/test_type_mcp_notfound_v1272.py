"""v1.27.2: /type 404 + MCP click/type unwrap — "Element not found" is a real error."""

import asyncio
import json
import os
import sys

import pytest

# Ensure src is importable (same pattern as existing tests)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def client():
    """TestClient without context manager (known conftest quirk)."""
    from main import app

    from fastapi.testclient import TestClient

    return TestClient(app)


def test_type_not_found_returns_404(client, monkeypatch):
    """POST /type with a selector that matches nothing → 404, not 200 OK."""
    # The test env has no real Chrome (conftest stub → 503). Mock the CDP
    # type_text to return an inner "Element not found" error, so the unwrap
    # logic in /type is exercised without a live browser.
    import main as main_mod

    class _FakeClient:
        is_connected = True
        tabs_count = 1
        operation_count = 0

        async def type_text(self, selector, text):
            return {"status": "error", "error": "Element not found"}

    monkeypatch.setattr(main_mod, "client", _FakeClient())
    resp = client.post("/type", json={"selector": "#definitely-not-here", "text": "x"})
    assert resp.status_code == 404
    body = resp.json()
    assert "Element not found" in body.get("detail", "")
    assert "#definitely-not-here" in body.get("detail", "")


def test_type_success_still_ok(client, monkeypatch):
    """POST /type on a real page still returns the ok envelope (mocked client)."""
    import main as main_mod

    class _FakeClient:
        is_connected = True
        tabs_count = 1
        operation_count = 0

        async def type_text(self, selector, text):
            return {"status": "ok"}

    monkeypatch.setattr(main_mod, "client", _FakeClient())
    resp = client.post("/type", json={"selector": "#q", "text": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"


# --- MCP unwrap tests (stub _target) ---


class _FakeTarget:
    def __init__(self, click_result=None, type_result=None):
        self._click = click_result
        self._type = type_result

    async def click(self, selector):
        return self._click

    async def type_text(self, selector, text):
        return self._type


def _install_fake_target(fake):
    """Patch mcp_server.tools._target with a stub returning (fake, run_op)."""
    import mcp_server.tools as tools

    async def fake_target():
        async def run_op(op, fn, *args):
            return await fn(*args)

        return fake, run_op

    original = tools._target
    tools._target = fake_target
    return original


def _run(coro):
    return asyncio.run(coro)


def test_mcp_click_unwraps_not_found():
    """MCP click tool returns a clear error (not the ok envelope) for missing elements."""
    import mcp_server.tools as tools

    fake = _FakeTarget(click_result={"status": "error", "error": "Element not found: #nope"})
    original = _install_fake_target(fake)
    try:
        result = json.loads(_run(tools.click("#nope")))
        assert result["status"] == "error"
        assert "Element not found" in result["error"]
    finally:
        tools._target = original


def test_mcp_type_unwraps_not_found():
    """MCP type tool returns a clear error (not the ok envelope) for missing elements."""
    import mcp_server.tools as tools

    fake = _FakeTarget(type_result={"status": "error", "error": "Element not found: #x"})
    original = _install_fake_target(fake)
    try:
        result = json.loads(_run(tools.type("#x", "hi")))
        assert result["status"] == "error"
        assert "Element not found" in result["error"]
    finally:
        tools._target = original


def test_mcp_click_success_passthrough():
    """MCP click tool passes through a genuine ok result unchanged."""
    import mcp_server.tools as tools

    fake = _FakeTarget(click_result={"status": "ok", "position": {"x": 10, "y": 20}})
    original = _install_fake_target(fake)
    try:
        result = json.loads(_run(tools.click("#btn")))
        assert result["status"] == "ok"
        assert result["position"] == {"x": 10, "y": 20}
    finally:
        tools._target = original
