"""Focused regression tests for the LLM Agent Navigation Engine."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import main
from agent_navigation import (
    AccessibilityTreeBuilder,
    available_actions,
    discover_forms,
    extract_by_schema,
    validate_expectations,
)


def ax_value(value):
    return {"type": "string", "value": value}


def ax_tree(*, filled=False, payment=False):
    nodes = [
        {
            "nodeId": "1",
            "role": ax_value("main"),
            "name": ax_value("Checkout"),
            "childIds": ["2", "6"],
        },
        {
            "nodeId": "2",
            "role": ax_value("form"),
            "name": ax_value("Shipping address"),
            "childIds": ["3", "4", "5"],
        },
        {
            "nodeId": "3",
            "backendDOMNodeId": 103,
            "role": ax_value("textbox"),
            "name": ax_value("Full name"),
            "value": ax_value("Ada Lovelace" if filled else ""),
            "properties": [{"name": "required", "value": {"value": True}}],
        },
        {
            "nodeId": "4",
            "backendDOMNodeId": 104,
            "role": ax_value("textbox"),
            "name": ax_value("ZIP code"),
            "value": ax_value("8001" if filled else ""),
            "properties": [
                {"name": "required", "value": {"value": True}},
                {"name": "invalid", "value": {"value": False}},
            ],
        },
        {
            "nodeId": "5",
            "backendDOMNodeId": 105,
            "role": ax_value("combobox"),
            "name": ax_value("Country"),
            "value": ax_value("Switzerland" if filled else "Select country"),
            "properties": [{"name": "expanded", "value": {"value": False}}],
        },
        {
            "nodeId": "6",
            "backendDOMNodeId": 106,
            "role": ax_value("button"),
            "name": ax_value("Continue"),
            "properties": [],
        },
    ]
    if payment:
        nodes.append(
            {"nodeId": "7", "role": ax_value("heading"), "name": ax_value("Payment method")}
        )
        nodes[0]["childIds"].append("7")
    return {"nodes": nodes}


def build(tree=None, url="https://example.test/checkout"):
    return AccessibilityTreeBuilder().build(
        tree or ax_tree(), page={"url": url, "title": "Checkout"}
    )


def test_accessibility_tree_produces_semantic_graph_and_states():
    snap = build()
    names = {node.name: node for node in snap.nodes}
    assert names["Shipping address"].role == "form"
    assert names["Full name"].states["required"] is True
    assert names["Full name"].backend_node_id == 103
    assert "form: Shipping address" in names["ZIP code"].path
    assert names["Country"].actions == ["focus", "open", "select"]
    assert names["Continue"].actions == ["click"]


def test_scope_interactive_and_truncation_are_deterministic():
    builder = AccessibilityTreeBuilder()
    snap = builder.build(ax_tree(), page={}, interactive_only=True)
    assert all(node.role not in {"main", "form"} for node in snap.nodes)
    assert snap.as_dict(max_nodes=2)["truncated"] is True
    assert builder.build(ax_tree(), page={}, interactive_only=True).fingerprint == snap.fingerprint


def test_form_discovery_maps_semantic_types_and_required_state():
    forms = discover_forms(build())
    assert len(forms) == 1
    fields = {field["semantic_type"]: field for field in forms[0]["fields"]}
    assert fields["full_name"]["required"] is True
    assert fields["postal_code"]["ref"].startswith("e")
    assert fields["country"]["role"] == "combobox"


def test_available_actions_explains_missing_fields():
    actions = available_actions(build())
    fill = next(item for item in actions["suggested_actions"] if item["action"] == "fill_form")
    assert fill["required_missing_fields"] == 2
    assert actions["context"]["page_type"] == "form"


def test_post_action_expectation_accepts_visible_text_and_url_change():
    before = build()
    after = build(ax_tree(payment=True), "https://example.test/payment")
    result = validate_expectations(
        before, after, {"any_of": [{"url_changed": True}, {"text_visible": "Payment method"}]}
    )
    assert result["satisfied"] is True
    assert len(result["matched"]) == 2


def test_schema_extraction_returns_evidence_and_missing_without_fabricating():
    tree = {
        "nodes": [
            {
                "nodeId": "1",
                "role": ax_value("main"),
                "name": ax_value("Product"),
                "childIds": ["2", "3"],
            },
            {
                "nodeId": "2",
                "role": ax_value("heading"),
                "name": ax_value("Product name"),
                "value": ax_value("Alpine Mug"),
            },
            {
                "nodeId": "3",
                "role": ax_value("staticText"),
                "name": ax_value("Price"),
                "value": ax_value("CHF 49.90"),
            },
        ]
    }
    result = extract_by_schema(
        build(tree),
        {
            "type": "object",
            "properties": {
                "product_name": {"type": "string"},
                "price": {"type": "string"},
                "availability": {"type": "string"},
            },
            "required": ["product_name", "price", "availability"],
        },
    )
    assert result["data"]["product_name"] == "Alpine Mug"
    assert result["evidence"]["price"]["ref"]
    assert result["missing"] == ["availability"]


def connected_client(monkeypatch):
    monkeypatch.setattr(type(main.client), "is_connected", property(lambda self: True))
    main.ax_snapshots.clear()
    return TestClient(main.app)


def test_accessibility_observe_api(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.get_accessibility_tree = AsyncMock(
        return_value={
            "status": "ok",
            "tree": ax_tree(),
            "page": {"url": "https://example.test", "title": "Checkout"},
        }
    )
    response = api.post(
        "/agent/observe", json={"mode": "accessibility", "scope": "main", "max_nodes": 20}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot_id"].startswith("ax_")
    assert any(node["name"] == "Country" for node in data["nodes"])
    assert response.json()["meta"]["mode"] == "accessibility"


def test_forms_and_extract_api(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.get_accessibility_tree = AsyncMock(
        return_value={
            "status": "ok",
            "tree": ax_tree(),
            "page": {"url": "https://example.test", "title": "Checkout"},
        }
    )
    discovered = api.post("/agent/forms/discover").json()["data"]
    assert discovered["forms"][0]["name"] == "Shipping address"
    extracted = api.post(
        "/agent/extract",
        json={
            "schema": {
                "type": "object",
                "properties": {"country": {"type": "string"}},
                "required": ["country"],
            }
        },
    )
    assert extracted.status_code == 200
    assert extracted.json()["data"]["evidence"]["country"]["ref"]
