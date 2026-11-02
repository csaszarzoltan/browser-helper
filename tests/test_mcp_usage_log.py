"""MCP usage log: one JSON line per tool call, no arguments, `bh usage` summary."""
import asyncio
import json
import os

import pytest
from click.testing import CliRunner
from mcp.server.fastmcp.exceptions import ToolError

from mcp_server.server import MCPServer


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "u.jsonl"
    monkeypatch.setenv("BH_USAGE_LOG", str(path))
    monkeypatch.setenv("MCP_PROFILE", "compact")
    return path


def _call(name, arguments):
    async def go():
        try:
            return await MCPServer().mcp.call_tool(name, arguments)
        except ToolError as exc:
            return str(exc)
    return asyncio.run(go())


def _lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def test_one_call_one_line(log):
    _call("describe", {})
    _call("bh", {"action": "eval", "args": {"js": "1+1"}})
    lines = _lines(log)
    assert [x["op"] for x in lines] == ["describe", "eval"]
    for x in lines:
        assert {"ts", "op", "status", "error_code", "ms"} <= set(x)
        assert isinstance(x["ms"], int)
    assert lines[0]["status"] == "ok" and lines[0]["error_code"] is None


def test_eval_logs_length_and_hash_never_the_text(log):
    js = "'SECRET123'.length"
    _call("bh", {"action": "eval", "args": {"js": js}})
    (line,) = _lines(log)
    assert line["js_len"] == len(js) and len(line["js_sha1_8"]) == 8
    assert "SECRET123" not in log.read_text()


def test_log_failure_does_not_change_the_reply(log, monkeypatch):
    good = _call("describe", {})
    monkeypatch.setenv("BH_USAGE_LOG", "/proc/nope/u.jsonl")
    assert _call("describe", {}) == good


def test_rotation_past_5mb(log):
    log.write_text('{"x": "' + "a" * (5 * 1024 * 1024) + '"}\n')
    _call("describe", {})
    assert log.with_name("u.jsonl.1").exists()
    assert [x["op"] for x in _lines(log)] == ["describe"]


def test_bh_usage_summarises(log):
    _call("describe", {})
    _call("bh", {"action": "eval", "args": {"js": "1+1"}})
    _call("bh", {"action": "eval", "args": {"js": "1+1"}})
    from mcp_server.cli import usage
    res = CliRunner().invoke(usage, ["--log", str(log), "--days", "1"])
    assert res.exit_code == 0, res.output
    assert "describe" in res.output and "eval" in res.output
    assert _lines(log)[1]["js_sha1_8"] in res.output


def test_error_envelope_logs_its_code_and_still_raises(log):
    from mcp_server.serialization import tool_error
    from mcp_server.server import _as_tool_result

    async def failing():
        return tool_error("nav", "timeout", "slow")

    with pytest.raises(ToolError):
        asyncio.run(_as_tool_result(failing, "nav")())
    (line,) = _lines(log)
    assert (line["op"], line["status"], line["error_code"]) == ("nav", "error", "timeout")


def test_unknown_action_is_not_logged_verbatim(log):
    _call("bh", {"action": "SECRET123"})
    (line,) = _lines(log)
    assert line["op"] == "unknown_action" and "SECRET123" not in log.read_text()


def test_handler_exception_logs_exception_and_reraises(log):
    import asyncio

    from mcp_server.server import _as_tool_result

    async def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        asyncio.run(_as_tool_result(boom, "boom")())
    (line,) = _lines(log)
    assert (line["op"], line["status"], line["error_code"]) == ("boom", "error", "exception")
