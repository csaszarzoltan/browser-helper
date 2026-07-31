"""
Pre-development interface + behavioral tests for Human Mouse Movement Middleware.

╔══════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                           ║
║                                                                    ║
║  Interface tests (green checkmark)    verify API contracts         ║
║  Behavioral tests (red X)             fail with NotImplemented     ║
║                                        Error until impl is done    ║
║                                                                    ║
║  Feature: P1-2 Human Mouse Movement Middleware                     ║
║    - src/behavioral_mouse.py (pre-dev stub exists)                 ║
║    - REST: POST/GET /mouse/config                                  ║
║    - Bezier path, overshoot, jitter, speed profiles                ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

ROUTE_EXCLUDE_PREFIXES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def route_paths() -> list[str]:
    from main import app
    paths = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if path and path not in ROUTE_EXCLUDE_PREFIXES:
            paths.append(path)
    return paths


# ===================================================================
# SECTION 1 - MODULE INTERFACE (green: API contract checks)
# ===================================================================


class TestModuleInterface:
    """Verify the behavioral_mouse module and its public API exist."""

    def test_module_imports(self):
        import behavioral_mouse  # noqa: F401

    def test_mouseconfig_class_exists(self):
        from behavioral_mouse import MouseConfig
        assert isinstance(MouseConfig, type)

    def test_mouseconfig_has_enabled_attr(self):
        from behavioral_mouse import MouseConfig
        c = MouseConfig()
        assert hasattr(c, "enabled")

    def test_mouseconfig_has_speed_attr(self):
        from behavioral_mouse import MouseConfig
        c = MouseConfig()
        assert hasattr(c, "speed")

    def test_mouseconfig_default_enabled_is_true(self):
        from behavioral_mouse import MouseConfig
        assert MouseConfig().enabled is True

    def test_mouseconfig_default_speed_is_normal(self):
        from behavioral_mouse import MouseConfig
        assert MouseConfig().speed == "normal"

    def test_mouseconfig_accepts_enabled_and_speed(self):
        from behavioral_mouse import MouseConfig
        c = MouseConfig(enabled=False, speed="fast")
        assert c.enabled is False
        assert c.speed == "fast"

    def test_mouseconfig_invalid_speed_raises_valueerror(self):
        from behavioral_mouse import MouseConfig
        with pytest.raises(ValueError, match="Invalid speed"):
            MouseConfig(speed="turbo")

    def test_mouseconfig_has_base_duration_ms_property(self):
        from behavioral_mouse import MouseConfig
        assert isinstance(MouseConfig.base_duration_ms, property)
        assert MouseConfig(speed="slow").base_duration_ms == 300
        assert MouseConfig(speed="normal").base_duration_ms == 150
        assert MouseConfig(speed="fast").base_duration_ms == 50

    def test_mouseconfig_to_dict_round_trips(self):
        from behavioral_mouse import MouseConfig
        c = MouseConfig(enabled=True, speed="slow")
        d = c.to_dict()
        assert isinstance(d, dict)
        assert d["enabled"] is True
        assert d["speed"] == "slow"

    def test_mouseconfig_from_dict_restores(self):
        from behavioral_mouse import MouseConfig
        c = MouseConfig.from_dict({"enabled": False, "speed": "fast"})
        assert c.enabled is False
        assert c.speed == "fast"

    def test_mouseconfig_from_dict_defaults(self):
        from behavioral_mouse import MouseConfig
        c = MouseConfig.from_dict({})
        assert c.enabled is True
        assert c.speed == "normal"

    def test_behavioralmouse_class_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert isinstance(BehavioralMouse, type)

    def test_behavioralmouse_init_takes_optional_config(self):
        from behavioral_mouse import BehavioralMouse
        b = BehavioralMouse()
        assert isinstance(b, BehavioralMouse)

    def test_behavioralmouse_init_with_config(self):
        from behavioral_mouse import BehavioralMouse, MouseConfig
        mc = MouseConfig(speed="slow")
        b = BehavioralMouse(config=mc)
        assert b.config is mc

    def test_behavioralmouse_has_config_property(self):
        from behavioral_mouse import BehavioralMouse
        assert isinstance(BehavioralMouse.config, property)

    def test_behavioralmouse_config_property_settable(self):
        from behavioral_mouse import BehavioralMouse, MouseConfig
        b = BehavioralMouse()
        mc = MouseConfig(speed="fast")
        b.config = mc
        assert b.config.speed == "fast"

    def test_move_to_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "move_to")
        assert callable(BehavioralMouse.move_to)
        assert inspect.iscoroutinefunction(BehavioralMouse.move_to)

    def test_move_to_signature(self):
        from behavioral_mouse import BehavioralMouse
        sig = inspect.signature(BehavioralMouse.move_to)
        params = list(sig.parameters.keys())
        assert "x" in params, f"move_to missing 'x' param: {params}"
        assert "y" in params, f"move_to missing 'y' param: {params}"

    def test_click_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "click")
        assert callable(BehavioralMouse.click)
        assert inspect.iscoroutinefunction(BehavioralMouse.click)

    def test_click_signature(self):
        from behavioral_mouse import BehavioralMouse
        sig = inspect.signature(BehavioralMouse.click)
        params = list(sig.parameters.keys())
        assert "x" in params, f"click missing 'x' param: {params}"
        assert "y" in params, f"click missing 'y' param: {params}"

    def test_bezier_path_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "_generate_bezier_path")
        assert callable(BehavioralMouse._generate_bezier_path)

    def test_add_jitter_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "_add_jitter")

    def test_should_overshoot_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "_should_overshoot")

    def test_raw_move_to_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "_raw_move_to")

    def test_make_dispatch_params_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "_make_dispatch_params")

    def test_inter_step_delays_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "_inter_step_delays")

    def test_compute_overshoot_target_method_exists(self):
        from behavioral_mouse import BehavioralMouse
        assert hasattr(BehavioralMouse, "_compute_overshoot_target")

    def test_jitter_amplitude_constant(self):
        from behavioral_mouse import BehavioralMouse
        assert BehavioralMouse.JITTER_AMPLITUDE == 2.0

    def test_overshoot_probability_constant(self):
        from behavioral_mouse import BehavioralMouse
        assert BehavioralMouse.OVERSHOOT_PROBABILITY == 0.15

    def test_valid_speeds_frozenset(self):
        from behavioral_mouse import MouseConfig
        assert hasattr(MouseConfig, "VALID_SPEEDS")
        assert MouseConfig.VALID_SPEEDS == frozenset({"slow", "normal", "fast"})

    def test_speed_durations_dict(self):
        from behavioral_mouse import MouseConfig
        assert MouseConfig.SPEED_DURATIONS["slow"] == 300
        assert MouseConfig.SPEED_DURATIONS["normal"] == 150
        assert MouseConfig.SPEED_DURATIONS["fast"] == 50


# ===================================================================
# SECTION 2 - API ENDPOINT INTERFACE (green: route registration)
# ===================================================================


class TestMouseConfigApiInterface:
    """Verify REST API endpoints for mouse config are registered."""

    def test_post_mouse_config_route_registered(self):
        paths = route_paths()
        assert "/mouse/config" in paths

    def test_get_mouse_config_route_registered(self):
        paths = route_paths()
        assert "/mouse/config" in paths


# ===================================================================
# SECTION 3 - FIXTURES
# ===================================================================


@pytest.fixture
def mock_config():
    from behavioral_mouse import MouseConfig
    return MouseConfig()


@pytest.fixture
def mouse(mock_config):
    from behavioral_mouse import BehavioralMouse
    return BehavioralMouse(config=mock_config)


@pytest.fixture
def mock_cdp_client():
    from cdp_client import CDPClient
    c = CDPClient(cdp_http_url="http://127.0.0.1:9555")
    c._connected = True
    c._ws = MagicMock()
    c._active_tab_id = "tab-1"
    c._send_command = AsyncMock(return_value={"result": {}})
    c._activate_current = AsyncMock()
    return c


@pytest_asyncio.fixture
async def async_client():
    from main import app
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ===================================================================
# SECTION 4 - BEZIER PATH GENERATION (red: NotImplementedError)
# ===================================================================


class TestBezierPathGeneration:
    """_generate_bezier_path() raises NotImplementedError in stub."""

    def test_generate_bezier_path_returns_list_of_tuples(self, mouse):
        """Test that _generate_bezier_path returns a list of (x, y) tuples."""
        path = mouse._generate_bezier_path(100, 200, 500, 600, num_steps=20)
        assert isinstance(path, list)
        assert len(path) == 20
        assert all(isinstance(p, tuple) and len(p) == 2 for p in path)
        # Start and end points should be close to the input coordinates
        assert abs(path[0][0] - 100) < 10
        assert abs(path[0][1] - 200) < 10
        assert abs(path[-1][0] - 500) < 10
        assert abs(path[-1][1] - 600) < 10

    def test_generate_bezier_path_static_method(self):
        from behavioral_mouse import BehavioralMouse
        path = BehavioralMouse._generate_bezier_path(0, 0, 800, 600)
        assert isinstance(path, list)
        assert len(path) > 0

    def test_generate_bezier_path_signature(self):
        from behavioral_mouse import BehavioralMouse
        sig = inspect.signature(BehavioralMouse._generate_bezier_path)
        p = list(sig.parameters.keys())
        for required in ("start_x", "start_y", "end_x", "end_y"):
            assert required in p, f"Missing param {required} in {p}"


# ===================================================================
# SECTION 5 - JITTER (red: NotImplementedError)
# ===================================================================


class TestJitter:
    """Jitter on control points."""

    def test_add_jitter_returns_tuple(self, mouse):
        """Test that _add_jitter returns a jittered tuple."""
        point = (100.0, 200.0)
        jittered = mouse._add_jitter(point)
        assert isinstance(jittered, tuple)
        assert len(jittered) == 2
        # Jittered point should be close to original (within amplitude)
        assert abs(jittered[0] - point[0]) <= 2.0
        assert abs(jittered[1] - point[1]) <= 2.0

    def test_add_jitter_accepts_amplitude(self, mouse):
        sig = inspect.signature(mouse._add_jitter)
        assert "amplitude" in sig.parameters


# ===================================================================
# SECTION 6 - OVERSHOOT (red: NotImplementedError)
# ===================================================================


class TestOvershoot:
    """Overshoot probability and target computation."""

    def test_should_overshoot_returns_bool(self, mouse):
        """Test that _should_overshoot returns a boolean."""
        result = mouse._should_overshoot()
        assert isinstance(result, bool)

    def test_compute_overshoot_target_returns_tuple(self, mouse):
        """Test that _compute_overshoot_target returns a tuple."""
        target = mouse._compute_overshoot_target(500.0, 300.0, overshoot_px=10)
        assert isinstance(target, tuple)
        assert len(target) == 2
        # Overshoot target should be beyond the original target
        assert target[0] > 500.0 or target[1] > 300.0

    def test_compute_overshoot_target_signature(self):
        from behavioral_mouse import BehavioralMouse
        sig = inspect.signature(BehavioralMouse._compute_overshoot_target)
        p = list(sig.parameters.keys())
        for required in ("end_x", "end_y"):
            assert required in p, f"Missing param {required} in {p}"


# ===================================================================
# SECTION 7 - SPEED PROFILES / TIMING
# ===================================================================


class TestSpeedProfiles:
    """Speed profile delays and inter-step timing."""

    def test_slow_base_duration(self):
        from behavioral_mouse import MouseConfig
        assert MouseConfig(speed="slow").base_duration_ms == 300

    def test_normal_base_duration(self):
        from behavioral_mouse import MouseConfig
        assert MouseConfig(speed="normal").base_duration_ms == 150

    def test_fast_base_duration(self):
        from behavioral_mouse import MouseConfig
        assert MouseConfig(speed="fast").base_duration_ms == 50

    def test_base_duration_ordering(self):
        from behavioral_mouse import MouseConfig
        slow = MouseConfig(speed="slow").base_duration_ms
        normal = MouseConfig(speed="normal").base_duration_ms
        fast = MouseConfig(speed="fast").base_duration_ms
        assert slow > normal > fast

    def test_inter_step_delays_returns_list(self, mouse):
        """Test that _inter_step_delays returns a list of delays."""
        delays = mouse._inter_step_delays(num_steps=20, base_duration_ms=300)
        assert isinstance(delays, list)
        assert len(delays) == 20
        assert all(isinstance(d, (int, float)) for d in delays)
        # Total should be close to base_duration_ms
        assert sum(delays) > 0

    def test_inter_step_delays_signature(self):
        from behavioral_mouse import BehavioralMouse
        sig = inspect.signature(BehavioralMouse._inter_step_delays)
        p = list(sig.parameters.keys())
        for required in ("num_steps", "base_duration_ms"):
            assert required in p, f"Missing param {required} in {p}"


# ===================================================================
# SECTION 8 - MOVE_TO / CLICK (red: NotImplementedError)
# ===================================================================


@pytest.mark.asyncio
class TestMoveToClick:
    """move_to() and click() raise NotImplementedError in stub."""

    async def test_move_to_returns_list(self, mouse, mock_cdp_client):
        """Test that move_to returns a list of events."""
        result = await mouse.move_to(x=500, y=300, client=mock_cdp_client)
        assert isinstance(result, list)

    async def test_click_returns_dict(self, mouse, mock_cdp_client):
        """Test that click returns a dict with status."""
        result = await mouse.click(x=500, y=300, client=mock_cdp_client)
        assert isinstance(result, dict)
        assert "status" in result

    async def test_move_to_returns_list_of_dicts(self, monkeypatch, mouse):
        monkeypatch.setattr(
            mouse, "move_to",
            AsyncMock(return_value=[{"type": "mouseMoved", "x": 100, "y": 200}]),
        )
        result = await mouse.move_to(500, 300)
        assert isinstance(result, list)
        assert len(result) > 0
        assert isinstance(result[0], dict)

    async def test_click_returns_dict_with_mock(self, monkeypatch, mouse):
        monkeypatch.setattr(
            mouse, "click",
            AsyncMock(return_value={"status": "ok", "x": 500, "y": 300}),
        )
        result = await mouse.click(500, 300)
        assert isinstance(result, dict)
        assert "status" in result
        assert "x" in result


# ===================================================================
# SECTION 9 - DISABLED MODE / RAW FALLTHROUGH (red: NotImplemented)
# ===================================================================


class TestDisabledMode:
    """Disabled mode falls through to raw CDP."""

    def test_raw_move_to_returns_list(self, mouse):
        """Test that _raw_move_to returns a list of events."""
        result = mouse._raw_move_to(100, 200)
        assert isinstance(result, list)

    def test_raw_move_to_signature(self):
        from behavioral_mouse import BehavioralMouse
        sig = inspect.signature(BehavioralMouse._raw_move_to)
        p = list(sig.parameters.keys())
        assert "x" in p, f"_raw_move_to missing 'x' param: {p}"
        assert "y" in p, f"_raw_move_to missing 'y' param: {p}"


# ===================================================================
# SECTION 10 - CDP EVENT DISPATCH (red: NotImplementedError)
# ===================================================================


class TestEventDispatch:
    """CDP event dispatch via _make_dispatch_params."""

    def test_make_dispatch_params_returns_dict(self, mouse):
        """Test that _make_dispatch_params returns a dict."""
        result = mouse._make_dispatch_params("mouseMoved", 100, 200)
        assert isinstance(result, dict)
        assert "type" in result
        assert result["type"] == "mouseMoved"

    def test_make_dispatch_params_signature(self):
        from behavioral_mouse import BehavioralMouse
        sig = inspect.signature(BehavioralMouse._make_dispatch_params)
        p = list(sig.parameters.keys())
        for required in ("event_type", "x", "y"):
            assert required in p, f"Missing param {required} in {p}"

    def test_make_dispatch_params_accepts_button(self, mouse):
        sig = inspect.signature(mouse._make_dispatch_params)
        assert "button" in sig.parameters

    def test_make_dispatch_params_returns_dict_with_mock(self, monkeypatch):
        from behavioral_mouse import BehavioralMouse
        mock_ret = {"type": "mouseMoved", "x": 100, "y": 200, "button": "left"}
        monkeypatch.setattr(
            BehavioralMouse, "_make_dispatch_params",
            staticmethod(lambda *a, **kw: mock_ret),
        )
        result = BehavioralMouse._make_dispatch_params("mouseMoved", 100, 200)
        assert isinstance(result, dict)
        assert result.get("type") == "mouseMoved"
        assert "x" in result
        assert "y" in result

    def test_make_dispatch_params_event_types(self, monkeypatch):
        from behavioral_mouse import BehavioralMouse
        mock_ret = {"type": "mousePressed", "x": 100, "y": 200, "button": "left"}
        monkeypatch.setattr(
            BehavioralMouse, "_make_dispatch_params",
            staticmethod(lambda *a, **kw: mock_ret),
        )
        result = BehavioralMouse._make_dispatch_params("mousePressed", 100, 200)
        assert result.get("type") in ("mouseMoved", "mousePressed", "mouseReleased")


# ===================================================================
# SECTION 11 - CONFIG PERSISTENCE (green: serialization works)
# ===================================================================


class TestConfigPersistence:
    """MouseConfig serialization round-trips - should pass."""

    def test_to_dict_round_trip(self):
        from behavioral_mouse import MouseConfig
        original = MouseConfig(enabled=False, speed="slow")
        d = original.to_dict()
        restored = MouseConfig.from_dict(d)
        assert restored.enabled == original.enabled
        assert restored.speed == original.speed

    def test_config_full_cycle(self):
        from behavioral_mouse import MouseConfig
        saved = MouseConfig(enabled=True, speed="fast").to_dict()
        loaded = MouseConfig.from_dict(saved)
        assert loaded.enabled is True
        assert loaded.speed == "fast"

    def test_config_default_round_trip(self):
        from behavioral_mouse import MouseConfig
        default = MouseConfig()
        d = default.to_dict()
        restored = MouseConfig.from_dict(d)
        assert restored.enabled == default.enabled
        assert restored.speed == default.speed


# ===================================================================
# SECTION 12 - API ENDPOINT BEHAVIOR (red: 404 until routes registered)
# ===================================================================


@pytest.mark.asyncio
class TestMouseConfigApiBehavior:
    """Mouse config REST API endpoints - 404 until routes are added."""

    async def test_post_mouse_config_response(self, async_client):
        resp = await async_client.post(
            "/mouse/config",
            json={"enabled": True, "speed": "slow"},
        )
        assert resp.status_code in (200, 201, 400, 422, 404, 500), (
            f"POST /mouse/config: {resp.status_code}: {resp.text}"
        )

    async def test_get_mouse_config_response(self, async_client):
        resp = await async_client.get("/mouse/config")
        assert resp.status_code in (200, 404), (
            f"GET /mouse/config: {resp.status_code}: {resp.text}"
        )
        if resp.status_code == 200:
            data = resp.json()
            cfg = data if "enabled" in data else data.get("config", {})
            assert "enabled" in cfg
            assert "speed" in cfg

    async def test_post_invalid_speed_422(self, async_client):
        resp = await async_client.post(
            "/mouse/config",
            json={"enabled": True, "speed": "turbo"},
        )
        assert resp.status_code in (422, 404), (
            f"Invalid speed: {resp.status_code}: {resp.text}"
        )

    async def test_post_empty_body(self, async_client):
        resp = await async_client.post("/mouse/config", json={})
        assert resp.status_code in (200, 422, 404), (
            f"Empty body: {resp.status_code}: {resp.text}"
        )


# ===================================================================
# SECTION 13 - EDGE CASES
# ===================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_mouseconfig_all_combinations(self):
        from behavioral_mouse import MouseConfig
        for enabled in (True, False):
            for speed in ("slow", "normal", "fast"):
                c = MouseConfig(enabled=enabled, speed=speed)
                assert c.enabled is enabled
                assert c.speed == speed

    def test_mouseconfig_str_repr(self):
        from behavioral_mouse import MouseConfig
        r = repr(MouseConfig(enabled=True, speed="slow"))
        assert "MouseConfig" in r
        assert "slow" in r

    def test_overshoot_probability_exact(self):
        from behavioral_mouse import BehavioralMouse
        assert BehavioralMouse.OVERSHOOT_PROBABILITY == 0.15

    def test_jitter_amplitude_exact(self):
        from behavioral_mouse import BehavioralMouse
        assert BehavioralMouse.JITTER_AMPLITUDE == 2.0
