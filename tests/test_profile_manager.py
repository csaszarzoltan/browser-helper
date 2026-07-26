"""Pre-development tests for ProfileManager (RED phase).

These tests define the expected interface BEFORE implementation.
All will fail with ImportError/AttributeError until the developer
writes src/profile_manager.py.
"""

import json
import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage_dir(tmp_path):
    """Return a temporary directory for profile storage."""
    return str(tmp_path / ".browser-helper")


@pytest.fixture
def pm(storage_dir):
    """Return a fresh ProfileManager isolated to a temp directory."""
    from profile_manager import ProfileManager

    mgr = ProfileManager(storage_dir=storage_dir)
    yield mgr
    # No cleanup needed — tmp_path is ephemeral


# ===================================================================
# Profile dataclass
# ===================================================================


class TestProfileDataclass:
    """Verify Profile dataclass fields and defaults."""

    def test_import(self):
        """Profile should be importable from profile_manager."""
        from profile_manager import Profile

        assert hasattr(Profile, "__dataclass_fields__")

    def test_default_resources(self):
        """Profile should have sensible resource_limits defaults."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test")
        assert p.resource_limits["max_memory_mb"] == 512
        assert p.resource_limits["max_cpu_percent"] == 80

    def test_extensions_default_empty(self):
        """Profile should start with no extensions."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test")
        assert p.extensions == []

    def test_tags_default_empty(self):
        """Profile should start with no tags."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test")
        assert p.tags == []

    def test_description_default_empty(self):
        """Profile description should default to empty string."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test")
        assert p.description == ""

    def test_timestamps_set_on_create(self):
        """created_at and last_used should be set on creation."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test")
        assert isinstance(p.created_at, float)
        assert isinstance(p.last_used, float)
        # Timestamps should be recent (within the last 5 seconds)
        now = datetime.now(UTC).timestamp()
        assert abs(p.created_at - now) < 5
        assert abs(p.last_used - now) < 5

    def test_custom_resource_limits(self):
        """Profile should accept custom resource_limits."""
        from profile_manager import Profile

        p = Profile(
            name="test",
            data_dir="/tmp/test",
            resource_limits={"max_memory_mb": 1024, "max_cpu_percent": 50},
        )
        assert p.resource_limits["max_memory_mb"] == 1024
        assert p.resource_limits["max_cpu_percent"] == 50


# ===================================================================
# ProfileManager CRUD
# ===================================================================


class TestProfileManagerInit:
    """Verify ProfileManager initialization."""

    def test_init_creates_storage_dir(self, storage_dir):
        """Storage dir should be created if it doesn't exist."""
        from profile_manager import ProfileManager

        assert not os.path.exists(storage_dir)
        ProfileManager(storage_dir=storage_dir)
        assert os.path.isdir(storage_dir)

    def test_init_creates_profiles_json(self, storage_dir):
        """profiles.json should be created on init if not present."""
        from profile_manager import ProfileManager

        ProfileManager(storage_dir=storage_dir)
        profiles_file = os.path.join(storage_dir, "profiles.json")
        assert os.path.isfile(profiles_file)

    def test_init_loads_existing_profiles(self, storage_dir):
        """Existing profiles.json should be loaded on init."""
        from profile_manager import ProfileManager

        # Pre-create profiles.json
        os.makedirs(storage_dir, exist_ok=True)
        profiles_file = os.path.join(storage_dir, "profiles.json")
        existing_data = {
            "work": {
                "name": "work",
                "data_dir": os.path.join(storage_dir, "profiles", "work"),
                "created_at": 1000.0,
                "last_used": 2000.0,
                "extensions": [],
                "description": "Work profile",
                "tags": ["work"],
                "resource_limits": {"max_memory_mb": 1024, "max_cpu_percent": 80},
            }
        }
        with open(profiles_file, "w") as f:
            json.dump(existing_data, f)

        mgr = ProfileManager(storage_dir=storage_dir)
        profiles = mgr.list_profiles()
        assert len(profiles) == 1
        assert profiles[0].name == "work"
        assert profiles[0].description == "Work profile"


class TestProfileManagerCRUD:
    """Core CRUD operations."""

    def test_create_profile(self, pm):
        """create_profile should return a Profile and store it."""
        profile = pm.create_profile(name="testing")
        assert profile.name == "testing"
        # Should have an absolute data_dir
        assert os.path.isabs(profile.data_dir)
        assert "testing" in profile.data_dir

    def test_create_profile_auto_creates_data_dir(self, pm):
        """Data directory should be created on profile creation."""
        pm.create_profile(name="testing")
        data_dir = pm.get_data_dir("testing")
        assert os.path.isdir(data_dir)

    def test_get_profile_exists(self, pm):
        """get_profile should return profile by name."""
        pm.create_profile(name="work")
        profile = pm.get_profile("work")
        assert profile is not None
        assert profile.name == "work"

    def test_get_profile_nonexistent(self, pm):
        """get_profile should return None for missing profile."""
        profile = pm.get_profile("nonexistent")
        assert profile is None

    def test_list_profiles_empty(self, pm):
        """list_profiles should return empty list initially."""
        profiles = pm.list_profiles()
        assert profiles == []

    def test_list_profiles_after_create(self, pm):
        """list_profiles should include newly created profiles."""
        pm.create_profile("alpha")
        pm.create_profile("beta")
        names = [p.name for p in pm.list_profiles()]
        assert "alpha" in names
        assert "beta" in names
        assert len(names) == 2

    def test_delete_profile(self, pm):
        """delete_profile should remove profile and return True."""
        pm.create_profile("temp")
        result = pm.delete_profile("temp")
        assert result is True
        assert pm.get_profile("temp") is None

    def test_delete_profile_removes_data_dir(self, pm):
        """delete_profile should remove the data directory."""
        pm.create_profile("temp")
        data_dir = pm.get_data_dir("temp")
        assert os.path.isdir(data_dir)
        pm.delete_profile("temp")
        assert not os.path.exists(data_dir)

    def test_delete_nonexistent(self, pm):
        """delete_profile should return False for nonexistent profile."""
        result = pm.delete_profile("nonexistent")
        assert result is False

    def test_rename_profile(self, pm):
        """rename_profile should rename and return True."""
        pm.create_profile("old")
        result = pm.rename_profile("old", "new")
        assert result is True
        assert pm.get_profile("old") is None
        assert pm.get_profile("new") is not None

    def test_rename_profile_moves_data_dir(self, pm):
        """rename should move the data directory."""
        pm.create_profile("old")
        old_dir = pm.get_data_dir("old")
        # Create a file in the old data dir to verify move
        os.makedirs(old_dir, exist_ok=True)
        with open(os.path.join(old_dir, "test.txt"), "w") as f:
            f.write("data")

        pm.rename_profile("old", "new")
        new_dir = pm.get_data_dir("new")
        assert os.path.isdir(new_dir)
        assert os.path.isfile(os.path.join(new_dir, "test.txt"))
        assert not os.path.exists(old_dir)

    def test_rename_nonexistent(self, pm):
        """rename_profile should return False for nonexistent profile."""
        result = pm.rename_profile("nonexistent", "new")
        assert result is False

    def test_rename_duplicate_target(self, pm):
        """rename_profile should return False when target name exists."""
        pm.create_profile("a")
        pm.create_profile("b")
        result = pm.rename_profile("a", "b")
        assert result is False

    def test_create_duplicate_name(self, pm):
        """create_profile should raise ValueError for duplicate name."""
        pm.create_profile("work")
        with pytest.raises(ValueError, match=r"(?i)already exists|duplicate"):
            pm.create_profile("work")


class TestProfilePersistence:
    """JSON persistence round-trip."""

    def test_profiles_file_created(self, pm):
        """profiles.json should exist after creating a profile."""
        pm.create_profile("persist-test")
        profiles_file = os.path.join(
            pm._storage_dir, "profiles.json"
        )
        assert os.path.isfile(profiles_file)

    def test_persistence_round_trip(self, pm, storage_dir):
        """Profiles should survive reload from disk."""
        pm.create_profile("alpha")
        pm.create_profile("beta")

        # Create a new ProfileManager reading the same file
        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        assert len(pm2.list_profiles()) == 2
        assert pm2.get_profile("alpha") is not None
        assert pm2.get_profile("beta") is not None

    def test_persistence_fields_preserved(self, pm, storage_dir):
        """All fields should survive a save/load round-trip."""
        pm.create_profile(
            "detailed",
            extensions=["/ext/one", "/ext/two"],
            description="My detailed profile",
            tags=["test", "demo"],
            resource_limits={"max_memory_mb": 2048, "max_cpu_percent": 60},
        )

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        p = pm2.get_profile("detailed")
        assert p.name == "detailed"
        assert p.extensions == ["/ext/one", "/ext/two"]
        assert p.description == "My detailed profile"
        assert p.tags == ["test", "demo"]
        assert p.resource_limits["max_memory_mb"] == 2048
        assert p.resource_limits["max_cpu_percent"] == 60

    def test_deletion_persists(self, pm, storage_dir):
        """Deleted profile should not reappear after reload."""
        pm.create_profile("temp")
        pm.delete_profile("temp")

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        assert pm2.get_profile("temp") is None

    def test_rename_persists(self, pm, storage_dir):
        """Rename should survive reload."""
        pm.create_profile("old")
        pm.rename_profile("old", "renamed")

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        assert pm2.get_profile("old") is None
        assert pm2.get_profile("renamed") is not None


class TestProfileDataDir:
    """Profile data directory management."""

    def test_get_data_dir_returns_path(self, pm):
        """get_data_dir should return an absolute path."""
        pm.create_profile("test")
        data_dir = pm.get_data_dir("test")
        assert os.path.isabs(data_dir)
        assert data_dir.endswith("test")

    def test_data_dir_isolation(self, pm):
        """Each profile should have its own data directory."""
        pm.create_profile("alpha")
        pm.create_profile("beta")
        alpha_dir = pm.get_data_dir("alpha")
        beta_dir = pm.get_data_dir("beta")
        assert alpha_dir != beta_dir

    def test_data_dir_nonexistent_profile(self, pm):
        """get_data_dir should return None for nonexistent profile."""
        data_dir = pm.get_data_dir("nonexistent")
        assert data_dir is None


# ===================================================================
# Extension management
# ===================================================================


class TestExtensionManagement:
    """Per-profile Chrome extension management."""

    def test_get_extensions_empty(self, pm):
        """New profile should have no extensions."""
        pm.create_profile("test")
        exts = pm.get_extensions("test")
        assert exts == []

    def test_add_extension(self, pm):
        """add_extension should add path and return True."""
        pm.create_profile("test")
        result = pm.add_extension("test", "/ext/adblock")
        assert result is True
        exts = pm.get_extensions("test")
        assert "/ext/adblock" in exts

    def test_add_extension_duplicate(self, pm):
        """add_extension should not add duplicate paths."""
        pm.create_profile("test")
        pm.add_extension("test", "/ext/adblock")
        pm.add_extension("test", "/ext/adblock")  # Duplicate
        exts = pm.get_extensions("test")
        assert exts.count("/ext/adblock") == 1

    def test_add_extension_multiple(self, pm):
        """Multiple extensions should be supported."""
        pm.create_profile("test")
        pm.add_extension("test", "/ext/one")
        pm.add_extension("test", "/ext/two")
        pm.add_extension("test", "/ext/three")
        assert len(pm.get_extensions("test")) == 3

    def test_remove_extension(self, pm):
        """remove_extension should remove path and return True."""
        pm.create_profile("test")
        pm.add_extension("test", "/ext/adblock")
        result = pm.remove_extension("test", "/ext/adblock")
        assert result is True
        assert "/ext/adblock" not in pm.get_extensions("test")

    def test_remove_extension_nonexistent(self, pm):
        """remove_extension should return False for nonexistent path."""
        pm.create_profile("test")
        result = pm.remove_extension("test", "/ext/nonexistent")
        assert result is False

    def test_get_extensions_nonexistent_profile(self, pm):
        """get_extensions should return None for nonexistent profile."""
        exts = pm.get_extensions("nope")
        assert exts is None

    def test_add_extension_nonexistent_profile(self, pm):
        """add_extension should return False for nonexistent profile."""
        result = pm.add_extension("nope", "/ext/whatever")
        assert result is False

    def test_extensions_persist(self, pm, storage_dir):
        """Extensions should survive reload."""
        pm.create_profile("test")
        pm.add_extension("test", "/ext/adblock")
        pm.add_extension("test", "/ext/ublock")

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        assert set(pm2.get_extensions("test")) == {"/ext/adblock", "/ext/ublock"}


# ===================================================================
# Import / Export
# ===================================================================


class TestProfileExport:
    """ZIP export functionality."""

    def test_export_creates_zip(self, pm, tmp_path):
        """export_profile should create a .zip archive."""
        pm.create_profile("export-test")
        output = str(tmp_path / "export-test.zip")
        result = pm.export_profile("export-test", output)
        assert result == output
        assert os.path.isfile(output)
        assert zipfile.is_zipfile(output)

    def test_export_contains_metadata(self, pm, tmp_path):
        """ZIP should contain a profiles.json entry with profile metadata."""
        pm.create_profile(
            "export-test",
            extensions=["/ext/test"],
            description="Export me",
            tags=["export"],
        )
        output = str(tmp_path / "export-test.zip")
        pm.export_profile("export-test", output)

        with zipfile.ZipFile(output, "r") as zf:
            assert "profiles.json" in zf.namelist()
            meta = json.loads(zf.read("profiles.json"))
            assert meta["name"] == "export-test"
            assert "/ext/test" in meta["extensions"]
            assert meta["description"] == "Export me"

    def test_export_contains_data_dir(self, pm, tmp_path):
        """ZIP should contain the data directory contents."""
        pm.create_profile("export-test")
        data_dir = pm.get_data_dir("export-test")
        os.makedirs(data_dir, exist_ok=True)
        # Put some files in the data dir
        with open(os.path.join(data_dir, "bookmarks.html"), "w") as f:
            f.write("<html></html>")
        os.makedirs(os.path.join(data_dir, "subdir"), exist_ok=True)
        with open(os.path.join(data_dir, "subdir", "settings.txt"), "w") as f:
            f.write("settings")

        output = str(tmp_path / "export-test.zip")
        pm.export_profile("export-test", output)

        with zipfile.ZipFile(output, "r") as zf:
            names = zf.namelist()
            # Should have data dir contents, prefixed with profile name
            assert any("bookmarks.html" in n for n in names)
            assert any("subdir/settings.txt" in n for n in names)

    def test_export_nonexistent_profile(self, pm, tmp_path):
        """export_profile should return None for nonexistent profile."""
        output = str(tmp_path / "nope.zip")
        result = pm.export_profile("nonexistent", output)
        assert result is None
        assert not os.path.exists(output)


class TestProfileImport:
    """ZIP import functionality."""

    def test_import_profile(self, pm, tmp_path):
        """import_profile should restore a profile from ZIP."""
        # First, create and export a profile
        pm.create_profile(
            "source",
            extensions=["/ext/one"],
            description="Imported profile",
            tags=["imported"],
            resource_limits={"max_memory_mb": 2048, "max_cpu_percent": 60},
        )
        export_path = str(tmp_path / "source.zip")
        pm.export_profile("source", export_path)

        # Delete the original
        pm.delete_profile("source")

        # Import it back
        imported = pm.import_profile(export_path)
        assert imported is not None
        assert imported.name == "source"
        assert imported.description == "Imported profile"
        assert imported.extensions == ["/ext/one"]
        assert imported.tags == ["imported"]

    def test_import_creates_data_dir(self, pm, tmp_path):
        """import_profile should recreate the data directory."""
        pm.create_profile("source")
        data_dir = pm.get_data_dir("source")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "state.dat"), "w") as f:
            f.write("state")

        export_path = str(tmp_path / "source.zip")
        pm.export_profile("source", export_path)
        pm.delete_profile("source")

        imported = pm.import_profile(export_path)
        assert imported is not None
        imported_data_dir = pm.get_data_dir("source")
        assert os.path.isdir(imported_data_dir)
        assert os.path.isfile(os.path.join(imported_data_dir, "state.dat"))

    def test_import_creates_new_profile(self, pm, tmp_path):
        """import_profile should add the profile to the manager."""
        pm.create_profile("original")
        export_path = str(tmp_path / "original.zip")
        pm.export_profile("original", export_path)
        pm.delete_profile("original")

        pm.import_profile(export_path)
        assert pm.get_profile("original") is not None
        names = [p.name for p in pm.list_profiles()]
        assert "original" in names

    def test_import_existing_name(self, pm, tmp_path):
        """import_profile should handle name conflict (e.g., append suffix)."""
        pm.create_profile("existing")
        export_path = str(tmp_path / "existing.zip")
        pm.export_profile("existing", export_path)

        # Try importing while the name exists
        with pytest.raises(ValueError, match=r"(?i)already exists|duplicate"):
            pm.import_profile(export_path)

    def test_import_corrupt_zip(self, pm, tmp_path):
        """import_profile should raise for corrupt/non-zip files."""
        corrupt = tmp_path / "corrupt.zip"
        with open(corrupt, "wb") as f:
            f.write(b"not a zip file")

        with pytest.raises((zipfile.BadZipFile, ValueError)):
            pm.import_profile(str(corrupt))

    def test_import_missing_metadata(self, pm, tmp_path):
        """import_profile should raise if ZIP lacks profiles.json."""
        bad_zip = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("random.txt", "no metadata here")

        with pytest.raises(ValueError, match=r"(?i)profiles.json|metadata"):
            pm.import_profile(str(bad_zip))


# ===================================================================
# Error handling
# ===================================================================


class TestErrorCases:
    """Edge cases and error handling."""

    def test_create_profile_empty_name(self, pm):
        """create_profile should reject empty name."""
        with pytest.raises(ValueError):
            pm.create_profile(name="")

    def test_create_profile_invalid_name(self, pm):
        """create_profile should reject names with path separators."""
        for bad_name in ["../escape", "a/b", "x/y/z"]:
            with pytest.raises(ValueError):
                pm.create_profile(name=bad_name)

    def test_data_dir_format(self, pm):
        """Data dirs should be under storage_dir/profiles/<name>/."""
        pm.create_profile("well-named")
        data_dir = pm.get_data_dir("well-named")
        assert data_dir.startswith(pm._storage_dir)
        assert "profiles" in data_dir
        assert data_dir.endswith("well-named")

    def test_profile_auto_saves_after_mutation(self, pm, storage_dir):
        """Mutations should auto-save (calling save is not needed)."""
        pm.create_profile("auto-save")
        pm.add_extension("auto-save", "/ext/plug")
        pm.rename_profile("auto-save", "auto-save-2")

        # Reload without any explicit save call
        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        p = pm2.get_profile("auto-save-2")
        assert p is not None
        assert "/ext/plug" in p.extensions
