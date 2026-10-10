"""Remote MCP access: bearer-token guard on the HTTP transport, and the refusal to
serve on a non-loopback address without a token."""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_server.server import MCPServer, bearer_token_app  # noqa: E402
from mcp_server.config import MCPSettings  # noqa: E402


async def _ok_app(scope, receive, send):
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _client(token: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=bearer_token_app(_ok_app, token))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def test_request_without_token_is_rejected():
    async def go():
        async with _client("s3cret-token") as c:
            return (await c.get("/mcp")).status_code
    assert asyncio.run(go()) == 401


def test_wrong_token_is_rejected():
    async def go():
        async with _client("s3cret-token") as c:
            return (await c.get("/mcp", headers={"Authorization": "Bearer nope"})).status_code
    assert asyncio.run(go()) == 401


def test_correct_token_passes_through():
    async def go():
        async with _client("s3cret-token") as c:
            return (await c.get("/mcp", headers={"Authorization": "Bearer s3cret-token"})).status_code
    assert asyncio.run(go()) == 200


def test_refuses_non_loopback_without_token(monkeypatch):
    monkeypatch.delenv("BH_MCP_TOKEN", raising=False)
    server = MCPServer(settings=MCPSettings(host="0.0.0.0", port=8799))
    with pytest.raises(ValueError, match="without BH_MCP_TOKEN"):
        asyncio.run(server._run_streamable_http())
