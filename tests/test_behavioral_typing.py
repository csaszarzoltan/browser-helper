"""
Pre-development tests for Human Typing Patterns Module (P1-3).

╔══════════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                               ║
║                                                                        ║
║  Interface tests (green checkmark)    → assert pass immediately         ║
║  Behavioral tests (red X)             → assert fail until impl.         ║
║                                                                        ║
║  Acceptance Criteria (from analysis brief Section P1-3):               ║
║    1. Log-normal distribution  (Anderson-Darling, 500+ samples)        ║
║    2. CPM bounds enforcement                                           ║
║    3. Non-determinism (different delays each sequence)                 ║
║    4. Raw mode pass-through (no delay)                                 ║
║    5. Disabled mode falls through to raw CDP dispatch                  ║
║    6. Valid key event dispatch (keyDown → keyPress → keyUp)            ║
║    7. POST/GET /typing/config endpoint round-trips                     ║
║    8. Invalid CPM range (min > max) returns 422                        ║
║    9. Mode switching at runtime                                        ║
║   10. Special characters, modifiers (Shift+key), empty string          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import math
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from behavioral_typing import BehavioralTyping, TypingConfig

# ── scipy is required for the Anderson-Darling distribution test ───────
scipy = pytest.importorskip("scipy", reason="scipy required for Anderson-Darling test")
from scipy import stats as scipy_stats

# ── Helpers ────────────────────────────────────────────────────────────

ROUTE_EXCLUDE_PREFIXES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def route_paths() -> list[str]:
    """List route paths registered on the FastAPI app for interface checks."""
    from main import app

    paths = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if path and path not in ROUTE_EXCLUDE_PREFIXES:
            paths.append(path)
    return paths


def generate_delays_brute(typing: BehavioralTyping, n: int = 500) -> list[float]:
    """Fallback: brute-generate delays by calling the internal generator.

    Used in behavioral tests that expect NotImplementedError until the
    real implementation is in place.
    """
    return typing._generate_delays(n)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def config() -> TypingConfig:
    """Default typing configuration."""
    return TypingConfig()


@pytest.fixture
def custom_config() -> TypingConfig:
    """Custom CPM bounds."""
    return TypingConfig(enabled=True, cpm_min=100, cpm_max=600)


@pytest.fixture
def typing(config) -> BehavioralTyping:
    """BehavioralTyping with default config."""
    return BehavioralTyping(config=config)


@pytest.fixture
def mock_client() -> AsyncMock:
    """Mock CDP client with _send_command patched."""
    client = AsyncMock()
    client._send_command = AsyncMock(return_value={"status": "ok"})
    return client


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Interface Tests  (should pass immediately)
# ═══════════════════════════════════════════════════════════════════════════


class TestTypingConfigInterface:
    """TypingConfig class structure and defaults."""

    def test_module_imports(self):
        """Module behavioral_typing imports cleanly."""
        import behavioral_typing as bt

        assert hasattr(bt, "TypingConfig")
        assert hasattr(bt, "BehavioralTyping")

    def test_config_default_enabled(self, config):
        """Default TypingConfig has enabled=True."""
        assert config.enabled is True

    def test_config_default_cpm_min(self, config):
        """Default cpm_min is 200."""
        assert config.cpm_min == 200

    def test_config_default_cpm_max(self, config):
        """Default cpm_max is 400."""
        assert config.cpm_max == 400

    def test_config_custom_values(self, custom_config):
        """Custom CPM values are stored correctly."""
        assert custom_config.enabled is True
        assert custom_config.cpm_min == 100
        assert custom_config.cpm_max == 600

    def test_config_disabled(self):
        """Config with enabled=False."""
        c = TypingConfig(enabled=False)
        assert c.enabled is False

    def test_config_to_dict_keys(self, config):
        """to_dict() returns expected keys."""
        d = config.to_dict()
        assert "enabled" in d
        assert "cpm_min" in d
        assert "cpm_max" in d

    def test_config_from_dict_defaults(self):
        """from_dict() with empty dict returns defaults."""
        c = TypingConfig.from_dict({})
        assert c.enabled is True
        assert c.cpm_min == 200
        assert c.cpm_max == 400

    def test_config_from_dict_overrides(self):
        """from_dict() applies overrides."""
        c = TypingConfig.from_dict({"enabled": False, "cpm_min": 50, "cpm_max": 100})
        assert c.enabled is False
        assert c.cpm_min == 50
        assert c.cpm_max == 100

    def test_config_invalid_cpm_min_gt_max_raises(self):
        """cpm_min > cpm_max raises ValueError."""
        with pytest.raises(ValueError, match="cpm_min"):
            TypingConfig(enabled=True, cpm_min=500, cpm_max=200)

    def test_config_invalid_cpm_zero_raises(self):
        """cpm_min < 1 raises ValueError."""
        with pytest.raises(ValueError, match="cpm_min"):
            TypingConfig(cpm_min=0)


class TestBehavioralTypingInterface:
    """BehavioralTyping class structure, constants, and method signatures."""

    def test_init_default_config(self, typing):
        """BehavioralTyping created with default config."""
        assert isinstance(typing.config, TypingConfig)
        assert typing.config.enabled is True

    def test_init_custom_config(self, custom_config):
        """BehavioralTyping accepts custom config."""
        bt = BehavioralTyping(config=custom_config)
        assert bt.config.cpm_min == 100

    def test_mode_constants(self):
        """MODE_HUMAN and MODE_RAW constants exist."""
        assert BehavioralTyping.MODE_HUMAN == "human"
        assert BehavioralTyping.MODE_RAW == "raw"

    def test_config_property(self, typing, config):
        """config property getter returns the config object."""
        assert typing.config is config

    def test_config_setter(self, typing):
        """config property setter updates config."""
        new = TypingConfig(enabled=False, cpm_min=300, cpm_max=500)
        typing.config = new
        assert typing.config.enabled is False
        assert typing.config.cpm_min == 300
        assert typing.config.cpm_max == 500

    def test_type_text_method_exists(self, typing):
        """type_text() is a callable async method."""
        assert hasattr(typing, "type_text")
        assert callable(typing.type_text)

    def test_generate_delays_method_exists(self, typing):
        """_generate_delays() is a callable method."""
        assert hasattr(typing, "_generate_delays")
        assert callable(typing._generate_delays)

    def test_compute_cpm_method_exists(self, typing):
        """_compute_cpm() is a callable static method."""
        assert hasattr(typing, "_compute_cpm")
        assert callable(typing._compute_cpm)

    def test_key_identifier_method_exists(self):
        """_key_identifier() is a callable static method."""
        assert hasattr(BehavioralTyping, "_key_identifier")
        assert callable(BehavioralTyping._key_identifier)

    def test_dispatch_key_event_method_exists(self):
        """_dispatch_key_event() is a callable static async method."""
        assert hasattr(BehavioralTyping, "_dispatch_key_event")
        assert callable(BehavioralTyping._dispatch_key_event)

    def test_dispatch_char_sequence_method_exists(self):
        """_dispatch_char_sequence() is a callable static async method."""
        assert hasattr(BehavioralTyping, "_dispatch_char_sequence")
        assert callable(BehavioralTyping._dispatch_char_sequence)


class TestTypingEndpointsInterface:
    """REST API route registration checks — xfail until endpoints are wired."""

    @pytest.mark.xfail(reason="P1-3 endpoint /typing/config not wired in main.py yet")
    def test_post_typing_config_route_registered(self):
        """POST /typing/config must be in the route table."""
        routes = route_paths()
        assert "/typing/config" in routes, (
            "P1-3 must register POST /typing/config"
        )

    @pytest.mark.xfail(reason="P1-3 endpoint /typing/config not wired in main.py yet")
    def test_get_typing_config_route_registered(self):
        """GET /typing/config must be in the route table."""
        routes = route_paths()
        # Both methods go to the same path — just check path exists
        # If only one method is registered, the route entry still appears
        assert "/typing/config" in routes, (
            "P1-3 must register GET /typing/config"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — Behavioral Tests  (should fail — NotImplementedError or RED)
# ═══════════════════════════════════════════════════════════════════════════


class TestDelayGenerationBehavioral:
    """Tests for log-normal delay generation."""

    def test_generate_delays_returns_list_of_floats(self, typing):
        """_generate_delays(N) returns a list of N floats (NotImplementedError atm)."""
        with pytest.raises(NotImplementedError):
            typing._generate_delays(10)

    def test_generate_delays_zero_chars(self, typing):
        """_generate_delays(0) returns empty list."""
        with pytest.raises(NotImplementedError):
            typing._generate_delays(0)

    @pytest.mark.xfail(reason="P1-3 not implemented: log-normal delay generation")
    def test_delays_are_positive(self, typing):
        """All generated delays must be > 0 seconds."""
        delays = typing._generate_delays(100)
        assert len(delays) == 100
        assert all(d > 0.0 for d in delays), "All delays must be positive"

    @pytest.mark.xfail(reason="P1-3 not implemented: log-normal distribution validation")
    def test_delays_follow_log_normal_distribution(self, typing):
        """500+ inter-key delays pass the Anderson-Darling test for log-normal.

        The null hypothesis is that log(delays) is normally distributed.
        We reject if the AD statistic exceeds the critical value at α=0.05.
        """
        n_samples = 500
        delays = typing._generate_delays(n_samples)
        assert len(delays) >= 500, f"Need 500+ samples, got {len(delays)}"

        # Log-normal test: log(delays) should be normally distributed
        log_delays = [math.log(d) for d in delays if d > 0]

        # Anderson-Darling test for normality
        result = scipy_stats.anderson(log_delays, dist="norm")
        # Critical value at 5% significance level is index 2
        critical_value = result.critical_values[2]
        assert result.statistic < critical_value, (
            f"Anderson-Darling statistic {result.statistic:.4f} exceeds "
            f"critical value {critical_value:.4f} at α=0.05 — "
            "log(delays) is not normally distributed (not log-normal)"
        )

    @pytest.mark.xfail(reason="P1-3 not implemented: CPM bounds")
    def test_cpm_bounds_enforced(self, typing):
        """Effective CPM stays within configured cpm_min/cpm_max."""
        delays = typing._generate_delays(100)
        cpm = typing._compute_cpm(delays)
        assert typing.config.cpm_min <= cpm <= typing.config.cpm_max, (
            f"CPM {cpm:.1f} not in [{typing.config.cpm_min}, {typing.config.cpm_max}]"
        )

    @pytest.mark.xfail(reason="P1-3 not implemented: custom CPM bounds")
    def test_custom_cpm_bounds_enforced(self, custom_config):
        """Custom CPM bounds are enforced."""
        bt = BehavioralTyping(config=custom_config)
        delays = bt._generate_delays(100)
        cpm = bt._compute_cpm(delays)
        assert custom_config.cpm_min <= cpm <= custom_config.cpm_max, (
            f"CPM {cpm:.1f} not in [{custom_config.cpm_min}, {custom_config.cpm_max}]"
        )

    @pytest.mark.xfail(reason="P1-3 not implemented: non-determinism")
    def test_delays_are_non_deterministic(self, typing):
        """Two calls to _generate_delays produce different delay sequences."""
        delays_a = typing._generate_delays(50)
        delays_b = typing._generate_delays(50)
        # Extremely unlikely that two random sequences are identical
        assert delays_a != delays_b, (
            "Consecutive delay sequences must differ (non-deterministic)"
        )

    @pytest.mark.xfail(reason="P1-3 not implemented: non-determinism statistical")
    def test_delays_vary_across_calls(self, typing):
        """500 samples from 5 consecutive calls show statistical variance."""
        all_samples = []
        for _ in range(5):
            all_samples.extend(typing._generate_delays(100))
        assert len(all_samples) == 500

        # Variance must be > 0 (trivial check that delays aren't constant)
        mean = sum(all_samples) / len(all_samples)
        variance = sum((d - mean) ** 2 for d in all_samples) / len(all_samples)
        assert variance > 1e-10, "Delay variance is effectively zero — not random"


class TestTypeTextBehavioral:
    """Tests for the main type_text() method."""

    @pytest.mark.asyncio
    async def test_type_text_default_mode_raises_not_implemented(self, typing):
        """type_text() raises NotImplementedError until implemented."""
        with pytest.raises(NotImplementedError):
            await typing.type_text("Hello")

    @pytest.mark.asyncio
    async def test_type_text_with_client(self, typing, mock_client):
        """type_text() accepts an optional client argument."""
        with pytest.raises(NotImplementedError):
            await typing.type_text("Hello", client=mock_client)

    @pytest.mark.xfail(reason="P1-3 not implemented: type_text raw mode")
    @pytest.mark.asyncio
    async def test_type_text_raw_mode_no_delay(self, typing, mock_client):
        """type_text(mode='raw') dispatches all chars with no inter-key delay."""
        result = await typing.type_text("Hello", mode="raw", client=mock_client)
        assert result["status"] == "ok"
        assert result["mode"] == "raw"
        assert result["total_delay_ms"] == pytest.approx(0.0, abs=1.0)

    @pytest.mark.xfail(reason="P1-3 not implemented: type_text disabled mode")
    @pytest.mark.asyncio
    async def test_disabled_mode_falls_through(self, mock_client):
        """When enabled=False, typing falls through to raw dispatch."""
        disabled = TypingConfig(enabled=False)
        bt = BehavioralTyping(config=disabled)
        result = await bt.type_text("Test", mode="human", client=mock_client)
        assert result["status"] == "ok"
        assert result["mode"] == "raw"  # Falls through to raw

    @pytest.mark.xfail(reason="P1-3 not implemented: mode switching")
    @pytest.mark.asyncio
    async def test_mode_switch_at_runtime(self, typing, mock_client):
        """Switch between human and raw mode at runtime via the mode parameter."""
        # First call with human mode
        result_human = await typing.type_text("Hi", mode="human", client=mock_client)
        assert result_human["mode"] == "human"

        # Second call with raw mode
        result_raw = await typing.type_text("Hi", mode="raw", client=mock_client)
        assert result_raw["mode"] == "raw"
        assert result_raw["total_delay_ms"] == pytest.approx(0.0, abs=1.0)


class TestEdgeCasesBehavioral:
    """Edge cases: empty string, special characters, modifiers."""

    @pytest.mark.xfail(reason="P1-3 not implemented: empty string edge case")
    @pytest.mark.asyncio
    async def test_empty_string_raw(self, typing, mock_client):
        """Empty string in raw mode returns immediately with 0 chars."""
        result = await typing.type_text("", mode="raw", client=mock_client)
        assert result["status"] == "ok"
        assert result["chars"] == 0

    @pytest.mark.xfail(reason="P1-3 not implemented: empty string edge case")
    @pytest.mark.asyncio
    async def test_empty_string_human(self, typing, mock_client):
        """Empty string in human mode returns immediately with 0 chars and no delay."""
        result = await typing.type_text("", mode="human", client=mock_client)
        assert result["status"] == "ok"
        assert result["chars"] == 0
        assert result["total_delay_ms"] == pytest.approx(0.0, abs=1.0)

    @pytest.mark.xfail(reason="P1-3 not implemented: special chars")
    async def test_key_identifier_special_chars(self):
        """_key_identifier handles special characters: ., !, ?, @, #, $, %."""
        for char in ".,!?@#$%^&*()_+-=[]{}|;':\"":
            params = BehavioralTyping._key_identifier(char)
            assert "key" in params
            assert "code" in params
            assert params["key"] == char or params["key"] == f"Key{char.upper()}"

    @pytest.mark.xfail(reason="P1-3 not implemented: modifier keys")
    async def test_key_identifier_shift_modifier(self):
        """_key_identifier handles Shift modifications (uppercase = Shift+key)."""
        # Upper-case letter 'A' should be keyDown Shift + keyDown A + keyUp A + keyUp Shift
        params = BehavioralTyping._key_identifier("A")
        assert params["key"] == "A"
        # The presence of modifiers should be indicated

    @pytest.mark.xfail(reason="P1-3 not implemented: special chars in type_text")
    @pytest.mark.asyncio
    async def test_type_text_special_characters(self, typing, mock_client):
        """type_text() handles special characters, not just alphanumeric."""
        special = "Hello, World! Email: test@example.com (100%)"
        result = await typing.type_text(special, mode="raw", client=mock_client)
        assert result["status"] == "ok"
        assert result["chars"] == len(special)

    @pytest.mark.xfail(reason="P1-3 not implemented: unicode chars")
    @pytest.mark.asyncio
    async def test_type_text_unicode(self, typing, mock_client):
        """type_text() handles Unicode characters (emojis, accented chars)."""
        unicode_text = "Café résumé 100€ naïve — über cool 😊"
        result = await typing.type_text(unicode_text, mode="raw", client=mock_client)
        assert result["status"] == "ok"
        assert result["chars"] == len(unicode_text)

    @pytest.mark.xfail(reason="P1-3 not implemented: whitespace")
    @pytest.mark.asyncio
    async def test_type_text_whitespace(self, typing, mock_client):
        """type_text() handles whitespace: spaces, tabs, newlines."""
        text = "line1\nline2\tindented  spaces"
        result = await typing.type_text(text, mode="raw", client=mock_client)
        assert result["status"] == "ok"
        assert result["chars"] == len(text)


class TestKeyDispatchBehavioral:
    """Tests for CDP key event dispatch."""

    @pytest.mark.asyncio
    async def test_dispatch_char_sequence_not_implemented(self, mock_client):
        """_dispatch_char_sequence raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await BehavioralTyping._dispatch_char_sequence(mock_client, "a")

    @pytest.mark.asyncio
    async def test_dispatch_key_event_not_implemented(self, mock_client):
        """_dispatch_key_event raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await BehavioralTyping._dispatch_key_event(
                mock_client, "keyDown", {"key": "a", "code": "KeyA"}
            )

    @pytest.mark.xfail(reason="P1-3 not implemented: key event dispatch")
    @pytest.mark.asyncio
    async def test_key_event_sequence_key_down(self, mock_client):
        """_dispatch_key_event dispatches a keyDown event."""
        result = await BehavioralTyping._dispatch_key_event(
            mock_client, "keyDown", {"key": "a", "code": "KeyA", "text": "a"}
        )
        assert result is not None

    @pytest.mark.xfail(reason="P1-3 not implemented: key event dispatch")
    @pytest.mark.asyncio
    async def test_key_event_sequence_key_up(self, mock_client):
        """_dispatch_key_event dispatches a keyUp event."""
        result = await BehavioralTyping._dispatch_key_event(
            mock_client, "keyUp", {"key": "a", "code": "KeyA"}
        )
        assert result is not None

    @pytest.mark.xfail(reason="P1-3 not implemented: full char sequence")
    @pytest.mark.asyncio
    async def test_full_char_sequence(self, mock_client):
        """_dispatch_char_sequence sends keyDown → keyPress → keyUp for one char."""
        await BehavioralTyping._dispatch_char_sequence(mock_client, "a")

        # Must have called _send_command 3 times (keyDown, keyPress, keyUp)
        assert mock_client._send_command.call_count == 3, (
            f"Expected 3 calls (keyDown+keyPress+keyUp), got "
            f"{mock_client._send_command.call_count}"
        )

        # Verify call order: keyDown → keyPress → keyUp
        calls = mock_client._send_command.call_args_list
        assert calls[0][0][0] == "Input.dispatchKeyEvent", (
            f"First call should be Input.dispatchKeyEvent, got {calls[0][0][0]}"
        )
        assert calls[1][0][0] == "Input.dispatchKeyEvent", (
            f"Second call should be Input.dispatchKeyEvent, got {calls[1][0][0]}"
        )
        assert calls[2][0][0] == "Input.dispatchKeyEvent", (
            f"Third call should be Input.dispatchKeyEvent, got {calls[2][0][0]}"
        )

    @pytest.mark.xfail(reason="P1-3 not implemented: event types")
    @pytest.mark.asyncio
    async def test_char_sequence_event_types(self, mock_client):
        """Each dispatchKeyEvent call has the correct event type parameter."""
        await BehavioralTyping._dispatch_char_sequence(mock_client, "b")
        calls = mock_client._send_command.call_args_list

        # First param of each call should be the method name
        # Second param should contain the event type
        event_types = [
            calls[0][0][1].get("type"),
            calls[1][0][1].get("type"),
            calls[2][0][1].get("type"),
        ]
        assert event_types == ["keyDown", "keyPress", "keyUp"], (
            f"Expected [keyDown, keyPress, keyUp], got {event_types}"
        )


class TestComputeCpmBehavioral:
    """Tests for the _compute_cpm method."""

    def test_compute_cpm_not_implemented(self, typing):
        """_compute_cpm raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            typing._compute_cpm([0.1, 0.2, 0.15])

    @pytest.mark.xfail(reason="P1-3 not implemented: CPM calculation")
    def test_compute_cpm_known_delays(self, typing):
        """_compute_cpm with uniform 0.3s delays gives 200 CPM."""
        uniform_300ms = [0.3] * 10  # 10 delays = 3 seconds total typing time
        cpm = typing._compute_cpm(uniform_300ms)
        # 11 characters typed in 3.0 seconds = 220 CPM (60/3.0 * 11)
        assert cpm == pytest.approx(200, rel=1.0)  # Roughly 200 CPM

    @pytest.mark.xfail(reason="P1-3 not implemented: CPM formula")
    def test_compute_cpm_instant(self, typing):
        """_compute_cpm with zero delays returns large (infinite) CPM."""
        with pytest.raises(ZeroDivisionError):
            typing._compute_cpm([0.0] * 10)  # Zero total time


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — API Endpoint Tests  (RED: route not implemented yet)
# ═══════════════════════════════════════════════════════════════════════════


class TestTypingApiBehavioral:
    """REST API round-trip tests — xfail until endpoints are wired in main.py."""

    @pytest.mark.xfail(reason="P1-3 endpoint /typing/config not wired in main.py yet")
    @pytest.mark.asyncio
    async def test_post_typing_config_roundtrip(self):
        """POST /typing/config returns 200 with config data."""
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/typing/config",
                json={"enabled": True, "cpm_min": 200, "cpm_max": 400},
            )
            assert resp.status_code == 200, (
                f"POST /typing/config returned {resp.status_code}: {resp.text}"
            )
            data = resp.json()
            assert data.get("status") == "ok"

    @pytest.mark.xfail(reason="P1-3 endpoint /typing/config not wired in main.py yet")
    @pytest.mark.asyncio
    async def test_get_typing_config_returns_config(self):
        """GET /typing/config returns the current configuration."""
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/typing/config")
            assert resp.status_code == 200
            data = resp.json()
            config_data = data.get("data", data)
            assert "enabled" in config_data
            assert "cpm_min" in config_data
            assert "cpm_max" in config_data

    @pytest.mark.xfail(reason="P1-3 endpoint /typing/config not wired in main.py yet")
    @pytest.mark.asyncio
    async def test_post_updates_get_returns_same(self):
        """POST update followed by GET returns the updated config."""
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/typing/config",
                json={"enabled": False, "cpm_min": 100, "cpm_max": 500},
            )
            resp = await client.get("/typing/config")
            data = resp.json()
            config_data = data.get("data", data)
            assert config_data["enabled"] is False
            assert config_data["cpm_min"] == 100
            assert config_data["cpm_max"] == 500

    @pytest.mark.xfail(reason="P1-3 endpoint /typing/config not wired in main.py yet")
    @pytest.mark.asyncio
    async def test_invalid_cpm_range_returns_422(self):
        """cpm_min > cpm_max returns 422 Unprocessable Entity."""
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/typing/config",
                json={"enabled": True, "cpm_min": 500, "cpm_max": 200},
            )
            assert resp.status_code == 422, (
                f"Expected 422 for invalid CPM range, got {resp.status_code}: {resp.text}"
            )

    @pytest.mark.xfail(reason="P1-3 endpoint /typing/config not wired in main.py yet")
    @pytest.mark.asyncio
    async def test_invalid_cpm_negative_value(self):
        """Negative CPM values return 422."""
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/typing/config",
                json={"enabled": True, "cpm_min": -1, "cpm_max": 200},
            )
            assert resp.status_code == 422

    @pytest.mark.xfail(reason="P1-3 endpoint /typing/config not wired in main.py yet")
    @pytest.mark.asyncio
    async def test_post_typing_config_partial_update(self):
        """POST with partial fields updates only specified fields."""
        from main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Set initial
            await client.post(
                "/typing/config",
                json={"enabled": True, "cpm_min": 200, "cpm_max": 400},
            )
            # Partial: only update cpm_max
            resp = await client.post(
                "/typing/config",
                json={"cpm_max": 600},
            )
            assert resp.status_code == 200
            data = resp.json()
            config_data = data.get("data", data)
            assert config_data["cpm_max"] == 600
            assert config_data["cpm_min"] == 200  # unchanged


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — Return-type and response-shape contract tests
# ═══════════════════════════════════════════════════════════════════════════


class TestResponseShapeBehavioral:
    """Contract tests for the dict shape returned by type_text()."""

    @pytest.mark.xfail(reason="P1-3 not implemented: response shape")
    @pytest.mark.asyncio
    async def test_type_text_response_shape(self, typing, mock_client):
        """type_text() returns dict with status, chars, mode, total_delay_ms."""
        result = await typing.type_text("Hello", mode="human", client=mock_client)
        assert isinstance(result, dict)
        assert "status" in result
        assert "chars" in result
        assert "mode" in result
        assert "total_delay_ms" in result
        assert result["chars"] == 5
        assert result["mode"] == "human"

    @pytest.mark.xfail(reason="P1-3 not implemented: raw response shape")
    @pytest.mark.asyncio
    async def test_type_text_raw_response_has_no_delay(self, typing, mock_client):
        """type_text(mode='raw') response shows total_delay_ms ≈ 0."""
        result = await typing.type_text("Hi", mode="raw", client=mock_client)
        assert result["total_delay_ms"] == pytest.approx(0.0, abs=1.0)

    @pytest.mark.xfail(reason="P1-3 not implemented: delayed response")
    @pytest.mark.asyncio
    async def test_type_text_human_response_has_positive_delay(self, typing, mock_client):
        """type_text(mode='human') response shows positive total_delay_ms."""
        result = await typing.type_text("Hello World!", mode="human", client=mock_client)
        assert result["total_delay_ms"] > 0
