"""TDD acceptance tests for the guided daily browser workflow."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_live_browser_has_guided_action_composer():
    assert 'id="guided-action-card"' in HTML
    assert 'id="guided-url"' in HTML
    assert 'id="guided-navigate"' in HTML
    assert 'id="guided-screenshot"' in HTML
    assert 'id="guided-observe"' in HTML
    assert 'id="guided-result"' in HTML


def test_guided_url_is_accessibly_labelled_and_validated():
    assert '<label for="guided-url"' in HTML
    assert 'type="url"' in HTML
    assert 'aria-describedby="guided-url-help guided-url-error"' in HTML
    assert 'id="guided-url-error"' in HTML


def test_guided_flow_has_recent_urls_without_storing_page_content():
    assert 'browser-helper.recent-urls' in JS
    assert 'MAX_RECENT_URLS' in JS
    assert 'saveRecentUrl' in JS
    assert 'renderRecentUrls' in JS
    assert 'localStorage.setItem(RECENT_URLS_KEY' in JS


def test_guided_flow_uses_existing_api_contracts_and_busy_states():
    assert "apiPost('/navigate'" in JS
    assert "apiPost('/screenshot'" in JS
    assert "apiPost('/agent/observe'" in JS
    assert 'setGuidedBusy' in JS
    assert 'aria-busy' in JS


def test_guided_flow_exposes_clear_feedback_and_keyboard_submit():
    assert 'showGuidedResult' in JS
    assert "event.key === 'Enter'" in JS
    assert 'guided-result.success' in CSS
    assert 'guided-result.error' in CSS
