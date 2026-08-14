"""Unit tests for the visual regression endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

from main import VisualRegressionRequest, agent_visual_regression


@pytest.fixture
def fake_client():
    client = AsyncMock()
    client.navigate = AsyncMock(return_value={"status": "ok"})
    client.wait_for_ready = AsyncMock(return_value={"status": "ok"})
    client.screenshot = AsyncMock(return_value={"status": "ok", "data": "aGVsbG8="})
    return client


def _fake_diff(**kw):
    return type(
        "DiffResult", (), {
            "passed": kw.get("passed", True),
            "pixel_delta": kw.get("pixel_delta", 0.0),
            "dimensions_match": kw.get("dimensions_match", True),
            "diff_image": kw.get("diff_image", ""),
            "error": kw.get("error", None),
        }
    )()


@pytest.mark.asyncio
async def test_vr_record_saves_baselines(fake_client):
    req = VisualRegressionRequest(urls=["https://a.com", "https://b.com"], record=True, wait_timeout=5)
    with patch("main.client", fake_client), \
         patch("main._get_current_session", return_value=None), \
         patch("main.run_op", new=AsyncMock(return_value={"status": "ok"})), \
         patch("main.baseline_mgr.save_baseline", return_value="/tmp/bl.png") as save:
        resp = await agent_visual_regression(req)
    assert resp["status"] == "ok"
    assert resp["data"]["mode"] == "record"
    assert save.call_count == 2
    assert all(u["recorded"] for u in resp["data"]["urls"])


@pytest.mark.asyncio
async def test_vr_compare_pass_and_fail(fake_client):
    req = VisualRegressionRequest(urls=["https://a.com", "https://b.com"], record=False, wait_timeout=5)
    with patch("main.client", fake_client), \
         patch("main._get_current_session", return_value=None), \
         patch("main.run_op", new=AsyncMock(return_value={"status": "ok"})), \
         patch("main.baseline_mgr.get_baseline", side_effect=["/tmp/bl.png", None]), \
         patch("screenshot_diff.ScreenshotDiffEngine.diff",
               side_effect=[_fake_diff(passed=True, pixel_delta=0.0),
                            _fake_diff(passed=False, pixel_delta=0.5)]):
        resp = await agent_visual_regression(req)
    urls = resp["data"]["urls"]
    assert urls[0]["status"] == "pass"
    assert urls[1]["status"] == "no_baseline"
    assert resp["data"]["failed"] == 1


@pytest.mark.asyncio
async def test_vr_compare_missing_baseline(fake_client):
    req = VisualRegressionRequest(urls=["https://a.com"], record=False, wait_timeout=5)
    with patch("main.client", fake_client), \
         patch("main._get_current_session", return_value=None), \
         patch("main.run_op", new=AsyncMock(return_value={"status": "ok"})), \
         patch("main.baseline_mgr.get_baseline", return_value=None):
        resp = await agent_visual_regression(req)
    assert resp["data"]["urls"][0]["status"] == "no_baseline"
    assert resp["data"]["status"] == "failed"
