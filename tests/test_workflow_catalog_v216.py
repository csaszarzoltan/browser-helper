"""Acceptance coverage for durable, parameterized workflow catalog."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from workflow_catalog import WorkflowCatalog

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")

SAMPLE = {
    "name": "Open target",
    "description": "Navigate to a supplied URL and capture evidence.",
    "steps": [
        {"action": "navigate", "url": "{{target_url}}"},
        {"action": "screenshot", "quality": 80},
    ],
    "parameters": [
        {"name": "target_url", "type": "url", "required": True},
    ],
}


def test_catalog_versions_workflows_and_persists(tmp_path: Path) -> None:
    catalog = WorkflowCatalog(tmp_path / "workflows.json")
    first = catalog.create(SAMPLE)
    second = catalog.create_version(first["workflow_id"], {**SAMPLE, "description": "Updated"})
    assert first["version"] == 1
    assert second["version"] == 2
    assert WorkflowCatalog(tmp_path / "workflows.json").get(first["workflow_id"])["version"] == 2
    assert len(catalog.versions(first["workflow_id"])) == 2


def test_parameter_resolution_is_typed_and_secret_safe(tmp_path: Path) -> None:
    catalog = WorkflowCatalog(tmp_path / "workflows.json")
    item = catalog.create({
        **SAMPLE,
        "steps": [{"action": "form_fill", "fields": [{"selector": "#token", "text": "{{api_secret}}"}]}],
        "parameters": [{"name": "api_secret", "type": "secret", "required": True}],
    })
    resolved = catalog.resolve(item["workflow_id"], {"api_secret": "private-value"})
    assert resolved["steps"][0]["fields"][0]["text"] == "private-value"
    assert resolved["recorded_parameters"]["api_secret"] == "[REDACTED]"
    assert "private-value" not in str(resolved["recorded_parameters"])


def test_catalog_rejects_invalid_placeholders_and_parameters(tmp_path: Path) -> None:
    catalog = WorkflowCatalog(tmp_path / "workflows.json")
    bad = {**SAMPLE, "steps": [{"action": "navigate", "url": "{{missing}}"}]}
    try:
        catalog.create(bad)
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("undefined placeholder should fail")


def test_workflow_api_create_version_resolve_and_archive(tmp_path: Path, monkeypatch) -> None:
    from main import workflow_catalog
    monkeypatch.setattr(workflow_catalog, "path", tmp_path / "workflows.json")
    workflow_catalog._workflows = {}
    with TestClient(app) as client:
        created = client.post("/api/v1/workflows", json=SAMPLE)
        assert created.status_code == 201
        workflow = created.json()["data"]
        resolved = client.post(f"/api/v1/workflows/{workflow['workflow_id']}/resolve", json={"parameters": {"target_url": "https://example.com"}})
        assert resolved.status_code == 200
        assert resolved.json()["data"]["steps"][0]["url"] == "https://example.com"
        version = client.post(f"/api/v1/workflows/{workflow['workflow_id']}/versions", json={**SAMPLE, "description": "v2"})
        assert version.json()["data"]["version"] == 2
        archived = client.post(f"/api/v1/workflows/{workflow['workflow_id']}/archive")
        assert archived.json()["data"]["archived"] is True


def test_dashboard_has_accessible_workflow_catalog() -> None:
    assert 'id="workflow-catalog"' in HTML
    assert 'id="workflow-catalog-list"' in HTML
    assert 'id="workflow-name"' in HTML
    assert 'id="workflow-parameter-panel"' in HTML
    assert "loadWorkflowCatalog" in JS
    assert "resolveWorkflowParameters" in JS
    assert "workflow_catalog_loaded" in JS
