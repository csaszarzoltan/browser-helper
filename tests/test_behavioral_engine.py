"""Tests for behavioral_engine — HumanProfile + BehavioralEngine."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from behavioral_engine import BehavioralEngine, HumanProfile


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

    async def _evaluate(js):
        return {"status": "ok", "result": {"x": 100, "y": 200}}

    client.evaluate = _evaluate
    client.type_text = AsyncMock(return_value={"status": "ok"})
    return client


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
        await engine.type_text("#input", "ab")
        assert client._ws.send.call_count >= 2

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
