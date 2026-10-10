"""Safety rules of the MCP surface: URL and cookie redaction, the origin allowlist, the profile report."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_token_like_url_parameters_are_hidden_and_others_kept():
    from mcp_server.tools import redact_url

    assert redact_url("https://a.test/x?token=abc123&page=2") == "https://a.test/x?token=[redacted]&page=2"
    assert redact_url("https://a.test/x?session_id=s1#frag") == "https://a.test/x?session_id=[redacted]#frag"
    assert redact_url("https://a.test/x?q=hello") == "https://a.test/x?q=hello"
    assert redact_url("https://a.test/plain") == "https://a.test/plain"


def test_navigate_refuses_an_origin_outside_the_allowlist(monkeypatch):
    from mcp_server import tools

    monkeypatch.setenv("BH_ALLOWED_ORIGINS", "https://example.com")
    out = json.loads(asyncio.run(tools.navigate("https://evil.test/")))
    assert out["error"]["code"] == "origin_not_allowed"


def test_allowlist_is_off_when_the_variable_is_unset(monkeypatch):
    from mcp_server import tools

    monkeypatch.delenv("BH_ALLOWED_ORIGINS", raising=False)
    assert tools._origin_allowlist() is None


def test_allowed_origin_matches_scheme_host_and_port_only():
    from mcp_server import tools

    allow = ["https://example.com"]
    assert tools._origin_allowed("https://example.com/any/path?x=1", allow)
    assert not tools._origin_allowed("http://example.com/", allow)
    assert not tools._origin_allowed("https://example.com.evil.test/", allow)


def test_cookie_values_are_redacted_unless_asked(monkeypatch):
    from mcp_server import tools

    class _Target:
        async def get_cookies(self):
            return {"cookies": [{"name": "sid", "value": "SECRET", "domain": "a.test"}]}

    async def fake_resolve(session_id):
        return _Target(), None

    monkeypatch.setattr(tools, "_resolve_cookie_target", fake_resolve)
    hidden = json.loads(asyncio.run(tools.export_cookies()))["data"]
    assert hidden["cookies"][0]["value"] == "[redacted]" and hidden["values_redacted"] is True
    shown = json.loads(asyncio.run(tools.export_cookies(include_values=True)))["data"]
    assert shown["cookies"][0]["value"] == "SECRET"


def test_token_in_the_url_fragment_is_hidden_too():
    from mcp_server.tools import redact_url

    assert redact_url("https://a.test/cb#access_token=SECRET&state=ok") == "https://a.test/cb#access_token=[redacted]&state=ok"
    assert redact_url("https://a.test/p#section") == "https://a.test/p#section"


def test_act_navigate_is_checked_against_the_origin_allowlist(monkeypatch):
    from mcp_server import tools

    monkeypatch.setenv("BH_ALLOWED_ORIGINS", "https://example.com")
    out = json.loads(asyncio.run(tools.act(action="navigate", url="https://evil.test/x")))
    assert out["error"]["code"] == "origin_not_allowed"
    out = json.loads(asyncio.run(tools.act(action="navigate", url="https://evil.test/x", snapshot_id="s")))
    assert out["error"]["code"] == "origin_not_allowed"
