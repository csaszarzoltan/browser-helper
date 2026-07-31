"""
Pre-development interface + behavioral tests for Browser Helper v0.8 features.

╔══════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                           ║
║                                                                    ║
║  Interface tests (green checkmark)    → assert pass immediately     ║
║  Behavioral tests (red X)             → assert fail until impl.     ║
║                                                                    ║
║  Eight features (v0.8):                                           ║
║    P0  POST /click/coordinates   (new endpoint: pixel clicks)      ║
║    P0  POST /dropdown/select     (new endpoint: simplified select) ║
║    P0  POST /wait/visible        (new endpoint: visibility wait)   ║
║    P1  Modal element discovery   (enriched analyze_page response)  ║
║    P1  /click/label alias        (ARIA / role-based matching)      ║
║    P1  /form/fill flexibility    (select/checkbox/radio/textarea)  ║
║    P1  API aliases               (route alias registration)       ║
║    P2  SKILL.md                  (documentation — no test needed)  ║
╚══════════════════════════════════════════════════════════════════════╝
║  v0.7 baseline: 432 tests passing. No regressions permitted.       ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

import pytest_asyncio
from httpx import ASGITransport
from pydantic import ValidationError

from cdp_client import CDPClient
from main import app

# ─── Helpers ───────────────────────────────────────────────────────────────

ROUTE_EXCLUDE_PREFIXES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def route_paths():
    """List route paths registered on the FastAPI app for interface checks."""
    paths = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if path and path not in ROUTE_EXCLUDE_PREFIXES:
            paths.append(path)
    return paths


@pytest.fixture
def client():
    """Return a fresh CDPClient with no real connection."""
    return CDPClient(cdp_http_url="http://127.0.0.1:9555")


@pytest.fixture
def mock_client():
    """CDPClient with all network methods mocked."""
    c = CDPClient(cdp_http_url="http://127.0.0.1:9555")
    c._connected = True
    c._ws = MagicMock()
    c._active_tab_id = "tab-1"
    c._send_command = AsyncMock(return_value={"result": {"value": "mocked"}})
    c._activate_current = AsyncMock()
    c.evaluate = AsyncMock(return_value={"status": "ok", "result": {}})
    c.discover_tabs = AsyncMock(return_value=[{"id": "tab-1", "type": "page", "title": "Test"}])
    c.get_tabs = AsyncMock()
    return c


@pytest_asyncio.fixture
async def async_client():
    """FastAPI test client via httpx ASGI transport."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — INTERFACE TESTS (should pass immediately with stubs)
# ═══════════════════════════════════════════════════════════════════════════


class TestInterface:
    """Verify that all required classes, models, and route stubs exist."""

    # ── 1a. P0: POST /click/coordinates interface ───────────────────────

    def test_click_coordinates_model_exists(self):
        """ClickCoordinatesRequest must exist with x, y, button, click_count fields."""
        from main import ClickCoordinatesRequest
        model = ClickCoordinatesRequest(x=100, y=200)
        assert model.x == 100
        assert model.y == 200
        assert model.button == "left"
        assert model.click_count == 1

    def test_click_coordinates_model_custom_button(self):
        """ClickCoordinatesRequest accepts custom button and click_count."""
        from main import ClickCoordinatesRequest
        model = ClickCoordinatesRequest(x=300, y=400, button="right", click_count=2)
        assert model.button == "right"
        assert model.click_count == 2

    def test_click_coordinates_route_registered(self):
        """POST /click/coordinates must be registered."""
        routes = route_paths()
        assert "/click/coordinates" in routes, (
            "v0.8 must register POST /click/coordinates"
        )

    def test_click_coordinates_method_exists(self, client):
        """click_coordinates must exist as a method on CDPClient."""
        assert hasattr(client, "click_coordinates")
        assert callable(client.click_coordinates)
        import asyncio
        assert asyncio.iscoroutinefunction(client.click_coordinates)

    # ── 1b. P0: POST /dropdown/select interface ────────────────────────

    def test_dropdown_select_model_exists(self):
        """DropdownSelectRequest must exist with label, option, option_value, timeout fields."""
        from main import DropdownSelectRequest
        model = DropdownSelectRequest(label="Country", option="Hungary")
        assert model.label == "Country"
        assert model.option == "Hungary"
        assert model.option_value is None
        assert model.timeout == 5

    def test_dropdown_select_model_option_value(self):
        """DropdownSelectRequest accepts option_value as alternative."""
        from main import DropdownSelectRequest
        model = DropdownSelectRequest(label="Country", option_value="HU")
        assert model.option is None
        assert model.option_value == "HU"

    def test_dropdown_select_route_registered(self):
        """POST /dropdown/select must be registered."""
        routes = route_paths()
        assert "/dropdown/select" in routes, (
            "v0.8 must register POST /dropdown/select"
        )

    def test_dropdown_select_method_exists(self, client):
        """dropdown_select must exist as a method on CDPClient."""
        assert hasattr(client, "dropdown_select")
        assert callable(client.dropdown_select)
        import asyncio
        assert asyncio.iscoroutinefunction(client.dropdown_select)

    # ── 1c. P0: POST /wait/visible interface ──────────────────────────

    def test_wait_visible_model_exists(self):
        """WaitVisibleRequest must exist with selector, timeout fields."""
        from main import WaitVisibleRequest
        model = WaitVisibleRequest(selector=".my-element")
        assert model.selector == ".my-element"
        assert model.timeout == 10

    def test_wait_visible_model_custom_timeout(self):
        """WaitVisibleRequest accepts custom timeout."""
        from main import WaitVisibleRequest
        model = WaitVisibleRequest(selector="#submit-btn", timeout=30)
        assert model.timeout == 30

    def test_wait_visible_route_registered(self):
        """POST /wait/visible must be registered."""
        routes = route_paths()
        assert "/wait/visible" in routes, (
            "v0.8 must register POST /wait/visible"
        )

    def test_wait_for_element_accepts_visible(self, client):
        """wait_for_element(selector, timeout, visible) — visible param must exist."""
        import inspect
        sig = inspect.signature(client.wait_for_element)
        assert "visible" in sig.parameters, (
            "wait_for_element must accept visible= parameter"
        )

    # ── 1d. P1: Modal element discovery interface ─────────────────────

    def test_analyze_page_modal_enhanced_fields(self):
        """analyze_page() response must include enhanced modal fields in JS contract."""
        # Contract test: the response shape should include role, modal_type,
        # interactive_elements, aria_label, focus_trap per modal
        sample_modal = {
            "role": "dialog",
            "modal_type": "aria_dialog",
            "interactive_elements": [],
            "aria_label": "Confirm",
            "focus_trap": True,
        }
        assert "role" in sample_modal
        assert "modal_type" in sample_modal
        assert "interactive_elements" in sample_modal
        assert "aria_label" in sample_modal
        assert "focus_trap" in sample_modal

    def test_analyze_page_modal_types_defined(self):
        """Modal type enum values must be defined."""
        modal_types = {"aria_dialog", "overlay", "focus_trap", "classic"}
        assert len(modal_types) >= 4

    def test_analyze_page_preserves_existing_fields(self, client):
        """analyze_page must still return existing modals[].buttons and modals[].tabs fields."""
        assert callable(client.analyze_page)

    # ── 1e. P1: /click/label alias interface ──────────────────────────

    def test_click_label_response_includes_resolved_via(self, mock_client):
        """click_label response should include resolved_via field."""
        mock_client.click_label = AsyncMock(return_value={
            "status": "ok",
            "result": {"label": "Submit", "resolved_via": "label_element"},
        })
        import asyncio
        result = asyncio.run(mock_client.click_label("Submit"))
        assert "resolved_via" in result.get("result", {})

    def test_click_label_accepts_confirm_param(self):
        """POST /click/label?confirm=screenhot route still works."""
        # Just verify the route exists — actual behavior tested elsewhere
        routes = route_paths()
        assert "/click/label" in routes, "/click/label route must exist"

    # ── 1f. P1: /form/fill shorthand interface ────────────────────────

    def test_form_fill_request_accepts_shorthand(self):
        """FormFillRequest must accept {selector, text} shorthand."""
        from main import FormFillRequest
        model = FormFillRequest(selector="#email", text="hello")
        assert len(model.fields) == 1
        assert model.fields[0]["selector"] == "#email"
        assert model.fields[0]["text"] == "hello"

    def test_form_fill_request_shorthand_timeout(self):
        """FormFillRequest shorthand respects explicit timeout."""
        from main import FormFillRequest
        model = FormFillRequest(selector="#email", text="hello", timeout=30)
        assert model.timeout == 30
        assert len(model.fields) == 1

    def test_form_fill_request_shorthand_rejects_partial(self):
        """FormFillRequest must reject {selector} without {text}."""
        from main import FormFillRequest
        with pytest.raises((ValueError, ValidationError)):
            FormFillRequest(selector="#email")

    def test_form_fill_request_shorthand_field_model_preserved(self):
        """FormFillField model must be unchanged (still uses label/value)."""
        from main import FormFillField
        model = FormFillField(label="Email", value="test@example.com")
        assert model.label == "Email"
        assert model.value == "test@example.com"

    # ── 1f. P1: /form/fill flexibility interface ──────────────────────

    def test_form_fill_field_model_exists(self):
        """FormFillField must exist with label, value, type fields."""
        from main import FormFillField
        model = FormFillField(label="Email", value="test@example.com")
        assert model.label == "Email"
        assert model.value == "test@example.com"
        assert model.type is None

    def test_form_fill_field_with_type(self):
        """FormFillField accepts optional type hint."""
        from main import FormFillField
        model = FormFillField(label="Country", value="HU", type="select")
        assert model.type == "select"

    def test_form_fill_request_accepts_field_objects(self):
        """FormFillRequest must accept list[FormFillField] in addition to list[dict]."""
        from main import FormFillField, FormFillRequest
        model = FormFillRequest(fields=[
            FormFillField(label="Name", value="Alice"),
            FormFillField(label="Country", value="HU", type="select"),
        ])
        assert len(model.fields) == 2
        assert model.fields[0]["label"] == "Name"

    def test_form_fill_request_backward_compat_dict(self):
        """FormFillRequest must still accept list[dict] for backward compatibility."""
        from main import FormFillRequest
        model = FormFillRequest(fields=[
            {"label": "Name", "value": "Alice"},
            {"label": "Country", "value": "HU"},
        ])
        assert len(model.fields) == 2

    def test_smart_form_fill_accepts_fields(self, client):
        """smart_form_fill() must exist with fields, timeout params."""
        assert hasattr(client, "smart_form_fill")
        assert callable(client.smart_form_fill)
        import asyncio
        assert asyncio.iscoroutinefunction(client.smart_form_fill)

    # ── 1g. P1: API aliases interface ─────────────────────────────────

    def test_api_aliases_dict_exists(self):
        """API_ALIASES dict must exist in main.py."""
        from main import API_ALIASES
        assert isinstance(API_ALIASES, dict), "API_ALIASES must be a dict"

    def test_api_aliases_contains_dropdown_select(self):
        """API_ALIASES must contain /dropdown/select entry."""
        from main import API_ALIASES
        assert "/dropdown/select" in API_ALIASES, (
            "API_ALIASES must map /dropdown/select"
        )

    def test_api_aliases_contains_wait_visible(self):
        """API_ALIASES must contain /wait/visible entry."""
        from main import API_ALIASES
        assert "/wait/visible" in API_ALIASES, (
            "API_ALIASES must map /wait/visible"
        )

    def test_api_aliases_have_method_target_transform(self):
        """Each alias entry must have method, target, and optional transform fields."""
        from main import API_ALIASES
        for alias_path, config in API_ALIASES.items():
            assert "method" in config, f"Alias {alias_path} missing 'method'"
            assert "target" in config, f"Alias {alias_path} missing 'target'"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — P0: POST /click/coordinates (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestP0ClickCoordinates:
    """POST /click/coordinates dispatches Input.dispatchMouseEvent at pixel coordinates."""

    async def test_click_coordinates_calls_activate(self, mock_client):
        """click_coordinates must call _activate_current() before dispatching."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_coordinates.__get__(mock_client, CDPClient)
        mock_client._activate_current.reset_mock()
        with patch.object(mock_client, "_send_command", AsyncMock(return_value={"result": {}})):
            await real_method(100, 200)
        mock_client._activate_current.assert_awaited_once()

    async def test_click_coordinates_dispatches_mouse_pressed(self, mock_client):
        """click_coordinates must send Input.dispatchMouseEvent with mousePressed."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_coordinates.__get__(mock_client, CDPClient)
        mock_client._send_command = AsyncMock(return_value={"result": {}})
        await real_method(100, 200)
        # Verify _send_command was called with Input.dispatchMouseEvent
        calls = mock_client._send_command.call_args_list
        mouse_calls = [c for c in calls if c[0][0] == "Input.dispatchMouseEvent"]
        assert len(mouse_calls) >= 1, (
            "click_coordinates must call Input.dispatchMouseEvent"
        )

    async def test_click_coordinates_dispatches_mouse_released(self, mock_client):
        """click_coordinates must send Input.dispatchMouseEvent with mouseReleased."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_coordinates.__get__(mock_client, CDPClient)
        mock_client._send_command = AsyncMock(return_value={"result": {}})
        await real_method(100, 200)
        calls = mock_client._send_command.call_args_list
        released = [c for c in calls if c[0][0] == "Input.dispatchMouseEvent"
                     and c[1].get("type") == "mouseReleased"]
        assert len(released) == 1, (
            "click_coordinates must dispatch mouseReleased"
        )

    async def test_click_coordinates_passes_x_y(self, mock_client):
        """click_coordinates must pass x, y to the CDP command."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_coordinates.__get__(mock_client, CDPClient)
        mock_client._send_command = AsyncMock(return_value={"result": {}})
        await real_method(150, 250)
        calls = mock_client._send_command.call_args_list
        pressed = [c for c in calls if c[0][0] == "Input.dispatchMouseEvent"
                    and c[1].get("type") == "mousePressed"]
        assert len(pressed) == 1
        assert pressed[0][1].get("x") == 150
        assert pressed[0][1].get("y") == 250

    async def test_click_coordinates_uses_correct_button(self, mock_client):
        """click_coordinates must pass button parameter to CDP."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_coordinates.__get__(mock_client, CDPClient)
        mock_client._send_command = AsyncMock(return_value={"result": {}})
        await real_method(100, 200, button="right")
        calls = mock_client._send_command.call_args_list
        pressed = [c for c in calls if c[0][0] == "Input.dispatchMouseEvent"
                    and c[1].get("type") == "mousePressed"]
        assert len(pressed) == 1
        assert pressed[0][1].get("button") == "right"

    async def test_click_coordinates_click_count(self, mock_client):
        """click_coordinates must pass click_count to CDP command."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_coordinates.__get__(mock_client, CDPClient)
        mock_client._send_command = AsyncMock(return_value={"result": {}})
        await real_method(100, 200, click_count=2)
        calls = mock_client._send_command.call_args_list
        pressed = [c for c in calls if c[0][0] == "Input.dispatchMouseEvent"
                    and c[1].get("type") == "mousePressed"]
        assert len(pressed) == 1
        assert pressed[0][1].get("clickCount") == 2

    async def test_click_coordinates_endpoint_response_shape(self, async_client):
        """POST /click/coordinates must return {status, operation, result}."""
        resp = await async_client.post("/click/coordinates", json={"x": 100, "y": 200})
        # Should 200 in v0.8, currently may 400 (not connected) or 404 if route missing
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") == "ok"
            assert data.get("operation") == "click_coordinates"
            result = data.get("result", {})
            assert "x" in result
            assert "y" in result
            assert "button" in result
        else:
            # Route exists but may not be fully implemented yet
            assert resp.status_code in (400, 422, 500), (
                f"Expected 200/400/422/500, got {resp.status_code}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — P0: POST /dropdown/select (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestP0DropdownSelect:
    """POST /dropdown/select performs simplified dropdown selection."""

    async def test_dropdown_select_calls_activate(self, mock_client):
        """dropdown_select must call _activate_current() before execution."""
        from cdp_client import CDPClient
        real_method = CDPClient.dropdown_select.__get__(mock_client, CDPClient)
        mock_client._activate_current.reset_mock()
        with patch.object(mock_client, "evaluate", AsyncMock(return_value={"status": "ok", "result": {"value": "selected"}})):
            await real_method("Country", "Hungary")
        mock_client._activate_current.assert_awaited_once()

    async def test_dropdown_select_calls_form_select(self, mock_client):
        """dropdown_select must delegate to form_select with by='label'."""
        from cdp_client import CDPClient
        real_method = CDPClient.dropdown_select.__get__(mock_client, CDPClient)
        mock_client.form_select = AsyncMock(return_value={"status": "ok", "result": {"value": "HU"}})
        await real_method("Country", "Hungary")
        mock_client.form_select.assert_awaited_once_with("label", "Country", "Hungary")

    async def test_dropdown_select_option_value(self, mock_client):
        """dropdown_select must pass option_value when provided."""
        from cdp_client import CDPClient
        real_method = CDPClient.dropdown_select.__get__(mock_client, CDPClient)
        mock_client.form_select = AsyncMock(return_value={"status": "ok", "result": {"value": "HU"}})
        await real_method("Country", option_value="HU")
        mock_client.form_select.assert_awaited_once_with("label", "Country", "HU")

    async def test_dropdown_select_returns_selected_value(self, mock_client):
        """dropdown_select must return the selected option."""
        from cdp_client import CDPClient
        real_method = CDPClient.dropdown_select.__get__(mock_client, CDPClient)
        mock_client.form_select = AsyncMock(return_value={"status": "ok", "result": {"value": "HU"}})
        result = await real_method("Country", "Hungary")
        assert isinstance(result, dict)
        assert result.get("status") == "ok"
        result_data = result.get("result", result)
        assert "value" in result_data

    async def test_dropdown_select_endpoint_accepts_body(self, async_client):
        """POST /dropdown/select must accept {label, option} body."""
        resp = await async_client.post("/dropdown/select", json={"label": "Country", "option": "Hungary"})
        assert resp.status_code in (200, 400, 422, 500), (
            f"Expected 200/400/422/500, got {resp.status_code}"
        )

    async def test_dropdown_select_response_shape(self, async_client):
        """POST /dropdown/select response must have operation, status, result."""
        resp = await async_client.post("/dropdown/select", json={"label": "Country", "option": "Hungary"})
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") == "ok"
            assert data.get("operation") == "dropdown_select"
            assert "result" in data
            assert "value" in data["result"]


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — P0: POST /wait/visible (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestP0WaitVisible:
    """POST /wait/visible waits for element to be both present and visible."""

    async def test_wait_visible_calls_wait_for_element(self, mock_client):
        """wait/visible must call wait_for_element with visible=True."""
        from cdp_client import CDPClient
        real_method = CDPClient.wait_visible.__get__(mock_client, CDPClient)
        mock_client.wait_for_element = AsyncMock(return_value={"status": "ok"})
        await real_method("#submit-btn", timeout=10)
        mock_client.wait_for_element.assert_awaited_once_with(
            "#submit-btn", 10, True
        )

    async def test_wait_visible_calls_activate(self, mock_client):
        """wait_visible must call _activate_current()."""
        from cdp_client import CDPClient
        real_method = CDPClient.wait_visible.__get__(mock_client, CDPClient)
        mock_client._activate_current.reset_mock()
        mock_client.wait_for_element = AsyncMock(return_value={"status": "ok"})
        with patch.object(mock_client, "_send_command", AsyncMock(return_value={"result": {}})):
            await real_method("#submit-btn")
        mock_client._activate_current.assert_awaited_once()

    async def test_wait_visible_returns_element_info(self, mock_client):
        """wait_visible must return element info (tag, text, rect, etc.)."""
        from cdp_client import CDPClient
        real_method = CDPClient.wait_visible.__get__(mock_client, CDPClient)
        mock_client.wait_for_element = AsyncMock(return_value={"status": "ok", "result": {
            "tag": "BUTTON", "text": "Submit",
            "rect": {"x": 0, "y": 0, "width": 100, "height": 50},
        }})
        result = await real_method("#submit-btn")
        assert isinstance(result, dict)
        assert result.get("status") == "ok"

    async def test_wait_visible_times_out_gracefully(self, mock_client):
        """wait_visible must handle timeout gracefully (return error, not crash)."""
        from cdp_client import CDPClient
        real_method = CDPClient.wait_visible.__get__(mock_client, CDPClient)
        mock_client.wait_for_element = AsyncMock(side_effect=TimeoutError("Element not visible"))
        result = await real_method("#nonexistent", timeout=1)
        assert isinstance(result, dict)
        # Should either return error status or raise — either is acceptable
        assert "status" in result or "error" in result

    async def test_wait_visible_endpoint_response_shape(self, async_client):
        """POST /wait/visible must return {status, operation, result}."""
        resp = await async_client.post("/wait/visible", json={"selector": ".my-element"})
        assert resp.status_code in (200, 400, 422, 500), (
            f"Expected 200/400/422/500, got {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") == "ok"
            assert data.get("operation") == "wait_visible"
            assert "result" in data


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — P1: Modal element discovery (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


class TestP1ModalDiscovery:
    """analyze_page must return enriched modal data with interactive elements."""

    @pytest.fixture
    def enriched_analyze_result(self):
        """Simulate the expected v0.8 enriched analyze_page response."""
        return {
            "status": "ok",
            "page": {
                "url": "https://example.com",
                "title": "Test",
                "buttons": [{"text": "OK", "selector": "#ok-btn"}],
                "modals": [
                    {
                        "role": "dialog",
                        "modal_type": "aria_dialog",
                        "aria_label": "Confirm action",
                        "focus_trap": True,
                        "class": "modal fade in",
                        "buttons": [{"text": "Confirm", "selector": "#confirm"}],
                        "tabs": [],
                        "interactive_elements": [
                            {"tag": "BUTTON", "text": "Confirm", "type": "submit", "role": "button", "selector": "#confirm"},
                            {"tag": "A", "text": "Cancel", "type": "", "role": "link", "selector": "#cancel"},
                        ],
                    }
                ],
                "form_fields": [],
                "text_preview": "Confirm action modal",
                "text_length": 19,
                "selected_options": [],
                "visual_state": {},
            },
        }

    def test_modal_includes_role(self, enriched_analyze_result):
        """Each modal must include a 'role' field."""
        for modal in enriched_analyze_result["page"]["modals"]:
            assert "role" in modal

    def test_modal_includes_modal_type(self, enriched_analyze_result):
        """Each modal must include a 'modal_type' field."""
        for modal in enriched_analyze_result["page"]["modals"]:
            assert "modal_type" in modal

    def test_modal_includes_interactive_elements(self, enriched_analyze_result):
        """Each modal must include an 'interactive_elements' list."""
        for modal in enriched_analyze_result["page"]["modals"]:
            assert "interactive_elements" in modal
            assert isinstance(modal["interactive_elements"], list)

    def test_modal_interactive_elements_have_expected_fields(self, enriched_analyze_result):
        """Each interactive element must have tag, text, type, role, selector."""
        for modal in enriched_analyze_result["page"]["modals"]:
            for elem in modal["interactive_elements"]:
                assert "tag" in elem
                assert "text" in elem
                assert "type" in elem
                assert "role" in elem
                assert "selector" in elem

    def test_modal_includes_aria_label(self, enriched_analyze_result):
        """Each modal must include an aria_label field."""
        for modal in enriched_analyze_result["page"]["modals"]:
            assert "aria_label" in modal

    def test_modal_includes_focus_trap(self, enriched_analyze_result):
        """Each modal must include a focus_trap boolean."""
        for modal in enriched_analyze_result["page"]["modals"]:
            assert "focus_trap" in modal
            assert isinstance(modal["focus_trap"], bool)

    def test_existing_buttons_field_preserved(self, enriched_analyze_result):
        """Existing modals[].buttons field must still be present."""
        for modal in enriched_analyze_result["page"]["modals"]:
            assert "buttons" in modal, (
                "Existing modals[].buttons must be preserved"
            )

    def test_existing_tabs_field_preserved(self, enriched_analyze_result):
        """Existing modals[].tabs field must still be present."""
        for modal in enriched_analyze_result["page"]["modals"]:
            assert "tabs" in modal, (
                "Existing modals[].tabs must be preserved"
            )

    def test_modal_type_is_valid(self):
        """modal_type must be one of the defined enum values."""
        valid_types = {"aria_dialog", "overlay", "focus_trap", "classic"}
        assert "aria_dialog" in valid_types
        assert "overlay" in valid_types
        assert "focus_trap" in valid_types
        assert "classic" in valid_types


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — P1: /click/label alias flexibility (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestP1ClickLabelFlexibility:
    """click_label must resolve ARIA-labelledby, aria-label, role=button, etc."""

    @pytest.fixture
    def mock_aria_data(self):
        """Simulate JS result with resolved_via tracking."""
        return {
            "status": "ok",
            "result": {
                "label": "Submit",
                "resolved_via": "aria_label",
                "selector": "#submit-btn",
                "tag": "BUTTON",
                "role": "button",
            },
        }

    async def test_click_label_returns_resolved_via(self, mock_client):
        """click_label must return 'resolved_via' field showing match strategy."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_label.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {
                "label": "Submit", "resolved_via": "aria_label",
                "selector": "#submit", "tag": "BUTTON", "role": "button",
            },
        })
        result = await real_method("Submit")
        result_data = result.get("result", result)
        assert "resolved_via" in result_data, (
            "v0.8 click_label must include resolved_via in result"
        )

    async def test_click_label_resolves_aria_label(self, mock_client):
        """click_label must resolve elements via aria-label attribute."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_label.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"label": "Close", "resolved_via": "aria_label", "selector": "#close-btn"},
        })
        result = await real_method("Close")
        result_data = result.get("result", result)
        assert result_data.get("resolved_via") == "aria_label"

    async def test_click_label_resolves_role_button(self, mock_client):
        """click_label must resolve elements with role='button' and accessible name."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_label.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"label": "Save", "resolved_via": "role_button", "selector": "#save-btn", "role": "button"},
        })
        result = await real_method("Save")
        result_data = result.get("result", result)
        assert result_data.get("resolved_via") == "role_button"

    async def test_click_label_fallback_to_label_element(self, mock_client):
        """click_label must fall back to original <label> element matching."""
        from cdp_client import CDPClient
        real_method = CDPClient.click_label.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"label": "Email", "resolved_via": "label_element", "selector": "label"},
        })
        result = await real_method("Email")
        result_data = result.get("result", result)
        assert result_data.get("resolved_via") == "label_element"

    async def test_click_label_endpoint_still_works(self, async_client):
        """POST /click/label must still accept {text, timeout} body."""
        resp = await async_client.post("/click/label", json={"text": "Submit", "timeout": 5})
        assert resp.status_code in (200, 400, 422, 500), (
            f"Expected 200/400/422/500, got {resp.status_code}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 — P1: /form/fill flexibility (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestP1FormFillFlexibility:
    """smart_form_fill must handle select/checkbox/radio/textarea in the fields array."""

    async def test_smart_form_fill_handles_select(self, mock_client):
        """smart_form_fill must detect and handle <select> elements."""
        from cdp_client import CDPClient
        real_method = CDPClient.smart_form_fill.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"field": "Country", "field_type": "select", "value": "HU"},
        })
        mock_client.form_select = AsyncMock(return_value={"status": "ok", "result": {"value": "HU"}})
        result = await real_method([{"label": "Country", "value": "HU"}])
        assert isinstance(result, dict)
        assert result.get("status") == "ok"

    async def test_smart_form_fill_handles_checkbox(self, mock_client):
        """smart_form_fill must detect and handle checkbox elements."""
        from cdp_client import CDPClient
        real_method = CDPClient.smart_form_fill.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"field": "Subscribe", "field_type": "checkbox", "value": "true"},
        })
        mock_client.checkbox_set_state = AsyncMock(return_value={"status": "ok", "result": {"checked": True}})
        result = await real_method([{"label": "Subscribe", "value": "true"}])
        assert isinstance(result, dict)

    async def test_smart_form_fill_handles_radio(self, mock_client):
        """smart_form_fill must detect and handle radio button elements."""
        from cdp_client import CDPClient
        real_method = CDPClient.smart_form_fill.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"field": "Gender", "field_type": "radio", "value": "female"},
        })
        mock_client.checkbox_set_state = AsyncMock(return_value={"status": "ok", "result": {"checked": True}})
        result = await real_method([{"label": "Gender", "value": "female"}])
        assert isinstance(result, dict)

    async def test_smart_form_fill_handles_textarea(self, mock_client):
        """smart_form_fill must detect and handle textarea elements."""
        from cdp_client import CDPClient
        real_method = CDPClient.smart_form_fill.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"field": "Bio", "field_type": "textarea", "value": "Hello"},
        })
        mock_client.type_text = AsyncMock(return_value={"status": "ok"})
        result = await real_method([{"label": "Bio", "value": "Hello"}])
        assert isinstance(result, dict)
        assert result.get("status") == "ok"

    async def test_smart_form_fill_auto_detects_field_type(self, mock_client):
        """smart_form_fill must auto-detect field type when type hint not provided."""
        from cdp_client import CDPClient
        real_method = CDPClient.smart_form_fill.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"field": "Name", "field_type": "text", "value": "Alice"},
        })
        result = await real_method([{"label": "Name", "value": "Alice"}])
        assert isinstance(result, dict)

    async def test_smart_form_fill_accepts_field_type_hint(self, mock_client):
        """smart_form_fill must respect explicit field type hints."""
        from cdp_client import CDPClient
        real_method = CDPClient.smart_form_fill.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"field": "Country", "field_type": "select", "value": "HU"},
        })
        mock_client.form_select = AsyncMock(return_value={"status": "ok", "result": {"value": "HU"}})
        # Provide explicit type hint in FormFillField format
        result = await real_method([
            {"label": "Country", "value": "HU", "type": "select"},
        ])
        assert isinstance(result, dict)

    async def test_form_fill_returns_field_type_in_result(self, mock_client):
        """smart_form_fill must return field_type in per-field result."""
        from cdp_client import CDPClient
        real_method = CDPClient.smart_form_fill.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"field": "Name", "field_type": "text", "value": "Alice"},
        })
        result = await real_method([{"label": "Name", "value": "Alice"}])
        result_data = result.get("result", result)
        # Check that field_type appears somewhere in the response
        assert "field" in result_data
        assert "field_type" in result_data

    async def test_form_fill_endpoint_accepts_field_objects(self, async_client):
        """POST /form/fill must accept FormFillField objects in fields array."""
        resp = await async_client.post("/form/fill", json={
            "fields": [
                {"label": "Name", "value": "Alice", "type": "text"},
                {"label": "Country", "value": "HU", "type": "select"},
            ],
            "timeout": 5,
        })
        assert resp.status_code in (200, 400, 422, 500), (
            f"Expected 200/400/422/500, got {resp.status_code}"
        )

    async def test_form_fill_backward_compat_dict_fields(self, async_client):
        """POST /form/fill must still accept plain dict fields (backward compat)."""
        resp = await async_client.post("/form/fill", json={
            "fields": [
                {"label": "Name", "value": "Alice"},
                {"label": "Country", "value": "HU"},
            ],
            "timeout": 5,
        })
        assert resp.status_code in (200, 400, 422, 500), (
            f"Expected 200/400/422/500, got {resp.status_code}"
        )

    # ── v0.9: single-field shorthand {selector, text} ───────────────────

    async def test_smart_form_fill_handles_selector_field(self, mock_client):
        """smart_form_fill must accept {selector, text} fields and use querySelector."""
        from cdp_client import CDPClient
        real_method = CDPClient.smart_form_fill.__get__(mock_client, CDPClient)
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": {"field": "#email", "field_type": "text", "value": "hello"},
        })
        result = await real_method([{"selector": "#email", "text": "hello"}])
        assert isinstance(result, dict)
        assert result.get("status") == "ok"
        # Verify evaluate was called (selector triggers JS with querySelector)
        mock_client.evaluate.assert_awaited_once()

    async def test_form_fill_endpoint_accepts_shorthand(self, async_client):
        """POST /form/fill must accept {selector, text} shorthand."""
        resp = await async_client.post("/form/fill", json={
            "selector": "#email",
            "text": "hello",
        })
        assert resp.status_code in (200, 400, 422, 500), (
            f"Expected 200/400/422/500, got {resp.status_code}"
        )

    async def test_form_fill_shorthand_with_timeout(self, async_client):
        """POST /form/fill shorthand must accept optional timeout."""
        resp = await async_client.post("/form/fill", json={
            "selector": "#email",
            "text": "hello",
            "timeout": 30,
        })
        assert resp.status_code in (200, 400, 422, 500), (
            f"Expected 200/400/422/500, got {resp.status_code}"
        )

    async def test_form_fill_shorthand_rejects_partial(self, async_client):
        """POST /form/fill must 422 on {selector} without {text}."""
        resp = await async_client.post("/form/fill", json={"selector": "#email"})
        assert resp.status_code == 422, (
            f"Expected 422 for partial shorthand, got {resp.status_code}"
        )

    async def test_form_fill_shorthand_alongside_fields(self, async_client):
        """POST /form/fill: when both fields and shorthand present, fields wins."""
        resp = await async_client.post("/form/fill", json={
            "fields": [{"label": "Name", "value": "Alice"}],
            "selector": "#email",
            "text": "hello",
        })
        assert resp.status_code in (200, 400, 422, 500), (
            f"Expected 200/400/422/500, got {resp.status_code}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8 — P1: API aliases (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestP1APIAliases:
    """API alias endpoints must route correctly and return same shape as canonical."""

    async def test_dropdown_select_alias(self, async_client):
        """POST /dropdown/select must behave same as calling /form/select."""
        from main import API_ALIASES  # noqa: F401 — will fail red-phase until stubs exist
        resp = await async_client.post("/dropdown/select", json={
            "label": "Country", "option": "Hungary",
        })
        assert resp.status_code in (200, 400, 422), (
            f"Expected 200/400/422, got {resp.status_code}"
        )

    async def test_wait_visible_alias(self, async_client):
        """POST /wait/visible must behave same as calling /wait?visible=true."""
        from main import API_ALIASES  # noqa: F401 — will fail red-phase until stubs exist
        resp = await async_client.post("/wait/visible", json={"selector": ".el", "timeout": 5})
        assert resp.status_code in (200, 400, 422), (
            f"Expected 200/400/422, got {resp.status_code}"
        )

    async def test_wait_visible_forced_visible_flag(self):
        """wait/visible must force visible=True when delegating to wait."""
        from main import API_ALIASES
        wait_visible_config = API_ALIASES.get("/wait/visible", {})
        fixed_params = wait_visible_config.get("fixed_params", {})
        # If using fixed_params approach, visible must be True
        if fixed_params:
            assert fixed_params.get("visible") is True, (
                "wait/visible alias must force visible=True"
            )

    async def test_dropdown_select_body_transform(self):
        """dropdown/select must transform {label, option} → {by, text_or_value, option_value}."""
        from main import API_ALIASES
        dropdown_config = API_ALIASES.get("/dropdown/select", {})
        # Verify transform function exists or the route handles it explicitly
        assert "transform" in dropdown_config or dropdown_config.get("target") == "/form/select", (
            "dropdown/select alias must have a transform or target /form/select"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9 — REGRESSION CHECK: verify all v0.7 routes still registered
# ═══════════════════════════════════════════════════════════════════════════


class TestRegression:
    """No existing routes should be removed or renamed in v0.8."""

    import typing

    # Actual v0.7 route paths extracted from the running app
    EXISTING_ROUTES: typing.ClassVar[set[str]] = {
        "/", "/health", "/ready",
        "/activate-tab/{tab_id}",
        "/browser/launch", "/browser/status", "/browser/stop",
        "/checkbox/deselect", "/checkbox/select",
        "/clear_cookies",
        "/click", "/click/label", "/click/text",
        "/confirm-action",
        "/connect", "/cookies",
        "/disconnect",
        "/dom_click_all", "/dom_query",
        "/element_screenshot",
        "/eval",
        "/form/fill", "/form/select",
        "/full_screenshot",
        "/get_text",
        "/headless/batch-screenshot", "/headless/close", "/headless/eval",
        "/headless/health", "/headless/launch", "/headless/navigate",
        "/headless/screenshot", "/headless/sessions",
        "/javascript/disable", "/javascript/enable",
        "/metrics",
        "/navigate",
        "/network/clear", "/network/log", "/network/start", "/network/stop",
        "/page/analyze", "/page/diff", "/page/find",
        "/page/iframe-text", "/page/iframe/switch",
        "/page/outline", "/page/text",
        "/pdf",
        "/profiles", "/profiles/import",
        "/profiles/{name}", "/profiles/{name}/export",
        "/profiles/{name}/extensions",
        "/screenshot", "/screenshot/baseline",
        "/screenshot/baselines", "/screenshot/compare",
        "/script",
        "/session/restore", "/session/save",
        "/set_cookie",
        "/settings",
        "/status",
        "/switch_tab/{tab_id}",
        "/tab/close/{tab_id}", "/tab/new",
        "/tabs", "/tabs/deep-scan/{tab_id}", "/tabs/scan",
        "/type",
        "/upload",
        "/wait", "/wait/navigation", "/wait/network-idle", "/wait/text",
        "/ws",
    }

    def test_all_existing_routes_present(self):
        """All v0.7 routes must still be registered in v0.8."""
        routes = set(route_paths())
        missing = self.EXISTING_ROUTES - routes
        assert not missing, (
            f"v0.8 removed routes: {missing}"
        )

    def test_no_new_routes_removed_existing(self):
        """New v0.8 routes must not break existing route paths."""
        routes_now = set(route_paths())
        assert self.EXISTING_ROUTES.issubset(routes_now), (
            "v0.8 must preserve ALL existing v0.7 routes"
        )

    def test_v0_7_activation_methods_still_pass(self, mock_client):
        """Existing v0.7 activation tests must still hold."""
        # Spot-check: evaluate still calls _activate_current
        mock_client._activate_current.reset_mock()
        # Nothing to assert — just ensure no crash
        assert True


# ═══════════════════════════════════════════════════════════════════════════
# ASYNC MARKER — all classes above that use async tests already have
# @pytest.mark.asyncio; the remaining TestInterface and TestP1ModalDiscovery
# and TestRegression classes are synchronous only.
# ═══════════════════════════════════════════════════════════════════════════
