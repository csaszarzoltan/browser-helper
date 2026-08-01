"""Acceptance tests for capability readiness and richer execution context."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from capability_registry import CapabilityRegistry, CapabilityStatus
from main import PUBLIC_PATHS, app

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_registry_exposes_sorted_safe_capabilities() -> None:
    registry = CapabilityRegistry.default()
    payload = registry.as_dict()
    assert payload["schema_version"] == 1
    assert payload["summary"]["total"] == len(payload["capabilities"])
    assert [item["id"] for item in payload["capabilities"]] == sorted(
        item["id"] for item in payload["capabilities"]
    )
    assert all("secret" not in str(item).lower() for item in payload["capabilities"])


def test_registry_marks_incomplete_domains_experimental() -> None:
    registry = CapabilityRegistry.default()
    by_id = {item.id: item for item in registry.capabilities}
    assert by_id["browser.core"].status is CapabilityStatus.READY
    assert by_id["anti_detection.compositor"].status is CapabilityStatus.EXPERIMENTAL
    assert by_id["behavioral.scroll"].status is CapabilityStatus.EXPERIMENTAL
    assert by_id["cloud.camofox"].status is CapabilityStatus.UNAVAILABLE
    assert by_id["cloud.camofox"].reason


def test_capability_api_returns_versioned_contract() -> None:
    assert "/api/v1/capabilities" in PUBLIC_PATHS
    with TestClient(app) as client:
        response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["operation"] == "capability_readiness"
    assert body["data"]["schema_version"] == 1
    assert body["data"]["summary"]["total"] >= 5


def test_dashboard_has_readiness_card_and_detailed_context() -> None:
    assert 'id="capability-readiness-card"' in HTML
    assert 'id="capability-summary"' in HTML
    assert 'id="context-target"' in HTML
    assert 'id="context-last-operation"' in HTML
    assert 'id="refresh-capabilities"' in HTML


def test_dashboard_fetches_and_renders_capability_readiness_accessibly() -> None:
    assert "'/api/v1/capabilities'" in JS
    assert "loadCapabilityReadiness" in JS
    assert "renderCapabilityReadiness" in JS
    assert "aria-label" in JS
    assert "capability_load_failed" in JS


def test_context_bridge_uses_target_and_last_operation() -> None:
    assert "data.cdp_url" in JS
    assert "data.last_operation" in JS
    assert "context-target" in JS
    assert "context-last-operation" in JS
