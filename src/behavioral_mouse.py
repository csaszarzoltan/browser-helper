"""
Human Mouse Movement Middleware (P1-2).

Provides Bezier-curve mouse paths with configurable speed profiles, overshoot,
and jitter. Wraps ``Input.dispatchMouseEvent`` for human-like pointer motion.

PRE-DEV STUB — All behavioral methods raise NotImplementedError.

Usage::

    from behavioral_mouse import BehavioralMouse, MouseConfig

    mouse = BehavioralMouse(MouseConfig(enabled=True, speed="normal"))
    await mouse.move_to(x=500, y=300)
    await mouse.click(x=500, y=300)
"""

from __future__ import annotations

from typing import Any


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
    SPEED_DURATIONS = {
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
        raise NotImplementedError("BehavioralMouse.move_to — not implemented yet")

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
        raise NotImplementedError("BehavioralMouse.click — not implemented yet")

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
        raise NotImplementedError(
            "BehavioralMouse._generate_bezier_path — not implemented yet"
        )

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
        raise NotImplementedError("BehavioralMouse._add_jitter — not implemented yet")

    @staticmethod
    def _should_overshoot() -> bool:
        """Return True ~15% of the time (overshoot probability)."""
        raise NotImplementedError(
            "BehavioralMouse._should_overshoot — not implemented yet"
        )

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
        raise NotImplementedError(
            "BehavioralMouse._compute_overshoot_target — not implemented yet"
        )

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
        raise NotImplementedError(
            "BehavioralMouse._inter_step_delays — not implemented yet"
        )

    # ── Raw fallthrough ───────────────────────────────────────────────

    @staticmethod
    def _raw_move_to(x: int, y: int) -> list[dict[str, Any]]:
        """Return a single immediate mouse-move event (no humanization).

        Used when enabled=False.
        """
        raise NotImplementedError("BehavioralMouse._raw_move_to — not implemented yet")

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
        raise NotImplementedError(
            "BehavioralMouse._make_dispatch_params — not implemented yet"
        )
