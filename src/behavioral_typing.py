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

import asyncio
import math
import random
from typing import Any

# Two-sided normal quantile for 95 % coverage — the log-normal is calibrated
# so that 95 % of sampled inter-key delays land inside the configured CPM range.
_Z95 = 1.959963985

# Non-printable / named keys: char → (key, code, windowsVirtualKeyCode).
# A char not in this table and not alphanumeric gets its own face value.
_NAMED_KEYS: dict[str, tuple[str, str, int]] = {
    "\n": ("Enter", "Enter", 13),
    "\r": ("Enter", "Enter", 13),
    "\t": ("Tab", "Tab", 9),
    " ": (" ", "Space", 32),
    "\b": ("Backspace", "Backspace", 8),
    "\x1b": ("Escape", "Escape", 27),
    "\x7f": ("Delete", "Delete", 46),
}

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
        effective_mode = mode
        if not self._config.enabled:
            # Disabled profile falls through to raw CDP dispatch.
            effective_mode = self.MODE_RAW

        if effective_mode not in (self.MODE_HUMAN, self.MODE_RAW):
            return {
                "status": "error",
                "chars": 0,
                "mode": effective_mode,
                "total_delay_ms": 0.0,
            }

        char_count = len(text)
        if char_count == 0:
            return {
                "status": "ok",
                "chars": 0,
                "mode": effective_mode,
                "total_delay_ms": 0.0,
            }

        # Human mode: N-1 inter-key gaps for N chars; first char has no preceding wait.
        delays = (
            self._generate_delays(char_count)
            if effective_mode == self.MODE_HUMAN
            else ([0.0] * (char_count - 1) if char_count > 1 else [])
        )

        total_delay = 0.0
        if client is not None:
            for index, char in enumerate(text):
                # Gaps are between chars: char 0 has no preceding gap.
                delay_before = 0.0 if index == 0 else delays[index - 1]
                await self._dispatch_char_sequence(client, char, delay_before)
                total_delay += delay_before

        return {
            "status": "ok",
            "chars": char_count,
            "mode": effective_mode,
            "total_delay_ms": total_delay * 1000.0,
        }

    # ── Delay generation ───────────────────────────────────────────────

    def _generate_delays(self, char_count: int) -> list[float]:
        """Generate log-normally distributed inter-key delays (seconds).

        Each delay is sampled from ``LogNormal(mu, sigma)`` where mu and
        sigma are calibrated so that 95 % of delays fall inside the
        configured CPM range.

        Args:
            char_count: Number of characters to generate delays for.

        Returns:
            List of ``max(0, char_count-1)`` delays in seconds.
            Empty for 0 or 1 character (no inter-key gap exists).
            The first character has no preceding delay; delays[i] is the
            gap before character i+1.
        """
        if char_count <= 1:
            return []

        # delay = 60 / cpm  →  cpm = 60 / delay.  Calibrate (mu, sigma) so that
        # 95 % of draws fall between the fast and slow ends of the CPM range.
        fast_delay = 60.0 / self._config.cpm_max
        slow_delay = 60.0 / self._config.cpm_min
        mu = (math.log(fast_delay) + math.log(slow_delay)) / 2.0
        sigma = (math.log(slow_delay) - math.log(fast_delay)) / (2.0 * _Z95)

        # A new Random per call keeps the draws independent of any caller state
        # while still being non-deterministic across sequences.
        rng = random.Random()
        return [rng.lognormvariate(mu, sigma) for _ in range(char_count - 1)]

    def _compute_cpm(self, delays: list[float]) -> float:
        """Compute effective characters-per-minute from a list of delays.

        Args:
            delays: Inter-key delays in seconds. Length is N-1 for N
                    characters (N>=1); empty for 0 or 1 character.

        Returns:
            Effective CPM as ``60 * (len(delays)+1) / sum(delays)``.
            Returns 0.0 for empty input. Raises ZeroDivisionError if
            sum(delays) == 0 for non-empty input (instant typing).

        Raises:
            ZeroDivisionError: if delays is non-empty and total time is zero.
        """
        if not delays:
            return 0.0
        total = sum(delays)
        if total == 0:
            raise ZeroDivisionError("total delay is zero")
        return 60.0 * (len(delays) + 1) / total

    # ── Key event dispatch helpers ─────────────────────────────────────

    @staticmethod
    def _key_identifier(char: str) -> dict[str, Any]:
        """Map a single character to its CDP ``Input.dispatchKeyEvent`` parameters.

        Returns a dict with keys::

            {"key": str, "code": str, "text": str | None,
             "windowsVirtualKeyCode": int | None,
             "nativeVirtualKeyCode": int | None}
        """
        named = _NAMED_KEYS.get(char)
        if named is not None:
            key, code, vk = named
            # Non-printing keys (Enter, Tab, Backspace) carry no text payload.
            # Space DOES: it is printable and inserting it is the whole point,
            # so it must send ``text=" "``. Measured against a real Chrome —
            # ``text=None`` is rejected with "Invalid parameters" (CDP types
            # ``text`` as a string, not nullable) and ``text=""`` inserts
            # nothing, so a space would silently vanish.
            return {
                "key": key,
                "code": code,
                "text": char if char.isprintable() else None,
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
            }

        if len(char) == 1 and char.isascii() and char.isalpha():
            code = f"Key{char.upper()}"
            vk = ord(char.upper())
            return {
                "key": char,
                "code": code,
                "text": char,
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
            }

        if len(char) == 1 and char.isascii() and char.isdigit():
            # Digits sit on the number row: "4" → code Digit4.
            code = f"Digit{char}"
            vk = ord(char)
            return {
                "key": char,
                "code": code,
                "text": char,
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
            }

        # Punctuation and non-ASCII: no dedicated key code exists, so the char
        # doubles as its own face value.  Shift is implied by the char itself.
        vk = ord(char) if len(char) == 1 and ord(char) < 256 else None
        return {
            "key": char,
            "code": "",
            "text": char,
            "windowsVirtualKeyCode": vk,
            "nativeVirtualKeyCode": vk,
        }

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
        params = dict(key_params)
        params["type"] = event_type
        # `text` is typed `string` by CDP, not nullable: sending JSON null is
        # rejected with "Invalid parameters". Strip the field entirely whenever
        # it is absent/None, and always on keyUp.
        if params.get("text") is None or event_type in ("keyUp", "rawKeyUp"):
            params.pop("text", None)
        return await client._send_command("Input.dispatchKeyEvent", params)

    @staticmethod
    async def _dispatch_char_sequence(
        client: Any,
        char: str,
        delay_before: float = 0.0,
    ) -> None:
        """Dispatch keyDown → keyUp for a single character.

        NOTE: ``keyPress`` is NOT a valid CDP ``Input.dispatchKeyEvent`` type.
        The protocol accepts ``keyDown``, ``keyUp``, ``rawKeyDown`` and
        ``char``. Sending ``keyPress`` makes Chrome answer
        ``-32602 Unexpected event type 'keyPress'``; the error was previously
        swallowed because each dispatch's result was discarded, so typing
        appeared to work while every character after the first raced an error.
        ``keyDown`` carrying ``text`` is what actually inserts the character.

        Args:
            client:       CDP client.
            char:         Single character to type.
            delay_before: Seconds to wait before this character.
        """
        if delay_before > 0:
            await asyncio.sleep(delay_before)

        params = BehavioralTyping._key_identifier(char)
        # keyDown alone inserts the character (it carries `text`); keyUp
        # completes the pair. There is no valid `keyPress` type in CDP.
        await BehavioralTyping._dispatch_key_event(client, "keyDown", params)
        await BehavioralTyping._dispatch_key_event(client, "keyUp", params)
