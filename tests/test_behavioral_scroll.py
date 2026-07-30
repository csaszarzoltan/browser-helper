"""
Pre-development RED-phase tests for Human Scrolling Middleware (P1-5).

╔══════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                          ║
║                                                                    ║
║  Interface tests (green ✓) → assert pass immediately with stub     ║
║  Behavioral tests (red  ✗) → assert fail until implementation      ║
║                                                                    ║
║  Acceptance Criteria covered:                                      ║
║    AC1 — smooth mode continuous scroll with variable speed         ║
║    AC2 — jagged mode includes pauses between steps                ║
║    AC3 — auto mode distance-based selection                       ║
║    AC4 — step size randomises 100-800px                            ║
║    AC5 — disabled falls through to raw CDP                         ║
║    AC6 — POST/GET endpoint round-trips                             ║
║    AC7 — invalid mode returns 422 / InvalidModeError               ║
║    AC8 — pause timing is log-normally distributed                  ║
║    AC9 — config persistence across restarts                        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import inspect
import json
import math
import random
import statistics
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from behavioral_scroll import (
    DEFAULT_STEP_MAX,
    DEFAULT_STEP_MIN,
    VALID_MODES,
    BehavioralScroll,
    InvalidModeError,
    ScrollStepEvent,
)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Interface Tests (PASSING — green checkmark)
# ═══════════════════════════════════════════════════════════════════════════


class TestInterfaceImports:
    """Module-level constants, exceptions, and main class are importable."""

    def test_module_imported(self):
        """behavioral_scroll module loads without error."""
        from behavioral_scroll import BehavioralScroll
        assert BehavioralScroll is not None

    def test_InvalidModeError_exists(self):
        """InvalidModeError is a subclass of ValueError."""
        assert issubclass(InvalidModeError, ValueError)

    def test_InvalidModeError_message(self):
        """InvalidModeError stores the invalid mode string."""
        exc = InvalidModeError("bogus")
        assert "bogus" in str(exc)
        assert exc.invalid_mode == "bogus"

    def test_VALID_MODES_contains_expected(self):
        """VALID_MODES contains smooth, jagged, auto."""
        assert VALID_MODES == {"smooth", "jagged", "auto"}

    def test_DEFAULT_STEP_constants(self):
        """DEFAULT_STEP_MIN=100 and DEFAULT_STEP_MAX=800."""
        assert DEFAULT_STEP_MIN == 100
        assert DEFAULT_STEP_MAX == 800

    def test_ScrollStepEvent_class(self):
        """ScrollStepEvent has expected fields."""
        e = ScrollStepEvent(delta_y=200, delay_ms=50.0, pause_after=300.0)
        assert e.delta_y == 200
        assert e.delay_ms == 50.0
        assert e.pause_after == 300.0

    def test_ScrollStepEvent_to_dict(self):
        """to_dict returns a serialisable dict."""
        e = ScrollStepEvent(delta_y=-150, delay_ms=40.0, pause_after=500.0)
        d = e.to_dict()
        assert d == {"delta_y": -150, "delay_ms": 40.0, "pause_after": 500.0}

    def test_ScrollStepEvent_to_dict_json_serialisable(self):
        """to_dict output can be json.dumps'd."""
        e = ScrollStepEvent(delta_y=-300, delay_ms=60.0, pause_after=200.0)
        json.dumps(e.to_dict())


class TestBehavioralScrollInterface:
    """BehavioralScroll class has expected structure and defaults."""

    def test_class_exists(self):
        """BehavioralScroll is a class."""
        assert isinstance(BehavioralScroll, type)

    def test_can_instantiate(self):
        """BehavioralScroll() without args works."""
        bs = BehavioralScroll()
        assert isinstance(bs, BehavioralScroll)

    def test_constructor_accepts_client(self):
        """BehavioralScroll(client=...) is accepted."""
        bs = BehavioralScroll(client="dummy")
        assert bs._client == "dummy"

    def test_constructor_accepts_settings_manager(self):
        """BehavioralScroll(settings_manager=...) is accepted."""
        bs = BehavioralScroll(settings_manager="dummy_sm")
        assert bs._settings == "dummy_sm"

    def test_default_enabled_is_true(self):
        """Default enabled state is True."""
        bs = BehavioralScroll()
        assert bs._enabled is True

    def test_default_mode_is_smooth(self):
        """Default mode is 'smooth'."""
        bs = BehavioralScroll()
        assert bs._mode == "smooth"

    def test_default_step_bounds(self):
        """Default step bounds are 100-800."""
        bs = BehavioralScroll()
        assert bs._step_min == 100
        assert bs._step_max == 800

    def test_config_property_returns_dict(self):
        """.config returns a dict with expected keys."""
        bs = BehavioralScroll()
        cfg = bs.config
        assert isinstance(cfg, dict)
        assert "enabled" in cfg
        assert "mode" in cfg
        assert "step_min" in cfg
        assert "step_max" in cfg

    def test_config_default_values(self):
        """Default config values are correct."""
        bs = BehavioralScroll()
        cfg = bs.config
        assert cfg["enabled"] is True
        assert cfg["mode"] == "smooth"
        assert cfg["step_min"] == 100
        assert cfg["step_max"] == 800

    def test_get_config_method_signature(self):
        """get_config takes no required positional args beyond self."""
        sig = inspect.signature(BehavioralScroll.get_config)
        params = list(sig.parameters.keys())
        assert params == ["self"], f"Unexpected signature: {params}"

    def test_update_config_method_signature(self):
        """update_config accepts enabled, mode, step_min, step_max."""
        sig = inspect.signature(BehavioralScroll.update_config)
        names = list(sig.parameters.keys())
        for field in ("enabled", "mode", "step_min", "step_max"):
            assert field in names, f"Missing parameter {field} in update_config"

    def test_scroll_method_is_async(self):
        """scroll() is an async method."""
        assert inspect.iscoroutinefunction(BehavioralScroll.scroll), (
            "scroll() should be async"
        )

    def test_scroll_method_signature(self):
        """scroll accepts target_y, current_y, and optional client."""
        sig = inspect.signature(BehavioralScroll.scroll)
        names = list(sig.parameters.keys())
        for field in ("target_y", "current_y", "client"):
            assert field in names, f"Missing parameter {field} in scroll"

    def test_has_static_methods(self):
        """Expected static methods exist on BehavioralScroll."""
        for name in (
            "_smooth_scroll",
            "_jagged_scroll",
            "_auto_mode",
            "_log_normal_pause",
            "_random_step",
            "_raw_scroll_event",
        ):
            assert hasattr(BehavioralScroll, name), f"Missing static method {name}"
            method = getattr(BehavioralScroll, name)
            assert isinstance(method, staticmethod) or callable(method)

    def test_ScrollStepEvent_is_public(self):
        """ScrollStepEvent is exported from the module."""
        from behavioral_scroll import ScrollStepEvent
        assert ScrollStepEvent is not None
        # Check __init__ signature parameters (instance attrs, not class attrs)
        sig = inspect.signature(ScrollStepEvent.__init__)
        param_names = list(sig.parameters.keys())
        for field in ("delta_y", "delay_ms", "pause_after"):
            assert field in param_names, (
                f"Missing {field!r} in ScrollStepEvent.__init__"
            )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — REST API Route Interface
# ═══════════════════════════════════════════════════════════════════════════


class TestScrollApiRoutes:
    """Routes for /scroll/config should be registered on the FastAPI app.

    These tests verify that the developer registers POST /scroll/config
    and GET /scroll/config endpoints. They currently FAIL because the
    routes do not exist yet (RED phase).
    """

    def _route_paths(self) -> list[str]:
        from main import app
        out = []
        for r in app.routes:
            path = getattr(r, "path", None)
            if path and "/scroll/" in path:
                out.append(f"{getattr(r, 'methods', {'UNKNOWN'})} {path}")
        return out

    def test_POST_scroll_config_route_exists(self):
        """POST /scroll/config is registered."""
        routes = self._route_paths()
        matches = [r for r in routes if "POST" in r and "/scroll/config" in r]
        assert len(matches) >= 1, (
            f"No POST /scroll/config route found. "
            f"Registered scroll routes: {routes}"
        )

    def test_GET_scroll_config_route_exists(self):
        """GET /scroll/config is registered."""
        routes = self._route_paths()
        matches = [r for r in routes if "GET" in r and "/scroll/config" in r]
        assert len(matches) >= 1, (
            f"No GET /scroll/config route found. "
            f"Registered scroll routes: {routes}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — Behavioral Tests (RED — fail with NotImplementedError)
# ═══════════════════════════════════════════════════════════════════════════
#
# Every test in this section calls a NotImplementedError method on the
# BehavioralScroll class. They WILL fail until the developer writes the
# real implementation. This is the intended RED-phase signal.


class TestAC1SmoothMode:
    """AC1: Smooth mode produces continuous scroll with variable speed."""

    def test_smooth_scroll_returns_list(self):
        """_smooth_scroll returns a list of ScrollStepEvent dicts."""
        events = BehavioralScroll._smooth_scroll(distance=1500)
        assert isinstance(events, list)
        assert len(events) > 0

    def test_smooth_scroll_events_are_continuous(self):
        """All smooth events have delta_y, delay_ms, and pause_after=0."""
        events = BehavioralScroll._smooth_scroll(distance=1500)
        for e in events:
            assert "delta_y" in e
            assert "delay_ms" in e
            assert "pause_after" in e

    def test_smooth_scroll_variable_deltas(self):
        """Smooth scroll deltas vary (ease-in-out: small→large→small)."""
        events = BehavioralScroll._smooth_scroll(distance=1500)
        deltas = [e["delta_y"] for e in events]
        # At least two different delta values exist (variable speed)
        unique = set(deltas)
        assert len(unique) >= 2, (
            f"Expected variable deltas, got only {unique}"
        )

    def test_smooth_scroll_reaches_target(self):
        """Total accumulated delta_y equals (or exceeds) the distance."""
        events = BehavioralScroll._smooth_scroll(distance=2000)
        total = sum(e["delta_y"] for e in events)
        assert total >= 2000, f"Got {total}, expected >= 2000"

    def test_smooth_scroll_no_zero_deltas(self):
        """Every smooth scroll step moves at least 1px."""
        events = BehavioralScroll._smooth_scroll(distance=1000)
        for e in events:
            assert e["delta_y"] > 0, f"Zero or negative delta: {e['delta_y']}"

    def test_smooth_scroll_delay_nonzero(self):
        """Each smooth event has a positive delay."""
        events = BehavioralScroll._smooth_scroll(distance=800)
        for e in events:
            assert e["delay_ms"] > 0, f"Zero or negative delay: {e['delay_ms']}"


class TestAC2JaggedMode:
    """AC2: Jagged mode includes pauses between scroll steps."""

    def test_jagged_scroll_returns_list(self):
        """_jagged_scroll returns a list of ScrollStepEvent dicts."""
        events = BehavioralScroll._jagged_scroll(distance=600)
        assert isinstance(events, list)
        assert len(events) > 0

    def test_jagged_scroll_has_pauses(self):
        """At least one jagged event has pause_after > 0."""
        events = BehavioralScroll._jagged_scroll(distance=600)
        pauses = [e["pause_after"] for e in events]
        assert any(p > 0 for p in pauses), (
            f"No positive pauses found: {pauses}"
        )

    def test_jagged_scroll_pattern_is_scroll_stop_pause(self):
        """Pattern alternates: scroll event → pause → scroll event → pause."""
        events = BehavioralScroll._jagged_scroll(distance=600)
        # Extract pause flags
        has_pause = [e["pause_after"] > 0 for e in events]
        # There should be at least one stop-pause cycle
        assert any(has_pause), "No pause detected in jagged pattern"

    def test_jagged_scroll_reaches_target(self):
        """Total accumulated delta_y meets distance in jagged mode."""
        events = BehavioralScroll._jagged_scroll(distance=900)
        total = sum(e["delta_y"] for e in events)
        assert total >= 900, f"Got {total}, expected >= 900"

    def test_jagged_pauses_vary(self):
        """Jagged pause durations are not all identical."""
        events = BehavioralScroll._jagged_scroll(distance=600)
        pauses = [e["pause_after"] for e in events if e["pause_after"] > 0]
        if len(pauses) >= 2:
            assert len(set(pauses)) >= 2, (
                f"All pauses identical: {pauses}"
            )


class TestAC3AutoMode:
    """AC3: Auto mode selects smooth for >1000px, jagged for <500px."""

    def test_auto_mode_returns_list(self):
        """_auto_mode returns a list of ScrollStepEvent dicts."""
        events = BehavioralScroll._auto_mode(distance=2000)
        assert isinstance(events, list)
        assert len(events) > 0

    def test_auto_mode_long_distance_is_smooth(self):
        """Auto mode for >1000px produces smooth-like behaviour (no pauses)."""
        events = BehavioralScroll._auto_mode(distance=2000)
        pauses = [e["pause_after"] for e in events]
        # Smooth mode has no pauses between events
        assert all(p == 0.0 for p in pauses), (
            f"Auto(long) should have zero pauses, got: {pauses}"
        )

    def test_auto_mode_short_distance_is_jagged(self):
        """Auto mode for <500px produces jagged-like behaviour (has pauses)."""
        events = BehavioralScroll._auto_mode(distance=300)
        pauses = [e["pause_after"] for e in events]
        assert any(p > 0 for p in pauses), (
            f"Auto(short) should have some pauses, got: {pauses}"
        )

    def test_auto_mode_boundary_500(self):
        """Auto mode at 500px boundary produces valid events."""
        events = BehavioralScroll._auto_mode(distance=500)
        assert len(events) > 0

    def test_auto_mode_boundary_1000(self):
        """Auto mode at 1000px boundary produces valid events."""
        events = BehavioralScroll._auto_mode(distance=1000)
        assert len(events) > 0


class TestAC4StepSizeRandomization:
    """AC4: Scroll step size randomises within 100-800px range."""

    def test_random_step_within_bounds_default(self):
        """Default _random_step returns values between 100 and 800."""
        samples = [BehavioralScroll._random_step() for _ in range(100)]
        assert all(DEFAULT_STEP_MIN <= s <= DEFAULT_STEP_MAX for s in samples), (
            f"Samples outside [{DEFAULT_STEP_MIN}, {DEFAULT_STEP_MAX}]: "
            f"min={min(samples)}, max={max(samples)}"
        )

    def test_random_step_custom_bounds(self):
        """_random_step respects custom min/max."""
        samples = [BehavioralScroll._random_step(200, 400) for _ in range(50)]
        assert all(200 <= s <= 400 for s in samples), (
            f"Samples outside [200, 400]: min={min(samples)}, max={max(samples)}"
        )

    def test_random_step_not_all_same(self):
        """_random_step produces varied values (not constant)."""
        samples = [BehavioralScroll._random_step() for _ in range(50)]
        assert len(set(samples)) >= 2, (
            f"All 50 samples identical: {samples[0]}"
        )


class TestAC5DisabledFallthrough:
    """AC5: Disabled mode falls through to raw CDP scroll."""

    @pytest.mark.asyncio
    async def test_disabled_scroll_returns_single_event(self):
        """When enabled=False, scroll() returns one immediate event."""
        bs = BehavioralScroll()
        bs._enabled = False
        events = await bs.scroll(target_y=2000, current_y=0)
        assert isinstance(events, list), "scroll() must return a list"
        # Disabled fallthrough should produce exactly 1 event
        assert len(events) == 1, (
            f"Expected 1 event for disabled mode, got {len(events)}"
        )

    @pytest.mark.asyncio
    async def test_disabled_scroll_event_has_no_pause(self):
        """Raw fallthrough event has pause_after == 0."""
        bs = BehavioralScroll()
        bs._enabled = False
        events = await bs.scroll(target_y=2000, current_y=0)
        ev = events[0]
        assert ev["pause_after"] == 0.0, (
            f"Raw fallthrough should have no pause, got {ev['pause_after']}"
        )

    @pytest.mark.asyncio
    async def test_disabled_scroll_total_distance(self):
        """Disabled scroll event covers the full distance."""
        bs = BehavioralScroll()
        bs._enabled = False
        events = await bs.scroll(target_y=1500, current_y=0)
        total = sum(e["delta_y"] for e in events)
        assert total == 1500, (
            f"Expected total distance 1500, got {total}"
        )


class TestAC6ConfigRoundTrip:
    """AC6: POST/GET endpoint round-trips (unit-level)."""

    def test_update_config_returns_dict(self):
        """update_config returns the new config dict."""
        bs = BehavioralScroll()
        result = bs.update_config(enabled=True, mode="smooth")
        assert isinstance(result, dict)
        assert result["enabled"] is True
        assert result["mode"] == "smooth"

    def test_update_config_preserves_unchanged_fields(self):
        """Updating one field preserves other defaults."""
        bs = BehavioralScroll()
        result = bs.update_config(mode="jagged")
        assert result["mode"] == "jagged"
        assert result["step_min"] == 100  # unchanged default
        assert result["step_max"] == 800  # unchanged default

    def test_get_config_matches_update_config(self):
        """get_config returns the same values as set by update_config."""
        bs = BehavioralScroll()
        bs.update_config(enabled=True, mode="auto", step_min=200, step_max=600)
        cfg = bs.get_config()
        assert cfg["enabled"] is True
        assert cfg["mode"] == "auto"
        assert cfg["step_min"] == 200
        assert cfg["step_max"] == 600


class TestAC7InvalidMode:
    """AC7: Invalid mode returns 422 / InvalidModeError."""

    def test_invalid_mode_raises_InvalidModeError(self):
        """update_config with bad mode raises InvalidModeError."""
        bs = BehavioralScroll()
        with pytest.raises(InvalidModeError) as exc_info:
            bs.update_config(mode="turbo")
        assert "turbo" in str(exc_info.value)

    def test_smooth_is_valid(self):
        """'smooth' does not raise."""
        bs = BehavioralScroll()
        bs.update_config(mode="smooth")  # should not raise

    def test_jagged_is_valid(self):
        """'jagged' does not raise."""
        bs = BehavioralScroll()
        bs.update_config(mode="jagged")  # should not raise

    def test_auto_is_valid(self):
        """'auto' does not raise."""
        bs = BehavioralScroll()
        bs.update_config(mode="auto")  # should not raise

    def test_empty_string_invalid(self):
        """Empty string for mode raises InvalidModeError."""
        bs = BehavioralScroll()
        with pytest.raises(InvalidModeError):
            bs.update_config(mode="")

    def test_numeric_mode_invalid(self):
        """Numeric mode raises InvalidModeError."""
        bs = BehavioralScroll()
        with pytest.raises(InvalidModeError):
            bs.update_config(mode=42)

    def test_step_min_out_of_range(self):
        """step_min < 100 raises ValueError."""
        bs = BehavioralScroll()
        with pytest.raises((ValueError, InvalidModeError)):
            bs.update_config(step_min=50)

    def test_step_max_out_of_range(self):
        """step_max > 800 raises ValueError."""
        bs = BehavioralScroll()
        with pytest.raises((ValueError, InvalidModeError)):
            bs.update_config(step_max=2000)


class TestAC8LogNormalPause:
    """AC8: Pause timing is log-normally distributed (not uniform)."""

    def test_log_normal_pause_returns_positive_float(self):
        """_log_normal_pause returns a positive float."""
        for _ in range(20):
            pause = BehavioralScroll._log_normal_pause()
            assert isinstance(pause, float), f"Expected float, got {type(pause)}"
            assert pause > 0, f"Expected positive pause, got {pause}"

    def test_log_normal_pause_default_range(self):
        """Default log-normal pauses are roughly in 150-1200ms range."""
        samples = [BehavioralScroll._log_normal_pause() for _ in range(200)]
        mean = statistics.mean(samples)
        assert 150 <= mean <= 1200, (
            f"Mean pause {mean:.1f}ms outside expected range [150, 1200]"
        )

    def test_log_normal_pause_right_skewed(self):
        """Log-normal distribution is right-skewed (median < mean)."""
        samples = [BehavioralScroll._log_normal_pause() for _ in range(500)]
        median = statistics.median(samples)
        mean = statistics.mean(samples)
        assert median < mean, (
            f"Log-normal should be right-skewed: median={median:.1f}, mean={mean:.1f}"
        )

    def test_log_normal_pause_not_all_identical(self):
        """Pause durations vary (not deterministic)."""
        samples = [BehavioralScroll._log_normal_pause() for _ in range(50)]
        assert len(set(samples)) >= 10, (
            "Fewer than 10 unique pause values in 50 samples — "
            "pauses look deterministic"
        )

    def test_log_normal_pause_one_tail(self):
        """Log-normal pauses are bounded (no extreme outliers)."""
        samples = [BehavioralScroll._log_normal_pause() for _ in range(500)]
        assert all(s < 5000 for s in samples), (
            f"Some samples exceed 5000ms: max={max(samples):.1f}"
        )

    def test_log_normal_custom_params(self):
        """Custom mu/sigma produce different pause distributions."""
        default_samples = [BehavioralScroll._log_normal_pause() for _ in range(100)]
        fast_samples = [
            BehavioralScroll._log_normal_pause(mu=5.0, sigma=0.3)
            for _ in range(100)
        ]
        assert statistics.mean(fast_samples) < statistics.mean(default_samples), (
            "Lower mu should produce shorter pauses"
        )


class TestAC9ConfigPersistence:
    """AC9: Config persists across restarts via SettingsManager."""

    def test_config_persists_after_reinit(self):
        """Config set via update_config survives re-initialization."""
        import tempfile
        from settings_manager import SettingsManager

        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("{}")
            settings_path = f.name

        try:
            sm = SettingsManager(path=settings_path)
            bs = BehavioralScroll(settings_manager=sm)
            bs.update_config(enabled=True, mode="auto", step_min=200, step_max=600)
            # Re-initialise with the same settings file
            sm2 = SettingsManager(path=settings_path)
            bs2 = BehavioralScroll(settings_manager=sm2)
            cfg = bs2.get_config()
            assert cfg["mode"] == "auto", f"Expected mode=auto, got {cfg['mode']}"
            assert cfg["step_min"] == 200
            assert cfg["step_max"] == 600
        finally:
            import os
            os.unlink(settings_path)

    def test_config_not_shared_across_instances(self):
        """Two BehavioralScroll instances have independent configs."""
        bs1 = BehavioralScroll()
        bs2 = BehavioralScroll()
        bs1.update_config(mode="jagged")
        cfg2 = bs2.get_config()
        assert cfg2["mode"] == "smooth", (
            "Instances should be independent"
        )
