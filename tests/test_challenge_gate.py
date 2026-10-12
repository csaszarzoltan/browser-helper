"""The bot-check gate must say when it could not read a page, and must cover a pinned read.

Reported 2026-10-12: a Cloudflare block page (short body, "Cloudflare Ray ID" text) came back
as status ok. The detector matches that text; the gate hid its own failures as "not blocked".
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BLOCK_TEXT = "Cloudflare Ray ID: a4973aabbcbdd266\n\nYour IP: 144.91.73.225\n\n© 2015 - 2026 Upwork® Global Inc."


class _Page:
    """A page client with the shape the gate and get_page_text use."""

    def __init__(self, title="www.upwork.com", text=BLOCK_TEXT, fail=None):
        self.title, self.text, self.fail = title, text, fail

    async def evaluate(self, js):
        if self.fail is not None:
            raise self.fail
        return {"status": "ok", "type": "string", "result": json.dumps(
            {"title": self.title, "url": "https://www.upwork.com/freelancers/x", "text": self.text})}

    async def wait_for_ready(self, timeout):
        return {}

    async def get_page_text(self):
        return {"status": "ok", "text": self.text, "length": len(self.text)}


def test_the_block_page_text_is_a_challenge_even_under_a_plain_title():
    from mcp_server.tools import is_challenge_page

    assert is_challenge_page("www.upwork.com", BLOCK_TEXT)


def test_a_page_that_cannot_be_read_is_reported_unchecked_not_blocked_and_not_clear(caplog):
    from mcp_server import tools

    caplog.set_level(logging.WARNING)
    blocked, cleared, check = asyncio.run(tools._challenge_gate("navigate", _Page(fail=TimeoutError())))
    assert blocked is None and cleared is False
    assert check.startswith("unavailable: TimeoutError")
    assert any("could not read the page" in record.message for record in caplog.records)


def test_a_page_with_no_content_yet_is_reported_unchecked(monkeypatch):
    from mcp_server import tools

    blocked, cleared, check = asyncio.run(tools._challenge_gate("navigate", _Page(title="", text="")))
    assert blocked is None and cleared is False
    assert check == "unavailable: the page has no content yet"


def test_an_unreadable_check_keeps_an_earlier_block_in_place(monkeypatch):
    # Not seeing the page is not the same as the challenge being gone.
    from mcp_server import tools

    monkeypatch.setitem(tools._MCP_SESSION, "challenge", "https://www.upwork.com/x")
    blocked, cleared, check = asyncio.run(tools._challenge_gate("navigate", _Page(fail=TimeoutError())))
    assert blocked is None and cleared is False and check
    assert tools._MCP_SESSION["challenge"] == "https://www.upwork.com/x"


def test_a_read_by_tab_id_is_gated_like_the_session_tab(monkeypatch):
    from mcp_server import tools

    async def fake_target():
        return object(), (lambda op, method, *a, **kw: method(*a, **kw))

    async def fake_pinned(tab_id):
        return _Page()

    monkeypatch.setattr(tools, "_target", fake_target)
    monkeypatch.setattr(tools, "_tab_pinned_client", fake_pinned)
    monkeypatch.setitem(tools._MCP_SESSION, "challenge", None)
    out = asyncio.run(tools.get_page_text(wait_ready=False, tab_id="ABC"))
    assert "blocked_challenge" in out
    assert BLOCK_TEXT not in out
