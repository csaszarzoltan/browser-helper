"""The semantic observe list must report ARIA roles and label-based names."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_runtime import SnapshotStore  # noqa: E402


def _by_name(elements, name):
    return next(e for e in elements if e["name"] == name)


def test_text_input_is_a_textbox_named_by_its_label():
    page = {"form_fields": [{"tag": "INPUT", "type": "text", "name": "custname",
                             "label": "Customer name:"}]}
    el = _by_name(SnapshotStore._extract_elements(page), "Customer name:")
    assert el["role"] == "textbox"


def test_input_types_map_to_aria_roles():
    page = {"form_fields": [
        {"tag": "INPUT", "type": "tel", "name": "custtel", "label": "Telephone:"},
        {"tag": "INPUT", "type": "radio", "name": "size", "label": "Small"},
        {"tag": "INPUT", "type": "checkbox", "name": "topping", "label": "Bacon"},
        {"tag": "INPUT", "type": "number", "name": "qty", "label": "Quantity"},
        {"tag": "TEXTAREA", "type": "", "name": "comments", "label": "Comments"},
    ]}
    roles = {e["name"]: e["role"] for e in SnapshotStore._extract_elements(page)}
    assert roles == {"Telephone:": "textbox", "Small": "radio", "Bacon": "checkbox",
                     "Quantity": "spinbutton", "Comments": "textbox"}


def test_field_without_label_falls_back_to_name_attribute():
    page = {"form_fields": [{"tag": "INPUT", "type": "text", "name": "custname", "label": ""}]}
    el = SnapshotStore._extract_elements(page)[0]
    assert el["name"] == "custname"
    assert el["role"] == "textbox"


def test_buttons_keep_their_text_as_name():
    page = {"buttons": [{"text": "Submit order", "type": "submit"}]}
    el = SnapshotStore._extract_elements(page)[0]
    assert el["name"] == "Submit order"
    assert el["role"] == "button"


def test_shadow_and_iframe_context_is_carried_to_elements():
    page = {"form_fields": [
        {"tag": "INPUT", "type": "text", "name": "shadowemail", "label": "Shadow email:",
         "context": "shadow", "selector": '[data-bh-ctx="c1"]'},
        {"tag": "INPUT", "type": "text", "name": "x", "label": "Plain:"},
    ]}
    els = SnapshotStore._extract_elements(page)
    shadow = _by_name(els, "Shadow email:")
    assert shadow["context"] == "shadow"
    assert shadow["selector"] == '[data-bh-ctx="c1"]'
    assert "context" not in _by_name(els, "Plain:")


def test_await_user_needs_a_condition(monkeypatch):
    import asyncio
    import json as _json

    from mcp_server import tools

    out = _json.loads(asyncio.run(tools.await_user()))
    assert out["status"] == "error"
    assert out["error"]["code"] == "invalid_params"


def test_select_option_needs_exactly_one_choice():
    import asyncio
    import json as _json

    from mcp_server import tools

    out = _json.loads(asyncio.run(tools.select_option(selector="#pick", value="a", label="A")))
    assert out["error"]["code"] == "invalid_params"
    out = _json.loads(asyncio.run(tools.select_option(selector="#pick")))
    assert out["error"]["code"] == "invalid_params"


def test_diff_names_a_changed_field_value():
    from types import SimpleNamespace

    from agent_runtime import _field_changes

    old = SimpleNamespace(elements=[{"role": "textbox", "name": "Username", "selector": None, "value": ""}])
    new = SimpleNamespace(elements=[{"role": "textbox", "name": "Username", "selector": None, "value": "hello"}])
    assert _field_changes(old, new, "value") == [
        {"role": "textbox", "name": "Username", "from": "", "to": "hello"}
    ]
    assert _field_changes(old, old, "value") == []


def test_cross_origin_selector_is_split_into_frame_and_inner_selector():
    from cdp_client import CDPClient

    assert CDPClient._split_oopif("oopif|f2|[data-bh-ctx=\"c1\"]") == ("f2", '[data-bh-ctx="c1"]')
    assert CDPClient._split_oopif('[data-bh-ctx="c1"]') is None
    assert CDPClient._split_oopif(None) is None


def test_backend_node_id_is_kept_so_closed_shadow_controls_can_be_acted_on():
    page = {"buttons": [{"tag": "BUTTON", "text": "Closed save", "context": "closed-shadow",
                         "backend_node_id": 42}]}
    el = SnapshotStore._extract_elements(page)[0]
    assert el["backend_node_id"] == 42
    assert el["role"] == "button"
