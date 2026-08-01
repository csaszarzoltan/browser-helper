"""TDD acceptance tests for the diagnostics operation-log assistant."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_operation_log_has_filter_export_and_summary_controls():
    for element_id in (
        "log-search", "log-status-filter", "log-export-json", "log-export-csv",
        "log-visible-summary", "log-empty-filtered",
    ):
        assert f'id="{element_id}"' in HTML


def test_log_assistant_filters_without_mutating_source_log():
    assert "filterOperationLog" in JS
    assert "operationLog.filter" in JS
    assert "operationLog.splice" not in JS
    assert "renderFilteredOperationLog" in JS


def test_log_export_is_redacted_and_bounded():
    assert "redactOperationEntry" in JS
    assert "MAX_EXPORTED_LOG_ENTRIES" in JS
    assert "MAX_EXPORTED_DETAIL_CHARS" in JS
    assert "operation-log-" in JS
    assert "text/csv" in JS
    assert "application/json" in JS


def test_log_assistant_integrates_with_existing_renderer():
    start = HTML.index("function renderLogTable()")
    end = HTML.index("function escHtml", start)
    source = HTML[start:end]
    assert "window.BrowserHelperDiagnostics.render" in source


def test_log_search_is_keyboard_accessible_and_announced():
    assert '<label for="log-search"' in HTML
    assert '<label for="log-status-filter"' in HTML
    assert 'aria-live="polite"' in HTML
    assert '.diagnostics-toolbar' in CSS
    assert '.diagnostics-summary' in CSS


def test_clear_log_requires_confirmation_once():
    assert 'id="log-clear"' in HTML
    assert 'data-confirm="Clear the in-memory operation log?"' in HTML
    start = HTML.index("function clearLog()")
    end = HTML.index("function renderLogTable()", start)
    assert "confirm(" not in HTML[start:end]
