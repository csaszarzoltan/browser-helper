"""TDD acceptance coverage for the unified, privacy-safe run timeline."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app, run_store
from run_timeline import RunStore

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_run_store_redacts_and_bounds_records() -> None:
    store = RunStore(max_runs=2)
    store.record("navigate", "success", 12.5, "token=abc&url=https://example.test")
    store.record("click", "error", 4, "Authorization: Bearer abc")
    store.record("observe", "success", 8, "password=hunter2")
    data = store.list_runs()
    assert len(data) == 2
    assert all("abc" not in str(item) and "hunter2" not in str(item) for item in data)
    assert data[0]["operation"] == "observe"


def test_run_records_have_stable_contract() -> None:
    store = RunStore(max_runs=5)
    item = store.record("screenshot", "success", 7.345, "captured")
    assert item["run_id"].startswith("run_")
    assert item["status"] == "success"
    assert item["duration_ms"] == 7.34
    assert item["verification"] == "unverified"
    assert item["schema_version"] == 1


def test_run_api_lists_and_clears_records() -> None:
    run_store.clear()
    run_store.record("navigate", "success", 10, "ok")
    with TestClient(app) as client:
        listed = client.get("/api/v1/runs")
        cleared = client.delete("/api/v1/runs")
    assert listed.status_code == 200
    assert listed.json()["data"]["count"] == 1
    assert cleared.status_code == 200
    assert cleared.json()["data"]["cleared"] == 1


def test_run_timeline_dashboard_contract() -> None:
    assert 'id="run-timeline-card"' in HTML
    assert 'id="run-timeline-list"' in HTML
    assert 'id="run-status-filter"' in HTML
    assert 'id="refresh-run-timeline"' in HTML
    assert 'id="clear-run-timeline"' in HTML


def test_run_timeline_ui_loads_filters_and_handles_failure() -> None:
    assert "'/api/v1/runs'" in JS
    assert "loadRunTimeline" in JS
    assert "renderRunTimeline" in JS
    assert "run_timeline_load_failed" in JS
    assert "run-status-filter" in JS
