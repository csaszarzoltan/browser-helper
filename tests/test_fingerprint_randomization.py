"""
Pre-development tests for Fingerprint Randomization Engine signal modules (RED phase).

╔══════════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                               ║
║                                                                        ║
║  Interface tests (green checkmark) → assert pass immediately with stub  ║
║  Behavioral tests (red X)          → assert fail until implementation   ║
║                                                                        ║
║  Classes under test:                                                   ║
║    CanvasFingerprinter     — canvas noise injection                     ║
║    WebGLSpoofer            — WebGL vendor/renderer spoofing            ║
║    AudioContextRandomizer  — AudioContext output variance              ║
║    NavigatorSpoofer        — navigator.* spoofing consistency          ║
║    ScreenColorConsistency  — screen/color/timezone/locale alignment    ║
║    TLSFingerprintAligner   — TLS/JA3 cipher suite alignment (P2 stub)  ║
║                                                                        ║
║  Acceptance Criteria (from analysis brief P0.1):                       ║
║    1. Canvas — toDataURL/getImageData noise injection                  ║
║    2. WebGL — spoof WEBGL_debug_renderer_info, getParameter           ║
║    3. AudioContext — getChannelData variance (0.1-1.0%)               ║
║    4. Navigator — userAgent, platform, language, concurrency, memory   ║
║    5. Screen — dimensions, colorDepth, pixelRatio, timezone, locale    ║
║    6. TLS/JA3 — cipher suite alignment with proxy geo (P2 deferred)    ║
║    7. Re-randomization on CDP connect and per-navigate                 ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import get_type_hints

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from anti_detection.signal_modules import (
    AudioContextRandomizer,
    CanvasFingerprinter,
    NavigatorSpoofer,
    ScreenColorConsistency,
    TLSFingerprintAligner,
    WebGLSpoofer,
)

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Interface Tests (PASSING — green checkmark)
# ═══════════════════════════════════════════════════════════════════════════


class TestCanvasFingerprinterInterface:
    """CanvasFingerprinter class contract tests."""

    def test_class_exists(self):
        """CanvasFingerprinter is importable and is a class."""
        assert isinstance(CanvasFingerprinter, type)

    def test_has_build_patch_static(self):
        """build_patch is a static method."""
        m = CanvasFingerprinter.__dict__.get("build_patch")
        assert isinstance(m, staticmethod), "build_patch should be a staticmethod"

    def test_build_patch_signature(self):
        """build_patch accepts (canvas_offset: tuple[int, int]) -> str."""
        sig = inspect.signature(CanvasFingerprinter.build_patch)
        params = list(sig.parameters.values())
        assert len(params) == 1, f"Expected 1 param, got {len(params)}"
        assert params[0].name == "canvas_offset"
        # Type hint check
        hints = get_type_hints(CanvasFingerprinter.build_patch)
        assert hints.get("return") is str or hints.get("return") == str, (
            f"build_patch should return str, got {hints.get('return')}"
        )

    def test_build_patch_annotation(self):
        """build_patch param canvas_offset is annotated as tuple[int, int]."""
        hints = get_type_hints(CanvasFingerprinter.build_patch)
        canvas_ann = hints.get("canvas_offset")
        hint_str = str(canvas_ann)
        assert "tuple" in hint_str.lower() or canvas_ann is tuple, (
            f"canvas_offset should be tuple type, got {hint_str}"
        )

    def test_has_measure_entropy_static(self):
        """measure_entropy is a static method."""
        m = CanvasFingerprinter.__dict__.get("measure_entropy")
        assert isinstance(m, staticmethod), "measure_entropy should be a staticmethod"

    def test_measure_entropy_signature(self):
        """measure_entropy accepts (patch_js: str) -> float."""
        sig = inspect.signature(CanvasFingerprinter.measure_entropy)
        assert len(sig.parameters) == 1
        hints = get_type_hints(CanvasFingerprinter.measure_entropy)
        assert hints.get("return") in (float,), (
            f"measure_entropy should return float, got {hints.get('return')}"
        )


class TestWebGLSpooferInterface:
    """WebGLSpoofer class contract tests."""

    def test_class_exists(self):
        """WebGLSpoofer is importable and is a class."""
        assert isinstance(WebGLSpoofer, type)

    def test_has_build_patch_static(self):
        """build_patch is a static method."""
        m = WebGLSpoofer.__dict__.get("build_patch")
        assert isinstance(m, staticmethod)

    def test_build_patch_signature(self):
        """build_patch accepts (webgl_vendor: str, webgl_renderer: str) -> str."""
        sig = inspect.signature(WebGLSpoofer.build_patch)
        assert len(sig.parameters) == 2
        hints = get_type_hints(WebGLSpoofer.build_patch)
        assert hints.get("return") is str

    def test_has_get_gpu_profiles_static(self):
        """get_gpu_profiles is a static method."""
        m = WebGLSpoofer.__dict__.get("get_gpu_profiles")
        assert isinstance(m, staticmethod)

    def test_get_gpu_profiles_signature(self):
        """get_gpu_profiles returns dict[str, list[str]]."""
        sig = inspect.signature(WebGLSpoofer.get_gpu_profiles)
        assert len(sig.parameters) == 0
        hints = get_type_hints(WebGLSpoofer.get_gpu_profiles)
        ret = hints.get("return")
        hint_str = str(ret)
        assert "dict" in hint_str.lower() or "Dict" in hint_str, (
            f"get_gpu_profiles should return dict, got {hint_str}"
        )


class TestAudioContextRandomizerInterface:
    """AudioContextRandomizer class contract tests."""

    def test_class_exists(self):
        """AudioContextRandomizer is importable and is a class."""
        assert isinstance(AudioContextRandomizer, type)

    def test_has_build_patch_static(self):
        """build_patch is a static method."""
        m = AudioContextRandomizer.__dict__.get("build_patch")
        assert isinstance(m, staticmethod)

    def test_build_patch_signature(self):
        """build_patch accepts (variance_pct: float) -> str."""
        sig = inspect.signature(AudioContextRandomizer.build_patch)
        assert len(sig.parameters) == 1
        hints = get_type_hints(AudioContextRandomizer.build_patch)
        assert hints.get("return") is str

    def test_has_validate_variance_static(self):
        """validate_variance is a static method."""
        m = AudioContextRandomizer.__dict__.get("validate_variance")
        assert isinstance(m, staticmethod)

    def test_validate_variance_signature(self):
        """validate_variance accepts (variance_pct: float) -> bool."""
        sig = inspect.signature(AudioContextRandomizer.validate_variance)
        assert len(sig.parameters) == 1
        hints = get_type_hints(AudioContextRandomizer.validate_variance)
        assert hints.get("return") is bool


class TestNavigatorSpooferInterface:
    """NavigatorSpoofer class contract tests."""

    def test_class_exists(self):
        """NavigatorSpoofer is importable and is a class."""
        assert isinstance(NavigatorSpoofer, type)

    def test_has_build_ua_patch_static(self):
        """build_ua_patch is a static method."""
        m = NavigatorSpoofer.__dict__.get("build_ua_patch")
        assert isinstance(m, staticmethod)

    def test_build_ua_patch_signature(self):
        """build_ua_patch accepts (user_agent: str) -> str."""
        sig = inspect.signature(NavigatorSpoofer.build_ua_patch)
        assert len(sig.parameters) == 1
        hints = get_type_hints(NavigatorSpoofer.build_ua_patch)
        assert hints.get("return") is str

    def test_has_build_language_patch_static(self):
        """build_language_patch is a static method."""
        m = NavigatorSpoofer.__dict__.get("build_language_patch")
        assert isinstance(m, staticmethod)

    def test_build_language_patch_signature(self):
        """build_language_patch accepts (language: str, languages: list[str]) -> str."""
        sig = inspect.signature(NavigatorSpoofer.build_language_patch)
        assert len(sig.parameters) == 2
        hints = get_type_hints(NavigatorSpoofer.build_language_patch)
        assert hints.get("return") is str

    def test_has_build_hardware_patch_static(self):
        """build_hardware_patch is a static method."""
        m = NavigatorSpoofer.__dict__.get("build_hardware_patch")
        assert isinstance(m, staticmethod)

    def test_build_hardware_patch_signature(self):
        """build_hardware_patch accepts (concurrency: int, device_memory: float) -> str."""
        sig = inspect.signature(NavigatorSpoofer.build_hardware_patch)
        assert len(sig.parameters) == 2
        hints = get_type_hints(NavigatorSpoofer.build_hardware_patch)
        assert hints.get("return") is str

    def test_has_build_navigator_patch_static(self):
        """build_navigator_patch is a static method."""
        m = NavigatorSpoofer.__dict__.get("build_navigator_patch")
        assert isinstance(m, staticmethod)

    def test_build_navigator_patch_signature(self):
        """build_navigator_patch accepts (props: dict) -> str."""
        sig = inspect.signature(NavigatorSpoofer.build_navigator_patch)
        assert len(sig.parameters) == 1
        hints = get_type_hints(NavigatorSpoofer.build_navigator_patch)
        assert hints.get("return") is str


class TestScreenColorConsistencyInterface:
    """ScreenColorConsistency class contract tests."""

    def test_class_exists(self):
        """ScreenColorConsistency is importable and is a class."""
        assert isinstance(ScreenColorConsistency, type)

    def test_has_build_screen_patch_static(self):
        """build_screen_patch is a static method."""
        m = ScreenColorConsistency.__dict__.get("build_screen_patch")
        assert isinstance(m, staticmethod)

    def test_build_screen_patch_signature(self):
        """build_screen_patch accepts (width, height, color_depth, pixel_ratio) -> str."""
        sig = inspect.signature(ScreenColorConsistency.build_screen_patch)
        assert len(sig.parameters) == 4
        hints = get_type_hints(ScreenColorConsistency.build_screen_patch)
        assert hints.get("return") is str

    def test_has_build_timezone_patch_static(self):
        """build_timezone_patch is a static method."""
        m = ScreenColorConsistency.__dict__.get("build_timezone_patch")
        assert isinstance(m, staticmethod)

    def test_build_timezone_patch_signature(self):
        """build_timezone_patch accepts (timezone: str) -> str."""
        sig = inspect.signature(ScreenColorConsistency.build_timezone_patch)
        assert len(sig.parameters) == 1
        hints = get_type_hints(ScreenColorConsistency.build_timezone_patch)
        assert hints.get("return") is str

    def test_has_build_locale_patch_static(self):
        """build_locale_patch is a static method."""
        m = ScreenColorConsistency.__dict__.get("build_locale_patch")
        assert isinstance(m, staticmethod)

    def test_build_locale_patch_signature(self):
        """build_locale_patch accepts (locale: str) -> str."""
        sig = inspect.signature(ScreenColorConsistency.build_locale_patch)
        assert len(sig.parameters) == 1
        hints = get_type_hints(ScreenColorConsistency.build_locale_patch)
        assert hints.get("return") is str

    def test_has_build_color_consistency_patch_static(self):
        """build_color_consistency_patch is a static method."""
        m = ScreenColorConsistency.__dict__.get("build_color_consistency_patch")
        assert isinstance(m, staticmethod)

    def test_build_color_consistency_patch_signature(self):
        """build_color_consistency_patch accepts (props: dict) -> str."""
        sig = inspect.signature(ScreenColorConsistency.build_color_consistency_patch)
        assert len(sig.parameters) == 1
        hints = get_type_hints(ScreenColorConsistency.build_color_consistency_patch)
        assert hints.get("return") is str


class TestTLSFingerprintAlignerInterface:
    """TLSFingerprintAligner class contract tests."""

    def test_class_exists(self):
        """TLSFingerprintAligner is importable and is a class."""
        assert isinstance(TLSFingerprintAligner, type)

    def test_has_build_patch_static(self):
        """build_patch is a static method."""
        m = TLSFingerprintAligner.__dict__.get("build_patch")
        assert isinstance(m, staticmethod)

    def test_build_patch_signature(self):
        """build_patch() -> str (no params)."""
        sig = inspect.signature(TLSFingerprintAligner.build_patch)
        assert len(sig.parameters) == 0
        hints = get_type_hints(TLSFingerprintAligner.build_patch)
        assert hints.get("return") is str

    def test_has_align_cipher_suites_static(self):
        """align_cipher_suites is a static method."""
        m = TLSFingerprintAligner.__dict__.get("align_cipher_suites")
        assert isinstance(m, staticmethod)

    def test_align_cipher_suites_signature(self):
        """align_cipher_suites accepts (proxy_geo: str) -> list[str]."""
        sig = inspect.signature(TLSFingerprintAligner.align_cipher_suites)
        assert len(sig.parameters) == 1
        hints = get_type_hints(TLSFingerprintAligner.align_cipher_suites)
        ret = hints.get("return")
        hint_str = str(ret)
        assert "list" in hint_str.lower() or "List" in hint_str, (
            f"align_cipher_suites should return list[str], got {hint_str}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — Behavioral Tests (RED — fails with NotImplementedError)
# ═══════════════════════════════════════════════════════════════════════════


class TestCanvasFingerprinterRED:
    """CanvasFingerprinter behavioral tests — RED phase."""

    def test_build_patch_returns_js_string(self):
        """build_patch should return a non-empty JS string (no exception)."""
        js = CanvasFingerprinter.build_patch(canvas_offset=(2, 1))
        assert isinstance(js, str)
        assert len(js) > 0

    def test_measure_entropy_returns_float(self):
        """measure_entropy should return a float (no exception)."""
        entropy = CanvasFingerprinter.measure_entropy(patch_js="(function(){})()")
        assert isinstance(entropy, float)
        assert 0.0 <= entropy <= 8.0

    def test_build_patch_returns_string(self):
        """build_patch should return a non-empty JS string."""
        js = CanvasFingerprinter.build_patch(canvas_offset=(2, 1))
        assert isinstance(js, str)
        assert len(js) > 0

    def test_different_offsets_different_output(self):
        """Different canvas offsets produce different JS patches."""
        js1 = CanvasFingerprinter.build_patch(canvas_offset=(0, 0))
        js2 = CanvasFingerprinter.build_patch(canvas_offset=(3, 2))
        assert js1 != js2, (
            "Patches for different offsets should differ"
        )


class TestWebGLSpooferRED:
    """WebGLSpoofer behavioral tests — GREEN phase."""

    def test_build_patch_returns_string(self):
        """build_patch should return a non-empty JS string."""
        js = WebGLSpoofer.build_patch(
            webgl_vendor="Google Inc. (NVIDIA)",
            webgl_renderer="ANGLE (NVIDIA, RTX 3080)",
        )
        assert isinstance(js, str) and len(js) > 0

    def test_get_gpu_profiles_returns_dict(self):
        """get_gpu_profiles should return a dict (no exception)."""
        profiles = WebGLSpoofer.get_gpu_profiles()
        assert isinstance(profiles, dict)
        assert len(profiles) >= 4

    def test_vendor_appears_in_js(self):
        """The vendor string should appear in the generated JS."""
        vendor = "Google Inc. (NVIDIA)"
        js = WebGLSpoofer.build_patch(
            webgl_vendor=vendor,
            webgl_renderer="ANGLE (NVIDIA, RTX 3080)",
        )
        assert vendor in js

    def test_different_vendor_different_output(self):
        """Different vendor strings produce different JS."""
        js1 = WebGLSpoofer.build_patch(
            webgl_vendor="NVIDIA", webgl_renderer="RTX 4090"
        )
        js2 = WebGLSpoofer.build_patch(
            webgl_vendor="AMD", webgl_renderer="RX 7900 XTX"
        )
        assert js1 != js2

    @pytest.mark.parametrize(
        "vendor, renderer",
        [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, RTX 3080)"),
            ("AMD", "ANGLE (AMD, AMD Radeon RX 7900 XTX Direct3D11)"),
            ("Intel", "ANGLE (Intel, Intel(R) Arc(TM) A770 Graphics Direct3D11)"),
            ("Apple", "Apple M2"),
        ],
    )
    def test_plausible_gpu_strings(self, vendor, renderer):
        """Should accept various plausible GPU vendor/renderer pairs."""
        js = WebGLSpoofer.build_patch(webgl_vendor=vendor, webgl_renderer=renderer)
        assert isinstance(js, str) and len(js) > 0

    def test_gpu_profiles_has_vendors(self):
        """get_gpu_profiles returns dict with well-known GPU vendors."""
        profiles = WebGLSpoofer.get_gpu_profiles()
        assert isinstance(profiles, dict)
        assert len(profiles) >= 4, "Should have at least 4 vendor entries"
        for vendor, renderers in profiles.items():
            assert isinstance(vendor, str)
            assert isinstance(renderers, list)
            assert len(renderers) >= 1


class TestAudioContextRandomizerRED:
    """AudioContextRandomizer behavioral tests — GREEN phase."""

    def test_build_patch_returns_string(self):
        """build_patch should return a non-empty JS string."""
        js = AudioContextRandomizer.build_patch(variance_pct=0.003)
        assert isinstance(js, str) and len(js) > 0

    def test_validate_variance_in_range(self):
        """validate_variance should accept valid values (no exception)."""
        assert AudioContextRandomizer.validate_variance(variance_pct=0.005) is True

    def test_variance_0_1_pct_accepted(self):
        """variance_pct=0.001 (0.1%) should be valid."""
        js = AudioContextRandomizer.build_patch(variance_pct=0.001)
        assert isinstance(js, str) and len(js) > 0

    def test_variance_1_0_pct_accepted(self):
        """variance_pct=0.01 (1.0%) should be valid."""
        js = AudioContextRandomizer.build_patch(variance_pct=0.01)
        assert isinstance(js, str) and len(js) > 0

    def test_variance_out_of_range_rejected(self):
        """variance_pct outside [0.001, 0.01] should be rejected by validate."""
        valid = AudioContextRandomizer.validate_variance(variance_pct=0.05)
        assert valid is False, "variance_pct=0.05 should be out of range"

    def test_variance_in_range_accepted(self):
        """variance_pct inside [0.001, 0.01] should pass validate."""
        valid = AudioContextRandomizer.validate_variance(variance_pct=0.005)
        assert valid is True


class TestNavigatorSpooferRED:
    """NavigatorSpoofer behavioral tests — GREEN phase."""

    def test_build_ua_patch_returns_string(self):
        """build_ua_patch should return a non-empty JS string."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        js = NavigatorSpoofer.build_ua_patch(user_agent=ua)
        assert isinstance(js, str) and len(js) > 0
        assert "userAgent" in js or "platform" in js

    def test_build_language_patch_returns_string(self):
        """build_language_patch should return a non-empty JS string."""
        js = NavigatorSpoofer.build_language_patch(
            language="en-US", languages=["en-US", "en"]
        )
        assert isinstance(js, str) and len(js) > 0
        assert "language" in js or "languages" in js

    def test_build_hardware_patch_returns_string(self):
        """build_hardware_patch should return a non-empty JS string."""
        js = NavigatorSpoofer.build_hardware_patch(concurrency=8, device_memory=8.0)
        assert isinstance(js, str) and len(js) > 0
        assert "hardwareConcurrency" in js or "deviceMemory" in js

    def test_build_navigator_patch_returns_string(self):
        """build_navigator_patch should return a non-empty JS string."""
        props = {
            "user_agent": "Mozilla/5.0 ...",
            "platform": "Win32",
            "language": "en-US",
            "languages": ["en-US", "en"],
            "hardware_concurrency": 8,
            "device_memory": 8,
        }
        js = NavigatorSpoofer.build_navigator_patch(props=props)
        assert isinstance(js, str) and len(js) > 0

    def test_different_ua_different_output(self):
        """Different user agents produce different patches."""
        ua1 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        ua2 = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15"
        js1 = NavigatorSpoofer.build_ua_patch(user_agent=ua1)
        js2 = NavigatorSpoofer.build_ua_patch(user_agent=ua2)
        assert js1 != js2


class TestScreenColorConsistencyRED:
    """ScreenColorConsistency behavioral tests — GREEN phase."""

    def test_build_screen_patch_returns_string(self):
        """build_screen_patch should return a non-empty JS string."""
        js = ScreenColorConsistency.build_screen_patch(
            width=1920, height=1080, color_depth=24, pixel_ratio=1.0
        )
        assert isinstance(js, str) and len(js) > 0
        assert "screen" in js.lower()

    def test_build_timezone_patch_returns_string(self):
        """build_timezone_patch should return a non-empty JS string."""
        js = ScreenColorConsistency.build_timezone_patch(
            timezone="America/New_York"
        )
        assert isinstance(js, str) and len(js) > 0
        assert "timezone" in js.lower() or "getTimezoneOffset" in js

    def test_build_locale_patch_returns_string(self):
        """build_locale_patch should return a non-empty JS string."""
        js = ScreenColorConsistency.build_locale_patch(locale="en-US")
        assert isinstance(js, str) and len(js) > 0

    def test_different_screen_sizes_different_output(self):
        """Different screen dimensions produce different patches."""
        js1 = ScreenColorConsistency.build_screen_patch(
            width=1920, height=1080, color_depth=24, pixel_ratio=1.0
        )
        js2 = ScreenColorConsistency.build_screen_patch(
            width=390, height=844, color_depth=32, pixel_ratio=3.0
        )
        assert js1 != js2

    def test_color_consistency_patch_accepts_full_profile(self):
        """build_color_consistency_patch accepts all mobile-safari-ios fields."""
        props = {
            "screen_width": 390,
            "screen_height": 844,
            "color_depth": 32,
            "pixel_ratio": 3.0,
            "timezone": "America/New_York",
            "locale": "en-US",
        }
        js = ScreenColorConsistency.build_color_consistency_patch(props=props)
        assert isinstance(js, str) and len(js) > 0


class TestTLSFingerprintAlignerRED:
    """TLSFingerprintAligner behavioral tests — GREEN phase (P2 deferred)."""

    def test_build_patch_returns_empty_string(self):
        """build_patch should return an empty string (no JS for TLS)."""
        js = TLSFingerprintAligner.build_patch()
        assert isinstance(js, str)
        assert js == "", "TLS patch should be empty (no JS injection available)"

    def test_align_cipher_suites_returns_list(self):
        """align_cipher_suites should return a list of cipher suite strings."""
        suites = TLSFingerprintAligner.align_cipher_suites(proxy_geo="EU-West")
        assert isinstance(suites, list)
        assert len(suites) > 0
        for s in suites:
            assert isinstance(s, str)

    @pytest.mark.parametrize("geo", ["US-East", "EU-West", "Asia-SE", "US-West"])
    def test_different_geo_different_suites(self, geo):
        """Different proxy geolocations should produce different cipher lists."""
        suites1 = TLSFingerprintAligner.align_cipher_suites(proxy_geo="US-East")
        suites2 = TLSFingerprintAligner.align_cipher_suites(proxy_geo=geo)
        if geo == "US-East":
            return  # Same geo, same suites
        assert suites1 != suites2
        for s in suites2:
            assert isinstance(s, str)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — Integration / Cross-Module Tests (RED phase)
# ═══════════════════════════════════════════════════════════════════════════


class TestReRandomizationRED:
    """Re-randomization on CDP connect and per-navigate — GREEN phase."""

    def test_re_randomization_trigger_exists(self):
        """Re-randomization should be possible: different offsets per call."""
        patch1 = CanvasFingerprinter.build_patch(canvas_offset=(1, 0))
        patch2 = CanvasFingerprinter.build_patch(canvas_offset=(3, 2))
        assert patch1 != patch2, (
            "Different canvas offsets should produce different patches "
            "(enables per-navigate re-randomization)"
        )

    def test_cross_module_profile_consistency(self):
        """All signal patches should be derivable from a single fingerprint dict."""
        fingerprint = {
            "canvas_offset": (2, 1),
            "webgl_vendor": "Google Inc. (Intel)",
            "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11)",
            "audio_variance_pct": 0.003,
            "user_agent": "Mozilla/5.0 ...",
            "platform": "Win32",
            "language": "en-US",
            "languages": ["en-US", "en"],
            "hardware_concurrency": 8,
            "device_memory": 8,
            "screen_width": 1920,
            "screen_height": 1080,
            "color_depth": 24,
            "pixel_ratio": 1.0,
            "timezone": "America/New_York",
            "locale": "en-US",
        }
        canvas_js = CanvasFingerprinter.build_patch(
            canvas_offset=fingerprint["canvas_offset"]
        )
        webgl_js = WebGLSpoofer.build_patch(
            webgl_vendor=fingerprint["webgl_vendor"],
            webgl_renderer=fingerprint["webgl_renderer"],
        )
        audio_js = AudioContextRandomizer.build_patch(
            variance_pct=fingerprint["audio_variance_pct"]
        )
        navigator_js = NavigatorSpoofer.build_navigator_patch(
            props={
                "user_agent": fingerprint["user_agent"],
                "platform": fingerprint["platform"],
                "language": fingerprint["language"],
                "languages": fingerprint["languages"],
                "hardware_concurrency": fingerprint["hardware_concurrency"],
                "device_memory": fingerprint["device_memory"],
            }
        )
        screen_js = ScreenColorConsistency.build_color_consistency_patch(
            props={
                "screen_width": fingerprint["screen_width"],
                "screen_height": fingerprint["screen_height"],
                "color_depth": fingerprint["color_depth"],
                "pixel_ratio": fingerprint["pixel_ratio"],
                "timezone": fingerprint["timezone"],
                "locale": fingerprint["locale"],
            }
        )

        checks = [
            ("canvas", canvas_js),
            ("webgl", webgl_js),
            ("audio", audio_js),
            ("navigator", navigator_js),
            ("screen", screen_js),
        ]
        for name, js in checks:
            assert isinstance(js, str) and len(js) > 0, (
                f"{name} patch should be non-empty string"
            )

        # All 5 JS patches should be distinct (different signal groups)
        unique_js = {js for _, js in checks}
        assert len(unique_js) >= 4, (
            "At least 4 of 5 signal patches should be different strings"
        )

        # All 5 combined should be injectable as a list
        all_scripts = [js for _, js in checks]
        assert len(all_scripts) == 5
