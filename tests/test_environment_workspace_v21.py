"""Acceptance tests for reusable environment recipes and dashboard workspace."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from environment_store import EnvironmentStore
from main import app

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_store_persists_safe_versioned_environment(tmp_path: Path) -> None:
    store = EnvironmentStore(tmp_path / "environments.json")
    item = store.create({
        "name": "Daily QA",
        "runtime": "visible",
        "profile": "qa-profile",
        "proxy_strategy": "round-robin",
        "tags": ["qa", "daily"],
    })
    assert item["schema_version"] == 1
    assert item["environment_id"].startswith("env_")
    assert EnvironmentStore(tmp_path / "environments.json").get(item["environment_id"])["name"] == "Daily QA"
    assert "secret" not in str(item).lower()


def test_store_rejects_secret_fields_and_invalid_references(tmp_path: Path) -> None:
    store = EnvironmentStore(tmp_path / "environments.json")
    for payload in (
        {"name": "Bad", "runtime": "visible", "api_key": "hidden"},
        {"name": "Bad", "runtime": "unknown"},
        {"name": "", "runtime": "visible"},
    ):
        try:
            store.create(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"payload should fail: {payload}")


def test_environment_api_crud_and_active_context(tmp_path: Path, monkeypatch) -> None:
    from main import environment_store
    monkeypatch.setattr(environment_store, "path", tmp_path / "environments.json")
    environment_store._items = {}
    environment_store._active_id = None
    with TestClient(app) as client:
        created = client.post("/api/v1/environments", json={"name": "Local QA", "runtime": "visible"})
        assert created.status_code == 201
        env = created.json()["data"]
        listed = client.get("/api/v1/environments").json()["data"]
        assert listed["count"] == 1
        activated = client.post(f"/api/v1/environments/{env['environment_id']}/activate")
        assert activated.status_code == 200
        assert activated.json()["data"]["active"] is True
        assert client.delete(f"/api/v1/environments/{env['environment_id']}").status_code == 409


def test_dashboard_exposes_accessible_environment_workspace() -> None:
    assert 'data-workspace="environments"' in HTML
    assert 'id="environment-list"' in HTML
    assert 'id="environment-name"' in HTML
    assert 'id="environment-runtime"' in HTML
    assert 'aria-live="polite"' in HTML
    assert "loadEnvironments" in JS
    assert "activateEnvironment" in JS
    assert "environment_activated" in JS
