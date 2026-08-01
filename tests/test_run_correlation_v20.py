"""TDD coverage for end-to-end run correlation and copyable run IDs."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app, log_operation, run_op, run_store

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_log_operation_reuses_run_id_in_legacy_entry() -> None:
    run_store.clear()
    fake_client = SimpleNamespace(is_connected=False, tabs_count=0)
    with patch("main.client", fake_client):
        entry = log_operation("navigate", "success", 8.2, "ok")
    assert entry["run_id"].startswith("run_")
    assert run_store.get(entry["run_id"])["operation"] == "navigate"


@pytest.mark.asyncio
async def test_run_op_returns_correlation_in_response_meta() -> None:
    method = AsyncMock(return_value={"url": "https://example.test"})
    with (
        patch("main.ensure_connected"),
        patch("main.broadcast_state", new=AsyncMock()),
        patch("main.client", SimpleNamespace(is_connected=True, tabs_count=1)),
    ):
        response = await run_op("navigate", method)
    assert response["status"] == "ok"
    assert response["meta"]["run_id"].startswith("run_")
    assert response["meta"]["verification"] == "unverified"


def test_single_run_api_contract() -> None:
    run_store.clear()
    item = run_store.record("click", "success", 4, "ok")
    with TestClient(app) as client:
        response = client.get(f"/api/v1/runs/{item['run_id']}")
    assert response.status_code == 200
    assert response.json()["data"]["run_id"] == item["run_id"]


def test_single_run_missing_is_404() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/runs/run_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


def test_timeline_displays_and_copies_run_id() -> None:
    assert 'id="run-correlation-guidance"' in HTML
    assert "copyRunId" in JS
    assert "Copy run ID" in JS
    assert "navigator.clipboard.writeText" in JS
    assert "run_id_copied" in JS
