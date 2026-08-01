"""TDD acceptance tests for privacy-safe guided run history."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_guided_flow_has_run_history_controls():
    assert 'id="guided-run-history"' in HTML
    assert 'id="guided-run-list"' in HTML
    assert 'id="guided-clear-runs"' in HTML
    assert 'id="guided-export-runs"' in HTML


def test_run_history_is_session_scoped_and_bounded():
    assert "browser-helper.guided-runs" in JS
    assert "sessionStorage.getItem" in JS
    assert "sessionStorage.setItem" in JS
    assert "MAX_GUIDED_RUNS" in JS
    assert "localStorage.setItem(GUIDED_RUNS_KEY" not in JS


def test_each_run_has_correlation_and_timing_fields():
    assert "crypto.randomUUID" in JS
    assert "run_id" in JS
    assert "started_at" in JS
    assert "duration_ms" in JS
    assert "outcome" in JS


def test_run_history_can_retry_and_export_redacted_json():
    assert "retryGuidedRun" in JS
    assert "exportGuidedRuns" in JS
    assert "guided-runs-" in JS
    assert "application/json" in JS
    assert "redactRun" in JS


def test_run_history_has_accessible_status_styles():
    assert 'aria-label="Guided run history"' in HTML
    assert '.guided-run-status.success' in CSS
    assert '.guided-run-status.error' in CSS
    assert '.guided-run-status.running' in CSS
