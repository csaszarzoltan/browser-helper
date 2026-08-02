"""Acceptance coverage for privacy-safe run detail and comparison."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app, run_store
from run_comparison import compare_runs

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_compare_runs_reports_truthful_field_differences() -> None:
    left = {"run_id": "run_left", "operation": "navigate", "status": "success", "verification": "verified", "duration_ms": 10.0, "details": "ok"}
    right = {"run_id": "run_right", "operation": "navigate", "status": "error", "verification": "failed", "duration_ms": 25.5, "details": "token=hidden"}
    result = compare_runs(left, right)
    assert result["schema_version"] == 1
    assert result["duration_delta_ms"] == 15.5
    assert result["differences"]["status"]["changed"] is True
    assert result["differences"]["operation"]["changed"] is False
    assert "details" not in str(result).lower()
    assert "hidden" not in str(result)


def test_compare_api_returns_stable_contract_and_missing_404() -> None:
    run_store.clear()
    left = run_store.record("observe", "success", 10, "safe", verification="verified")
    right = run_store.record("observe", "error", 14, "password=hidden", verification="failed")
    with TestClient(app) as client:
        response = client.get(f"/api/v1/runs/compare?left={left['run_id']}&right={right['run_id']}")
        missing = client.get(f"/api/v1/runs/compare?left={left['run_id']}&right=run_missing")
    assert response.status_code == 200
    assert response.json()["data"]["left"]["run_id"] == left["run_id"]
    assert "hidden" not in str(response.json())
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "run_not_found"


def test_dashboard_has_accessible_run_detail_and_comparison() -> None:
    assert 'id="run-detail-panel"' in HTML
    assert 'id="run-compare-panel"' in HTML
    assert 'id="run-compare-left"' in HTML
    assert 'id="run-compare-right"' in HTML
    assert 'aria-live="polite"' in HTML
    assert "loadRunDetail" in JS
    assert "compareSelectedRuns" in JS
    assert "run_comparison_loaded" in JS


def test_run_comparison_ui_does_not_render_detail_payload() -> None:
    assert "comparison.details" not in JS
    assert "left.details" not in JS
    assert "right.details" not in JS
