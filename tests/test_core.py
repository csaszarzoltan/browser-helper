"""Tests for browser-helper CDP client."""
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx
import pytest
from cdp_client import CDPClient, CDPError


# Skip tests that need a Chrome-free environment when Chrome is actually running
def _chrome_is_running() -> bool:
    """Check if a Chrome CDP endpoint is reachable."""
    try:
        httpx.get("http://127.0.0.1:9555/json", timeout=2)
        return True
    except Exception:
        return False


CHROME_RUNNING = _chrome_is_running()


# ─── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Return a fresh CDPClient (no real connection)."""
    return CDPClient(cdp_http_url="http://127.0.0.1:9555")


# ─── Init tests ─────────────────────────────────────────────────────

class TestInit:
    def test_default_url(self):
        c = CDPClient()
        assert c.cdp_http_url == "http://127.0.0.1:9555"

    def test_custom_url(self):
        c = CDPClient(cdp_http_url="http://localhost:9222")
        assert c.cdp_http_url == "http://localhost:9222"

    def test_trailing_slash_stripped(self):
        c = CDPClient(cdp_http_url="http://localhost:9222/")
        assert c.cdp_http_url == "http://localhost:9222"

    def test_initial_state(self, client):
        assert client.is_connected is False
        assert client.tabs_count == 0
        assert client._network_monitoring is False
        assert client._network_entries == []


# ─── Connection tests (mock) ────────────────────────────────────────

class TestConnection:
    @pytest.mark.skipif(CHROME_RUNNING, reason="Chrome is already running on this machine")
    @pytest.mark.asyncio
    async def test_connect_no_chrome(self, client):
        """Should raise CDPError when Chrome is not running."""
        with pytest.raises((CDPError, Exception)):
            await client.connect()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, client):
        """Disconnect should not crash when not connected."""
        await client.disconnect()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_double_disconnect(self, client):
        """Calling close() twice should be safe."""
        await client.close()
        await client.close()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_send_command_when_not_connected(self, client):
        """Should raise CDPError."""
        with pytest.raises(CDPError, match="Not connected"):
            await client._send_command("Page.navigate", {"url": "http://example.com"})


# ─── Method tests (mock-based, no real Chrome) ──────────────────────

class TestMethods:
    @pytest.mark.asyncio
    async def test_navigate_when_not_connected(self, client):
        """Should fail gracefully."""
        with pytest.raises(CDPError):
            await client.navigate("http://example.com")

    @pytest.mark.asyncio
    async def test_evaluate_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.evaluate("1+1")

    @pytest.mark.asyncio
    async def test_click_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.click(".button")

    @pytest.mark.asyncio
    async def test_type_text_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.type_text("input", "hello")

    @pytest.mark.asyncio
    async def test_screenshot_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.screenshot()

    @pytest.mark.asyncio
    async def test_pdf_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.pdf()

    @pytest.mark.asyncio
    async def test_get_cookies_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.get_cookies()

    @pytest.mark.asyncio
    async def test_get_page_text_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.get_page_text()


# ─── New feature tests ──────────────────────────────────────────────

class TestNewFeatures:
    @pytest.mark.asyncio
    async def test_full_page_screenshot_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.full_page_screenshot()

    @pytest.mark.asyncio
    async def test_element_screenshot_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.element_screenshot(".main")

    @pytest.mark.asyncio
    async def test_dom_query_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.dom_query("a")

    @pytest.mark.asyncio
    async def test_execute_script_when_not_connected(self, client):
        """Should return error results, not raise, because execute_script catches exceptions internally."""
        result = await client.execute_script([{"action": "eval", "params": {"js": "1+1"}}])
        assert result["status"] == "ok"
        assert result["steps"] == 1
        assert result["results"][0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_performance_metrics_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.get_performance_metrics()

    @pytest.mark.asyncio
    async def test_session_save_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.session_save()

    @pytest.mark.asyncio
    async def test_session_restore_when_not_connected(self, client):
        """Should return gracefully without raising — session_restore handles disconnection internally."""
        result = await client.session_restore({"cookies": [], "localStorage": {}})
        assert result["status"] == "ok"
        assert "restored" in result

    def test_network_monitoring_initially_off(self, client):
        assert client._network_monitoring is False
        assert client._network_entries == []

    @pytest.mark.asyncio
    async def test_network_stop_when_not_started(self, client):
        """Stop should work even if not started — no-op when not monitoring."""
        result = await client.stop_network_monitoring()
        assert result == {"status": "ok", "monitoring": False}
        assert client._network_monitoring is False

    @pytest.mark.asyncio
    async def test_clear_network_log(self, client):
        """Should not crash even if empty."""
        n = client._network_entries  # just ensure attribute exists
        assert isinstance(n, list)


# ─── Edge cases ─────────────────────────────────────────────────────

class TestEdgeCases:
    def test_cdp_http_url_format(self):
        """Various URL formats should work."""
        cases = [
            ("http://127.0.0.1:9555", "http://127.0.0.1:9555"),
            ("http://127.0.0.1:9555/", "http://127.0.0.1:9555"),
            ("http://localhost:9222", "http://localhost:9222"),
            ("http://192.168.1.100:9222", "http://192.168.1.100:9222"),
        ]
        for url, expected in cases:
            c = CDPClient(cdp_http_url=url)
            assert c.cdp_http_url == expected

    def test_initial_tabs_empty_list(self, client):
        assert client._tabs == []

    def test_tab_count_no_tabs(self, client):
        assert client.tabs_count == 0

    def test_multiple_clients_isolation(self):
        a = CDPClient("http://localhost:9222")
        b = CDPClient("http://127.0.0.1:9555")
        assert a.cdp_http_url != b.cdp_http_url
