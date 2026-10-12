"""Tabs must not close while an agent or a person still uses them.

Two reapers closed live tabs: the MCP liveness probe read a busy page or an open
JavaScript dialog as a dead tab, and the session was then replaced (which closes
its tab); the orphan sweep closed every unowned page tab, not only about:blank.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class _Client:
    def __init__(self, listed: bool, silent: bool):
        self._tabs_cache = []
        self._tabs_cache_ts = 0
        self._listed = listed
        self._silent = silent

    async def discover_tabs(self):
        return [{"id": "t1", "type": "page", "url": "http://x/"}] if self._listed else []

    async def _send_command(self, method, params):
        if self._silent:
            await asyncio.sleep(60)
        return {"result": {}}


def _probe(monkeypatch, listed: bool, silent: bool) -> bool:
    from mcp_server import tools

    monkeypatch.setattr(tools, "_PROBE_TIMEOUT_S", 0.05, raising=False)
    sess = SimpleNamespace(client=_Client(listed, silent), tab_id="t1", session_id="s")
    return asyncio.run(tools._session_tab_alive(sess))


def test_a_listed_tab_that_does_not_answer_is_not_treated_as_closed(monkeypatch):
    # A busy page or an open JavaScript dialog never answers Runtime.evaluate, but the
    # tab is still there. Replacing the session would close the page the agent is using.
    assert _probe(monkeypatch, listed=True, silent=True) is True


def test_a_tab_missing_from_the_list_is_gone(monkeypatch):
    assert _probe(monkeypatch, listed=False, silent=False) is False


def test_a_listed_tab_that_answers_is_alive(monkeypatch):
    assert _probe(monkeypatch, listed=True, silent=False) is True


def test_the_orphan_sweep_closes_only_blank_tabs(monkeypatch):
    import httpx

    from session_registry import SessionRegistry

    tabs = [
        {"id": "owned", "type": "page", "url": "https://owned.test/"},
        {"id": "user", "type": "page", "url": "https://upwork.test/jobs"},
        {"id": "popup", "type": "page", "url": "https://login.test/oauth"},
        {"id": "blank", "type": "page", "url": "about:blank"},
    ]
    closed: list[str] = []

    def handler(request):
        if request.url.path == "/json":
            return httpx.Response(200, json=tabs)
        if request.url.path.startswith("/json/close/"):
            closed.append(request.url.path.rsplit("/", 1)[1])
            return httpx.Response(200, text="Target is closing")
        return httpx.Response(404)

    real_client = httpx.AsyncClient

    def client(**_kwargs):
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    reg = SessionRegistry(ttl=1800.0, max_sessions=15)
    reg._sessions["s"] = SimpleNamespace(tab_id="owned")
    assert asyncio.run(reg._reap_orphan_tabs("http://127.0.0.1:9")) == 1
    assert closed == ["blank"]


def test_an_mcp_session_in_use_is_refreshed_and_not_reaped_as_idle(monkeypatch):
    # MCP calls reuse their session without SessionRegistry.get(), so last_seen stayed at
    # creation time and the idle reaper closed the agent's tab 30 minutes later, mid-task.
    import time

    import main
    from mcp_server import tools
    from session_registry import Session, SessionRegistry

    monkeypatch.delenv("BH_TEST_NO_CHROME", raising=False)
    reg = SessionRegistry(ttl=1800.0, max_sessions=15)
    sess = Session(session_id="mcp", client=_Client(listed=True, silent=False), tab_id="t1",
                   last_seen=time.monotonic() - 3600)
    reg._sessions["mcp"] = sess
    monkeypatch.setattr(main, "session_registry", reg)
    monkeypatch.setitem(tools._MCP_SESSION, "session", sess)
    asyncio.run(tools._mcp_session())
    assert time.monotonic() - sess.last_seen < 60
    assert asyncio.run(reg.cleanup()) == 0 and "mcp" in reg._sessions
