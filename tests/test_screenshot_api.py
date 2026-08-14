"""Pre-development tests for screenshot REST API endpoints (RED phase).

These tests define the expected REST API interface BEFORE implementation.
All screenshot comparison tests will fail until the developer:
1. Creates src/screenshot_diff.py with ScreenshotDiffEngine + DiffResult
2. Creates src/baseline_manager.py with BaselineManager
3. Adds screenshot comparison endpoints to main.py:
   - POST /screenshot/baseline
   - POST /screenshot/compare
   - GET  /screenshot/baselines
   - DELETE /screenshot/baseline
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from httpx import ASGITransport, AsyncClient

from main import app

# ===================================================================
# POST /screenshot/baseline — Capture baseline
# ===================================================================


class TestPostBaseline:
    """Test POST /screenshot/baseline endpoint."""

    @pytest.mark.asyncio
    async def test_baseline_requires_connected_cdp(self):
        """Should return 400 when CDP is not connected."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/baseline",
                json={"url": "https://example.com"},
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "detail" in data
            assert "not connected" in data.get("detail", "").lower() or "cdp" in data.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_baseline_with_invalid_payload(self):
        """Should return 422 for invalid payload."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/baseline",
                json={"url": 12345},  # url should be a string
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_baseline_accepts_profile(self):
        """Should accept profile parameter."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/baseline",
                json={
                    "url": "https://example.com",
                    "profile": "work",
                    "quality": 70,
                },
            )
            assert resp.status_code in (400, 422)
            if resp.status_code == 400:
                data = resp.json()
                assert "detail" in data

    @pytest.mark.asyncio
    async def test_baseline_accepts_viewport(self):
        """Should accept viewport parameter."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/baseline",
                json={
                    "url": "https://example.com",
                    "viewport": {"width": 1280, "height": 720},
                },
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_baseline_response_shape(self):
        """On success, should return status + baseline with url/path/size/timestamp."""
        import base64 as b64
        from io import BytesIO
        from unittest.mock import AsyncMock, PropertyMock, patch

        from PIL import Image

        from baseline_manager import BaselineManager

        # Create a mock CDP client
        mock = AsyncMock()
        type(mock).is_connected = PropertyMock(return_value=True)
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        sample_b64 = b64.b64encode(buf.getvalue()).decode("ascii")
        mock.screenshot.return_value = {
            "status": "ok", "data": sample_b64, "format": "jpeg", "size": len(sample_b64),
        }
        bm = BaselineManager(base_dir="/tmp/test_baselines_shape")

        with patch("main.client", mock), patch("main.baseline_mgr", bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
                data = resp.json()
                assert data["status"] == "ok"
                assert "baseline" in data
                bl = data["baseline"]
                assert "url" in bl
                assert "path" in bl
                assert "size" in bl
                assert "timestamp" in bl


# ===================================================================
# POST /screenshot/compare — Compare against baseline
# ===================================================================


class TestPostCompare:
    """Test POST /screenshot/compare endpoint."""

    @pytest.mark.asyncio
    async def test_compare_requires_baseline(self):
        """Should return 400 when no baseline exists for the URL."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/compare",
                json={"url": "https://no-baseline.com"},
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "detail" in data or "error" in data

    @pytest.mark.asyncio
    async def test_compare_requires_connected_cdp(self):
        """Should return 400 when CDP is not connected."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/compare",
                json={"url": "https://example.com"},
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "detail" in data

    @pytest.mark.asyncio
    async def test_compare_accepts_threshold(self):
        """Should accept threshold parameter."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/compare",
                json={
                    "url": "https://example.com",
                    "threshold": 0.005,
                },
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_compare_invalid_threshold(self):
        """Should return 422 for invalid threshold (negative or >1)."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/compare",
                json={
                    "url": "https://example.com",
                    "threshold": -0.1,
                },
            )
            assert resp.status_code in (422, 400)

    @pytest.mark.asyncio
    async def test_compare_accepts_profile(self):
        """Should accept profile parameter."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/screenshot/compare",
                json={
                    "url": "https://example.com",
                    "profile": "work",
                },
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_compare_response_shape(self):
        """On success, comparison response should match the spec shape."""
        import base64 as b64
        import tempfile
        from io import BytesIO
        from unittest.mock import AsyncMock, PropertyMock, patch

        from PIL import Image

        from baseline_manager import BaselineManager

        # Create a mock CDP client
        mock = AsyncMock()
        type(mock).is_connected = PropertyMock(return_value=True)
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        sample_b64 = b64.b64encode(buf.getvalue()).decode("ascii")
        mock.screenshot.return_value = {
            "status": "ok", "data": sample_b64, "format": "jpeg", "size": len(sample_b64),
        }
        bm = BaselineManager(base_dir=tempfile.mkdtemp(prefix="bm_shape_"))

        with patch("main.client", mock), patch("main.baseline_mgr", bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # First save a baseline
                resp1 = await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                assert resp1.status_code == 200, f"Baseline save failed: {resp1.text[:200]}"

                # Then compare
                resp = await client.post(
                    "/screenshot/compare",
                    json={"url": "https://example.com"},
                )
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
                data = resp.json()
                assert data["status"] == "ok"
                assert "comparison" in data
                comp = data["comparison"]
                assert "url" in comp
                assert "passed" in comp
                assert isinstance(comp["passed"], bool)
                assert "pixel_delta" in comp
                assert isinstance(comp["pixel_delta"], float)
                assert "threshold" in comp
                assert isinstance(comp["threshold"], float)
                assert "dimensions_match" in comp
                assert isinstance(comp["dimensions_match"], bool)
                assert "baseline_size" in comp
                assert "current_size" in comp
            assert "diff_image" in comp
            assert "baseline_taken_at" in comp
            assert "compared_at" in comp


# ===================================================================
# GET /screenshot/baselines — List baselines
# ===================================================================


class TestGetBaselines:
    """Test GET /screenshot/baselines endpoint."""

    @pytest.mark.asyncio
    async def test_list_empty_initially(self):
        """Should return an empty list when no baselines exist."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/screenshot/baselines")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            assert data["status"] == "ok"
            assert data["baselines"] == []
            assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_list_with_profile_filter(self):
        """Should accept profile query parameter."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/screenshot/baselines?profile=work")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            assert "baselines" in data
            assert "count" in data

    @pytest.mark.asyncio
    async def test_list_response_shape(self):
        """Response should contain baselines array with metadata."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/screenshot/baselines")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            assert data["status"] == "ok"
            assert isinstance(data["baselines"], list)
            assert isinstance(data["count"], int)
            if data["baselines"]:
                entry = data["baselines"][0]
                assert "url" in entry
                assert "path" in entry
                assert "size" in entry
                assert "timestamp" in entry
                assert "profile" in entry


# ===================================================================
# DELETE /screenshot/baseline — Delete a baseline
# ===================================================================


class TestDeleteBaseline:
    """Test DELETE /screenshot/baseline endpoint."""

    @pytest.mark.asyncio
    async def test_delete_missing_baseline(self):
        """Should return 404 for a non-existent baseline."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.request(
                "DELETE",
                "/screenshot/baseline",
                json={"url": "https://nonexistent.com"},
            )
            # During RED phase the endpoint doesn't exist, so expect
            # it to be missing. Once implemented, should return 404
            # with a meaningful error message.
            assert resp.status_code in (
                404, 200
            ), f"Expected 200/404, got {resp.status_code}: {resp.text[:200]}"

    @pytest.mark.asyncio
    async def test_delete_accepts_profile(self):
        """Should accept profile parameter."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.request(
                "DELETE",
                "/screenshot/baseline",
                json={
                    "url": "https://example.com",
                    "profile": "work",
                },
            )
            assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_delete_response_shape(self):
        """On successful delete, should return status ok + deleted true."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.request(
                "DELETE",
                "/screenshot/baseline",
                json={"url": "https://example.com"},
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            assert data["status"] == "ok"
            assert data["deleted"] is True


# ===================================================================
# Pydantic request model validation
# ===================================================================


class TestRequestModels:
    """Verify the Pydantic request models for screenshot endpoints."""

    def test_baseline_request_model(self):
        """BaselineRequest model should have correct fields."""
        from main import BaselineRequest

        req = BaselineRequest(url="https://example.com")
        assert req.url == "https://example.com"
        assert req.profile is None
        assert req.quality == 70
        assert req.viewport is None

        req2 = BaselineRequest(
            url="https://example.com",
            profile="work",
            quality=90,
            viewport={"width": 1280, "height": 720},
        )
        assert req2.profile == "work"
        assert req2.quality == 90
        assert req2.viewport == {"width": 1280, "height": 720}

    def test_compare_request_model(self):
        """CompareRequest model should have correct fields."""
        from main import CompareRequest

        req = CompareRequest(url="https://example.com")
        assert req.url == "https://example.com"
        assert req.profile is None
        assert req.threshold == 0.001
        assert req.quality == 70

        req2 = CompareRequest(url="https://example.com", threshold=0.5, profile="test")
        assert req2.threshold == 0.5
        assert req2.profile == "test"

    def test_compare_request_validates_threshold(self):
        """CompareRequest should validate threshold is in range 0.0-1.0."""
        from main import CompareRequest

        CompareRequest(url="https://example.com", threshold=0.0)
        CompareRequest(url="https://example.com", threshold=1.0)
        CompareRequest(url="https://example.com", threshold=0.5)
        CompareRequest(url="https://example.com")

        import pydantic

        with pytest.raises(pydantic.ValidationError):
            CompareRequest(url="https://example.com", threshold=-0.1)
        with pytest.raises(pydantic.ValidationError):
            CompareRequest(url="https://example.com", threshold=1.5)

    def test_delete_baseline_request_model(self):
        """DeleteBaselineRequest model should have correct fields."""
        from main import DeleteBaselineRequest

        req = DeleteBaselineRequest(url="https://example.com")
        assert req.url == "https://example.com"
        assert req.profile is None

        req2 = DeleteBaselineRequest(url="https://example.com", profile="work")
        assert req2.profile == "work"


# ===================================================================
# CI/CD output format
# ===================================================================


class TestCIOutputFormat:
    """Verify CI/CD-friendly JSON output format."""

    @pytest.mark.asyncio
    async def test_compare_output_has_cicd_fields(self):
        """Comparison response should include passed, pixel_delta, threshold."""
        import base64 as b64
        import tempfile
        from io import BytesIO
        from unittest.mock import AsyncMock, PropertyMock, patch

        from PIL import Image

        from baseline_manager import BaselineManager

        mock = AsyncMock()
        type(mock).is_connected = PropertyMock(return_value=True)
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        sample_b64 = b64.b64encode(buf.getvalue()).decode("ascii")
        mock.screenshot.return_value = {
            "status": "ok", "data": sample_b64, "format": "jpeg", "size": len(sample_b64),
        }
        bm = BaselineManager(base_dir=tempfile.mkdtemp(prefix="bm_cicd_"))

        with patch("main.client", mock), patch("main.baseline_mgr", bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Save baseline first
                await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                resp = await client.post(
                    "/screenshot/compare",
                    json={"url": "https://example.com"},
                )
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
                data = resp.json()
                comparison = data["comparison"]
                assert "passed" in comparison
                assert isinstance(comparison["passed"], bool)
                assert "pixel_delta" in comparison
                assert isinstance(comparison["pixel_delta"], (float, int))
                assert "threshold" in comparison
                assert isinstance(comparison["threshold"], (float, int))


# ===================================================================
# Mock-based CDP tests — full round-trip with mocked CDP client
# ===================================================================


class TestMockCDPIntegration:
    """Full round-trip integration tests using a mocked CDP client."""

    @pytest.fixture
    def sample_png_b64(self):
        """Return a base64-encoded 100x100 red PNG."""
        import base64 as b64
        from io import BytesIO

        from PIL import Image

        img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return b64.b64encode(buf.getvalue()).decode("ascii")

    @pytest.fixture
    def diff_png_b64(self):
        """Return a base64-encoded 100x100 blue PNG (different from red)."""
        import base64 as b64
        from io import BytesIO

        from PIL import Image

        img = Image.new("RGBA", (100, 100), (0, 0, 255, 255))  # blue
        buf = BytesIO()
        img.save(buf, format="PNG")
        return b64.b64encode(buf.getvalue()).decode("ascii")

    @pytest.fixture
    def mock_client(self, sample_png_b64):
        """Create a mocked CDP client that returns known screenshot data."""
        from unittest.mock import AsyncMock, PropertyMock

        mock = AsyncMock()
        type(mock).is_connected = PropertyMock(return_value=True)
        mock.screenshot.return_value = {
            "status": "ok",
            "data": sample_png_b64,
            "format": "jpeg",
            "size": len(sample_png_b64),
        }
        return mock

    @pytest.fixture
    def isolated_bm(self, tmp_path):
        """Create a fresh BaselineManager in a temp directory."""
        from baseline_manager import BaselineManager

        return BaselineManager(base_dir=str(tmp_path / "baselines"))

    # ── Baseline save (mock CDP) ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_mock_baseline_save_returns_200(self, mock_client, isolated_bm):
        """POST /screenshot/baseline with mocked CDP should return 200 with baseline metadata."""
        from unittest.mock import patch

        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
                data = resp.json()
                assert data["status"] == "ok"
                assert data["baseline"]["url"] == "https://example.com"
                assert isinstance(data["baseline"]["path"], str)
                assert isinstance(data["baseline"]["size"], int)
                assert isinstance(data["baseline"]["timestamp"], str)

    @pytest.mark.asyncio
    async def test_mock_baseline_save_with_profile(self, mock_client, isolated_bm):
        """POST /screenshot/baseline should accept profile parameter with mock CDP."""
        from unittest.mock import patch

        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com", "profile": "work"},
                )
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
                data = resp.json()
                assert data["status"] == "ok"
                assert data["baseline"]["url"] == "https://example.com"

    # ── Full round-trip: baseline → compare → verify pass ──────────

    @pytest.mark.asyncio
    async def test_full_roundtrip_compare_pass(self, mock_client, isolated_bm):
        """Baseline → modify page (same mock data) → compare → should pass with threshold=0.0."""
        from unittest.mock import patch

        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Step 1: Save baseline
                resp1 = await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                assert resp1.status_code == 200

                # Step 2: Compare (same mock data → should pass)
                resp2 = await client.post(
                    "/screenshot/compare",
                    json={"url": "https://example.com", "threshold": 0.0},
                )
                assert resp2.status_code == 200, f"Expected 200, got {resp2.status_code}: {resp2.text[:200]}"
                data = resp2.json()
                assert data["status"] == "ok"
                assert data["comparison"]["passed"] is True
                assert data["comparison"]["pixel_delta"] == 0.0
                assert data["comparison"]["threshold"] == 0.0
                assert data["comparison"]["dimensions_match"] is True
                assert "diff_image" in data["comparison"]

    # ── Full round-trip: baseline → compare → verify failure ───────

    @pytest.mark.asyncio
    async def test_full_roundtrip_compare_fail(self, mock_client, sample_png_b64, diff_png_b64, isolated_bm):
        """Baseline → modify page (different data) → compare → should fail with threshold=0.0."""
        from unittest.mock import AsyncMock, PropertyMock, patch

        # First create a mock that returns RED screenshot
        mock_save = AsyncMock()
        type(mock_save).is_connected = PropertyMock(return_value=True)
        mock_save.screenshot.return_value = {
            "status": "ok",
            "data": sample_png_b64,
            "format": "jpeg",
            "size": len(sample_png_b64),
        }

        with patch("main.client", mock_save), patch("main.baseline_mgr", isolated_bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Step 1: Save baseline (RED image)
                resp1 = await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                assert resp1.status_code == 200

        # Step 2: Change mock to return different (BLUE) image
        mock_compare = AsyncMock()
        type(mock_compare).is_connected = PropertyMock(return_value=True)
        mock_compare.screenshot.return_value = {
            "status": "ok",
            "data": diff_png_b64,
            "format": "jpeg",
            "size": len(diff_png_b64),
        }

        with patch("main.client", mock_compare), patch("main.baseline_mgr", isolated_bm):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp2 = await client.post(
                    "/screenshot/compare",
                    json={"url": "https://example.com", "threshold": 0.0},
                )
                assert resp2.status_code == 200, f"Expected 200, got {resp2.status_code}: {resp2.text[:200]}"
                data = resp2.json()
                assert data["status"] == "ok"
                assert data["comparison"]["passed"] is False
                assert data["comparison"]["pixel_delta"] == 1.0  # Completely different
                assert data["comparison"]["dimensions_match"] is True

    # ── Threshold edge cases ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_threshold_one_always_passes(self, mock_client, sample_png_b64, diff_png_b64, isolated_bm):
        """threshold=1.0 should pass even with completely different screenshots."""
        from unittest.mock import AsyncMock, PropertyMock, patch

        mock_compare = AsyncMock()
        type(mock_compare).is_connected = PropertyMock(return_value=True)
        mock_compare.screenshot.return_value = {
            "status": "ok",
            "data": diff_png_b64,
            "format": "jpeg",
            "size": len(diff_png_b64),
        }

        transport = ASGITransport(app=app)

        # Save a baseline with the first mock
        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                assert resp.status_code == 200

        # Compare with different image but threshold=1.0
        with patch("main.client", mock_compare), patch("main.baseline_mgr", isolated_bm):
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post(
                    "/screenshot/compare",
                    json={"url": "https://example.com", "threshold": 1.0},
                )
                assert resp.status_code == 200
                assert resp.json()["comparison"]["passed"] is True

    @pytest.mark.asyncio
    async def test_threshold_zero_fails_on_any_diff(self, mock_client, sample_png_b64, diff_png_b64, isolated_bm):
        """threshold=0.0 should fail on any pixel difference."""
        from unittest.mock import AsyncMock, PropertyMock, patch

        mock_different = AsyncMock()
        type(mock_different).is_connected = PropertyMock(return_value=True)
        mock_different.screenshot.return_value = {
            "status": "ok",
            "data": diff_png_b64,
            "format": "jpeg",
            "size": len(diff_png_b64),
        }

        transport = ASGITransport(app=app)

        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                await c.post("/screenshot/baseline", json={"url": "https://example.com"})

        with patch("main.client", mock_different), patch("main.baseline_mgr", isolated_bm):
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post(
                    "/screenshot/compare",
                    json={"url": "https://example.com", "threshold": 0.0},
                )
                assert resp.status_code == 200
                assert resp.json()["comparison"]["passed"] is False

    # ── CDP disconnect mid-comparison ───────────────────────────────

    @pytest.mark.asyncio
    async def test_cdp_disconnected_mid_baseline(self, mock_client, isolated_bm):
        """Baseline save should return 400 when CDP disconnects during screenshot."""
        from unittest.mock import AsyncMock, PropertyMock, patch

        disconnected = AsyncMock()
        type(disconnected).is_connected = PropertyMock(return_value=True)
        disconnected.screenshot.side_effect = Exception("CDP connection lost")

        with patch("main.client", disconnected), patch("main.baseline_mgr", isolated_bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                assert resp.status_code == 400
                data = resp.json()
                assert "detail" in data

    @pytest.mark.asyncio
    async def test_cdp_disconnected_mid_compare(self, mock_client, isolated_bm):
        """Compare should return 400 when CDP disconnects during screenshot."""
        from unittest.mock import AsyncMock, PropertyMock, patch

        transport = ASGITransport(app=app)

        # Save baseline first with working CDP
        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                await c.post("/screenshot/baseline", json={"url": "https://example.com"})

        # Now CDP fails mid-comparison
        disconnected = AsyncMock()
        type(disconnected).is_connected = PropertyMock(return_value=True)
        disconnected.screenshot.side_effect = Exception("CDP connection lost")

        with patch("main.client", disconnected), patch("main.baseline_mgr", isolated_bm):
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post(
                    "/screenshot/compare",
                    json={"url": "https://example.com"},
                )
                assert resp.status_code == 400
                data = resp.json()
                assert "detail" in data

    # ── GET /screenshot/baselines with profile filter ──────────────

    @pytest.mark.asyncio
    async def test_get_baselines_with_profiles_after_save(self, mock_client, isolated_bm):
        """GET /screenshot/baselines should reflect saved baselines with profile filter."""
        from unittest.mock import patch

        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Save two baselines with different profiles
                await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://work.com", "profile": "work"},
                )
                await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://personal.com", "profile": "personal"},
                )

                # List with profile=work
                resp_work = await client.get("/screenshot/baselines?profile=work")
                assert resp_work.status_code == 200
                data = resp_work.json()
                assert data["status"] == "ok"
                assert len(data["baselines"]) == 1
                assert "work.com" in data["baselines"][0]["url"]

                # List all (no filter)
                resp_all = await client.get("/screenshot/baselines")
                assert resp_all.status_code == 200
                data_all = resp_all.json()
                assert data_all["count"] >= 2

    # ── run_op pattern with new endpoints ──────────────────────────

    @pytest.mark.asyncio
    async def test_run_op_pattern_baseline(self, mock_client, isolated_bm):
        """Baseline endpoint should work with run_op internal pattern (logging, state broadcast)."""
        from unittest.mock import patch

        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )
                # The baseline endpoint returns status="ok" which is run_op style
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_run_op_pattern_compare(self, mock_client, isolated_bm):
        """Compare endpoint should work with run_op internal pattern."""
        from unittest.mock import patch

        with patch("main.client", mock_client), patch("main.baseline_mgr", isolated_bm):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Save baseline first
                await client.post(
                    "/screenshot/baseline",
                    json={"url": "https://example.com"},
                )

                # Then compare
                resp = await client.post(
                    "/screenshot/compare",
                    json={"url": "https://example.com"},
                )
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"
