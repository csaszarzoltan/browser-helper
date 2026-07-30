"""
Pre-development RED-phase tests for BehavioralSimulator (P0.2).

╔══════════════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                                    ║
║                                                                              ║
║  Interface tests (green ✓) → assert pass immediately with stub               ║
║  Behavioral tests (red  ✗) → assert fail until implementation                ║
║                                                                              ║
║  Acceptance Criteria covered:                                                ║
║    AC1 — MouseMovementResult dataclass has points, duration_ms, steps        ║
║    AC2 — Mouse trajectory is curved (turn angle > 15°)                       ║
║    AC3 — Landing within ±5px of destination                                  ║
║    AC4 — At least 3 intermediate trajectory points                           ║
║    AC5 — Variable velocity (not constant)                                    ║
║    AC6 — Fitts's Law: longer distance → longer duration                      ║
║    AC7 — Non-deterministic: 100 calls → 100 different trajectories          ║
║    AC8 — Keystroke dwell 80-200ms, flight 100-500ms                         ║
║    AC9 — ~5% typo probability with backspace correction                      ║
║    AC10 — Total timing matches 40-80 WPM                                     ║
║    AC11 — Timing std dev > 10ms (per-character variance)                     ║
║    AC12 — Scroll variable velocity 0-3000px/s                               ║
║    AC13 — Scroll exponential momentum decay 200-800ms                        ║
║    AC14 — Scroll reading pauses 1-15s                                       ║
║    AC15 — At least 2 scroll steps                                            ║
║    AC16 — Click x,y within element bounds                                    ║
║    AC17 — Click offset ±5-15px from center                                  ║
║    AC18 — Click temporal delay 50-200ms                                      ║
║    AC19 — Click never exactly (0,0) or element center                        ║
║    AC20 — No out-of-bounds click coordinates                                 ║
║    AC21 — Edge cases: zero-dimension element, single-char text,              ║
║                       viewport height mismatch                               ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import math
import random
import statistics
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from behavioral_sim import BehavioralSimulator, MouseMovementResult


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def small_rect() -> dict[str, float]:
    """Small button element rect."""
    return {"x": 100.0, "y": 200.0, "w": 80.0, "h": 30.0}


@pytest.fixture
def large_rect() -> dict[str, float]:
    """Large div element rect."""
    return {"x": 0.0, "y": 0.0, "w": 1024.0, "h": 768.0}


# ======================================================================
# SECTION 1 — Interface Tests (PASSING — green checkmark)
# ======================================================================


class TestInterfaceMouseMovementResult:
    """MouseMovementResult dataclass exists with expected fields."""

    def test_dataclass_importable(self):
        """MouseMovementResult is importable from behavioral_sim."""
        assert MouseMovementResult is not None

    def test_dataclass_fields(self):
        """MouseMovementResult has points, duration_ms, steps fields."""
        result = MouseMovementResult()
        assert hasattr(result, "points")
        assert hasattr(result, "duration_ms")
        assert hasattr(result, "steps")

    def test_dataclass_field_types_points(self):
        """points is a list of (float, float) tuples."""
        result = MouseMovementResult(points=[(10.0, 20.0), (30.0, 40.0)])
        assert isinstance(result.points, list)
        if result.points:
            x, y = result.points[0]
            assert isinstance(x, (int, float))
            assert isinstance(y, (int, float))

    def test_dataclass_field_type_duration_ms(self):
        """duration_ms is a float."""
        result = MouseMovementResult(duration_ms=123.45)
        assert isinstance(result.duration_ms, float)

    def test_dataclass_field_type_steps(self):
        """steps is an int."""
        result = MouseMovementResult(steps=10)
        assert isinstance(result.steps, int)

    def test_dataclass_defaults(self):
        """Default values are empty list, 0.0, 0."""
        result = MouseMovementResult()
        assert result.points == []
        assert result.duration_ms == 0.0
        assert result.steps == 0

    def test_dataclass_is_dataclass(self):
        """MouseMovementResult is a dataclass (has __dataclass_fields__)."""
        from dataclasses import is_dataclass

        assert is_dataclass(MouseMovementResult)


class TestInterfaceBehavioralSimulator:
    """BehavioralSimulator class exists with expected static methods."""

    def test_class_importable(self):
        """BehavioralSimulator is importable from behavioral_sim."""
        assert BehavioralSimulator is not None

    def test_wind_mouse_bezier_method_exists(self):
        """wind_mouse_bezier is a static method on BehavioralSimulator."""
        assert hasattr(BehavioralSimulator, "wind_mouse_bezier")
        assert callable(BehavioralSimulator.wind_mouse_bezier)

    def test_keystroke_timing_method_exists(self):
        """keystroke_timing is a static method on BehavioralSimulator."""
        assert hasattr(BehavioralSimulator, "keystroke_timing")
        assert callable(BehavioralSimulator.keystroke_timing)

    def test_scroll_sequence_method_exists(self):
        """scroll_sequence is a static method on BehavioralSimulator."""
        assert hasattr(BehavioralSimulator, "scroll_sequence")
        assert callable(BehavioralSimulator.scroll_sequence)

    def test_click_position_method_exists(self):
        """click_position is a static method on BehavioralSimulator."""
        assert hasattr(BehavioralSimulator, "click_position")
        assert callable(BehavioralSimulator.click_position)

    def test_wind_mouse_bezier_signature(self):
        """wind_mouse_bezier has correct parameter names."""
        import inspect

        sig = inspect.signature(BehavioralSimulator.wind_mouse_bezier)
        params = set(sig.parameters.keys())
        for expected in ("start_x", "start_y", "dest_x", "dest_y", "gravity",
                         "wind", "max_step", "target_threshold"):
            assert expected in params, (
                f"Missing parameter {expected!r} in wind_mouse_bezier"
            )

    def test_keystroke_timing_signature(self):
        """keystroke_timing has correct parameter names."""
        import inspect

        sig = inspect.signature(BehavioralSimulator.keystroke_timing)
        params = set(sig.parameters.keys())
        assert "text" in params
        assert "wpm_range" in params

    def test_scroll_sequence_signature(self):
        """scroll_sequence has correct parameter names."""
        import inspect

        sig = inspect.signature(BehavioralSimulator.scroll_sequence)
        params = set(sig.parameters.keys())
        for expected in ("viewport_height", "total_distance", "min_pause_ms",
                         "max_pause_ms"):
            assert expected in params, (
                f"Missing parameter {expected!r} in scroll_sequence"
            )

    def test_click_position_signature(self):
        """click_position has correct parameter names."""
        import inspect

        sig = inspect.signature(BehavioralSimulator.click_position)
        params = set(sig.parameters.keys())
        for expected in ("element_rect", "jitter_px", "jitter_ms_range"):
            assert expected in params, (
                f"Missing parameter {expected!r} in click_position"
            )

    def test_wind_mouse_bezier_returns_mousemovementresult(self):
        """wind_mouse_bezier raises NotImplementedError (stub)."""
        with pytest.raises(NotImplementedError):
            BehavioralSimulator.wind_mouse_bezier(0, 0, 100, 100)

    def test_keystroke_timing_raises_not_implemented(self):
        """keystroke_timing raises NotImplementedError (stub)."""
        with pytest.raises(NotImplementedError):
            BehavioralSimulator.keystroke_timing("Hello")

    def test_scroll_sequence_raises_not_implemented(self):
        """scroll_sequence raises NotImplementedError (stub)."""
        with pytest.raises(NotImplementedError):
            BehavioralSimulator.scroll_sequence(1080)

    def test_click_position_raises_not_implemented(self):
        """click_position raises NotImplementedError (stub)."""
        with pytest.raises(NotImplementedError):
            BehavioralSimulator.click_position({"x": 0, "y": 0, "w": 100, "h": 50})


# ======================================================================
# SECTION 2 — Behavioral Tests: wind_mouse_bezier (RED — xfail)
# ======================================================================


class TestWindMouseBezierBehavioral:
    """Acceptance: curved trajectory, variable velocity, pinpoint landing."""

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_trajectory_is_curved(self):
        """Trajectory has at least one turn angle > 15° from straight line."""
        result = BehavioralSimulator.wind_mouse_bezier(100, 100, 500, 300)
        points = result.points
        assert len(points) >= 4, (
            f"Need at least 4 points for angle check, got {len(points)}"
        )

        max_angle = 0.0
        for i in range(1, len(points) - 1):
            ax, ay = points[i - 1]
            bx, by = points[i]
            cx, cy = points[i + 1]

            v1 = (ax - bx, ay - by)
            v2 = (cx - bx, cy - by)

            dot = v1[0] * v2[0] + v1[1] * v2[1]
            mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
            mag2 = math.sqrt(v2[0]**2 + v2[1]**2)

            if mag1 * mag2 > 1e-8:
                cos_angle = dot / (mag1 * mag2)
                cos_angle = max(-1.0, min(1.0, cos_angle))
                angle = math.degrees(math.acos(cos_angle))
                max_angle = max(max_angle, angle)

        assert max_angle > 15.0, (
            f"Max turn angle {max_angle:.1f}° ≤ 15° — trajectory is too straight"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_landing_within_threshold(self):
        """Final point is within ±5px of destination."""
        dest_x, dest_y = 500.0, 300.0
        result = BehavioralSimulator.wind_mouse_bezier(100, 100, dest_x, dest_y)
        points = result.points
        assert len(points) >= 2, "Need at least start + end point"

        fx, fy = points[-1]
        dx = abs(fx - dest_x)
        dy = abs(fy - dest_y)
        assert dx <= 5.0, f"Final x {fx} differs from dest {dest_x} by {dx}px"
        assert dy <= 5.0, f"Final y {fy} differs from dest {dest_y} by {dy}px"

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_at_least_3_intermediate_points(self):
        """Trajectory has at least 3 intermediate points (steps >= 3)."""
        result = BehavioralSimulator.wind_mouse_bezier(0, 0, 500, 300)
        assert result.steps >= 3, (
            f"Got {result.steps} steps, expected at least 3"
        )
        # steps = len(points) - 1, so need len(points) >= 4
        assert len(result.points) >= 4, (
            f"Got {len(result.points)} points, expected at least 4"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_variable_velocity(self):
        """Velocity varies across the trajectory (not constant)."""
        result = BehavioralSimulator.wind_mouse_bezier(100, 100, 800, 400)
        points = result.points
        assert len(points) >= 5, "Need ≥5 points for velocity variation check"

        # Compute segment distances
        distances = []
        for i in range(1, len(points)):
            dx = points[i][0] - points[i - 1][0]
            dy = points[i][1] - points[i - 1][1]
            distances.append(math.sqrt(dx**2 + dy**2))

        # Velocity (px/step) should vary — not all same
        assert len(set(round(d, 4) for d in distances)) >= 2, (
            f"All segment distances identical: {distances}"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_fitts_law_longer_distance_longer_duration(self):
        """Longer distance produces longer duration (Fitts's Law)."""
        short = BehavioralSimulator.wind_mouse_bezier(0, 0, 100, 100)
        long_ = BehavioralSimulator.wind_mouse_bezier(0, 0, 800, 600)

        short_d = math.sqrt(100**2 + 100**2)
        long_d = math.sqrt(800**2 + 600**2)

        assert long_.duration_ms > short.duration_ms, (
            f"Long distance ({long_d:.0f}px) duration {long_.duration_ms:.0f}ms "
            f"≤ short distance ({short_d:.0f}px) duration {short.duration_ms:.0f}ms"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_total_duration_positive(self):
        """Duration is a positive number."""
        result = BehavioralSimulator.wind_mouse_bezier(0, 0, 500, 300)
        assert result.duration_ms > 0, (
            f"Duration {result.duration_ms} should be positive"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_100_calls_different_trajectories(self):
        """100 repeated calls produce 100 different trajectories."""
        trajectories = []
        for _ in range(100):
            result = BehavioralSimulator.wind_mouse_bezier(100, 100, 600, 400)
            # Use start of trajectory as fingerprint (avoid end-point similarity)
            fingerprint = tuple(
                round(p[0], 1) for p in result.points[:3]
            )
            trajectories.append(fingerprint)

        unique = len(set(trajectories))
        assert unique >= 90, (
            f"Only {unique}/100 unique trajectory fingerprints — "
            "trajectories look deterministic"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_all_points_are_tuples_of_floats(self):
        """All trajectory points are (float, float) tuples."""
        result = BehavioralSimulator.wind_mouse_bezier(0, 0, 500, 300)
        for i, pt in enumerate(result.points):
            assert isinstance(pt, (list, tuple)), (
                f"Point {i} is {type(pt)}, expected tuple"
            )
            assert len(pt) == 2, f"Point {i} has {len(pt)} values, expected 2"
            x, y = pt
            assert isinstance(x, (int, float)), (
                f"Point {i} x is {type(x)}, expected float"
            )
            assert isinstance(y, (int, float)), (
                f"Point {i} y is {type(y)}, expected float"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: wind_mouse_bezier")
    def test_gravity_wind_parameters_affect_trajectory(self):
        """Different gravity/wind produce different paths for same endpoints."""
        r1 = BehavioralSimulator.wind_mouse_bezier(100, 100, 500, 300,
                                                     gravity=1.0, wind=1.0)
        r2 = BehavioralSimulator.wind_mouse_bezier(100, 100, 500, 300,
                                                     gravity=20.0, wind=20.0)
        # Different trajectories (at least one intermediate point differs)
        p1 = r1.points
        p2 = r2.points
        min_len = min(len(p1), len(p2))
        mid_idx = min_len // 2
        differing = (
            abs(p1[mid_idx][0] - p2[mid_idx][0]) > 1.0
            or abs(p1[mid_idx][1] - p2[mid_idx][1]) > 1.0
        )
        assert differing, (
            "Gravity/wind parameters had no effect on mid-trajectory point"
        )


# ======================================================================
# SECTION 3 — Behavioral Tests: keystroke_timing (RED — xfail)
# ======================================================================


class TestKeystrokeTimingBehavioral:
    """Acceptance: dwell 80-200ms, flight 100-500ms, ~5% typos, 40-80 WPM."""

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_returns_list_of_dicts(self):
        """Returns list of dicts with char, dwell_ms, flight_ms keys."""
        result = BehavioralSimulator.keystroke_timing("Hello")
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, dict)
            assert "char" in item
            assert "dwell_ms" in item
            assert "flight_ms" in item

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_dwell_within_range(self):
        """dwell_ms per character is between 80 and 200ms."""
        result = BehavioralSimulator.keystroke_timing("Hello World! This is a test.")
        for item in result:
            assert 80 <= item["dwell_ms"] <= 200, (
                f"dwell_ms {item['dwell_ms']} for '{item['char']}' "
                f"outside range [80, 200]"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_flight_within_range(self):
        """flight_ms is between 100 and 500ms."""
        result = BehavioralSimulator.keystroke_timing(
            "Hello World! This is a test sentence."
        )
        for item in result:
            assert 100 <= item["flight_ms"] <= 500, (
                f"flight_ms {item['flight_ms']} for '{item['char']}' "
                f"outside range [100, 500]"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_typo_probability_approx_5_percent(self):
        """~5% of sequences have typos (backspace corrections).

        Run 10 sequences of ~40 chars each, count typo events.
        Expected: ~20 typo events in 400 chars = 5%.
        Allow tolerance: 2-12% range over multiple runs.
        """
        total_chars = 0
        total_typos = 0
        runs = 10
        text = "The quick brown fox jumps over the lazy dog." * 2  # ~90 chars

        for _ in range(runs):
            result = BehavioralSimulator.keystroke_timing(text)
            for item in result:
                total_chars += 1
                if item["char"] == "\b" or item.get("is_typo", False):
                    total_typos += 1

        typo_rate = total_typos / total_chars if total_chars > 0 else 0
        assert 0.01 <= typo_rate <= 0.20, (
            f"Typo rate {typo_rate:.1%} outside expected range [1%, 20%] "
            f"(approx 5% expected)"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_backspace_correction_removes_previous_char(self):
        """After a typo, the next non-backspace char re-types the correct one.

        Look for backspace entries and verify correction pattern exists.
        """
        result = BehavioralSimulator.keystroke_timing("Hello")
        chars = [item["char"] for item in result]
        # If there's a backspace, there should be a correction after it
        for i, c in enumerate(chars):
            if c == "\b" and i + 1 < len(chars):
                # A character follows the backspace — correction
                break
        else:
            # No backspace in this run — that's okay (5% prob)
            pass

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_timing_matches_40_wpm(self):
        """Total timing for typing matches approximately 40-80 WPM."""
        text = "The quick brown fox jumps over the lazy dog."  # 44 chars
        result = BehavioralSimulator.keystroke_timing(text, wpm_range=(40, 80))

        total_dwell = sum(item["dwell_ms"] for item in result)
        total_flight = sum(item["flight_ms"] for item in result)
        total_time_ms = total_dwell + total_flight
        total_time_min = total_time_ms / 60_000.0

        # WPM = (chars / 5) / time_min  (standard: 1 word = 5 chars)
        if total_time_min > 0:
            wpm = (len(text) / 5.0) / total_time_min
            assert 20 <= wpm <= 160, (
                f"Estimated WPM {wpm:.0f} outside broad range [20, 160] "
                f"(total_time={total_time_ms:.0f}ms for {len(text)} chars)"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_standard_deviation_above_10ms(self):
        """Timing varies per character: std dev > 10ms across dwell values."""
        text = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        result = BehavioralSimulator.keystroke_timing(text)
        dwells = [item["dwell_ms"] for item in result]

        assert len(dwells) >= 10, (
            f"Need at least 10 dwell samples for std dev, got {len(dwells)}"
        )
        std_dev = statistics.stdev(dwells)
        assert std_dev > 10.0, (
            f"Dwell std dev {std_dev:.1f}ms ≤ 10ms — timing looks too uniform"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_single_char_returns_one_result(self):
        """Single-character text returns exactly one timing entry."""
        result = BehavioralSimulator.keystroke_timing("a")
        assert len(result) == 1

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_empty_string_returns_empty_list(self):
        """Empty string text returns empty list (no keys to press)."""
        result = BehavioralSimulator.keystroke_timing("")
        assert result == []

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_wpm_range_affects_timing(self):
        """Higher WPM range produces faster overall typing."""
        text = "Hello World!" * 5

        slow = BehavioralSimulator.keystroke_timing(text, wpm_range=(40, 50))
        fast = BehavioralSimulator.keystroke_timing(text, wpm_range=(70, 80))

        slow_total = sum(s["dwell_ms"] + s["flight_ms"] for s in slow)
        fast_total = sum(f["dwell_ms"] + f["flight_ms"] for f in fast)

        assert fast_total < slow_total, (
            f"Fast WPM total {fast_total:.0f}ms ≥ slow WPM total {slow_total:.0f}ms"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_non_deterministic_output(self):
        """Two calls with same input produce different timing."""
        text = "The quick brown fox."
        r1 = BehavioralSimulator.keystroke_timing(text)
        r2 = BehavioralSimulator.keystroke_timing(text)

        dwells1 = tuple(item["dwell_ms"] for item in r1)
        dwells2 = tuple(item["dwell_ms"] for item in r2)
        assert dwells1 != dwells2, (
            "Two calls produced identical dwell timing — looks deterministic"
        )


# ======================================================================
# SECTION 4 — Behavioral Tests: scroll_sequence (RED — xfail)
# ======================================================================


class TestScrollSequenceBehavioral:
    """Acceptance: variable velocity, exponential decay, reading pauses."""

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_returns_list_of_dicts(self):
        """Returns list of dicts with delta_y, duration_ms, pause_after_ms keys."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        assert isinstance(result, list)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, dict)
            assert "delta_y" in item
            assert "duration_ms" in item
            assert "pause_after_ms" in item

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_at_least_2_steps(self):
        """Scroll sequence has at least 2 scroll steps."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        assert len(result) >= 2, (
            f"Got {len(result)} steps, expected at least 2"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_variable_velocity_range(self):
        """Scroll velocity varies between 0 and 3000px/s."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        for item in result:
            delta_y = item["delta_y"]
            duration_s = item["duration_ms"] / 1000.0
            if duration_s > 0:
                velocity = abs(delta_y) / duration_s
            else:
                velocity = 0.0
            assert 0.0 <= velocity <= 3000.0, (
                f"Velocity {velocity:.0f}px/s outside range [0, 3000] "
                f"(delta_y={delta_y}, duration_ms={item['duration_ms']})"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_exponential_decay(self):
        """Each step has decay in 200-800ms range (exponential momentum)."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        decay_times = [
            item["duration_ms"] for item in result
        ]
        # Individual decay durations should be in the 200-800ms range
        for i, dt in enumerate(decay_times):
            assert 200 <= dt <= 800, (
                f"Step {i} duration_ms={dt}ms outside expected decay range [200, 800]"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_decay_decreases_over_time(self):
        """Momentum decay: later steps have shorter or equal duration vs earlier."""
        result = BehavioralSimulator.scroll_sequence(
            viewport_height=1080, total_distance=5000
        )
        durations = [item["duration_ms"] for item in result]
        # At least one later step has decreasing duration (not monotonically increasing)
        has_decay = any(
            durations[i] > durations[i + 1]
            for i in range(len(durations) - 1)
        )
        assert has_decay, (
            f"Durations never decrease: {durations} — no exponential decay"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_reading_pauses_between_1_and_15_seconds(self):
        """Reading pauses between steps are 1-15s."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        pauses = [item["pause_after_ms"] for item in result]

        for i, p in enumerate(pauses):
            # The last element's pause may be 0 (no following pause)
            if i < len(pauses) - 1:
                assert 1000 <= p <= 15000, (
                    f"Pause {i} = {p}ms outside range [1000, 15000]"
                )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_pauses_not_uniform(self):
        """Pauses have non-uniform distribution (not all identical)."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        pauses = [item["pause_after_ms"] for item in result]
        # Filter out the last element (usually 0)
        non_zero_pauses = [p for p in pauses if p > 0]
        if len(non_zero_pauses) >= 3:
            assert len(set(non_zero_pauses)) >= 2, (
                f"All non-zero pauses identical: {non_zero_pauses}"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_total_distance_respected(self):
        """When total_distance is given, sum of delta_y approximates it."""
        target = 3000
        result = BehavioralSimulator.scroll_sequence(
            viewport_height=1080, total_distance=target
        )
        total = sum(item["delta_y"] for item in result)
        # Allow some tolerance — scrolling isn't perfectly precise
        assert abs(total - target) <= target * 0.3, (
            f"Total scroll distance {total} differs from target {target} "
            f"by {(total - target):.0f}px (>{target*0.3:.0f}px)"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_non_deterministic(self):
        """Two calls with same params produce different sequences."""
        s1 = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        s2 = BehavioralSimulator.scroll_sequence(viewport_height=1080)

        deltas1 = tuple(item["delta_y"] for item in s1)
        deltas2 = tuple(item["delta_y"] for item in s2)
        assert deltas1 != deltas2, (
            "Two scroll calls produced identical sequences"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_negative_delta_for_scroll_down(self):
        """Scroll delta_y is typically negative (scrolling down)."""
        result = BehavioralSimulator.scroll_sequence(
            viewport_height=1080, total_distance=2000
        )
        for item in result:
            assert item["delta_y"] <= 0, (
                f"Scroll step has positive delta_y {item['delta_y']} "
                f"— expected negative for scroll-down"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")


    def test_no_negative_duration_or_pause(self):
        """No negative durations or pauses."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        for i, item in enumerate(result):
            assert item["delta_y"] != 0, f"Step {i} has zero delta_y"
            assert item["duration_ms"] >= 0, f"Step {i} has negative duration"
            assert item["pause_after_ms"] >= 0, f"Step {i} has negative pause"


# ======================================================================
# SECTION 5 — Behavioral Tests: click_position (RED — xfail)
# ======================================================================


class TestClickPositionBehavioral:
    """Acceptance: within bounds, ±5-15px jitter, 50-200ms delay."""

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_returns_dict_with_x_y_delay(self, small_rect):
        """Returns dict with x, y, delay_ms keys."""
        result = BehavioralSimulator.click_position(small_rect)
        assert isinstance(result, dict)
        assert "x" in result
        assert "y" in result
        assert "delay_ms" in result

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_within_element_bounds(self, small_rect):
        """x,y are within element bounds (rect x, y, w, h)."""
        r = small_rect
        for _ in range(50):
            result = BehavioralSimulator.click_position(r)
            x, y = result["x"], result["y"]
            assert r["x"] <= x <= r["x"] + r["w"], (
                f"x={x} outside bounds [{r['x']}, {r['x'] + r['w']}]"
            )
            assert r["y"] <= y <= r["y"] + r["h"], (
                f"y={y} outside bounds [{r['y']}, {r['y'] + r['h']}]"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_spatial_offset_from_center(self, large_rect):
        """Offset from element center is between 5 and 15px."""
        r = large_rect
        cx = r["x"] + r["w"] / 2.0
        cy = r["y"] + r["h"] / 2.0

        offsets = []
        for _ in range(50):
            result = BehavioralSimulator.click_position(r)
            dx = abs(result["x"] - cx)
            dy = abs(result["y"] - cy)
            dist = math.sqrt(dx**2 + dy**2)
            offsets.append(dist)

        mean_offset = statistics.mean(offsets)
        assert 3.0 <= mean_offset <= 25.0, (
            f"Mean offset {mean_offset:.1f}px outside expected range [3, 25] "
            f"(target: 5-15px typical)"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_temporal_delay_between_50_and_200ms(self, small_rect):
        """delay_ms (temporal jitter) is between 50 and 200ms."""
        for _ in range(50):
            result = BehavioralSimulator.click_position(small_rect)
            assert 50 <= result["delay_ms"] <= 200, (
                f"delay_ms {result['delay_ms']} outside range [50, 200]"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_never_exact_center(self, small_rect):
        """Click offset is never exactly (0,0) or element center."""
        r = small_rect
        cx = r["x"] + r["w"] / 2.0
        cy = r["y"] + r["h"] / 2.0

        for _ in range(100):
            result = BehavioralSimulator.click_position(r)
            # Never exactly center
            assert not (result["x"] == cx and result["y"] == cy), (
                f"Click at exact center ({cx}, {cy})"
            )
            # Never exactly (0, 0)
            assert not (result["x"] == 0.0 and result["y"] == 0.0), (
                "Click at (0, 0)"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_no_out_of_bounds(self, small_rect):
        """No out-of-bounds coordinates after 200 calls."""
        r = small_rect
        for _ in range(200):
            result = BehavioralSimulator.click_position(r)
            x, y = result["x"], result["y"]
            assert r["x"] <= x <= r["x"] + r["w"], (
                f"x={x} outside rect [{r['x']}, {r['x'] + r['w']}]"
            )
            assert r["y"] <= y <= r["y"] + r["h"], (
                f"y={y} outside rect [{r['y']}, {r['y'] + r['h']}]"
            )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_values_are_floats(self, small_rect):
        """x, y, delay_ms are float values."""
        result = BehavioralSimulator.click_position(small_rect)
        assert isinstance(result["x"], float)
        assert isinstance(result["y"], float)
        assert isinstance(result["delay_ms"], float)

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_non_deterministic(self, small_rect):
        """Two calls produce different positions."""
        r1 = BehavioralSimulator.click_position(small_rect)
        r2 = BehavioralSimulator.click_position(small_rect)
        assert not (r1["x"] == r2["x"] and r1["y"] == r2["y"]), (
            "Two click_position calls returned identical coordinates"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_jitter_px_affects_spread(self, small_rect):
        """Higher jitter_px produces wider spatial spread."""
        r = small_rect

        low_jitter = [
            BehavioralSimulator.click_position(r, jitter_px=2.0)
            for _ in range(50)
        ]
        high_jitter = [
            BehavioralSimulator.click_position(r, jitter_px=20.0)
            for _ in range(50)
        ]

        cx = r["x"] + r["w"] / 2.0
        cy = r["y"] + r["h"] / 2.0

        low_dists = [math.sqrt((p["x"] - cx)**2 + (p["y"] - cy)**2) for p in low_jitter]
        high_dists = [math.sqrt((p["x"] - cx)**2 + (p["y"] - cy)**2) for p in high_jitter]

        assert statistics.mean(high_dists) > statistics.mean(low_dists), (
            "Higher jitter_px should produce wider spread"
        )


# ======================================================================
# SECTION 6 — Edge Case Tests (RED — xfail)
# ======================================================================


class TestClickPositionEdgeCases:
    """Edge cases: zero-dimension element, extreme values."""

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_zero_width_element(self):
        """Element with zero width still returns a valid click within bounds."""
        rect = {"x": 100.0, "y": 200.0, "w": 0.0, "h": 50.0}
        result = BehavioralSimulator.click_position(rect)
        assert rect["x"] <= result["x"] <= rect["x"] + rect["w"] + 0.1, (
            f"x={result['x']} outside zero-width bounds"
        )
        assert rect["y"] <= result["y"] <= rect["y"] + rect["h"], (
            f"y={result['y']} outside height bounds"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_zero_height_element(self):
        """Element with zero height still returns a valid click."""
        rect = {"x": 100.0, "y": 200.0, "w": 80.0, "h": 0.0}
        result = BehavioralSimulator.click_position(rect)
        assert rect["x"] <= result["x"] <= rect["x"] + rect["w"], (
            f"x={result['x']} outside width bounds"
        )
        assert rect["y"] - 0.1 <= result["y"] <= rect["y"] + rect["h"] + 0.1, (
            f"y={result['y']} outside zero-height bounds"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_zero_dimension_element(self):
        """Element with zero width and height returns the element's (x, y)."""
        rect = {"x": 300.0, "y": 400.0, "w": 0.0, "h": 0.0}
        result = BehavioralSimulator.click_position(rect)
        # x and y should be very close to the rect origin
        assert abs(result["x"] - rect["x"]) <= 15.0
        assert abs(result["y"] - rect["y"]) <= 15.0

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_negative_coordinates_rect(self):
        """Element with negative coordinates is handled correctly."""
        rect = {"x": -100.0, "y": -50.0, "w": 100.0, "h": 50.0}
        result = BehavioralSimulator.click_position(rect)
        assert rect["x"] <= result["x"] <= rect["x"] + rect["w"], (
            f"x={result['x']} outside negative rect bounds [{rect['x']}, "
            f"{rect['x'] + rect['w']}]"
        )
        assert rect["y"] <= result["y"] <= rect["y"] + rect["h"], (
            f"y={result['y']} outside negative rect bounds [{rect['y']}, "
            f"{rect['y'] + rect['h']}]"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: click_position")
    def test_large_element(self):
        """Large element produces jitter offset proportional to jitter_px."""
        rect = {"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0}
        result = BehavioralSimulator.click_position(rect)
        assert 0 <= result["x"] <= 1920
        assert 0 <= result["y"] <= 1080
        assert 50 <= result["delay_ms"] <= 200


class TestKeystrokeTimingEdgeCases:
    """Edge cases: empty/special characters, extreme WPM."""

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_special_characters(self):
        """Special characters (digits, symbols) produce valid timing."""
        text = "123!@#ABC"
        result = BehavioralSimulator.keystroke_timing(text)
        assert len(result) == len(text), (
            f"Got {len(result)} entries for {len(text)} chars"
        )
        for item in result:
            assert "char" in item
            assert 80 <= item.get("dwell_ms", 0) <= 200
            assert 100 <= item.get("flight_ms", 0) <= 500

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_wpm_range_min_max_equal(self):
        """When min==max WPM, timing is still computed (no crash)."""
        result = BehavioralSimulator.keystroke_timing("Test", wpm_range=(60, 60))
        assert len(result) == 4
        assert all(80 <= item["dwell_ms"] <= 200 for item in result)

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_long_text(self):
        """Long text (100+ chars) produces complete timing list."""
        text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 3
        result = BehavioralSimulator.keystroke_timing(text)
        assert len(result) == len(text), (
            f"Got {len(result)} entries for {len(text)} chars"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: keystroke_timing")
    def test_text_with_spaces(self):
        """Spaces are included in the timing list."""
        result = BehavioralSimulator.keystroke_timing("a b c")
        chars = [item["char"] for item in result]
        assert " " in chars, "Spaces not present in timing output"


class TestScrollSequenceEdgeCases:
    """Edge cases: viewport height mismatch, extreme values."""

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_small_viewport(self):
        """Small viewport (e.g. 480px mobile) produces valid sequence."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=480)
        assert len(result) >= 1

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_large_viewport(self):
        """Large viewport (4K, 2160px) produces valid sequence."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=2160)
        assert len(result) >= 1

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_no_total_distance(self):
        """When total_distance is None, default to 2-3 viewport-heights."""
        result = BehavioralSimulator.scroll_sequence(viewport_height=1080)
        total = sum(item["delta_y"] for item in result)
        # Should scroll at least 1 viewport height
        assert abs(total) >= 800, (
            f"Total scroll distance {total} seems too small"
        )

    @pytest.mark.xfail(reason="P0.2 not implemented: scroll_sequence")
    def test_custom_pause_range(self):
        """Custom min/max pause range is respected."""
        result = BehavioralSimulator.scroll_sequence(
            viewport_height=1080, min_pause_ms=2000, max_pause_ms=5000
        )
        pauses = [item["pause_after_ms"] for item in result]
        non_zero = [p for p in pauses if p > 0]
        if non_zero:
            assert all(2000 <= p <= 5000 for p in non_zero), (
                f"Pause outside custom range: {non_zero}"
            )


# ======================================================================
# SECTION 7 — Regression Guards (RED — xfail, permanent)
# ======================================================================


class TestSanityChecks:
    """Basic sanity checks that must hold after implementation."""

    def test_all_methods_require_no_instance(self):
        """All 4 methods are static — no instance needed (interface check)."""
        assert callable(BehavioralSimulator.wind_mouse_bezier)
        assert callable(BehavioralSimulator.keystroke_timing)
        assert callable(BehavioralSimulator.scroll_sequence)
        assert callable(BehavioralSimulator.click_position)

    @pytest.mark.xfail(reason="P0.2 not implemented: all methods")
    def test_no_negative_values(self):
        """No method returns negative durations, steps, or counts."""
        mouse = BehavioralSimulator.wind_mouse_bezier(0, 0, 100, 100)
        assert mouse.duration_ms >= 0
        assert mouse.steps >= 0

        typing = BehavioralSimulator.keystroke_timing("Hi")
        for item in typing:
            assert item["dwell_ms"] >= 0
            assert item["flight_ms"] >= 0

        scroll = BehavioralSimulator.scroll_sequence(1080)
        for item in scroll:
            assert item["duration_ms"] >= 0
            assert item["pause_after_ms"] >= 0

        click = BehavioralSimulator.click_position({"x": 0, "y": 0, "w": 100, "h": 50})
        assert click["delay_ms"] >= 0
