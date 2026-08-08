"""Unit tests for the high-level agent endpoints (search, flow, extractors)."""

import pytest
from unittest.mock import AsyncMock, patch

from main import (
    AgentFlowRequest,
    AgentFlowStep,
    AgentSearchRequest,
    _SEARCH_ENGINES,
    agent_run_flow,
    agent_search,
)


class FakeResult:
    """Mimics run_op's api_success dict."""

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self._data = kw.get("data", {})

    def get(self, key, default=None):
        return self._data.get(key, default) if key in self._data else self.__dict__.get(key, default)


@pytest.fixture
def fake_client():
    client = AsyncMock()
    client.navigate = AsyncMock(return_value={"status": "ok"})
    client.wait_for_ready = AsyncMock(return_value={"status": "ok", "ready": True})
    client.evaluate = AsyncMock(return_value={"status": "ok", "result": "some answer text " * 20})
    client.click_by_text = AsyncMock(return_value={"status": "ok"})
    client.click = AsyncMock(return_value={"status": "ok"})
    client.type_text = AsyncMock(return_value={"status": "ok"})
    client.wait_for_text = AsyncMock(return_value={"status": "ok"})
    client.screenshot = AsyncMock(return_value={"status": "ok", "data": "abc"})
    return client


@pytest.mark.asyncio
async def test_search_engines_map():
    assert "perplexity" in _SEARCH_ENGINES
    assert "google" in _SEARCH_ENGINES
    assert "ddg" in _SEARCH_ENGINES
    assert "bing" in _SEARCH_ENGINES
    # Perplexity builds the direct /search URL.
    builder, _ = _SEARCH_ENGINES["perplexity"]
    url = builder("kérdés")
    assert "perplexity.ai/search" in url


@pytest.mark.asyncio
async def test_search_returns_answer(fake_client):
    req = AgentSearchRequest(query="teszt", engine="perplexity", timeout=5)
    with patch("main.client", fake_client), \
         patch("main._get_current_session", return_value=None), \
         patch("main.run_op", new=AsyncMock(return_value={"status": "ok"})):
        resp = await agent_search(req)
    assert resp["status"] == "ok"
    assert resp["data"]["answer_length"] > 0
    assert "some answer text" in resp["data"]["answer"]


@pytest.mark.asyncio
async def test_run_flow_reports_steps(fake_client):
    req = AgentFlowRequest(
        name="t",
        steps=[
            AgentFlowStep(action="navigate", url="https://example.com"),
            AgentFlowStep(action="eval", js="document.title"),
            AgentFlowStep(action="wait_text", text="ok", timeout=3),
        ],
    )
    with patch("main.client", fake_client), \
         patch("main.run_op", new=AsyncMock(return_value={"status": "ok"})):
        resp = await agent_run_flow(req)
    assert resp["status"] == "ok"
    assert resp["data"]["step_count"] == 3
    assert resp["data"]["failed_steps"] == 0
    assert all(s["ok"] for s in resp["data"]["steps"])


@pytest.mark.asyncio
async def test_run_flow_stops_on_error(fake_client):
    async def boom(*a, **k):
        raise RuntimeError("boom")

    req = AgentFlowRequest(
        name="t",
        steps=[
            AgentFlowStep(action="navigate", url="https://example.com"),
            AgentFlowStep(action="eval", js="x"),
            AgentFlowStep(action="navigate", url="https://x.com"),
        ],
    )
    with patch("main.client", fake_client):
        async def fake_run_op(op, method, *args, **kwargs):
            if op == "flow_eval":
                raise RuntimeError("boom")
            return {"status": "ok"}

        with patch("main.run_op", new=fake_run_op):
            resp = await agent_run_flow(req)
    assert resp["data"]["status"] == "failed"
    assert resp["data"]["failed_steps"] == 1
    assert resp["data"]["step_count"] == 2  # stopped at the failing step
