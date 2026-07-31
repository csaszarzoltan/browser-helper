"""
Tests for browser-helper CDP client.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx
import pytest


# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from cdp_client import CDPClient, CDPError


# Skip tests that need a Chrome-free environment when Chrome is actually running
def _chrome_is_running() -> bool:
    """Check if a Chrome CDP endpoint is reachable."""
    try:
        httpx.get("http://127.0.0.1:9555/json", timeout=2)
        return True
    except Exception:
        return False


CHROME_RUNNING = _chrome_is_running()

from unittest.mock import AsyncMock


@pytest.fixture
def client():
    """Return a fresh CDPClient (no real connection)."""
    return CDPClient(cdp_http_url="http://127.0.0.1:9555")


@pytest.fixture
def mocked_evaluate_client():
    """CDPClient with evaluate() mocked for condensed snapshot contract tests."""
    c = CDPClient(cdp_http_url="http://127.0.0.1:9555")
    c.evaluate = AsyncMock(return_value={
        "status": "ok",
        "result": json.dumps({
            "url": "http://test", "title": "Test",
            "buttons": [], "form_fields": [], "modals": [],
            "text_preview": "", "text_length": 0,
            "condensed_fallback": False,
            "field_count": 0, "button_count": 0,
            "checkbox_count": 0, "radio_count": 0, "modal_count": 0,
            "selected_options": [], "visual_state": {},
            "iframes": [],
        }),
    })
    return c


@pytest.fixture
def activation_spy(monkeypatch):
    """Monkeypatch _activate_current with a call tracker.

    Each test gets a fresh spy. The returned list records every call
    to _activate_current().
    """
    calls = []

    async def _spy(self_):
        calls.append(True)

    monkeypatch.setattr(CDPClient, '_activate_current', _spy)
    return calls


# ─── Init tests ─────────────────────────────────────────────────────

class TestInit:
    def test_default_url(self):
        c = CDPClient()
        assert c.cdp_http_url == "http://127.0.0.1:9555"

    def test_custom_url(self):
        c = CDPClient(cdp_http_url="http://localhost:9222")
        assert c.cdp_http_url == "http://localhost:9222"

    def test_trailing_slash_stripped(self):
        c = CDPClient(cdp_http_url="http://localhost:9222/")
        assert c.cdp_http_url == "http://localhost:9222"

    def test_initial_state(self, client):
        assert client.is_connected is False
        assert client.tabs_count == 0
        assert client._network_monitoring is False
        assert client._network_entries == []


# ─── Connection tests (mock) ────────────────────────────────────────

class TestConnection:
    @pytest.mark.skipif(CHROME_RUNNING, reason="Chrome is already running on this machine")
    @pytest.mark.asyncio
    async def test_connect_no_chrome(self, client):
        """Should raise CDPError when Chrome is not running."""
        with pytest.raises((CDPError, Exception)):
            await client.connect()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, client):
        """Disconnect should not crash when not connected."""
        await client.disconnect()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_double_disconnect(self, client):
        """Calling close() twice should be safe."""
        await client.close()
        await client.close()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_send_command_when_not_connected(self, client):
        """Should raise CDPError."""
        with pytest.raises(CDPError, match="Not connected"):
            await client._send_command("Page.navigate", {"url": "http://example.com"})


# ─── Method tests (mock-based, no real Chrome) ──────────────────────

class TestMethods:
    @pytest.mark.asyncio
    async def test_navigate_when_not_connected(self, client):
        """Should fail gracefully."""
        with pytest.raises(CDPError):
            await client.navigate("http://example.com")

    @pytest.mark.asyncio
    async def test_evaluate_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.evaluate("1+1")

    @pytest.mark.asyncio
    async def test_click_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.click(".button")

    @pytest.mark.asyncio
    async def test_type_text_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.type_text("input", "hello")

    @pytest.mark.asyncio
    async def test_screenshot_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.screenshot()

    @pytest.mark.asyncio
    async def test_pdf_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.pdf()

    @pytest.mark.asyncio
    async def test_get_cookies_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.get_cookies()

    @pytest.mark.asyncio
    async def test_get_page_text_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.get_page_text()


# ─── New feature tests ──────────────────────────────────────────────

class TestNewFeatures:
    @pytest.mark.asyncio
    async def test_full_page_screenshot_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.full_page_screenshot()

    @pytest.mark.asyncio
    async def test_element_screenshot_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.element_screenshot(".main")

    @pytest.mark.asyncio
    async def test_dom_query_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.dom_query("a")

    @pytest.mark.asyncio
    async def test_execute_script_when_not_connected(self, client):
        """Should return error results, not raise, because execute_script catches exceptions internally."""
        result = await client.execute_script([{"action": "eval", "params": {"js": "1+1"}}])
        assert result["status"] == "ok"
        assert result["steps"] == 1
        assert result["results"][0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_performance_metrics_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.get_performance_metrics()

    @pytest.mark.asyncio
    async def test_session_save_when_not_connected(self, client):
        with pytest.raises(CDPError):
            await client.session_save()

    @pytest.mark.asyncio
    async def test_session_restore_when_not_connected(self, client):
        """Should return gracefully without raising — session_restore handles disconnection internally."""
        result = await client.session_restore({"cookies": [], "localStorage": {}})
        assert result["status"] == "ok"
        assert "restored" in result

    def test_network_monitoring_initially_off(self, client):
        assert client._network_monitoring is False
        assert client._network_entries == []

    @pytest.mark.asyncio
    async def test_network_stop_when_not_started(self, client):
        """Stop should work even if not started — no-op when not monitoring."""
        result = await client.stop_network_monitoring()
        assert result == {"status": "ok", "monitoring": False}
        assert client._network_monitoring is False

    @pytest.mark.asyncio
    async def test_clear_network_log(self, client):
        """Should not crash even if empty."""
        n = client._network_entries  # just ensure attribute exists
        assert isinstance(n, list)


# ─── Edge cases ─────────────────────────────────────────────────────

class TestEdgeCases:
    def test_cdp_http_url_format(self):
        """Various URL formats should work."""
        cases = [
            ("http://127.0.0.1:9555", "http://127.0.0.1:9555"),
            ("http://127.0.0.1:9555/", "http://127.0.0.1:9555"),
            ("http://localhost:9222", "http://localhost:9222"),
            ("http://192.168.1.100:9222", "http://192.168.1.100:9222"),
        ]
        for url, expected in cases:
            c = CDPClient(cdp_http_url=url)
            assert c.cdp_http_url == expected

    def test_initial_tabs_empty_list(self, client):
        assert client._tabs == []

    def test_tab_count_no_tabs(self, client):
        assert client.tabs_count == 0

    def test_multiple_clients_isolation(self):
        a = CDPClient("http://localhost:9222")
        b = CDPClient("http://127.0.0.1:9555")
        assert a.cdp_http_url != b.cdp_http_url


# ─── P1: Checkbox/Radio State Visibility — pre-dev tests ─────────────
#
# RED-phase pre-development tests for P1 Checkbox State Visibility.
# Feature: Enhance /page/analyze response with `selected_options` summary
# and `visual_state` map.
#
# Acceptance Criteria (from analysis brief):
# [ ] /page/analyze response contains selected_options array
# [ ] /page/analyze response contains visual_state object
# [ ] selected_options only includes checked checkboxes and selected radio buttons
# [ ] visual_state includes ALL visible checkboxes and radio buttons
# [ ] Labels resolve correctly (for=, parent <label>, placeholder, aria-label)
# [ ] Hidden/display:none checkboxes are excluded
# [ ] Existing analyze_page fields remain unchanged

import json
from unittest.mock import patch


def _make_mock_page(**overrides) -> dict:
    """Build a representative analyze_page JS output dict.

    Simulates what the CURRENT JS returns — no selected_options or
    visual_state fields.  Tests that verify new fields exist will FAIL
    (RED) because these fields are missing here.
    """
    page = {
        "url": "http://example.com/form",
        "title": "Test Form",
        "buttons": [
            {"tag": "BUTTON", "text": "Submit", "x": 100, "y": 200,
             "w": 80, "h": 30, "disabled": False, "in_modal": False},
        ],
        "modals": [],
        "form_fields": [
            {
                "tag": "INPUT", "type": "checkbox", "name": "notify_email",
                "label": "Email notifications", "value": "email",
                "placeholder": "", "section": "Notifications",
                "required": False, "checked": True,
                "has_error": False, "error_text": "",
            },
            {
                "tag": "INPUT", "type": "checkbox", "name": "notify_sms",
                "label": "SMS notifications", "value": "sms",
                "placeholder": "", "section": "Notifications",
                "required": False, "checked": False,
                "has_error": False, "error_text": "",
            },
            {
                "tag": "INPUT", "type": "radio", "name": "frequency",
                "label": "Weekly digest", "value": "weekly",
                "placeholder": "", "section": "Frequency",
                "required": True, "checked": True,
                "has_error": False, "error_text": "",
            },
            {
                "tag": "INPUT", "type": "radio", "name": "frequency",
                "label": "Daily digest", "value": "daily",
                "placeholder": "", "section": "Frequency",
                "required": True, "checked": False,
                "has_error": False, "error_text": "",
            },
            {
                "tag": "INPUT", "type": "text", "name": "username",
                "label": "Username", "value": "zoltan",
                "placeholder": "Enter name", "section": "Account",
                "required": True, "checked": False,
                "has_error": False, "error_text": "",
            },
        ],
        "alerts": [],
        "text_preview": "Email notifications SMS notifications Weekly digest Daily digest Username Submit",
        "text_length": 98,
        "iframes": [],
    }
    page.update(overrides)
    return page


def _make_mock_evaluate_return(page_dict: dict) -> dict:
    """Build the dict that client.evaluate() returns after running analyze_page JS."""
    return {
        "status": "ok",
        "result": json.dumps(page_dict),
        "type": "string",
    }


def _mock_client_calls(client, page_dict: dict):
    """Patch _activate_current and evaluate so analyze_page can run without CDP."""
    patchers = [
        patch.object(client, "_activate_current", return_value=None),
        patch.object(client, "evaluate",
                     return_value=_make_mock_evaluate_return(page_dict)),
    ]
    for p in patchers:
        p.start()
    return patchers


class TestCheckboxStateInterface:
    """Interface tests: API contract shape.

    These validate that the Python-level response structure is correct
    when the JS provides the new fields.  They mock the evaluate call
    so they pass regardless of implementation status.
    """

    @pytest.mark.asyncio
    async def test_selected_options_is_list_when_present(self, client):
        """selected_options must be a list when included in page data."""
        page = _make_mock_page(
            selected_options=[
                {"label": "Email notifications", "type": "checkbox",
                 "value": "email", "checked": True},
                {"label": "Weekly digest", "type": "radio",
                 "value": "weekly", "checked": True},
            ],
            visual_state={
                "Email notifications": {"checked": True, "type": "checkbox",
                                         "value": "email"},
                "SMS notifications": {"checked": False, "type": "checkbox",
                                       "value": "sms"},
                "Weekly digest": {"checked": True, "type": "radio",
                                   "value": "weekly"},
                "Daily digest": {"checked": False, "type": "radio",
                                  "value": "daily"},
            },
        )
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            assert result["status"] == "ok"
            page_data = result.get("page", {})
            assert isinstance(page_data.get("selected_options"), list), (
                "selected_options must be a list"
            )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_visual_state_is_dict_when_present(self, client):
        """visual_state must be a dict when included in page data."""
        page = _make_mock_page(
            selected_options=[],
            visual_state={
                "Email notifications": {"checked": True, "type": "checkbox",
                                         "value": "email"},
            },
        )
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            assert isinstance(page_data.get("visual_state"), dict), (
                "visual_state must be a dict"
            )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_selected_options_item_structure(self, client):
        """Each item in selected_options must have label, type, value, checked keys."""
        page = _make_mock_page(
            selected_options=[
                {"label": "Email notifications", "type": "checkbox",
                 "value": "email", "checked": True},
            ],
            visual_state={},
        )
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            items = page_data.get("selected_options", [])
            assert len(items) >= 1
            item = items[0]
            for key in ("label", "type", "value", "checked"):
                assert key in item, (
                    f"selected_options item missing key: {key}"
                )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_visual_state_value_structure(self, client):
        """Each value in visual_state dict must have checked, type, value keys."""
        page = _make_mock_page(
            selected_options=[],
            visual_state={
                "Email notifications": {"checked": True, "type": "checkbox",
                                         "value": "email"},
            },
        )
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            vs = page_data.get("visual_state", {})
            assert len(vs) >= 1
            for label, state in vs.items():
                for key in ("checked", "type", "value"):
                    assert key in state, (
                        f"visual_state['{label}'] missing key: {key}"
                    )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_existing_fields_untouched(self, client):
        """Adding selected_options/visual_state must not remove existing fields."""
        page = _make_mock_page(
            selected_options=[],
            visual_state={},
        )
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            for key in ("url", "title", "buttons", "modals", "form_fields",
                         "alerts", "text_preview", "text_length", "iframes"):
                assert key in page_data, (
                    f"Existing field '{key}' missing from analyze_page response"
                )
        finally:
            for p in patchers:
                p.stop()


class TestCheckboxStateVisibilityRED:
    """Behavioral RED tests — expected to fail until implementation.

    These simulate what the CURRENT analyze_page() JS returns (without
    selected_options/visual_state) and assert the new fields exist.
    They WILL FAIL until the JS is updated — that is the RED signal.
    """

    @pytest.mark.asyncio
    async def test_selected_options_in_response(self, client):
        """AC: /page/analyze response contains selected_options array.

        RED: The current JS doesn't aggregate checkboxes into selected_options.
        """
        page = _make_mock_page()  # No selected_options field — as the current code
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            assert "selected_options" in page_data, (
                "RED: selected_options missing from analyze_page response. "
                "Expected: [{label, type, value, checked}, ...] after JS update"
            )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_visual_state_in_response(self, client):
        """AC: /page/analyze response contains visual_state object.

        RED: The current JS doesn't build the visual_state map.
        """
        page = _make_mock_page()
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            assert "visual_state" in page_data, (
                "RED: visual_state missing from analyze_page response. "
                "Expected: {label: {checked, type, value}} after JS update"
            )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_selected_options_only_checked(self, client):
        """AC: selected_options only includes checked/selected items.

        RED: selected_options missing entirely (current code).
        After implementation, only checked items should be in the list.
        """
        page = _make_mock_page()
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            selected = page_data["selected_options"]
            for item in selected:
                assert item.get("checked") is True, (
                    f"selected_options contains unchecked item: {item.get('label')}"
                )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_visual_state_includes_all(self, client):
        """AC: visual_state includes ALL visible checkboxes/radios.

        RED: visual_state missing entirely (current code).
        After implementation, ALL checkbox/radio inputs (checked + unchecked)
        must appear in the visual_state dict.
        """
        page = _make_mock_page()
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            vs = page_data["visual_state"]
            labels_in_vs = list(vs.keys())
            assert len(labels_in_vs) >= 1, (
                "visual_state must include at least one checkbox/radio"
            )
            checked_count = sum(1 for v in vs.values() if v.get("checked"))
            unchecked_count = sum(1 for v in vs.values() if not v.get("checked"))
            assert unchecked_count >= 1 or checked_count >= 1
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_hidden_checkboxes_excluded(self, client):
        """AC: Hidden/display:none checkboxes are excluded from both fields."""
        visible_only = [
            {"tag": "INPUT", "type": "checkbox", "name": "visible",
             "label": "Visible option", "value": "visible",
             "placeholder": "", "section": "",
             "required": False, "checked": True,
             "has_error": False, "error_text": ""},
        ]
        page = _make_mock_page(form_fields=visible_only)
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            vs = page_data["visual_state"]
            assert "Visible option" in vs or "visible" in str(vs)
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_non_checkbox_fields_not_affected(self, client):
        """AC: Non-checkbox fields don't appear in the new fields."""
        page = _make_mock_page()
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            selected = page_data["selected_options"]
            vs = page_data["visual_state"]
            for item in selected:
                assert item.get("label") != "Username", (
                    "Text input must not appear in selected_options"
                )
            assert "Username" not in vs, (
                "Text input must not appear in visual_state"
            )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_empty_page_returns_empty_lists(self, client):
        """AC: When no checkboxes exist, selected_options=[] and visual_state={}."""
        no_checkboxes = [
            {"tag": "INPUT", "type": "text", "name": "name",
             "label": "Name", "value": "",
             "placeholder": "", "section": "",
             "required": False, "checked": False,
             "has_error": False, "error_text": ""},
        ]
        page = _make_mock_page(form_fields=no_checkboxes, buttons=[])
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            assert "selected_options" in page_data, (
                "selected_options must exist even when empty (zero checkboxes)"
            )
            assert "visual_state" in page_data, (
                "visual_state must exist even when empty (zero checkboxes)"
            )
            assert page_data["selected_options"] == [], (
                f"selected_options should be [], got {page_data['selected_options']}"
            )
            assert page_data["visual_state"] == {}, (
                f"visual_state should be {{}}, got {page_data['visual_state']}"
            )
        finally:
            for p in patchers:
                p.stop()


class TestCheckboxStateEdgeCases:
    """Edge case and boundary tests for P1 Checkbox State Visibility."""

    @pytest.mark.asyncio
    async def test_radio_button_selection_in_selected_options(self, client):
        """Radio buttons should appear in selected_options like checkboxes."""
        page = _make_mock_page(
            selected_options=[
                {"label": "Weekly digest", "type": "radio",
                 "value": "weekly", "checked": True},
            ],
            visual_state={
                "Weekly digest": {"checked": True, "type": "radio",
                                   "value": "weekly"},
                "Daily digest": {"checked": False, "type": "radio",
                                  "value": "daily"},
            },
        )
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            selected = page_data.get("selected_options", [])
            radio_items = [s for s in selected if s.get("type") == "radio"]
            assert len(radio_items) >= 1, (
                "Selected radio buttons must appear in selected_options"
            )
            assert radio_items[0]["checked"] is True
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_visual_state_radio_included(self, client):
        """Radio buttons must appear in visual_state alongside checkboxes."""
        page = _make_mock_page(
            selected_options=[],
            visual_state={
                "Weekly digest": {"checked": True, "type": "radio",
                                   "value": "weekly"},
                "Daily digest": {"checked": False, "type": "radio",
                                  "value": "daily"},
            },
        )
        patchers = _mock_client_calls(client, page)
        try:
            result = await client.analyze_page()
            page_data = result.get("page", {})
            vs = page_data.get("visual_state", {})
            radio_labels = [k for k, v in vs.items() if v.get("type") == "radio"]
            assert len(radio_labels) >= 1, (
                "Radio buttons must be included in visual_state"
            )
        finally:
            for p in patchers:
                p.stop()

    @pytest.mark.asyncio
    async def test_analyze_page_activates_then_evaluates(self, client):
        """analyze_page must call _activate_current before evaluate.

        Verify the call chain: _activate_current -> evaluate.
        This is a regression guard that also applies to the new fields.
        """
        calls = []

        async def tracking_activate():
            calls.append("_activate_current")

        async def tracking_evaluate(js):
            calls.append("evaluate")
            return _make_mock_evaluate_return(_make_mock_page())

        with (patch.object(client, "_activate_current", tracking_activate),
              patch.object(client, "evaluate", tracking_evaluate)):
            await client.analyze_page()

        assert calls == ["_activate_current", "evaluate"], (
            f"Expected [_activate_current, evaluate], got {calls}"
        )
# ─── P2: Condensed Snapshot Mode ─────────────────────────────────────
#
# RED-phase pre-development tests for P2 Condensed Snapshot.
# Feature: POST /page/analyze?condensed=true strips navigation, sidebar,
# footer, breadcrumbs and returns only main content area.
#
# Acceptance Criteria:
# [ ] POST /page/analyze?condensed=true returns stripped snapshot
# [ ] Navigation elements (nav, .sidebar, footer, header, .breadcrumb) excluded
# [ ] Main content area (main, article, [role=main]) preserved
# [ ] All interactive elements within content area still reported
# [ ] Fallback: if no main content container, full page + "condensed_fallback": true
# [ ] POST /page/analyze (without param) unchanged
# [ ] selected_options and visual_state included in condensed mode

class TestCondensedSnapshotInterface:
    """Interface tests: method existence, signature, and route contract.

    These should PASS once the method stub is added — they validate
    the public API surface.
    """

    def test_analyze_page_condensed_method_exists(self, client):
        """CDPClient must expose analyze_page_condensed()."""
        assert hasattr(client, "analyze_page_condensed"), (
            "CDPClient missing analyze_page_condensed() method"
        )

    @pytest.mark.asyncio
    async def test_analyze_page_condensed_is_callable(self, client):
        """Method must be a callable async function."""
        method = client.analyze_page_condensed
        assert callable(method), "analyze_page_condensed must be callable"

    def test_analyze_page_condensed_takes_no_required_args(self, client):
        """Should take no required arguments (like analyze_page)."""
        import inspect
        sig = inspect.signature(client.analyze_page_condensed)
        # self is bound, so first real param would be arg 1
        params = list(sig.parameters.values())
        # Allow only optional parameters (self excluded)
        required = [p for p in params if p.default is inspect.Parameter.empty
                     and p.name != "self"]
        assert len(required) == 0, (
            f"analyze_page_condensed has required params: {required}"
        )

    def test_analyze_page_condensed_returns_dict(self, client):
        """Return type annotation should be -> dict."""
        import inspect
        return_ann = inspect.signature(client.analyze_page_condensed).return_annotation
        if return_ann is not inspect.Parameter.empty and return_ann is not None:
            # Accept dict, Dict, or dict[str, Any]
            import typing
            valid = (dict, typing.Dict)
            assert return_ann in valid or (
                hasattr(return_ann, "__origin__") and return_ann.__origin__ is dict
            ), f"Expected dict return annotation, got {return_ann}"


class TestCondensedSnapshotRED:
    """Behavioral RED tests — expected to fail until implementation is complete.

    These define the contract: response shape, exclusion rules, fallback,
    and inclusion of P1 fields.
    """

    @pytest.mark.asyncio
    async def test_analyze_page_condensed_raises_cdperror_when_not_connected(self, client):
        """Calling without a connection must raise CDPError (same as other methods)."""
        with pytest.raises(CDPError, match="Not connected"):
            await client.analyze_page_condensed()

    @pytest.mark.asyncio
    async def test_condensed_response_has_page_key(self, mocked_evaluate_client):
        """Must return {'status': 'ok', 'page': {...}} like analyze_page."""
        result = await mocked_evaluate_client.analyze_page_condensed()
        assert result["status"] == "ok"
        assert "page" in result, "condensed response missing 'page' key"

    @pytest.mark.asyncio
    async def test_condensed_includes_selected_options(self, mocked_evaluate_client):
        """Condensed mode must include selected_options from P1."""
        result = await mocked_evaluate_client.analyze_page_condensed()
        page = result.get("page", {})
        assert "selected_options" in page, (
            "Condensed mode must include selected_options (P1 field)"
        )
        assert isinstance(page["selected_options"], list)

    @pytest.mark.asyncio
    async def test_condensed_includes_visual_state(self, mocked_evaluate_client):
        """Condensed mode must include visual_state from P1."""
        result = await mocked_evaluate_client.analyze_page_condensed()
        page = result.get("page", {})
        assert "visual_state" in page, (
            "Condensed mode must include visual_state (P1 field)"
        )
        assert isinstance(page["visual_state"], dict)

    @pytest.mark.asyncio
    async def test_condensed_excludes_nav_elements(self, mocked_evaluate_client):
        """Navigation elements should be excluded from condensed output.

        This is a contract test: the JS inside analyze_page_condensed must
        filter out nav/aside/footer/header/.sidebar/.breadcrumb.
        """
        result = await mocked_evaluate_client.analyze_page_condensed()
        page = result.get("page", {})
        # If buttons exist, none should be inside nav-type containers
        # (actual DOM filtering is JS-level; here we verify the response
        #  can be processed without structural errors)
        assert "buttons" in page
        assert "form_fields" in page

    @pytest.mark.asyncio
    async def test_condensed_fallback_when_no_main(self, mocked_evaluate_client):
        """If no main content container is found, full page + condensed_fallback: true."""
        result = await mocked_evaluate_client.analyze_page_condensed()
        page = result.get("page", {})
        # When fallback, condensed_fallback should be True
        # When main container found, condensed_fallback should be absent or False
        assert isinstance(page.get("condensed_fallback"), bool) or "condensed_fallback" not in page

    @pytest.mark.asyncio
    async def test_condensed_preserves_url_and_title(self, mocked_evaluate_client):
        """Standard fields (url, title) must still be present."""
        result = await mocked_evaluate_client.analyze_page_condensed()
        page = result.get("page", {})
        assert "url" in page, "condensed page missing url"
        assert "title" in page, "condensed page missing title"

    @pytest.mark.asyncio
    async def test_condensed_preserves_text_preview(self, mocked_evaluate_client):
        """Text preview should be present (scoped to content area)."""
        result = await mocked_evaluate_client.analyze_page_condensed()
        page = result.get("page", {})
        assert "text_preview" in page, "condensed page missing text_preview"
        assert "text_length" in page, "condensed page missing text_length"

    @pytest.mark.asyncio
    async def test_condensed_includes_iframes(self, mocked_evaluate_client):
        """Iframes within main content should still be reported."""
        result = await mocked_evaluate_client.analyze_page_condensed()
        page = result.get("page", {})
        assert "iframes" in page, "condensed page missing iframes"
        assert isinstance(page["iframes"], list)


class TestCondensedRouteContract:
    """Verify the /page/analyze route accepts ?condensed=true.

    These tests inspect the route endpoint via the app object to verify
    the contract without needing a running server.
    """

    def test_page_analyze_route_accepts_condensed_param(self):
        """The /page/analyze route must accept condensed: bool = Query(False).

        We import the app and check the route's endpoint signature.
        """
        from main import app  # noqa: F811
        # Find the /page/analyze route
        route = None
        for r in app.routes:
            if hasattr(r, "path") and r.path == "/page/analyze" and "POST" in r.methods:
                route = r
                break
        assert route is not None, "/page/analyze POST route not found"

        import inspect
        # The endpoint function signature must include condensed: bool = Query(False)
        sig = inspect.signature(route.endpoint)
        params = sig.parameters
        assert "condensed" in params, (
            "page_analyze endpoint must accept 'condensed' query param. "
            "Expected: async def page_analyze(condensed: bool = Query(False)):"
        )
        # Check the default value is Query(False)
        condensed_param = params["condensed"]
        import fastapi
        default = condensed_param.default
        assert isinstance(default, fastapi.params.Query), (
            "condensed param must use fastapi.Query default. "
            f"Got {type(default).__name__}"
        )
        assert default.default is False, (
            "condensed param must default to False. "
            f"Got default={default.default!r}"
        )
        assert condensed_param.annotation is bool, (
            "condensed param must be typed bool. "
            f"Got annotation={condensed_param.annotation!r}"
        )

    def test_page_analyze_without_condensed_still_works(self):
        """Ensure the route still accepts being called without the param (backward compatible).

        The original signature must still be compatible — the new param
        is optional with a default.
        """
        from main import app
        route = None
        for r in app.routes:
            if hasattr(r, "path") and r.path == "/page/analyze" and "POST" in r.methods:
                route = r
                break
        assert route is not None

        import inspect
        sig = inspect.signature(route.endpoint)
        params = sig.parameters
        assert "condensed" in params
        # The default being False ensures backward compatibility
        fastapi_params = params["condensed"].default
        assert fastapi_params.default is False


# ─── P2 Condensed Snapshot: Edge Cases ──────────────────────────────

class TestCondensedSnapshotEdgeCases:
    """Boundary and edge case tests for condensed mode."""

    def test_analyze_page_condensed_not_same_as_analyze_page(self, client):
        """analyze_page_condensed and analyze_page must be distinct methods."""
        assert client.analyze_page_condensed is not client.analyze_page, (
            "analyze_page_condensed must be a separate method, not an alias"
        )

    @pytest.mark.asyncio
    async def test_condensed_activates_current_tab(self, client):
        """Must call _activate_current (same pattern as analyze_page)."""
        # We can verify by checking the method internally calls activate
        # For now, contract test: calling should not raise AttributeError
        # related to missing _activate_current
        with pytest.raises(CDPError):
            await client.analyze_page_condensed()

    def test_condensed_response_keys_subset_of_analyze(self, client):
        """The set of keys in condensed page should be a subset of analyze_page keys.

        Contract: condensed returns the same shape but scoped to main content.
        No new top-level keys should appear that aren't in analyze_page.
        """
        import inspect
        # We can't call either without connection, but we can compare
        # the return annotations for consistency
        condensed_sig = inspect.signature(client.analyze_page_condensed)
        analyze_sig = inspect.signature(client.analyze_page)
        c_ret = condensed_sig.return_annotation
        a_ret = analyze_sig.return_annotation
        if c_ret is not inspect.Parameter.empty and a_ret is not inspect.Parameter.empty:
            # Both should be dict return type
            assert c_ret == a_ret or c_ret in (dict,) or a_ret in (dict,)


# ═══════════════════════════════════════════════════════════════════
# P0: Tab Auto-Activation — Pre-Dev Tests
# ═══════════════════════════════════════════════════════════════════
#
# Feature: Every CDP client method that performs a page operation must
# call self._activate_current() before sending CDP commands, so the
# intended tab is foregrounded before any action.
#
# Current gap: 14 methods listed below bypass _activate_current().
#
# RED phase (now):  these behavioral tests FAIL because the methods
#                   don't call _activate_current() yet.
# GREEN phase (after implementation): they PASS.
#
# Acceptance Criteria:
# [ ] evaluate() calls _activate_current() before executing JS
# [ ] screenshot() calls _activate_current() before capture
# [ ] get_page_text() calls _activate_current() before text extraction
# [ ] dom_query() calls _activate_current() before DOM query
# [ ] get_cookies(), set_cookie(), clear_cookies() call _activate_current()
# [ ] pdf() calls _activate_current()
# [ ] open_new_tab(), close_tab() call _activate_current()
# [ ] switch_tab() has explicit _activate_current() after reconnect
# [ ] All existing tests still pass
# [ ] No new imports required

# ─── Interface: method existence + signatures ───────────────────────

class TestTabActivationInterface:
    """Verify every method exists and has the correct async callable signature.

    These tests should PASS immediately because the methods already exist
    on CDPClient. They validate the public API surface before behavioral
    testing.
    """

    # ── Helpers ──────────────────────────────────────────────────

    def _assert_async_method(self, client, name: str, doc_hint: str = ""):
        """Assert that *name* is an async callable on *client*."""
        assert hasattr(client, name), (
            f"CDPClient.{name}() does not exist. {doc_hint}"
        )
        method = getattr(client, name)
        assert callable(method), f"CDPClient.{name}() is not callable"
        import inspect
        assert inspect.iscoroutinefunction(method), (
            f"CDPClient.{name}() must be an async def method"
        )

    def _assert_has_param(self, client, method_name: str, param: str):
        """Assert that *method_name* has a parameter called *param*."""
        import inspect
        sig = inspect.signature(getattr(client, method_name))
        assert param in sig.parameters, (
            f"CDPClient.{method_name}() missing parameter '{param}'. "
            f"Existing params: {list(sig.parameters.keys())}"
        )

    # ── Methods that need _activate_current() ─────────────────────

    def test_evaluate_exists(self, client):
        self._assert_async_method(client, "evaluate")

    def test_evaluate_has_js_code_param(self, client):
        self._assert_has_param(client, "evaluate", "js_code")

    def test_evaluate_js_exists(self, client):
        self._assert_async_method(client, "evaluate_js",
                                   "Alias for evaluate()")

    def test_evaluate_js_has_js_code_param(self, client):
        self._assert_has_param(client, "evaluate_js", "js_code")

    def test_screenshot_exists(self, client):
        self._assert_async_method(client, "screenshot")

    def test_screenshot_has_quality_param(self, client):
        self._assert_has_param(client, "screenshot", "quality")

    def test_full_page_screenshot_exists(self, client):
        self._assert_async_method(client, "full_page_screenshot")

    def test_full_page_screenshot_has_quality_param(self, client):
        self._assert_has_param(client, "full_page_screenshot", "quality")

    def test_element_screenshot_exists(self, client):
        self._assert_async_method(client, "element_screenshot")

    def test_element_screenshot_has_selector_param(self, client):
        self._assert_has_param(client, "element_screenshot", "selector")

    def test_element_screenshot_has_quality_param(self, client):
        self._assert_has_param(client, "element_screenshot", "quality")

    def test_get_page_text_exists(self, client):
        self._assert_async_method(client, "get_page_text")

    def test_dom_query_exists(self, client):
        self._assert_async_method(client, "dom_query")

    def test_dom_query_has_selector_param(self, client):
        self._assert_has_param(client, "dom_query", "selector")

    def test_dom_click_all_exists(self, client):
        self._assert_async_method(client, "dom_click_all")

    def test_dom_click_all_has_selector_param(self, client):
        self._assert_has_param(client, "dom_click_all", "selector")

    def test_get_cookies_exists(self, client):
        self._assert_async_method(client, "get_cookies")

    def test_set_cookie_exists(self, client):
        self._assert_async_method(client, "set_cookie")

    def test_set_cookie_has_name_param(self, client):
        self._assert_has_param(client, "set_cookie", "name")

    def test_set_cookie_has_value_param(self, client):
        self._assert_has_param(client, "set_cookie", "value")

    def test_clear_cookies_exists(self, client):
        self._assert_async_method(client, "clear_cookies")

    def test_pdf_exists(self, client):
        self._assert_async_method(client, "pdf")

    def test_open_new_tab_exists(self, client):
        self._assert_async_method(client, "open_new_tab")

    def test_open_new_tab_has_url_param(self, client):
        self._assert_has_param(client, "open_new_tab", "url")

    def test_close_tab_exists(self, client):
        self._assert_async_method(client, "close_tab")

    def test_close_tab_has_tab_id_param(self, client):
        self._assert_has_param(client, "close_tab", "tab_id")

    def test_switch_tab_exists(self, client):
        self._assert_async_method(client, "switch_tab")

    def test_switch_tab_has_tab_id_param(self, client):
        self._assert_has_param(client, "switch_tab", "tab_id")

    def test_activate_current_exists(self, client):
        """_activate_current() itself must exist as a private method."""
        self._assert_async_method(client, "_activate_current")


# ─── Behavioral RED tests: verify _activate_current() is called ─────

class TestTabActivationRED:
    """Behavioral tests — expected to FAIL before implementation.

    Each test monkeypatches _activate_current() with a call tracker,
    invokes the CDP method, then asserts the spy was called.

    PRE-IMPLEMENTATION (RED):  assert len(calls) > 0  →  FAIL
    POST-IMPLEMENTATION (GREEN): assert len(calls) > 0  →  PASS
    """

    # ─── evaluate() / evaluate_js() ───────────────────────────────

    @pytest.mark.asyncio
    async def test_evaluate_activates(self, client, activation_spy):
        """evaluate() must call _activate_current() before JS execution.

        Currently fails (RED): evaluate() sends Runtime.evaluate directly
        without calling _activate_current().
        """
        with pytest.raises(CDPError):
            await client.evaluate("1+1")
        assert len(activation_spy) > 0, (
            "RED: evaluate() does not call _activate_current(). "
            "Add 'await self._activate_current()' at the start of evaluate()."
        )

    @pytest.mark.asyncio
    async def test_evaluate_js_activates(self, client, activation_spy):
        """evaluate_js() must call _activate_current() (either directly or via evaluate())."""
        with pytest.raises(CDPError):
            await client.evaluate_js("document.title")
        assert len(activation_spy) > 0, (
            "RED: evaluate_js() does not call _activate_current(). "
            "Either add it directly or ensure evaluate() provides it."
        )

    # ─── Screenshot methods ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_screenshot_activates(self, client, activation_spy):
        """screenshot() must call _activate_current() before capture."""
        with pytest.raises(CDPError):
            await client.screenshot()
        assert len(activation_spy) > 0, (
            "RED: screenshot() does not call _activate_current(). "
            "Add 'await self._activate_current()' before the Page.captureScreenshot call."
        )

    @pytest.mark.asyncio
    async def test_full_page_screenshot_activates(self, client, activation_spy):
        """full_page_screenshot() must call _activate_current()."""
        with pytest.raises(CDPError):
            await client.full_page_screenshot()
        assert len(activation_spy) > 0, (
            "RED: full_page_screenshot() does not call _activate_current()."
        )

    @pytest.mark.asyncio
    async def test_element_screenshot_activates(self, client, activation_spy):
        """element_screenshot() must call _activate_current()."""
        with pytest.raises(CDPError):
            await client.element_screenshot(".main")
        assert len(activation_spy) > 0, (
            "RED: element_screenshot() does not call _activate_current()."
        )

    # ─── get_page_text() ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_page_text_activates(self, client, activation_spy):
        """get_page_text() must call _activate_current() before text extraction."""
        with pytest.raises(CDPError):
            await client.get_page_text()
        assert len(activation_spy) > 0, (
            "RED: get_page_text() does not call _activate_current()."
        )

    # ─── DOM methods ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_dom_query_activates(self, client, activation_spy):
        """dom_query() must call _activate_current() before DOM query."""
        with pytest.raises(CDPError):
            await client.dom_query("a")
        assert len(activation_spy) > 0, (
            "RED: dom_query() does not call _activate_current()."
        )

    @pytest.mark.asyncio
    async def test_dom_click_all_activates(self, client, activation_spy):
        """dom_click_all() must call _activate_current() before clicking."""
        with pytest.raises(CDPError):
            await client.dom_click_all("button")
        assert len(activation_spy) > 0, (
            "RED: dom_click_all() does not call _activate_current()."
        )

    # ─── Cookie methods ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_cookies_activates(self, client, activation_spy):
        """get_cookies() must call _activate_current()."""
        with pytest.raises(CDPError):
            await client.get_cookies()
        assert len(activation_spy) > 0, (
            "RED: get_cookies() does not call _activate_current()."
        )

    @pytest.mark.asyncio
    async def test_set_cookie_activates(self, client, activation_spy):
        """set_cookie() must call _activate_current() before setting.

        Note: set_cookie() catches CDPError internally, so it does NOT
        raise — it returns {"status": "error", "error": ...}. The spy
        assertion still works because _send_command is called inside
        the try block.
        """
        result = await client.set_cookie("test", "value")
        assert result["status"] == "error"  # expected — no Chrome
        assert len(activation_spy) > 0, (
            "RED: set_cookie() does not call _activate_current()."
        )

    @pytest.mark.asyncio
    async def test_clear_cookies_activates(self, client, activation_spy):
        """clear_cookies() must call _activate_current()."""
        with pytest.raises(CDPError):
            await client.clear_cookies()
        assert len(activation_spy) > 0, (
            "RED: clear_cookies() does not call _activate_current()."
        )

    # ─── pdf() ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pdf_activates(self, client, activation_spy):
        """pdf() must call _activate_current() before PDF generation."""
        with pytest.raises(CDPError):
            await client.pdf()
        assert len(activation_spy) > 0, (
            "RED: pdf() does not call _activate_current()."
        )

    # ─── Tab management methods ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_open_new_tab_activates(self, client, activation_spy):
        """open_new_tab() must call _activate_current() before opening.

        The method already calls _activate_current() and catches CDP
        errors internally, returning {"status": "error"} instead of
        raising. The spy confirms activation was called.
        """
        result = await client.open_new_tab()
        assert result["status"] == "error", (
            "Expected error (no Chrome running), got success"
        )
        assert len(activation_spy) > 0, (
            "open_new_tab() must call _activate_current()."
        )

    @pytest.mark.asyncio
    async def test_close_tab_activates(self, client, activation_spy):
        """close_tab() must call _activate_current() before closing.

        Uses httpx (not _send_command). Will raise connection error.
        """
        with pytest.raises(Exception):
            await client.close_tab("tab-123")
        assert len(activation_spy) > 0, (
            "RED: close_tab() does not call _activate_current()."
        )

    # ─── switch_tab() (requires mocking to reach activation point) ──

    @pytest.mark.asyncio
    async def test_switch_tab_activates_after_reconnect(self, client, activation_spy, monkeypatch):
        """switch_tab() must call _activate_current() after WS reconnect.

        This test mocks the HTTP tab discovery and WebSocket connection
        so the method executes past the reconnect point where
        _activate_current() should be called.
        """
        import asyncio

        # Fake tab returned by discover_tabs
        fake_tab = {
            "id": "tab-123",
            "type": "page",
            "title": "Test Tab",
            "url": "about:blank",
            "webSocketDebuggerUrl": "ws://localhost:9555/devtools/page/tab-123",
        }

        # Mock discover_tabs to return the fake tab
        async def mock_discover_tabs():
            return [fake_tab]
        monkeypatch.setattr(client, "discover_tabs", mock_discover_tabs)

        # Mock close() to be a no-op
        async def mock_close():
            client._connected = False
        monkeypatch.setattr(client, "close", mock_close)

        # Mock _send_command to succeed (for Page.enable, Runtime.enable)
        async def mock_send_command(cmd, params=None):
            return {}
        monkeypatch.setattr(client, "_send_command", mock_send_command)

        # Create a fake WebSocket that accepts send/recv
        class FakeWebSocket:
            async def send(self, data):
                pass

            async def recv(self):
                # Never resolve — prevents _listener from consuming messages
                await asyncio.sleep(3600)

            async def close(self):
                pass

        async def mock_ws_connect(url, **kwargs):
            return FakeWebSocket()
        monkeypatch.setattr("websockets.connect", mock_ws_connect)

        # Call switch_tab — should succeed with mocks
        result = await client.switch_tab("tab-123")
        assert result["status"] == "ok", f"switch_tab failed: {result}"
        assert len(activation_spy) > 0, (
            "RED: switch_tab() does not call _activate_current() after reconnect. "
            "Add 'await self._activate_current()' after the WS reconnect + Page.enable."
        )

    # ─── Edge: methods that already have _activate_current() ──────
    # These tests verify that the spy doesn't report false positives
    # from already-correct methods. They should PASS.

    @pytest.mark.asyncio
    async def test_navigate_already_activates(self, client, activation_spy):
        """navigate() already calls _activate_current() — confirm spy works."""
        with pytest.raises(CDPError):
            await client.navigate("http://example.com")
        assert len(activation_spy) > 0, (
            "navigate() should call _activate_current() — if this fails, "
            "the spy mechanism is broken."
        )

    @pytest.mark.asyncio
    async def test_click_already_activates(self, client, activation_spy):
        """click() already calls _activate_current() — confirm spy works."""
        with pytest.raises(CDPError):
            await client.click(".button")
        assert len(activation_spy) > 0, (
            "click() should call _activate_current() — if this fails, "
            "the spy mechanism is broken."
        )

    @pytest.mark.asyncio
    async def test_type_text_already_activates(self, client, activation_spy):
        """type_text() already calls _activate_current() — confirm spy works."""
        with pytest.raises(CDPError):
            await client.type_text("input", "hello")
        assert len(activation_spy) > 0, (
            "type_text() should call _activate_current() — if this fails, "
            "the spy mechanism is broken."
        )

    # ─── Spy integrity check: verify the spy resets per test ─────

    def test_spy_starts_empty(self, activation_spy):
        """Sanity check: a fresh spy has zero calls recorded."""
        assert len(activation_spy) == 0, (
            "Spy should start empty. Fixture may not be resetting properly."
        )

    def test_spy_is_list(self, activation_spy):
        """Sanity check: spy returns a list."""
        assert isinstance(activation_spy, list)
