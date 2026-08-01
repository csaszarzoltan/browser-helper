"""TDD acceptance tests for safe, actionable run recovery guidance."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app, run_store
from run_recovery import RecoveryAdvisor

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_recovery_advisor_distinguishes_transport_and_verification_failure() -> None:
    advisor = RecoveryAdvisor()
    transport = advisor.advise({"operation": "navigate", "status": "error", "verification": "unverified", "details": "timeout"})
    verification = advisor.advise({"operation": "click", "status": "success", "verification": "failed", "details": "Still editing"})
    assert transport["category"] == "execution_failure"
    assert transport["retry_safety"] == "review"
    assert "connection" in " ".join(transport["steps"]).lower() or "retry" in " ".join(transport["steps"]).lower()
    assert verification["category"] == "verification_failure"
    assert verification["retry_safety"] == "review"
    assert "evidence" in " ".join(verification["steps"]).lower()


def test_recovery_advisor_marks_read_only_operations_safe() -> None:
    advisor = RecoveryAdvisor()
    advice = advisor.advise({"operation": "screenshot", "status": "error", "verification": "unverified", "details": "timeout"})
    assert advice["retry_safety"] == "safe"
    assert advice["recommended_action"] == "retry"


def test_recovery_advisor_never_echoes_sensitive_details() -> None:
    advisor = RecoveryAdvisor()
    advice = advisor.advise({"operation": "navigate", "status": "error", "verification": "unverified", "details": "token=private-value"})
    assert "private-value" not in str(advice)


def test_recovery_api_returns_guidance_and_missing_404() -> None:
    run_store.clear()
    run = run_store.record("screenshot", "error", 12, "timeout")
    with TestClient(app) as client:
        response = client.get(f"/api/v1/runs/{run['run_id']}/recovery")
        missing = client.get("/api/v1/runs/run_missing/recovery")
    assert response.status_code == 200
    assert response.json()["data"]["retry_safety"] == "safe"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "run_not_found"


def test_recovery_ui_contract_is_accessible_and_non_automatic() -> None:
    assert 'id="recovery-guidance"' in HTML
    assert 'id="run-recovery-result"' in HTML
    assert "loadRunRecovery" in JS
    assert "Recovery guidance" in JS
    assert "run_recovery_loaded" in JS
    assert "run-recovery-result" in JS
    assert "Retry now" not in JS
