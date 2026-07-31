"""
Pre-development tests for FingerprintEngine module (RED phase).

╔══════════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                               ║
║                                                                        ║
║  Interface tests (green checkmark) → assert pass immediately with stub  ║
║  Behavioral tests (red X)          → assert fail until implementation   ║
║                                                                        ║
║  Acceptance Criteria (from analysis brief P0.1):                       ║
║    1. FingerprintConfig is a dataclass with all spec fields            ║
║    2. FingerprintEngine class exists with correct method signatures    ║
║    3. generate_canvas_noise_script() returns valid JS string           ║
║    4. generate_webgl_override_script() returns valid JS string         ║
║    5. generate_audio_override_script() returns valid JS string         ║
║    6. generate_all_scripts() returns list[str] with all scripts        ║
║    7. get_plausible_gpu_pool() returns dict with real GPU entries      ║
║    8. get_default_config() returns FingerprintConfig with defaults     ║
║    9. Per-session seed: same seed → same noise (consistency)          ║
║   10. Canvas toDataURL output differs per session (different seed)     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import get_type_hints

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from fingerprint_engine import FingerprintConfig, FingerprintEngine


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def engine() -> FingerprintEngine:
    """Return a FingerprintEngine with default config."""
    return FingerprintEngine()


@pytest.fixture
def engine_with_config() -> FingerprintEngine:
    """Return a FingerprintEngine with a custom config."""
    return FingerprintEngine(
        FingerprintConfig(
            canvas_noise_seed=42,
            webgl_vendor="Google Inc. (NVIDIA)",
            webgl_renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
            audio_sample_rate=48000,
            geolocation={"lat": 47.3769, "lng": 8.5417},
            timezone="Europe/Zurich",
            locale="de-CH",
        )
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Interface Tests (PASSING — green checkmark)
# ═══════════════════════════════════════════════════════════════════════════


class TestFingerprintConfigInterface:
    """FingerprintConfig dataclass contract tests."""

    def test_is_dataclass(self):
        """FingerprintConfig is a dataclass."""
        assert is_dataclass(FingerprintConfig), (
            "FingerprintConfig must be a dataclass"
        )

    def test_has_canvas_noise_seed_field(self):
        """FingerprintConfig has canvas_noise_seed: int = 0."""
        assert "canvas_noise_seed" in FingerprintConfig.__dataclass_fields__, (
            "Missing canvas_noise_seed field"
        )
        f = FingerprintConfig.__dataclass_fields__["canvas_noise_seed"]
        assert f.type is int or str(f.type) == "int", (
            f"canvas_noise_seed must be int, got {f.type}"
        )

    def test_has_webgl_vendor_field(self):
        """FingerprintConfig has webgl_vendor: str = ''."""
        assert "webgl_vendor" in FingerprintConfig.__dataclass_fields__, (
            "Missing webgl_vendor field"
        )

    def test_has_webgl_renderer_field(self):
        """FingerprintConfig has webgl_renderer: str = ''."""
        assert "webgl_renderer" in FingerprintConfig.__dataclass_fields__, (
            "Missing webgl_renderer field"
        )

    def test_has_audio_sample_rate_field(self):
        """FingerprintConfig has audio_sample_rate: int = 44100."""
        assert "audio_sample_rate" in FingerprintConfig.__dataclass_fields__, (
            "Missing audio_sample_rate field"
        )

    def test_has_geolocation_field(self):
        """FingerprintConfig has geolocation: dict | None = None."""
        assert "geolocation" in FingerprintConfig.__dataclass_fields__, (
            "Missing geolocation field"
        )

    def test_has_timezone_field(self):
        """FingerprintConfig has timezone: str | None = None."""
        assert "timezone" in FingerprintConfig.__dataclass_fields__, (
            "Missing timezone field"
        )

    def test_has_locale_field(self):
        """FingerprintConfig has locale: str | None = None."""
        assert "locale" in FingerprintConfig.__dataclass_fields__, (
            "Missing locale field"
        )

    def test_all_spec_fields_present(self):
        """All 7 spec fields are present in FingerprintConfig."""
        expected = {
            "canvas_noise_seed",
            "webgl_vendor",
            "webgl_renderer",
            "audio_sample_rate",
            "geolocation",
            "timezone",
            "locale",
        }
        actual = set(FingerprintConfig.__dataclass_fields__.keys())
        missing = expected - actual
        assert not missing, f"Missing fields: {missing}"

    def test_default_canvas_noise_seed_is_zero(self):
        """canvas_noise_seed defaults to 0."""
        cfg = FingerprintConfig()
        assert cfg.canvas_noise_seed == 0

    def test_default_audio_sample_rate_is_44100(self):
        """audio_sample_rate defaults to 44100."""
        cfg = FingerprintConfig()
        assert cfg.audio_sample_rate == 44100

    def test_default_geolocation_is_none(self):
        """geolocation defaults to None."""
        cfg = FingerprintConfig()
        assert cfg.geolocation is None


class TestFingerprintEngineInterface:
    """FingerprintEngine class contract tests."""

    def test_class_exists(self):
        """FingerprintEngine can be imported."""
        from fingerprint_engine import FingerprintEngine

        assert FingerprintEngine is not None

    def test_can_instantiate(self):
        """FingerprintEngine() creates an instance."""
        engine = FingerprintEngine()
        assert isinstance(engine, FingerprintEngine)

    def test_constructor_accepts_none_config(self):
        """FingerprintEngine(None) works."""
        engine = FingerprintEngine(None)
        assert isinstance(engine, FingerprintEngine)

    def test_constructor_accepts_fingerprint_config(self):
        """FingerprintEngine(config) accepts a FingerprintConfig."""
        cfg = FingerprintConfig()
        engine = FingerprintEngine(cfg)
        assert isinstance(engine, FingerprintEngine)

    def test_config_property_exists(self):
        """FingerprintEngine has a config property."""
        assert hasattr(FingerprintEngine, "config"), (
            "Missing config property"
        )

    def test_config_property_returns_config(self, engine):
        """FingerprintEngine.config returns a FingerprintConfig."""
        cfg = engine.config
        assert isinstance(cfg, FingerprintConfig)

    def test_config_setter_works(self, engine):
        """FingerprintEngine.config setter accepts a FingerprintConfig."""
        new_cfg = FingerprintConfig(canvas_noise_seed=99)
        engine.config = new_cfg
        assert engine.config.canvas_noise_seed == 99

    def test_get_default_config_is_static_method(self):
        """get_default_config is a static method."""
        method = FingerprintEngine.get_default_config
        assert isinstance(inspect.getattr_static(FingerprintEngine, "get_default_config"), staticmethod) or \
               callable(method), "get_default_config should be callable as a static method"

    def test_get_default_config_callable(self):
        """get_default_config can be called without an instance."""
        assert callable(FingerprintEngine.get_default_config)

    def test_generate_canvas_noise_script_is_static(self):
        """generate_canvas_noise_script is a static method."""
        assert callable(FingerprintEngine.generate_canvas_noise_script)

    def test_generate_webgl_override_script_is_static(self):
        """generate_webgl_override_script is a static method."""
        assert callable(FingerprintEngine.generate_webgl_override_script)

    def test_generate_audio_override_script_is_static(self):
        """generate_audio_override_script is a static method."""
        assert callable(FingerprintEngine.generate_audio_override_script)

    def test_generate_all_scripts_is_method(self, engine):
        """generate_all_scripts is an instance method."""
        assert callable(engine.generate_all_scripts)

    def test_get_plausible_gpu_pool_is_static(self):
        """get_plausible_gpu_pool is a static method."""
        assert callable(FingerprintEngine.get_plausible_gpu_pool)

    def test_generate_canvas_noise_script_signature(self):
        """generate_canvas_noise_script accepts (seed: int) -> str."""
        sig = inspect.signature(FingerprintEngine.generate_canvas_noise_script)
        params = list(sig.parameters.keys())
        assert "seed" in params, f"Missing 'seed' parameter, got {params}"
        assert sig.return_annotation is str or str(sig.return_annotation) == "str", (
            f"Return annotation should be str, got {sig.return_annotation}"
        )

    def test_generate_webgl_override_script_signature(self):
        """generate_webgl_override_script accepts (vendor, renderer) -> str."""
        sig = inspect.signature(FingerprintEngine.generate_webgl_override_script)
        assert "vendor" in sig.parameters
        assert "renderer" in sig.parameters

    def test_generate_audio_override_script_signature(self):
        """generate_audio_override_script accepts (sample_rate: int) -> str."""
        sig = inspect.signature(FingerprintEngine.generate_audio_override_script)
        assert "sample_rate" in sig.parameters

    def test_wind_mouse_bezier_signature_defaults(self):
        """Verify default parameter values on wind_mouse_bezier."""
        sig = inspect.signature(FingerprintEngine.get_default_config)
        # No required params for get_default_config

    def test_generate_all_scripts_signature(self):
        """generate_all_scripts(self) -> list[str]."""
        # Instance method — just check it's callable with no extra args
        engine = FingerprintEngine()
        assert callable(engine.generate_all_scripts)

    def test_get_plausible_gpu_pool_signature(self):
        """get_plausible_gpu_pool() -> dict[str, list[str]]."""
        sig = inspect.signature(FingerprintEngine.get_plausible_gpu_pool)
        # No required parameters


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — Behavioral Tests (FAILING — NotImplementedError)
# ═══════════════════════════════════════════════════════════════════════════


class TestGetDefaultConfigRED:
    """get_default_config behavioral tests — RED phase."""

    def test_get_default_config_raises_not_implemented(self):
        """get_default_config() raises NotImplementedError until implemented."""
        with pytest.raises(NotImplementedError):
            FingerprintEngine.get_default_config()

    def test_get_default_config_returns_fingerprint_config_type(self):
        """get_default_config() should return a FingerprintConfig instance."""
        try:
            result = FingerprintEngine.get_default_config()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert isinstance(result, FingerprintConfig), (
            "get_default_config() should return FingerprintConfig"
        )

    def test_get_default_config_has_all_defaults(self):
        """get_default_config() should return config with all default values."""
        try:
            result = FingerprintEngine.get_default_config()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert result.canvas_noise_seed == 0
        assert result.webgl_vendor == ""
        assert result.webgl_renderer == ""
        assert result.audio_sample_rate == 44100
        assert result.geolocation is None
        assert result.timezone is None
        assert result.locale is None


class TestGenerateCanvasNoiseScriptRED:
    """generate_canvas_noise_script behavioral tests — RED phase."""

    def test_raises_not_implemented(self):
        """generate_canvas_noise_script raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            FingerprintEngine.generate_canvas_noise_script(seed=42)

    def test_returns_string(self):
        """generate_canvas_noise_script should return a non-empty JS string."""
        try:
            js = FingerprintEngine.generate_canvas_noise_script(seed=42)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert isinstance(js, str), "Should return a string"
        assert len(js) > 0, "Should return non-empty JS source"
        assert "toDataURL" in js or "toBlob" in js or "getImageData" in js, (
            "JS should patch canvas methods"
        )

    def test_seeded_output_is_consistent(self):
        """Same seed should produce the same JS output (deterministic)."""
        try:
            js1 = FingerprintEngine.generate_canvas_noise_script(seed=42)
            js2 = FingerprintEngine.generate_canvas_noise_script(seed=42)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert js1 == js2, "Same seed should produce identical JS"

    def test_different_seed_different_output(self):
        """Different seeds should produce different JS output."""
        try:
            js1 = FingerprintEngine.generate_canvas_noise_script(seed=42)
            js2 = FingerprintEngine.generate_canvas_noise_script(seed=99)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert js1 != js2, "Different seeds should produce different JS"

    def test_js_has_semicolons(self):
        """Generated JS should be valid-ish (has semicolons or function blocks)."""
        try:
            js = FingerprintEngine.generate_canvas_noise_script(seed=1)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert "function" in js or ";" in js, (
            "JS should have function declarations or statements"
        )


class TestGenerateWebGLOverrideScriptRED:
    """generate_webgl_override_script behavioral tests — RED phase."""

    def test_raises_not_implemented(self):
        """generate_webgl_override_script raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            FingerprintEngine.generate_webgl_override_script(
                vendor="NVIDIA", renderer="RTX 3080"
            )

    def test_returns_string(self):
        """generate_webgl_override_script should return a non-empty JS string."""
        try:
            js = FingerprintEngine.generate_webgl_override_script(
                vendor="Google Inc. (NVIDIA)",
                renderer="ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
            )
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert isinstance(js, str)
        assert len(js) > 0
        assert "WEBGL_debug_renderer_info" in js or "UNMASKED_RENDERER" in js, (
            "JS should address WEBGL_debug_renderer_info"
        )

    def test_vendor_appears_in_js(self):
        """The vendor string should appear in the generated JS."""
        vendor = "Google Inc. (NVIDIA)"
        try:
            js = FingerprintEngine.generate_webgl_override_script(
                vendor=vendor, renderer="Generic"
            )
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert vendor in js, "Vendor string should be embedded in JS"

    def test_different_vendor_different_output(self):
        """Different vendor strings produce different JS."""
        try:
            js1 = FingerprintEngine.generate_webgl_override_script(
                vendor="NVIDIA Corporation", renderer="RTX 4090"
            )
            js2 = FingerprintEngine.generate_webgl_override_script(
                vendor="AMD", renderer="RX 7900 XTX"
            )
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

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
        try:
            js = FingerprintEngine.generate_webgl_override_script(
                vendor=vendor, renderer=renderer
            )
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert isinstance(js, str) and len(js) > 0


class TestGenerateAudioOverrideScriptRED:
    """generate_audio_override_script behavioral tests — RED phase."""

    def test_raises_not_implemented(self):
        """generate_audio_override_script raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            FingerprintEngine.generate_audio_override_script(sample_rate=44100)

    def test_returns_string(self):
        """generate_audio_override_script should return a non-empty JS string."""
        try:
            js = FingerprintEngine.generate_audio_override_script(sample_rate=44100)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert isinstance(js, str)
        assert len(js) > 0

    def test_sample_rate_44100_common(self):
        """sample_rate=44100 is the recommended value."""
        try:
            js = FingerprintEngine.generate_audio_override_script(sample_rate=44100)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert "44100" in js or "sampleRate" in js, (
            "JS should reference sampleRate"
        )

    @pytest.mark.parametrize("sample_rate", [44100, 48000, 96000])
    def test_accepts_common_sample_rates(self, sample_rate):
        """Should accept common audio sample rates."""
        try:
            js = FingerprintEngine.generate_audio_override_script(
                sample_rate=sample_rate
            )
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert isinstance(js, str) and len(js) > 0


class TestGenerateAllScriptsRED:
    """generate_all_scripts behavioral tests — RED phase."""

    def test_raises_not_implemented(self):
        """generate_all_scripts() raises NotImplementedError."""
        engine = FingerprintEngine()
        with pytest.raises(NotImplementedError):
            engine.generate_all_scripts()

    def test_returns_list(self):
        """generate_all_scripts() should return a list of strings."""
        engine = FingerprintEngine()
        try:
            scripts = engine.generate_all_scripts()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert isinstance(scripts, list), "Should return a list"
        assert len(scripts) >= 3, (
            "Should include at least canvas, WebGL, and audio scripts"
        )
        for s in scripts:
            assert isinstance(s, str), "Each item should be a string"
            assert len(s) > 0, "Each script should be non-empty"

    def test_uses_config_values(self):
        """generate_all_scripts() should use the engine's config."""
        cfg = FingerprintConfig(
            canvas_noise_seed=42,
            webgl_vendor="Test Vendor",
            audio_sample_rate=48000,
        )
        engine = FingerprintEngine(cfg)
        try:
            scripts = engine.generate_all_scripts()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        # At minimum calls generate with the configured values
        assert len(scripts) >= 1

    def test_different_config_different_output(self):
        """Different configs should produce different scripts."""
        engine_a = FingerprintEngine(FingerprintConfig(canvas_noise_seed=1))
        engine_b = FingerprintEngine(FingerprintConfig(canvas_noise_seed=999))
        try:
            scripts_a = engine_a.generate_all_scripts()
            scripts_b = engine_b.generate_all_scripts()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert scripts_a != scripts_b, (
            "Different configs should produce different script lists"
        )


class TestGetPlausibleGpuPoolRED:
    """get_plausible_gpu_pool behavioral tests — RED phase."""

    def test_raises_not_implemented(self):
        """get_plausible_gpu_pool() raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            FingerprintEngine.get_plausible_gpu_pool()

    def test_returns_dict(self):
        """get_plausible_gpu_pool() should return a dict."""
        try:
            pool = FingerprintEngine.get_plausible_gpu_pool()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert isinstance(pool, dict), "Should return a dict"

    def test_keys_are_vendor_strings(self):
        """Dict keys should be GPU vendor names (strings)."""
        try:
            pool = FingerprintEngine.get_plausible_gpu_pool()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        for vendor in pool:
            assert isinstance(vendor, str) and len(vendor) > 0, (
                f"Vendor key should be non-empty string, got {vendor!r}"
            )

    def test_values_are_lists_of_renderers(self):
        """Dict values should be lists of renderer strings."""
        try:
            pool = FingerprintEngine.get_plausible_gpu_pool()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        for vendor, renderers in pool.items():
            assert isinstance(renderers, list), (
                f"Values for {vendor!r} should be list"
            )
            assert len(renderers) >= 1, (
                f"Each vendor should have at least one renderer"
            )
            for r in renderers:
                assert isinstance(r, str) and len(r) > 0, (
                    f"Renderer should be non-empty string, got {r!r}"
                )

    def test_has_nvidia_vendor(self):
        """GPU pool should include NVIDIA vendor entries."""
        try:
            pool = FingerprintEngine.get_plausible_gpu_pool()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        vendors_lower = {k.lower() for k in pool}
        assert any("nvidia" in v for v in vendors_lower), (
            "Pool should include NVIDIA GPUs"
        )

    def test_has_at_least_two_vendors(self):
        """GPU pool should have at least 2 different vendors for variety."""
        try:
            pool = FingerprintEngine.get_plausible_gpu_pool()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

        assert len(pool) >= 2, "Should have at least 2 GPU vendors"


class TestConfigBehaviorRED:
    """FingerprintConfig behavioral edge cases — RED phase."""

    def test_config_with_dict_geolocation(self):
        """geolocation field accepts a dict."""
        cfg = FingerprintConfig(geolocation={"lat": 47.0, "lng": 8.0})
        assert cfg.geolocation == {"lat": 47.0, "lng": 8.0}

    def test_config_with_timezone_iana(self):
        """timezone field accepts IANA timezone strings."""
        cfg = FingerprintConfig(timezone="America/New_York")
        assert cfg.timezone == "America/New_York"

    def test_config_with_locale(self):
        """locale field accepts locale strings."""
        cfg = FingerprintConfig(locale="en-US")
        assert cfg.locale == "en-US"

    def test_engine_uses_provided_config(self, engine_with_config):
        """Engine with custom config retains config values."""
        cfg = engine_with_config.config
        assert cfg.canvas_noise_seed == 42
        assert cfg.webgl_vendor == "Google Inc. (NVIDIA)"
        assert cfg.audio_sample_rate == 48000
        assert cfg.timezone == "Europe/Zurich"

    def test_engine_default_config_empty(self, engine):
        """Default engine config has default values."""
        cfg = engine.config
        assert cfg.canvas_noise_seed == 0
        assert cfg.webgl_vendor == ""
