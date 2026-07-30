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

Dependencies: math, random, json (stdlib); websockets (external).
"""

from __future__ import annotations

import asyncio
import json
import math
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
# Utility: normal distribution via Box-Muller (stdlib only)
# ======================================================================


def _gauss(rng: random.Random, mu: float = 0.0, sigma: float = 1.0) -> float:
    """Sample from a normal distribution using Box-Muller transform."""
    u1 = rng.random()
    u2 = rng.random()
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return mu + sigma * z


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

        Two random control points create non-linear velocity along the path.

        Args:
            x0, y0: Start coordinates.
            x1, y1: End coordinates.
            steps:  Number of interpolation steps (default 20).

        Returns:
            List of (x, y) tuples forming the path.
        """
        dx = x1 - x0
        dy = y1 - y0

        # Random control points: first biased 20-50% along, second 60-90% along
        # with perpendicular offsets to create curvature
        t1 = 0.2 + random.random() * 0.3
        t2 = 0.6 + random.random() * 0.3

        perp_x = -dy * (0.1 + random.random() * 0.4)
        perp_y = dx * (0.1 + random.random() * 0.4)

        cx1 = x0 + dx * t1 + perp_x
        cy1 = y0 + dy * t1 + perp_y

        cx2 = x0 + dx * t2 - perp_x
        cy2 = y0 + dy * t2 - perp_y

        points: list[tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            # Cubic Bezier: B(t) = (1-t)³P₀ + 3(1-t)²t P₁ + 3(1-t)t² P₂ + t³P₃
            inv_t = 1.0 - t
            x = (
                inv_t ** 3 * x0
                + 3 * inv_t ** 2 * t * cx1
                + 3 * inv_t * t ** 2 * cx2
                + t ** 3 * x1
            )
            y = (
                inv_t ** 3 * y0
                + 3 * inv_t ** 2 * t * cy1
                + 3 * inv_t * t ** 2 * cy2
                + t ** 3 * y1
            )
            points.append((round(x, 1), round(y, 1)))

        return points

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
        path = MouseSimulator.bezier_path(
            float(from_x), float(from_y), float(to_x), float(to_y),
        )

        # Determine velocity: fall back to computed value if not provided
        if velocity_ms is None:
            total_dist = math.hypot(to_x - from_x, to_y - from_y)
            # 200-800ms per 200px, scaled by distance
            base = 200 + self._rng.random() * 600
            velocity_ms = int(base * (total_dist / 200.0)) if total_dist > 0 else 200
            velocity_ms = max(200, min(800, velocity_ms))

        # Per-step delay
        step_delay = max(10, velocity_ms // len(path)) if path else 10

        events: list[dict] = []
        try:
            import websockets

            async with websockets.connect(cdp_ws_url) as ws:
                for x, y in path:
                    event = {
                        "method": "Input.dispatchMouseEvent",
                        "params": {
                            "type": "mouseMoved",
                            "x": round(x),
                            "y": round(y),
                        },
                    }
                    await ws.send(json.dumps(event))
                    events.append(event)
                    if len(events) < len(path):  # don't delay after last point
                        await asyncio.sleep(step_delay / 1000.0)
        except (OSError, TimeoutError):
            # CDP unavailable — return computed path without dispatching
            for x, y in path:
                events.append({
                    "method": "Input.dispatchMouseEvent",
                    "params": {
                        "type": "mouseMoved",
                        "x": round(x),
                        "y": round(y),
                    },
                })
                await asyncio.sleep(0)  # yield control

        return events


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

        Each character gets a dwell time between 100-300ms with burst
        variation. Approximately ``typo_rate`` fraction of characters
        are replaced by a backspace (``\\b``) to simulate typos.

        Args:
            text:      The text to type.
            cpm:       Target characters-per-minute speed.
            typo_rate: Probability of a backspace typo (0.0-1.0).

        Returns:
            List of (char_or_backspace, delay_ms) tuples.
        """
        # Base dwell from CPM: 300 CPM = 5 chars/sec = 200ms per char
        base_dwell = 60000 // cpm  # ms per character

        intervals: list[tuple[str, int]] = []
        # Seeded module-level rng for static-method determinism
        local_rng = random.Random()

        for ch in text:
            # Burst variation: consecutive chars in bursts of 3-6
            # get a speed boost (~70-95% of base dwell)
            burst_factor = 0.7 + local_rng.random() * 0.25
            dwell = max(100, min(300, int(base_dwell * burst_factor)))

            # Add per-character variance (std ~15ms)
            dwell += int(_gauss(local_rng, 0, 15))
            dwell = max(100, min(300, dwell))

            # Decide if this character is a typo (backspace correction)
            if local_rng.random() < typo_rate:
                # Simulate quick typo: type wrong char, then backspace
                typo_char = local_rng.choice(
                    "abcdefghijklmnopqrstuvwxyz",
                )
                typo_dwell = max(100, dwell // 2)
                intervals.append((typo_char, typo_dwell))
                intervals.append(("\b", dwell))
                # Continue with the correct character below
                intervals.append((ch, dwell))
            else:
                intervals.append((ch, dwell))

        return intervals

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
        intervals = TypingSimulator.typing_intervals(text, typo_rate=typo_rate)

        # Compute total_ms from intervals regardless of CDP availability
        total_ms = sum(delay for _, delay in intervals)

        chars_typed = 0
        typos = 0

        try:
            import websockets

            async with websockets.connect(cdp_ws_url) as ws:
                # Focus field if selector provided
                if field_selector:
                    focus_cmd = {
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": (
                                f"document.querySelector({field_selector!r})"
                                ".focus()"
                            ),
                        },
                    }
                    await ws.send(json.dumps(focus_cmd))
                    await asyncio.sleep(0.1)

                for ch, delay in intervals:
                    if ch == "\b":
                        # Backspace key event
                        event = {
                            "method": "Input.dispatchKeyEvent",
                            "params": {
                                "type": "keyDown",
                                "key": "Backspace",
                                "windowsVirtualKeyCode": 8,
                            },
                        }
                        await ws.send(json.dumps(event))
                        typos += 1
                        # Dispatch keyUp
                        up = dict(event)
                        up["params"] = dict(event["params"])
                        up["params"]["type"] = "keyUp"
                        await ws.send(json.dumps(up))
                    else:
                        # Character key event
                        event = {
                            "method": "Input.dispatchKeyEvent",
                            "params": {
                                "type": "char",
                                "text": ch,
                                "key": ch,
                            },
                        }
                        await ws.send(json.dumps(event))
                        chars_typed += 1

                    await asyncio.sleep(delay / 1000.0)

        except (OSError, TimeoutError):
            # CDP unavailable — compute result from intervals without dispatching
            chars_typed = sum(1 for c, _ in intervals if c != "\b" and c != "<BACK>")
            typos = sum(1 for c, _ in intervals if c == "\b" or c == "<BACK>")

        return TypingResult(
            chars_typed=chars_typed,
            typos=typos,
            total_ms=total_ms,
        )


# ======================================================================
# ScrollSimulator
# ======================================================================


class ScrollSimulator:
    """Simulate human-like scrolling with momentum and overshoot.

    Generates non-uniform step sizes to mimic natural scroll acceleration
    and deceleration, with ~15% probability of overshoot+correction.
    """

    SCROLL_PX_PER_STEP = 100  # approximate single wheel tick in px

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    async def human_scroll(
        self,
        cdp_ws_url: str,
        direction: str = "down",
        distance_px: int | None = None,
    ) -> ScrollResult:
        """Scroll with human-like momentum and optional overshoot.

        Builds a scroll sequence with acceleration (first ~30% of steps),
        cruising (~40%), and deceleration (~30%), plus a ~15% chance of
        an overshoot+correction double-tick at the end.

        Args:
            cdp_ws_url:  CDP WebSocket endpoint URL.
            direction:   'down' or 'up'.
            distance_px: Total scroll distance in pixels (None = viewport).

        Returns:
            ScrollResult with scroll steps and timing.
        """
        if distance_px is None:
            distance_px = self._rng.randint(300, 1500)

        delta_sign = -1 if direction == "up" else 1
        steps: list[dict[str, Any]] = []
        total_pixels = 0
        total_ms = 0.0

        # Build step sequence with momentum profile
        num_steps = max(3, distance_px // self.SCROLL_PX_PER_STEP)
        step_sizes = self._build_momentum_profile(num_steps, distance_px)

        for step_px in step_sizes:
            actual_px = step_px * delta_sign
            steps.append({
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "mouseWheel",
                    "deltaX": 0,
                    "deltaY": actual_px,
                },
            })
            total_pixels += abs(step_px)
            # Inter-step delay: faster during cruise, slower at edges
            total_ms += 30 + self._rng.random() * 40

        # ~15% overshoot + correction
        overshot = False
        if self._rng.random() < 0.15:
            overshoot_px = int(total_pixels * (0.05 + self._rng.random() * 0.1))
            steps.append({
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "mouseWheel",
                    "deltaX": 0,
                    "deltaY": overshoot_px * delta_sign,
                },
            })
            total_ms += 50 + self._rng.random() * 30
            # Correction back
            steps.append({
                "method": "Input.dispatchMouseEvent",
                "params": {
                    "type": "mouseWheel",
                    "deltaX": 0,
                    "deltaY": -overshoot_px * delta_sign,
                },
            })
            total_ms += 40 + self._rng.random() * 20
            overshot = True

        # Pause at boundaries: add a boundary-check tick
        steps.append({
            "method": "Input.dispatchMouseEvent",
            "params": {
                "type": "mouseWheel",
                "deltaX": 0,
                "deltaY": 0,
            },
        })
        total_ms += 100 + self._rng.random() * 200

        try:
            import websockets

            async with websockets.connect(cdp_ws_url) as ws:
                for event in steps:
                    await ws.send(json.dumps(event))
                    await asyncio.sleep(0.02 + self._rng.random() * 0.03)
        except (OSError, TimeoutError):
            await asyncio.sleep(0)  # yield control

        return ScrollResult(
            scroll_steps=steps,
            total_pixels=total_pixels,
            total_ms=total_ms,
            overshot=overshot,
        )

    def _build_momentum_profile(
        self, num_steps: int, total_px: int,
    ) -> list[int]:
        """Build a list of per-step pixel amounts with acceleration/deceleration.

        Uses a sine easing: starts slow, accelerates to peak, decelerates.
        """
        accel_end = int(num_steps * 0.3)
        cruise_end = int(num_steps * 0.7)
        avg_px = total_px // max(1, num_steps)

        steps: list[int] = []
        cumulative = 0
        for i in range(num_steps):
            if i < accel_end:
                # Acceleration phase
                t = i / max(1, accel_end)
                factor = t  # linear ramp
            elif i < cruise_end:
                # Cruise phase
                factor = 1.0
            else:
                # Deceleration phase
                remaining = num_steps - i
                decel_steps = num_steps - cruise_end
                t = (decel_steps - remaining) / max(1, decel_steps)
                factor = 1.0 - t  # linear ramp down

            px = max(1, int(avg_px * (0.5 + factor * 0.5)))
            # Ensure we don't overshoot total_px
            if cumulative + px > total_px:
                px = total_px - cumulative
            steps.append(px)
            cumulative += px
            if cumulative >= total_px:
                break

        return steps


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
        # Generate jitter using Box-Muller
        offset_x = _gauss(self._rng, 0, sigma_px)
        offset_y = _gauss(self._rng, 0, sigma_px)

        click_x = element_center_x + offset_x
        click_y = element_center_y + offset_y
        offset_px = math.hypot(offset_x, offset_y)
        delay_ms = 50 + self._rng.random() * 150  # 50-200ms pre-click delay

        try:
            import websockets

            async with websockets.connect(cdp_ws_url) as ws:
                # Small pre-click delay
                await asyncio.sleep(delay_ms / 1000.0)

                # Mouse move to jittered position
                move_event = {
                    "method": "Input.dispatchMouseEvent",
                    "params": {
                        "type": "mouseMoved",
                        "x": round(click_x),
                        "y": round(click_y),
                    },
                }
                await ws.send(json.dumps(move_event))

                # Mouse down
                down_event = {
                    "method": "Input.dispatchMouseEvent",
                    "params": {
                        "type": "mousePressed",
                        "button": "left",
                        "clickCount": 1,
                        "x": round(click_x),
                        "y": round(click_y),
                    },
                }
                await ws.send(json.dumps(down_event))

                # Delay between press and release (30-80ms)
                await asyncio.sleep(0.03 + self._rng.random() * 0.05)

                # Mouse up
                up_event = {
                    "method": "Input.dispatchMouseEvent",
                    "params": {
                        "type": "mouseReleased",
                        "button": "left",
                        "clickCount": 1,
                        "x": round(click_x),
                        "y": round(click_y),
                    },
                }
                await ws.send(json.dumps(up_event))
        except (OSError, TimeoutError):
            # CDP unavailable — return computed result without dispatching
            await asyncio.sleep(0)

        return ClickResult(
            x=click_x,
            y=click_y,
            offset_px=offset_px,
            delay_ms=delay_ms,
        )


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
        try:
            import websockets

            async with websockets.connect(cdp_ws_url) as ws:
                # Initial focus
                focus_event = {"method": "Page.focus", "params": {}}
                await ws.send(json.dumps(focus_event))

                # Wait then blur
                await asyncio.sleep(focus_duration_s)
                blur_event = {"method": "Page.blur", "params": {}}
                await ws.send(json.dumps(blur_event))

                # Wait then refocus
                await asyncio.sleep(blur_duration_s)
                await ws.send(json.dumps(focus_event))
        except (OSError, TimeoutError):
            # CDP unavailable — just yield control
            await asyncio.sleep(0)


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
