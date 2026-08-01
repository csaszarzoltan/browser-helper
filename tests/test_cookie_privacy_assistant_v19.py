"""TDD acceptance tests for privacy-safe cookie diagnostics."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_cookie_panel_has_search_summary_and_safe_export():
    for element_id in (
        "cookie-search", "cookie-secure-filter", "cookie-visible-summary",
        "cookie-export-metadata", "cookie-clear", "cookie-empty-filtered",
    ):
        assert f'id="{element_id}"' in HTML


def test_cookie_values_are_masked_in_renderer():
    start = HTML.index("function renderCookies(cookies)")
    end = HTML.index("function shortVal", start)
    source = HTML[start:end]
    assert "BrowserHelperCookies.render" in source
    assert "title=\"${escHtml(value)}\"" not in source


def test_cookie_filtering_is_non_destructive():
    assert "currentCookies" in JS
    assert "filterCookies" in JS
    assert "currentCookies.filter" in JS
    assert "currentCookies.splice" not in JS


def test_cookie_metadata_export_excludes_values():
    assert "exportCookieMetadata" in JS
    assert "redactCookieMetadata" in JS
    assert "cookie-metadata-" in JS
    redact_start = JS.index("const redactCookieMetadata")
    redact_end = JS.index("};", redact_start)
    assert "value:" not in JS[redact_start:redact_end]


def test_cookie_clear_confirmation_is_delegated_once():
    assert 'id="cookie-clear"' in HTML
    assert 'data-confirm="Clear all cookies from the connected browser?"' in HTML
    start = HTML.index("function clearCookies()")
    end = HTML.index("//  SCRIPT RUNNER", start)
    assert "confirm(" not in HTML[start:end]


def test_cookie_privacy_copy_is_explicit():
    assert "Cookie values are masked" in HTML
    assert "Metadata export never includes cookie values" in HTML
