"""Pre-development tests for BaselineManager (RED phase).

These tests define the expected interface BEFORE implementation.
All will fail with ImportError/AttributeError until the developer
writes src/baseline_manager.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------



# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

@pytest.fixture
def base_dir(tmp_path):
    """Return a temporary directory for baseline storage."""
    return str(tmp_path / ".browser-helper" / "baselines")


@pytest.fixture
def bm(base_dir):
    """Return a fresh BaselineManager isolated to a temp directory."""
    from baseline_manager import BaselineManager

    mgr = BaselineManager(base_dir=base_dir)
    yield mgr


@pytest.fixture
def sample_png(tmp_path):
    """Create a small valid PNG image for testing."""
    import struct
    import zlib

    # Minimal 1x1 red PNG
    width, height = 1, 1
    raw = b"\x00" + b"\xff\x00\x00\xff"  # RGBA: red
    compressed = zlib.compress(raw)
    # Build minimal PNG
    def make_chunk(chunk_type, data):
        chunk = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + chunk + crc

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += make_chunk(b"IHDR", ihdr)
    png += make_chunk(b"IDAT", compressed)
    png += make_chunk(b"IEND", b"")

    path = str(tmp_path / "sample.png")
    with open(path, "wb") as f:
        f.write(png)
    return path


# ===================================================================
# BaselineManager interface tests
# ===================================================================


class TestBaselineManagerInterface:
    """Verify BaselineManager class and methods exist."""

    def test_import(self):
        """BaselineManager should be importable from baseline_manager."""
        from baseline_manager import BaselineManager

        assert hasattr(BaselineManager, "__init__")
        assert hasattr(BaselineManager, "get_baseline_path")
        assert hasattr(BaselineManager, "save_baseline")
        assert hasattr(BaselineManager, "get_baseline")
        assert hasattr(BaselineManager, "list_baselines")
        assert hasattr(BaselineManager, "delete_baseline")
        assert hasattr(BaselineManager, "get_app_data_dir")

    def test_init_signature(self):
        """__init__ should accept base_dir parameter."""
        import inspect

        from baseline_manager import BaselineManager

        sig = inspect.signature(BaselineManager.__init__)
        params = list(sig.parameters.keys())
        assert "base_dir" in params
        # base_dir should have a default of None
        param = sig.parameters["base_dir"]
        assert param.default is None

    def test_get_baseline_path_signature(self):
        """get_baseline_path() should have correct parameters."""
        import inspect

        from baseline_manager import BaselineManager

        sig = inspect.signature(BaselineManager.get_baseline_path)
        params = list(sig.parameters.keys())
        assert "url" in params
        assert "profile" in params
        assert "viewport" in params

    def test_save_baseline_signature(self):
        """save_baseline() should have correct parameters."""
        import inspect

        from baseline_manager import BaselineManager

        sig = inspect.signature(BaselineManager.save_baseline)
        params = list(sig.parameters.keys())
        assert "url" in params
        assert "image_data" in params
        assert "profile" in params
        assert "viewport" in params
        assert "format" in params

    def test_get_baseline_signature(self):
        """get_baseline() should have correct parameters."""
        import inspect

        from baseline_manager import BaselineManager

        sig = inspect.signature(BaselineManager.get_baseline)
        params = list(sig.parameters.keys())
        assert "url" in params
        assert "profile" in params
        assert "viewport" in params
        # Should return str | None
        assert sig.return_annotation in (str | None, "str | None")

    def test_list_baselines_signature(self):
        """list_baselines() should accept optional profile filter."""
        import inspect

        from baseline_manager import BaselineManager

        sig = inspect.signature(BaselineManager.list_baselines)
        params = list(sig.parameters.keys())
        assert "profile" in params
        # Should return list[dict]
        assert "list" in str(sig.return_annotation).lower()

    def test_delete_baseline_signature(self):
        """delete_baseline() should accept url and profile."""
        import inspect

        from baseline_manager import BaselineManager

        sig = inspect.signature(BaselineManager.delete_baseline)
        params = list(sig.parameters.keys())
        assert "url" in params
        assert "profile" in params
        # Should return bool
        return_type = sig.return_annotation
        assert return_type in (bool, "bool")


# ===================================================================
# BaselineManager behavioral tests
# ===================================================================


class TestGetBaselinePath:
    """Test get_baseline_path() method."""

    def test_creates_directories(self, bm):
        """get_baseline_path() should create required directories."""
        path = bm.get_baseline_path(url="https://example.com")
        dir_path = Path(path).parent
        assert dir_path.exists(), "Directory should be created"

    def test_returns_string(self, bm):
        """get_baseline_path() should return a string path."""
        path = bm.get_baseline_path(url="https://example.com")
        assert isinstance(path, str)
        assert path.endswith(".png")

    def test_url_hashing_same_url(self, bm):
        """Same URL should produce the same filename (deterministic hash)."""
        p1 = bm.get_baseline_path(url="https://example.com")
        p2 = bm.get_baseline_path(url="https://example.com")
        assert p1 == p2

    def test_different_urls_different_paths(self, bm):
        """Different URLs should produce different paths."""
        p1 = bm.get_baseline_path(url="https://example.com")
        p2 = bm.get_baseline_path(url="https://other.com")
        assert p1 != p2

    def test_profile_scoped_paths(self, bm):
        """Different profiles should produce different paths even for same URL."""
        p1 = bm.get_baseline_path(url="https://example.com", profile="work")
        p2 = bm.get_baseline_path(url="https://example.com", profile="personal")
        assert p1 != p2

    def test_viewport_scoped_paths(self, bm):
        """Different viewport dimensions should produce different paths."""
        vp1 = {"width": 1280, "height": 720}
        vp2 = {"width": 1920, "height": 1080}
        p1 = bm.get_baseline_path(url="https://example.com", viewport=vp1)
        p2 = bm.get_baseline_path(url="https://example.com", viewport=vp2)
        assert p1 != p2

    def test_path_contains_hash(self, bm):
        """Filename should be a hash of url+profile+viewport."""
        path = bm.get_baseline_path(url="https://example.com")
        filename = Path(path).name
        name_without_ext = filename.replace(".png", "")
        # Should be a hex string (hash)
        assert all(c in "0123456789abcdef" for c in name_without_ext)
        assert len(name_without_ext) >= 8


class TestSaveBaseline:
    """Test save_baseline() method."""

    def test_saves_file_and_returns_path(self, bm, sample_png):
        """save_baseline() should create a file and return its path."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        path = bm.save_baseline(url="https://example.com", image_data=image_data)
        assert isinstance(path, str)
        saved = Path(path)
        assert saved.exists()
        assert saved.stat().st_size > 0

    def test_saves_png_format(self, bm, sample_png):
        """save_baseline() should save as PNG by default."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        path = bm.save_baseline(url="https://example.com", image_data=image_data)
        assert path.endswith(".png")
        with open(path, "rb") as f:
            header = f.read(8)
        assert header == b"\x89PNG\r\n\x1a\n"

    def test_profile_scoped_save(self, bm, sample_png):
        """save_baseline() with profile should store in profile-specific path."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        path = bm.save_baseline(url="https://example.com", image_data=image_data, profile="work")
        assert "work" in path or Path(path).parent.parent.name != "baselines"

    def test_overwrite_existing(self, bm, sample_png):
        """save_baseline() should overwrite existing baseline for same URL."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        p1 = bm.save_baseline(url="https://example.com", image_data=image_data)
        # Save again with different data
        import struct
        import zlib
        raw = b"\x00" + b"\x00\x00\xff\xff"  # Blue pixel instead of red
        compressed = zlib.compress(raw)
        def make_chunk(chunk_type, data):
            chunk = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + chunk + crc
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        png2 = b"\x89PNG\r\n\x1a\n"
        png2 += make_chunk(b"IHDR", ihdr)
        png2 += make_chunk(b"IDAT", compressed)
        png2 += make_chunk(b"IEND", b"")
        p2 = bm.save_baseline(url="https://example.com", image_data=png2)
        assert p1 == p2  # Same URL → same path
        assert Path(p2).exists()


class TestGetBaseline:
    """Test get_baseline() method."""

    def test_returns_path_for_existing(self, bm, sample_png):
        """get_baseline() should return the file path for an existing baseline."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        saved = bm.save_baseline(url="https://example.com", image_data=image_data)
        retrieved = bm.get_baseline(url="https://example.com")
        assert retrieved == saved

    def test_returns_none_for_missing(self, bm):
        """get_baseline() should return None when no baseline exists."""
        path = bm.get_baseline(url="https://nonexistent.com")
        assert path is None

    def test_profile_scoped_retrieval(self, bm, sample_png):
        """get_baseline() should respect profile scoping."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://example.com", image_data=image_data, profile="work")
        # Should find with matching profile
        found = bm.get_baseline(url="https://example.com", profile="work")
        assert found is not None
        # Should NOT find without profile (different scope)
        not_found = bm.get_baseline(url="https://example.com")
        assert not_found is None


class TestListBaselines:
    """Test list_baselines() method."""

    def test_empty_list_initially(self, bm):
        """list_baselines() should return an empty list when no baselines exist."""
        baselines = bm.list_baselines()
        assert isinstance(baselines, list)
        assert len(baselines) == 0

    def test_returns_baselines_after_save(self, bm, sample_png):
        """list_baselines() should return baselines after saving."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://example.com", image_data=image_data)
        baselines = bm.list_baselines()
        assert len(baselines) >= 1
        entry = baselines[0]
        assert "url" in entry
        assert "path" in entry
        assert "size" in entry
        assert "timestamp" in entry

    def test_profiles_filter(self, bm, sample_png):
        """list_baselines(profile=...) should filter by profile."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://work.com", image_data=image_data, profile="work")
        bm.save_baseline(url="https://personal.com", image_data=image_data, profile="personal")
        work_baselines = bm.list_baselines(profile="work")
        assert len(work_baselines) == 1
        assert "work.com" in work_baselines[0]["url"]
        all_baselines = bm.list_baselines()
        assert len(all_baselines) == 2

    def test_entry_metadata_shape(self, bm, sample_png):
        """Each baseline entry should contain url, path, size, and timestamp."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://example.com", image_data=image_data)
        entries = bm.list_baselines()
        entry = entries[0]
        assert isinstance(entry["url"], str)
        assert isinstance(entry["path"], str)
        assert isinstance(entry["size"], int)
        assert isinstance(entry["timestamp"], str)  # ISO format


class TestDeleteBaseline:
    """Test delete_baseline() method."""

    def test_deletes_existing(self, bm, sample_png):
        """delete_baseline() should remove an existing baseline and return True."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://example.com", image_data=image_data)
        result = bm.delete_baseline(url="https://example.com")
        assert result is True
        assert bm.get_baseline(url="https://example.com") is None

    def test_delete_missing_returns_false(self, bm):
        """delete_baseline() should return False for a non-existent baseline."""
        result = bm.delete_baseline(url="https://nonexistent.com")
        assert result is False

    def test_delete_profile_scoped(self, bm, sample_png):
        """delete_baseline() should respect profile scoping."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://example.com", image_data=image_data, profile="work")
        # Deleting without profile should NOT delete it
        result = bm.delete_baseline(url="https://example.com")
        assert result is False
        # Deleting with correct profile should work
        result = bm.delete_baseline(url="https://example.com", profile="work")
        assert result is True


class TestAppDataDir:
    """Test get_app_data_dir() method."""

    def test_returns_string(self, bm):
        """get_app_data_dir() should return a string path."""
        path = bm.get_app_data_dir()
        assert isinstance(path, str)
        assert len(path) > 0

    def test_default_uses_settings(self):
        """Default base_dir should use settings.json location."""
        from baseline_manager import BaselineManager

        bm = BaselineManager()
        path = bm.get_app_data_dir()
        assert isinstance(path, str)


# ===================================================================
# Edge case tests — URLs with special characters
# ===================================================================


class TestEdgeCaseURLSpecialChars:
    """Test BaselineManager with URLs containing special characters."""

    def test_unicode_url(self, bm):
        """URLs with unicode characters should be handled correctly."""
        path = bm.get_baseline_path(url="https://éxämplê.com/page")
        assert isinstance(path, str)
        assert path.endswith(".png")
        # The directory should have been created
        dir_path = Path(path).parent
        assert dir_path.exists()

    def test_url_with_query_params(self, bm):
        """URLs with query parameters should produce different paths than without."""
        p1 = bm.get_baseline_path(url="https://example.com/page")
        p2 = bm.get_baseline_path(url="https://example.com/page?foo=bar&baz=123")
        assert p1 != p2

    def test_url_with_fragment(self, bm):
        """URLs with fragments should hash differently from same URL without fragment."""
        p1 = bm.get_baseline_path(url="https://example.com/page")
        p2 = bm.get_baseline_path(url="https://example.com/page#section")
        assert p1 != p2

    def test_url_with_special_chars_roundtrip(self, bm, sample_png):
        """Saving and retrieving a baseline with special chars in URL."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        url = "https://example.com/path?q=üñîçödé&lang=hu#frag"
        saved = bm.save_baseline(url=url, image_data=image_data)
        assert saved is not None
        retrieved = bm.get_baseline(url=url)
        assert retrieved == saved

    def test_url_with_unicode_listed(self, bm, sample_png):
        """Baselines with unicode URLs should appear in listing."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://例子.测试/path", image_data=image_data)
        baselines = bm.list_baselines()
        assert any("例子" in bl["url"] or "测试" in bl["url"] for bl in baselines)


# ===================================================================
# Edge case tests — multiple viewports for same URL
# ===================================================================


class TestMultipleViewports:
    """Test that the same URL with different viewports creates distinct baselines."""

    @pytest.fixture
    def mobile_viewport(self):
        return {"width": 375, "height": 667}

    @pytest.fixture
    def tablet_viewport(self):
        return {"width": 768, "height": 1024}

    @pytest.fixture
    def desktop_viewport(self):
        return {"width": 1920, "height": 1080}

    def test_same_url_different_viewports_distinct(self, bm, sample_png, mobile_viewport, desktop_viewport):
        """Same URL with different viewports should produce separate baselines."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        p1 = bm.save_baseline(url="https://example.com", image_data=image_data, viewport=mobile_viewport)
        p2 = bm.save_baseline(url="https://example.com", image_data=image_data, viewport=desktop_viewport)
        assert p1 != p2

    def test_multiple_viewports_listing_count(self, bm, sample_png, mobile_viewport, tablet_viewport, desktop_viewport):
        """Each viewport baseline should appear as a separate entry in listing."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://example.com", image_data=image_data, viewport=mobile_viewport)
        bm.save_baseline(url="https://example.com", image_data=image_data, viewport=tablet_viewport)
        bm.save_baseline(url="https://example.com", image_data=image_data, viewport=desktop_viewport)
        baselines = bm.list_baselines()
        # Should have 3 entries for the same URL with different viewports
        same_url = [bl for bl in baselines if bl["url"] == "https://example.com"]
        assert len(same_url) == 3

    def test_retrieve_with_correct_viewport(self, bm, sample_png, mobile_viewport, desktop_viewport):
        """Retrieving with the correct viewport should find the matching baseline."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        saved = bm.save_baseline(url="https://example.com", image_data=image_data, viewport=mobile_viewport)
        # Also save for desktop
        bm.save_baseline(url="https://example.com", image_data=image_data, viewport=desktop_viewport)
        # Retrieving with mobile viewport should match
        found = bm.get_baseline(url="https://example.com", viewport=mobile_viewport)
        assert found == saved

    def test_retrieve_without_viewport_when_multiple_exist(self, bm, sample_png, mobile_viewport, desktop_viewport):
        """When multiple viewports exist, retrieving without viewport finds the no-viewport one."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        saved_no_vp = bm.save_baseline(url="https://example.com", image_data=image_data)
        bm.save_baseline(url="https://example.com", image_data=image_data, viewport=mobile_viewport)
        bm.save_baseline(url="https://example.com", image_data=image_data, viewport=desktop_viewport)
        # Retrieving without viewport should get the one saved without viewport
        found = bm.get_baseline(url="https://example.com")
        assert found == saved_no_vp


# ===================================================================
# Integration tests — profile isolation
# ===================================================================


class TestProfileIsolation:
    """Test baseline isolation across profiles."""

    def test_baseline_not_visible_to_other_profile(self, bm, sample_png):
        """A baseline saved under one profile should not be visible from another."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://example.com", image_data=image_data, profile="work")
        # Should not be visible with different profile
        assert bm.get_baseline(url="https://example.com", profile="personal") is None
        # Should not be visible without profile
        assert bm.get_baseline(url="https://example.com") is None

    def test_no_cross_profile_leakage_in_listing(self, bm, sample_png):
        """Listing with a specific profile should not show other profiles' baselines."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://work.com", image_data=image_data, profile="work")
        bm.save_baseline(url="https://personal.com", image_data=image_data, profile="personal")
        work_list = bm.list_baselines(profile="work")
        personal_list = bm.list_baselines(profile="personal")
        assert len(work_list) == 1
        assert len(personal_list) == 1
        assert "work.com" in work_list[0]["url"]
        assert "personal.com" in personal_list[0]["url"]

    def test_delete_respects_profile_isolation(self, bm, sample_png):
        """Deleting a baseline for one profile should not affect another profile."""
        with open(sample_png, "rb") as f:
            image_data = f.read()
        bm.save_baseline(url="https://example.com", image_data=image_data, profile="work")
        bm.save_baseline(url="https://example.com", image_data=image_data, profile="personal")
        # Delete work baseline
        result = bm.delete_baseline(url="https://example.com", profile="work")
        assert result is True
        # Personal should still exist
        assert bm.get_baseline(url="https://example.com", profile="personal") is not None
        # Work should be gone
        assert bm.get_baseline(url="https://example.com", profile="work") is None


# ===================================================================
# Integration tests — concurrent baseline saves
# ===================================================================


class TestConcurrentSaves:
    """Test concurrent baseline saves for async safety."""

    def test_concurrent_saves_same_url(self, bm, sample_png):
        """Multiple concurrent saves for same URL should not cause errors."""
        import concurrent.futures

        with open(sample_png, "rb") as f:
            image_data = f.read()

        urls = [f"https://example.com/page{i}" for i in range(10)]

        def save_one(url):
            return bm.save_baseline(url=url, image_data=image_data)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(save_one, urls))

        assert all(isinstance(p, str) for p in results)
        assert len(results) == 10
        # All should be listed
        baselines = bm.list_baselines()
        assert len(baselines) == 10

    def test_concurrent_saves_same_url_overwrite(self, bm, sample_png):
        """Concurrent overwrites of the same baseline should not crash."""
        import concurrent.futures

        with open(sample_png, "rb") as f:
            image_data = f.read()

        def save_same(_):
            return bm.save_baseline(url="https://example.com", image_data=image_data)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(save_same, range(10)))

        assert all(isinstance(p, str) for p in results)
        # All should return the same path
        assert len(set(results)) == 1

    def test_concurrent_saves_different_profiles(self, bm, sample_png):
        """Concurrent saves to different profiles should all succeed."""
        import concurrent.futures

        with open(sample_png, "rb") as f:
            image_data = f.read()

        profiles = [f"profile_{i}" for i in range(10)]

        def save_with_profile(profile):
            return bm.save_baseline(
                url="https://example.com",
                image_data=image_data,
                profile=profile,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(save_with_profile, profiles))

        assert all(isinstance(p, str) for p in results)
        assert len(results) == 10
        # Each profile should have 1 baseline
        for profile in profiles:
            bl = bm.list_baselines(profile=profile)
            assert len(bl) == 1


# ===================================================================
# Cross-feature integration — ProfileManager data_dir
# ===================================================================


class TestCrossFeatureIntegration:
    """Test baseline scoping relative to user profiles."""

    def test_baseline_scoped_to_profile_data_dir(self, tmp_path):
        """Baseline should be storable relative to a profile-managed data dir."""
        from baseline_manager import BaselineManager

        profile_data_dir = str(tmp_path / "profiles" / "work" / "data")
        bm = BaselineManager(base_dir=str(Path(profile_data_dir) / "baselines"))
        path = bm.get_baseline_path(url="https://example.com")
        assert "profiles" in path
        assert "work" in path
        assert path.startswith(profile_data_dir)

    def test_baseline_stored_relative_to_profile_dir(self, tmp_path):
        """Baseline files should be stored under the profile data directory."""
        from baseline_manager import BaselineManager

        profile_data_dir = str(tmp_path / "profiles" / "personal" / "data")
        bm = BaselineManager(base_dir=str(Path(profile_data_dir) / "baselines"))
        with open(str(tmp_path / "test.png"), "wb") as f:
            f.write(b"dummy png data")
        from PIL import Image
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        img_path = str(tmp_path / "valid.png")
        img.save(img_path)
        with open(img_path, "rb") as f:
            image_data = f.read()
        saved = bm.save_baseline(url="https://example.com", image_data=image_data)
        assert saved.startswith(profile_data_dir)
        assert Path(saved).exists()

    def test_no_cross_profile_leakage_with_data_dir(self, tmp_path):
        """Baselines stored under different profile dirs should not overlap."""
        from baseline_manager import BaselineManager

        # Two profiles with separate base dirs
        bm_a = BaselineManager(base_dir=str(tmp_path / "profiles" / "a" / "baselines"))
        bm_b = BaselineManager(base_dir=str(tmp_path / "profiles" / "b" / "baselines"))

        from PIL import Image
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        img_path = str(tmp_path / "valid.png")
        img.save(img_path)
        with open(img_path, "rb") as f:
            image_data = f.read()

        bm_a.save_baseline(url="https://example.com", image_data=image_data)
        # Profile B should have no baselines
        b_list = bm_b.list_baselines()
        assert len(b_list) == 0
        # Profile B get_baseline should return None
        assert bm_b.get_baseline(url="https://example.com") is None
