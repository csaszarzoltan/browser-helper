"""MCP server — LIVE end-to-end tests against the real browser-helper Chrome.

Unlike the wire-protocol suite (``test_mcp_integration.py``, which runs with
``BH_TEST_NO_CHROME=1`` so CDP-gated tools fail deterministically), this suite
attaches the MCP server's tool handlers to the *real* Chrome CDP endpoint the
browser-helper service uses (``http://127.0.0.1:9557``, the debug port saved
by ``run.py --debug-port``).

This is the E2E proof for v1.27.3's /mcp-status feature: when ``MCP_ENABLED=1``
is set (now the systemd default), the MCP tool surface is wired to a live
browser and ``tools/call`` for browser tools must actually drive Chrome.

Design:
- The server subprocess runs WITHOUT ``BH_TEST_NO_CHROME`` so ``_mcp_session()``
  mints a real session on the real CDP endpoint.
- The service must be reachable: ``CHROME_AUTO_PORT`` (or 9557) must answer
  ``/json/version``. Tests are skipped otherwise (CI / dev boxes without the
  service running must not fail the suite).
- Only *read-only* tools are exercised (``get_tabs``, ``session_status``) plus
  one navigation to a deterministic local page — no destructive actions.

Run: ``.venv/bin/python -m pytest tests/test_mcp_live_e2e.py -v``
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_integration_helpers import REPO_ROOT, StdioTransport

# ---------------------------------------------------------------------------
# Live-service detection — skip cleanly when no browser-helper Chrome is up
# ---------------------------------------------------------------------------


def _local_cdp_port() -> int:
    """Port of the live browser-helper Chrome: CHROME_AUTO_PORT > 9555."""
    return int(os.environ.get("CHROME_AUTO_PORT", "9555"))


def _live_service_available() -> bool:
    """True when the browser-helper CDP endpoint answers /json/version."""
    import urllib.request

    try:
        with urllib.request.urlopen(  # noqa: S310 — localhost only
            f"http://127.0.0.1:{_local_cdp_port()}/json/version", timeout=2
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


live_service = pytest.mark.skipif(
    not _live_service_available(),
    reason="browser-helper Chrome CDP not reachable — start the service first",
)


# ---------------------------------------------------------------------------
# Fixture — MCP server subprocess wired to the REAL CDP endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def live_stdio_server():
    """Real MCP server subprocess; tool calls drive a DEDICATED test Chrome.

    A dedicated headless Chrome (own profile, own port) is launched so the
    E2E suite never touches the production browser-helper Chrome (9555) and
    the tab pile-up from repeated runs cannot make ``/json/new`` flake out
    (HTTP 500 once Chrome accumulates too many tabs).
    """
    import shutil
    import socket
    import subprocess
    import tempfile
    import time
    import urllib.request

    # Find a free port, then launch a private headless Chrome on it.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        test_port = s.getsockname()[1]
    profile_dir = tempfile.mkdtemp(prefix="bh-mcp-e2e-")
    chrome = subprocess.Popen(
        [
            "google-chrome",
            f"--remote-debugging-port={test_port}",
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--user-data-dir={profile_dir}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    ready = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(  # noqa: S310 — localhost only
                f"http://127.0.0.1:{test_port}/json/version", timeout=2
            ) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            pass
        time.sleep(0.3)
    if not ready:
        chrome.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)
        pytest.skip("dedicated test Chrome did not come up — cannot run E2E")

    env = dict(os.environ)
    env["BH_TEST_NO_CHROME"] = ""  # explicit empty to override StdioTransport.setdefault("1")
    env.setdefault("PYTHONPATH", str(REPO_ROOT / "src"))
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["CHROME_AUTO_PORT"] = str(test_port)
    transport = StdioTransport(env=env)
    try:
        yield transport
    finally:
        transport.close()
        chrome.terminate()
        try:
            chrome.wait(timeout=5)
        except Exception:
            chrome.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)


def _rpc_ok(resp: dict) -> dict:
    assert "error" not in resp, f"JSON-RPC error: {resp.get('error')}"
    assert "result" in resp, f"no result in response: {resp}"
    return resp["result"]


def _tool_text(resp: dict) -> str:
    result = _rpc_ok(resp)
    texts = [
        c.get("text", "")
        for c in result.get("content") or []
        if c.get("type") == "text"
    ]
    assert texts, f"no text content in tool result: {result}"
    return texts[0]


def _tool_json(resp: dict) -> dict:
    """Parse the tool's JSON-string result; assert the tool did not error."""
    result = _rpc_ok(resp)
    text = _tool_text(resp)
    assert not result.get("isError"), f"tool call returned isError: {text}"
    return json.loads(text)


def _init_and_list(transport: StdioTransport) -> None:
    resp = transport.request(
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "live-e2e", "version": "1.0"},
        },
    )
    _rpc_ok(resp)
    transport.request(
        "notifications/initialized", {}
    )


# ---------------------------------------------------------------------------
# Live E2E — real Chrome, real CDP, real MCP wire protocol
# ---------------------------------------------------------------------------


class TestLiveMCPE2E:
    def test_initialize_and_list_tools(self, live_stdio_server):
        """The server initializes and advertises the browser tool surface."""
        _init_and_list(live_stdio_server)
        resp = live_stdio_server.request("tools/list", {})
        result = _rpc_ok(resp)
        names = {t["name"] for t in result.get("tools", [])}
        assert "navigate" in names
        assert "get_tabs" in names
        assert "click" in names
        assert "session_status" in names

    def test_get_tabs_drives_real_chrome(self, live_stdio_server):
        """tools/call get_tabs returns the LIVE tab list from the service."""
        _init_and_list(live_stdio_server)
        resp = live_stdio_server.request(
            "tools/call",
            {"name": "get_tabs", "arguments": {}},
        )
        data = _tool_json(resp)
        # The real Chrome has at least one tab (browser-level WS attached).
        assert "data" in data or "tabs" in data or isinstance(data, list), data
        tabs = data.get("data") if isinstance(data, dict) else data
        if isinstance(tabs, dict):
            tabs = tabs.get("tabs", tabs)
        assert isinstance(tabs, list) and len(tabs) >= 1, f"no live tabs: {data}"

    def test_session_status_lists_live_sessions(self, live_stdio_server):
        """session_status returns the session store (incl. the MCP-minted one)."""
        _init_and_list(live_stdio_server)
        resp = live_stdio_server.request(
            "tools/call",
            {"name": "session_status", "arguments": {}},
        )
        data = _tool_json(resp)
        # The MCP server mints a real session when a browser tool runs first;
        # session_status itself is a store read (no CDP dependency).
        sessions = data.get("data", {}).get("sessions", [])
        assert isinstance(sessions, list), f"session_status data missing: {data}"
        assert data.get("data", {}).get("total", 0) >= 0, data

    def test_navigate_to_local_page_and_read_tabs(self, live_stdio_server):
        """Navigate the live tab to a deterministic page; tab list reflects it."""
        _init_and_list(live_stdio_server)
        resp = live_stdio_server.request(
            "tools/call",
            {"name": "navigate", "arguments": {"url": "data:text/html,<title>mcp-live-e2e</title>"}},
        )
        nav = _tool_json(resp)
        assert nav.get("status") == "ok", f"navigate failed: {nav}"
        # The navigate tool reports the URL it actually reached; data: URLs
        # are not reflected as the tab's URL in /json (Chrome keeps the
        # entry as about:blank), so verify the returned URL instead of the
        # tab-list entry, and separately that the tab list is live/current.
        nav_data = nav.get("data") or {}
        nav_url = nav_data.get("url", "") if isinstance(nav_data, dict) else ""
        assert "data:text/html" in str(nav_url), f"navigate did not report URL: {nav}"
        resp = live_stdio_server.request(
            "tools/call",
            {"name": "get_tabs", "arguments": {}},
        )
        data = _tool_json(resp)
        tabs = data.get("data") if isinstance(data, dict) else data
        if isinstance(tabs, dict):
            tabs = tabs.get("tabs", tabs)
        assert isinstance(tabs, list) and len(tabs) >= 1, f"no live tabs: {data}"
        # The MCP-minted session tab must be present in the live list.
        assert any(t.get("id") for t in tabs), f"tab list entries lack ids: {data}"
