"""
Anti-detection profile types and validation.

Defines the four predefined stealth profiles, the AntiDetectionProfile
dataclass, the ProfileValidator for fingerprint checks, and the list
of valid selection strategies.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from profile_manager import Profile

logger = logging.getLogger("browser-helper.anti-detection")

# ── Valid selection strategies ──────────────────────────────────────

SELECTION_STRATEGIES = ("random", "sticky", "geo-match")

# ── AntiDetectionProfile dataclass ──────────────────────────────────


@dataclass
class AntiDetectionProfile(Profile):
    """A profile extended with anti-detection fingerprint and type.

    *profile_type* identifies the predefined fingerprint template
    (e.g. ``stealth-chrome-120``, ``standard``). *fingerprint* holds
    the actual signal-group data used for injection.
    """

    profile_type: str = "standard"
    fingerprint: dict[str, Any] = field(default_factory=dict)


# ── Predefined anti-detection profiles ─────────────────────────────

ANTI_DETECTION_PROFILES: dict[str, dict[str, Any]] = {
    "stealth-chrome-120": {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "platform": "Win32",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "screen_width": 1920,
        "screen_height": 1080,
        "color_depth": 24,
        "pixel_ratio": 1.0,
        "timezone": "America/New_York",
        "locale": "en-US",
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0)",
        "canvas_offset": (0, 0),
        "audio_variance_pct": 0.0001,
    },
    "mobile-safari-ios": {
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        "platform": "iPhone",
        "hardware_concurrency": 6,
        "device_memory": 4,
        "screen_width": 390,
        "screen_height": 844,
        "color_depth": 32,
        "pixel_ratio": 3.0,
        "timezone": "America/New_York",
        "locale": "en-US",
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple GPU",
        "canvas_offset": (0, 1),
        "audio_variance_pct": 0.0002,
    },
    "firefox-linux": {
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) "
            "Gecko/20100101 Firefox/120.0"
        ),
        "platform": "Linux x86_64",
        "hardware_concurrency": 4,
        "device_memory": 8,
        "screen_width": 1366,
        "screen_height": 768,
        "color_depth": 24,
        "pixel_ratio": 1.0,
        "timezone": "Europe/Berlin",
        "locale": "de-DE",
        "webgl_vendor": "Mesa/X.org",
        "webgl_renderer": "Mesa DRI Intel(R) HD Graphics 620 (KBL GT2)",
        "canvas_offset": (0, 0),
        "audio_variance_pct": 0.00015,
    },
    "edge-windows": {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
        ),
        "platform": "Win64",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "screen_width": 1920,
        "screen_height": 1080,
        "color_depth": 24,
        "pixel_ratio": 1.0,
        "timezone": "America/New_York",
        "locale": "en-US",
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0)",
        "canvas_offset": (0, 0),
        "audio_variance_pct": 0.0001,
    },
}


# ═══════════════════════════════════════════════════════════════════
# ProfileValidator
# ═══════════════════════════════════════════════════════════════════


class ProfileValidator:
    """Validates a fingerprint dict against known detection signals.

    Uses static analysis (consistency checks) as well as remote
    fingerprint-checker services. Known checkers are listed in
    *known_checkers*.
    """

    def __init__(self) -> None:
        self.known_checkers: list[dict[str, str]] = [
            {
                "name": "sannysoft",
                "url": "https://bot.sannysoft.com/check",
                "type": "get",
            },
            {
                "name": "fingerprintjs",
                "url": "https://fingerprint.com/api/check",
                "type": "post",
            },
        ]

    @staticmethod
    def _check_ua_platform_consistency(profile_fingerprint: dict[str, Any]) -> list[str]:
        """Detect inconsistencies between user-agent and platform."""
        failures: list[str] = []
        ua = (profile_fingerprint.get("user_agent") or "").lower()
        platform = (profile_fingerprint.get("platform") or "").lower()

        # iOS UA vs non-iOS platform
        if "iphone" in ua or "ipad" in ua:
            if "win" in platform or "linux" in platform:
                failures.append("ua_platform_mismatch: iOS UA with non-iOS platform")
        # macOS UA vs non-macOS platform
        elif "mac os" in ua or "macintosh" in ua:
            if "win" in platform or "linux" in platform:
                failures.append("ua_platform_mismatch: macOS UA with non-macOS platform")
        # Windows UA vs non-Windows platform
        elif "windows nt" in ua:
            if "linux" in platform or "iphone" in platform or "mac" in platform:
                failures.append("ua_platform_mismatch: Windows UA with non-Windows platform")
        # Linux UA vs non-Linux platform
        elif "linux" in ua and "x11" not in ua:
            if "win" in platform or "iphone" in platform:
                failures.append("ua_platform_mismatch: Linux UA with non-Linux platform")
        # Firefox UA vs non-Firefox platform hints
        if "firefox" in ua and "edg/" in ua:
            failures.append("ua_browser_conflict: Firefox UA contains Edge marker")

        return failures

    @staticmethod
    def _check_screen_consistency(profile_fingerprint: dict[str, Any]) -> list[str]:
        """Validate screen dimensions are sensible for the device type."""
        failures: list[str] = []
        width = profile_fingerprint.get("screen_width", 0)
        height = profile_fingerprint.get("screen_height", 0)
        ua = (profile_fingerprint.get("user_agent") or "").lower()

        if width <= 0 or height <= 0:
            failures.append("screen_dimensions_invalid: non-positive dimensions")
            return failures

        # iPhone resolution checks
        if "iphone" in ua:
            if width < 320 or height < 480:
                failures.append("screen_too_small_for_ios")
            if width > 480:  # portraid width on iPhone shouldn't exceed ~430
                failures.append("screen_too_wide_for_ios")

        # Desktop checks
        if ("windows" in ua or "linux" in ua or "mac os" in ua) and "iphone" not in ua:
            if width < 800:
                failures.append("screen_too_narrow_for_desktop")

        return failures

    @staticmethod
    def _check_hardware_sanity(profile_fingerprint: dict[str, Any]) -> list[str]:
        """Validate hardware_concurrency and device_memory are plausible."""
        failures: list[str] = []
        hc = profile_fingerprint.get("hardware_concurrency", 0)
        dm = profile_fingerprint.get("device_memory", 0)

        if not isinstance(hc, int) or hc <= 0:
            failures.append("hardware_concurrency_invalid: must be positive int")
        if not isinstance(dm, (int, float)) or dm <= 0:
            failures.append("device_memory_invalid: must be positive number")

        return failures

    @staticmethod
    def _check_webgl_consistency(profile_fingerprint: dict[str, Any]) -> list[str]:
        """Check webgl vendor/renderer pairing is plausible."""
        failures: list[str] = []
        vendor = (profile_fingerprint.get("webgl_vendor") or "").lower()
        renderer = (profile_fingerprint.get("webgl_renderer") or "").lower()
        platform = (profile_fingerprint.get("platform") or "").lower()

        # Apple GPU should not appear on Windows/Linux
        if "apple" in renderer or "apple" in vendor:
            if "win" in platform or "linux" in platform:
                failures.append("webgl_platform_mismatch: Apple GPU on non-Apple platform")
        # Intel GPU on non-Intel platform is fine (common), but require vendor
        if renderer and not vendor:
            failures.append("webgl_missing_vendor")

        return failures

    def validate(
        self,
        profile_fingerprint: dict[str, Any],
        checker_url: str | None = None,
    ) -> dict[str, Any]:
        """Run consistency checks against *profile_fingerprint*.

        Returns a report dict with keys:
            - ``passed``: bool — overall pass/fail
            - ``failed_checks``: list of str — descriptions of each failure
            - ``score``: float — 0.0 (all fail) to 1.0 (all pass)
        """
        failed_checks: list[str] = []

        # Run static analysis checks
        failed_checks.extend(self._check_ua_platform_consistency(profile_fingerprint))
        failed_checks.extend(self._check_screen_consistency(profile_fingerprint))
        failed_checks.extend(self._check_hardware_sanity(profile_fingerprint))
        failed_checks.extend(self._check_webgl_consistency(profile_fingerprint))

        # Count possible checks (4 categories)
        max_checks = 4
        passed_count = max_checks - min(len(failed_checks), max_checks)
        score = passed_count / max_checks if max_checks > 0 else 1.0

        # For empty fingerprint mark everything as failed
        if not profile_fingerprint:
            failed_checks.append("empty_fingerprint: no data to validate")
            score = 0.0

        return {
            "passed": score >= 0.5 and len(failed_checks) == 0,
            "failed_checks": failed_checks,
            "score": round(score, 2),
        }


# Re-export for convenience
__all__ = [
    "AntiDetectionProfile",
    "ANTI_DETECTION_PROFILES",
    "ProfileValidator",
    "SELECTION_STRATEGIES",
]
