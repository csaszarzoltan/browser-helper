"""MCP ``compact`` profile: two tools (bh, describe) that front the full surface."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from mcp_integration_helpers import StdioTransport

from mcp_server.registry import build_tool_defs

_INIT = {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
# Actions that block until their own timeout even with no browser: not worth a minute each.
_SLOW = {"await_user", "wait_for", "wait_js", "wait_network_idle", "browser_wait_for_condition"}


def _full():
    return {t.name: t for t in build_tool_defs(profile="full")}


def _minimal_args(schema):
    """Smallest arguments that satisfy the schema's required properties."""
    placeholders = {"string": "x", "integer": 1, "number": 1, "boolean": True, "array": [], "object": {}}
    out = {}
    for key in schema.get("required", []):
        prop = schema["properties"][key]
        out[key] = prop["enum"][0] if "enum" in prop else placeholders[prop.get("type", "string")]
    return out


def _call(srv, name, arguments, req_id):
    resp = srv.request("tools/call", {"name": name, "arguments": arguments}, req_id=req_id)
    result = resp["result"]
    text = result["content"][0]["text"]
    if text.startswith("Error executing tool"):
        text = text.split(": ", 1)[1]
    try:
        env = json.loads(text)
    except ValueError:
        env = {"status": "error", "error": {"code": "not_json", "message": text}}
    return bool(result.get("isError")), env


@pytest.fixture(scope="module")
def servers():
    full = StdioTransport("--transport", "stdio", env={"MCP_PROFILE": "full"})
    compact = StdioTransport("--transport", "stdio", env={"MCP_PROFILE": "compact"})
    for srv in (full, compact):
        srv.request("initialize", _INIT, req_id=1)
    yield full, compact
    full.close()
    compact.close()


def test_compact_exposes_two_tools_in_a_small_schema(monkeypatch):
    monkeypatch.setenv("MCP_PROFILE", "compact")
    defs = build_tool_defs()
    assert sorted(t.name for t in defs) == ["bh", "describe"]
    size = len(json.dumps([{"name": t.name, "description": t.description, "inputSchema": t.parameters} for t in defs]))
    assert size < 4000, size


def test_bh_action_enum_is_exactly_the_full_tool_names(monkeypatch):
    monkeypatch.setenv("MCP_PROFILE", "compact")
    bh = build_tool_defs().by_name("bh")
    assert bh.parameters["properties"]["action"]["enum"] == sorted(_full())
    assert len(_full()) == 79


def test_wire_tools_list_is_two_tools(servers):
    _, compact = servers
    tools = compact.request("tools/list", {}, req_id=2)["result"]["tools"]
    assert [t["name"] for t in tools] == ["bh", "describe"]
    assert len(json.dumps(tools)) < 4000


def test_describe_lists_every_action(servers):
    _, compact = servers
    err, env = _call(compact, "describe", {}, 3)
    assert not err
    assert sorted(env["data"]["actions"]) == sorted(_full())
    assert all(env["data"]["actions"].values())


def test_describe_returns_the_full_schema_for_each_action(servers):
    _, compact = servers
    for i, (name, tool) in enumerate(sorted(_full().items()), start=100):
        err, env = _call(compact, "describe", {"action": name}, i)
        assert not err, name
        assert env["data"]["description"] == tool.description, name
        assert env["data"]["args_schema"] == tool.parameters, name


def test_unknown_action_suggests_close_names(servers):
    _, compact = servers
    err, env = _call(compact, "bh", {"action": "navigat"}, 300)
    assert err and env["error"]["code"] == "unknown_action"
    assert "navigate" in env["data"]["did_you_mean"]
    err, env = _call(compact, "describe", {"action": "nope"}, 301)
    assert err and env["error"]["code"] == "unknown_action"


def test_unknown_and_mistyped_args_are_rejected_before_the_call(servers):
    _, compact = servers
    err, env = _call(compact, "bh", {"action": "navigate", "args": {"urll": "x"}}, 302)
    assert err and env["error"]["code"] == "invalid_args"
    assert "url" in env["error"]["message"]
    err, env = _call(compact, "bh", {"action": "navigate", "args": {"url": 5}}, 303)
    assert err and env["error"]["code"] == "invalid_args"
    assert "string" in env["error"]["message"]


def test_missing_required_args_are_rejected_for_every_action_that_has_them(servers):
    _, compact = servers
    checked = 0
    for i, (name, tool) in enumerate(sorted(_full().items()), start=400):
        if not tool.parameters.get("required"):
            continue
        err, env = _call(compact, "bh", {"action": name, "args": {}}, i)
        assert err and env["error"]["code"] == "invalid_args", name
        checked += 1
    assert checked > 20


def test_every_action_through_bh_matches_the_direct_call(servers):
    """Same status and error code as the full profile, with the minimal valid arguments."""
    full, compact = servers
    compared = []
    for i, (name, tool) in enumerate(sorted(_full().items()), start=600):
        if name in _SLOW:
            continue
        args = _minimal_args(tool.parameters)
        direct_err, direct = _call(full, name, args, i)
        via_err, via = _call(compact, "bh", {"action": name, "args": args}, i + 1000)
        assert via_err == direct_err, name
        assert via["status"] == direct["status"], name
        assert (via.get("error") or {}).get("code") == (direct.get("error") or {}).get("code"), name
        compared.append(name)
    assert len(compared) == len(_full()) - len(_SLOW), compared


def test_args_reach_the_handler(servers):
    """A valid call with arguments runs the handler: without a browser it fails inside the tool."""
    _, compact = servers
    err, env = _call(compact, "bh", {"action": "navigate", "args": {"url": "http://127.0.0.1:1/"}}, 900)
    assert env["error"]["code"] != "invalid_args"
    err, env = _call(compact, "bh", {"action": "memory_remember", "args": {"key": "k", "content": "v"}}, 901)
    assert not err and env["status"] == "ok"
    err, env = _call(compact, "bh", {"action": "memory_list"}, 902)
    assert not err and "k" in json.dumps(env)
