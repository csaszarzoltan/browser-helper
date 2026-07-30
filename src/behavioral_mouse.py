"""
Human Mouse Movement Middleware (P1-2).

Provides Bezier-curve mouse paths with configurable speed profiles, overshoot,
and jitter. Wraps ``Input.dispatchMouseEvent`` for human-like pointer motion.

Usage::

    from behavioral_mouse import BehavioralMouse, MouseConfig

    mouse = BehavioralMouse(MouseConfig(enabled=True, speed="normal"))
    await mouse.move_to(x=500, y=300)
    await mouse.click(x=500, y=300)
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, ClassVar

# ---------------------------------------------------------------------------
# Mouse Configuration
# ---------------------------------------------------------------------------


class MouseConfig:
    """Configuration for human mouse movement behavior.

    Attributes:
        enabled:  When False, mouse operations fall through to raw CDP.
        speed:    One of ``"slow"``, ``"normal"``, ``"fast"``.
    """

    VALID_SPEEDS = frozenset({"slow", "normal", "fast"})

    # Base durations (ms) for each speed profile
    SPEED_DURATIONS: ClassVar[dict[str, int]] = {
        "slow": 300,
        "normal": 150,
        "fast": 50,
    }

    def __init__(
        self,
        enabled: bool = True,
        speed: str = "normal",
    ) -> None:
        self.enabled = enabled
        self.speed = speed
        self._validate()

    def _validate(self) -> None:
        """Raise ValueError if speed is invalid."""
        if self.speed not in self.VALID_SPEEDS:
            raise ValueError(
                f"Invalid speed: {self.speed!r}. "
                f"Expected one of {sorted(self.VALID_SPEEDS)}"
            )

    @property
    def base_duration_ms(self) -> int:
        """Return the base movement duration for the current speed profile."""
        return self.SPEED_DURATIONS[self.speed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "speed": self.speed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MouseConfig:
        return cls(
            enabled=data.get("enabled", True),
            speed=data.get("speed", "normal"),
        )

    def __repr__(self) -> str:
        return f"MouseConfig(enabled={self.enabled}, speed={self.speed!r})"


# ---------------------------------------------------------------------------
# Behavioral Mouse Middleware
# ---------------------------------------------------------------------------


class BehavioralMouse:
    """Middleware providing human-like mouse movement via Bezier curves.

    Usage::

        mouse = BehavioralMouse()
        events = await mouse.move_to(500, 300)
        result = await mouse.click(500, 300)
    """

    MODE_ENABLED = "enabled"
    MODE_RAW = "raw"

    # Overshoot probability (~15%)
    OVERSHOOT_PROBABILITY = 0.15
    # Jitter amplitude (±2px)
    JITTER_AMPLITUDE = 2.0

    def __init__(self, config: MouseConfig | None = None) -> None:
        self._config = config or MouseConfig()

    # ── Config ────────────────────────────────────────────────────────

    @property
    def config(self) -> MouseConfig:
        """Return the current mouse configuration."""
        return self._config

    @config.setter
    def config(self, value: MouseConfig) -> None:
        self._config = value

    # ── Public API ────────────────────────────────────────────────────

    async def move_to(
        self,
        x: int,
        y: int,
        client: Any = None,
    ) -> list[dict[str, Any]]:
        """Move the mouse to (x, y) using a Bezier curve path.

        Args:
            x: Target X coordinate.
            y: Target Y coordinate.
            client: Optional CDP client for dispatching mouse events.

        Returns:
            List of ``Input.dispatchMouseEvent`` parameter dicts representing
            each intermediate mouse-move event on the Bezier path.  When
            ``enabled=False``, returns a single immediate-move event.
        """
        if not self._config.enabled:
            return self._raw_move_to(x, y)

        # Start position (0, 0) is a reasonable default for a fresh session.
        start_x: float = 0.0
        start_y: float = 0.0

        # Compute base number of steps based on distance
        distance = math.sqrt((x - start_x) ** 2 + (y - start_y) ** 2)
        num_steps = max(10, min(50, int(distance / 20)))

        # Generate the Bezier path
        path = self._generate_bezier_path(start_x, start_y, float(x), float(y), num_steps)

        # Optionally apply overshoot
        if self._should_overshoot():
            overshoot_target = self._compute_overshoot_target(float(x), float(y))
            overshoot_path = self._generate_bezier_path(
                float(x), float(y),
                overshoot_target[0], overshoot_target[1],
                num_steps=max(5, num_steps // 2),
            )
            # Append overshoot and correct back
            path = path + overshoot_path
            correction = self._generate_bezier_path(
                overshoot_target[0], overshoot_target[1],
                float(x), float(y),
                num_steps=max(5, num_steps // 2),
            )
            path = path + correction

        # Generate inter-step delays
        delays = self._inter_step_delays(len(path), self._config.base_duration_ms)

        # Build dispatch events with jittered positions
        events: list[dict[str, Any]] = []
        for i, (px, py) in enumerate(path):
            jx, jy = self._add_jitter((px, py))
            params = self._make_dispatch_params(
                "mouseMoved",
                round(jx),
                round(jy),
            )
            params["_delay"] = delays[i] if i < len(delays) else 0.0
            events.append(params)

        # If client is provided, dispatch events in real time
        if client is not None:
            for evt in events:
                delay = evt.pop("_delay", 0.0)
                if delay > 0:
                    await self._sleep(delay)
                await client._send_command("Input.dispatchMouseEvent", evt)

        return events

    async def _sleep(self, duration: float) -> None:
        """Async sleep the given duration in seconds."""
        import asyncio

        await asyncio.sleep(duration)

    async def click(
        self,
        x: int,
        y: int,
        client: Any = None,
    ) -> dict[str, Any]:
        """Click at (x, y) with human-like pre-click movement.

        Args:
            x: Target X coordinate.
            y: Target Y coordinate.
            client: Optional CDP client for dispatching mouse events.

        Returns:
            Result dict with keys::

                {"status": "ok" | "error",
                 "x": int, "y": int,
                 "move_events": int,
                 "duration_ms": float}
        """
        start_time = time.monotonic()

        # First move to the target
        move_events = await self.move_to(x, y, client=client)

        # Small pre-click pause (human-like)
        pause_ms = random.uniform(30, 80)
        if client is not None:
            await self._sleep(pause_ms / 1000.0)

        # Mouse down
        press_params = self._make_dispatch_params("mousePressed", x, y)
        if client is not None:
            await client._send_command("Input.dispatchMouseEvent", press_params)

        # Inter-click delay
        release_delay = random.uniform(20, 50) / 1000.0
        if client is not None:
            await self._sleep(release_delay)

        # Mouse up
        release_params = self._make_dispatch_params("mouseReleased", x, y)
        if client is not None:
            await client._send_command("Input.dispatchMouseEvent", release_params)

        duration_ms = (time.monotonic() - start_time) * 1000

        return {
            "status": "ok",
            "x": x,
            "y": y,
            "move_events": len(move_events) if isinstance(move_events, list) else 0,
            "duration_ms": round(duration_ms, 2),
        }

    # ── Bezier path generation ────────────────────────────────────────

    @staticmethod
    def _generate_bezier_path(
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        num_steps: int = 20,
    ) -> list[tuple[float, float]]:
        """Generate a cubic Bezier curve path from start to end.

        Control points are chosen to produce a natural curve with slight
        curvature, avoiding perfectly straight lines.

        Args:
            start_x, start_y: Starting coordinates.
            end_x, end_y: Target coordinates.
            num_steps: Number of intermediate points (including endpoints).

        Returns:
            List of (x, y) tuples forming the Bezier path.
        """
        # Choose control points with slight natural curvature
        dx = end_x - start_x
        dy = end_y - start_y
        offset = max(abs(dx), abs(dy)) * 0.2

        cp1_x = start_x + dx * 0.25 + random.uniform(-offset, offset)
        cp1_y = start_y + dy * 0.25 + random.uniform(-offset, offset)
        cp2_x = start_x + dx * 0.75 + random.uniform(-offset, offset)
        cp2_y = start_y + dy * 0.75 + random.uniform(-offset, offset)

        # Evaluate cubic Bezier at t in [0, 1]
        path: list[tuple[float, float]] = []
        for i in range(num_steps):
            t = i / (num_steps - 1) if num_steps > 1 else 0.0
            inv_t = 1.0 - t

            x = (
                inv_t ** 3 * start_x
                + 3 * inv_t ** 2 * t * cp1_x
                + 3 * inv_t * t ** 2 * cp2_x
                + t ** 3 * end_x
            )
            y = (
                inv_t ** 3 * start_y
                + 3 * inv_t ** 2 * t * cp1_y
                + 3 * inv_t * t ** 2 * cp2_y
                + t ** 3 * end_y
            )
            path.append((x, y))

        return path

    @staticmethod
    def _add_jitter(
        point: tuple[float, float],
        amplitude: float = JITTER_AMPLITUDE,
    ) -> tuple[float, float]:
        """Add random jitter to a control point.

        Args:
            point: (x, y) coordinate.
            amplitude: Maximum pixel offset in each axis (default 2.0).

        Returns:
            Jittered (x, y) coordinate.
        """
        jx = point[0] + random.uniform(-amplitude, amplitude)
        jy = point[1] + random.uniform(-amplitude, amplitude)
        return (jx, jy)

    @staticmethod
    def _should_overshoot() -> bool:
        """Return True ~15% of the time (overshoot probability)."""
        return random.random() < BehavioralMouse.OVERSHOOT_PROBABILITY

    @staticmethod
    def _compute_overshoot_target(
        end_x: float,
        end_y: float,
        overshoot_px: int = 10,
    ) -> tuple[float, float]:
        """Compute an overshoot point beyond the target.

        Args:
            end_x, end_y: Original target coordinates.
            overshoot_px: How many pixels beyond to overshoot (default 10).

        Returns:
            (overshoot_x, overshoot_y) coordinates.
        """
        angle = random.uniform(0, 2 * math.pi)
        ox = end_x + math.cos(angle) * overshoot_px
        oy = end_y + math.sin(angle) * overshoot_px
        return (ox, oy)

    # ── Timing ────────────────────────────────────────────────────────

    @staticmethod
    def _inter_step_delays(
        num_steps: int,
        base_duration_ms: int,
    ) -> list[float]:
        """Generate per-step delays (ms) that sum to approximately base_duration_ms.

        Delays are distributed with easing: shorter at the start/end, longer
        in the middle (simulating acceleration/deceleration).

        Args:
            num_steps: Number of movement steps.
            base_duration_ms: Total desired movement duration in ms.

        Returns:
            List of *num_steps* delays in seconds.
        """
        if num_steps <= 1:
            return [base_duration_ms / 1000.0]

        # Use eased weights (sine easing for acceleration/deceleration)
        weights: list[float] = []
        for i in range(num_steps):
            t = i / (num_steps - 1)
            # Bell-like curve: low at edges, high in middle
            weight = math.sin(t * math.pi) + 0.1
            weights.append(weight)

        total_weight = sum(weights)
        delays_s: list[float] = []
        for w in weights:
            delay_ms = (w / total_weight) * base_duration_ms
            delays_s.append(delay_ms / 1000.0)

        return delays_s

    # ── Raw fallthrough ───────────────────────────────────────────────

    @staticmethod
    def _raw_move_to(x: int, y: int) -> list[dict[str, Any]]:
        """Return a single immediate mouse-move event (no humanization).

        Used when enabled=False.
        """
        return [
            {
                "type": "mouseMoved",
                "x": x,
                "y": y,
                "button": "none",
            }
        ]

    @staticmethod
    def _make_dispatch_params(
        event_type: str,
        x: int,
        y: int,
        button: str = "left",
        click_count: int = 1,
    ) -> dict[str, Any]:
        """Build ``Input.dispatchMouseEvent`` parameter dict.

        Args:
            event_type: One of ``"mousePressed"``, ``"mouseReleased"``,
                       ``"mouseMoved"``.
            x, y: Coordinates.
            button: ``"left"``, ``"right"``, or ``"middle"``.
            click_count: Number of clicks (for double-click).

        Returns:
            CDP-compatible parameter dict.
        """
        return {
            "type": event_type,
            "x": x,
            "y": y,
            "button": button,
            "clickCount": click_count,
        }
