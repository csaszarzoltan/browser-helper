"""Focused regression tests for the LLM Agent Navigation Engine."""

import pytest

# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

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


def legacy_page_without_dropdown():
    return {
        "page": {
            "url": "https://example.test",
            "title": "Demo",
            "text_preview": "Submit Save",
            "buttons": [{"text": "Submit", "selector": "#submit"}],
        }
    }


def modal_ax_tree():
    return {
        "nodes": [
            {"nodeId": "1", "role": ax_value("main"), "name": ax_value("Page"), "childIds": ["2"]},
            {
                "nodeId": "2",
                "role": ax_value("dialog"),
                "name": ax_value("Add a link"),
                "childIds": ["3", "4"],
            },
            {
                "nodeId": "3",
                "backendDOMNodeId": 4023,
                "role": ax_value("button"),
                "name": ax_value("Add a web link"),
            },
            {
                "nodeId": "4",
                "backendDOMNodeId": 4024,
                "role": ax_value("textbox"),
                "name": ax_value("Describe what the link is for"),
                "properties": [{"name": "required", "value": {"value": True}}],
            },
        ]
    }


def test_snapshot_store_pin_survives_capacity_pruning():
    from agent_runtime import SnapshotStore

    store = SnapshotStore(max_snapshots=2)
    first = store.add(legacy_page_without_dropdown())
    store.pin(first.snapshot_id)
    for index in range(5):
        store.add({"page": {"url": f"https://example.test/{index}", "text": str(index)}})
    assert store.get(first.snapshot_id).snapshot_id == first.snapshot_id
    store.unpin(first.snapshot_id)
    store.add({"page": {"url": "https://example.test/final", "text": "final"}})
    assert not store.is_pinned(first.snapshot_id)


def test_observe_falls_back_to_accessibility_for_missing_text(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.analyze_page_condensed = AsyncMock(return_value=legacy_page_without_dropdown())
    main.client.get_accessibility_tree = AsyncMock(
        return_value={
            "status": "ok",
            "tree": modal_ax_tree(),
            "page": {"url": "https://example.test", "title": "Demo"},
        }
    )
    response = api.post(
        "/agent/observe", json={"search_text": "Add a web link", "fallback": "accessibility"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["fallback"] is True
    assert any(node["name"] == "Add a web link" for node in body["data"]["nodes"])


def test_direct_backend_node_click_needs_no_snapshot(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.click_backend_node = AsyncMock(return_value={"status": "ok", "clicked": True})
    response = api.post(
        "/agent/act",
        json={"action": "click", "target": {"backend_node_id": 4023}, "observe_after": False},
    )
    assert response.status_code == 200
    main.client.click_backend_node.assert_awaited_once_with(4023)


def test_modal_scope_is_automatic(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.get_accessibility_tree = AsyncMock(
        return_value={
            "status": "ok",
            "tree": modal_ax_tree(),
            "page": {"url": "https://example.test", "title": "Demo"},
        }
    )
    data = api.post("/agent/observe", json={"mode": "accessibility"}).json()["data"]
    assert {node["name"] for node in data["nodes"]} == {
        "Add a link",
        "Add a web link",
        "Describe what the link is for",
    }


def test_stale_snapshot_auto_recovers_by_accessible_name(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.get_accessibility_tree = AsyncMock(
        return_value={
            "status": "ok",
            "tree": modal_ax_tree(),
            "page": {"url": "https://example.test", "title": "Demo"},
        }
    )
    main.client.click_backend_node = AsyncMock(return_value={"status": "ok", "clicked": True})
    response = api.post(
        "/agent/act",
        json={
            "action": "click",
            "target": {"snapshot_id": "missing", "ref": "e99", "name": "Add a web link"},
            "auto_recover": True,
            "observe_after": False,
        },
    )
    assert response.status_code == 200
    main.client.click_backend_node.assert_awaited_once_with(4023)


def test_workflow_record_and_replay(monkeypatch):
    api = connected_client(monkeypatch)
    main.agent_recordings.clear()
    main.active_recording_id = None
    main.client.click_backend_node = AsyncMock(return_value={"status": "ok", "clicked": True})
    rec = api.post("/agent/record", json={"name": "modal-link"}).json()["data"]
    assert (
        api.post(
            "/agent/act",
            json={"action": "click", "target": {"backend_node_id": 4023}, "observe_after": False},
        ).status_code
        == 200
    )
    stopped = api.post("/agent/record/stop").json()["data"]
    assert len(stopped["steps"]) == 1
    replay = api.post("/agent/replay", json={"recording_id": rec["recording_id"]})
    assert replay.status_code == 200
    assert replay.json()["data"]["replayed"] == 1


def test_smart_form_fill_uses_literal_placeholder_scan():
    import inspect

    from cdp_client import CDPClient

    source = inspect.getsource(CDPClient.smart_form_fill)
    assert 'Array.from(document.querySelectorAll("input, textarea"))' in source
    assert "candidate.placeholder" in source
    assert "CSS.escape(f.placeholder)" not in source


def test_observe_include_hidden_returns_ignored_ax_nodes(monkeypatch):
    api = connected_client(monkeypatch)
    tree = modal_ax_tree()
    tree["nodes"].append(
        {"nodeId": "9", "ignored": True, "role": ax_value("tab"), "name": ax_value("Published")}
    )
    main.client.get_accessibility_tree = AsyncMock(
        return_value={"status": "ok", "tree": tree, "page": {}}
    )
    normal = api.post("/agent/observe", json={"mode": "accessibility", "auto_modal": False}).json()[
        "data"
    ]
    hidden = api.post(
        "/agent/observe",
        json={"mode": "accessibility", "auto_modal": False, "include_hidden": True},
    ).json()["data"]
    assert not any(node["name"] == "Published" for node in normal["nodes"])
    assert any(node["name"] == "Published" for node in hidden["nodes"])


def test_act_verify_after_reports_verified_text(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.click_backend_node = AsyncMock(return_value={"status": "ok"})
    main.client.wait_for_text_detailed = AsyncMock(
        return_value={"found": True, "elapsed_ms": 220, "actual_text": "Browser Helper"}
    )
    response = api.post(
        "/agent/act",
        json={
            "action": "click",
            "target": {"backend_node_id": 3596},
            "verify_after": {"type": "text_visible", "text": "Browser Helper", "timeout_ms": 5000},
            "observe_after": False,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["verified"] is True
    assert data["actual_text"] == "Browser Helper"


def test_select_tab_and_wait_for_element_actions(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.select_tab_by_text = AsyncMock(return_value={"status": "ok"})
    main.client.wait_for_text_detailed = AsyncMock(
        return_value={"found": True, "elapsed_ms": 2340, "actual_text": "Browser Helper"}
    )
    assert (
        api.post(
            "/agent/act",
            json={"action": "select_tab", "target": {"text": "Published"}, "observe_after": False},
        ).status_code
        == 200
    )
    waited = api.post(
        "/agent/act",
        json={
            "action": "wait_for_element",
            "target": {"text": "Browser Helper"},
            "timeout_ms": 10000,
            "observe_after": False,
        },
    ).json()["data"]["result"]
    assert waited == {"found": True, "elapsed_ms": 2340, "actual_text": "Browser Helper"}


def test_forms_fill_autocomplete_resolver(monkeypatch):
    api = connected_client(monkeypatch)
    tree = modal_ax_tree()
    tree["nodes"][3]["name"] = ax_value("Skills and deliverables")
    main.client.get_accessibility_tree = AsyncMock(
        return_value={"status": "ok", "tree": tree, "page": {}}
    )
    main.client.fill_autocomplete = AsyncMock(
        return_value={"status": "ok", "result": {"status": "ok", "selected": "Python"}}
    )
    discovered = api.post("/agent/forms/discover").json()["data"]["forms"][0]
    response = api.post(
        "/agent/forms/fill",
        json={
            "form_ref": discovered["form_ref"],
            "data": {"skills_and_deliverables": {"value": "Python", "resolver": "autocomplete"}},
            "validate": False,
        },
    )
    assert response.status_code == 200
    main.client.fill_autocomplete.assert_awaited_once()
    assert response.json()["data"]["confirmed"] == 1


def test_forms_discover_page_with_history_triggers_lazy_load(monkeypatch):
    api = connected_client(monkeypatch)
    main.client.trigger_lazy_history = AsyncMock(
        return_value={"status": "ok", "result": {"scrolls": 3}}
    )
    main.client.get_accessibility_tree = AsyncMock(
        return_value={"status": "ok", "tree": modal_ax_tree(), "page": {}}
    )
    response = api.post("/agent/forms/discover", json={"scope": "page_with_history"})
    assert response.status_code == 200
    main.client.trigger_lazy_history.assert_awaited_once()
    assert response.json()["data"]["history_load"]["status"] == "ok"


def test_replay_accepts_new_contract_and_applies_overrides(monkeypatch):
    api = connected_client(monkeypatch)
    main.agent_recordings.clear()
    main.active_recording_id = None
    main.client.smart_form_fill = AsyncMock(return_value={"status": "ok"})
    rec = api.post("/agent/record", json={"start": True}).json()["data"]
    api.post(
        "/agent/act",
        json={
            "action": "fill",
            "fields": [{"label": "Title", "value": "Old title"}],
            "observe_after": False,
        },
    )
    api.post("/agent/record/stop")
    response = api.post(
        "/agent/replay",
        json={
            "recorded_id": rec["recording_id"],
            "on_error": "stop",
            "data_overrides": {"value": "Browser Helper v2.0"},
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["replayed"] == 1
    assert (
        main.client.smart_form_fill.await_args_list[-1].args[0][0]["value"] == "Browser Helper v2.0"
    )
