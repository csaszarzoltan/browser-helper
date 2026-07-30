"""
Human Typing Patterns Middleware — log-normal delay between keystrokes.

Replaces uniform ``Input.insertText`` with human-like typing that dispatches
individual key events (keyDown, keyPress, keyUp) with inter-key delays
drawn from a log-normal distribution.

Two modes:
    - "human"  — log-normal inter-key delays, configurable CPM range
    - "raw"    — straight pass-through, no delay between keystrokes

REST API:
    POST /typing/config  → configure enabled flag + CPM min/max
    GET  /typing/config  → return current configuration
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Typing Configuration
# ---------------------------------------------------------------------------


class TypingConfig:
    """Configuration for human typing behavior.

    Attributes:
        enabled:  When False, typing falls through to raw CDP dispatch.
        cpm_min:  Lower bound of characters-per-minute range (default 200).
        cpm_max:  Upper bound of characters-per-minute range (default 400).
    """

    def __init__(
        self,
        enabled: bool = True,
        cpm_min: int = 200,
        cpm_max: int = 400,
    ) -> None:
        self.enabled = enabled
        self.cpm_min = cpm_min
        self.cpm_max = cpm_max
        self._validate()

    def _validate(self) -> None:
        """Raise ValueError if CPM bounds are invalid."""
        if self.cpm_min > self.cpm_max:
            raise ValueError(
                f"cpm_min ({self.cpm_min}) must not exceed cpm_max ({self.cpm_max})"
            )
        if self.cpm_min < 1:
            raise ValueError(f"cpm_min must be >= 1, got {self.cpm_min}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "cpm_min": self.cpm_min,
            "cpm_max": self.cpm_max,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TypingConfig:
        return cls(
            enabled=data.get("enabled", True),
            cpm_min=data.get("cpm_min", 200),
            cpm_max=data.get("cpm_max", 400),
        )

    def __repr__(self) -> str:
        return (
            f"TypingConfig(enabled={self.enabled}, "
            f"cpm_min={self.cpm_min}, cpm_max={self.cpm_max})"
        )


# ---------------------------------------------------------------------------
# Behavioral Typing Middleware
# ---------------------------------------------------------------------------


class BehavioralTyping:
    """Middleware that types text with human-like inter-key delays.

    Dispatches each character via ``Input.dispatchKeyEvent`` (keyDown,
    keyPress, keyUp sequence) instead of the uniform ``Input.insertText``.

    Usage::

        typing = BehavioralTyping(TypingConfig(enabled=True, cpm_min=200, cpm_max=400))
        await typing.type_text("Hello, world!", mode="human")
        await typing.type_text("Instant text", mode="raw")
    """

    MODE_HUMAN = "human"
    MODE_RAW = "raw"

    def __init__(self, config: TypingConfig | None = None) -> None:
        self._config = config or TypingConfig()

    # ── Config ─────────────────────────────────────────────────────────

    @property
    def config(self) -> TypingConfig:
        """Return the current typing configuration."""
        return self._config

    @config.setter
    def config(self, value: TypingConfig) -> None:
        self._config = value

    # ── Public API ─────────────────────────────────────────────────────

    async def type_text(
        self,
        text: str,
        mode: str = MODE_HUMAN,
        client: Any = None,
    ) -> dict[str, Any]:
        """Type *text* with human-like delays (``mode="human"``) or raw pass-through.

        Args:
            text:   The string to type.
            mode:   ``"human"`` (log-normal delays) or ``"raw"`` (no delay).
            client: Optional CDP client to dispatch key events.  When None,
                    delays are still generated but not dispatched.

        Returns:
            dict with keys::

                {"status": "ok"|"error",
                 "chars": int,
                 "mode": str,
                 "total_delay_ms": float}
        """
        raise NotImplementedError("BehavioralTyping.type_text")  # TODO: P1-3

    # ── Delay generation ───────────────────────────────────────────────

    def _generate_delays(self, char_count: int) -> list[float]:
        """Generate log-normally distributed inter-key delays (seconds).

        Each delay is sampled from ``LogNormal(mu, sigma)`` where mu and
        sigma are calibrated so that 95 % of delays fall inside the
        configured CPM range.

        Args:
            char_count: Number of characters to generate delays for.

        Returns:
            List of *char_count* delays in seconds.
        """
        raise NotImplementedError("BehavioralTyping._generate_delays")  # TODO: P1-3

    def _compute_cpm(self, delays: list[float]) -> float:
        """Compute effective characters-per-minute from a list of delays.

        Args:
            delays: Inter-key delays in seconds (length = N-1 for N chars,
                    or N for N chars if the last delay represents total
                    typing time).

        Returns:
            Effective CPM value.
        """
        raise NotImplementedError("BehavioralTyping._compute_cpm")  # TODO: P1-3

    # ── Key event dispatch helpers ─────────────────────────────────────

    @staticmethod
    def _key_identifier(char: str) -> dict[str, Any]:
        """Map a single character to its CDP ``Input.dispatchKeyEvent`` parameters.

        Returns a dict with keys::

            {"key": str, "code": str, "text": str | None,
             "windowsVirtualKeyCode": int | None,
             "nativeVirtualKeyCode": int | None}
        """
        raise NotImplementedError("BehavioralTyping._key_identifier")  # TODO: P1-3

    @staticmethod
    async def _dispatch_key_event(
        client: Any,
        event_type: str,
        key_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a single CDP ``Input.dispatchKeyEvent``.

        Args:
            client:     CDP client with ``_send_command(method, params)``.
            event_type: One of ``"keyDown"``, ``"keyPress"``, ``"keyUp"``.
            key_params: Parameters returned by ``_key_identifier()``.

        Returns:
            CDP command result.
        """
        raise NotImplementedError("BehavioralTyping._dispatch_key_event")  # TODO: P1-3

    @staticmethod
    async def _dispatch_char_sequence(
        client: Any,
        char: str,
        delay_before: float = 0.0,
    ) -> None:
        """Dispatch keyDown → keyPress → keyUp for a single character.

        Args:
            client:       CDP client.
            char:         Single character to type.
            delay_before: Seconds to wait before this character.
        """
        raise NotImplementedError("BehavioralTyping._dispatch_char_sequence")  # TODO: P1-3
