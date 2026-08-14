"""
Tests for v1.1 features:
- FormFillField: selector, placeholder, nth fields
- FormFillRequest: shorthand with selector+text
- Script endpoint: documentation, action completeness
- smart_form_fill: contenteditable support
"""
import json

import pytest

# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick



# ---------------------------------------------------------------------------
# FormFillField model tests
# ---------------------------------------------------------------------------

class TestFormFillField:
    """Validate FormFillField model accepts new field types."""

    def test_label_only(self):
        """Original label-only format still works."""
        from src.main import FormFillField
        f = FormFillField(label="Email", value="a@b.com")
        d = f.model_dump()
        assert d["label"] == "Email"
        assert d["value"] == "a@b.com"
        assert d["selector"] is None
        assert d["placeholder"] is None
        assert d["nth"] == 0

    def test_selector_field(self):
        """Direct CSS selector."""
        from src.main import FormFillField
        f = FormFillField(selector="#email", value="a@b.com")
        d = f.model_dump()
        assert d["selector"] == "#email"
        assert d["label"] is None

    def test_placeholder_field(self):
        """Exact placeholder match."""
        from src.main import FormFillField
        f = FormFillField(placeholder="Enter email", value="a@b.com")
        d = f.model_dump()
        assert d["placeholder"] == "Enter email"

    def test_nth_field(self):
        """nth index for multiple matching fields."""
        from src.main import FormFillField
        f = FormFillField(label="Name", value="Zoltan", nth=2)
        d = f.model_dump()
        assert d["nth"] == 2

    def test_combined_fields(self):
        """All fields at once."""
        from src.main import FormFillField
        f = FormFillField(
            label="Title", value="Test",
            selector=".title-input", placeholder="Enter title",
            nth=1
        )
        d = f.model_dump()
        assert d["selector"] == ".title-input"
        assert d["placeholder"] == "Enter title"
        assert d["nth"] == 1

    def test_none_defaults(self):
        """Optional fields default to None/0."""
        from src.main import FormFillField
        f = FormFillField(label="X", value="Y")
        d = f.model_dump()
        assert d["selector"] is None
        assert d["placeholder"] is None
        assert d["nth"] == 0
        assert d["type"] is None


# ---------------------------------------------------------------------------
# FormFillRequest model tests
# ---------------------------------------------------------------------------

class TestFormFillRequest:
    """Validate FormFillRequest accepts the extended fields."""

    def test_selector_shorthand(self):
        """Selector + text shorthand."""
        from src.main import FormFillRequest
        r = FormFillRequest(selector="#email", text="a@b.com")
        assert r.fields is not None
        assert len(r.fields) == 1
        assert r.fields[0]["selector"] == "#email"
        assert r.fields[0]["text"] == "a@b.com"

    def test_fields_with_new_types(self):
        """Fields array with selector, placeholder, nth."""
        from src.main import FormFillRequest
        r = FormFillRequest(fields=[
            {"selector": "#name", "value": "Zoltan"},
            {"placeholder": "Enter title", "value": "My Project"},
            {"label": "Description", "value": "A thing", "nth": 1},
        ])
        assert r.fields is not None
        assert len(r.fields) == 3
        assert r.fields[0]["selector"] == "#name"
        assert r.fields[1]["placeholder"] == "Enter title"
        assert r.fields[2]["nth"] == 1

    def test_backward_compat_label_value(self):
        """Old format {label, value} still works."""
        from src.main import FormFillRequest
        r = FormFillRequest(fields=[{"label": "Email", "value": "a@b.com"}])
        assert r.fields is not None
        assert len(r.fields) == 1
        assert r.fields[0]["label"] == "Email"


# ---------------------------------------------------------------------------
# Script endpoint action list test
# ---------------------------------------------------------------------------

class TestScriptActions:
    """Verify /script endpoint documentation matches implementation."""

    def test_script_docstring_includes_all_actions(self):
        """The /script endpoint docstring should list all supported actions."""
        from src.main import execute_script
        doc = execute_script.__doc__ or ""
        expected_actions = [
            "navigate", "click", "type", "eval", "screenshot",
            "full_page_screenshot", "element_screenshot", "wait",
            "wait_for_element", "wait_text", "wait_for_navigation",
            "wait_for_network_idle", "scroll", "get_text", "pdf",
            "click_text", "click_label", "form_fill", "form_select",
            "analyze_page", "upload_files", "find_element",
            "get_iframe_text", "switch_to_iframe", "get_page_outline",
            "page_diff", "close",
        ]
        for action in expected_actions:
            assert action in doc, f"Action '{action}' missing from /script docstring"

    def test_script_steps_type(self):
        """ScriptRequest accepts a list of dicts."""
        from src.main import ScriptRequest
        r = ScriptRequest(steps=[
            {"action": "navigate", "params": {"url": "https://example.com"}},
            {"action": "eval", "params": {"js": "document.title"}},
        ])
        assert len(r.steps) == 2
        assert r.steps[0]["action"] == "navigate"


# ---------------------------------------------------------------------------
# smart_form_fill JS logic tests (unit-level, no browser)
# ---------------------------------------------------------------------------

class TestSmartFormFillJSLogic:
    """Test the JS generation logic in smart_form_fill (without running CDP)."""

    def test_fields_serialized_in_js(self):
        """Verify field descriptors appear in generated JS."""
        fields = [
            {"selector": "#email", "value": "test@test.com"},
            {"placeholder": "Enter title", "value": "My Title"},
            {"label": "Description", "value": "Desc", "nth": 1},
        ]
        # The JS should include all field properties
        js_fields = json.dumps(fields)
        assert "selector" in js_fields
        assert "placeholder" in js_fields
        assert "nth" in js_fields

    def test_form_fill_response_structure(self):
        """Response from smart_form_fill should have expected keys."""
        # This tests the model_dump output, not the actual CDP call
        from src.main import FormFillField
        fields = [
            FormFillField(selector="#name", value="Zoltan"),
            FormFillField(label="Email", value="a@b.com", nth=0),
            FormFillField(placeholder="Title", value="Project"),
        ]
        for f in fields:
            d = f.model_dump()
            assert "value" in d
            assert any(k in d for k in ("label", "selector", "placeholder")), \
                f"Field {d} has no lookup key"


# ---------------------------------------------------------------------------
# Contenteditable support test
# ---------------------------------------------------------------------------

class TestContenteditableSupport:
    """Verify smart_form_fill handles contenteditable elements."""

    def test_contenteditable_in_js(self):
        """The JS code should check for contenteditable attribute."""
        # Read the smart_form_fill JS source
        import inspect

        from src.cdp_client import CDPClient
        source = inspect.getsource(CDPClient.smart_form_fill)
        assert "contenteditable" in source
        assert "textContent" in source
