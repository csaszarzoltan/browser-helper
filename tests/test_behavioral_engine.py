"""Tests for behavioral_engine — HumanProfile + BehavioralEngine."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from behavioral_engine import BehavioralEngine, HumanProfile
from behavioral_typing import BehavioralTyping, TypingConfig

# ── HumanProfile Tests ─────────────────────────────────────────────────


class TestHumanProfile:
    """HumanProfile generation and determinism."""

    def test_default_profile(self):
        p = HumanProfile()
        assert p.enabled is True
        assert p.wpm_range == (45, 80)
        assert p.scroll_mode == "auto"

    def test_from_session_deterministic(self):
        """Same session_id → same profile every time."""
        p1 = HumanProfile.from_session("session-abc-123")
        p2 = HumanProfile.from_session("session-abc-123")
        assert p1.wpm_range == p2.wpm_range
        assert p1.mouse_gravity == p2.mouse_gravity
        assert p1.scroll_mode == p2.scroll_mode
        assert p1.speed_factor == p2.speed_factor

    def test_different_sessions_different_profiles(self):
        """Different session_ids → different profiles."""
        p1 = HumanProfile.from_session("session-aaa")
        p2 = HumanProfile.from_session("session-bbb")
        # At least one attribute should differ
        diffs = [
            p1.wpm_range != p2.wpm_range,
            p1.mouse_gravity != p2.mouse_gravity,
            p1.scroll_mode != p2.scroll_mode,
            p1.speed_factor != p2.speed_factor,
        ]
        assert any(diffs), "Expected different profiles for different sessions"

    def test_no_session_returns_default(self):
        p = HumanProfile.from_session(None)
        assert p.wpm_range == (45, 80)

    def test_wpm_range_reasonable(self):
        for _ in range(20):
            p = HumanProfile.from_session(f"test-{_}")
            assert 30 <= p.wpm_range[0] <= 100
            assert p.wpm_range[0] < p.wpm_range[1]

    def test_mouse_params_reasonable(self):
        for _ in range(20):
            p = HumanProfile.from_session(f"test-{_}")
            assert 5.0 <= p.mouse_gravity <= 15.0
            assert 1.0 <= p.mouse_wind <= 6.0


# ── BehavioralEngine Tests ────────────────────────────────────────────


def _mock_client(connected: bool = True):
    """Create a minimal mock CDPClient for testing."""
    client = MagicMock()
    client._connected = connected
    client._ws = AsyncMock() if connected else None
    client._message_id = 0
    client._sent: list[tuple[str, dict]] = []

    async def _evaluate(js):
        return {"status": "ok", "result": {"x": 100, "y": 200}}

    async def _send_command(method, params=None, **extra):
        client._sent.append((method, params or {}))
        return {}

    client.evaluate = _evaluate
    client._send_command = _send_command
    client.type_text = AsyncMock(return_value={"status": "ok"})
    return client


def _key_events(client):
    """All Input.dispatchKeyEvent params sent via _send_command."""
    return [p for m, p in client._sent if m == "Input.dispatchKeyEvent"]


class TestBehavioralEngine:
    """BehavioralEngine unit tests."""

    @pytest.mark.asyncio
    async def test_engine_initializes(self):
        client = _mock_client()
        engine = BehavioralEngine(client)
        assert engine.profile.enabled is True

    @pytest.mark.asyncio
    async def test_move_mouse_sends_cdp_events(self):
        client = _mock_client()
        engine = BehavioralEngine(client)
        engine._last_mouse_pos = (10.0, 10.0)
        await engine.move_mouse_to(200.0, 200.0)
        # Should have sent multiple mouseMoved events
        assert client._ws.send.call_count >= 2

    @pytest.mark.asyncio
    async def test_click_at_sends_press_and_release(self):
        client = _mock_client()
        engine = BehavioralEngine(client)
        await engine.click_at(150.0, 150.0)
        calls = [json.loads(c.args[0]) for c in client._ws.send.call_args_list]
        event_types = [c["params"]["type"] for c in calls if "params" in c]
        assert "mousePressed" in event_types
        assert "mouseReleased" in event_types

    @pytest.mark.asyncio
    async def test_type_text_sends_key_events(self):
        client = _mock_client()
        engine = BehavioralEngine(client)
        with patch("asyncio.sleep", new=AsyncMock()):
            await engine.type_text("#input", "ab")
        assert len(_key_events(client)) == 2 * 2

    @pytest.mark.asyncio
    async def test_scroll_sends_wheel_events(self):
        client = _mock_client()
        engine = BehavioralEngine(client)
        events = await engine.scroll(500)
        assert isinstance(events, list)
        assert client._ws.send.call_count >= 1

    @pytest.mark.asyncio
    async def test_disabled_profile_no_cdp(self):
        client = _mock_client()
        profile = HumanProfile(enabled=False)
        engine = BehavioralEngine(client, profile=profile)
        engine._last_mouse_pos = (0.0, 0.0)
        await engine.move_mouse_to(100.0, 100.0)
        # No CDP events when disabled
        assert client._ws.send.call_count == 0

    @pytest.mark.asyncio
    async def test_disconnected_client_no_cdp(self):
        client = _mock_client(connected=False)
        engine = BehavioralEngine(client)
        engine._last_mouse_pos = (0.0, 0.0)
        await engine.move_mouse_to(100.0, 100.0)
        # No crash when disconnected

    @pytest.mark.asyncio
    async def test_type_text_element_not_found(self):
        """Missing selector still returns the error dict, never raises."""

        async def _evaluate_none(js):
            return {"status": "ok", "result": None}

        client = _mock_client()
        client.evaluate = _evaluate_none
        engine = BehavioralEngine(client)
        result = await engine.type_text("#missing", "ab")
        assert result["status"] == "error"
        assert "#missing" in result["error"]
        assert _key_events(client) == []

    @pytest.mark.asyncio
    async def test_type_text_disabled_profile_delegates(self):
        """profile.enabled=False still delegates to client.type_text."""
        client = _mock_client()
        engine = BehavioralEngine(client, profile=HumanProfile(enabled=False))
        result = await engine.type_text("#input", "ab")
        assert result == {"status": "ok"}
        client.type_text.assert_awaited_once_with("#input", "ab")
        assert _key_events(client) == []


# ── SPEC-3: engine delegates typing to BehavioralTyping ────────────────────


class TestBehavioralTypingDelegation:
    """The engine's typing path routes through BehavioralTyping (SPEC-3)."""

    @pytest.mark.asyncio
    async def test_three_events_per_char_single_sender(self):
        """behavioral_typing: engine emits exactly 3 events/char via _send_command."""
        from unittest.mock import AsyncMock as _AM

        client = _mock_client()
        engine = BehavioralEngine(client)
        with patch("asyncio.sleep", new=_AM()):
            result = await engine.type_text("#input", "Hi! A")
        keys = _key_events(client)
        assert result == {
            "status": "ok",
            "operation": "behavioral_type",
            "result": {"chars": 5},
        }
        assert len(keys) == 2 * 5
        # Single sender: nothing went through the old fire-and-forget ws.send.
        ws_payloads = [json.loads(c.args[0]) for c in client._ws.send.call_args_list]
        ws_keys = [p for p in ws_payloads if p.get("method") == "Input.dispatchKeyEvent"]
        assert ws_keys == []

    @pytest.mark.asyncio
    async def test_backspace_named_key(self):
        """backspace: user-supplied '\\b' dispatches as Backspace."""
        client = _mock_client()
        engine = BehavioralEngine(client)
        with patch("asyncio.sleep", new=AsyncMock()):
            await engine.type_text("#input", "a\bb")
        keys = _key_events(client)
        assert len(keys) == 2 * 3
        downs = [p for p in keys if p.get("type") == "keyDown"]
        assert [p["key"] for p in downs] == ["a", "Backspace", "b"]
        vk = next(
            p for p in downs if p["key"] == "Backspace"
        )["windowsVirtualKeyCode"]
        assert vk == 8

    @pytest.mark.asyncio
    async def test_no_modifiers_field(self):
        """Uppercase/shifted chars carry face-value text, no modifiers field."""
        client = _mock_client()
        engine = BehavioralEngine(client)
        with patch("asyncio.sleep", new=AsyncMock()):
            await engine.type_text("#input", "H!")
        keys = _key_events(client)
        assert len(keys) == 2 * 2
        assert all("modifiers" not in p for p in keys)
        downs = [p for p in keys if p.get("type") == "keyDown"]
        assert [p.get("text") for p in downs] == ["H", "!"]

    def test_speed_factor_translation(self):
        """speed_factor: wpm_range * 5 * speed_factor becomes the CPM range."""
        profile = HumanProfile(wpm_range=(40, 70), speed_factor=0.7)
        engine = BehavioralEngine(None, profile=profile)
        assert engine.typing.config.cpm_min == round(40 * 5 * 0.7)
        assert engine.typing.config.cpm_max == round(70 * 5 * 0.7)
        assert engine.typing.config.cpm_min == 140
        assert engine.typing.config.cpm_max == 245

    def test_speed_factor_translation_default_profile(self):
        """Default profile (45,80) @ 1.0 produces (225, 400)."""
        engine = BehavioralEngine(None, profile=HumanProfile())
        assert (engine.typing.config.cpm_min, engine.typing.config.cpm_max) == (225, 400)

    def test_speed_factor_translation_clamped(self):
        """Degenerate profiles clamp to cpm_min <= cpm_max, cpm >= 1."""
        engine = BehavioralEngine(
            None, profile=HumanProfile(wpm_range=(0, 0), speed_factor=0.0)
        )
        assert engine.typing.config.cpm_min >= 1
        assert engine.typing.config.cpm_min <= engine.typing.config.cpm_max

    @pytest.mark.asyncio
    async def test_raw_mode_disabled_typing_still_dispatches(self):
        """raw_mode: TypingConfig(enabled=False) still dispatches 3/char, no gap."""
        client = _mock_client()
        engine = BehavioralEngine(
            client,
            profile=HumanProfile(),
            typing_config=TypingConfig(enabled=False),
        )
        gaps: list[float] = []
        # Resolve the real implementation BEFORE patching: accessing it later
        # would return the patched stand-in.  It is a staticmethod, so it is
        # already an unbound function here.
        orig_seq = BehavioralTyping._dispatch_char_sequence

        async def _record_seq(c, char, delay_before=0.0):
            gaps.append(delay_before)
            await orig_seq(c, char, 0.0)

        with (
            patch("asyncio.sleep", new=AsyncMock()),
            patch.object(
                BehavioralTyping,
                "_dispatch_char_sequence",
                staticmethod(_record_seq),
            ),
        ):
            result = await engine.type_text("#input", "Hi")
        keys = _key_events(client)
        assert result["status"] == "ok"
        assert len(keys) == 2 * 2
        # Raw mode: no inter-key delay between the two chars.
        assert gaps == [0.0, 0.0]
