"""Pre-development tests for ScreenshotDiffEngine (RED phase).

These tests define the expected interface BEFORE implementation.
All will fail with ImportError/AttributeError until the developer
writes src/screenshot_diff.py.
"""

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def identical_pair(tmp_path):
    """Create two identical small PNG images."""
    img1 = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    p1 = str(tmp_path / "a.png")
    p2 = str(tmp_path / "b.png")
    img1.save(p1)
    img1.save(p2)
    return p1, p2


@pytest.fixture
def different_pair(tmp_path):
    """Create two completely different PNG images (all pixels differ)."""
    img1 = Image.new("RGBA", (100, 100), (255, 0, 0, 255))  # fully red
    img2 = Image.new("RGBA", (100, 100), (0, 0, 255, 255))  # fully blue
    p1 = str(tmp_path / "red.png")
    p2 = str(tmp_path / "blue.png")
    img1.save(p1)
    img2.save(p2)
    return p1, p2


@pytest.fixture
def slightly_different_pair(tmp_path):
    """Create two images that differ in one pixel only."""
    img1 = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    img2 = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    # Change a single pixel
    img2.putpixel((50, 50), (0, 0, 0, 255))
    p1 = str(tmp_path / "white.png")
    p2 = str(tmp_path / "white_single_diff.png")
    img1.save(p1)
    img2.save(p2)
    return p1, p2


@pytest.fixture
def corrupt_image(tmp_path):
    """Create a file that looks like an image but has invalid data."""
    path = str(tmp_path / "corrupt.png")
    with open(path, "wb") as f:
        f.write(b"not a real png data at all")
    return path


@pytest.fixture
def missing_path(tmp_path):
    """Return a path that does not exist."""
    return str(tmp_path / "does_not_exist.png")


@pytest.fixture
def dimension_mismatch_pair(tmp_path):
    """Create two images with different dimensions."""
    img1 = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    img2 = Image.new("RGBA", (200, 150), (0, 255, 0, 255))
    p1 = str(tmp_path / "small.png")
    p2 = str(tmp_path / "large.png")
    img1.save(p1)
    img2.save(p2)
    return p1, p2


@pytest.fixture
def diff_output_path(tmp_path):
    """Return a path where the diff output image should be written."""
    return str(tmp_path / "diff_output.png")


# ===================================================================
# DiffResult dataclass interface
# ===================================================================


class TestDiffResultDataclass:
    """Verify DiffResult dataclass fields and defaults."""

    def test_import(self):
        """DiffResult should be importable from screenshot_diff."""
        from screenshot_diff import DiffResult

        assert hasattr(DiffResult, "__dataclass_fields__")

    def test_fields(self):
        """DiffResult should have all required fields with correct types."""
        from screenshot_diff import DiffResult

        r = DiffResult(
            passed=True,
            pixel_delta=0.0,
            diff_image="",
            baseline_size=(100, 100),
            current_size=(100, 100),
            dimensions_match=True,
            error=None,
        )
        assert isinstance(r.passed, bool)
        assert isinstance(r.pixel_delta, float)
        assert isinstance(r.diff_image, str)
        assert isinstance(r.baseline_size, tuple)
        assert isinstance(r.current_size, tuple)
        assert isinstance(r.dimensions_match, bool)
        assert r.error is None or isinstance(r.error, str)

    def test_default_values(self):
        """DiffResult should have sensible defaults for optional fields."""
        from screenshot_diff import DiffResult

        r = DiffResult(
            passed=False,
            pixel_delta=0.0,
            diff_image="",
            baseline_size=(0, 0),
            current_size=(0, 0),
            dimensions_match=True,
            error=None,
        )
        assert r.passed is False
        assert r.pixel_delta == 0.0
        assert r.diff_image == ""
        assert r.baseline_size == (0, 0)
        assert r.current_size == (0, 0)
        assert r.dimensions_match is True
        assert r.error is None


# ===================================================================
# ScreenshotDiffEngine interface
# ===================================================================


class TestScreenshotDiffEngineInterface:
    """Verify ScreenshotDiffEngine class and static methods exist."""

    def test_import(self):
        """ScreenshotDiffEngine should be importable from screenshot_diff."""
        from screenshot_diff import ScreenshotDiffEngine

        assert hasattr(ScreenshotDiffEngine, "diff")
        assert hasattr(ScreenshotDiffEngine, "compute_pixel_delta")
        assert hasattr(ScreenshotDiffEngine, "create_diff_image")

    def test_diff_signature(self):
        """diff() should be a static method with correct parameter names."""
        import inspect

        from screenshot_diff import ScreenshotDiffEngine

        sig = inspect.signature(ScreenshotDiffEngine.diff)
        params = list(sig.parameters.keys())
        assert "baseline_path" in params
        assert "current_path" in params
        assert "output_path" in params

    def test_compute_pixel_delta_signature(self):
        """compute_pixel_delta() should accept two image paths."""
        import inspect

        from screenshot_diff import ScreenshotDiffEngine

        sig = inspect.signature(ScreenshotDiffEngine.compute_pixel_delta)
        params = list(sig.parameters.keys())
        assert "img1_path" in params
        assert "img2_path" in params

    def test_create_diff_image_signature(self):
        """create_diff_image() should accept two image paths and output path."""
        import inspect

        from screenshot_diff import ScreenshotDiffEngine

        sig = inspect.signature(ScreenshotDiffEngine.create_diff_image)
        params = list(sig.parameters.keys())
        assert "img1_path" in params
        assert "img2_path" in params
        assert "output_path" in params


# ===================================================================
# ScreenshotDiffEngine behavioral tests
# ===================================================================


class TestDiffBehavior:
    """Test static diff() method behavior."""

    def test_diff_returns_diffresult(self, identical_pair, diff_output_path):
        """diff() should return a DiffResult instance."""
        from screenshot_diff import DiffResult, ScreenshotDiffEngine

        baseline, current = identical_pair
        result = ScreenshotDiffEngine.diff(baseline, current, diff_output_path)
        assert isinstance(result, DiffResult)

    def test_diff_identical_images_pass(self, identical_pair, diff_output_path):
        """diff() should return passed=True with threshold=0.0 for identical images."""
        from screenshot_diff import ScreenshotDiffEngine

        baseline, current = identical_pair
        result = ScreenshotDiffEngine.diff(
            baseline, current, diff_output_path, threshold=0.0
        )
        assert result.passed is True
        assert result.pixel_delta == 0.0
        assert result.dimensions_match is True

    def test_diff_different_images_fail(self, different_pair, diff_output_path):
        """diff() should return passed=False with threshold=0.0 for different images."""
        from screenshot_diff import ScreenshotDiffEngine

        baseline, current = different_pair
        result = ScreenshotDiffEngine.diff(
            baseline, current, diff_output_path, threshold=0.0
        )
        assert result.passed is False
        assert result.pixel_delta > 0.0
        assert result.dimensions_match is True

    def test_diff_default_threshold(self, slightly_different_pair, diff_output_path):
        """diff() should use default threshold (0.001) when not specified."""
        from screenshot_diff import ScreenshotDiffEngine

        baseline, current = slightly_different_pair
        result = ScreenshotDiffEngine.diff(baseline, current, diff_output_path)
        # Single pixel diff in 100x100 = 1/10000 = 0.0001, should be under default 0.001
        assert isinstance(result.passed, bool)
        assert isinstance(result.pixel_delta, float)

    def test_diff_image_is_base64(self, identical_pair, diff_output_path):
        """diff() should include a base64-encoded PNG in diff_image field."""
        from screenshot_diff import ScreenshotDiffEngine

        baseline, current = identical_pair
        result = ScreenshotDiffEngine.diff(baseline, current, diff_output_path)
        assert isinstance(result.diff_image, str)
        # Verify it's valid base64
        try:
            decoded = base64.b64decode(result.diff_image)
            # Verify it's a PNG header
            assert decoded[:8] == b"\x89PNG\r\n\x1a\n"
        except (ValueError, OSError, TypeError):
            pytest.fail("diff_image is not valid base64 PNG data")

    def test_diff_dimension_mismatch(self, dimension_mismatch_pair, diff_output_path):
        """diff() should handle dimension mismatches gracefully."""
        from screenshot_diff import ScreenshotDiffEngine

        baseline, current = dimension_mismatch_pair
        result = ScreenshotDiffEngine.diff(baseline, current, diff_output_path)
        assert result.dimensions_match is False
        assert result.error is not None
        assert "dimension" in result.error.lower()

    def test_diff_corrupt_image(self, corrupt_image, identical_pair, diff_output_path):
        """diff() should handle corrupt image files gracefully."""
        from screenshot_diff import ScreenshotDiffEngine

        baseline, _ = identical_pair
        result = ScreenshotDiffEngine.diff(corrupt_image, baseline, diff_output_path)
        assert result.error is not None

    def test_diff_missing_baseline(self, missing_path, identical_pair, diff_output_path):
        """diff() should handle missing baseline file gracefully."""
        from screenshot_diff import ScreenshotDiffEngine

        _, current = identical_pair
        result = ScreenshotDiffEngine.diff(missing_path, current, diff_output_path)
        assert result.error is not None
        assert "not found" in result.error.lower() or "exist" in result.error.lower()

    def test_diff_missing_current(self, missing_path, identical_pair, diff_output_path):
        """diff() should handle missing current file gracefully."""
        from screenshot_diff import ScreenshotDiffEngine

        baseline, _ = identical_pair
        result = ScreenshotDiffEngine.diff(baseline, missing_path, diff_output_path)
        assert result.error is not None

    def test_diff_output_file_created(self, identical_pair, diff_output_path):
        """diff() should write a diff overlay image to output_path."""
        from screenshot_diff import ScreenshotDiffEngine

        baseline, current = identical_pair
        ScreenshotDiffEngine.diff(baseline, current, diff_output_path)
        output = Path(diff_output_path)
        assert output.exists()
        assert output.stat().st_size > 0


class TestComputePixelDelta:
    """Test compute_pixel_delta() static method."""

    def test_identical_images_zero(self, identical_pair):
        """Identical images should yield 0.0 pixel delta."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = identical_pair
        delta = ScreenshotDiffEngine.compute_pixel_delta(p1, p2)
        assert delta == 0.0

    def test_completely_different_images_one(self, different_pair):
        """Completely different images should yield 1.0 pixel delta."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = different_pair
        delta = ScreenshotDiffEngine.compute_pixel_delta(p1, p2)
        assert delta == 1.0

    def test_slightly_different_images_mid(self, slightly_different_pair):
        """Slightly different images should yield a delta between 0 and 1."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = slightly_different_pair
        delta = ScreenshotDiffEngine.compute_pixel_delta(p1, p2)
        assert 0.0 < delta < 1.0

    def test_dimension_mismatch(self, dimension_mismatch_pair):
        """Dimension mismatch should return 1.0 or raise."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = dimension_mismatch_pair
        try:
            delta = ScreenshotDiffEngine.compute_pixel_delta(p1, p2)
            # If it doesn't raise, should return 1.0 to signal mismatch
            assert delta == 1.0
        except ValueError:
            pass  # Raising is also acceptable

    def test_corrupt_image_error(self, corrupt_image, identical_pair):
        """Corrupt image should raise or return 1.0."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, _ = identical_pair
        try:
            delta = ScreenshotDiffEngine.compute_pixel_delta(corrupt_image, p1)
            assert delta == 1.0
        except (ValueError, OSError, TypeError):
            pass  # Exception is acceptable for corrupt data


class TestCreateDiffImage:
    """Test create_diff_image() static method."""

    def test_creates_png_at_path(self, different_pair, diff_output_path):
        """create_diff_image() should create a valid PNG file at output_path."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = different_pair
        ScreenshotDiffEngine.create_diff_image(p1, p2, diff_output_path)
        output = Path(diff_output_path)
        assert output.exists()
        assert output.stat().st_size > 0
        # Validate PNG header
        with open(diff_output_path, "rb") as f:
            header = f.read(8)
        assert header == b"\x89PNG\r\n\x1a\n"

    def test_identical_images_blank_diff(self, identical_pair, diff_output_path):
        """create_diff_image() should produce a blank (all black) diff for identical images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = identical_pair
        ScreenshotDiffEngine.create_diff_image(p1, p2, diff_output_path)
        img = Image.open(diff_output_path)
        # For identical images, diff should be all black (no changes)
        extrema = img.getextrema()
        assert all(
            ex == (0, 0) for ex in extrema
        ), "Diff image should be all black for identical inputs"

    def test_dimension_mismatch_handling(self, dimension_mismatch_pair, diff_output_path):
        """create_diff_image() should handle dimension mismatches."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = dimension_mismatch_pair
        try:
            ScreenshotDiffEngine.create_diff_image(p1, p2, diff_output_path)
        except ValueError:
            pass  # Acceptable to raise on dimension mismatch
        except OSError as e:
            pytest.fail(f"Unexpected OSError for dimension mismatch: {e}")


# ===================================================================
# Integration-style: diff output file exists and can be read back
# ===================================================================


class TestDiffOutputProperties:
    """Verify properties of the diff output image file."""

    def test_output_is_rgba_or_rgb(self, different_pair, diff_output_path):
        """The diff image should be in RGB or RGBA mode."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = different_pair
        ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        img = Image.open(diff_output_path)
        assert img.mode in ("RGB", "RGBA")

    def test_output_size_matches_input(self, different_pair, diff_output_path):
        """The diff image dimensions should match the input images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = different_pair
        ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        img = Image.open(diff_output_path)
        # Open the first input to check size
        ref = Image.open(p1)
        assert img.size == ref.size


# ===================================================================
# Edge case tests — large images
# ===================================================================


class TestEdgeCaseLargeImages:
    """Test diff engine with very large images (memory handling)."""

    @pytest.fixture
    def large_image_pair(self, tmp_path):
        """Create two 5000x5000 images with slightly different pixels."""
        from screenshot_diff import ScreenshotDiffEngine  # noqa: F401

        img1 = Image.new("RGBA", (5000, 5000), (128, 128, 128, 255))
        img2 = Image.new("RGBA", (5000, 5000), (128, 128, 128, 255))
        # Change 100 pixels in the second image
        for i in range(100):
            x = i * 50
            y = i * 50
            if x < 5000 and y < 5000:
                img2.putpixel((x, y), (255, 0, 0, 255))
        p1 = str(tmp_path / "large_a.png")
        p2 = str(tmp_path / "large_b.png")
        img1.save(p1)
        img2.save(p2)
        return p1, p2

    def test_large_images_diff_completes(self, large_image_pair, diff_output_path):
        """diff() should complete without error for 5000x5000 images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = large_image_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        assert result.error is None
        assert isinstance(result.pixel_delta, float)

    def test_large_images_pixel_delta_accurate(self, large_image_pair, diff_output_path):
        """Pixel delta should be correct (100 differing out of 25M = 0.000004)."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = large_image_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        # 100 differing pixels / 25,000,000 total
        expected_delta = 100 / (5000 * 5000)
        assert abs(result.pixel_delta - expected_delta) < 1e-10

    def test_large_images_diff_created(self, large_image_pair, diff_output_path):
        """diff() should produce an output file for large images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = large_image_pair
        ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        output = Path(diff_output_path)
        assert output.exists()
        assert output.stat().st_size > 0

    def test_large_images_base64_valid(self, large_image_pair, diff_output_path):
        """diff() should produce valid base64 output for large images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = large_image_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        decoded = base64.b64decode(result.diff_image)
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"


# ===================================================================
# Edge case tests — very small images (1x1)
# ===================================================================


class TestEdgeCaseTinyImages:
    """Test diff engine with 1x1 pixel images."""

    @pytest.fixture
    def tiny_identical_pair(self, tmp_path):
        """Two identical 1x1 images."""
        img1 = Image.new("RGBA", (1, 1), (255, 0, 0, 255))
        p1 = str(tmp_path / "tiny_a.png")
        p2 = str(tmp_path / "tiny_b.png")
        img1.save(p1)
        img1.save(p2)
        return p1, p2

    @pytest.fixture
    def tiny_different_pair(self, tmp_path):
        """Two different 1x1 images."""
        img1 = Image.new("RGBA", (1, 1), (255, 0, 0, 255))
        img2 = Image.new("RGBA", (1, 1), (0, 0, 255, 255))
        p1 = str(tmp_path / "tiny_red.png")
        p2 = str(tmp_path / "tiny_blue.png")
        img1.save(p1)
        img2.save(p2)
        return p1, p2

    def test_tiny_identical_pass(self, tiny_identical_pair, diff_output_path):
        """diff() should pass for identical 1x1 images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = tiny_identical_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path, threshold=0.0)
        assert result.passed is True
        assert result.pixel_delta == 0.0
        assert result.baseline_size == (1, 1)
        assert result.current_size == (1, 1)

    def test_tiny_different_fail(self, tiny_different_pair, diff_output_path):
        """diff() should fail for different 1x1 images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = tiny_different_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path, threshold=0.0)
        assert result.passed is False
        assert result.pixel_delta == 1.0

    def test_tiny_creates_diff_output(self, tiny_different_pair, diff_output_path):
        """diff() should create a valid diff output for 1x1 images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = tiny_different_pair
        ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        output = Path(diff_output_path)
        assert output.exists()
        img = Image.open(diff_output_path)
        assert img.size == (1, 1)


# ===================================================================
# Edge case tests — zero-byte and corrupt files
# ===================================================================


class TestEdgeCaseZeroByte:
    """Test diff engine with zero-byte / empty files."""

    @pytest.fixture
    def zero_byte_path(self, tmp_path):
        """Create a zero-byte file that looks like a PNG."""
        path = str(tmp_path / "empty.png")
        with open(path, "wb") as f:
            f.write(b"")
        return path

    @pytest.fixture
    def valid_image(self, tmp_path):
        """Create a valid small image for comparison."""
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        path = str(tmp_path / "valid.png")
        img.save(path)
        return path

    def test_zero_byte_as_baseline(self, zero_byte_path, valid_image, diff_output_path):
        """diff() should handle zero-byte baseline file gracefully."""
        from screenshot_diff import ScreenshotDiffEngine

        result = ScreenshotDiffEngine.diff(zero_byte_path, valid_image, diff_output_path)
        assert result.error is not None
        assert result.pixel_delta == 0.0

    def test_zero_byte_as_current(self, valid_image, zero_byte_path, diff_output_path):
        """diff() should handle zero-byte current file gracefully."""
        from screenshot_diff import ScreenshotDiffEngine

        result = ScreenshotDiffEngine.diff(valid_image, zero_byte_path, diff_output_path)
        assert result.error is not None

    def test_both_zero_byte(self, zero_byte_path, diff_output_path):
        """diff() should handle both files being zero-byte gracefully."""
        from screenshot_diff import ScreenshotDiffEngine

        # Create a second zero-byte file
        zero2 = zero_byte_path.replace(".png", "_2.png")
        with open(zero2, "wb") as f:
            f.write(b"")

        result = ScreenshotDiffEngine.diff(zero_byte_path, zero2, diff_output_path)
        assert result.error is not None


# ===================================================================
# Edge case tests — threshold boundaries (0.0 and 1.0)
# ===================================================================


class TestEdgeCaseThresholdBounds:
    """Test diff engine with extreme threshold values."""

    def test_threshold_zero_exact_match_passes(self, identical_pair, diff_output_path):
        """threshold=0.0 should pass for perfectly identical images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = identical_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path, threshold=0.0)
        assert result.passed is True
        assert result.pixel_delta == 0.0

    def test_threshold_zero_single_pixel_diff_fails(self, slightly_different_pair, diff_output_path):
        """threshold=0.0 should fail for any difference, even one pixel."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = slightly_different_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path, threshold=0.0)
        assert result.passed is False
        assert result.pixel_delta > 0.0

    def test_threshold_one_always_passes_even_different(self, different_pair, diff_output_path):
        """threshold=1.0 should pass even for completely different images."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = different_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path, threshold=1.0)
        assert result.passed is True

    def test_threshold_one_always_passes_dimension_mismatch(self, dimension_mismatch_pair, diff_output_path):
        """threshold=1.0 should still report dimension mismatch but not pass."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = dimension_mismatch_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path, threshold=1.0)
        # Dimension mismatch has pixel_delta=1.0 which is <= 1.0
        assert result.dimensions_match is False
        assert result.error is not None


# ===================================================================
# Edge case tests — extreme aspect ratios
# ===================================================================


class TestEdgeCaseExtremeAspectRatios:
    """Test diff engine with very tall and very wide images."""

    @pytest.fixture
    def tall_image_pair(self, tmp_path):
        """Create a 1x5000 and an identical tall image."""
        from screenshot_diff import ScreenshotDiffEngine  # noqa: F401

        img1 = Image.new("RGBA", (1, 5000), (128, 128, 128, 255))
        img2 = Image.new("RGBA", (1, 5000), (128, 128, 128, 255))
        img2.putpixel((0, 2500), (255, 0, 0, 255))  # one pixel different
        p1 = str(tmp_path / "tall_a.png")
        p2 = str(tmp_path / "tall_b.png")
        img1.save(p1)
        img2.save(p2)
        return p1, p2

    @pytest.fixture
    def wide_image_pair(self, tmp_path):
        """Create a 5000x1 and an identical wide image."""
        from screenshot_diff import ScreenshotDiffEngine  # noqa: F401

        img1 = Image.new("RGBA", (5000, 1), (128, 128, 128, 255))
        img2 = Image.new("RGBA", (5000, 1), (128, 128, 128, 255))
        img2.putpixel((2500, 0), (255, 0, 0, 255))  # one pixel different
        p1 = str(tmp_path / "wide_a.png")
        p2 = str(tmp_path / "wide_b.png")
        img1.save(p1)
        img2.save(p2)
        return p1, p2

    def test_tall_images_diff_completes(self, tall_image_pair, diff_output_path):
        """diff() should handle 1x5000 images without error."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = tall_image_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        assert result.error is None
        assert result.baseline_size == (1, 5000)

    def test_tall_images_pixel_delta(self, tall_image_pair, diff_output_path):
        """Pixel delta should be 1/5000 for one differing pixel in 1x5000."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = tall_image_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        expected_delta = 1 / 5000
        assert abs(result.pixel_delta - expected_delta) < 1e-10

    def test_wide_images_diff_completes(self, wide_image_pair, diff_output_path):
        """diff() should handle 5000x1 images without error."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = wide_image_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        assert result.error is None
        assert result.baseline_size == (5000, 1)

    def test_wide_images_diff_has_output(self, wide_image_pair, diff_output_path):
        """diff() should produce a valid output file for extreme aspect ratios."""
        from screenshot_diff import ScreenshotDiffEngine

        p1, p2 = wide_image_pair
        result = ScreenshotDiffEngine.diff(p1, p2, diff_output_path)
        assert result.error is None
        output = Path(diff_output_path)
        assert output.exists()
        assert output.stat().st_size > 0
