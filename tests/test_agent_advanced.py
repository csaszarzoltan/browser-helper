"""Unit tests for the advanced agent endpoints (diff, console, templates, VLM)."""

from unittest.mock import AsyncMock, patch

import pytest

from main import (
    _FLOW_TEMPLATES,
    AgentConsoleRequest,
    AgentDiffRequest,
    agent_console,
    agent_diff,
)


@pytest.fixture
def fake_client():
    client = AsyncMock()
    client.navigate = AsyncMock(return_value={"status": "ok"})
    client.wait_for_ready = AsyncMock(return_value={"status": "ok", "ready": True})
    client.screenshot = AsyncMock(return_value={"status": "ok", "data": "aGVsbG8="})  # "hello"
    client.start_console_monitoring = AsyncMock(return_value={"status": "ok"})
    client.get_console_entries = lambda level=None: [
        {"type": "Runtime.consoleAPICalled", "level": "error", "text": "boom", "timestamp": 1},
    ]
    client.clear_console_entries = lambda: None
    return client


@pytest.mark.asyncio
async def test_diff_compares_two_urls(fake_client):
    req = AgentDiffRequest(url_a="https://a.com", url_b="https://b.com", wait_timeout=5)
    with patch("main.client", fake_client), \
         patch("main._get_current_session", return_value=None), \
         patch("main.run_op", new=AsyncMock(return_value={"status": "ok"})), \
         patch("main.artifact_store.put", return_value={"artifact_id": "art-1"}), \
         patch("screenshot_diff.ScreenshotDiffEngine") as FakeDiff:
        # Fake the diff engine to avoid image processing.
        FakeDiff.diff.return_value = type(
            "R", (), {"passed": False, "pixel_delta": 0.05,
                      "dimensions_match": True, "diff_image": "aGVsbG8=", "error": None}
        )()
        resp = await agent_diff(req)
    assert resp["status"] == "ok"
    assert resp["data"]["passed"] is False
    assert resp["data"]["pixel_delta"] == 0.05
    assert resp["data"]["diff_artifact_id"] == "art-1"


@pytest.mark.asyncio
async def test_console_returns_entries(fake_client):
    req = AgentConsoleRequest()
    with patch("main.client", fake_client), \
         patch("main._get_current_session", return_value=None):
        resp = await agent_console(req)
    assert resp["status"] == "ok"
    assert resp["data"]["count"] == 1
    assert resp["data"]["errors"] == 1
    assert resp["data"]["entries"][0]["text"] == "boom"


@pytest.mark.asyncio
async def test_console_clear(fake_client):
    req = AgentConsoleRequest(clear_first=True)
    with patch("main.client", fake_client), \
         patch("main._get_current_session", return_value=None):
        resp = await agent_console(req)
    assert resp["data"]["cleared"] is True
    assert resp["data"]["entries"] == []


def test_flow_templates_exist():
    assert "login" in _FLOW_TEMPLATES
    assert "signup" in _FLOW_TEMPLATES
    assert "search" in _FLOW_TEMPLATES
    assert "checkout" in _FLOW_TEMPLATES
    # login template builds a flow with the expected steps.
    flow = _FLOW_TEMPLATES["login"]["build"](
        {"url": "https://x.com", "username": "u", "password": "p", "success_text": "Welcome"}
    )
    assert flow["steps"][0]["action"] == "navigate"
    assert flow["steps"][-1]["action"] == "wait_text"
    assert flow["steps"][-1]["text"] == "Welcome"
