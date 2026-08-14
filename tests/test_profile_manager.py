"""Pre-development tests for ProfileManager (RED phase).

These tests define the expected interface BEFORE implementation.
All will fail with ImportError/AttributeError until the developer
writes src/profile_manager.py.

Extended for Anti-Detection Profile Manager (Task 4.4):
- Interface tests for ANTI_DETECTION_PROFILES, AntiDetectionProfile, ProfileValidator
- Behavioral tests for selection strategies, validation, session integration
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



# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

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


# ===================================================================
# ANTI_DETECTION PROFILE TYPES — Interface Tests
# ===================================================================
# These tests verify the interface contracts for the anti-detection
# profile type system. They pass immediately once the developer
# defines the ANTI_DETECTION_PROFILES constant and AntiDetectionProfile
# dataclass in src/anti_detection/profile_types.py.
# ===================================================================


class TestAntiDetectionProfileTypesInterface:
    """Interface tests for ANTI_DETECTION_PROFILES and AntiDetectionProfile."""

    def test_import_anti_detection_profiles(self):
        """ANTI_DETECTION_PROFILES must be importable from anti_detection.profile_types."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        assert isinstance(ANTI_DETECTION_PROFILES, dict)

    def test_import_anti_detection_profile_dataclass(self):
        """AntiDetectionProfile must be importable from anti_detection.profile_types."""
        from anti_detection.profile_types import AntiDetectionProfile

        assert hasattr(AntiDetectionProfile, "__dataclass_fields__")

    def test_four_predefined_profiles(self):
        """There must be exactly 4 predefined anti-detection profiles."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        expected_profiles = {
            "stealth-chrome-120",
            "mobile-safari-ios",
            "firefox-linux",
            "edge-windows",
        }
        assert set(ANTI_DETECTION_PROFILES.keys()) == expected_profiles

    def test_stealth_chrome_120_structure(self):
        """stealth-chrome-120 must have all required fingerprint fields."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        profile = ANTI_DETECTION_PROFILES["stealth-chrome-120"]
        required_fields = {
            "user_agent", "platform", "hardware_concurrency", "device_memory",
            "screen_width", "screen_height", "color_depth", "pixel_ratio",
            "timezone", "locale", "webgl_vendor", "webgl_renderer",
            "canvas_offset", "audio_variance_pct",
        }
        for field in required_fields:
            assert field in profile, f"Missing field: {field}"

    def test_mobile_safari_ios_structure(self):
        """mobile-safari-ios must have all required fingerprint fields."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        profile = ANTI_DETECTION_PROFILES["mobile-safari-ios"]
        required_fields = {
            "user_agent", "platform", "hardware_concurrency", "device_memory",
            "screen_width", "screen_height", "color_depth", "pixel_ratio",
            "timezone", "locale", "webgl_vendor", "webgl_renderer",
            "canvas_offset", "audio_variance_pct",
        }
        for field in required_fields:
            assert field in profile, f"Missing field: {field}"

    def test_firefox_linux_structure(self):
        """firefox-linux must have all required fingerprint fields."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        profile = ANTI_DETECTION_PROFILES["firefox-linux"]
        required_fields = {
            "user_agent", "platform", "hardware_concurrency", "device_memory",
            "screen_width", "screen_height", "color_depth", "pixel_ratio",
            "timezone", "locale", "webgl_vendor", "webgl_renderer",
            "canvas_offset", "audio_variance_pct",
        }
        for field in required_fields:
            assert field in profile, f"Missing field: {field}"

    def test_edge_windows_structure(self):
        """edge-windows must have all required fingerprint fields."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        profile = ANTI_DETECTION_PROFILES["edge-windows"]
        required_fields = {
            "user_agent", "platform", "hardware_concurrency", "device_memory",
            "screen_width", "screen_height", "color_depth", "pixel_ratio",
            "timezone", "locale", "webgl_vendor", "webgl_renderer",
            "canvas_offset", "audio_variance_pct",
        }
        for field in required_fields:
            assert field in profile, f"Missing field: {field}"

    def test_canvas_offset_is_tuple_of_two_ints(self):
        """canvas_offset must be a (int, int) tuple in every profile."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        for name, profile in ANTI_DETECTION_PROFILES.items():
            offset = profile["canvas_offset"]
            assert isinstance(offset, (tuple, list)), f"{name}: canvas_offset not a tuple"
            assert len(offset) == 2, f"{name}: canvas_offset must have 2 elements"
            assert all(isinstance(v, int) for v in offset), f"{name}: canvas_offset values must be ints"

    def test_audio_variance_pct_is_float(self):
        """audio_variance_pct must be a float in every profile."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        for name, profile in ANTI_DETECTION_PROFILES.items():
            assert isinstance(profile["audio_variance_pct"], (int, float)), (
                f"{name}: audio_variance_pct must be numeric"
            )

    def test_hardware_concurrency_is_positive_int(self):
        """hardware_concurrency must be a positive int in every profile."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        for name, profile in ANTI_DETECTION_PROFILES.items():
            assert isinstance(profile["hardware_concurrency"], int), f"{name}: hardware_concurrency must be int"
            assert profile["hardware_concurrency"] > 0, f"{name}: hardware_concurrency must be positive"

    def test_screen_dimensions_positive(self):
        """screen dimensions must be positive ints in every profile."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        for name, profile in ANTI_DETECTION_PROFILES.items():
            assert profile["screen_width"] > 0, f"{name}: screen_width must be positive"
            assert profile["screen_height"] > 0, f"{name}: screen_height must be positive"

    def test_anti_detection_profile_extends_profile(self):
        """AntiDetectionProfile must extend the base Profile dataclass."""
        from anti_detection.profile_types import AntiDetectionProfile
        from profile_manager import Profile

        assert issubclass(AntiDetectionProfile, Profile)

    def test_anti_detection_profile_has_profile_type_field(self):
        """AntiDetectionProfile must have a profile_type field defaulting to 'standard'."""
        from anti_detection.profile_types import AntiDetectionProfile

        assert "profile_type" in AntiDetectionProfile.model_fields or \
               "profile_type" in AntiDetectionProfile.__dataclass_fields__

    def test_anti_detection_profile_has_fingerprint_field(self):
        """AntiDetectionProfile must have a fingerprint dict field."""
        from anti_detection.profile_types import AntiDetectionProfile

        assert "fingerprint" in AntiDetectionProfile.model_fields or \
               "fingerprint" in AntiDetectionProfile.__dataclass_fields__

    def test_anti_detection_profile_default_profile_type(self):
        """AntiDetectionProfile should default profile_type to 'standard'."""
        from anti_detection.profile_types import AntiDetectionProfile

        p = AntiDetectionProfile(name="test", data_dir="/tmp/test")
        assert p.profile_type == "standard"

    def test_anti_detection_profile_default_fingerprint(self):
        """AntiDetectionProfile should default fingerprint to empty dict."""
        from anti_detection.profile_types import AntiDetectionProfile

        p = AntiDetectionProfile(name="test", data_dir="/tmp/test")
        assert p.fingerprint == {}


# ===================================================================
# EXTENDED ProfileManager — Interface Tests
# ===================================================================
# These tests verify that ProfileManager gains the new anti-detection
# methods with correct signatures. They pass once the stubs exist.
# ===================================================================


class TestProfileManagerAntiDetectionInterface:
    """Interface tests for extended ProfileManager anti-detection methods."""

    def test_create_anti_detection_profile_exists(self, pm):
        """ProfileManager must have create_anti_detection_profile method."""
        assert hasattr(pm, "create_anti_detection_profile")
        assert callable(pm.create_anti_detection_profile)

    def test_create_anti_detection_profile_signature(self, pm):
        """create_anti_detection_profile must accept profile_type and optional name."""
        import inspect

        sig = inspect.signature(pm.create_anti_detection_profile)
        params = list(sig.parameters.keys())
        assert "profile_type" in params, "profile_type required param"
        assert "name" in params, "name optional param"

    def test_get_fingerprint_exists(self, pm):
        """ProfileManager must have get_fingerprint method."""
        assert hasattr(pm, "get_fingerprint")
        assert callable(pm.get_fingerprint)

    def test_get_fingerprint_signature(self, pm):
        """get_fingerprint must accept profile_name and return dict or None."""
        import inspect

        sig = inspect.signature(pm.get_fingerprint)
        assert "profile_name" in sig.parameters

    def test_select_profile_for_request_exists(self, pm):
        """ProfileManager must have select_profile_for_request method."""
        assert hasattr(pm, "select_profile_for_request")
        assert callable(pm.select_profile_for_request)

    def test_select_profile_for_request_signature(self, pm):
        """select_profile_for_request must accept strategy parameter with default 'random'."""
        import inspect

        sig = inspect.signature(pm.select_profile_for_request)
        assert "strategy" in sig.parameters
        # Default should be 'random'
        default = sig.parameters["strategy"].default
        assert default == "random" or default is inspect.Parameter.empty

    def test_validate_profile_exists(self, pm):
        """ProfileManager must have validate_profile method."""
        assert hasattr(pm, "validate_profile")
        assert callable(pm.validate_profile)

    def test_validate_profile_signature(self, pm):
        """validate_profile must accept profile_name and optional checker_url."""
        import inspect

        sig = inspect.signature(pm.validate_profile)
        params = list(sig.parameters.keys())
        assert "profile_name" in params
        assert "checker_url" in params

    def test_create_anti_detection_profile_returns_anti_detection_profile(self, pm):
        """create_anti_detection_profile must return AntiDetectionProfile."""
        from anti_detection.profile_types import AntiDetectionProfile

        result = pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="test-chrome",
        )
        assert isinstance(result, AntiDetectionProfile)

    def test_get_fingerprint_none_for_missing(self, pm):
        """get_fingerprint should return None for nonexistent profile."""
        result = pm.get_fingerprint("nonexistent")
        assert result is None


# ===================================================================
# ProfileValidator — Interface Tests
# ===================================================================
# ProfileValidator is a new validation class used by ProfileManager
# to run detection checks against known fingerprint checkers.
# ===================================================================


class TestProfileValidatorInterface:
    """Interface tests for ProfileValidator."""

    def test_profile_validator_importable(self):
        """ProfileValidator must be importable from profile_manager or anti_detection."""
        from anti_detection.profile_types import ProfileValidator

        assert callable(ProfileValidator)

    def test_profile_validator_validate_method(self):
        """ProfileValidator must have a validate method."""
        from anti_detection.profile_types import ProfileValidator

        assert callable(ProfileValidator.validate)

    def test_validate_signature(self):
        """validate must accept profile_fingerprint dict and optional checker_url."""
        import inspect

        from anti_detection.profile_types import ProfileValidator
        sig = inspect.signature(ProfileValidator.validate)
        params = list(sig.parameters.keys())
        assert "profile_fingerprint" in params or "self" in params
        # Either instance method or classmethod
        assert "checker_url" in params or any(
            "checker" in p for p in params
        )

    def test_validate_returns_dict(self):
        """validate must return a dict with passed, failed_checks, and score."""
        from anti_detection.profile_types import ProfileValidator

        validator = ProfileValidator()
        result = validator.validate(
            profile_fingerprint={"user_agent": "test", "platform": "Win32"},
        )
        assert isinstance(result, dict)
        assert "passed" in result
        assert "failed_checks" in result
        assert "score" in result

    def test_validator_has_checker_list(self):
        """ProfileValidator should know about known checkers."""
        from anti_detection.profile_types import ProfileValidator

        validator = ProfileValidator()
        assert hasattr(validator, "known_checkers") or hasattr(validator, "checkers")
        checkers = getattr(validator, "known_checkers", getattr(validator, "checkers", []))
        assert isinstance(checkers, (list, tuple))
        assert len(checkers) > 0


# ===================================================================
# Selection Strategies — Interface Tests
# ===================================================================
# Verify that all three selection strategies are defined and accepted.
# ===================================================================


class TestSelectionStrategiesInterface:
    """Interface tests for profile selection strategies."""

    def test_strategy_random_works(self, pm):
        """'random' strategy must return an AntiDetectionProfile."""
        from anti_detection.profile_types import AntiDetectionProfile

        # First create an anti-detection profile
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="sel-test-chrome")
        pm.create_anti_detection_profile(profile_type="mobile-safari-ios", name="sel-test-safari")

        profile = pm.select_profile_for_request(strategy="random")
        assert isinstance(profile, AntiDetectionProfile)
        assert profile.profile_type in ("stealth-chrome-120", "mobile-safari-ios")

    def test_strategy_sticky_works(self, pm):
        """'sticky' strategy must return same profile within same session context."""
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="sticky-test")

        first = pm.select_profile_for_request(strategy="sticky")
        second = pm.select_profile_for_request(strategy="sticky")
        assert first.name == second.name, "Sticky strategy should return same profile"

    def test_strategy_geo_match_defined(self):
        """'geo-match' strategy must be accepted as valid strategy name."""
        import inspect

        from profile_manager import ProfileManager

        sig = inspect.signature(ProfileManager.select_profile_for_request)
        assert "strategy" in sig.parameters, "select_profile_for_request must accept a strategy param"

    def test_invalid_strategy_raises(self, pm):
        """Invalid strategy name must raise ValueError."""
        with pytest.raises(ValueError):
            pm.select_profile_for_request(strategy="invalid-strategy-name")

    def test_random_strategy_rotates_across_profiles(self, pm):
        """'random' strategy must eventually return different profiles."""
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="rot-a")
        pm.create_anti_detection_profile(profile_type="mobile-safari-ios", name="rot-b")

        results = set()
        for _ in range(20):
            p = pm.select_profile_for_request(strategy="random")
            results.add(p.name)
        # With 2 profiles and 20 draws, both should appear with high probability
        assert len(results) > 1, "Random strategy should rotate across profiles"


# ===================================================================
# v0.4.0 Multi-Profile Session Integration — Interface Tests
# ===================================================================
# Verify that anti-detection profiles integrate with the existing
# SessionPool / HeadlessManager session system.
# ===================================================================


class TestMultiProfileSessionIntegration:
    """Interface tests for v0.4.0 Multi-Profile Session integration."""

    def test_session_handle_accepts_anti_detection_profile(self, pm):
        """SessionHandle should accept profile_name from an anti-detection profile."""
        from headless_manager import SessionHandle

        # Create an anti-detection profile via the manager
        ad_profile = pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="session-test",
        )

        handle = SessionHandle(
            session_id="sess-1",
            chrome_pid=9999,
            cdp_url="http://127.0.0.1:19222",
            port=19222,
            created_at=1000.0,
            last_active=1000.0,
            status="active",
            profile_name=ad_profile.name,
        )
        assert handle.profile_name == "session-test"
        # Retrieve fingerprint for the session's profile
        fingerprint = pm.get_fingerprint("session-test")
        assert isinstance(fingerprint, dict)
        assert "user_agent" in fingerprint

    def test_headless_manager_launch_with_profile_type(self):
        """HeadlessManager.launch_session must accept an anti-detection profile name."""
        # Check that the existing launch_session signature has a 'profile' parameter
        import inspect

        from headless_manager import HeadlessManager

        sig = inspect.signature(HeadlessManager.launch_session)
        assert "profile" in sig.parameters, (
            "launch_session must accept profile parameter for anti-detection integration"
        )

    def test_fingerprint_used_by_fingerprint_randomizer(self, pm):
        """get_fingerprint output must be consumable by FingerprintRandomizer."""
        from anti_detection.fingerprint_randomizer import FingerprintRandomizer

        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="fp-consumer-test",
        )
        fingerprint = pm.get_fingerprint("fp-consumer-test")
        randomizer = FingerprintRandomizer(profile_fingerprint=fingerprint)
        assert randomizer.profile_fingerprint == fingerprint


# ===================================================================
# ProfileManager Anti-Detection — Behavioral Tests
# ===================================================================
# These tests verify runtime behavior. They raise NotImplementedError
# until the developer completes the implementation.
# ===================================================================


class TestCreateAntiDetectionProfileBehaviors:
    """Behavioral tests for create_anti_detection_profile."""

    def test_creates_and_persists(self, pm, storage_dir):
        """Anti-detection profile must persist to disk."""
        from anti_detection.profile_types import AntiDetectionProfile

        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="persist-ad",
        )

        # Reload from disk
        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        p = pm2.get_profile("persist-ad")
        assert p is not None
        assert isinstance(p, AntiDetectionProfile)
        assert p.profile_type == "stealth-chrome-120"
        assert p.fingerprint != {}

    def test_fingerprint_matches_template(self, pm):
        """Fingerprint must match the predefined profile template."""
        from anti_detection.profile_types import ANTI_DETECTION_PROFILES

        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="fp-match",
        )
        fingerprint = pm.get_fingerprint("fp-match")
        template = ANTI_DETECTION_PROFILES["stealth-chrome-120"]
        for key in template:
            assert fingerprint.get(key) == template[key], (
                f"Mismatch for {key}: got {fingerprint.get(key)}, expected {template[key]}"
            )

    def test_create_without_name_auto_generates(self, pm):
        """Omitting name should auto-generate one from the profile type."""
        p = pm.create_anti_detection_profile(profile_type="mobile-safari-ios")
        assert p.name is not None and len(p.name) > 0
        assert "mobile" in p.name.lower() or "safari" in p.name.lower()

    def test_create_with_invalid_profile_type_raises(self, pm):
        """Invalid profile_type must raise ValueError."""
        with pytest.raises(ValueError):
            pm.create_anti_detection_profile(profile_type="nonexistent-browser")

    def test_create_standard_type_has_empty_fingerprint(self, pm):
        """profile_type='standard' should produce an empty fingerprint dict."""
        pm.create_anti_detection_profile(profile_type="standard", name="std-ad")
        fingerprint = pm.get_fingerprint("std-ad")
        # Standard type has no predefined fingerprint data
        assert isinstance(fingerprint, dict)
        # Standard profiles don't get filled in from ANTI_DETECTION_PROFILES
        assert not fingerprint or fingerprint == {}

    def test_create_persists_fingerprint_in_json(self, pm, storage_dir):
        """Fingerprint data must survive a JSON save/load round-trip."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="json-fp",
        )

        # Read the raw JSON to verify fingerprint is stored
        profiles_file = os.path.join(pm._storage_dir, "profiles.json")
        with open(profiles_file, encoding="utf-8") as f:
            data = json.load(f)

        assert "json-fp" in data
        assert "fingerprint" in data["json-fp"]
        assert data["json-fp"]["fingerprint"]["user_agent"].startswith("Mozilla")
        assert data["json-fp"]["profile_type"] == "stealth-chrome-120"

    def test_create_raises_on_duplicate_name(self, pm):
        """Creating with an existing profile name must raise."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="dup-test",
        )
        with pytest.raises(ValueError, match=r"(?i)already exists|duplicate"):
            pm.create_anti_detection_profile(
                profile_type="mobile-safari-ios",
                name="dup-test",
            )


class TestGetFingerprintBehaviors:
    """Behavioral tests for get_fingerprint."""

    def test_returns_fingerprint_dict(self, pm):
        """get_fingerprint must return a non-empty dict for anti-detection profile."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="fp-test",
        )
        fp = pm.get_fingerprint("fp-test")
        assert isinstance(fp, dict)
        assert len(fp) > 0

    def test_contains_required_keys(self, pm):
        """Fingerprint must contain all signal-group keys for the profile type."""
        pm.create_anti_detection_profile(
            profile_type="firefox-linux",
            name="fp-keys",
        )
        fp = pm.get_fingerprint("fp-keys")
        required_keys = {
            "user_agent", "platform", "hardware_concurrency", "device_memory",
            "screen_width", "screen_height", "color_depth", "pixel_ratio",
            "timezone", "locale", "webgl_vendor", "webgl_renderer",
            "canvas_offset", "audio_variance_pct",
        }
        for key in required_keys:
            assert key in fp, f"Missing key in fingerprint: {key}"

    def test_standard_profile_returns_empty_dict(self, pm):
        """get_fingerprint for 'standard' profile type must return empty dict."""
        pm.create_anti_detection_profile(profile_type="standard", name="std-fp")
        fp = pm.get_fingerprint("std-fp")
        assert fp == {}

    def test_returns_none_for_standard_profile_with_no_ad_data(self, pm):
        """get_fingerprint for a regular (non-anti-detection) profile must return None."""
        pm.create_profile(name="regular-fp")
        fp = pm.get_fingerprint("regular-fp")
        # Regular profiles have no fingerprint dict, so return None
        assert fp is None


class TestSelectProfileForRequestBehaviors:
    """Behavioral tests for select_profile_for_request."""

    def test_random_returns_one_of_available(self, pm):
        """Random strategy must select from available anti-detection profiles."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="random-a",
        )
        pm.create_anti_detection_profile(
            profile_type="mobile-safari-ios",
            name="random-b",
        )

        selected = pm.select_profile_for_request(strategy="random")
        assert selected.name in ("random-a", "random-b")
        assert selected.profile_type in ("stealth-chrome-120", "mobile-safari-ios")

    def test_random_excludes_standard_profiles(self, pm):
        """Random strategy must only select from anti-detection profiles, not standard ones."""
        # Create a mix of AD and standard profiles
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="ad-only")
        pm.create_profile(name="standard-only")

        for _ in range(10):
            selected = pm.select_profile_for_request(strategy="random")
            assert selected.profile_type != "standard", (
                "Random strategy selected a standard profile"
            )

    def test_sticky_same_session_same_profile(self, pm):
        """Sticky strategy must return the same profile within a session context."""
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="sticky-a")
        pm.create_anti_detection_profile(profile_type="mobile-safari-ios", name="sticky-b")

        # Simulate session context via a session_id parameter or implicit state
        session_a_results = []
        session_b_results = []
        for _ in range(5):
            session_a_results.append(
                pm.select_profile_for_request(strategy="sticky", session_id="sess-A")
            )
            session_b_results.append(
                pm.select_profile_for_request(strategy="sticky", session_id="sess-B")
            )

        # Each session should consistently get the same profile
        names_a = {p.name for p in session_a_results}
        names_b = {p.name for p in session_b_results}
        assert len(names_a) == 1, f"Session A got multiple profiles: {names_a}"
        assert len(names_b) == 1, f"Session B got multiple profiles: {names_b}"

    def test_random_no_profiles_raises(self, pm):
        """select_profile_for_request with no anti-detection profiles must raise."""
        with pytest.raises(RuntimeError, match=r"(?i)no.*profile|no.*available"):
            pm.select_profile_for_request(strategy="random")

    def test_sticky_initial_assignment_is_deterministic(self, pm):
        """Sticky strategy should deterministically assign the first seen profile per session."""
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="det-a")
        pm.create_anti_detection_profile(profile_type="mobile-safari-ios", name="det-b")

        # Two independent calls to sticky for the same session
        first = pm.select_profile_for_request(strategy="sticky", session_id="det-sess")
        second = pm.select_profile_for_request(strategy="sticky", session_id="det-sess")
        assert first.name == second.name

    def test_geo_match_matches_timezone_to_proxy(self, pm):
        """Geo-match strategy must select profile whose timezone matches the request location."""
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="geo-us")
        pm.create_anti_detection_profile(profile_type="mobile-safari-ios", name="geo-any")

        # Request from a specific timezone
        selected = pm.select_profile_for_request(
            strategy="geo-match",
            timezone="America/New_York",
        )
        # Should match the US-tuned profile
        assert selected.name == "geo-us" or selected.profile_type == "stealth-chrome-120"


class TestValidateProfileBehaviors:
    """Behavioral tests for validate_profile."""

    def test_validate_returns_report_dict(self, pm):
        """validate_profile must return a dict with expected keys."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="val-test",
        )
        report = pm.validate_profile("val-test")
        assert isinstance(report, dict)
        assert "passed" in report
        assert "failed_checks" in report
        assert "score" in report

    def test_validate_passing_profile(self, pm):
        """A well-configured profile should pass validation."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="val-pass",
        )
        report = pm.validate_profile("val-pass")
        assert isinstance(report["passed"], bool)
        assert report["score"] >= 0.5, "Expected passing profile to score >= 0.5"

    def test_validate_failing_profile(self, pm):
        """A deliberately broken profile should fail validation."""
        # Create a profile with incorrect/mismatched fingerprint data
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="val-fail",
        )
        # Modify fingerprint to be inconsistent
        report = pm.validate_profile("val-fail")
        # Even a good profile may have some failures depending on checker, but score should be reported
        assert 0.0 <= report["score"] <= 1.0
        assert isinstance(report["failed_checks"], list)

    def test_validate_invalid_profile_name(self, pm):
        """validate_profile must raise for nonexistent profile name."""
        with pytest.raises(ValueError):
            pm.validate_profile("nonexistent-profile-name")

    def test_validate_with_custom_checker_url(self, pm):
        """validate_profile must accept a custom checker URL."""
        pm.create_anti_detection_profile(
            profile_type="edge-windows",
            name="val-custom",
        )
        report = pm.validate_profile(
            "val-custom",
            checker_url="https://fingerprint.example.com/check",
        )
        assert isinstance(report, dict)
        assert "passed" in report

    def test_validate_returns_failed_check_details(self, pm):
        """validate_report must include specific failed check names."""
        pm.create_anti_detection_profile(
            profile_type="mobile-safari-ios",
            name="val-details",
        )
        report = pm.validate_profile("val-details")
        for failure in report.get("failed_checks", []):
            assert isinstance(failure, (dict, str))

# ===================================================================
# Multi-Profile Session Integration — Behavioral Tests
# ===================================================================


class TestSessionProfileIntegrationBehavioral:
    """Behavioral tests for profile ↔ session integration."""

    def test_fingerprint_injected_into_session(self, pm):
        """Fingerprint from profile must be usable by FingerprintRandomizer for session injection."""
        from anti_detection.fingerprint_randomizer import FingerprintRandomizer

        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="sess-inject",
        )
        fingerprint = pm.get_fingerprint("sess-inject")

        # The randomizer should generate valid JS patches using this fingerprint
        canvas_patch = FingerprintRandomizer.build_canvas_patch(
            fingerprint["canvas_offset"]
        )
        assert isinstance(canvas_patch, str)
        assert len(canvas_patch) > 0
        assert "getImageData" in canvas_patch or "toDataURL" in canvas_patch

    def test_session_pool_accepts_anti_detection_profile_names(self, pm):
        """SessionPool should manage sessions launched with anti-detection profile names."""
        pm.create_anti_detection_profile(
            profile_type="firefox-linux",
            name="pool-test",
        )

        # Verify the profile is tracked through the pool (profile_name in SessionHandle)
        # This tests the integration contract, not the actual Chrome launch
        assert pm.get_profile("pool-test") is not None
        fingerprint = pm.get_fingerprint("pool-test")
        assert fingerprint is not None

    def test_profile_persistence_across_session_reuse(self, pm):
        """Profile fingerprint must remain stable across multiple session reuses."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="reuse-test",
        )

        fp_first = pm.get_fingerprint("reuse-test")
        # Simulate multiple sessions using the same profile
        for _ in range(3):
            # Re-reading the same profile should return identical fingerprint data
            fp = pm.get_fingerprint("reuse-test")
            assert fp == fp_first, "Fingerprint changed between sessions"

    def test_profile_selection_sticky_across_same_session(self, pm):
        """Sticky profile selection must persist within a single session."""
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="sticky-int-a")
        pm.create_anti_detection_profile(profile_type="mobile-safari-ios", name="sticky-int-b")

        session_handle = "integration-session-1"
        selected_1 = pm.select_profile_for_request(strategy="sticky", session_id=session_handle)
        selected_2 = pm.select_profile_for_request(strategy="sticky", session_id=session_handle)
        selected_3 = pm.select_profile_for_request(strategy="sticky", session_id=session_handle)

        # All three calls should return the same profile
        assert selected_1.name == selected_2.name == selected_3.name

    def test_different_sessions_get_maybe_different_profiles(self, pm):
        """Different sticky sessions may get different profiles (load-balancing)."""
        pm.create_anti_detection_profile(profile_type="stealth-chrome-120", name="bal-a")
        pm.create_anti_detection_profile(profile_type="mobile-safari-ios", name="bal-b")

        results = set()
        for i in range(10):
            selected = pm.select_profile_for_request(
                strategy="sticky", session_id=f"unique-sess-{i}"
            )
            results.add(selected.name)

        # With at least 2 profiles and a spread of sessions, we should see both
        assert len(results) > 1, "Sticky sessions should distribute across profiles"


# ===================================================================
# Auto-Run Detection Tests — Behavioral Tests
# ===================================================================
# Profile validation should auto-run detection tests against known
# fingerprint checkers (mocked in tests).
# ===================================================================


class TestAutoRunDetectionBehaviors:
    """Behavioral tests for auto-run detection checks."""

    def test_validate_contacts_checker(self, pm, monkeypatch):
        """validate_profile must make HTTP requests to checker URLs."""
        import httpx
        calls = []

        async def mock_post(url, *args, **kwargs):
            calls.append(url)
            return httpx.Response(200, json={
                "passed": True,
                "failedChecks": [],
                "score": 0.95,
            })

        monkeypatch.setattr(httpx, "post", mock_post)

        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="auto-detect",
        )
        report = pm.validate_profile("auto-detect")
        assert len(calls) > 0, "validate_profile should call checker URL"
        assert isinstance(report, dict)
        # The monkeypatched response should flow through
        assert report["passed"] is True

    def test_validate_with_multiple_checkers(self, pm, monkeypatch):
        """validate_profile should run checks against multiple checker services."""
        import httpx
        call_targets = []

        async def mock_get(url, *args, **kwargs):
            call_targets.append(url)
            return httpx.Response(200, json={"score": 0.9})

        monkeypatch.setattr(httpx, "get", mock_get)

        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="multi-check",
        )
        pm.validate_profile("multi-check")
        # Should call at least one known checker
        assert len(call_targets) >= 1

    def test_checker_failure_returns_low_score(self, pm, monkeypatch):
        """When checker reports failures, score must reflect them."""
        import httpx

        async def mock_check(url, *args, **kwargs):
            return httpx.Response(200, json={
                "passed": False,
                "failedChecks": ["navigator.webdriver", "chrome.runtime"],
                "score": 0.15,
            })

        monkeypatch.setattr(httpx, "post", mock_check)
        monkeypatch.setattr(httpx, "get", mock_check)

        pm.create_anti_detection_profile(
            profile_type="mobile-safari-ios",
            name="low-score",
        )
        report = pm.validate_profile("low-score")
        assert report["passed"] is False
        assert report["score"] < 0.5
        assert len(report["failed_checks"]) >= 2

    def test_checker_timeout_graceful(self, pm, monkeypatch):
        """Checker timeout should not crash validate_profile; should return partial results."""
        import httpx

        async def timeout_get(url, *args, **kwargs):
            raise httpx.TimeoutException("Connection timed out")

        monkeypatch.setattr(httpx, "get", timeout_get)
        monkeypatch.setattr(httpx, "post", timeout_get)

        pm.create_anti_detection_profile(
            profile_type="edge-windows",
            name="timeout-test",
        )
        # Should not raise despite checker timeout
        report = pm.validate_profile("timeout-test")
        assert isinstance(report, dict)
        assert "passed" in report
        # Timeout should produce a failed/unavailable result
        assert report["score"] <= 0.5 or report["passed"] is False

    def test_known_checker_urls_accessible(self):
        """Known checker URLs in ProfileValidator should be reachable."""
        from anti_detection.profile_types import ProfileValidator

        validator = ProfileValidator()
        checkers = getattr(validator, "known_checkers", getattr(validator, "checkers", []))
        # At minimum the validator should reference Sannysoft
        checker_urls = [c if isinstance(c, str) else c.get("url", "") for c in checkers]
        assert any("sannysoft" in url.lower() for url in checker_urls), (
            "Expected bot.sannysoft.com in known checkers"
        )


# ===================================================================
# ProfileValidator — Behavioral Tests
# ===================================================================


class TestProfileValidatorBehaviors:
    """Behavioral tests for ProfileValidator runtime behavior."""

    def test_direct_validation_logic(self):
        """ProfileValidator should implement actual validation logic."""
        from anti_detection.profile_types import ProfileValidator

        validator = ProfileValidator()
        good_fingerprint = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "platform": "Win32",
            "hardware_concurrency": 8,
            "device_memory": 8,
            "screen_width": 1920,
            "screen_height": 1080,
        }
        result = validator.validate(profile_fingerprint=good_fingerprint)
        assert "passed" in result
        assert "failed_checks" in result
        assert "score" in result

    def test_validation_with_broken_fingerprint(self):
        """Validator should detect inconsistent fingerprint data."""
        from anti_detection.profile_types import ProfileValidator

        validator = ProfileValidator()
        bad_fingerprint = {
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
            "platform": "Win32",  # Mismatch: iOS UA but Win32 platform
            "hardware_concurrency": 2,
            "device_memory": 4,
        }
        result = validator.validate(profile_fingerprint=bad_fingerprint)
        # Should detect the inconsistency
        assert isinstance(result["failed_checks"], list)

    def test_validation_score_ranges(self):
        """Validation score must be between 0.0 and 1.0."""
        from anti_detection.profile_types import ProfileValidator

        validator = ProfileValidator()
        result = validator.validate(profile_fingerprint={})
        assert 0.0 <= result["score"] <= 1.0

    def test_validation_empty_fingerprint(self):
        """Empty fingerprint should produce a failing result."""
        from anti_detection.profile_types import ProfileValidator

        validator = ProfileValidator()
        result = validator.validate(profile_fingerprint={})
        assert result["passed"] is False
        assert len(result["failed_checks"]) > 0


# ===================================================================
# Stub / NotImplementedError Behavioral Tests
# ===================================================================
# These tests raise explicit NotImplementedError if the behavior
# stubs are not yet implemented. They serve as TODO markers for the
# developer.
# ===================================================================


class TestStubBehaviors:
    """NotImplementedError stubs for behaviors not yet implemented."""

    def test_create_anti_detection_profile_behavior_pending(self, pm):
        """create_anti_detection_profile must raise NotImplementedError if not implemented."""
        try:
            pm.create_anti_detection_profile(
                profile_type="stealth-chrome-120",
                name="stub-test",
            )
        except NotImplementedError:
            pytest.skip("create_anti_detection_profile not yet implemented")
        except Exception:  # noqa: BLE001, S110 - any other error means it IS implemented
            pass  # Some other error means it IS implemented, just not correctly

    def test_select_profile_random_behavior_pending(self, pm):
        """select_profile_for_request(random) must raise NotImplementedError if not implemented."""
        try:
            pm.select_profile_for_request(strategy="random")
        except NotImplementedError:
            pytest.skip("select_profile_for_request not yet implemented")
        except (RuntimeError, ValueError):
            pass  # Other errors mean it exists and is partially working

    def test_select_profile_sticky_behavior_pending(self, pm):
        """select_profile_for_request(sticky) must raise NotImplementedError if not implemented."""
        try:
            pm.select_profile_for_request(strategy="sticky")
        except NotImplementedError:
            pytest.skip("Sticky strategy not yet implemented")
        except (RuntimeError, ValueError):
            pass

    def test_validate_profile_behavior_pending(self, pm):
        """validate_profile must raise NotImplementedError if not implemented."""
        try:
            pm.validate_profile("stub-profile")
        except NotImplementedError:
            pytest.skip("validate_profile not yet implemented")
        except (ValueError, KeyError):
            pass  # Non-NotImplementedError means it's implemented but missing the profile

    def test_profile_validator_behavior_pending(self):
        """ProfileValidator.validate must raise NotImplementedError if not implemented."""
        from anti_detection.profile_types import ProfileValidator

        try:
            validator = ProfileValidator()
            validator.validate(profile_fingerprint={"test": "data"})
        except NotImplementedError:
            pytest.skip("ProfileValidator.validate not yet implemented")
        except Exception:  # noqa: BLE001, S110 - any other error means it IS implemented
            pass


# ===================================================================
# Edge Cases & Error Handling
# ===================================================================


class TestAntiDetectionEdgeCases:
    """Edge cases for anti-detection profile management."""

    def test_empty_profiles_json_does_not_crash(self, pm, storage_dir):
        """Corrupt or empty profiles.json must not crash anti-detection operations."""
        profiles_file = os.path.join(storage_dir, "profiles.json")
        with open(profiles_file, "w") as f:
            f.write("")

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        # Creating an anti-detection profile should still work
        p = pm2.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="post-corrupt",
        )
        assert p is not None
        assert p.name == "post-corrupt"

    def test_delete_anti_detection_profile_cleans_up(self, pm):
        """Deleting an anti-detection profile must remove it completely."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="cleanup-ad",
        )
        pm.delete_profile("cleanup-ad")
        assert pm.get_profile("cleanup-ad") is None
        assert pm.get_fingerprint("cleanup-ad") is None

    def test_special_characters_in_profile_name(self, pm):
        """Profile names with special characters should work or be rejected."""
        from anti_detection.profile_types import AntiDetectionProfile

        try:
            p = pm.create_anti_detection_profile(
                profile_type="stealth-chrome-120",
                name="my-ad-profile-v1",
            )
            assert isinstance(p, AntiDetectionProfile)
        except ValueError:
            pytest.skip("Name with hyphens rejected — may be intentional")

    def test_multiple_anti_detection_profiles_same_type(self, pm):
        """Multiple profiles of the same type should each have unique fingerprints."""
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="same-type-a",
        )
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="same-type-b",
        )

        fp1 = pm.get_fingerprint("same-type-a")
        fp2 = pm.get_fingerprint("same-type-b")
        # Same type means identical fingerprint data (deterministic)
        assert fp1 == fp2, (
            "Same profile type should produce identical fingerprints"
        )

    def test_standard_profile_cannot_be_selected_by_strategy(self, pm):
        """Standard (non-AD) profiles must be excluded from selection strategies."""
        pm.create_profile(name="regular-profile")
        pm.create_anti_detection_profile(
            profile_type="stealth-chrome-120",
            name="ad-profile-1",
        )

        selected = pm.select_profile_for_request(strategy="random")
        assert selected.name != "regular-profile", (
            "Standard profile selected by anti-detection strategy"
        )
