"""Smoke tests for the dashboard HTML (static/index.html).

Covers:
- File exists and is readable
- Basic HTML structure (doctype, html, head, body)
- Title element
- WebSocket connection JavaScript code is present
- Essential UI elements (status indicators, cards, action buttons)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

DASHBOARD_PATH = Path(__file__).parent.parent / "static" / "index.html"


# ─── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def dashboard_html() -> str:
    """Read the dashboard HTML once per session."""
    assert DASHBOARD_PATH.is_file(), f"Dashboard not found at {DASHBOARD_PATH}"
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# ─── File existence ──────────────────────────────────────────────────

class TestDashboardFile:
    """The dashboard HTML file exists and is non-empty."""

    def test_file_exists(self):
        assert DASHBOARD_PATH.is_file()

    def test_file_is_readable(self):
        content = DASHBOARD_PATH.read_text(encoding="utf-8")
        assert len(content) > 0


# ─── Basic HTML structure ────────────────────────────────────────────

class TestDashboardStructure:
    """Basic HTML document structure."""

    def test_has_doctype(self, dashboard_html):
        assert dashboard_html.startswith("<!DOCTYPE html>") or \
               dashboard_html.startswith("<!doctype html>")

    def test_has_html_tag(self, dashboard_html):
        assert "<html" in dashboard_html
        assert "</html>" in dashboard_html

    def test_has_head_tag(self, dashboard_html):
        assert "<head>" in dashboard_html or "<head " in dashboard_html
        assert "</head>" in dashboard_html

    def test_has_body_tag(self, dashboard_html):
        assert "<body>" in dashboard_html or "<body " in dashboard_html
        assert "</body>" in dashboard_html

    def test_has_title(self, dashboard_html):
        assert "<title>" in dashboard_html
        assert "</title>" in dashboard_html
        # Extract title content
        start = dashboard_html.index("<title>") + len("<title>")
        end = dashboard_html.index("</title>")
        title = dashboard_html[start:end].strip()
        assert len(title) > 0
        assert "Browser" in title or "Dashboard" in title or "Helper" in title


# ─── WebSocket connectivity ──────────────────────────────────────────

class TestDashboardWebSocket:
    """The dashboard includes WebSocket client code."""

    def test_has_websocket_connect(self, dashboard_html):
        """Should attempt to connect to /ws endpoint."""
        assert "WebSocket" in dashboard_html or "new WebSocket" in dashboard_html

    def test_has_websocket_url(self, dashboard_html):
        """Should reference the /ws path."""
        assert "/ws" in dashboard_html or "ws://" in dashboard_html or "wss://" in dashboard_html

    def test_has_onmessage_handler(self, dashboard_html):
        """Should handle incoming WS messages."""
        assert "onmessage" in dashboard_html

    def test_has_onclose_handler(self, dashboard_html):
        """Should handle WS disconnection."""
        assert "onclose" in dashboard_html

    def test_has_reconnect_logic(self, dashboard_html):
        """Should attempt to reconnect on disconnect using scheduleReconnect."""
        assert "scheduleReconnect" in dashboard_html or "setTimeout" in dashboard_html


# ─── Essential UI elements ───────────────────────────────────────────

class TestDashboardUI:
    """The dashboard contains essential UI widgets."""

    def test_has_connection_status_indicator(self, dashboard_html):
        """Should show connection status (green/red dot)."""
        assert "connected" in dashboard_html.lower()
        assert "status" in dashboard_html.lower()

    def test_has_tab_count_indicator(self, dashboard_html):
        """Should show the number of open tabs."""
        assert "tab" in dashboard_html.lower()

    def test_has_operation_log(self, dashboard_html):
        """Should have a log/recent operations view."""
        assert "log" in dashboard_html.lower() or "operation" in dashboard_html.lower()

    def test_has_action_section(self, dashboard_html):
        """Should have action buttons/controls."""
        assert "action" in dashboard_html.lower() or "control" in dashboard_html.lower() or \
               "button" in dashboard_html

    def test_has_url_input(self, dashboard_html):
        """Should have a navigate/URL input."""
        assert "navigate" in dashboard_html.lower() or "url" in dashboard_html.lower()

    def test_has_screenshot_capability(self, dashboard_html):
        """Should have a screenshot button or reference."""
        assert "screenshot" in dashboard_html.lower()

    def test_has_script_tag(self, dashboard_html):
        """Should contain at least one <script> tag."""
        assert "<script" in dashboard_html
        assert "</script>" in dashboard_html


# ─── Meta tags and assets ───────────────────────────────────────────

class TestDashboardMeta:
    """Meta tags and external assets."""

    def test_has_viewport_meta(self, dashboard_html):
        assert 'name="viewport"' in dashboard_html or \
               "name='viewport'" in dashboard_html

    def test_has_charset_meta(self, dashboard_html):
        assert 'charset="UTF-8"' in dashboard_html or \
               "charset='UTF-8'" in dashboard_html or \
               'charset="utf-8"' in dashboard_html


# ─── Rendering safety ───────────────────────────────────────────────

class TestDashboardSafety:
    """The HTML should be safe (no hardcoded credentials, no obvious issues)."""

    def test_no_hardcoded_api_keys(self, dashboard_html):
        """Should not contain hardcoded API tokens or secrets."""
        # Exclude environment variable references
        lines_with_token = [line for line in dashboard_html.splitlines()
                            if "token" in line.lower() and "api_token" not in line.lower()
                            and "API_TOKEN" not in line]
        assert len(lines_with_token) == 0, f"Possible hardcoded token: {lines_with_token}"

    def test_no_localhost_links_unless_ws(self, dashboard_html):
        """Should not contain hardcoded absolute localhost URLs
        (WebSocket URL construction is fine)."""
        # Exclude WebSocket URL patterns and font-awesome CDN, etc.
        import re
        localhost_urls = re.findall(r'https?://localhost[\:\d]*[/\w\-\.]*', dashboard_html, re.IGNORECASE)
        # WS URLs with localhost are expected (WebSocket connection)
        non_ws_urls = [u for u in localhost_urls if "ws" not in u.lower()]
        assert len(non_ws_urls) == 0, f"Hardcoded absolute localhost URLs: {non_ws_urls}"
