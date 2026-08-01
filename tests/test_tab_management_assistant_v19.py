"""TDD acceptance tests for safer, faster tab management."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_tabs_panel_has_search_open_and_summary_controls():
    for element_id in (
        "tab-search", "tab-new-url", "tab-open", "tab-visible-summary", "tab-empty-filtered",
    ):
        assert f'id="{element_id}"' in HTML


def test_tab_assistant_validates_new_tab_urls():
    assert "normalizeTabUrl" in JS
    assert "Only HTTP and HTTPS addresses are supported" in JS
    assert "openValidatedTab" in JS
    assert "apiPost('/tab/new'" in JS


def test_tabs_are_filtered_without_mutating_source_collection():
    assert "currentTabs" in JS
    assert "filterTabs" in JS
    assert "currentTabs.filter" in JS
    assert "currentTabs.splice" not in JS


def test_dynamic_close_buttons_have_confirmation_and_accessible_names():
    start = HTML.index("function renderTabs(tabs)")
    end = HTML.index("async function switchTab", start)
    source = HTML[start:end]
    assert "data-confirm=" in source
    assert "aria-label=" in source
    assert "Close tab" in source
    assert "Switch to tab" in source


def test_tab_switch_updates_context_and_refreshes_tabs():
    start = HTML.index("async function switchTab(tabId)")
    end = HTML.index("async function closeTab", start)
    source = HTML[start:end]
    assert "refreshTabs()" in source
    assert "BrowserHelperTabs.announceSwitch" in source


def test_tab_assistant_has_accessible_responsive_styles():
    assert '<label for="tab-search"' in HTML
    assert '<label for="tab-new-url"' in HTML
    assert 'aria-live="polite"' in HTML
    assert '.tab-management-toolbar' in CSS
    assert '.tab-management-summary' in CSS
