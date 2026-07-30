"""
BehavioralSimulator — Human-like behavioral simulation for browser automation.

Provides human-like mouse movement (WindMouse + Bezier hybrid), keystroke
timing with dwell/flight distributions, scroll momentum with power-law
decay, and click jitter with Gaussian spatial offset. These are injected
at the CDP level, not JS level.

Usage:
    from behavioral_sim import BehavioralSimulator

    result = BehavioralSimulator.wind_mouse_bezier(100, 100, 500, 300)
    keys = BehavioralSimulator.keystroke_timing("Hello, world!")
    scroll = BehavioralSimulator.scroll_sequence(viewport_height=1080)
    click = BehavioralSimulator.click_position({"x": 200, "y": 150, "w": 100, "h": 40})
"""

from __future__ import annotations

import math
import random
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
# Internal helpers
# ---------------------------------------------------------------------------


def _wind_mouse_internal(
    start_x: float,
    start_y: float,
    dest_x: float,
    dest_y: float,
    gravity: float,
    wind: float,
    max_step: float,
    target_threshold: float,
) -> list[tuple[float, float]]:
    """Pure WindMouse algorithm with Bezier landing micro-correction.

    Returns list of (x, y) trajectory points from start to destination.
    Far from target: WindMouse physics (wind + gravity) for macro-trajectory.
    Near target: Bezier micro-correction for smooth landing.
    """
    points: list[tuple[float, float]] = [(start_x, start_y)]
    # Internal RNG for deterministic-ish output per call
    rng = random.Random()
    rng.seed(
        hash((start_x, start_y, dest_x, dest_y, gravity, wind))
        % (2**31)
    )

    x, y = float(start_x), float(start_y)
    vx, vy = 0.0, 0.0
    W_x, W_y = 0.0, 0.0

    sqrt_3 = math.sqrt(3)
    sqrt_2 = math.sqrt(2)

    while True:
        # Distances to target
        dist = math.hypot(dest_x - x, dest_y - y)
        if dist < target_threshold:
            break

        # Wind force: random walk with inertia
        W_x = W_x * 0.5 + rng.uniform(-0.5, 0.5) * wind
        W_y = W_y * 0.5 + rng.uniform(-0.5, 0.5) * wind

        # Gravity towards destination
        G_x = (dest_x - x) / dist * gravity
        G_y = (dest_y - y) / dist * gravity

        # Cap gravity by threshold-based damping
        if dist < 100:
            G_x *= dist / 100
            G_y *= dist / 100

        # Apply forces to velocity
        vx = (vx + W_x + G_x) * 0.9
        vy = (vy + W_y + G_y) * 0.9

        # Clamp velocity magnitude to max_step
        speed = math.hypot(vx, vy)
        if speed > max_step:
            vx = vx / speed * max_step
            vy = vy / speed * max_step

        # Move
        x += vx
        y += vy

        # Clamp to bounds (prevent negative coordinates)
        x = max(0.0, x)
        y = max(0.0, y)

        points.append((x, y))

    # Add destination as final point (force exact landing)
    # But only if we didn't already overshoot
    if len(points) < 2 or math.hypot(points[-1][0] - dest_x, points[-1][1] - dest_y) > 1.0:
        points.append((float(dest_x), float(dest_y)))

    return points


def _bezier_curve(
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    steps: int,
) -> list[tuple[float, float]]:
    """Generate a cubic Bezier curve between two points with random control points."""
    rng = random.Random()
    rng.seed(hash((start_x, start_y, end_x, end_y)) % (2**31))

    ctrl1_x = start_x + (end_x - start_x) * 0.2 + rng.uniform(-30, 30)
    ctrl1_y = start_y + (end_y - start_y) * 0.2 + rng.uniform(-30, 30)
    ctrl2_x = start_x + (end_x - start_x) * 0.8 + rng.uniform(-30, 30)
    ctrl2_y = start_y + (end_y - start_y) * 0.8 + rng.uniform(-30, 30)

    points: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        # Cubic Bezier
        bx = (
            (1 - t) ** 3 * start_x
            + 3 * (1 - t) ** 2 * t * ctrl1_x
            + 3 * (1 - t) * t**2 * ctrl2_x
            + t**3 * end_x
        )
        by = (
            (1 - t) ** 3 * start_y
            + 3 * (1 - t) ** 2 * t * ctrl1_y
            + 3 * (1 - t) * t**2 * ctrl2_y
            + t**3 * end_y
        )
        points.append((bx, by))
    return points


def _compute_duration(points: list[tuple[float, float]], base_wpm: int = 60) -> float:
    """Estimate total movement duration in ms based on distance and WPM."""
    total_dist = 0.0
    for i in range(1, len(points)):
        total_dist += math.hypot(
            points[i][0] - points[i - 1][0],
            points[i][1] - points[i - 1][1],
        )
    # Base speed: ~200 pixels per 100ms at 60 WPM, scales with WPM
    speed_px_per_ms = 2.0 * (base_wpm / 60.0)
    duration = total_dist / speed_px_per_ms if speed_px_per_ms > 0 else 100
    return max(duration, 30.0)  # At least 30ms


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
        # Generate WindMouse trajectory
        wind_points = _wind_mouse_internal(
            start_x, start_y, dest_x, dest_y,
            gravity, wind, max_step, target_threshold,
        )

        # If we have enough points, blend with Bezier for the final segment
        # (last few points before destination)
        if len(wind_points) >= 3:
            # Get the point before the final one and do a Bezier from there to dest
            pre_last = wind_points[-2]
            bezier_segment = _bezier_curve(
                pre_last[0], pre_last[1],
                float(dest_x), float(dest_y),
                steps=5,
            )
            # Replace last points with the Bezier curve (skip first bezier point = pre_last)
            points = wind_points[:-2] + bezier_segment[1:]
        else:
            points = wind_points

        # Deduplicate consecutive identical points
        cleaned: list[tuple[float, float]] = [points[0]]
        for p in points[1:]:
            if p != cleaned[-1]:
                cleaned.append(p)

        duration = _compute_duration(cleaned)
        return MouseMovementResult(
            points=cleaned,
            duration_ms=round(duration, 1),
            steps=len(cleaned),
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
        if not text:
            return []

        rng = random.Random()
        rng.seed(hash(text) % (2**31))

        min_wpm, max_wpm = wpm_range
        base_wpm = rng.randint(min_wpm, max_wpm)

        # Convert WPM to timing (chars per second)
        # Average word = 5 characters
        cps = base_wpm * 5 / 60.0  # characters per second
        # Base dwell + flight per char
        base_dwell_ms = 120.0 / (cps / 5.0) if cps > 0 else 120.0
        base_flight_ms = 250.0 / (cps / 5.0) if cps > 0 else 250.0

        results: list[dict[str, Any]] = []

        # Letters near home row are faster
        fast_chars = set("asdfghjkl;'qwertyuiop[]zxcvbnm,./ ")
        slow_chars = set("QWERTYUIOPASDFGHJKLZXCVBNM{}|:\"<>?!@#$%^&*()_+")

        for char in text:
            # Determine if this character gets a typo
            has_typo = rng.random() < 0.05

            if has_typo:
                # Typo: add wrong char + backspace
                typo_char = rng.choice("asdfghjklqwertyuiopzxcvbnm")
                # dwell for the typo
                dwell_typo = base_dwell_ms * rng.uniform(0.8, 1.2)
                flight_typo = base_flight_ms * rng.uniform(0.5, 1.5)
                results.append({
                    "char": typo_char,
                    "dwell_ms": round(dwell_typo),
                    "flight_ms": round(flight_typo),
                    "is_backspace": False,
                })
                # backspace
                dwell_bs = base_dwell_ms * rng.uniform(0.6, 1.0)
                flight_bs = base_flight_ms * rng.uniform(0.3, 0.8)
                results.append({
                    "char": "\b",
                    "dwell_ms": round(dwell_bs),
                    "flight_ms": round(flight_bs),
                    "is_backspace": True,
                })

            # Speed modifiers based on character type
            speed_mod = 1.0
            if char in fast_chars:
                speed_mod = rng.uniform(0.8, 1.0)
            elif char in slow_chars:
                speed_mod = rng.uniform(1.0, 1.4)
            elif char.isupper():
                speed_mod = rng.uniform(1.1, 1.3)

            dwell = base_dwell_ms * rng.uniform(0.8, 1.2) * speed_mod
            flight = base_flight_ms * rng.uniform(0.7, 1.5) * speed_mod

            # Clamp to spec ranges
            dwell = max(80, min(200, dwell))
            flight = max(100, min(500, flight))

            results.append({
                "char": char,
                "dwell_ms": round(dwell),
                "flight_ms": round(flight),
                "is_backspace": False,
            })

        return results

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
        rng = random.Random()
        rng.seed(hash((viewport_height, total_distance or 0, min_pause_ms, max_pause_ms)) % (2**31))

        if total_distance is None:
            total_distance = viewport_height * rng.randint(3, 8)

        results: list[dict[str, Any]] = []
        remaining = total_distance
        scroll_count = 0
        max_scrolls = 80  # Safety limit

        # Initial velocity: start fast (~50-80% of viewport per event)
        velocity = viewport_height * rng.uniform(0.4, 0.8)

        while remaining > 10 and scroll_count < max_scrolls:
            # Power-law decay: each event reduces velocity
            # velocity_n = velocity_0 * n^(-0.3)
            exponent = 0.3
            decay = (scroll_count + 1) ** (-exponent)
            current_velocity = velocity * decay

            # Add noise
            current_velocity *= rng.uniform(0.7, 1.3)

            delta_y = max(10, min(remaining, round(current_velocity)))

            # Duration proportional to delta with slight variance
            duration = delta_y / viewport_height * rng.uniform(80, 200)
            duration = max(20, round(duration))

            # Pause: reading time, longer for larger scrolls (simulating reading)
            pause_ratio = delta_y / viewport_height
            pause = rng.uniform(min_pause_ms, max_pause_ms) * min(1.0, pause_ratio * 3)
            pause = max(50, round(pause))

            results.append({
                "delta_y": delta_y,
                "duration_ms": duration,
                "pause_after_ms": pause,
            })

            remaining -= delta_y
            scroll_count += 1

        # If we still have distance, add a final chunk
        if remaining > 10:
            results.append({
                "delta_y": remaining,
                "duration_ms": max(20, round(remaining / viewport_height * 150)),
                "pause_after_ms": min_pause_ms,
            })

        return results

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
        rng = random.Random()
        rng.seed(
            hash((
                element_rect.get("x", 0),
                element_rect.get("y", 0),
                element_rect.get("w", 0),
                element_rect.get("h", 0),
                jitter_px,
            )) % (2**31)
        )

        center_x = element_rect["x"] + element_rect["w"] / 2
        center_y = element_rect["y"] + element_rect["h"] / 2

        # Gaussian spatial offset
        offset_x = rng.gauss(0, jitter_px)
        offset_y = rng.gauss(0, jitter_px)

        click_x = center_x + offset_x
        click_y = center_y + offset_y

        # Pre-click delay
        min_delay, max_delay = jitter_ms_range
        delay = rng.uniform(min_delay, max_delay)

        return {
            "x": round(click_x, 1),
            "y": round(click_y, 1),
            "delay_ms": round(delay, 1),
        }
