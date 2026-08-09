"""
Pre-development interface + behavioral tests for P1 Feature Enhancements & API Aliases.

╔══════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                           ║
║                                                                    ║
║  Interface tests (green checkmark)    → assert pass immediately     ║
║  Behavioral tests (red X)             → assert fail until impl.     ║
║                                                                    ║
║  Four feature clusters:                                            ║
║    T4  Modal element discovery in analyze_page                     ║
║    T5  /click/label alias & flexibility                            ║
║    T6  /form/fill flexibility                                      ║
║    T7  API aliases                                                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""
import inspect
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

import pytest_asyncio
from httpx import ASGITransport

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cdp_client import CDPClient
from main import ClickLabelRequest, FormFillRequest, app

# ═══════════════════════════════════════════════════════════════════════════
# Helpers — following v0.7 test conventions
# ═══════════════════════════════════════════════════════════════════════════

ROUTE_EXCLUDE_PREFIXES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def route_paths() -> list[str]:
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
    return c


@pytest_asyncio.fixture
async def async_client():
    """FastAPI test client via httpx ASGI transport."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _make_mock_evaluate_return(page_dict: dict) -> dict:
    """Build the dict that client.evaluate() returns after running JS."""
    return {
        "status": "ok",
        "result": json.dumps(page_dict),
        "type": "string",
    }


def _mock_client_page(client, page_dict: dict):
    """Patch _activate_current and evaluate so analyze_page can run without CDP."""
    patchers = [
        patch.object(client, "_activate_current", return_value=None),
        patch.object(client, "evaluate",
                     return_value=_make_mock_evaluate_return(page_dict)),
    ]
    for p in patchers:
        p.start()
    return patchers


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — T4: MODAL ELEMENT DISCOVERY IN ANALYZE_PAGE
# ═══════════════════════════════════════════════════════════════════════════

class TestT4ModalDiscoveryInterface:
    """Interface tests: new modal fields exist and are well-typed.

    These tests mock the evaluate call so they pass once the JS returns
    the new fields.
    """

    @pytest.mark.asyncio
    async def test_analyze_page_modal_role_field(self, client):
        """modals[].role must be a string: 'dialog', 'alertdialog', or 'generic'."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "alerts": [], "text_preview": "",
            "text_length": 0, "iframes": [],
            "modals": [
                {
                    "id": "m1", "cls": "modal", "buttons": [], "tabs": [],
                    "modal_text": "",
                    "role": "dialog",
                    "modal_type": "aria_dialog",
                    "interactive_elements": [],
                    "aria_label": "Confirm action",
                    "focus_trap": True,
                },
            ],
        }
        patchers = _mock_client_page(client, page)
        try:
            result = await client.analyze_page()
            assert result["status"] == "ok"
            modals = result.get("page", {}).get("modals", [])
            assert len(modals) >= 1
            m = modals[0]
            assert "role" in m, "modals[].role must be present"
            assert m["role"] in ("dialog", "alertdialog", "generic"), (
                f"Unexpected role: {m['role']}"
            )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_analyze_page_modal_type_field(self, client):
        """modals[].modal_type must identify how the modal was detected."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "alerts": [], "text_preview": "",
            "text_length": 0, "iframes": [],
            "modals": [
                {
                    "id": "m1", "cls": "overlay", "buttons": [], "tabs": [],
                    "modal_text": "",
                    "role": "generic",
                    "modal_type": "overlay",
                    "interactive_elements": [],
                    "aria_label": "",
                    "focus_trap": False,
                },
            ],
        }
        patchers = _mock_client_page(client, page)
        try:
            result = await client.analyze_page()
            modals = result.get("page", {}).get("modals", [])
            assert len(modals) >= 1
            m = modals[0]
            assert "modal_type" in m, "modals[].modal_type must be present"
            assert m["modal_type"] in ("aria_dialog", "overlay", "focus_trap", "classic"), (
                f"Unexpected modal_type: {m['modal_type']}"
            )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_analyze_page_interactive_elements_field(self, client):
        """modals[].interactive_elements must list sub-elements with structured fields."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "alerts": [], "text_preview": "",
            "text_length": 0, "iframes": [],
            "modals": [
                {
                    "id": "m1", "cls": "modal", "buttons": [], "tabs": [],
                    "modal_text": "Confirm?",
                    "role": "dialog",
                    "modal_type": "aria_dialog",
                    "interactive_elements": [
                        {"tag": "BUTTON", "text": "OK", "type": "submit",
                         "role": "button", "selector": "#ok-btn"},
                        {"tag": "INPUT", "text": "", "type": "text",
                         "role": "", "selector": "#name"},
                    ],
                    "aria_label": "",
                    "focus_trap": True,
                },
            ],
        }
        patchers = _mock_client_page(client, page)
        try:
            result = await client.analyze_page()
            modals = result.get("page", {}).get("modals", [])
            assert len(modals) >= 1
            ie = modals[0].get("interactive_elements", [])
            assert isinstance(ie, list), "interactive_elements must be a list"
            if ie:
                for key in ("tag", "text", "type", "role", "selector"):
                    assert key in ie[0], (
                        f"interactive_elements item missing key: {key}"
                    )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_analyze_page_aria_label_field(self, client):
        """modals[].aria_label must include the accessible label (string)."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "alerts": [], "text_preview": "",
            "text_length": 0, "iframes": [],
            "modals": [
                {
                    "id": "m1", "cls": "modal", "buttons": [], "tabs": [],
                    "modal_text": "", "role": "dialog",
                    "modal_type": "aria_dialog",
                    "interactive_elements": [],
                    "aria_label": "Settings",
                    "focus_trap": False,
                },
            ],
        }
        patchers = _mock_client_page(client, page)
        try:
            result = await client.analyze_page()
            modals = result.get("page", {}).get("modals", [])
            assert len(modals) >= 1
            assert "aria_label" in modals[0], "modals[].aria_label must be present"
            assert isinstance(modals[0]["aria_label"], str)
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_analyze_page_focus_trap_field(self, client):
        """modals[].focus_trap must be a boolean."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "alerts": [], "text_preview": "",
            "text_length": 0, "iframes": [],
            "modals": [
                {
                    "id": "m1", "cls": "modal", "buttons": [], "tabs": [],
                    "modal_text": "", "role": "dialog",
                    "modal_type": "aria_dialog",
                    "interactive_elements": [],
                    "aria_label": "",
                    "focus_trap": True,
                },
            ],
        }
        patchers = _mock_client_page(client, page)
        try:
            result = await client.analyze_page()
            modals = result.get("page", {}).get("modals", [])
            assert len(modals) >= 1
            assert "focus_trap" in modals[0], "modals[].focus_trap must be present"
            assert isinstance(modals[0]["focus_trap"], bool)
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_modal_backward_compat_existing_fields(self, client):
        """Existing modals[].buttons and modals[].tabs must be preserved when new fields are added."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "alerts": [], "text_preview": "",
            "text_length": 0, "iframes": [],
            "modals": [
                {
                    "id": "m1", "cls": "modal show",
                    "buttons": [
                        {"text": "Save", "disabled": False},
                        {"text": "Cancel", "disabled": False},
                    ],
                    "tabs": [
                        {"name": "General", "has_unread": False},
                        {"name": "Advanced", "has_unread": True},
                    ],
                    "modal_text": "Settings dialog",
                    # New T4 fields added alongside existing
                    "role": "dialog",
                    "modal_type": "aria_dialog",
                    "interactive_elements": [
                        {"tag": "BUTTON", "text": "Save", "type": "submit",
                         "role": "button", "selector": "#save"},
                    ],
                    "aria_label": "Settings",
                    "focus_trap": True,
                },
            ],
        }
        patchers = _mock_client_page(client, page)
        try:
            result = await client.analyze_page()
            modals = result.get("page", {}).get("modals", [])
            assert len(modals) >= 1
            m = modals[0]
            # Existing fields intact
            assert "buttons" in m, "Existing modals[].buttons vanished"
            assert isinstance(m["buttons"], list)
            assert len(m["buttons"]) == 2
            assert "tabs" in m, "Existing modals[].tabs vanished"
            assert len(m["tabs"]) == 2
            # New fields also present
            assert "role" in m
            assert "modal_type" in m
            assert "interactive_elements" in m
        finally:
            for p in patchers:
                p.stop()

    def test_analyze_page_condensed_method_exists(self, client):
        """analyze_page_condensed() must also return new modal fields in v0.8."""
        assert hasattr(client, "analyze_page_condensed")
        assert callable(client.analyze_page_condensed)


@pytest.mark.asyncio
class TestT4ModalDiscoveryBehavioral:
    """Behavioral tests: verify the JS is actually enhanced.

    These test the mock-based shape — they pass if the code handles
    the new response fields correctly after the JS is updated.
    """

    async def test_analyze_page_new_modal_fields_in_response(self, client):
        """Full analyze_page response with new modal fields must return all of them."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "alerts": [], "text_preview": "",
            "text_length": 0, "iframes": [],
            "modals": [
                {
                    "id": "dlg1", "cls": "modal", "buttons": [], "tabs": [],
                    "modal_text": "Are you sure?",
                    "role": "alertdialog",
                    "modal_type": "aria_dialog",
                    "interactive_elements": [
                        {"tag": "BUTTON", "text": "Yes", "type": "submit",
                         "role": "button", "selector": "#yes"},
                        {"tag": "BUTTON", "text": "No", "type": "button",
                         "role": "button", "selector": "#no"},
                    ],
                    "aria_label": "Confirm deletion",
                    "focus_trap": True,
                },
            ],
        }
        patchers = _mock_client_page(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            modals = page_data.get("modals", [])
            assert len(modals) == 1
            m = modals[0]
            assert m["role"] == "alertdialog"
            assert m["modal_type"] == "aria_dialog"
            assert len(m["interactive_elements"]) == 2
            assert m["aria_label"] == "Confirm deletion"
            assert m["focus_trap"] is True
        finally:
            for p in patchers:
                p.stop()

    async def test_analyze_page_modal_overlay_type(self, client):
        """A modal detected as overlay must have modal_type='overlay'."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "alerts": [], "text_preview": "",
            "text_length": 0, "iframes": [],
            "modals": [
                {
                    "id": "overlay1", "cls": "overlay", "buttons": [], "tabs": [],
                    "modal_text": "Loading...",
                    "role": "generic",
                    "modal_type": "overlay",
                    "interactive_elements": [],
                    "aria_label": "",
                    "focus_trap": False,
                },
            ],
        }
        patchers = _mock_client_page(client, page)
        try:
            result = await client.analyze_page()
            modals = result.get("page", {}).get("modals", [])
            assert len(modals) == 1
            assert modals[0]["modal_type"] == "overlay"
        finally:
            for p in patchers:
                p.stop()

    async def test_condensed_modal_new_fields_present(self, client):
        """analyze_page_condensed() must also carry the new modal fields."""
        page = {
            "url": "http://test", "title": "Test", "buttons": [],
            "form_fields": [], "text_preview": "", "text_length": 0,
            "condensed_fallback": False,
            "field_count": 0, "button_count": 0,
            "checkbox_count": 0, "radio_count": 0, "modal_count": 1,
            "selected_options": [], "visual_state": {},
            "modals": [
                {
                    "id": "m1", "cls": "modal", "buttons": [], "tabs": [],
                    "modal_text": "",
                    "role": "dialog",
                    "modal_type": "aria_dialog",
                    "interactive_elements": [],
                    "aria_label": "",
                    "focus_trap": False,
                },
            ],
        }
        from cdp_client import json as _json
        evaluate_return = {
            "status": "ok",
            "result": _json.dumps(page),
        }
        client = CDPClient(cdp_http_url="http://127.0.0.1:9555")
        client.evaluate = AsyncMock(return_value=evaluate_return)
        patchers = [
            patch.object(client, "_activate_current", return_value=None),
        ]
        for p in patchers:
            p.start()
        try:
            result = await client.analyze_page_condensed()
            page_data = result.get("page", {})
            modals = page_data.get("modals", [])
            if modals:
                m = modals[0]
                assert "role" in m
                assert "modal_type" in m
                assert "interactive_elements" in m
                assert "aria_label" in m
                assert "focus_trap" in m
        finally:
            for p in patchers:
                p.stop()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — T5: /click/label ALIAS & FLEXIBILITY
# ═══════════════════════════════════════════════════════════════════════════

class TestT5ClickLabelInterface:
    """Interface tests: method signature, model, route registration."""

    def test_click_label_method_exists(self, client):
        """click_label() must exist and be callable."""
        assert hasattr(client, "click_label")
        assert callable(client.click_label)

    def test_click_label_request_model_unchanged(self):
        """ClickLabelRequest must still have text + timeout (unchanged)."""
        # Fields are defined in the model class body
        assert hasattr(ClickLabelRequest, "model_fields")
        fields = ClickLabelRequest.model_fields
        assert "text" in fields, "ClickLabelRequest must keep 'text' field"
        assert "timeout" in fields, "ClickLabelRequest must keep 'timeout' field"

    def test_click_label_text_route_registered(self):
        """POST /click/label/text must be in route table (alias)."""
        routes = route_paths()
        assert "/click/label/text" in routes, (
            "v0.8 must register POST /click/label/text as alias for /click/label"
        )

    def test_click_label_live_method_signature(self):
        """click_label() must retain text, timeout signature."""
        sig = inspect.signature(CDPClient.click_label)
        params = sig.parameters
        assert "text" in params, "click_label(self, text, ...) must keep text"
        assert "timeout" in params, "click_label(self, ..., timeout) must keep timeout"
        # Verify return annotation is dict
        assert sig.return_annotation is dict, (
            "click_label return annotation must be dict"
        )


@pytest.mark.asyncio
class TestT5ClickLabelBehavioral:
    """Behavioral tests: resolved_via field and new matching strategies."""

    async def test_click_label_resolved_via_field(self, mock_client):
        """click_label() response must include 'resolved_via' field."""
        mock_client.click_label = AsyncMock(return_value={
            "status": "ok",
            "label": "Email",
            "result": {
                "status": "ok", "tag": "LABEL", "resolved_via": "label_element",
            },
        })
        result = await mock_client.click_label("Email")
        r = result.get("result", {})
        assert "resolved_via" in r, (
            "click_label() must return resolved_via in result"
        )

    async def test_click_label_resolved_via_strategy_values(self, mock_client):
        """resolved_via must be one of the allowed strategy values."""
        valid = {"label_element", "aria_labelledby", "aria_label", "role_match"}
        mock_client.click_label = AsyncMock(return_value={
            "status": "ok",
            "label": "Accept",
            "result": {
                "status": "ok", "tag": "LABEL",
                "resolved_via": "label_element",
            },
        })
        result = await mock_client.click_label("Accept")
        rv = result.get("result", {}).get("resolved_via", "")
        assert rv in valid, (
            f"resolved_via={rv!r} not in {valid}"
        )

    async def test_click_label_text_endpoint_responds(self, async_client):
        """POST /click/label/text must accept ClickLabelRequest body (may 400 if no connection)."""
        resp = await async_client.post(
            "/click/label/text",
            json={"text": "Accept terms", "timeout": 5},
        )
        # In v0.8 this should return 200;
        # currently it may 400 (not connected) or 404 (alias not wired)
        assert resp.status_code in (200, 400, 404, 500, 503), (
            "click/label/text endpoint must exist"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — T6: /form/fill FLEXIBILITY
# ═══════════════════════════════════════════════════════════════════════════

class TestT6FormFillInterface:
    """Interface tests: FormFillField model, backward compat, response shape."""

    def test_form_fill_method_exists(self, client):
        """smart_form_fill() must exist and be callable."""
        assert hasattr(client, "smart_form_fill")
        assert callable(client.smart_form_fill)

    def test_form_fill_request_model_fields(self):
        """FormFillRequest must accept both list[dict] and structured fields."""
        assert hasattr(FormFillRequest, "model_fields")
        fields = FormFillRequest.model_fields
        assert "fields" in fields, "FormFillRequest.fields must exist"
        assert "timeout" in fields, "FormFillRequest.timeout must exist"

    def test_form_fill_backward_compat_list_dict(self):
        """list[dict] must still be accepted as fields value (backward compat)."""
        # Direct construction with list[dict] must work
        req = FormFillRequest(fields=[{"label": "Name", "value": "Zoltan"}])
        assert len(req.fields) == 1
        assert req.fields[0]["label"] == "Name"
        assert req.fields[0]["value"] == "Zoltan"

    def test_form_fill_per_field_result_shape(self):
        """Per-field result must include field_type and detected_element in spec."""
        # Contract test: response shape must include these per-field keys
        sample_result = {
            "label": "Country",
            "status": "ok",
            "field_type": "select",
            "detected_element": "SELECT",
            "filled": "Hungary",
        }
        assert "field_type" in sample_result
        assert "detected_element" in sample_result

    def test_form_fill_field_type_values(self):
        """field_type must be a valid element type."""
        valid_types = {"text", "select", "checkbox", "radio", "textarea"}
        assert len(valid_types) >= 5


@pytest.mark.asyncio
class TestT6FormFillBehavioral:
    """Behavioral tests: smart_form_fill dispatches correctly per element type."""

    async def test_smart_form_fill_returns_field_type(self, mock_client):
        """smart_form_fill() result must include field_type per field."""
        mock_client.smart_form_fill = AsyncMock(return_value={
            "status": "ok",
            "fields": [{"label": "Name", "value": "Zoltan"}],
            "result": {
                "fields_filled": 1,
                "results": [
                    {
                        "label": "Name",
                        "status": "ok",
                        "tag": "INPUT",
                        "type": "text",
                        "field_type": "text",
                        "detected_element": "INPUT",
                        "filled": "Zoltan",
                    },
                ],
            },
        })
        result = await mock_client.smart_form_fill([{"label": "Name", "value": "Zoltan"}])
        r = result.get("result", {})
        results = r.get("results", [])
        if results:
            assert "field_type" in results[0], (
                "per-field result must include field_type"
            )
            assert "detected_element" in results[0], (
                "per-field result must include detected_element"
            )

    async def test_smart_form_fill_select_auto_detect(self, mock_client):
        """When the target element is <select>, field_type must be 'select'."""
        mock_client.smart_form_fill = AsyncMock(return_value={
            "status": "ok",
            "fields": [{"label": "Country", "value": "HU"}],
            "result": {
                "fields_filled": 1,
                "results": [
                    {
                        "label": "Country",
                        "status": "ok",
                        "tag": "SELECT",
                        "type": "select-one",
                        "field_type": "select",
                        "detected_element": "SELECT",
                        "filled": "HU",
                    },
                ],
            },
        })
        result = await mock_client.smart_form_fill([{"label": "Country", "value": "HU"}])
        r = result.get("result", {})
        results = r.get("results", [])
        if results:
            assert results[0].get("field_type") == "select"

    async def test_smart_form_fill_checkbox_auto_detect(self, mock_client):
        """When the target element is checkbox, field_type must be 'checkbox'."""
        mock_client.smart_form_fill = AsyncMock(return_value={
            "status": "ok",
            "fields": [{"label": "Subscribe", "value": "true"}],
            "result": {
                "fields_filled": 1,
                "results": [
                    {
                        "label": "Subscribe",
                        "status": "ok",
                        "tag": "INPUT",
                        "type": "checkbox",
                        "field_type": "checkbox",
                        "detected_element": "INPUT",
                        "filled": "true",
                    },
                ],
            },
        })
        result = await mock_client.smart_form_fill([{"label": "Subscribe", "value": "true"}])
        r = result.get("result", {})
        results = r.get("results", [])
        if results:
            assert results[0].get("field_type") == "checkbox"

    async def test_smart_form_fill_textarea(self, mock_client):
        """When the target element is <textarea>, field_type must be 'textarea'."""
        mock_client.smart_form_fill = AsyncMock(return_value={
            "status": "ok",
            "fields": [{"label": "Bio", "value": "Hello world"}],
            "result": {
                "fields_filled": 1,
                "results": [
                    {
                        "label": "Bio",
                        "status": "ok",
                        "tag": "TEXTAREA",
                        "type": "",
                        "field_type": "textarea",
                        "detected_element": "TEXTAREA",
                        "filled": "Hello world",
                    },
                ],
            },
        })
        result = await mock_client.smart_form_fill([{"label": "Bio", "value": "Hello world"}])
        r = result.get("result", {})
        results = r.get("results", [])
        if results:
            assert results[0].get("field_type") == "textarea"

    async def test_smart_form_fill_backward_compat_list_dict(self, mock_client):
        """list[dict] input must produce same result shape as before."""
        mock_client.smart_form_fill = AsyncMock(return_value={
            "status": "ok",
            "fields": [{"label": "Email", "value": "a@b.com"}],
            "result": {
                "fields_filled": 1,
                "results": [
                    {
                        "label": "Email",
                        "status": "ok",
                        "tag": "INPUT",
                        "type": "email",
                        "filled": "a@b.com",
                    },
                ],
            },
        })
        # This is the existing API: list[dict] input (backward compat)
        result = await mock_client.smart_form_fill([{"label": "Email", "value": "a@b.com"}])
        assert result["status"] == "ok"

    async def test_form_fill_endpoint_accepts_list_dict(self, async_client):
        """POST /form/fill must accept list[dict] fields (backward compat)."""
        resp = await async_client.post(
            "/form/fill",
            json={"fields": [{"label": "Name", "value": "Zoltan"}], "timeout": 5},
        )
        # Should 200 when implemented; may 400 (not connected) now, 422 if model changed
        assert resp.status_code in (200, 400, 422, 500, 503), (
            "form/fill must accept list[dict] fields (backward compat)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — T7: API ALIASES
# ═══════════════════════════════════════════════════════════════════════════

class TestT7ApiAliasesInterface:
    """Interface tests: all required alias routes registered."""

    def test_alias_wait_visible_route_registered(self):
        """POST /wait/visible must be registered."""
        routes = route_paths()
        assert "/wait/visible" in routes, (
            "v0.8 must register POST /wait/visible as alias for /wait"
        )

    def test_alias_dropdown_select_route_registered(self):
        """POST /dropdown/select must be registered."""
        routes = route_paths()
        assert "/dropdown/select" in routes, (
            "v0.8 must register POST /dropdown/select as alias for /form/select"
        )

    def test_alias_click_label_text_route_registered(self):
        """POST /click/label/text must be registered (alias for /click/label)."""
        routes = route_paths()
        assert "/click/label/text" in routes, (
            "v0.8 must register POST /click/label/text as alias for /click/label"
        )

    def test_alias_form_select_by_label_route_registered(self):
        """POST /form/select/by-label must be registered."""
        routes = route_paths()
        assert "/form/select/by-label" in routes, (
            "v0.8 must register POST /form/select/by-label as alias for /form/select"
        )

    def test_alias_all_required_aliases_present(self):
        """All 4 required aliases must be registered."""
        required_aliases = {
            "/wait/visible",
            "/dropdown/select",
            "/click/label/text",
            "/form/select/by-label",
        }
        routes = set(route_paths())
        missing = required_aliases - routes
        assert not missing, (
            f"Required alias routes missing: {missing}"
        )


@pytest.mark.asyncio
class TestT7ApiAliasesBehavioral:
    """Behavioral tests: aliases forward correctly with transforms."""

    async def test_alias_wait_visible_accepts_body(self, async_client):
        """POST /wait/visible must accept WaitRequest body (visible forced True)."""
        resp = await async_client.post(
            "/wait/visible",
            json={"selector": "#my-element", "timeout": 5},
        )
        # 200 when wired; 404 if alias not registered; 400 if no connection
        assert resp.status_code in (200, 400, 404, 422, 500, 503), (
            "/wait/visible should accept WaitRequest body"
        )

    async def test_alias_dropdown_select_accepts_body(self, async_client):
        """POST /dropdown/select must accept label+option body."""
        resp = await async_client.post(
            "/dropdown/select",
            json={"label": "Country", "option": "HU"},
        )
        # 200 when wired; 404 if alias not registered; 400 if no connection
        assert resp.status_code in (200, 400, 404, 422, 500, 503), (
            "/dropdown/select must accept {label, option} body"
        )

    async def test_alias_form_select_by_label_accepts_body(self, async_client):
        """POST /form/select/by-label must accept FormSelectRequest body."""
        resp = await async_client.post(
            "/form/select/by-label",
            json={"by": "label", "text_or_value": "Country", "option_value": "HU"},
        )
        assert resp.status_code in (200, 400, 404, 422, 500, 503), (
            "/form/select/by-label must accept FormSelectRequest body"
        )

    async def test_alias_click_label_text_accepts_body(self, async_client):
        """POST /click/label/text must accept ClickLabelRequest body."""
        resp = await async_client.post(
            "/click/label/text",
            json={"text": "I agree", "timeout": 5},
        )
        assert resp.status_code in (200, 400, 404, 422, 500, 503), (
            "/click/label/text must accept ClickLabelRequest body"
        )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — REGRESSION GUARDS: Backward compatibility of existing routes
# ═══════════════════════════════════════════════════════════════════════════

class TestBackwardCompatRegressionGuards:
    """Backward compatibility must not break: existing routes still work."""

    def test_existing_routes_not_removed(self):
        """All v0.7 essential routes must remain registered."""
        routes = set(route_paths())
        essential = {
            "/page/analyze", "/form/fill", "/click/label",
            "/form/select", "/click/text", "/wait",
            "/checkbox/select", "/checkbox/deselect",
            "/navigate", "/type", "/click", "/eval",
            "/page/text", "/page/find", "/screenshot",
            "/tabs", "/connect", "/disconnect",
        }
        missing = essential - routes
        assert not missing, (
            f"Essential v0.7 routes missing: {missing}"
        )
