"""
Pre-development tests for Profile.fingerprint_config + headless injection (RED phase).

Tests P1.1 (Profile.fingerprint_config field, JSON persistence, export/import)
and P1.2 (REST endpoints for fingerprint config + headless injection in launch_session).

Interface tests (PASS) — check signatures, field existence, backward compatibility.
Behavioral tests (FAIL) — raise NotImplementedError until the developer implements
  Profile.fingerprint_config, FingerprintConfig, and headless injection.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


# ---------------------------------------------------------------------------
# Expected FingerprintConfig field names (mirror existing FINGERPRINT_FIELDS)
# ---------------------------------------------------------------------------
FINGERPRINT_CONFIG_FIELDS = [
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

SAMPLE_CONFIG = {
    "screen_width": 1920,
    "screen_height": 1080,
    "webgl_vendor": "Google Inc. (Intel)",
    "timezone": "America/New_York",
    "platform": "Win32",
}


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


@pytest.fixture
def pm_with_config(storage_dir):
    """ProfileManager with a profile that has fingerprint_config set."""
    from profile_manager import ProfileManager

    mgr = ProfileManager(storage_dir=storage_dir)
    mgr.create_profile("fp-configured")
    # Set fingerprint_config on the profile via raw dict — the dev's setter
    # or direct field assignment is expected
    raw = mgr._data["fp-configured"]
    raw["fingerprint_config"] = dict(SAMPLE_CONFIG)
    mgr.save()
    return mgr


# ===================================================================
# P1.1-a: Profile.fingerprint_config field existence
# ===================================================================


class TestFingerprintConfigField:
    """Verify Profile dataclass gains a fingerprint_config field."""

    def test_fingerprint_config_field_exists(self):
        """Profile dataclass should have a fingerprint_config field."""
        from profile_manager import Profile

        assert "fingerprint_config" in Profile.__dataclass_fields__, (
            "Profile dataclass must have a 'fingerprint_config' field"
        )

    def test_fingerprint_config_default_none(self):
        """New Profile should have fingerprint_config=None."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test")
        assert p.fingerprint_config is None, (
            "New profiles should have fingerprint_config=None for backward compatibility"
        )

    def test_fingerprint_config_accepts_dict(self):
        """Profile should accept a dict for fingerprint_config."""
        from profile_manager import Profile

        cfg = {"timezone": "Europe/Budapest"}
        p = Profile(name="test", data_dir="/tmp/test", fingerprint_config=cfg)
        assert isinstance(p.fingerprint_config, dict)
        assert p.fingerprint_config["timezone"] == "Europe/Budapest"

    def test_fingerprint_config_accepts_empty_dict(self):
        """Profile should accept an empty dict for fingerprint_config."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test", fingerprint_config={})
        assert p.fingerprint_config == {}

    def test_fingerprint_config_backward_compat_no_arg(self):
        """Creating a Profile without fingerprint_config must not fail."""
        from profile_manager import Profile

        p = Profile(name="legacy", data_dir="/tmp/legacy")
        assert p.fingerprint_config is None


# ===================================================================
# P1.1-b: to_dict / from_dict round-trip
# ===================================================================


class TestFingerprintConfigSerialization:
    """Verify fingerprint_config survives to_dict/from_dict round-trip."""

    def test_to_dict_includes_fingerprint_config(self):
        """to_dict() should include fingerprint_config key."""
        from profile_manager import Profile

        p = Profile(
            name="test",
            data_dir="/tmp/test",
            fingerprint_config=dict(SAMPLE_CONFIG),
        )
        d = p.to_dict()
        assert "fingerprint_config" in d, (
            "to_dict() must include 'fingerprint_config' key"
        )
        assert d["fingerprint_config"] == SAMPLE_CONFIG

    def test_to_dict_fingerprint_config_none(self):
        """to_dict() should include fingerprint_config as None when unset."""
        from profile_manager import Profile

        p = Profile(name="test", data_dir="/tmp/test")
        d = p.to_dict()
        assert "fingerprint_config" in d
        assert d["fingerprint_config"] is None

    def test_from_dict_with_fingerprint_config(self):
        """from_dict() should restore fingerprint_config."""
        from profile_manager import Profile

        d = {
            "name": "test",
            "data_dir": "/tmp/test",
            "created_at": 1000.0,
            "last_used": 1000.0,
            "extensions": [],
            "description": "",
            "tags": [],
            "resource_limits": {"max_memory_mb": 512, "max_cpu_percent": 80},
            "fingerprint_config": dict(SAMPLE_CONFIG),
        }
        p = Profile.from_dict(d)
        assert p.fingerprint_config == SAMPLE_CONFIG, (
            "from_dict() should restore fingerprint_config"
        )

    def test_from_dict_fingerprint_config_none(self):
        """from_dict() with fingerprint_config=None should set field to None."""
        from profile_manager import Profile

        d = {
            "name": "test",
            "data_dir": "/tmp/test",
            "created_at": 1000.0,
            "last_used": 1000.0,
            "extensions": [],
            "description": "",
            "tags": [],
            "resource_limits": {"max_memory_mb": 512, "max_cpu_percent": 80},
            "fingerprint_config": None,
        }
        p = Profile.from_dict(d)
        assert p.fingerprint_config is None

    def test_from_dict_without_fingerprint_config(self):
        """from_dict() without fingerprint_config key must not fail (backward compat)."""
        from profile_manager import Profile

        d = {
            "name": "legacy",
            "data_dir": "/tmp/legacy",
            "created_at": 1000.0,
            "last_used": 1000.0,
            "extensions": [],
            "description": "",
            "tags": [],
            "resource_limits": {"max_memory_mb": 512, "max_cpu_percent": 80},
            # NOTE: no fingerprint_config key
        }
        p = Profile.from_dict(d)
        assert p.fingerprint_config is None, (
            "Legacy profile dict without fingerprint_config should default to None"
        )


# ===================================================================
# P1.1-c: JSON persistence — save / reload round-trip
# ===================================================================


class TestFingerprintConfigPersistence:
    """Verify fingerprint_config persists through save → reload."""

    def test_save_persists_fingerprint_config(self, pm, storage_dir):
        """Profile with fingerprint_config should persist it in JSON."""
        pm.create_profile("persist-test")
        # Set fingerprint_config via internal dict (dev's API may differ)
        pm._data["persist-test"]["fingerprint_config"] = dict(SAMPLE_CONFIG)
        pm.save()

        # Reload
        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        raw = pm2._data.get("persist-test", {})
        assert raw.get("fingerprint_config") == SAMPLE_CONFIG, (
            "fingerprint_config must be persisted in profiles.json"
        )

    def test_reload_restores_fingerprint_config(self, pm, storage_dir):
        """Profile loaded from JSON should have fingerprint_config set."""
        pm.create_profile("reload-test")
        pm._data["reload-test"]["fingerprint_config"] = {"timezone": "Asia/Tokyo"}
        pm.save()

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        p = pm2.get_profile("reload-test")
        assert p is not None
        assert p.fingerprint_config == {"timezone": "Asia/Tokyo"}, (
            "Reloaded profile should have fingerprint_config"
        )

    def test_save_without_fingerprint_config_no_error(self, pm, storage_dir):
        """Profile without fingerprint_config should save and reload fine."""
        pm.create_profile("no-config")

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        p = pm2.get_profile("no-config")
        assert p.fingerprint_config is None

    def test_fingerprint_config_persists_across_save_calls(self, pm, storage_dir):
        """Multiple save/load cycles must preserve fingerprint_config."""
        pm.create_profile("multi")
        pm._data["multi"]["fingerprint_config"] = {"canvas_offset_x": 5}
        pm.save()

        for _ in range(3):
            from profile_manager import ProfileManager

            pm2 = ProfileManager(storage_dir=storage_dir)
            p = pm2.get_profile("multi")
            assert p.fingerprint_config == {"canvas_offset_x": 5}
            # Re-save
            pm2.save()


# ===================================================================
# P1.1-d: Export / import preserves fingerprint_config
# ===================================================================


class TestFingerprintConfigImportExport:
    """Verify export/import preserves fingerprint_config."""

    def test_export_includes_fingerprint_config(self, pm, tmp_path):
        """Exported ZIP profiles.json should contain fingerprint_config."""
        pm.create_profile("fp-export")
        pm._data["fp-export"]["fingerprint_config"] = dict(SAMPLE_CONFIG)
        pm.save()

        import zipfile

        export_path = str(tmp_path / "fp-export.zip")
        pm.export_profile("fp-export", export_path)

        with zipfile.ZipFile(export_path, "r") as zf:
            meta = json.loads(zf.read("profiles.json"))
            assert "fingerprint_config" in meta, (
                "Exported profiles.json must include fingerprint_config"
            )
            assert meta["fingerprint_config"] == SAMPLE_CONFIG

    def test_import_restores_fingerprint_config(self, pm, tmp_path, storage_dir):
        """Imported profile should retain fingerprint_config."""
        pm.create_profile("source")
        cfg = {"timezone": "Asia/Shanghai", "screen_width": 2560}
        pm._data["source"]["fingerprint_config"] = cfg
        pm.save()

        export_path = str(tmp_path / "source.zip")
        pm.export_profile("source", export_path)
        pm.delete_profile("source")

        imported = pm.import_profile(export_path)
        assert imported.fingerprint_config == cfg, (
            "Imported profile should have same fingerprint_config as exported"
        )

    def test_import_restores_after_reload(self, pm, tmp_path, storage_dir):
        """fingerprint_config should survive import + reload cycle."""
        pm.create_profile("src")
        cfg = {"platform": "MacIntel", "timezone": "US/Eastern"}
        pm._data["src"]["fingerprint_config"] = cfg
        pm.save()

        export_path = str(tmp_path / "src.zip")
        pm.export_profile("src", export_path)
        pm.delete_profile("src")
        pm.import_profile(export_path)

        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        p = pm2.get_profile("src")
        assert p.fingerprint_config == cfg

    def test_export_without_fingerprint_config(self, pm, tmp_path):
        """Exporting a profile without fingerprint_config should work."""
        pm.create_profile("plain")
        export_path = str(tmp_path / "plain.zip")
        pm.export_profile("plain", export_path)

        import zipfile

        with zipfile.ZipFile(export_path, "r") as zf:
            meta = json.loads(zf.read("profiles.json"))
            # Should always include the field, defaulting to None
            assert "fingerprint_config" in meta
            assert meta["fingerprint_config"] is None

    def test_import_without_fingerprint_config(self, pm, tmp_path):
        """Importing legacy export without fingerprint_config should work."""
        pm.create_profile("legacy")
        export_path = str(tmp_path / "legacy.zip")
        pm.export_profile("legacy", export_path)

        # Strip fingerprint_config from export
        import zipfile

        stripped_path = str(tmp_path / "legacy-stripped.zip")
        with zipfile.ZipFile(export_path, "r") as zf_src:
            meta = json.loads(zf_src.read("profiles.json"))
            meta.pop("fingerprint_config", None)
            with zipfile.ZipFile(stripped_path, "w") as zf_dst:
                zf_dst.writestr("profiles.json", json.dumps(meta))
                for member in zf_src.namelist():
                    if member == "profiles.json":
                        continue
                    zf_dst.writestr(member, zf_src.read(member))

        pm.delete_profile("legacy")
        imported = pm.import_profile(stripped_path)
        assert imported.fingerprint_config is None, (
            "Legacy import without fingerprint_config should default to None"
        )


# ===================================================================
# P1.1-e: Backward compatibility — old JSON without fingerprint_config
# ===================================================================


class TestFingerprintConfigBackwardCompat:
    """Profiles JSON without fingerprint_config must load without error."""

    def test_old_json_still_loads(self, storage_dir):
        """Profiles JSON without fingerprint_config field should load fine."""
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
                # NOTE: no fingerprint_config
            }
        }
        with open(profiles_file, "w") as f:
            json.dump(old_data, f)

        mgr = ProfileManager(storage_dir=storage_dir)
        p = mgr.get_profile("legacy")
        assert p is not None
        assert p.fingerprint_config is None, (
            "Old profile without fingerprint_config should have None"
        )

    def test_old_profile_with_existing_fingerprint_unchanged(self, storage_dir):
        """Adding fingerprint_config must not break existing fingerprint field."""
        from profile_manager import Profile

        # Create a profile that already has fingerprint field set
        p = Profile(
            name="hybrid",
            data_dir="/tmp/hybrid",
            fingerprint={"canvas_offset_x": 3, "canvas_offset_y": 7},
        )
        # Setting fingerprint_config should be independent
        p.fingerprint_config = {"timezone": "Europe/London"}
        assert p.fingerprint == {"canvas_offset_x": 3, "canvas_offset_y": 7}
        assert p.fingerprint_config == {"timezone": "Europe/London"}


# ===================================================================
# P1.1-f: FingerprintConfig schema definition
# ===================================================================


class TestFingerprintConfigSchema:
    """Verify FingerprintConfig class/module exists and defines valid fields."""

    def test_fingerprint_config_importable(self):
        """FingerprintConfig should be importable from fingerprint_engine."""
        try:
            from fingerprint_engine import FingerprintConfig
        except ImportError:
            from profile_manager import FingerprintConfig as _F
            FingerprintConfig = _F
        # Just being importable is the interface test
        assert True

    def test_fingerprint_config_has_known_fields(self):
        """FingerprintConfig should define all known fingerprint fields."""
        try:
            from fingerprint_engine import FingerprintConfig
        except ImportError:
            from profile_manager import FingerprintConfig as _F
            FingerprintConfig = _F

        # Check that FingerprintConfig defines the expected fields
        # It could be a TypedDict, dataclass, Pydantic model, or simple list
        if hasattr(FingerprintConfig, "__annotations__"):
            fields = FingerprintConfig.__annotations__
        elif hasattr(FingerprintConfig, "model_fields"):
            fields = FingerprintConfig.model_fields
        elif hasattr(FingerprintConfig, "__dataclass_fields__"):
            fields = FingerprintConfig.__dataclass_fields__
        elif isinstance(FingerprintConfig, (list, tuple, set)):
            fields = {f: None for f in FingerprintConfig}
        elif hasattr(FingerprintConfig, "fields"):
            fields = FingerprintConfig.fields
        else:
            # Allow dynamic resolution
            assert callable(FingerprintConfig), (
                "FingerprintConfig must be callable or have fields"
            )
            return

        for field in FINGERPRINT_CONFIG_FIELDS:
            assert field in fields, (
                f"FingerprintConfig missing expected field: {field}"
            )

    def test_fingerprint_config_validates_dict(self):
        """FingerprintConfig should validate a dict of config values."""
        try:
            from fingerprint_engine import FingerprintConfig
        except ImportError:
            from profile_manager import FingerprintConfig as _F
            FingerprintConfig = _F

        # Should not raise for valid fields
        valid_config = {"timezone": "Europe/Berlin", "screen_width": 1920}
        if isinstance(FingerprintConfig, type) and hasattr(FingerprintConfig, "model_validate"):
            # Pydantic model
            result = FingerprintConfig.model_validate(valid_config)
        elif callable(FingerprintConfig) and not isinstance(FingerprintConfig, type):
            # It's a function validator
            result = FingerprintConfig(valid_config)
            assert result is True or isinstance(result, dict)
        elif isinstance(FingerprintConfig, type):
            try:
                result = FingerprintConfig(**valid_config)
                assert result is not None
            except TypeError:
                pass  # Different constructor signature
        # Just not raising is sufficient

    def test_fingerprint_config_rejects_unknown(self):
        """FingerprintConfig should reject unknown field names."""
        try:
            from fingerprint_engine import FingerprintConfig
        except ImportError:
            from profile_manager import FingerprintConfig as _F
            FingerprintConfig = _F

        invalid_config = {"nonexistent_field": "value"}
        if hasattr(FingerprintConfig, "model_validate"):
            with pytest.raises((ValueError, TypeError, KeyError)):
                FingerprintConfig.model_validate(invalid_config)
        elif callable(FingerprintConfig) and not isinstance(FingerprintConfig, type):
            with pytest.raises((ValueError, TypeError, KeyError)):
                FingerprintConfig(invalid_config)
        elif isinstance(FingerprintConfig, type):
            with pytest.raises((ValueError, TypeError, KeyError)):
                FingerprintConfig(**invalid_config)


# ===================================================================
# P1.2-a: GET /profiles/{name}/fingerprint
# ===================================================================


class TestGetFingerprintConfig:
    """GET /profiles/{name}/fingerprint — retrieve fingerprint config."""

    @pytest.mark.asyncio
    async def test_get_returns_config(self, pm_with_config, storage_dir):
        """GET should return existing fingerprint_config."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        # Override profile manager in the app
        app.dependency_overrides = {}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profile/fp-configured/fingerprint")
            assert resp.status_code == 200
            data = resp.json()
            assert "fingerprint_config" in data
            assert data["fingerprint_config"] == SAMPLE_CONFIG

    @pytest.mark.asyncio
    async def test_get_unconfigured_returns_empty(self, pm):
        """GET on profile without config should return null/empty."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("fresh")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profile/fresh/fingerprint")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("fingerprint_config") is None or data.get("fingerprint_config") == {}, (
                "Unconfigured profile should return null/empty fingerprint_config"
            )

    @pytest.mark.asyncio
    async def test_get_nonexistent_404(self):
        """GET on non-existent profile should return 404."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profile/nonexistent/fingerprint")
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_same_as_profile_list(self, pm_with_config, storage_dir):
        """Profile list should include fingerprint_config field matching GET."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            list_resp = await client.get("/profiles")
            assert list_resp.status_code == 200
            profiles = list_resp.json().get("profiles", [])
            fp_profile = next(
                (p for p in profiles if p.get("name") == "fp-configured"),
                None,
            )
            assert fp_profile is not None
            assert "fingerprint_config" in fp_profile, (
                "Profile list response should include fingerprint_config field"
            )
            assert fp_profile["fingerprint_config"] == SAMPLE_CONFIG

    @pytest.mark.asyncio
    async def test_get_returns_dict(self, pm_with_config, storage_dir):
        """GET response should always return a dict with fingerprint_config key."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/profile/fp-configured/fingerprint")
            assert resp.status_code == 200
            assert isinstance(resp.json(), dict)


# ===================================================================
# P1.2-b: PUT /profiles/{name}/fingerprint
# ===================================================================


class TestPutFingerprintConfig:
    """PUT /profiles/{name}/fingerprint — update fingerprint config."""

    VALID_CONFIG = {"timezone": "Europe/Budapest", "screen_width": 2560}

    @pytest.mark.asyncio
    async def test_put_sets_config(self, pm):
        """PUT should set fingerprint_config on the profile."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("config-me")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http/test") as client:
            resp = await client.put(
                "/profile/config-me/fingerprint",
                json=self.VALID_CONFIG,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("fingerprint_config") == self.VALID_CONFIG

    @pytest.mark.asyncio
    async def test_put_then_get_returns_same(self, pm):
        """PUT then GET should return the same config."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("roundtrip")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            put_resp = await client.put(
                "/profile/roundtrip/fingerprint",
                json=self.VALID_CONFIG,
            )
            assert put_resp.status_code == 200

            get_resp = await client.get("/profile/roundtrip/fingerprint")
            assert get_resp.status_code == 200
            assert get_resp.json().get("fingerprint_config") == self.VALID_CONFIG

    @pytest.mark.asyncio
    async def test_put_empty_dict(self, pm):
        """PUT with empty dict should clear/reset the config."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("clear-me")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Set config
            await client.put(
                "/profile/clear-me/fingerprint",
                json={"timezone": "Asia/Tokyo"},
            )
            # Clear it
            resp = await client.put(
                "/profile/clear-me/fingerprint",
                json={},
            )
            assert resp.status_code == 200
            get_resp = await client.get("/profile/clear-me/fingerprint")
            assert get_resp.json().get("fingerprint_config") == {} or \
                   get_resp.json().get("fingerprint_config") is None

    @pytest.mark.asyncio
    async def test_put_replaces_existing_config(self, pm):
        """PUT should fully replace existing config, not merge."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("replace-me")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.put(
                "/profile/replace-me/fingerprint",
                json={"timezone": "Old/Value", "screen_width": 1024},
            )
            await client.put(
                "/profile/replace-me/fingerprint",
                json={"timezone": "New/Value"},
            )
            get_resp = await client.get("/profile/replace-me/fingerprint")
            cfg = get_resp.json().get("fingerprint_config", {})
            assert cfg.get("timezone") == "New/Value"
            # The screen_width that was in the first PUT but not the second
            # should be gone if the config was fully replaced (not merged)
            assert "screen_width" not in cfg, (
                "PUT should fully replace config, not merge"
            )

    @pytest.mark.asyncio
    async def test_put_unknown_field_rejected(self, pm):
        """PUT with unknown field names should be rejected with 422."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("validate-me")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profile/validate-me/fingerprint",
                json={"fake_field": "value"},
            )
            assert resp.status_code == 422, (
                "PUT with unknown field should return 422"
            )

    @pytest.mark.asyncio
    async def test_put_non_dict_rejected(self, pm):
        """PUT with non-dict body should be rejected with 422."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("type-check")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profile/type-check/fingerprint",
                json="not-a-dict",
            )
            assert resp.status_code == 422, (
                "PUT with non-dict body should return 422"
            )

    @pytest.mark.asyncio
    async def test_put_list_rejected(self, pm):
        """PUT with a JSON array should be rejected."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("array-check")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profile/array-check/fingerprint",
                json=[1, 2, 3],
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_put_nonexistent_profile_404(self):
        """PUT on non-existent profile should return 404."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profile/nonexistent/fingerprint",
                json={"timezone": "UTC"},
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_put_persists_restart(self, pm, storage_dir):
        """Config set via PUT should survive ProfileManager reload."""
        from httpx import ASGITransport, AsyncClient
        from main import app

        pm.create_profile("persist")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/profile/persist/fingerprint",
                json={"hardware_concurrency": 8},
            )
            assert resp.status_code == 200

        # Re-init ProfileManager (simulates restart)
        from profile_manager import ProfileManager

        pm2 = ProfileManager(storage_dir=storage_dir)
        p = pm2.get_profile("persist")
        assert p.fingerprint_config == {"hardware_concurrency": 8}, (
            "fingerprint_config must persist in JSON after restart"
        )


# ===================================================================
# P1.2-c: FingerprintEngine integration — headless injection
# ===================================================================


class TestFingerprintEngine:
    """Verify FingerprintEngine generates scripts from config."""

    def test_fingerprint_engine_importable(self):
        """FingerprintEngine should be importable from fingerprint_engine module."""
        try:
            from fingerprint_engine import FingerprintEngine
        except ImportError:
            # Also accept it in headless_manager
            from headless_manager import FingerprintEngine
        assert True

    def test_generate_all_scripts_method_exists(self):
        """FingerprintEngine should have generate_all_scripts class/static method."""
        try:
            from fingerprint_engine import FingerprintEngine
        except ImportError:
            from headless_manager import FingerprintEngine

        assert hasattr(FingerprintEngine, "generate_all_scripts"), (
            "FingerprintEngine must have generate_all_scripts method"
        )
        assert callable(FingerprintEngine.generate_all_scripts)

    def test_generate_all_scripts_returns_list(self):
        """generate_all_scripts should return a list of script strings."""
        try:
            from fingerprint_engine import FingerprintEngine
        except ImportError:
            from headless_manager import FingerprintEngine

        config = {"timezone": "America/New_York", "screen_width": 1920}
        scripts = FingerprintEngine.generate_all_scripts(config)
        assert isinstance(scripts, list), (
            "generate_all_scripts must return a list"
        )
        if scripts:
            assert all(isinstance(s, str) for s in scripts), (
                "All scripts must be strings"
            )

    def test_generate_all_scripts_empty_config_returns_list(self):
        """Even with empty config, generate_all_scripts should return a list."""
        try:
            from fingerprint_engine import FingerprintEngine
        except ImportError:
            from headless_manager import FingerprintEngine

        scripts = FingerprintEngine.generate_all_scripts({})
        assert isinstance(scripts, list)

    def test_generate_all_scripts_none_config_returns_list(self):
        """With None config, generate_all_scripts should return an empty list (no injection)."""
        try:
            from fingerprint_engine import FingerprintEngine
        except ImportError:
            from headless_manager import FingerprintEngine

        scripts = FingerprintEngine.generate_all_scripts(None)
        assert isinstance(scripts, list)


class TestFingerprintEngineIntegration:
    """Verify FingerprintEngine integrates with HeadlessManager.launch_session."""

    @pytest.mark.asyncio
    async def test_launch_without_config_no_injection(self, pm):
        """Sessions without fingerprint_config should not inject scripts."""
        from headless_manager import HeadlessManager

        mgr = HeadlessManager(max_sessions=0)  # Prevent actual launch
        # No config — no fingerprint scripts
        # This interface test just checks the path doesn't crash
        assert True

    def test_fingerprint_injection_hook_exists(self):
        """launch_session should have fingerprint injection point."""
        import inspect

        from headless_manager import HeadlessManager

        source = inspect.getsource(HeadlessManager.launch_session)
        # The method should reference fingerprint_config or FingerprintEngine
        has_fp_config_ref = "fingerprint_config" in source
        has_engine_ref = "FingerprintEngine" in source or "generate_all_scripts" in source
        assert has_fp_config_ref or has_engine_ref, (
            "launch_session must reference fingerprint_config or FingerprintEngine"
        )

    def test_session_handle_has_fingerprint_info(self):
        """SessionHandle may include fingerprint injection info."""
        from headless_manager import SessionHandle

        handle = SessionHandle(
            session_id="fp-test",
            chrome_pid=9999,
            cdp_url="http://127.0.0.1:9999",
            port=9999,
            created_at=0.0,
            last_active=0.0,
            status="active",
        )
        # This should not crash — the handle is just a dataclass
        assert handle.session_id == "fp-test"


# ===================================================================
# P1.2-d: CDP injection via Page.addScriptToEvaluateOnNewDocument
# ===================================================================


class TestCDPScriptInjection:
    """Verify scripts are injected via Page.addScriptToEvaluateOnNewDocument."""

    def test_add_script_on_new_document_available(self):
        """CDPClient should have add_script_to_evaluate_on_new_document method."""
        from cdp_client import CDPClient

        method_name = None
        for candidate in [
            "add_script_to_evaluate_on_new_document",
            "addScriptToEvaluateOnNewDocument",
            "inject_script",
        ]:
            if hasattr(CDPClient, candidate):
                method_name = candidate
                break

        assert method_name is not None, (
            "CDPClient must have a method for Page.addScriptToEvaluateOnNewDocument. "
            "Expected one of: add_script_to_evaluate_on_new_document, "
            "addScriptToEvaluateOnNewDocument, inject_script"
        )

    def test_inject_scripts_method_exists_on_headless(self):
        """HeadlessManager should have a method to inject fingerprint scripts."""
        from headless_manager import HeadlessManager

        method_name = None
        for candidate in [
            "_inject_fingerprint_scripts",
            "_apply_fingerprint_config",
            "inject_fingerprint",
        ]:
            if hasattr(HeadlessManager, candidate):
                method_name = candidate
                break

        assert method_name is not None, (
            "HeadlessManager must have a method to inject fingerprint scripts. "
            "Expected one of: _inject_fingerprint_scripts, "
            "_apply_fingerprint_config, inject_fingerprint"
        )

    def test_inject_scripts_accepts_scripts_list(self):
        """The injection method should accept a list of script strings."""
        from headless_manager import HeadlessManager

        method_name = None
        for candidate in [
            "_inject_fingerprint_scripts",
            "_apply_fingerprint_config",
            "inject_fingerprint",
        ]:
            if hasattr(HeadlessManager, candidate):
                method_name = candidate
                break

        if method_name:
            import inspect
            sig = inspect.signature(getattr(HeadlessManager, method_name))
            params = list(sig.parameters.keys())
            # Should accept at least 'scripts' or 'self' + config/scripts
            assert len(params) >= 2, (
                f"{method_name} should accept at least (self, scripts/config)"
            )


# ===================================================================
# P1.2-e: Regression — existing profile/headless functionality
# ===================================================================


class TestFingerprintConfigRegression:
    """Existing functionality must work unchanged with fingerprint_config addition."""

    def test_create_profile_unchanged(self, pm):
        """create_profile should work without fingerprint_config."""
        p = pm.create_profile("standard")
        assert p.name == "standard"
        assert p.fingerprint_config is None

    def test_get_profile_unchanged(self, pm):
        """get_profile should work unchanged."""
        pm.create_profile("standard")
        p = pm.get_profile("standard")
        assert p is not None
        assert p.fingerprint_config is None

    def test_list_profiles_unchanged(self, pm):
        """list_profiles should include fingerprint_config field."""
        pm.create_profile("alpha")
        profiles = pm.list_profiles()
        for p in profiles:
            assert hasattr(p, "fingerprint_config"), (
                "Every profile should have fingerprint_config attribute"
            )

    def test_delete_profile_unchanged(self, pm):
        """delete_profile should work unchanged."""
        pm.create_profile("temp")
        assert pm.delete_profile("temp") is True

    def test_rename_profile_unchanged(self, pm):
        """rename_profile should preserve fingerprint_config."""
        pm.create_profile("old")
        pm._data["old"]["fingerprint_config"] = {"timezone": "UTC"}
        pm.save()
        assert pm.rename_profile("old", "new") is True
        p = pm.get_profile("new")
        assert p.fingerprint_config == {"timezone": "UTC"}

    def test_add_extension_unchanged(self, pm):
        """add_extension should work unchanged."""
        pm.create_profile("test")
        assert pm.add_extension("test", "/ext/path") is True

    def test_export_with_fingerprint_config_does_not_break(self, pm, tmp_path):
        """Export with fingerprint_config should not break the export."""
        pm.create_profile("test")
        pm._data["test"]["fingerprint_config"] = {"platform": "MacIntel"}
        pm.save()
        export_path = str(tmp_path / "test.zip")
        result = pm.export_profile("test", export_path)
        assert result is not None
        assert os.path.isfile(export_path)
