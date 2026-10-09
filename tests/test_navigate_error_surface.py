"""A failed page load must surface as an error, not as status ok."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cdp_client import CDPClient, CDPError  # noqa: E402


class _Stub:
    """Just enough of CDPClient for navigate(): one Page.navigate reply."""

    _connection_type = "remote"  # skips the tab-discovery sync after navigation
    _tabs_cache: list = []
    _tabs_cache_ts = 0
    _ws_tab_id = "tab"
    _active_tab_id = "tab"

    def __init__(self, reply: dict):
        self._reply = reply

    async def _activate_current(self):
        return None

    async def _send_command(self, method, params=None, **_):
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
