"""
Human-like behavioral simulation for browser automation (P0 Task 4.3).

Five simulator classes produce human-like interaction patterns:

  - MouseSimulator:    Bezier-curve mouse paths with variable velocity
  - TypingSimulator:   Per-character dwell, burst variation, ~3% typos
  - ScrollSimulator:   Momentum scroll with overshoot/correction
  - ClickSimulator:    Normal-distribution spatial jitter (sigma=4px)
  - TabFocusSimulator: Realistic focus/blur timing (10-60s loss)

Each simulator is instantiated independently and dispatches CDP Input events
via a WebSocket URL.

PRE-DEV STUB — All behavioral methods raise NotImplementedError.
Imports and dataclasses are ready for interface tests.

Dependencies: math, random (stdlib only); numpy optional for P0.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


# ======================================================================
# Result dataclasses
# ======================================================================


@dataclass
class MovementResult:
    """Result of a mouse movement simulation.

    Attributes:
        points:      Trajectory points as (x, y) tuples.
        duration_ms: Total movement time in milliseconds.
        steps:       Number of intermediate steps.
    """

    points: list[tuple[float, float]] = field(default_factory=list)
    duration_ms: float = 0.0
    steps: int = 0


@dataclass
class TypingResult:
    """Result of a typing simulation.

    Attributes:
        chars_typed: Number of characters typed.
        typos:       Number of backspace corrections made.
        total_ms:    Total elapsed time in milliseconds.
    """

    chars_typed: int = 0
    typos: int = 0
    total_ms: float = 0.0


@dataclass
class ScrollResult:
    """Result of a scroll simulation.

    Attributes:
        scroll_steps:  Individual scroll delta events.
        total_pixels:  Total scroll distance in pixels.
        total_ms:      Total elapsed time in milliseconds.
        overshot:      Whether an overshoot+correction occurred.
    """

    scroll_steps: list[dict[str, Any]] = field(default_factory=list)
    total_pixels: int = 0
    total_ms: float = 0.0
    overshot: bool = False


@dataclass
class ClickResult:
    """Result of a click simulation.

    Attributes:
        x:           Actual click x-coordinate.
        y:           Actual click y-coordinate.
        offset_px:   Euclidean distance from element centre.
        delay_ms:    Pre-click delay in milliseconds.
    """

    x: float = 0.0
    y: float = 0.0
    offset_px: float = 0.0
    delay_ms: float = 0.0


# ======================================================================
# MouseSimulator
# ======================================================================


class MouseSimulator:
    """Simulate human-like mouse movements via Bezier curves.

    Generates non-linear paths from a start point to a destination with
    variable velocity (200-800ms per 200px of travel).
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    @staticmethod
    def bezier_path(
        x0: float, y0: float, x1: float, y1: float, steps: int = 20,
    ) -> list[tuple[float, float]]:
        """Generate intermediate points along a cubic Bezier curve.

        Args:
            x0, y0: Start coordinates.
            x1, y1: End coordinates.
            steps:  Number of interpolation steps (default 20).

        Returns:
            List of (x, y) tuples forming the path.
        """
        raise NotImplementedError("bezier_path not implemented")

    async def human_mouse_move(
        self,
        cdp_ws_url: str,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        velocity_ms: int | None = None,
    ) -> list[dict]:
        """Move the mouse along a human-like Bezier path.

        Args:
            cdp_ws_url: CDP WebSocket endpoint URL.
            from_x, from_y: Start coordinates.
            to_x, to_y: Destination coordinates.
            velocity_ms: Target velocity in ms per 200px (200-800).

        Returns:
            List of dispatched CDP event dicts.
        """
        raise NotImplementedError("human_mouse_move not implemented")


# ======================================================================
# TypingSimulator
# ======================================================================


class TypingSimulator:
    """Simulate human-like keyboard typing patterns.

    Produces per-character dwell times of 100-300ms with burst-speed
    variation and approximately 3% backspace/typo rate.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    @staticmethod
    def typing_intervals(
        text: str, cpm: int = 300, typo_rate: float = 0.03,
    ) -> list[tuple[str, int]]:
        """Generate character-by-character typing intervals.

        Args:
            text:      The text to type.
            cpm:       Target characters-per-minute speed.
            typo_rate: Probability of a backspace typo (0.0-1.0).

        Returns:
            List of (char_or_backspace, delay_ms) tuples.
        """
        raise NotImplementedError("typing_intervals not implemented")

    async def human_typing(
        self,
        cdp_ws_url: str,
        text: str,
        field_selector: str | None = None,
        typo_rate: float = 0.03,
    ) -> TypingResult:
        """Type text with human-like timing and errors.

        Args:
            cdp_ws_url:     CDP WebSocket endpoint URL.
            text:           Text to type.
            field_selector: Optional CSS selector to focus first.
            typo_rate:      Probability of a backspace typo (0.0-1.0).

        Returns:
            TypingResult with chars_typed, typos, total_ms.
        """
        raise NotImplementedError("human_typing not implemented")


# ======================================================================
# ScrollSimulator
# ======================================================================


class ScrollSimulator:
    """Simulate human-like scrolling with momentum and overshoot.

    Generates non-uniform step sizes to mimic natural scroll acceleration
    and deceleration, with ~15% probability of overshoot+correction.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    async def human_scroll(
        self,
        cdp_ws_url: str,
        direction: str = "down",
        distance_px: int | None = None,
    ) -> ScrollResult:
        """Scroll with human-like momentum and optional overshoot.

        Args:
            cdp_ws_url:  CDP WebSocket endpoint URL.
            direction:   'down' or 'up'.
            distance_px: Total scroll distance in pixels (None = viewport).

        Returns:
            ScrollResult with scroll steps and timing.
        """
        raise NotImplementedError("human_scroll not implemented")


# ======================================================================
# ClickSimulator
# ======================================================================


class ClickSimulator:
    """Simulate human-like mouse clicks with spatial jitter.

    Offsets the click position from the element centre following a normal
    distribution with default sigma=4px, and adds a small temporal delay.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    async def human_click(
        self,
        cdp_ws_url: str,
        element_center_x: int,
        element_center_y: int,
        sigma_px: float = 4.0,
    ) -> ClickResult:
        """Click with normally-distributed spatial jitter.

        Args:
            cdp_ws_url:      CDP WebSocket endpoint URL.
            element_center_x: Element bounding-box centre X.
            element_center_y: Element bounding-box centre Y.
            sigma_px:        Standard deviation of jitter in px (default 4.0).

        Returns:
            ClickResult with actual coordinates and offset.
        """
        raise NotImplementedError("human_click not implemented")


# ======================================================================
# TabFocusSimulator
# ======================================================================


class TabFocusSimulator:
    """Simulate tab focus and blur events.

    Fires CDP Page.blur / Page.focus events with realistic timing:
    focus duration typically 10-60 seconds before a blur event.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    async def simulate_focus_blur(
        self,
        cdp_ws_url: str,
        focus_duration_s: float = 30.0,
        blur_duration_s: float = 15.0,
    ) -> None:
        """Simulate a tab focus/blur cycle.

        Args:
            cdp_ws_url:       CDP WebSocket endpoint URL.
            focus_duration_s: Time before first blur event (default 30.0).
            blur_duration_s:  Time before refocus (default 15.0).
        """
        raise NotImplementedError("simulate_focus_blur not implemented")


# ======================================================================
# BehavioralSimulation facade
# ======================================================================


class BehavioralSimulation:
    """Facade that composes all five simulator types for convenience.

    Usage:
        sim = BehavioralSimulation()
        await sim.human_mouse_move("ws://...", 100, 100, 500, 300)
        await sim.human_typing("ws://...", "Hello world")
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self.mouse = MouseSimulator(self._rng)
        self.typing = TypingSimulator(self._rng)
        self.scroll = ScrollSimulator(self._rng)
        self.click = ClickSimulator(self._rng)
        self.focus_blur = TabFocusSimulator(self._rng)

    async def human_mouse_move(
        self,
        cdp_ws_url: str,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        velocity_ms: int | None = None,
    ) -> list[dict]:
        return await self.mouse.human_mouse_move(
            cdp_ws_url, from_x, from_y, to_x, to_y, velocity_ms,
        )

    async def human_typing(
        self,
        cdp_ws_url: str,
        text: str,
        field_selector: str | None = None,
        typo_rate: float = 0.03,
    ) -> TypingResult:
        return await self.typing.human_typing(
            cdp_ws_url, text, field_selector, typo_rate,
        )

    async def human_scroll(
        self,
        cdp_ws_url: str,
        direction: str = "down",
        distance_px: int | None = None,
    ) -> ScrollResult:
        return await self.scroll.human_scroll(
            cdp_ws_url, direction, distance_px,
        )

    async def human_click(
        self,
        cdp_ws_url: str,
        element_center_x: int,
        element_center_y: int,
        sigma_px: float = 4.0,
    ) -> ClickResult:
        return await self.click.human_click(
            cdp_ws_url, element_center_x, element_center_y, sigma_px,
        )

    async def simulate_focus_blur(
        self,
        cdp_ws_url: str,
        focus_duration_s: float = 30.0,
        blur_duration_s: float = 15.0,
    ) -> None:
        return await self.focus_blur.simulate_focus_blur(
            cdp_ws_url, focus_duration_s, blur_duration_s,
        )

    @staticmethod
    def bezier_path(
        x0: float, y0: float, x1: float, y1: float, steps: int = 20,
    ) -> list[tuple[float, float]]:
        return MouseSimulator.bezier_path(x0, y0, x1, y1, steps)

    @staticmethod
    def typing_intervals(
        text: str, cpm: int = 300, typo_rate: float = 0.03,
    ) -> list[tuple[str, int]]:
        return TypingSimulator.typing_intervals(text, cpm, typo_rate)
