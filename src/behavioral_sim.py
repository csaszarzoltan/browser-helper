"""
BehavioralSimulator — Human-like behavioral simulation for browser automation.

Provides human-like mouse movement (WindMouse + Bezier hybrid), keystroke
timing with dwell/flight distributions, scroll momentum with power-law
decay, and click jitter with Gaussian spatial offset. These are injected
at the CDP level, not JS level.

PRE-DEV STUB — All behavioral methods raise NotImplementedError.

Usage:
    from behavioral_sim import BehavioralSimulator

    result = BehavioralSimulator.wind_mouse_bezier(100, 100, 500, 300)
    keys = BehavioralSimulator.keystroke_timing("Hello, world!")
    scroll = BehavioralSimulator.scroll_sequence(viewport_height=1080)
    click = BehavioralSimulator.click_position({"x": 200, "y": 150, "w": 100, "h": 40})

# === Pre-Development Contract ===
# Interface tests (pass with stub):
#   - MouseMovementResult dataclass exists with expected fields
#   - BehavioralSimulator class exists
#   - All static methods are present with correct signatures
# Behavioral tests (fail with NotImplementedError):
#   - wind_mouse_bezier() returns MouseMovementResult with curved trajectory
#   - keystroke_timing() returns list with dwell/flight timing
#   - scroll_sequence() returns list with power-law decay
#   - click_position() returns dict with Gaussian offset
#   - Parameters affect output (gravity, wind, wpm_range, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MouseMovementResult:
    """Result of a mouse movement simulation.

    Attributes:
        points:       Trajectory points as (x, y) tuples.
        duration_ms:  Total movement time in milliseconds.
        steps:        Number of intermediate points in the trajectory.
    """

    points: list[tuple[float, float]] = field(default_factory=list)
    duration_ms: float = 0.0
    steps: int = 0


# ---------------------------------------------------------------------------
# Behavioral Simulator
# ---------------------------------------------------------------------------


class BehavioralSimulator:
    """Human-like behavioral simulation for browser automation.

    All methods are static — no instance state needed. Each method
    generates a sequence of CDP-level commands that mimic human
    interaction patterns.
    """

    # ── Mouse movement ────────────────────────────────────────────────

    @staticmethod
    def wind_mouse_bezier(
        start_x: float,
        start_y: float,
        dest_x: float,
        dest_y: float,
        gravity: float = 9.0,
        wind: float = 3.0,
        max_step: float = 15.0,
        target_threshold: float = 12.0,
    ) -> MouseMovementResult:
        """Generate a human-like mouse trajectory using WindMouse + Bezier hybrid.

        Far from target: WindMouse physics (wind + gravity) for macro-trajectory.
        Near target: Bezier micro-correction for smooth landing.

        Args:
            start_x:           Starting X coordinate.
            start_y:           Starting Y coordinate.
            dest_x:            Target X coordinate.
            dest_y:            Target Y coordinate.
            gravity:           Gravity strength for WindMouse (default 9.0).
            wind:              Wind strength for WindMouse (default 3.0).
            max_step:          Maximum step size in pixels (default 15.0).
            target_threshold:  Distance in px to switch to Bezier (default 12.0).

        Returns:
            A MouseMovementResult with trajectory points, duration, and step count.
        """
        raise NotImplementedError(
            "wind_mouse_bezier — WindMouse + Bezier hybrid trajectory"
        )

    # ── Keystroke timing ──────────────────────────────────────────────

    @staticmethod
    def keystroke_timing(
        text: str,
        wpm_range: tuple[int, int] = (40, 80),
    ) -> list[dict[str, Any]]:
        """Generate per-character timing with dwell/flight distributions.

        Returns a list of dicts, one per character, each containing:
            char:      The character being typed.
            dwell_ms:  Time the key is held down (80-200ms typical).
            flight_ms: Time between releasing this key and pressing the next
                       (100-500ms typical).

        Includes occasional typos + backspace corrections (~5% probability).

        Args:
            text:      The text to generate timing for.
            wpm_range: (min_wpm, max_wpm) tuple controlling overall speed.

        Returns:
            List of ``{char, dwell_ms, flight_ms}`` dicts.
        """
        raise NotImplementedError(
            "keystroke_timing — dwell/flight per-character timing"
        )

    # ── Scroll simulation ─────────────────────────────────────────────

    @staticmethod
    def scroll_sequence(
        viewport_height: int,
        total_distance: int | None = None,
        min_pause_ms: int = 1000,
        max_pause_ms: int = 15000,
    ) -> list[dict[str, Any]]:
        """Generate a scroll sequence with power-law momentum decay.

        Each scroll event is followed by a reading pause. Velocity starts
        high and decays following a power law, producing realistic scroll
        deceleration.

        Args:
            viewport_height: Height of the browser viewport in pixels.
            total_distance:  Total scroll distance in pixels. If None,
                             calculated as a multiple of viewport_height.
            min_pause_ms:    Minimum pause between scroll events (ms).
            max_pause_ms:    Maximum pause between scroll events (ms).

        Returns:
            List of ``{delta_y, duration_ms, pause_after_ms}`` dicts.
        """
        raise NotImplementedError(
            "scroll_sequence — power-law momentum decay scroll"
        )

    # ── Click jitter ──────────────────────────────────────────────────

    @staticmethod
    def click_position(
        element_rect: dict[str, float],
        jitter_px: float = 10.0,
        jitter_ms_range: tuple[int, int] = (50, 200),
    ) -> dict[str, Any]:
        """Generate a human-like click position and timing.

        Applies a Gaussian spatial offset to the element center and a
        pre-click delay drawn from the specified range.

        Args:
            element_rect:   Dict with keys ``x``, ``y``, ``w``, ``h`` defining
                           the element's bounding box.
            jitter_px:      Standard deviation of the spatial jitter in pixels.
            jitter_ms_range: (min_delay_ms, max_delay_ms) for pre-click delay.

        Returns:
            ``{"x": float, "y": float, "delay_ms": float}`` dict.
        """
        raise NotImplementedError(
            "click_position — Gaussian spatial + temporal jitter"
        )
