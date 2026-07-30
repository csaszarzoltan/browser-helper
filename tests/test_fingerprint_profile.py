"""Pre-development tests for Fingerprint Profile Extension (RED phase).

These tests define the expected ProfileManager fingerprint interface BEFORE
the developer implements it. All behavioral tests will fail with
AttributeError or NotImplementedError until the developer adds:
  - Profile.fingerprint field
  - ProfileManager.generate_fingerprint(name, overrides=None)
  - ProfileManager.get_fingerprint(name)
  - Fingerprint validation logic
  - Import/export fingerprint preservation
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Expected fingerprint field list (as per P1-4 spec)
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


# ===================================================================
# AC #1: Fingerprint schema has all required fields
# ===================================================================


class TestFingerprintSchema:
    """Verify fingerprint field presence in Profile dataclass."""

    def test_fingerprint_field_exists(self):
        """Profile dataclass should have a fingerprint field."""
        from profile_manager import Profile

        assert "fingerprint" in Profile.__dataclass_fields__, (
            "Profile dataclass must have a 'fingerprint' field"
        )

    def test_fingerprint_default_is_none(self):
        """New Profile should have fingerprint=None."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test")
        assert p.fingerprint is None, (
            "New profiles should have fingerprint=None for backward compatibility"
        )

    def test_fingerprint_accepts_dict(self):
        """Profile should accept a dict for the fingerprint field."""
        from profile_manager import Profile

        fp = {field: None for field in FINGERPRINT_FIELDS}
        p = Profile(name="test", data_dir="/tmp/test", fingerprint=fp)
        assert isinstance(p.fingerprint, dict)
        assert p.fingerprint["canvas_offset_x"] is None

    def test_fingerprint_field_count(self):
        """Fingerprint dict should contain exactly the expected fields."""
        from profile_manager import Profile

        fp = {field: None for field in FINGERPRINT_FIELDS}
        p = Profile(name="test", data_dir="/tmp/test", fingerprint=fp)
        assert len(p.fingerprint) == len(FINGERPRINT_FIELDS), (
            f"Expected {len(FINGERPRINT_FIELDS)} fields, got {len(p.fingerprint)}"
        )

    def test_fingerprint_has_all_required_fields(self):
        """Fingerprint dict must contain every required field."""
        from profile_manager import Profile

        fp = {field: None for field in FINGERPRINT_FIELDS}
        p = Profile(name="test", data_dir="/tmp/test", fingerprint=fp)
        for field in FINGERPRINT_FIELDS:
            assert field in p.fingerprint, (
                f"Fingerprint missing required field: {field}"
            )


# ===================================================================
# AC #2: Fingerprint generation produces valid values
# ===================================================================


class TestFingerprintGeneration:
    """Verify generate_fingerprint produces valid fingerprint values."""

    def test_generate_fingerprint_method_exists(self):
        """ProfileManager should have a generate_fingerprint method."""
        from profile_manager import ProfileManager

        assert hasattr(ProfileManager, "generate_fingerprint"), (
            "ProfileManager must have generate_fingerprint method"
        )

    def test_generate_fingerprint_returns_dict(self, pm):
        """generate_fingerprint should return a dict."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert isinstance(fp, dict), "generate_fingerprint must return a dict"

    def test_generated_fingerprint_has_all_fields(self, pm):
        """Generated fingerprint must contain all required fields."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        for field in FINGERPRINT_FIELDS:
            assert field in fp, (
                f"Generated fingerprint missing field: {field}"
            )

    def test_generated_values_are_not_none(self, pm):
        """All generated fingerprint values should be non-None."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        for field in FINGERPRINT_FIELDS:
            assert fp[field] is not None, (
                f"Generated field {field} must not be None"
            )

    def test_canvas_offset_is_integer_pair(self, pm):
        """canvas_offset_x/y should be integers."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert isinstance(fp["canvas_offset_x"], int)
        assert isinstance(fp["canvas_offset_y"], int)

    def test_webgl_vendor_is_string(self, pm):
        """webgl_vendor should be a non-empty string."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert isinstance(fp["webgl_vendor"], str) and len(fp["webgl_vendor"]) > 0

    def test_webgl_renderer_is_string(self, pm):
        """webgl_renderer should be a non-empty string."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert isinstance(fp["webgl_renderer"], str) and len(fp["webgl_renderer"]) > 0

    def test_hardware_concurrency_is_positive_int(self, pm):
        """hardware_concurrency should be a positive integer (2-64)."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert isinstance(fp["hardware_concurrency"], int)
        assert 2 <= fp["hardware_concurrency"] <= 64

    def test_device_memory_is_positive_number(self, pm):
        """device_memory should be a positive number (0.25-128)."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert isinstance(fp["device_memory"], (int, float))
        assert 0.25 <= fp["device_memory"] <= 128

    def test_screen_dimensions_are_positive_ints(self, pm):
        """screen_width/height should be positive integers."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert isinstance(fp["screen_width"], int) and fp["screen_width"] >= 800
        assert isinstance(fp["screen_height"], int) and fp["screen_height"] >= 600

    def test_color_depth_is_valid(self, pm):
        """color_depth should be 24 or 30 (typical values)."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert fp["color_depth"] in (24, 30), (
            f"color_depth should be 24 or 30, got {fp['color_depth']}"
        )

    def test_timezone_is_valid_string(self, pm):
        """timezone should be a valid IANA timezone string."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        assert isinstance(fp["timezone"], str) and "/" in fp["timezone"], (
            f"timezone should be IANA format (e.g. 'America/New_York'), got {fp['timezone']!r}"
        )

    def test_platform_is_valid_string(self, pm):
        """platform should be a known browser platform string."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        known_platforms = {"Win32", "MacIntel", "Linux x86_64", "Linux armv8l"}
        assert fp["platform"] in known_platforms, (
            f"platform should be one of {known_platforms}, got {fp['platform']!r}"
        )


# ===================================================================
# AC #3: Overrides are applied
# ===================================================================


class TestFingerprintOverrides:
    """Verify fingerprint generation accepts field overrides."""

    def test_override_preserves_other_fields(self, pm):
        """Override one field, others should still be populated."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test", overrides={"canvas_offset_x": 5})
        assert fp["canvas_offset_x"] == 5
        # Other fields should still have values
        assert fp["canvas_offset_y"] is not None
        assert fp["webgl_vendor"] is not None

    def test_override_canvas_offset_x(self, pm):
        """Override canvas_offset_x should be reflected in result."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test", overrides={"canvas_offset_x": 3})
        assert fp["canvas_offset_x"] == 3

    def test_override_canvas_offset_y(self, pm):
        """Override canvas_offset_y should be reflected in result."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test", overrides={"canvas_offset_y": 7})
        assert fp["canvas_offset_y"] == 7

    def test_override_multiple_fields(self, pm):
        """Multiple field overrides should all be applied."""
        pm.create_profile("test")
        overrides = {
            "canvas_offset_x": 1,
            "canvas_offset_y": 2,
            "webgl_vendor": "Google Inc. (Intel)",
            "hardware_concurrency": 8,
            "timezone": "Europe/Zurich",
        }
        fp = pm.generate_fingerprint("test", overrides=overrides)
        for field, value in overrides.items():
            assert fp[field] == value, (
                f"Override field {field} should be {value!r}, got {fp[field]!r}"
            )

    def test_override_empty_dict(self, pm):
        """Empty overrides dict should produce default fingerprint."""
        pm.create_profile("test")
        fp1 = pm.generate_fingerprint("test", overrides={})
        fp2 = pm.generate_fingerprint("test")
        # Both should be valid dicts with all fields
        assert isinstance(fp1, dict)
        assert isinstance(fp2, dict)
        assert len(fp1) == len(FINGERPRINT_FIELDS)


# ===================================================================
# AC #4: GET returns fingerprint after POST/generation
# ===================================================================


class TestFingerprintGet:
    """Verify get_fingerprint returns generated fingerprint."""

    def test_get_fingerprint_method_exists(self):
        """ProfileManager should have a get_fingerprint method."""
        from profile_manager import ProfileManager

        assert hasattr(ProfileManager, "get_fingerprint"), (
            "ProfileManager must have get_fingerprint method"
        )

    def test_get_fingerprint_returns_generated(self, pm):
        """get_fingerprint should return the same dict as generate_fingerprint."""
        pm.create_profile("test")
        generated = pm.generate_fingerprint("test")
        retrieved = pm.get_fingerprint("test")
        assert retrieved == generated, (
            "get_fingerprint should return same data as was generated"
        )

    def test_get_fingerprint_none_when_not_generated(self, pm):
        """get_fingerprint should return None if no fingerprint was generated."""
        pm.create_profile("test")
        fp = pm.get_fingerprint("test")
        assert fp is None, (
            "get_fingerprint should return None when no fingerprint exists"
        )

    def test_get_fingerprint_nonexistent_profile(self, pm):
        """get_fingerprint should raise KeyError or return None for nonexistent profile."""
        from profile_manager import ProfileManager

        mgr = ProfileManager(storage_dir=str(pm._storage_dir))
        # Profile doesn't exist — should either raise or return None
        try:
            result = mgr.get_fingerprint("nonexistent")
            assert result is None, (
                "get_fingerprint on nonexistent profile should return None"
            )
        except (KeyError, ValueError):
            pass  # Also acceptable


# ===================================================================
# AC #6: Existing CRUD still works unchanged
# ===================================================================


class TestFingerprintCRUDCompat:
    """Verify existing ProfileManager CRUD is backward-compatible."""

    def test_create_profile(self, pm):
        """create_profile should still work."""
        profile = pm.create_profile("test-fp")
        assert profile.name == "test-fp"
        assert os.path.isabs(profile.data_dir)

    def test_get_profile(self, pm):
        """get_profile should still work."""
        pm.create_profile("test-fp")
        profile = pm.get_profile("test-fp")
        assert profile is not None
        assert profile.name == "test-fp"

    def test_list_profiles(self, pm):
        """list_profiles should still work."""
        pm.create_profile("alpha")
        pm.create_profile("beta")
        assert len(pm.list_profiles()) == 2

    def test_delete_profile(self, pm):
        """delete_profile should still work."""
        pm.create_profile("temp")
        assert pm.delete_profile("temp") is True
        assert pm.get_profile("temp") is None

    def test_rename_profile(self, pm):
        """rename_profile should still work."""
        pm.create_profile("old")
        assert pm.rename_profile("old", "new") is True
        assert pm.get_profile("old") is None
        assert pm.get_profile("new") is not None

    def test_add_extension(self, pm):
        """add_extension should still work."""
        pm.create_profile("test")
        assert pm.add_extension("test", "/ext/plug") is True
        assert "/ext/plug" in pm.get_extensions("test")

    def test_fingerprint_stored_on_profile(self, pm):
        """After generate_fingerprint, the profile should have fingerprint via get_profile."""
        pm.create_profile("test")
        fp = pm.generate_fingerprint("test")
        profile = pm.get_profile("test")
        assert profile.fingerprint is not None
        assert profile.fingerprint == fp


# ===================================================================
# AC #7: Import/export preserves fingerprint fields
# ===================================================================


class TestFingerprintImportExport:
    """Verify export/import preserves fingerprint fields."""

    def test_export_includes_fingerprint(self, pm, tmp_path):
        """Exported profile JSON should include fingerprint field."""
        pm.create_profile("test")
        pm.generate_fingerprint("test")
        output = str(tmp_path / "test-fp.zip")
        pm.export_profile("test", output)

        import zipfile

        with zipfile.ZipFile(output, "r") as zf:
            meta = json.loads(zf.read("profiles.json"))
            assert "fingerprint" in meta, (
                "Exported profiles.json must include fingerprint field"
            )
            assert meta["fingerprint"] is not None

    def test_import_restores_fingerprint(self, pm, tmp_path):
        """Imported profile should retain fingerprint."""
        pm.create_profile("source")
        fp = pm.generate_fingerprint("source")
        export_path = str(tmp_path / "source.zip")
        pm.export_profile("source", export_path)
        pm.delete_profile("source")

        imported = pm.import_profile(export_path)
        assert imported.fingerprint == fp, (
            "Imported profile should have same fingerprint as exported"
        )

    def test_import_restores_fingerprint_after_reload(self, pm, tmp_path, storage_dir):
        """Fingerprint should survive reload after import."""
        pm.create_profile("source")
        fp = pm.generate_fingerprint("source", overrides={"timezone": "Asia/Tokyo"})
        export_path = str(tmp_path / "source.zip")
        pm.export_profile("source", export_path)
        pm.delete_profile("source")

        pm.import_profile(export_path)

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        p = pm2.get_profile("source")
        assert p.fingerprint == fp

    def test_export_without_fingerprint(self, pm, tmp_path):
        """Exporting a profile without fingerprint should still work."""
        pm.create_profile("plain")
        output = str(tmp_path / "plain.zip")
        pm.export_profile("plain", output)

        import zipfile

        with zipfile.ZipFile(output, "r") as zf:
            meta = json.loads(zf.read("profiles.json"))
            assert "fingerprint" in meta, (
                "profiles.json should always include fingerprint field (default None)"
            )
            assert meta["fingerprint"] is None

    def test_import_without_fingerprint(self, pm, tmp_path):
        """Importing a profile without fingerprint field should still work (backward compat)."""
        # Create a minimal export without fingerprint
        pm.create_profile("legacy")
        export_path = str(tmp_path / "legacy.zip")
        pm.export_profile("legacy", export_path)

        # Manually strip fingerprint from the export
        import zipfile

        stripped_path = str(tmp_path / "legacy-stripped.zip")
        with zipfile.ZipFile(export_path, "r") as zf_src:
            meta = json.loads(zf_src.read("profiles.json"))
            meta.pop("fingerprint", None)
            with zipfile.ZipFile(stripped_path, "w") as zf_dst:
                zf_dst.writestr("profiles.json", json.dumps(meta))
                for member in zf_src.namelist():
                    if member == "profiles.json":
                        continue
                    zf_dst.writestr(member, zf_src.read(member))

        pm.delete_profile("legacy")
        imported = pm.import_profile(stripped_path)
        assert imported.fingerprint is None or imported.fingerprint == {}, (
            "Legacy profile without fingerprint should have None/empty fingerprint"
        )


# ===================================================================
# AC #8: Backward compatibility — old profiles without fingerprint
# ===================================================================


class TestFingerprintBackwardCompat:
    """Verify backward compatibility with profiles that have no fingerprint field."""

    def test_old_profile_json_still_loads(self, storage_dir):
        """Profiles JSON without fingerprint field should load without error."""
        from profile_manager import ProfileManager

        os.makedirs(storage_dir, exist_ok=True)
        profiles_file = os.path.join(storage_dir, "profiles.json")
        old_data = {
            "legacy": {
                "name": "legacy",
                "data_dir": os.path.join(storage_dir, "profiles", "legacy"),
                "created_at": 1000.0,
                "last_used": 1000.0,
                "extensions": [],
                "description": "Old profile",
                "tags": [],
                "resource_limits": {"max_memory_mb": 512, "max_cpu_percent": 80},
                # NOTE: no "fingerprint" field
            }
        }
        with open(profiles_file, "w") as f:
            json.dump(old_data, f)

        mgr = ProfileManager(storage_dir=storage_dir)
        p = mgr.get_profile("legacy")
        assert p is not None
        assert p.name == "legacy"
        # fingerprint should default to None
        assert p.fingerprint is None, (
            "Old profile without fingerprint should have fingerprint=None"
        )

    def test_get_fingerprint_on_old_profile_returns_none(self, storage_dir):
        """get_fingerprint on legacy profile should return None, not error."""
        from profile_manager import ProfileManager

        os.makedirs(storage_dir, exist_ok=True)
        profiles_file = os.path.join(storage_dir, "profiles.json")
        old_data = {
            "legacy": {
                "name": "legacy",
                "data_dir": os.path.join(storage_dir, "profiles", "legacy"),
                "created_at": 1000.0,
                "last_used": 1000.0,
                "extensions": [],
                "description": "Old profile",
                "tags": [],
                "resource_limits": {"max_memory_mb": 512, "max_cpu_percent": 80},
            }
        }
        with open(profiles_file, "w") as f:
            json.dump(old_data, f)

        mgr = ProfileManager(storage_dir=storage_dir)
        fp = mgr.get_fingerprint("legacy")
        assert fp is None, (
            "get_fingerprint on legacy profile should return None"
        )

    def test_generate_fingerprint_on_old_profile_upgrades(self, storage_dir):
        """generate_fingerprint on a legacy profile should add fingerprint."""
        from profile_manager import ProfileManager

        os.makedirs(storage_dir, exist_ok=True)
        profiles_file = os.path.join(storage_dir, "profiles.json")
        old_data = {
            "legacy": {
                "name": "legacy",
                "data_dir": os.path.join(storage_dir, "profiles", "legacy"),
                "created_at": 1000.0,
                "last_used": 1000.0,
                "extensions": [],
                "description": "Old profile",
                "tags": [],
                "resource_limits": {"max_memory_mb": 512, "max_cpu_percent": 80},
            }
        }
        with open(profiles_file, "w") as f:
            json.dump(old_data, f)

        mgr = ProfileManager(storage_dir=storage_dir)
        fp = mgr.generate_fingerprint("legacy")
        assert isinstance(fp, dict)
        assert len(fp) == len(FINGERPRINT_FIELDS)

        # Verify it persists after reload
        from profile_manager import ProfileManager

        mgr2 = ProfileManager(storage_dir=storage_dir)
        p = mgr2.get_profile("legacy")
        assert p.fingerprint is not None
        assert p.fingerprint == fp


# ===================================================================
# AC #10: Invalid override values return appropriate errors
# ===================================================================


class TestFingerprintValidation:
    """Verify validation of override values."""

    def test_invalid_canvas_offset_type(self, pm):
        """canvas_offset_x/y should reject non-integer types."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"canvas_offset_x": "abc"})

    def test_invalid_hardware_concurrency_zero(self, pm):
        """hardware_concurrency must be positive."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"hardware_concurrency": 0})

    def test_invalid_hardware_concurrency_negative(self, pm):
        """hardware_concurrency must be positive."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"hardware_concurrency": -4})

    def test_invalid_device_memory_negative(self, pm):
        """device_memory must be positive."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"device_memory": -1})

    def test_invalid_color_depth(self, pm):
        """color_depth must be a valid value (24 or 30)."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"color_depth": 16})

    def test_invalid_timezone_format(self, pm):
        """timezone must be a valid IANA string."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"timezone": "NotATimezone"})

    def test_invalid_platform(self, pm):
        """platform must be a known value."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"platform": "Commodore64"})

    def test_invalid_screen_width(self, pm):
        """screen_width must be a positive integer >= 800."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"screen_width": 320})

    def test_unknown_field_rejected(self, pm):
        """Unknown fields in overrides should be rejected."""
        pm.create_profile("test")
        with pytest.raises((ValueError, KeyError)):
            pm.generate_fingerprint("test", overrides={"nonexistent_field": "value"})

    def test_none_override(self, pm):
        """Setting an override to None should be rejected or use default."""
        pm.create_profile("test")
        with pytest.raises((ValueError, TypeError)):
            pm.generate_fingerprint("test", overrides={"canvas_offset_x": None})

    def test_generate_on_nonexistent_profile_errors(self, pm):
        """generate_fingerprint on nonexistent profile should raise error."""
        with pytest.raises((KeyError, ValueError)):
            pm.generate_fingerprint("nonexistent")
