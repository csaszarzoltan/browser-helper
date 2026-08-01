"""TDD acceptance tests for a redacted per-run support bundle."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app, run_store
from run_timeline import RunStore

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_run_store_get_returns_copy_and_missing_is_none() -> None:
    store = RunStore(max_runs=5)
    recorded = store.record("navigate", "success", 3, "ok")
    loaded = store.get(recorded["run_id"])
    assert loaded == recorded
    assert loaded is not recorded
    assert store.get("run_missing") is None


def test_support_bundle_is_versioned_redacted_and_context_safe() -> None:
    run_store.clear()
    recorded = run_store.record("navigate", "error", 12, "token=private-value")
    with TestClient(app) as client:
        response = client.get(f"/api/v1/runs/{recorded['run_id']}/support")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    bundle = body["data"]
    assert bundle["schema_version"] == 1
    assert bundle["run"]["run_id"] == recorded["run_id"]
    assert "private-value" not in str(bundle)
    assert "capability_summary" in bundle
    assert "browser_context" in bundle
    assert "cookies" not in str(bundle).lower()


def test_support_bundle_missing_run_is_404() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/runs/run_missing/support")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


def test_timeline_support_download_ui_contract() -> None:
    assert 'id="run-support-guidance"' in HTML
    assert "downloadRunSupportBundle" in JS
    assert "support.json" in JS
    assert "run_support_exported" in JS
    assert "Support JSON" in JS
