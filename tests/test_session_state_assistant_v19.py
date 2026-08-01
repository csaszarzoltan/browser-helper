"""TDD acceptance tests for the privacy-safe session state assistant."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_session_manager_has_assistant_controls():
    for element_id in (
        "session-validate", "session-download", "session-import",
        "session-import-file", "session-clear-sensitive", "session-validation-status",
    ):
        assert f'id="{element_id}"' in HTML


def test_session_assistant_validates_expected_shape_and_size():
    assert "validateSessionState" in JS
    assert "MAX_SESSION_IMPORT_BYTES" in JS
    assert "cookies" in JS
    assert "localStorage" in JS
    assert "sessionStorage" in JS
    assert "must be a JSON object" in JS


def test_session_assistant_never_persists_session_payload():
    assert "browser-helper.session" not in JS
    assert "localStorage.setItem(SESSION" not in JS
    assert "sessionStorage.setItem(SESSION" not in JS
    assert "Session state is never stored by the dashboard" in HTML


def test_session_assistant_imports_and_exports_json_safely():
    assert "importSessionFile" in JS
    assert "downloadSessionState" in JS
    assert "application/json" in JS
    assert "session-state-" in JS
    assert "URL.revokeObjectURL" in JS


def test_restore_uses_shared_validation_and_confirmation():
    start = HTML.index("async function restoreSession()")
    end = HTML.index("//  JS CONSOLE", start)
    source = HTML[start:end]
    assert "window.BrowserHelperSession.validate" in source
    assert "window.confirm" in source
    assert "window.BrowserHelperSession.setBusy" in source


def test_session_status_has_accessible_states():
    assert 'aria-live="polite"' in HTML
    assert '.session-validation.success' in CSS
    assert '.session-validation.error' in CSS
    assert '.session-validation.warning' in CSS
