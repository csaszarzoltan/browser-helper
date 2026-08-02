"""TDD acceptance coverage for the v2.18 daily work launchpad."""
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from daily_launchpad import build_daily_launchpad
from main import app, run_store

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_builder_prioritizes_actionable_safe_daily_context():
    result = build_daily_launchpad(
        environments=[{"environment_id": "env_daily", "name": "Daily QA", "runtime": "visible", "active": True, "password": "must-not-leak"}],
        workflows=[{"workflow_id": "wf_1", "name": "Smoke test", "version": 3, "steps": [{"action": "navigate"}], "parameters": []}],
        runs=[
            {"run_id": "run_failed", "operation": "navigate", "status": "error", "verification": "unverified", "duration_ms": 12, "timestamp": "2026-08-02T10:00:00Z", "details": "token=secret"},
            {"run_id": "run_ok", "operation": "screenshot", "status": "success", "verification": "verified", "duration_ms": 20, "timestamp": "2026-08-02T09:00:00Z", "details": "private page content"},
        ],
        connected=True,
        tab_count=2,
    )
    assert result["schema_version"] == 1
    assert result["next_action"]["id"] == "review_failures"
    assert result["active_environment"] == {"environment_id": "env_daily", "name": "Daily QA", "runtime": "visible"}
    assert result["recent_workflows"][0]["step_count"] == 1
    assert result["attention_runs"][0]["run_id"] == "run_failed"
    assert "details" not in result["attention_runs"][0]
    assert "password" not in str(result)
    assert "must-not-leak" not in str(result)
    assert "token=secret" not in str(result)


def test_builder_guides_disconnected_and_unconfigured_users():
    result = build_daily_launchpad(environments=[], workflows=[], runs=[], connected=False, tab_count=0)
    assert result["next_action"]["id"] == "connect_browser"
    assert result["summary"]["saved_workflows"] == 0
    assert result["summary"]["attention_runs"] == 0


def test_dashboard_contains_accessible_launchpad_and_responsive_styles():
    assert 'id="daily-launchpad"' in HTML
    assert 'aria-labelledby="daily-launchpad-title"' in HTML
    assert 'id="launchpad-next-action"' in HTML
    assert 'id="launchpad-workflows"' in HTML
    assert 'id="launchpad-attention"' in HTML
    assert '.daily-launchpad-grid' in CSS
    assert '@media' in CSS


def test_launchpad_client_has_loading_error_empty_and_navigation_states():
    assert "loadDailyLaunchpad" in JS
    assert "/api/v1/launchpad" in JS
    assert "launchpad_load_failed" in JS
    assert "launchpad_action_selected" in JS
    assert "No saved workflows yet" in JS
    assert "No runs need attention" in JS


@pytest.mark.asyncio
async def test_launchpad_api_returns_bounded_privacy_safe_data():
    run_store.clear()
    run_store.record("navigate", "error", 10, "password=hunter2", verification="unverified")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/launchpad")
    assert response.status_code == 200
    payload = response.json()
    assert payload["operation"] == "daily_launchpad"
    assert payload["data"]["summary"]["attention_runs"] == 1
    assert len(payload["data"]["attention_runs"]) <= 5
    assert "hunter2" not in response.text
