"""TDD acceptance tests for truthful operation verification status."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from main import infer_verification, run_op, run_store

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")


def test_infer_verification_recognizes_explicit_outcomes() -> None:
    assert infer_verification({"verified": True}) == "verified"
    assert infer_verification({"verified": False}) == "failed"
    assert infer_verification({"verification": {"verified": True}}) == "verified"
    assert infer_verification({"confirmation": {"state_change": {"changed": True}}}) == "verified"
    assert infer_verification({"confirmation": {"state_change": {"changed": False}}}) == "failed"


def test_infer_verification_does_not_invent_success() -> None:
    assert infer_verification({"status": "ok"}) == "unverified"
    assert infer_verification("clicked") == "unverified"
    assert infer_verification(None) == "unverified"


@pytest.mark.asyncio
async def test_run_op_propagates_verified_result_to_meta_and_store() -> None:
    run_store.clear()
    method = AsyncMock(return_value={"verified": True, "actual_text": "Saved"})
    with (
        patch("main.ensure_connected"),
        patch("main.broadcast_state", new=AsyncMock()),
        patch("main.client", SimpleNamespace(is_connected=True, tabs_count=1)),
    ):
        response = await run_op("click", method)
    assert response["meta"]["verification"] == "verified"
    assert run_store.get(response["meta"]["run_id"])["verification"] == "verified"


@pytest.mark.asyncio
async def test_run_op_propagates_failed_verification_without_transport_failure() -> None:
    run_store.clear()
    method = AsyncMock(return_value={"verified": False, "actual_text": "Still editing"})
    with (
        patch("main.ensure_connected"),
        patch("main.broadcast_state", new=AsyncMock()),
        patch("main.client", SimpleNamespace(is_connected=True, tabs_count=1)),
    ):
        response = await run_op("click", method)
    assert response["status"] == "ok"
    assert response["meta"]["verification"] == "failed"
    assert run_store.get(response["meta"]["run_id"])["status"] == "success"


def test_timeline_has_verification_filter_and_explanation() -> None:
    assert 'id="run-verification-filter"' in HTML
    assert 'id="verification-guidance"' in HTML
    assert "run-verification-filter" in JS
    assert "verified" in JS
    assert "unverified" in JS
