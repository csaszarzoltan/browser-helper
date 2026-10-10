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
