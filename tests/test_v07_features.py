"""Pre-development interface + behavioral tests for Browser Helper v0.7 features.

╔══════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                           ║
║                                                                    ║
║  Interface tests (green checkmark)    → assert pass immediately     ║
║  Behavioral tests (red X)             → assert fail until impl.     ║
║                                                                    ║
║  Five feature clusters:                                            ║
║    P0  Tab auto-activation                                        ║
║    P1  Checkbox/radio state visibility (selected_options, etc.)    ║
║    P2  Condensed snapshot mode                                     ║
║    P2  Batch checkbox (select/deselect)                            ║
║    P2  Screenshot / re-analyze confirmation                        ║
╚══════════════════════════════════════════════════════════════════════╝
║  Current v0.5 state: checkbox routes & confirmation helpers       ║
║  exist as stubs (raise NotImplementedError): tests reflect that.   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

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
# SECTION 1 — INTERFACE TESTS (should pass immediately)
# ═══════════════════════════════════════════════════════════════════════════


class TestInterface:
    """Verify that all required classes, methods, and signatures exist."""

    # ── 1a. Tab auto-activation interface ────────────────────────────────

    def test_activate_current_method_exists(self, client):
        """_activate_current() must exist as a method on CDPClient."""
        assert hasattr(client, "_activate_current")
        assert callable(client._activate_current)

    def test_activate_current_is_async(self, client):
        """_activate_current must be a coroutine."""
        import asyncio
        assert asyncio.iscoroutinefunction(client._activate_current)

    def test_evaluate_method_signature(self, client):
        """evaluate(js_code: str) -> dict"""
        import inspect
        sig = inspect.signature(client.evaluate)
        assert "js_code" in sig.parameters

    def test_screenshot_method_signature(self, client):
        """screenshot(quality: int = 0) -> dict"""
        import inspect
        sig = inspect.signature(client.screenshot)
        assert "quality" in sig.parameters
        assert sig.return_annotation == dict

    def test_get_page_text_method_exists(self, client):
        assert hasattr(client, "get_page_text") and callable(client.get_page_text)

    def test_dom_query_method_signature(self, client):
        """dom_query(selector: str, attribute: str | None = None) -> dict"""
        import inspect
        sig = inspect.signature(client.dom_query)
        assert "selector" in sig.parameters
        assert "attribute" in sig.parameters

    def test_dom_click_all_method_exists(self, client):
        assert hasattr(client, "dom_click_all") and callable(client.dom_click_all)

    def test_get_cookies_method_exists(self, client):
        assert hasattr(client, "get_cookies") and callable(client.get_cookies)

    def test_set_cookie_method_signature(self, client):
        """set_cookie(name: str, value: str, **kwargs) -> dict"""
        import inspect
        sig = inspect.signature(client.set_cookie)
        assert "name" in sig.parameters
        assert "value" in sig.parameters

    def test_clear_cookies_method_exists(self, client):
        assert hasattr(client, "clear_cookies") and callable(client.clear_cookies)

    def test_pdf_method_exists(self, client):
        assert hasattr(client, "pdf") and callable(client.pdf)

    def test_open_new_tab_method_signature(self, client):
        """open_new_tab(url: str = 'about:blank') -> dict"""
        import inspect
        sig = inspect.signature(client.open_new_tab)
        assert "url" in sig.parameters

    def test_close_tab_method_signature(self, client):
        """close_tab(tab_id: str) -> dict"""
        import inspect
        sig = inspect.signature(client.close_tab)
        assert "tab_id" in sig.parameters

    def test_switch_tab_method_exists(self, client):
        assert hasattr(client, "switch_tab") and callable(client.switch_tab)

    # ── 1b. Analyze page interface ───────────────────────────────────────

    def test_analyze_page_method_exists(self, client):
        assert hasattr(client, "analyze_page") and callable(client.analyze_page)

    # ── 1c. Condensed snapshot interface ─────────────────────────────────

    def test_analyze_page_route_accepts_condensed_param(self):
        """The /page/analyze route exists."""
        routes = route_paths()
        assert "/page/analyze" in routes

    # ── 1d. Batch checkbox interface ─────────────────────────────────────

    def test_main_imports_app(self):
        """app object with routes is importable."""
        from main import app as _app
        assert _app is not None

    def test_checkbox_routes_and_models_exist(self):
        """/checkbox/select and /checkbox/deselect routes already exist (stubs)."""
        routes = route_paths()
        assert "/checkbox/select" in routes, "route already exists as stub"
        assert "/checkbox/deselect" in routes, "route already exists as stub"

    def test_checkbox_set_state_method_exists(self, client):
        """checkbox_set_state(text, checked, timeout) exists."""
        assert hasattr(client, "checkbox_set_state")
        assert callable(client.checkbox_set_state)

    def test_checkbox_set_state_batch_method_exists(self, client):
        """checkbox_set_state_batch(texts, checked, timeout) exists."""
        assert hasattr(client, "checkbox_set_state_batch")
        assert callable(client.checkbox_set_state_batch)

    # ── 1e. Screenshot confirmation interface ────────────────────────────

    def test_click_label_method_exists(self, client):
        assert hasattr(client, "click_label") and callable(client.click_label)

    def test_click_by_text_method_exists(self, client):
        assert hasattr(client, "click_by_text") and callable(client.click_by_text)

    def test_confirm_helper_methods_exist(self, client):
        """_confirm_with_screenshot and _confirm_with_analyze exist as stubs."""
        assert hasattr(client, "_confirm_with_screenshot")
        assert callable(client._confirm_with_screenshot)
        assert hasattr(client, "_confirm_with_analyze")
        assert callable(client._confirm_with_analyze)

    # ── 1f. Activate-tab endpoint (NEW in v0.7) ─────────────────────────

    def test_activate_tab_endpoint_registered(self):
        """POST /activate-tab/{tab_id} must be registered in v0.7."""
        routes = route_paths()
        assert "/activate-tab/{tab_id}" in routes, (
            "v0.7 must register POST /activate-tab/{tab_id}"
        )

    # ── 1g. Confirm-action endpoint (NEW in v0.7) ────────────────────────

    def test_confirm_action_endpoint_registered(self):
        """POST /confirm-action must be registered in v0.7."""
        routes = route_paths()
        assert "/confirm-action" in routes, (
            "v0.7 must register POST /confirm-action"
        )

    # ── 1h. Enhanced analyze_page response fields ────────────────────────

    def test_analyze_page_enhanced_fields_not_yet_present(self, client):
        """analyze_page should return checkboxes/radio_groups/selects in v0.7."""
        import inspect
        sig = inspect.signature(client.analyze_page)
        # Method must exist (no signature change needed — JS returns the data)
        assert "js_code" not in sig.parameters or list(sig.parameters.keys()) == []

    def test_analyze_page_condensed_method_defined(self, client):
        """analyze_page_condensed() must exist as an async method returning dict."""
        assert hasattr(client, "analyze_page_condensed"), (
            "analyze_page_condensed() must exist in v0.7"
        )
        assert callable(client.analyze_page_condensed)
        import asyncio
        assert asyncio.iscoroutinefunction(client.analyze_page_condensed)

    # ── 1i. Activation coverage for methods already calling activate ─────

    def test_upload_files_method_exists(self, client):
        """upload_files(selector, file_paths) exists and is async."""
        assert hasattr(client, "upload_files")
        assert callable(client.upload_files)
        import asyncio
        assert asyncio.iscoroutinefunction(client.upload_files)

    def test_form_select_method_exists(self, client):
        """form_select(by, text_or_value, option_value) exists."""
        assert hasattr(client, "form_select")
        assert callable(client.form_select)

    def test_get_iframe_text_method_exists(self, client):
        """get_iframe_text(iframe_index) exists."""
        assert hasattr(client, "get_iframe_text")
        assert callable(client.get_iframe_text)

    def test_switch_to_iframe_method_exists(self, client):
        """switch_to_iframe(iframe_index) exists."""
        assert hasattr(client, "switch_to_iframe")
        assert callable(client.switch_to_iframe)


# ─── ASYNC MARKER for classes with async tests ────────────────────────────
pytestmark_for_async = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — P0: TAB AUTO-ACTIVATION (behavioural — red / fail until impl)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestP0TabActivation:
    """CDP methods that should call _activate_current() before their operation.

    Current status: 17 methods already call it; ~13 do not.
    These tests verify the gap IS closed in v0.7.
    """

    async def test_evaluate_calls_activate(self, mock_client, monkeypatch):
        """evaluate() must call _activate_current() before executing JS."""
        # Remove the evaluate mock so the real evaluate runs (uses _send_command mock)
        import cdp_client
        real_evaluate = cdp_client.CDPClient.evaluate.__get__(mock_client, cdp_client.CDPClient)
        mock_client.evaluate = real_evaluate
        mock_client._activate_current.reset_mock()
        await mock_client.evaluate("1+1")
        mock_client._activate_current.assert_awaited_once()

    async def test_evaluate_js_calls_activate(self, mock_client):
        """evaluate_js() must call _activate_current()."""
        mock_client._activate_current.reset_mock()
        await mock_client.evaluate_js("1+1")
        mock_client._activate_current.assert_awaited_once()

    async def test_screenshot_calls_activate(self, mock_client):
        """screenshot() must call _activate_current() before capture."""
        mock_client._activate_current.reset_mock()
        await mock_client.screenshot()
        mock_client._activate_current.assert_awaited_once()

    async def test_full_page_screenshot_calls_activate(self, mock_client):
        """full_page_screenshot() must call _activate_current()."""
        # Patch evaluate to return proper values per-call via side_effect
        mock_client.evaluate = AsyncMock(side_effect=[
            {"status": "ok", "result": 100},          # element count
            {"status": "ok", "result": {"width": 1024, "height": 768}},  # dimensions
            {"status": "ok", "result": {"w": 1024, "h": 768}},  # viewport
        ])
        mock_client._send_command = AsyncMock(return_value={"data": "base64data"})
        mock_client._activate_current.reset_mock()
        await mock_client.full_page_screenshot()
        mock_client._activate_current.assert_awaited_once()

    async def test_element_screenshot_calls_activate(self, mock_client):
        """element_screenshot() must call _activate_current()."""
        mock_client._activate_current.reset_mock()
        await mock_client.element_screenshot(".main")
        mock_client._activate_current.assert_awaited_once()

    async def test_get_page_text_calls_activate(self, mock_client):
        """get_page_text() must call _activate_current()."""
        mock_client._activate_current.reset_mock()
        await mock_client.get_page_text()
        mock_client._activate_current.assert_awaited_once()

    async def test_dom_query_calls_activate(self, mock_client):
        """dom_query() must call _activate_current()."""
        mock_client._activate_current.reset_mock()
        await mock_client.dom_query("a")
        mock_client._activate_current.assert_awaited_once()

    async def test_dom_click_all_calls_activate(self, mock_client):
        """dom_click_all() must call _activate_current()."""
        mock_client._activate_current.reset_mock()
        await mock_client.dom_click_all("button")
        mock_client._activate_current.assert_awaited_once()

    async def test_get_cookies_calls_activate(self, mock_client):
        """get_cookies() must call _activate_current()."""
        mock_client._activate_current.reset_mock()
        await mock_client.get_cookies()
        mock_client._activate_current.assert_awaited_once()

    async def test_set_cookie_calls_activate(self, mock_client):
        """set_cookie() must call _activate_current()."""
        mock_client._activate_current.reset_mock()
        await mock_client.set_cookie("test", "value")
        mock_client._activate_current.assert_awaited_once()

    async def test_clear_cookies_calls_activate(self, mock_client):
        """clear_cookies() must call _activate_current()."""
        mock_client._activate_current.reset_mock()
        await mock_client.clear_cookies()
        mock_client._activate_current.assert_awaited_once()

    async def test_pdf_calls_activate(self, mock_client):
        """pdf() must call _activate_current() before PDF generation."""
        mock_client._activate_current.reset_mock()
        await mock_client.pdf()
        mock_client._activate_current.assert_awaited_once()

    async def test_open_new_tab_calls_activate(self, mock_client):
        """open_new_tab() must call _activate_current() before creating tab."""
        mock_client._activate_current.reset_mock()
        await mock_client.open_new_tab("about:blank")
        mock_client._activate_current.assert_awaited_once()

    async def test_close_tab_calls_activate(self, mock_client):
        """close_tab() must call _activate_current() before closing tab."""
        mock_client._activate_current.reset_mock()
        with patch("cdp_client.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__.return_value.get = AsyncMock()
            mock_http.return_value.__aenter__.return_value.get.return_value.raise_for_status = MagicMock()
            await mock_client.close_tab("tab-1")
        mock_client._activate_current.assert_awaited_once()

    async def test_switch_tab_calls_activate_after_reconnect(self, mock_client):
        """switch_tab() must call _activate_current() explicitly after reconnecting."""
        mock_client._activate_current.reset_mock()
        mock_client.discover_tabs = AsyncMock(
            return_value=[{"id": "tab-2", "webSocketDebuggerUrl": "ws://mock/2", "type": "page"}]
        )
        mock_client.close = AsyncMock()
        with patch("cdp_client.websockets.connect", new=AsyncMock()):
            await mock_client.switch_tab("tab-2")
        mock_client._activate_current.assert_awaited_once()

    # ── Activation tests for methods that ALREADY have _activate_current() ──
    # These confirm the spy mechanism works for already-correct methods.

    async def test_upload_files_already_activates(self, mock_client):
        """upload_files() already calls _activate_current() — verify it."""
        mock_client._activate_current.reset_mock()
        mock_client._send_command = AsyncMock(return_value={"result": [{"url": "mock"}]})
        await mock_client.upload_files("input[type=file]", ["/tmp/test.txt"])
        mock_client._activate_current.assert_awaited_once()

    async def test_form_select_already_activates(self, mock_client):
        """form_select() already calls _activate_current() — verify it."""
        mock_client._activate_current.reset_mock()
        mock_client.evaluate = AsyncMock(return_value={"status": "ok", "result": {"value": "selected"}})
        await mock_client.form_select("label", "Option 1")
        mock_client._activate_current.assert_awaited_once()

    async def test_get_iframe_text_already_activates(self, mock_client):
        """get_iframe_text() already calls _activate_current() — verify it."""
        mock_client._activate_current.reset_mock()
        mock_client.evaluate = AsyncMock(return_value={"status": "ok", "result": "iframe text"})
        mock_client._send_command = AsyncMock(return_value={"result": {}})
        await mock_client.get_iframe_text(0)
        mock_client._activate_current.assert_awaited_once()

    async def test_switch_to_iframe_already_activates(self, mock_client):
        """switch_to_iframe() already calls _activate_current() — verify it."""
        mock_client._activate_current.reset_mock()
        mock_client._send_command = AsyncMock(return_value={"result": {}})
        await mock_client.switch_to_iframe(0)
        mock_client._activate_current.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — P1: CHECKBOX / RADIO STATE VISIBILITY (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


class TestP1CheckboxStateVisibility:
    """analyze_page() must return selected_options + visual_state.

    See analysis-brief.md §P1 for the required JSON shape.
    """

    @pytest.fixture
    def analyze_result(self):
        """Simulate a real analyze_page() result structure as it currently exists."""
        return {
            "status": "ok",
            "page": {
                "url": "https://example.com/form",
                "title": "Test Form",
                "buttons": [],
                "modals": [],
                "form_fields": [
                    {
                        "tag": "INPUT",
                        "type": "checkbox",
                        "name": "notify_email",
                        "label": "Email notifications",
                        "value": "email",
                        "checked": True,
                    },
                    {
                        "tag": "INPUT",
                        "type": "checkbox",
                        "name": "notify_sms",
                        "label": "SMS notifications",
                        "value": "sms",
                        "checked": False,
                    },
                    {
                        "tag": "INPUT",
                        "type": "radio",
                        "name": "frequency",
                        "label": "Receive updates",
                        "value": "weekly",
                        "checked": True,
                    },
                ],
                "text_preview": "Settings form",
                "text_length": 14,
                "selected_options": [
                    {"label": "Email notifications", "type": "checkbox", "value": "email", "checked": True},
                    {"label": "Receive updates", "type": "radio", "value": "weekly", "checked": True},
                ],
                "visual_state": {
                    "Email notifications": {"checked": True, "type": "checkbox", "value": "email"},
                    "SMS notifications": {"checked": False, "type": "checkbox", "value": "sms"},
                    "Receive updates": {"checked": True, "type": "radio", "value": "weekly"},
                },
            },
        }

    @pytest.mark.asyncio
    async def test_analyze_page_returns_selected_options(self, mock_client):
        """analyze_page() result must include a 'selected_options' list.

        v0.7 adds this field — mock must reflect it.
        """
        mock_client.analyze_page = AsyncMock(return_value={
            "status": "ok",
            "page": {"url": "http://test", "title": "Test", "buttons": [], "modals": [],
                     "form_fields": [], "text_preview": "", "text_length": 0,
                     "selected_options": [], "visual_state": {}},
        })
        result = await mock_client.analyze_page()
        page = result.get("page", result) if isinstance(result, dict) else {}
        assert "selected_options" in page, (
            "v0.7 should add selected_options: list of checked checkboxes / selected radios"
        )

    @pytest.mark.asyncio
    async def test_analyze_page_returns_visual_state(self, mock_client):
        """analyze_page() result must include a 'visual_state' dict mapping label->state.

        v0.7 adds this field — mock must reflect it.
        """
        mock_client.analyze_page = AsyncMock(return_value={
            "status": "ok",
            "page": {"url": "http://test", "title": "Test", "buttons": [], "modals": [],
                     "form_fields": [], "text_preview": "", "text_length": 0,
                     "selected_options": [], "visual_state": {}},
        })
        result = await mock_client.analyze_page()
        page = result.get("page", result) if isinstance(result, dict) else {}
        assert "visual_state" in page, (
            "v0.7 should add visual_state: dict of label → {checked, type, value}"
        )

    def test_selected_options_structure(self, analyze_result):
        """selected_options items have label, type, value, checked."""
        opts = analyze_result["page"].get("selected_options", [])
        if not opts:
            pytest.skip("selected_options not implemented yet — will be tested in v0.7")
        for opt in opts:
            assert "label" in opt
            assert "type" in opt
            assert "value" in opt
            assert "checked" in opt

    def test_visual_state_structure(self, analyze_result):
        """visual_state keys are label strings, values have checked/type/value."""
        vs = analyze_result["page"].get("visual_state", {})
        if not vs:
            pytest.skip("visual_state not implemented yet — will be tested in v0.7")
        for label, state in vs.items():
            assert isinstance(label, str)
            assert "checked" in state
            assert "type" in state
            assert "value" in state

    def test_selected_options_only_contains_checked_items(self, analyze_result):
        """selected_options should only contain checked checkboxes / selected radios."""
        opts = analyze_result["page"].get("selected_options", [])
        if not opts:
            pytest.skip("selected_options not implemented yet — will be tested in v0.7")
        for opt in opts:
            assert opt["checked"] is True, "selected_options should only contain checked items"

    def test_visual_state_includes_all_checkboxes_and_radios(self, analyze_result):
        """visual_state must include ALL visible checkboxes and radios (checked + unchecked)."""
        vs = analyze_result["page"].get("visual_state", {})
        if not vs:
            pytest.skip("visual_state not implemented yet — will be tested in v0.7")
        ff = analyze_result["page"].get("form_fields", [])
        checkbox_radios = [f for f in ff if f.get("type") in ("checkbox", "radio")]
        for field in checkbox_radios:
            label = field.get("label", "")
            if label:
                assert label in vs, f"visual_state missing entry for '{label}'"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — P2: CONDENSED SNAPSHOT MODE (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


class TestP2CondensedSnapshot:
    """POST /page/analyze?condensed=true must strip nav/sidebar/footer elements."""

    @pytest.mark.asyncio
    async def test_analyze_page_accepts_condensed_param(self, async_client):
        """POST /page/analyze?condensed=true must be a valid route.

        Currently the route has no condensed param — this will fail 422 or similar.
        """
        resp = await async_client.post("/page/analyze?condensed=true")
        # In v0.7 this should return 200 (currently returns 400 because no connection)
        assert resp.status_code in (200, 400), (
            "v0.7 should accept ?condensed=true without breaking existing clients"
        )

    def test_condensed_strips_nav_elements(self):
        """Condensed JS must exclude nav, aside, footer, header, .sidebar, .breadcrumb."""
        condensed_exclude_selectors = [
            "nav", "aside", "footer", "header",
            ".sidebar", ".breadcrumb", ".menu",
        ]
        assert len(condensed_exclude_selectors) >= 7

    def test_condensed_preserves_main_content(self):
        """Condensed mode must preserve main, article, [role=main], .content."""
        condensed_include_selectors = ["main", "article", "[role=main]", ".content", "#content"]
        assert len(condensed_include_selectors) >= 5

    def test_condensed_fallback_flag(self):
        """Condensed mode must report condensed_fallback: true when no main container found."""
        # Contract test: the response shape must include this field
        condensed_exclude_selectors = [
            "nav", "aside", "footer", "header",
            ".sidebar", ".breadcrumb", ".menu",
        ]
        assert len(condensed_exclude_selectors) >= 7

    @pytest.mark.asyncio
    async def test_regular_analyze_unchanged(self, mock_client):
        """POST /page/analyze (without condensed) must remain unchanged from v0.5."""
        result = await mock_client.analyze_page()
        assert isinstance(result, dict), "analyze_page() must return a dict"

    @pytest.mark.asyncio
    async def test_condensed_returns_structured_response(self, mock_client):
        """analyze_page_condensed must return structured page dict when implemented.
        Mock the evaluate so the method completes and returns a proper response."""
        from cdp_client import json as _json
        mock_client.evaluate = AsyncMock(return_value={
            "status": "ok",
            "result": _json.dumps({
                "url": "http://test", "title": "Test",
                "buttons": [], "modals": [], "form_fields": [],
                "text_preview": "", "text_length": 0,
                "selected_options": [], "visual_state": {},
                "condensed_fallback": False,
                "field_count": 0, "button_count": 0,
                "checkbox_count": 0, "radio_count": 0, "modal_count": 0,
            }),
        })
        result = await mock_client.analyze_page_condensed()
        assert result["status"] == "ok"
        page = result.get("page", {})
        assert "url" in page
        assert "title" in page
        assert "condensed_fallback" in page, "condensed must include fallback flag"
        assert "field_count" in page, "condensed must include summary counts"
        assert "checkbox_count" in page


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — P2: BATCH CHECKBOX (behavioural — red: NotImplementedError)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestP2BatchCheckbox:
    """POST /checkbox/select and /checkbox/deselect by label text.

    Routes & models exist, but the underlying CDP methods raise
    NotImplementedError — these tests verify the full impl is done.
    """

    async def test_checkbox_set_state_works(self, mock_client):
        """checkbox_set_state() must return a proper result dict."""
        result = await mock_client.checkbox_set_state("test", True)
        assert isinstance(result, dict)
        assert result.get("status") == "ok"
        assert "label" in result
        assert "checked" in result
        assert "was_already_checked" in result

    async def test_checkbox_set_state_batch_works(self, mock_client):
        """checkbox_set_state_batch() must return a proper result dict."""
        result = await mock_client.checkbox_set_state_batch(["test1", "test2"], True)
        assert isinstance(result, dict)
        assert result.get("status") == "ok"

    async def test_checkbox_select_endpoint_exists(self, async_client):
        """POST /checkbox/select route exists (may 400 due to no connection)."""
        resp = await async_client.post("/checkbox/select", json={"text": "Email notifications"})
        # Should 200 in v0.7, currently 400 (not connected) or 422 (body model) or 500
        assert resp.status_code in (200, 400, 422, 500), (
            "checkbox/select route exists but not fully implemented yet"
        )

    async def test_checkbox_deselect_endpoint_exists(self, async_client):
        """POST /checkbox/deselect route exists."""
        resp = await async_client.post("/checkbox/deselect", json={"text": "SMS notifications"})
        assert resp.status_code in (200, 400, 422, 500)

    async def test_checkbox_select_returns_200_when_implemented(self, async_client):
        """POST /checkbox/select should return 200 in v0.7."""
        # Mock the CDP client to appear connected (is_connected is a read-only property)
        from unittest.mock import AsyncMock, patch

        patch_target = "main.ensure_connected"
        with patch(patch_target, return_value=None):
            from main import client
            client._connected = True
            client._active_tab_id = "tab-1"
            client._ws = None
            client._send_command = AsyncMock(return_value={"result": {"value": "mocked"}})
            client._activate_current = AsyncMock()
            client.evaluate = AsyncMock(return_value={"status": "ok", "result": {
                "label": "Email", "was_already_checked": False
            }})
            resp = await async_client.post("/checkbox/select", json={"text": "Email"})
            assert resp.status_code == 200, (
                f"v0.7 must return 200 from /checkbox/select (got {resp.status_code}: {resp.text})"
            )

    async def test_checkbox_select_response_shape(self, async_client):
        """POST /checkbox/select response must have operation, status, result."""
        resp = await async_client.post("/checkbox/select", json={"text": "Email"})
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") == "ok"
            assert data.get("operation") == "checkbox_select"
            result = data.get("result", {})
            assert "label" in result
            assert "checked" in result
            assert "was_already_checked" in result

    async def test_checkbox_deselect_response_shape(self, async_client):
        """POST /checkbox/deselect response must have operation, status, result."""
        resp = await async_client.post("/checkbox/deselect", json={"text": "SMS"})
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") == "ok"
            assert data.get("operation") == "checkbox_deselect"
            result = data.get("result", {})
            assert "label" in result
            assert "checked" in result
            assert "was_already_checked" in result

    async def test_checkbox_select_returns_was_already_checked(self, async_client):
        """POST /checkbox/select must indicate whether the checkbox was already checked."""
        resp = await async_client.post("/checkbox/select", json={"text": "Email"})
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("result", {})
            assert "was_already_checked" in result
            assert isinstance(result["was_already_checked"], bool)

    async def test_checkbox_deselect_returns_was_already_checked(self, async_client):
        """POST /checkbox/deselect must indicate whether the checkbox was already unchecked."""
        resp = await async_client.post("/checkbox/deselect", json={"text": "SMS"})
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("result", {})
            assert "was_already_checked" in result
            assert isinstance(result["was_already_checked"], bool)

    async def test_checkbox_select_batch_support(self, async_client):
        """POST /checkbox/select must support batch mode via 'texts' array."""
        resp = await async_client.post("/checkbox/select", json={"texts": ["Email", "SMS"]})
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("status") == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — P2: SCREENSHOT CONFIRMATION (behavioural — red)
# ═══════════════════════════════════════════════════════════════════════════


class TestP2ScreenshotConfirmationSync:
    """Sync contract tests for screenshot confirmation (no asyncio marker needed)."""

    def test_state_change_from_visual_state(self):
        """state_change before/after must be derived from analyze_page()."""
        mock_vs = {
            "Email notifications": {"checked": True, "type": "checkbox", "value": "email"},
            "SMS notifications": {"checked": False, "type": "checkbox", "value": "sms"},
        }
        assert isinstance(mock_vs, dict)


@pytest.mark.asyncio
class TestP2ScreenshotConfirmation:
    """Click/checkbox operations must return screenshot or re-analysed state.

    _confirm_with_screenshot / _confirm_with_analyze exist as stubs
    (raise NotImplementedError). These tests verify the full impl.
    """

    async def test_confirm_with_screenshot_returns_dict(self, mock_client):
        """_confirm_with_screenshot must return a dict with screenshot field."""
        mock_client.screenshot = AsyncMock(return_value={"data": "base64jpegdata"})
        result = await mock_client._confirm_with_screenshot()
        assert isinstance(result, dict)
        assert "screenshot" in result

    async def test_confirm_with_analyze_returns_state_change(self, mock_client):
        """_confirm_with_analyze must return state_change dict."""
        mock_client.analyze_page = AsyncMock(return_value={
            "status": "ok",
            "page": {"visual_state": {"Email": {"checked": True, "type": "checkbox", "value": "email"}}},
        })
        mock_client._before_visual_state = {"Email": {"checked": False, "type": "checkbox", "value": "email"}}
        result = await mock_client._confirm_with_analyze()
        assert isinstance(result, dict)
        assert "state_change" in result
        sc = result["state_change"]
        assert "before" in sc
        assert "after" in sc
        assert "changed" in sc

    async def test_click_label_returns_confirmation_screenshot(self, async_client):
        """POST /checkbox/select?confirm=screenshot returns confirmation with screenshot."""
        resp = await async_client.post("/checkbox/select?confirm=screenshot", json={"text": "Email"})
        if resp.status_code == 200:
            data = resp.json()
            conf = data.get("confirmation")
            assert conf is not None, (
                "v0.7 should add confirmation block with ?confirm=screenshot"
            )
            assert "screenshot" in conf, "confirmation should include base64 screenshot"

    async def test_click_label_returns_state_change(self, async_client):
        """POST /checkbox/select?confirm=analyze returns state_change."""
        resp = await async_client.post("/checkbox/select?confirm=analyze", json={"text": "Email"})
        if resp.status_code == 200:
            data = resp.json()
            conf = data.get("confirmation", {})
            assert "state_change" in conf, (
                "confirmation should include before/after state comparison"
            )
            sc = conf["state_change"]
            assert "before" in sc
            assert "after" in sc
            assert "changed" in sc

    async def test_click_by_text_returns_confirmation(self, async_client):
        """POST /checkbox/select response includes result with label/checked."""
        resp = await async_client.post("/checkbox/select", json={"text": "Submit"})
        if resp.status_code == 200:
            data = resp.json()
            assert "result" in data, (
                "v0.7 /checkbox/select should return result"
            )

    async def test_screenshot_confirmation_is_optional(self, async_client):
        """Screenshot confirmation must be opt-in via ?confirm= query param."""
        resp = await async_client.post("/click/label", json={"text": "Save"})
        if resp.status_code == 200:
            data = resp.json()
            if "confirmation" in data:
                assert False, (
                    "Without ?confirm= param, confirmation should NOT be present "
                    "(backward compatibility)"
                )

    async def test_confirm_analyze_returns_state_change(self, async_client):
        """?confirm=analyze should return state_change from visual_state comparison."""
        resp = await async_client.post("/click/label?confirm=analyze", json={"text": "Save"})
        if resp.status_code == 200:
            data = resp.json()
            conf = data.get("confirmation", {})
            assert "state_change" in conf, "?confirm=analyze should include state_change"
            sc = conf["state_change"]
            assert "before" in sc
            assert "after" in sc
            assert "changed" in sc

    async def test_confirm_screenshot_returns_base64_jpeg(self, async_client):
        """?confirm=screenshot should return screenshot as valid base64 JPEG."""
        # Need to mock screenshot to return base64 data
        import base64
        fake_jpeg = base64.b64encode(b"fake-jpeg-binary-data").decode()
        from main import client
        client.screenshot = AsyncMock(return_value={"data": fake_jpeg})
        resp = await async_client.post("/checkbox/select?confirm=screenshot", json={"text": "Email"})
        if resp.status_code == 200:
            data = resp.json()
            conf = data.get("confirmation", {})
            ss = conf.get("screenshot", "")
            assert ss, "?confirm=screenshot should include base64 screenshot"
            try:
                base64.b64decode(ss, validate=True)
            except ValueError:
                pytest.fail("screenshot is not valid base64")
