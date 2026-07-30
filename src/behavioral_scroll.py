"""
Human-like scrolling middleware for browser-helper (P1-5).

Provides configurable scroll behaviors ("smooth", "jagged", "auto")
that simulate real user scrolling patterns. Used as a middleware layer
wrapping CDP's window.scrollTo / Input.dispatchMouseWheelEvent.

PRE-DEV STUB — All behavioral methods raise NotImplementedError.

Usage:
    from behavioral_scroll import BehavioralScroll, InvalidModeError

    bs = BehavioralScroll(client)
    events = await bs.scroll(target_y=2000)

# === Pre-Development Contract ===
# Interface tests (pass with stub):
#   - class BehavioralScroll exists
#   - InvalidModeError exists
#   - config property, update_config(), get_config(), scroll() exist
# Behavioral tests (fail with NotImplementedError):
#   - smooth mode produces continuous variable-speed events
#   - jagged mode includes pauses between steps
#   - auto mode selects smooth for >1000px, jagged for <500px
#   - step sizes randomize within 100-800px range
#   - disabled mode falls through to raw CDP
#   - pause timing follows log-normal distribution
"""

from __future__ import annotations

import math
import random
from typing import Any


class InvalidModeError(ValueError):
    """Raised when an invalid scroll mode string is supplied."""

    def __init__(self, mode: str):
        super().__init__(f"Invalid scroll mode: {mode!r}. Expected one of: smooth, jagged, auto")
        self.invalid_mode = mode


VALID_MODES = frozenset({"smooth", "jagged", "auto"})
DEFAULT_STEP_MIN = 100
DEFAULT_STEP_MAX = 800


class ScrollStepEvent:
    """Single scroll step event produced by BehavioralScroll.

    Represents one atomic scroll action, suitable for dispatching via
    Input.dispatchMouseWheelEvent or Runtime.evaluate window.scrollTo.
    """

    def __init__(self, delta_y: int, delay_ms: float, pause_after: float = 0.0):
        self.delta_y = delta_y
        self.delay_ms = delay_ms
        self.pause_after = pause_after

    def to_dict(self) -> dict[str, Any]:
        return {
            "delta_y": self.delta_y,
            "delay_ms": self.delay_ms,
            "pause_after": self.pause_after,
        }


class BehavioralScroll:
    """Middleware providing human-like scrolling behavior.

    Parameters
    ----------
    client : optional
        CDP client instance. When provided, the middleware can dispatch
        real scroll commands (not required for step-generation tests).
    settings_manager : optional
        SettingsManager instance for persisting config across restarts.

    Attributes
    ----------
    enabled : bool
        When False, scroll() falls through to a single immediate event.
    mode : str
        One of "smooth", "jagged", "auto".
    step_min : int
        Minimum px per scroll event (default 100).
    step_max : int
        Maximum px per scroll event (default 800).
    """

    def __init__(self, client=None, settings_manager=None):
        self._client = client
        self._settings = settings_manager
        self._enabled = True
        self._mode = "smooth"
        self._step_min = DEFAULT_STEP_MIN
        self._step_max = DEFAULT_STEP_MAX
        self._config: dict[str, Any] = {}

    # ── Config management ────────────────────────────────────────

    @property
    def config(self) -> dict[str, Any]:
        """Current scroll configuration as a dict."""
        return {
            "enabled": self._enabled,
            "mode": self._mode,
            "step_min": self._step_min,
            "step_max": self._step_max,
        }

    def get_config(self) -> dict[str, Any]:
        """Return current config (alias for .config)."""
        raise NotImplementedError("get_config — config serialization")

    def update_config(
        self,
        enabled: bool | None = None,
        mode: str | None = None,
        step_min: int | None = None,
        step_max: int | None = None,
    ) -> dict[str, Any]:
        """Update one or more config fields and return the new config.

        Raises InvalidModeError when mode is not one of smooth/jagged/auto.
        Raises ValueError when step bounds are out of 100-800 range.
        """
        raise NotImplementedError("update_config — config mutation + validation")

    # ── Scroll execution ─────────────────────────────────────────

    async def scroll(
        self,
        target_y: int,
        current_y: int = 0,
        client=None,
    ) -> list[dict[str, Any]]:
        """Execute a human-like scroll towards *target_y*.

        Returns a list of ScrollStepEvent dicts describing each scroll
        event that would be dispatched. The *client* argument allows
        overriding or injecting a CDP client per-call.

        When *enabled* is False, returns a single immediate-scroll event
        (no humanization).
        """
        raise NotImplementedError("scroll — human-like scroll orchestration")

    # ── Mode-specific generators ─────────────────────────────────

    @staticmethod
    def _smooth_scroll(
        distance: int,
        step_min: int = DEFAULT_STEP_MIN,
        step_max: int = DEFAULT_STEP_MAX,
    ) -> list[ScrollStepEvent]:
        """Generate smooth scroll events with ease-in-out acceleration.

        Steps start small, accelerate to larger deltas in the middle,
        then decelerate near the end. Variable delay between events
        simulates real mouse-wheel inertia.
        """
        raise NotImplementedError("_smooth_scroll — ease-in-out acceleration curve")

    @staticmethod
    def _jagged_scroll(
        distance: int,
        step_min: int = DEFAULT_STEP_MIN,
        step_max: int = DEFAULT_STEP_MAX,
    ) -> list[ScrollStepEvent]:
        """Generate jagged scroll events with reading-simulation pauses.

        Each step is followed by a log-normal distributed pause
        (scroll-stop-pause pattern). Pause length varies to simulate
        the user reading content before scrolling again.
        """
        raise NotImplementedError("_jagged_scroll — scroll-stop-pause pattern")

    @staticmethod
    def _auto_mode(
        distance: int,
        step_min: int = DEFAULT_STEP_MIN,
        step_max: int = DEFAULT_STEP_MAX,
    ) -> list[ScrollStepEvent]:
        """Auto-select mode based on scroll distance.

        Returns smooth events for distances > 1000px.
        Returns jagged events for distances < 500px.
        For distances 500-1000px, uses a weighted random between the two.
        """
        raise NotImplementedError("_auto_mode — distance-based mode selection")

    # ── Timing helpers ───────────────────────────────────────────

    @staticmethod
    def _log_normal_pause(mu: float = 6.0, sigma: float = 0.5) -> float:
        """Generate a log-normal distributed pause duration in milliseconds.

        Default parameters (mu=6.0, sigma=0.5) produce pauses roughly in
        the range 150-1200ms with a right-skewed distribution, simulating
        reading time between scroll steps.
        """
        raise NotImplementedError("_log_normal_pause — log-normal random pause")

    @staticmethod
    def _random_step(min_px: int = DEFAULT_STEP_MIN, max_px: int = DEFAULT_STEP_MAX) -> int:
        """Return a random step size within [min_px, max_px]."""
        raise NotImplementedError("_random_step — randomised scroll step")

    # ── Raw fallthrough ──────────────────────────────────────────

    @staticmethod
    def _raw_scroll_event(distance: int) -> list[dict[str, Any]]:
        """Return a single immediate scroll event (no humanization).

        Used when enabled=False or as a base primitive.
        """
        raise NotImplementedError("_raw_scroll_event — fallthrough to raw CDP")


# ── Exceptions ────────────────────────────────────────────────────


class ScrollConfigError(Exception):
    """Generic configuration error for the BehavioralScroll module."""
