"""Pre-development tests for Fingerprint REST API endpoints (RED phase).

These tests define the expected HTTP interface for fingerprint endpoints
BEFORE the developer implements them. All tests will fail until the
developer adds:
  - POST /profile/{name}/fingerprint
  - GET /profile/{name}/fingerprint
  - Fingerprint validation and storage in ProfileManager
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from httpx import ASGITransport, AsyncClient

from main import app, profile_mgr

# ---------------------------------------------------------------------------
# Expected fingerprint field list
# ---------------------------------------------------------------------------
FINGERPRINT_FIELDS = [
    "canvas_offset_x",
    "canvas_offset_y",
    "webgl_vendor",
    "webgl_renderer",
    "hardware_concurrency",
    "device_memory",
    "screen_width",
    "screen_height",
    "color_depth",
    "timezone",
    "platform",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_profile_mgr():
    """Reset profile manager state between tests."""
    for p in list(profile_mgr.list_profiles()):
        profile_mgr.delete_profile(p.name)
    yield


@pytest.fixture
def created_profile():
    """Create a basic profile for fingerprint tests."""
    profile_mgr.create_profile("fingerprint-probe")
    yield


# ===================================================================
# POST /profile/{name}/fingerprint — Generate/assign fingerprint
# ===================================================================


class TestPostFingerprint:
    """Test POST /profile/{name}/fingerprint endpoint."""

    @pytest.mark.asyncio
    async def test_post_creates_fingerprint(self, created_profile):
        """POST should generate and return a fingerprint."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profile/fingerprint-probe/fingerprint")
            assert resp.status_code == 201 or resp.status_code == 200
            data = resp.json()
            assert "fingerprint" in data
            fp = data["fingerprint"]
            assert isinstance(fp, dict)
            for field in FINGERPRINT_FIELDS:
                assert field in fp, (
                    f"Response fingerprint missing field: {field}"
                )

    @pytest.mark.asyncio
    async def test_post_with_overrides(self, created_profile):
        """POST with overrides should respect supplied values."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={
                    "overrides": {
                        "canvas_offset_x": 5,
                        "canvas_offset_y": 10,
                        "webgl_vendor": "Google Inc. (Intel)",
                    }
                },
            )
            assert resp.status_code in (200, 201)
            data = resp.json()
            fp = data["fingerprint"]
            assert fp["canvas_offset_x"] == 5
            assert fp["canvas_offset_y"] == 10
            assert fp["webgl_vendor"] == "Google Inc. (Intel)"

    @pytest.mark.asyncio
    async def test_post_nonexistent_profile(self):
        """POST on nonexistent profile should return 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profile/no-such-profile/fingerprint")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_post_invalid_override(self, created_profile):
        """POST with invalid override value should return 400/422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {"canvas_offset_x": "not-an-int"}},
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_post_unknown_override_field(self, created_profile):
        """POST with unknown override field should return 400/422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {"fake_field": "value"}},
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_post_generates_real_device_values(self, created_profile):
        """Generated fingerprint should contain realistic device values, not random numbers."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profile/fingerprint-probe/fingerprint")
            assert resp.status_code in (200, 201)
            fp = resp.json()["fingerprint"]
            # Real-device checks — these should match known GPU/device combos
            assert isinstance(fp["webgl_vendor"], str) and len(fp["webgl_vendor"]) > 0
            assert isinstance(fp["webgl_renderer"], str) and len(fp["webgl_renderer"]) > 0
            # WebGL values should look like real GPUs, not random strings
            assert any(
                vendor in fp["webgl_vendor"].lower()
                for vendor in ["google", "intel", "nvidia", "amd", "apple", "mesa"]
            ), f"webgl_vendor should be a known GPU vendor, got {fp['webgl_vendor']!r}"

    @pytest.mark.asyncio
    async def test_post_twice_updates_fingerprint(self, created_profile):
        """POSTing twice should update the fingerprint."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.post("/profile/fingerprint-probe/fingerprint")
            fp1 = resp1.json()["fingerprint"]
            resp2 = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {"canvas_offset_x": 99}},
            )
            fp2 = resp2.json()["fingerprint"]
            assert fp2["canvas_offset_x"] == 99
            # Other fields might differ since it's a fresh generation

    @pytest.mark.asyncio
    async def test_post_empty_overrides(self, created_profile):
        """POST with empty overrides {} should generate default fingerprint."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {}},
            )
            assert resp.status_code in (200, 201)
            fp = resp.json()["fingerprint"]
            assert isinstance(fp, dict)
            assert len(fp) == len(FINGERPRINT_FIELDS)


# ===================================================================
# GET /profile/{name}/fingerprint — Retrieve current fingerprint
# ===================================================================


class TestGetFingerprint:
    """Test GET /profile/{name}/fingerprint endpoint."""

    @pytest.mark.asyncio
    async def test_get_after_post(self, created_profile):
        """GET should return the same fingerprint that was generated by POST."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Generate fingerprint
            post_resp = await client.post("/profile/fingerprint-probe/fingerprint")
            assert post_resp.status_code in (200, 201)
            expected = post_resp.json()["fingerprint"]

            # Retrieve it
            get_resp = await client.get("/profile/fingerprint-probe/fingerprint")
            assert get_resp.status_code == 200
            data = get_resp.json()
            assert "fingerprint" in data
            assert data["fingerprint"] == expected

    @pytest.mark.asyncio
    async def test_get_before_post(self, created_profile):
        """GET without prior POST should return null/empty fingerprint."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profile/fingerprint-probe/fingerprint")
            assert resp.status_code == 200
            data = resp.json()
            assert data["fingerprint"] is None or data["fingerprint"] == {}, (
                "GET before generating fingerprint should return null/empty"
            )

    @pytest.mark.asyncio
    async def test_get_nonexistent_profile(self):
        """GET on nonexistent profile should return 404."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profile/nonexistent/fingerprint")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_overridden_values(self, created_profile):
        """GET should reflect overridden field values."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {"timezone": "Asia/Shanghai", "platform": "MacIntel"}},
            )
            resp = await client.get("/profile/fingerprint-probe/fingerprint")
            assert resp.status_code == 200
            fp = resp.json()["fingerprint"]
            assert fp["timezone"] == "Asia/Shanghai"
            assert fp["platform"] == "MacIntel"


# ===================================================================
# Backward compatibility — old profiles without fingerprint
# ===================================================================


class TestFingerprintBackwardCompatAPI:
    """Old profiles without fingerprint should work fine with endpoints."""

    @pytest.mark.asyncio
    async def test_get_fingerprint_old_profile_returns_null(self):
        """GET fingerprint on profile that has no fingerprint should return null, not error."""
        # Create a profile via direct ProfileManager call
        profile_mgr.create_profile("old-skool")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profile/old-skool/fingerprint")
            assert resp.status_code == 200
            data = resp.json()
            # Should return null/None, not an error
            assert data.get("fingerprint") is None or data.get("fingerprint") == {}

    @pytest.mark.asyncio
    async def test_post_then_get_full_cycle(self):
        """Full POST then GET cycle should work end-to-end."""
        # Create profile via API first
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create via profiles API
            await client.post("/profiles", json={"name": "e2e-test"})

            # POST fingerprint
            post_resp = await client.post("/profile/e2e-test/fingerprint")
            assert post_resp.status_code in (200, 201)
            fp = post_resp.json()["fingerprint"]

            # GET fingerprint
            get_resp = await client.get("/profile/e2e-test/fingerprint")
            assert get_resp.status_code == 200
            assert get_resp.json()["fingerprint"] == fp


# ===================================================================
# CRUD backward compat — existing profile endpoints still work
# ===================================================================


class TestCRUDCompatAPI:
    """Existing profile REST API endpoints should work unchanged."""

    @pytest.mark.asyncio
    async def test_list_profiles(self, created_profile):
        """GET /profiles should still list profiles."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profiles")
            assert resp.status_code == 200
            data = resp.json()
            names = [p["name"] for p in data["profiles"]]
            assert "fingerprint-probe" in names

    @pytest.mark.asyncio
    async def test_create_profile(self):
        """POST /profiles should still create profiles."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profiles", json={"name": "new-profile"})
            assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_delete_profile(self, created_profile):
        """DELETE /profiles/{name} should still delete."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/profile/fingerprint-probe")
            # The exact endpoint depends on profile implementation —
            # just verify it doesn't crash
            assert resp.status_code in (200, 202, 204)

    @pytest.mark.asyncio
    async def test_list_includes_fingerprint_field(self, created_profile):
        """Profile list response should include fingerprint field."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Generate fingerprint first
            await client.post("/profile/fingerprint-probe/fingerprint")
            resp = await client.get("/profiles")
            data = resp.json()
            profile = next(
                p for p in data["profiles"] if p["name"] == "fingerprint-probe"
            )
            assert "fingerprint" in profile, (
                "Profile list response should include fingerprint field"
            )


# ===================================================================
# Validation — invalid values
# ===================================================================


class TestFingerprintValidationAPI:
    """REST endpoint validation for invalid inputs."""

    @pytest.mark.asyncio
    async def test_invalid_canvas_offset(self, created_profile):
        """Non-integer canvas_offset should return error."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {"canvas_offset_x": "abc"}},
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_invalid_hardware_concurrency(self, created_profile):
        """Zero/negative hardware_concurrency should return error."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {"hardware_concurrency": 0}},
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_invalid_color_depth(self, created_profile):
        """Invalid color_depth should return error."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {"color_depth": 16}},
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_invalid_screen_width(self, created_profile):
        """Too-small screen_width should return error."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                json={"overrides": {"screen_width": 320}},
            )
            assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_malformed_json(self, created_profile):
        """Malformed body should return 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profile/fingerprint-probe/fingerprint",
                content=b"not json at all",
                headers={"content-type": "application/json"},
            )
            assert resp.status_code == 422
