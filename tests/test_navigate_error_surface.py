"""A failed page load must surface as an error, not as status ok."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cdp_client import CDPClient, CDPError  # noqa: E402


class _Stub:
    """Just enough of CDPClient for navigate(): one Page.navigate reply."""

    # The real readiness helpers, so the tests exercise the production code.
    _document_state = CDPClient._document_state
    _wait_for_document = CDPClient._wait_for_document
    _WAIT_UNTIL_STATES = CDPClient._WAIT_UNTIL_STATES

    _connection_type = "remote"  # skips the tab-discovery sync after navigation
    _tabs_cache: list = []
    _tabs_cache_ts = 0
    _ws_tab_id = "tab"
    _active_tab_id = "tab"

    async def _activate_current(self):
        return None

    def __init__(self, reply: dict):
        self._reply = reply
        self._evaluations = 0

    async def _send_command(self, method, params=None, **_):
        if method == "Runtime.evaluate":
            # readyState is "complete"; timeOrigin changes once the navigation has
            # produced a new document, so the wait accepts the new page.
            self._evaluations += 1
            origin = 1.0 if self._evaluations == 1 else 2.0
            return {"result": {"value": f'["complete", {origin}]'}}
        assert method == "Page.navigate"
        return self._reply


def test_navigate_raises_when_chrome_reports_error_text():
    stub = _Stub({"frameId": "f1", "errorText": "net::ERR_INTERNET_DISCONNECTED"})
    with pytest.raises(CDPError, match="ERR_INTERNET_DISCONNECTED"):
        asyncio.run(CDPClient.navigate(stub, "https://example.com/"))


def test_navigate_returns_ok_when_no_error_text():
    stub = _Stub({"frameId": "f1"})
    out = asyncio.run(CDPClient.navigate(stub, "https://example.com/"))
    assert out["status"] == "ok"
    assert out["url"] == "https://example.com/"


class _NeverReady(_Stub):
    """Page never leaves 'loading'; the wait must give up and report it."""

    async def _send_command(self, method, params=None, **_):
        if method == "Runtime.evaluate":
            return {"result": {"value": '["loading", 1.0]'}}
        return await super()._send_command(method, params)


def test_navigate_times_out_when_page_never_loads():
    stub = _NeverReady({"frameId": "f1"})
    with pytest.raises(CDPError, match="did not reach domcontentloaded within 0.3s"):
        asyncio.run(CDPClient.navigate(stub, "https://example.com/", timeout=0.3))


def test_navigate_rejects_unknown_wait_until():
    stub = _Stub({"frameId": "f1"})
    with pytest.raises(ValueError, match="wait_until"):
        asyncio.run(CDPClient.navigate(stub, "https://example.com/", wait_until="networkidle"))
