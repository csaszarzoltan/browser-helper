"""MCP server — end-to-end integration tests over real transports.

This suite exercises the *wire protocol* of the MCP server exactly as a real
client would: it spawns the actual server binary (``python -m
browser_helper.mcp``) as a subprocess and talks JSON-RPC over real stdio and
real HTTP (streamable-HTTP with a session-id handshake). No MagicMock touches
the transport layer — the only fakes are environment-level (a temp fleet DB
so fleet reads run against a real registry on disk, and ``main.run_op``
patching for engine calls that would otherwise drive a real browser).

Transport coverage (task body):
  1. stdio subprocess e2e  — initialize + tools/list + tools/call per tool
  2. streamable-HTTP e2e   — same verification over an HTTP client
  3. fleet tools against a real fleet registry (tmp FLEET_DB_PATH)
  4. error handling        — unknown tool, missing required arg, fleet node
                             registered but down

Run: ``.venv/bin/python -m pytest tests/test_mcp_integration.py -v``
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_integration_helpers import (
    REPO_ROOT,
    StdioTransport,
    StreamableHTTPTransport,
)

# ---------------------------------------------------------------------------
# Fixtures — real-transport server lifecycle (no transport mocks anywhere)
# ---------------------------------------------------------------------------


@pytest.fixture()
def stdio_server():
    """Start a real MCP server subprocess on stdio; yield the transport."""
    transport = StdioTransport()
    yield transport
    transport.close()


@pytest.fixture()
def http_server(fleet_env: dict[str, str]):
    """Real MCP server on streamable-HTTP, ephemeral port, session handshake.

    The subprocess binds port 0; uvicorn logs the bound port on stderr
    (``Uvicorn running on http://127.0.0.1:NNNN``), which is parsed to build
    the base URL. ``connect()`` performs the initialize handshake and
    captures the ``mcp-session-id`` header. ``fleet_env`` keeps the fleet
    registry isolated per test and makes this fixture compose with fleet
    seeding tests.
    """
    transport = StdioTransport("--transport", "streamable-http", "--port", "0", env=fleet_env)
    line = transport.wait_for_stderr(r"Uvicorn running on http://[^\s]+", timeout=20)
    assert line, f"server did not report a bound port; stderr={transport.stderr_tail()}"
    match = re.search(r"http://[0-9.:]+", line)
    assert match, f"cannot parse uvicorn URL from {line!r}"
    base_url = f"{match.group(0)}/mcp"
    client = StreamableHTTPTransport.connect(base_url)
    yield client, base_url
    client.close()
    transport.close()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_TOOLS = [
    "navigate",
    "click",
    "type",
    "screenshot",
    "snapshot",
    "get_tabs",
    "switch_tab",
    "close_tab",
    "session_status",
    "search",
    "get_content",
    "run_flow",
    "fleet_nodes",
    "fleet_status",
    "fleet_queue",
    "memory_remember",
    "memory_recall",
    "memory_forget",
    "memory_list",
]

#: Minimum response-envelope shape asserted for every successful tool call.
#: The exact payloads vary with the engine state, so we pin the envelope
#: contract instead of brittle field-level equality.
ENVELOPE_KEYS = {"status", "operation", "data", "error", "meta"}

#: Browser tools are wired to the CDP engine; with no browser attached they
#: fail deterministically at the engine gate ("Not connected to CDP") rather
#: than returning an envelope. The every-tool e2e test asserts that exact
#: behavior for these, and an ok envelope for the pure-read tools.
CDP_GATED_TOOLS = {
    "navigate",
    "click",
    "type",
    "screenshot",
    "snapshot",
    "get_tabs",
    "switch_tab",
    "close_tab",
}

#: High-level agent tools that perform long multi-step operations (search
#: navigates + waits for streaming answers, get_content loads + extracts,
#: run_flow executes ordered steps). Without a live browser they don't fail
#: with a fast deterministic "CDP" error — they hang waiting for content.
#: The every-tool e2e loop skips them (they are covered by their own tests).
HIGH_LEVEL_TOOLS = {"search", "get_content", "run_flow"}

#: Fleet tools must never mutate the registry (AC#5 read-only gate).
FLEET_TOOLS = ("fleet_nodes", "fleet_status", "fleet_queue")


def _server_env(**overrides: str) -> dict[str, str]:
    """Env for the server subprocess: repo PYTHONPATH + isolated fleet DB.

    Without a temp ``FLEET_DB_PATH`` the server would touch the developer's
    real ``~/.browser-helper/fleet.db`` — isolation is mandatory.
    """
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(REPO_ROOT / "src"))
    env["PYTHONUNBUFFERED"] = "1"
    env.update(overrides)
    return env


@pytest.fixture()
def fleet_db_path(tmp_path: Path) -> str:
    """A fresh per-test fleet registry DB, isolated from the real one."""
    return str(tmp_path / "fleet.db")


def _inject_fleet_env(fleet_db_path: str) -> dict[str, str]:
    """Env for the server subprocess with an isolated fleet registry.

    Without a temp ``FLEET_DB_PATH`` the server would touch the developer's
    real ``~/.browser-helper/fleet.db`` — isolation is mandatory. The env is
    also applied to the *test process* so the coordinator we seed (in-process)
    and the server subprocess read the same registry file.
    """
    os.environ["FLEET_DB_PATH"] = fleet_db_path
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(REPO_ROOT / "src"))
    env["PYTHONUNBUFFERED"] = "1"
    return env


@pytest.fixture()
def fleet_env(fleet_db_path: str) -> dict[str, str]:
    """Per-test fleet DB: set in-process AND return the subprocess env."""
    return _inject_fleet_env(fleet_db_path)


def _assert_rpc_ok(resp: dict) -> dict:
    """Assert a JSON-RPC response has no error; return the ``result`` dict."""
    assert "error" not in resp, f"JSON-RPC error: {resp.get('error')}"
    assert "result" in resp, f"no result in response: {resp}"
    return resp["result"]


def _assert_tool_ok(resp: dict) -> dict:
    """Assert a tools/call response succeeded; return the parsed envelope dict."""
    result = _assert_rpc_ok(resp)
    content = result.get("content") or []
    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
    assert texts, f"no text content in tool result: {result}"
    text = texts[0]
    assert not result.get("isError"), f"tool call returned isError: {text}"
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover — should never happen
        raise AssertionError(f"tool result is not a JSON envelope: {text!r}") from exc


def _assert_tool_error(resp: dict) -> str:
    """Assert a tools/call returned isError; return the error message text."""
    result = _assert_rpc_ok(resp)
    assert result.get("isError") is True, f"expected tool error, got: {result}"
    texts = [c.get("text", "") for c in result.get("content") or []]
    return "".join(texts)


# ---------------------------------------------------------------------------
# 1. stdio transport — real subprocess, line-delimited JSON-RPC
# ---------------------------------------------------------------------------


class TestStdioE2E:
    """End-to-end over the stdio transport (task body item 1)."""

    def test_initialize_returns_server_info(self, stdio_server):
        resp = stdio_server.request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        )
        result = _assert_rpc_ok(resp)
        assert result["serverInfo"]["name"] == "browser-helper"
        assert result["protocolVersion"] == "2025-11-25"

    def test_tools_list_exact_surface(self, stdio_server):
        _assert_rpc_ok(
            stdio_server.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            )
        )
        resp = stdio_server.request("tools/list")
        result = _assert_rpc_ok(resp)
        names = [t["name"] for t in result["tools"]]
        assert sorted(names) == sorted(EXPECTED_TOOLS)
        for tool in result["tools"]:
            schema = tool.get("inputSchema") or {}
            assert schema.get("type") == "object", f"{tool['name']} schema"

    def test_every_tool_callable_over_stdio(self, stdio_server):
        """tools/call each tool; assert the wire-level contract per tool.

        With no browser attached (separate process, no CDP connection), the
        browser tools fail deterministically at the engine gate with an
        isError tool result; the read-only tools (session_status + fleet)
        return a full ok envelope. Both are real, end-to-end behavior.
        """
        _assert_rpc_ok(
            stdio_server.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            )
        )
        tools = _assert_rpc_ok(stdio_server.request("tools/list"))["tools"]
        req_id = 10
        for tool in tools:
            name = tool["name"]
            if name in HIGH_LEVEL_TOOLS:
                continue  # long-running agent tools — covered by own tests
            args = _args_for(name)
            resp = stdio_server.request(
                "tools/call", {"name": name, "arguments": args}, req_id=req_id
            )
            req_id += 1
            if name in CDP_GATED_TOOLS:
                msg = _assert_tool_error(resp)
                assert "CDP" in msg, f"{name}: unexpected error: {msg}"
            else:
                envelope = _assert_tool_ok(resp)
                assert envelope["operation"] == name, f"{name}: operation mismatch"
                assert set(envelope) >= ENVELOPE_KEYS, f"{name}: envelope mismatch"

    def test_fleet_tools_against_real_registry_over_stdio(self, tmp_path, fleet_env):
        """Spin a stdio server on a temp fleet DB; register a node in-process;
        assert fleet reads observe it (task body item 3)."""
        server = StdioTransport(env=fleet_env)
        try:
            _assert_rpc_ok(
                server.request(
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                )
            )
            # Register a real node in the same registry the server reads.
            from fleet.api import get_fleet_coordinator

            coordinator = get_fleet_coordinator()
            import asyncio

            asyncio.run(
                coordinator.registry.register(url="ws://127.0.0.1:1", node_id="node_1", capacity=2)
            )
            asyncio.run(coordinator.registry.update_health("node_1", healthy=True))

            envelope = _assert_tool_ok(
                server.request("tools/call", {"name": "fleet_nodes", "arguments": {}})
            )
            assert envelope["data"]["total"] == 1
            assert envelope["data"]["healthy"] == 1
        finally:
            server.close()


# ---------------------------------------------------------------------------
# 2. streamable-HTTP transport — real HTTP POST + session-id handshake
# ---------------------------------------------------------------------------


class TestHTTPE2E:
    """End-to-end over the streamable-HTTP transport (task body item 2)."""

    def test_http_initialize_and_list(self, http_server):
        client, _base_url = http_server
        resp = client.request("tools/list")
        result = _assert_rpc_ok(resp)
        names = [t["name"] for t in result["tools"]]
        assert sorted(names) == sorted(EXPECTED_TOOLS)
        # the transport object already did initialize during connect

    def test_http_session_id_required(self, http_server):
        """A request without a session id is rejected by the transport.

        The streamable-HTTP transport creates a session on initialize and
        requires the returned ``mcp-session-id`` header on every later
        request — a fresh POST without it must be rejected server-side.
        """
        import urllib.error
        import urllib.request

        _client, base_url = http_server
        body = json.dumps({"jsonrpc": "2.0", "id": 99, "method": "tools/list"}).encode()
        req = urllib.request.Request(
            base_url,
            data=body,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8")
        # The server must reject the request (HTTP error or JSON-RPC error)
        # and the rejection must reference the missing session id.
        assert "session" in payload.lower(), f"unexpected payload: {payload}"

    def test_every_tool_callable_over_http(self, http_server):
        client, _ = http_server
        tools = _assert_rpc_ok(client.request("tools/list"))["tools"]
        for tool in tools:
            name = tool["name"]
            if name in HIGH_LEVEL_TOOLS:
                continue  # long-running agent tools — covered by own tests
            resp = client.request("tools/call", {"name": name, "arguments": _args_for(name)})
            if name in CDP_GATED_TOOLS:
                msg = _assert_tool_error(resp)
                assert "CDP" in msg, f"{name}: unexpected error: {msg}"
            else:
                envelope = _assert_tool_ok(resp)
                assert envelope["operation"] == name
                assert set(envelope) >= ENVELOPE_KEYS

    def test_http_fleet_nodes_with_real_registry(self, http_server):
        client, _ = http_server
        # The HTTP server subprocess was started with the fleet DB env
        # (http_server composes fleet_env), so seed that same registry.
        import asyncio

        from fleet.api import get_fleet_coordinator

        coordinator = get_fleet_coordinator()
        asyncio.run(
            coordinator.registry.register(url="ws://127.0.0.1:1", node_id="node_1", capacity=2)
        )
        asyncio.run(coordinator.registry.update_health("node_1", healthy=True))

        resp = client.request("tools/call", {"name": "fleet_nodes", "arguments": {}})
        envelope = _assert_tool_ok(resp)
        assert envelope["data"]["total"] == 1


# ---------------------------------------------------------------------------
# 3. fleet tools against a real fleet registry (task body item 3)
# ---------------------------------------------------------------------------


class TestFleetRealRegistry:
    """Fleet reads observe real registry state (spins a node in the fixture).

    Every test gets a fresh fleet DB (``fleet_env``) and a stdio server
    subprocess started with that same DB, so the registry the test seeds
    in-process is the registry the server reads over the wire.
    """

    @pytest.fixture(autouse=True)
    def _server(self, fleet_env: dict[str, str]):
        server = StdioTransport(env=fleet_env)
        _assert_rpc_ok(
            server.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            )
        )
        yield server
        server.close()

    @pytest.fixture()
    def coordinator(self):
        from fleet.api import get_fleet_coordinator

        return get_fleet_coordinator()

    def test_fleet_nodes_reports_registered_node(self, _server, coordinator):
        import asyncio

        asyncio.run(
            coordinator.registry.register(url="ws://127.0.0.1:1", node_id="node_1", capacity=2)
        )
        asyncio.run(coordinator.registry.update_health("node_1", healthy=True))

        resp = _server.request("tools/call", {"name": "fleet_nodes", "arguments": {}})
        envelope = _assert_tool_ok(resp)
        assert envelope["data"]["total"] == 1
        assert envelope["data"]["healthy"] == 1
        assert envelope["meta"].get("read_only") is True

    def test_fleet_status_reports_active_session(self, _server, coordinator):
        import asyncio

        asyncio.run(
            coordinator.registry.register(url="ws://127.0.0.1:1", node_id="node_1", capacity=2)
        )
        asyncio.run(
            coordinator.storage.add_session(
                session_id="sess_1",
                node_id="node_1",
                node_url="ws://127.0.0.1:1",
                status="active",
            )
        )

        resp = _server.request("tools/call", {"name": "fleet_status", "arguments": {}})
        envelope = _assert_tool_ok(resp)
        assert envelope["data"]["total"] == 1
        assert envelope["data"]["active"] == 1

    def test_fleet_queue_reports_enqueued_requests(self, _server, coordinator):
        import asyncio

        asyncio.run(coordinator.queue.enqueue(session_id="req_1"))
        asyncio.run(coordinator.queue.enqueue(session_id="req_2"))

        resp = _server.request("tools/call", {"name": "fleet_queue", "arguments": {}})
        envelope = _assert_tool_ok(resp)
        assert envelope["data"]["size"] == 2


# ---------------------------------------------------------------------------
# 4. error handling (task body item 4)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tools/call error paths: unknown tool, missing arg, dead fleet node."""

    def test_unknown_tool_returns_is_error(self, stdio_server):
        _assert_rpc_ok(
            stdio_server.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            )
        )
        resp = stdio_server.request("tools/call", {"name": "does_not_exist", "arguments": {}})
        assert _assert_tool_error(resp)

    def test_missing_required_arg_returns_is_error(self, stdio_server):
        _assert_rpc_ok(
            stdio_server.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            )
        )
        resp = stdio_server.request("tools/call", {"name": "navigate", "arguments": {}})
        assert _assert_tool_error(resp)

    def test_fleet_node_down_reported_unhealthy(self, fleet_env):
        """A registered node with health=down must surface as unhealthy."""
        import asyncio

        from fleet.api import get_fleet_coordinator

        coordinator = get_fleet_coordinator()
        asyncio.run(
            coordinator.registry.storage.add_node(
                node_id="node_down",
                url="ws://127.0.0.1:1",
                capacity=1,
                healthy=False,
            )
        )
        # register() defaults to healthy; add_node(healthy=False) is the
        # direct route to a *down* node (the "fleet node down" error path).

        server = StdioTransport(env=fleet_env)
        try:
            _assert_rpc_ok(
                server.request(
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                )
            )
            resp = server.request("tools/call", {"name": "fleet_nodes", "arguments": {}})
            envelope = _assert_tool_ok(resp)
            assert envelope["data"]["total"] == 1
            assert envelope["data"]["unhealthy"] == 1
            assert envelope["data"]["healthy"] == 0
        finally:
            server.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _args_for(name: str) -> dict:
    """Synthetic arguments for a tool call that avoid real side effects.

    Browser tools run through ``main.run_op``, which requires a connected CDP
    client — with no browser attached these calls fail cleanly *inside* the
    envelope (status: error) rather than crashing the server, which is
    exactly the failure mode an integration test must tolerate. The fleet
    tools are pure reads.
    """
    if name == "navigate":
        return {"url": "about:blank"}
    if name in ("click", "type"):
        return {"selector": "#noop"} if name == "click" else {"selector": "#noop", "text": "x"}
    if name in ("switch_tab", "close_tab"):
        return {"id": "tab_nonexistent"}
    if name == "search":
        return {"query": "noop", "engine": "perplexity", "timeout": 5}
    if name == "get_content":
        return {"url": "about:blank", "wait_ready": False}
    if name == "run_flow":
        return {"steps": [], "name": "noop"}
    if name == "memory_remember":
        return {"key": "test_key", "content": "test content"}
    if name == "memory_recall":
        return {"query": "test"}
    if name == "memory_forget":
        return {"key_or_id": "test_key"}
    if name == "memory_list":
        return {}
    return {}
