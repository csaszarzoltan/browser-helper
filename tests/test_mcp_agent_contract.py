"""The contract an agent relies on: schemas it can read, failures it can detect, safe defaults,
and an error-code table that matches the codes the handlers really return."""

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_registry_schema_reaches_the_registered_tool():
    from mcp_server.server import MCPServer

    mcp = MCPServer().mcp
    schema = mcp._tool_manager.get_tool("navigate").parameters
    assert schema["properties"]["wait_until"]["enum"] == ["commit", "domcontentloaded", "load"]


def test_an_error_envelope_becomes_a_tool_error():
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp_server.server import _as_tool_result

    async def failing():
        return json.dumps({"status": "error", "error": {"code": "timeout", "message": "x"}})

    async def passing():
        return json.dumps({"status": "ok", "data": 1})

    with pytest.raises(ToolError):
        asyncio.run(_as_tool_result(failing)())
    assert json.loads(asyncio.run(_as_tool_result(passing)())) == {"status": "ok", "data": 1}


def test_wrapper_keeps_the_handler_signature_for_context_injection():
    import inspect

    from mcp_server.server import _as_tool_result
    from mcp_server.tools import wait_for

    assert "ctx" in inspect.signature(_as_tool_result(wait_for)).parameters


def test_engine_timeout_inside_an_ok_envelope_is_detected():
    from mcp_server.tools import _engine_failure

    wrapped = {"status": "ok", "data": {"status": "ok", "result": {"status": "error", "error": "timeout after 2s"}}}
    assert _engine_failure(wrapped) == "timeout after 2s"
    assert _engine_failure({"status": "ok", "data": {"status": "ok", "result": {"status": "ok"}}}) is None


def test_reset_session_default_does_not_wipe_the_whole_profile(monkeypatch):
    from mcp_server import tools

    sent = []

    class _Target:
        async def evaluate(self, js):
            return {"result": "example.test"}

        async def _send_command(self, method, params=None, **_):
            sent.append(method)
            if method == "Network.getAllCookies":
                return {"cookies": [{"name": "a", "domain": "example.test", "path": "/"}]}
            return {}

    async def fake_target():
        return _Target(), None

    monkeypatch.setattr(tools, "_target", fake_target)
    out = json.loads(asyncio.run(tools.browser_reset_session()))
    assert out["status"] == "ok" and out["data"]["scope"] == "site"
    assert "Network.clearBrowserCookies" not in sent
    assert "Network.deleteCookies" in sent


def test_network_block_acts_on_this_session_tab(monkeypatch):
    from mcp_server import tools

    called = {}

    class _Target:
        async def set_network_block(self, patterns):
            called["patterns"] = patterns
            return {"status": "ok"}

    async def fake_target():
        return _Target(), (lambda op, fn, *a, **kw: fn(*a, **kw))

    monkeypatch.setattr(tools, "_target", fake_target)
    asyncio.run(tools.network_block(patterns=["ads"]))
    assert called["patterns"] == ["ads"]


def test_documented_error_codes_cover_the_codes_the_handlers_return():
    doc = (ROOT / "docs" / "mcp-server.md").read_text(encoding="utf-8")
    table_codes = set(re.findall(r"^\| `([a-z_]+)`", doc, re.M))
    table_codes |= set(c for group in re.findall(r"^\| `([a-z_]+)` / `([a-z_]+)`", doc, re.M) for c in group)
    emitted = set()
    for path in (ROOT / "src" / "mcp_server").glob("*.py"):
        emitted |= set(re.findall(r'(?:tool_error|_wait_failure)\([^,]+,\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    must_document = {"timeout", "element_not_found", "stale_snapshot", "origin_not_allowed", "tab_not_found",
                     "invalid_params", "no_such_option", "not_select", "still_loading", "error_page",
                     "chrome_unavailable", "operation_failed", "wait_for_timeout", "not_actionable",
                     "tab_closed", "blocked_challenge"}
    assert must_document <= table_codes, f"undocumented: {sorted(must_document - table_codes)}"
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "mcp_server").glob("*.py"))
    missing = {c for c in must_document if f'"{c}"' not in source and f"'{c}'" not in source}
    assert not missing, f"documented but not in the code: {sorted(missing)}"


def test_legacy_all_scope_still_clears_the_cache(monkeypatch):
    from mcp_server import tools

    cleared = {}

    class _Target:
        async def evaluate(self, js):
            return {"result": "https://example.test/page"}

        async def _send_command(self, method, params=None, **_):
            return {"cookies": []} if method == "Network.getCookies" else {}

        async def clear_browser_cache(self):
            cleared["cache"] = True

    async def fake_target():
        return _Target(), None

    monkeypatch.setattr(tools, "_target", fake_target)
    out = json.loads(asyncio.run(tools.browser_reset_session(scope="all")))
    assert out["data"]["cleared"]["cache"] is True and cleared == {"cache": True}


def test_browser_navigate_result_urls_are_redacted(monkeypatch):
    from mcp_server import tools

    class _Target:
        async def add_script_to_evaluate_on_new_document(self, js):
            return {}

        async def navigate(self, url, **kw):
            return {"status": "ok", "url": url, "tab_id": "t"}

    async def fake_target():
        return _Target(), (lambda op, fn, *a, **kw: fn(*a, **kw))

    monkeypatch.setattr(tools, "_target", fake_target)
    out = json.loads(asyncio.run(tools.browser_navigate(url="https://a.test/cb?token=SECRET#access_token=X")))
    assert "SECRET" not in json.dumps(out) and "X" not in out["data"]["url"].split("#")[1].split("=")[1]


def test_site_reset_removes_every_path_of_the_site_and_keeps_other_sites(monkeypatch):
    from mcp_server import tools

    jar = [
        {"name": "a", "domain": "site.test", "path": "/admin"},
        {"name": "b", "domain": ".site.test", "path": "/shop"},
        {"name": "c", "domain": "other.test", "path": "/"},
    ]
    deleted = []

    class _Target:
        async def evaluate(self, js):
            return {"result": "site.test"}

        async def _send_command(self, method, params=None, **_):
            if method == "Network.getAllCookies":
                return {"cookies": jar}
            if method == "Network.deleteCookies":
                deleted.append(params["name"])
            return {}

    removed = asyncio.run(tools._clear_site_cookies(_Target()))
    assert removed == 2 and sorted(deleted) == ["a", "b"]


def test_challenge_pages_are_recognised_and_normal_pages_are_not():
    from mcp_server.tools import is_challenge_page

    assert is_challenge_page("Just a moment...", "")
    assert is_challenge_page("Upwork", "Cloudflare Ray ID: 8a1 Your IP: 1.2.3.4")
    assert not is_challenge_page("Blog", "We use Cloudflare Ray ID headers. " + "x" * 3000)
    assert not is_challenge_page("Home", "Welcome back")


def _challenge_target(title, text):
    class _Target:
        async def evaluate(self, js):
            return {"result": json.dumps({"title": title, "url": "https://a.test/?token=SECRET", "text": text})}

    return _Target()


def test_challenge_is_reported_as_blocked_then_cleared(monkeypatch):
    from mcp_server import tools

    tools._MCP_SESSION["challenge"] = None
    blocked, cleared = asyncio.run(tools._challenge_gate("navigate", _challenge_target("Just a moment...", "")))
    env = json.loads(blocked)
    assert env["error"]["code"] == "blocked_challenge" and "SECRET" not in blocked
    assert env["data"]["url"].startswith("https://a.test/") and cleared is False
    again, cleared = asyncio.run(tools._challenge_gate("navigate", _challenge_target("Dashboard", "hello")))
    assert again is None and cleared is True
    _, cleared = asyncio.run(tools._challenge_gate("navigate", _challenge_target("Dashboard", "hello")))
    assert cleared is False


def test_get_page_text_refuses_a_challenge_page(monkeypatch):
    from mcp_server import tools

    class _Target:
        async def evaluate(self, js):
            return {"result": json.dumps({"title": "Just a moment...", "url": "https://a.test/", "text": ""})}

        async def wait_for_ready(self, t):
            return {}

        async def get_page_text(self):
            raise AssertionError("must not read a challenge page as content")

    async def fake_target():
        return _Target(), (lambda op, fn, *a, **kw: fn(*a, **kw))

    monkeypatch.setattr(tools, "_target", fake_target)
    out = json.loads(asyncio.run(tools.get_page_text()))
    assert out["status"] == "error" and out["error"]["code"] == "blocked_challenge"


def test_a_replaced_tab_is_reported_once_in_meta_notices():
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp_server import tools
    from mcp_server.server import _as_tool_result

    async def handler():
        return json.dumps({"status": "ok", "data": 1, "meta": {}})

    tools._NOTICES.clear()
    tools._NOTICES.append({"code": "tab_replaced", "old_tab_id": "A", "new_tab_id": "B"})
    first = json.loads(asyncio.run(_as_tool_result(handler)()))
    assert first["meta"]["notices"][0]["new_tab_id"] == "B"
    second = json.loads(asyncio.run(_as_tool_result(handler)()))
    assert "notices" not in second["meta"]

    async def failing():
        return json.dumps({"status": "error", "error": {"code": "x", "message": "m"}})

    tools._NOTICES.append({"code": "tab_closed"})
    with pytest.raises(ToolError) as err:
        asyncio.run(_as_tool_result(failing)())
    assert "tab_closed" in str(err.value)


async def _no_target():
    return object(), None


def test_a_tab_seen_earlier_and_now_gone_is_tab_closed_not_unknown(monkeypatch):
    import main
    from mcp_server import tools

    class _Resp:
        body = json.dumps({"error": {"code": "tab_not_found", "message": "Tab T1 is not open"}}).encode()

    async def gone(tab_id, source=None):
        return _Resp()

    monkeypatch.setattr(main, "_assert_tab_exists", gone)
    monkeypatch.setattr(tools, "_target", _no_target)
    tools._SEEN_TABS["T1"] = {"title": "Jobs", "url": "https://a.test/jobs?token=SECRET"}
    out = json.loads(asyncio.run(tools._tab_pinned_client("T1")))
    assert out["error"]["code"] == "tab_closed" and "SECRET" not in json.dumps(out)
    other = json.loads(asyncio.run(tools._tab_pinned_client("NEVER")))
    assert other["error"]["code"] == "tab_not_found"


def test_an_unreachable_browser_is_not_reported_as_a_closed_tab(monkeypatch):
    import main
    from mcp_server import tools

    class _Resp:
        body = json.dumps({"error": {"code": "browser_unreachable", "message": "Cannot list tabs: refused"}}).encode()

    async def down(tab_id, source=None):
        return _Resp()

    monkeypatch.setattr(main, "_assert_tab_exists", down)
    monkeypatch.setattr(tools, "_target", _no_target)
    tools._SEEN_TABS["T2"] = {"title": "x", "url": "https://a.test/"}
    out = json.loads(asyncio.run(tools._tab_pinned_client("T2")))
    assert out["error"]["code"] == "browser_unreachable"


def test_tab_existence_is_checked_through_the_session_client(monkeypatch):
    import main
    from mcp_server import tools

    seen = {}
    marker = object()

    async def fake_target():
        return marker, None

    async def check(tab_id, source=None):
        seen["source"] = source

        class _Resp:
            body = json.dumps({"error": {"code": "tab_not_found", "message": "gone"}}).encode()

        return _Resp()

    monkeypatch.setattr(tools, "_target", fake_target)
    monkeypatch.setattr(main, "_assert_tab_exists", check)
    asyncio.run(tools._tab_pinned_client("X"))
    assert seen["source"] is marker  # not the module-level default client (wrong port over stdio)
