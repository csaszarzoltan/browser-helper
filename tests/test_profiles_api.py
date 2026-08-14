"""Pre-development tests for profile REST API endpoints (RED phase).

These tests define the expected REST API interface BEFORE implementation.
All profile-related tests will fail until the developer:
1. Creates src/profile_manager.py with Profile + ProfileManager
2. Adds profile_mgr = ProfileManager() to main.py
3. Adds /profiles REST endpoints to main.py
"""

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


def _load_json(path: str):
    """Read a JSON file (used via executor to avoid blocking I/O in async tests)."""
    with open(path) as f:
        return json.load(f)

# Mark as integration (uses TestClient)
pytestmark = pytest.mark.integration

from httpx import ASGITransport, AsyncClient

from main import app, profile_mgr

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_profile_mgr():
    """Reset profile manager state between tests."""
    # Clear all profiles
    for p in list(profile_mgr.list_profiles()):
        profile_mgr.delete_profile(p.name)
    yield


@pytest.fixture
def populated_mgr():
    """Create a few profiles for list/get tests."""
    profile_mgr.create_profile("work", tags=["official"], description="Work profile")
    profile_mgr.create_profile("personal", tags=["private"], description="Personal browsing")
    profile_mgr.create_profile("testing", tags=["dev"], description="For testing")
    yield


# ===================================================================
# GET /profiles — List all profiles
# ===================================================================


class TestListProfiles:
    """Test GET /profiles endpoint."""

    @pytest.mark.asyncio
    async def test_list_empty(self):
        """Should return empty list when no profiles exist."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profiles")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["profiles"] == []

    @pytest.mark.asyncio
    async def test_list_with_profiles(self, populated_mgr):
        """Should return all created profiles."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profiles")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            names = [p["name"] for p in data["profiles"]]
            assert "work" in names
            assert "personal" in names
            assert "testing" in names
            assert len(data["profiles"]) == 3

    @pytest.mark.asyncio
    async def test_list_returns_fields(self, populated_mgr):
        """Each profile in list should contain full metadata."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profiles")
            data = resp.json()
            profile = next(p for p in data["profiles"] if p["name"] == "work")
            assert "data_dir" in profile
            assert "created_at" in profile
            assert "last_used" in profile
            assert "extensions" in profile
            assert "description" in profile
            assert "tags" in profile
            assert "resource_limits" in profile


# ===================================================================
# POST /profiles — Create a profile
# ===================================================================


class TestCreateProfile:
    """Test POST /profiles endpoint."""

    @pytest.mark.asyncio
    async def test_create_simple(self):
        """Should create a profile with just a name."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profiles", json={"name": "new-profile"})
            assert resp.status_code == 201
            data = resp.json()
            assert data["status"] == "ok"
            assert data["profile"]["name"] == "new-profile"

    @pytest.mark.asyncio
    async def test_create_with_all_fields(self):
        """Should create a profile with optional fields."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profiles",
                json={
                    "name": "full-profile",
                    "extensions": ["/ext/one", "/ext/two"],
                    "description": "Full featured",
                    "tags": ["important", "demo"],
                    "resource_limits": {"max_memory_mb": 1024, "max_cpu_percent": 60},
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            p = data["profile"]
            assert p["extensions"] == ["/ext/one", "/ext/two"]
            assert p["description"] == "Full featured"
            assert "important" in p["tags"]
            assert p["resource_limits"]["max_memory_mb"] == 1024

    @pytest.mark.asyncio
    async def test_create_missing_name(self):
        """Should return 422 when name is missing."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profiles", json={})
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_invalid_name(self):
        """Should return 400 for empty/invalid name."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profiles", json={"name": ""})
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_duplicate(self):
        """Should return 409 for duplicate profile name."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/profiles", json={"name": "dupe"})
            resp = await client.post("/profiles", json={"name": "dupe"})
            assert resp.status_code == 409
            data = resp.json()
            assert "already exists" in data.get("detail", "").lower()


# ===================================================================
# GET /profiles/{name} — Get a single profile
# ===================================================================


class TestGetProfile:
    """Test GET /profiles/{name} endpoint."""

    @pytest.mark.asyncio
    async def test_get_profile(self, populated_mgr):
        """Should return profile details by name."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profiles/work")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            p = data["profile"]
            assert p["name"] == "work"
            assert p["description"] == "Work profile"
            assert "official" in p["tags"]

    @pytest.mark.asyncio
    async def test_get_profile_not_found(self):
        """Should return 404 for nonexistent profile."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profiles/nonexistent")
            assert resp.status_code == 404
            data = resp.json()
            assert "detail" in data


# ===================================================================
# PUT /profiles/{name} — Update profile metadata
# ===================================================================


class TestUpdateProfile:
    """Test PUT /profiles/{name} endpoint."""

    @pytest.mark.asyncio
    async def test_update_description(self, populated_mgr):
        """Should update profile description."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profiles/work",
                json={"description": "Updated work profile"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["profile"]["description"] == "Updated work profile"

    @pytest.mark.asyncio
    async def test_update_tags(self, populated_mgr):
        """Should update profile tags."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profiles/work",
                json={"tags": ["official", "updated"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "updated" in data["profile"]["tags"]

    @pytest.mark.asyncio
    async def test_update_resource_limits(self, populated_mgr):
        """Should update resource limits."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profiles/work",
                json={"resource_limits": {"max_memory_mb": 2048}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["profile"]["resource_limits"]["max_memory_mb"] == 2048

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        """Should return 404 for nonexistent profile."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profiles/nonexistent",
                json={"description": "who cares"},
            )
            assert resp.status_code == 404


# ===================================================================
# DELETE /profiles/{name} — Delete a profile
# ===================================================================


class TestDeleteProfile:
    """Test DELETE /profiles/{name} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_profile(self, populated_mgr):
        """Should delete profile and return 200."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/profiles/work")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"

            # Verify it's gone
            get_resp = await client.get("/profiles/work")
            assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """Should return 404 for nonexistent profile."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/profiles/nonexistent")
            assert resp.status_code == 404


# ===================================================================
# POST /profiles/{name}/export — Export profile as ZIP
# ===================================================================


class TestExportProfile:
    """Test POST /profiles/{name}/export endpoint."""

    @pytest.mark.asyncio
    async def test_export_returns_zip(self, populated_mgr):
        """Should export profile as a downloadable ZIP."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profiles/work/export")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "path" in data
            assert data["path"].endswith(".zip")

    @pytest.mark.asyncio
    async def test_export_not_found(self):
        """Should return 404 for nonexistent profile."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profiles/nonexistent/export")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_export_valid_zip(self, populated_mgr):
        """Exported file should be a valid zip archive."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/profiles/work/export")
            data = resp.json()
            zip_path = data["path"]
            assert zipfile.is_zipfile(zip_path)

            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                assert any("profiles.json" in n for n in names)


# ===================================================================
# POST /profiles/import — Import profile from ZIP
# ===================================================================


class TestImportProfile:
    """Test POST /profiles/import endpoint."""

    @pytest.mark.asyncio
    async def test_import_profile(self, populated_mgr, tmp_path):
        """Should import a profile from a ZIP file."""
        # First export one
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            export_resp = await client.post("/profiles/work/export")
            zip_path = export_resp.json()["path"]

            # Delete it
            await client.delete("/profiles/work")

            # Import it back
            import_resp = await client.post(
                "/profiles/import",
                json={"path": zip_path},
            )
            assert import_resp.status_code == 201
            data = import_resp.json()
            assert data["status"] == "ok"
            assert data["profile"]["name"] == "work"

            # Verify it's back
            get_resp = await client.get("/profiles/work")
            assert get_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_import_invalid_path(self):
        """Should return 400 for nonexistent file."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profiles/import",
                json={"path": "/tmp/nonexistent.zip"},
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_import_corrupt_file(self, tmp_path):
        """Should return 400 for corrupt ZIP."""
        import asyncio

        corrupt = tmp_path / "corrupt.zip"
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, corrupt.write_bytes, b"not a zip file")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profiles/import",
                json={"path": str(corrupt)},
            )
            assert resp.status_code == 400


# ===================================================================
# POST /profiles/{name}/extensions — Manage extensions
# ===================================================================


class TestExtensionEndpoints:
    """Extension management via REST."""

    @pytest.mark.asyncio
    async def test_add_extension(self, populated_mgr):
        """Should add an extension to a profile."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profiles/work/extensions",
                json={"path": "/ext/adblock"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "/ext/adblock" in data["extensions"]

    @pytest.mark.asyncio
    async def test_add_extension_not_found(self):
        """Should return 404 for nonexistent profile."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/profiles/nonexistent/extensions",
                json={"path": "/ext/test"},
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_remove_extension(self, populated_mgr):
        """Should remove an extension from a profile."""
        # First add an extension
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/profiles/work/extensions",
                json={"path": "/ext/toremove"},
            )

            # Now remove it
            resp = await client.request(
                "DELETE",
                "/profiles/work/extensions",
                json={"path": "/ext/toremove"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "/ext/toremove" not in data["extensions"]

    @pytest.mark.asyncio
    async def test_list_extensions(self, populated_mgr):
        """GET should list extensions for a profile."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/profiles/work/extensions",
                json={"path": "/ext/one"},
            )
            await client.post(
                "/profiles/work/extensions",
                json={"path": "/ext/two"},
            )

            resp = await client.get("/profiles/work/extensions")
            assert resp.status_code == 200
            data = resp.json()
            assert set(data["extensions"]) == {"/ext/one", "/ext/two"}


# ===================================================================
# Cross-profile isolation
# ===================================================================


class TestProfileIsolation:
    """Verify profiles are isolated from each other."""

    @pytest.mark.asyncio
    async def test_separate_data_dirs(self):
        """Each profile should have a unique data directory."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp_a = await client.post("/profiles", json={"name": "alpha"})
            resp_b = await client.post("/profiles", json={"name": "beta"})

            alpha_dir = resp_a.json()["profile"]["data_dir"]
            beta_dir = resp_b.json()["profile"]["data_dir"]
            assert alpha_dir != beta_dir
            assert alpha_dir.endswith("alpha")
            assert beta_dir.endswith("beta")


# ===================================================================
# Profile persistence across restarts (simulated round-trip)
# ===================================================================


class TestProfilePersistence:
    """Profiles should survive a simulated restart."""

    @pytest.mark.asyncio
    async def test_persistence_round_trip(self, populated_mgr):
        """Profiles should persist in profiles.json and be reloadable."""
        import asyncio
        import os

        # Check that profiles.json exists with data
        from main import profile_mgr

        profiles_file = os.path.join(profile_mgr._storage_dir, "profiles.json")
        loop = asyncio.get_running_loop()
        assert await loop.run_in_executor(None, os.path.isfile, profiles_file)

        data = await loop.run_in_executor(None, _load_json, profiles_file)
        assert "work" in data
        assert "personal" in data
        assert "testing" in data
        assert data["work"]["description"] == "Work profile"
