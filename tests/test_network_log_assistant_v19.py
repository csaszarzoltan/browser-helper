"""TDD acceptance tests for privacy-aware network diagnostics."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_network_panel_has_capture_filter_and_export_controls():
    for element_id in (
        "network-start", "network-stop", "network-clear", "network-capture-status",
        "network-search", "network-method-filter", "network-status-filter",
        "network-export-json", "network-export-csv", "network-visible-summary",
        "network-empty-filtered",
    ):
        assert f'id="{element_id}"' in HTML


def test_network_filtering_is_non_destructive():
    assert "filterNetworkRequests" in JS
    assert "networkRequests.filter" in JS
    assert "networkRequests.splice" not in JS
    assert "renderFilteredNetworkLog" in JS


def test_network_exports_are_bounded_and_url_redacted():
    assert "sanitizeNetworkUrl" in JS
    assert "SENSITIVE_QUERY_KEYS" in JS
    assert "MAX_EXPORTED_NETWORK_ENTRIES" in JS
    assert "network-log-" in JS
    assert "application/json" in JS
    assert "text/csv" in JS


def test_existing_network_renderer_delegates_to_assistant():
    start = HTML.index("function renderNetworkLog()")
    end = HTML.index("function shortUrl", start)
    source = HTML[start:end]
    assert "window.BrowserHelperNetwork.render" in source


def test_capture_controls_report_state_and_refresh():
    assert "startNetworkCapture" in JS
    assert "stopNetworkCapture" in JS
    assert "setNetworkCaptureState" in JS
    assert "refreshNetworkLog" in JS


def test_network_controls_are_accessible_and_responsive():
    assert '<label for="network-search"' in HTML
    assert '<label for="network-method-filter"' in HTML
    assert '<label for="network-status-filter"' in HTML
    assert 'aria-live="polite"' in HTML
    assert '.network-diagnostics-toolbar' in CSS
    assert '.network-capture-status' in CSS
