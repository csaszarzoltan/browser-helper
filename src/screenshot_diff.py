"""Screenshot Diff Engine — compare screenshots using PIL ImageChops.

Provides ScreenshotDiffEngine (static methods) and DiffResult dataclass.
"""

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops


@dataclass
class DiffResult:
    """Result of a screenshot comparison.

    Attributes:
        passed: True if pixel_delta <= threshold.
        pixel_delta: Fraction of differing pixels (0.0 to 1.0).
        diff_image: Base64-encoded PNG of the visual diff overlay.
        baseline_size: (width, height) of the baseline image.
        current_size: (width, height) of the current image.
        dimensions_match: True if both images have same dimensions.
        error: Error message if something went wrong, else None.
    """
    passed: bool
    pixel_delta: float
    diff_image: str
    baseline_size: tuple
    current_size: tuple
    dimensions_match: bool
    error: str | None = None


class ScreenshotDiffEngine:
    """Static utility class for screenshot comparison."""

    @staticmethod
    def diff(
        baseline_path: str,
        current_path: str,
        output_path: str,
        threshold: float = 0.001,
    ) -> DiffResult:
        """Compare two images and produce a diff result.

        Opens both images, computes pixel delta, creates an overlay
        diff image, saves it to *output_path*, and returns a DiffResult
        that includes a base64-encoded version of the diff image.

        Args:
            baseline_path: Path to the baseline (reference) image.
            current_path: Path to the current (new) image.
            output_path: Where to write the visual diff overlay PNG.
            threshold: Maximum pixel_delta to still consider a pass.

        Returns:
            A DiffResult describing the comparison outcome.
        """
        # Check for missing files
        b_path = Path(baseline_path)
        c_path = Path(current_path)
        if not b_path.exists():
            return DiffResult(
                passed=False,
                pixel_delta=0.0,
                diff_image="",
                baseline_size=(0, 0),
                current_size=(0, 0),
                dimensions_match=True,
                error=f"File not found: {baseline_path}",
            )
        if not c_path.exists():
            return DiffResult(
                passed=False,
                pixel_delta=0.0,
                diff_image="",
                baseline_size=(0, 0),
                current_size=(0, 0),
                dimensions_match=True,
                error=f"File not found: {current_path}",
            )

        try:
            baseline = Image.open(baseline_path)
            current = Image.open(current_path)
        except (OSError, SyntaxError) as exc:
            return DiffResult(
                passed=False,
                pixel_delta=0.0,
                diff_image="",
                baseline_size=(0, 0),
                current_size=(0, 0),
                dimensions_match=True,
                error=str(exc),
            )

        baseline_size = baseline.size
        current_size = current.size

        # Dimension mismatch
        if baseline_size != current_size:
            err_msg = (
                f"Dimension mismatch: baseline={baseline_size}, current={current_size}"
            )
            try:
                ScreenshotDiffEngine._create_diff_image_safe(
                    baseline, current, output_path
                )
            except (OSError, ValueError):  # best-effort: dimension-mismatch overlay may fail
                pass

            diff_b64 = ""
            try:
                with Image.new("RGB", baseline_size, (0, 0, 0)) as blank:
                    buf = BytesIO()
                    blank.save(buf, format="PNG")
                    diff_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            except OSError:  # best-effort: blank diff fallback
                pass

            return DiffResult(
                passed=False,
                pixel_delta=1.0,
                diff_image=diff_b64,
                baseline_size=baseline_size,
                current_size=current_size,
                dimensions_match=False,
                error=err_msg,
            )

        # Compute pixel delta
        pixel_delta = ScreenshotDiffEngine._compute_delta(baseline, current)

        # Create visual diff overlay and write to disk
        ScreenshotDiffEngine._create_diff_image_safe(baseline, current, output_path)

        # Build base64 diff image from the output file
        with Image.open(output_path) as diff_img:
            buf = BytesIO()
            diff_img.save(buf, format="PNG")
            diff_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        passed = pixel_delta <= threshold

        return DiffResult(
            passed=passed,
            pixel_delta=pixel_delta,
            diff_image=diff_b64,
            baseline_size=baseline_size,
            current_size=current_size,
            dimensions_match=True,
            error=None,
        )

    @staticmethod
    def compute_pixel_delta(img1_path: str, img2_path: str) -> float:
        """Return the fraction of pixels that differ between two images.

        Args:
            img1_path: Path to the first image.
            img2_path: Path to the second image.

        Returns:
            A float in [0.0, 1.0] — the ratio of differing pixels.
            1.0 on dimension mismatch, corrupt data, or I/O error.
        """
        try:
            img1 = Image.open(img1_path)
            img2 = Image.open(img2_path)
        except (OSError, SyntaxError):
            return 1.0

        return ScreenshotDiffEngine._compute_delta(img1, img2)

    @staticmethod
    def create_diff_image(
        img1_path: str, img2_path: str, output_path: str
    ) -> None:
        """Create a visual diff image highlighting changed pixels in red.

        Args:
            img1_path: Path to the first image (baseline/reference).
            img2_path: Path to the second image (current/new).
            output_path: Where to write the diff overlay PNG.

        Raises:
            ValueError: If images have different dimensions.
        """
        img1 = Image.open(img1_path)
        img2 = Image.open(img2_path)

        if img1.size != img2.size:
            raise ValueError(
                f"Dimension mismatch: {img1.size} vs {img2.size}"
            )

        ScreenshotDiffEngine._create_diff_image_safe(img1, img2, output_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_delta(img1: Image.Image, img2: Image.Image) -> float:
        """Compute pixel delta between two already-open PIL images."""
        if img1.size != img2.size:
            return 1.0

        try:
            diff = ImageChops.difference(img1, img2)
        except (OSError, ValueError):
            return 1.0

        # Count non-black pixels in the grayscale difference
        gray = diff.convert("L")
        diff_count = sum(1 for p in gray.getdata() if p > 0)
        total_pixels = img1.size[0] * img1.size[1]

        return diff_count / total_pixels if total_pixels > 0 else 0.0

    @staticmethod
    def _create_diff_image_safe(
        img1: Image.Image, img2: Image.Image, output_path: str
    ) -> None:
        """Create a visual diff overlay: changed pixels in red on black.

        Both images must have the same dimensions.  The result is always
        saved as an RGB PNG.
        """
        # Compute per-pixel absolute difference
        diff = ImageChops.difference(img1, img2)

        # Convert to RGB if needed
        if diff.mode != "RGB":
            diff = diff.convert("RGB")

        # Build output: black background, red for changed pixels
        out = Image.new("RGB", diff.size, (0, 0, 0))
        pixels_out = out.load()
        pixels_diff = diff.load()
        w, h = diff.size

        for y in range(h):
            for x in range(w):
                r, g, b = pixels_diff[x, y]
                if r > 0 or g > 0 or b > 0:
                    pixels_out[x, y] = (255, 0, 0)

        out.save(output_path, format="PNG")
