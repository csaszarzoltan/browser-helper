"""Semantic navigation primitives for LLM-driven browser agents.

The module converts Chrome's accessibility tree into a compact, stable snapshot,
models forms and element relationships, validates post-action expectations, and
performs deterministic schema-guided extraction.  It intentionally contains no
FastAPI or CDP transport code so its behavior is easy to test in isolation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

INTERACTIVE_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "link",
    "listbox",
    "menuitem",
    "option",
    "radio",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "textbox",
}
LANDMARK_ROLES = {"main", "dialog", "form", "region", "table", "grid", "alert"}
FORM_ROLES = {
    "textbox",
    "searchbox",
    "combobox",
    "checkbox",
    "radio",
    "switch",
    "slider",
    "spinbutton",
}
ROLE_PREFIX = {"main": "r", "region": "r", "dialog": "d", "form": "f", "table": "t", "grid": "t"}


def _value(value: Any, default: Any = None) -> Any:
    """Unwrap a CDP RemoteObject-like ``{"value": ...}`` value."""
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return default if value is None else value


def _properties(node: dict) -> dict[str, Any]:
    return {
        str(p.get("name")): _value(p.get("value"))
        for p in node.get("properties", [])
        if p.get("name")
    }


def _semantic_type(name: str, role: str, props: dict[str, Any]) -> str:
    text = " ".join((name, str(props.get("autocomplete", "")))).lower()
    patterns = [
        ("email", r"e-?mail"),
        ("postal_code", r"postal|zip|postcode"),
        ("phone", r"phone|mobile|telephone|tel\b"),
        ("country", r"country"),
        ("city", r"city|town"),
        ("street_address", r"street|address line|house number"),
        ("full_name", r"full name|your name|recipient"),
        ("first_name", r"first name|given name"),
        ("last_name", r"last name|family name|surname"),
        ("password", r"password|passcode"),
        ("date", r"date|birthday|birth date"),
    ]
    for result, pattern in patterns:
        if re.search(pattern, text):
            return result
    return "boolean" if role in {"checkbox", "switch"} else role


@dataclass
class SemanticNode:
    ref: str
    role: str
    name: str = ""
    description: str = ""
    value: Any = None
    backend_node_id: int | None = None
    parent_ref: str | None = None
    children: list[str] = field(default_factory=list)
    path: list[str] = field(default_factory=list)
    relations: dict[str, Any] = field(default_factory=dict)
    states: dict[str, Any] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def as_dict(self) -> dict:
        result = {
            "ref": self.ref,
            "role": self.role,
            "name": self.name,
            "description": self.description,
            "value": self.value,
            "backend_node_id": self.backend_node_id,
            "parent_ref": self.parent_ref,
            "children": self.children,
            "path": self.path,
            "relations": self.relations,
            "states": self.states,
            "actions": self.actions,
            "confidence": self.confidence,
        }
        result.update(self.states)
        return {k: v for k, v in result.items() if v not in (None, "", [], {})}


@dataclass
class AccessibilitySnapshot:
    snapshot_id: str
    fingerprint: str
    nodes: list[SemanticNode]
    roots: list[str]
    page: dict[str, str]

    def as_dict(self, *, max_nodes: int = 250) -> dict:
        visible = self.nodes[:max_nodes]
        return {
            "snapshot_id": self.snapshot_id,
            "fingerprint": self.fingerprint,
            "page": self.page,
            "roots": self.roots,
            "nodes": [node.as_dict() for node in visible],
            "truncated": len(visible) < len(self.nodes),
            "omitted_nodes": max(0, len(self.nodes) - len(visible)),
        }


class AccessibilityTreeBuilder:
    """Build a compact semantic graph from ``Accessibility.getFullAXTree`` output."""

    def build(
        self,
        raw: dict,
        *,
        page: dict[str, str] | None = None,
        include: Iterable[str] | None = None,
        scope: str = "page",
        interactive_only: bool = False,
        include_hidden: bool = False,
    ) -> AccessibilitySnapshot:
        raw_nodes = list(raw.get("nodes", []))
        parent_of: dict[str, str] = {}
        for node in raw_nodes:
            for child in node.get("childIds", []):
                parent_of[str(child)] = str(node.get("nodeId"))

        ordered: list[SemanticNode] = []
        id_to_ref: dict[str, str] = {}
        counters: dict[str, int] = {}
        requested = {x.lower() for x in include or []}

        for raw_node in raw_nodes:
            if raw_node.get("ignored") and not include_hidden:
                continue
            role = str(_value(raw_node.get("role"), "generic") or "generic").lower()
            name = str(_value(raw_node.get("name"), "") or "").strip()
            props = _properties(raw_node)
            if not self._include(role, requested, interactive_only):
                continue
            prefix = ROLE_PREFIX.get(role, "e" if role in INTERACTIVE_ROLES else "n")
            counters[prefix] = counters.get(prefix, 0) + 1
            ref = f"{prefix}{counters[prefix]}"
            node_id = str(raw_node.get("nodeId"))
            id_to_ref[node_id] = ref
            states = {
                key: props[key]
                for key in (
                    "checked",
                    "expanded",
                    "selected",
                    "required",
                    "invalid",
                    "disabled",
                    "readonly",
                    "multiselectable",
                )
                if key in props
            }
            if "disabled" in states:
                states["enabled"] = not bool(states["disabled"])
            actions = self._actions(role, states)
            ordered.append(
                SemanticNode(
                    ref=ref,
                    role=role,
                    name=name,
                    description=str(_value(raw_node.get("description"), "") or ""),
                    value=_value(raw_node.get("value")),
                    backend_node_id=raw_node.get("backendDOMNodeId"),
                    states=states,
                    actions=actions,
                    confidence=1.0 if name or role in LANDMARK_ROLES else 0.75,
                )
            )

        node_by_ref = {n.ref: n for n in ordered}
        for raw_node in raw_nodes:
            ref = id_to_ref.get(str(raw_node.get("nodeId")))
            if not ref:
                continue
            node = node_by_ref[ref]
            parent_id = parent_of.get(str(raw_node.get("nodeId")))
            while parent_id and parent_id not in id_to_ref:
                parent_id = parent_of.get(parent_id)
            if parent_id:
                node.parent_ref = id_to_ref[parent_id]
                node_by_ref[node.parent_ref].children.append(ref)
            node.path = self._path(node, node_by_ref)
            props = _properties(raw_node)
            node.relations = self._relations(props, id_to_ref)

        roots = [n.ref for n in ordered if not n.parent_ref]
        selected = self._apply_scope(ordered, scope)
        canonical = json.dumps(
            [n.as_dict() for n in selected], sort_keys=True, ensure_ascii=False, default=str
        )
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        snapshot_id = f"ax_{fingerprint[:16]}"
        return AccessibilitySnapshot(snapshot_id, fingerprint, selected, roots, page or {})

    @staticmethod
    def _include(role: str, requested: set[str], interactive_only: bool) -> bool:
        if interactive_only:
            return role in INTERACTIVE_ROLES
        if not requested:
            return (
                role in INTERACTIVE_ROLES
                or role in LANDMARK_ROLES
                or role in {"heading", "row", "cell", "listitem", "statictext"}
            )
        categories = {
            "interactive": role in INTERACTIVE_ROLES,
            "headings": role == "heading",
            "forms": role == "form" or role in FORM_ROLES,
            "tables": role in {"table", "grid", "row", "cell", "columnheader", "rowheader"},
            "dialogs": role == "dialog",
            "alerts": role == "alert",
        }
        return role in requested or any(categories.get(x, False) for x in requested)

    @staticmethod
    def _actions(role: str, states: dict[str, Any]) -> list[str]:
        if states.get("disabled"):
            return []
        if role in {"button", "link", "menuitem", "tab", "option"}:
            return ["click"]
        if role in {"textbox", "searchbox", "spinbutton"}:
            return ["focus", "fill"]
        if role in {"combobox", "listbox"}:
            return ["focus", "open", "select"]
        if role in {"checkbox", "radio", "switch"}:
            return ["click", "set_state"]
        return []

    @staticmethod
    def _path(node: SemanticNode, nodes: dict[str, SemanticNode]) -> list[str]:
        path: list[str] = []
        current = node
        seen: set[str] = set()
        while current.parent_ref and current.parent_ref not in seen:
            seen.add(current.parent_ref)
            current = nodes[current.parent_ref]
            if current.role in LANDMARK_ROLES or current.role == "heading":
                label = f"{current.role}: {current.name}".rstrip()
                path.append(label)
        return list(reversed(path))

    @staticmethod
    def _relations(props: dict[str, Any], id_to_ref: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        aliases = {
            "labelledby": "labelled_by",
            "describedby": "described_by",
            "controls": "controls_region",
            "flowto": "next_step",
        }
        for source, target in aliases.items():
            value = props.get(source)
            if not value:
                continue
            ids = value if isinstance(value, list) else [value]
            refs = [
                id_to_ref[str(v.get("value", v) if isinstance(v, dict) else v)]
                for v in ids
                if str(v.get("value", v) if isinstance(v, dict) else v) in id_to_ref
            ]
            if refs:
                result[target] = refs[0] if len(refs) == 1 else refs
        return result

    @staticmethod
    def _apply_scope(nodes: list[SemanticNode], scope: str) -> list[SemanticNode]:
        scope = (scope or "page").lower().strip()
        if scope in {"page", "all"}:
            return nodes
        if scope in {"main", "dialog", "form", "table", "region"}:
            matches = [
                n for n in nodes if n.role == scope or (scope == "table" and n.role == "grid")
            ]
            if not matches:
                return nodes
            allowed = {m.ref for m in matches}
            changed = True
            while changed:
                before = len(allowed)
                allowed.update(n.ref for n in nodes if n.parent_ref in allowed)
                changed = len(allowed) != before
            return [n for n in nodes if n.ref in allowed]
        target = next((n for n in nodes if n.ref == scope), None)
        if not target:
            raise ValueError(f"Unknown accessibility scope: {scope}")
        allowed = {target.ref}
        changed = True
        while changed:
            before = len(allowed)
            allowed.update(n.ref for n in nodes if n.parent_ref in allowed)
            changed = len(allowed) != before
        return [n for n in nodes if n.ref in allowed]


def discover_forms(snapshot: AccessibilitySnapshot) -> list[dict]:
    """Discover semantic forms and fields from a normalized accessibility snapshot."""
    forms = [n for n in snapshot.nodes if n.role == "form"]
    if not forms:
        forms = [SemanticNode(ref="form_1", role="form", name="Page form")]
    result = []
    for index, form in enumerate(forms, 1):
        fields = []
        for node in snapshot.nodes:
            if node.role not in FORM_ROLES:
                continue
            if form.ref != "form_1" and form.ref not in {
                node.parent_ref,
                *[p.split(":", 1)[-1].strip() for p in node.path],
            }:
                ancestor = node.parent_ref
                by_ref = {n.ref: n for n in snapshot.nodes}
                while ancestor and ancestor != form.ref:
                    ancestor = by_ref.get(ancestor).parent_ref if by_ref.get(ancestor) else None
                if ancestor != form.ref:
                    continue
            fields.append(
                {
                    "ref": node.ref,
                    "role": node.role,
                    "label": node.name,
                    "semantic_type": _semantic_type(node.name, node.role, node.states),
                    "required": bool(node.states.get("required", False)),
                    "disabled": bool(node.states.get("disabled", False)),
                    "invalid": node.states.get("invalid", False),
                    "current_value": node.value,
                    "actions": node.actions,
                }
            )
        if fields:
            result.append(
                {
                    "form_ref": form.ref if form.ref != "form_1" else f"form_{index}",
                    "name": form.name or f"Form {index}",
                    "fields": fields,
                }
            )
    return result


def available_actions(snapshot: AccessibilitySnapshot) -> dict:
    """Return page-specific actions and blocking reasons for an LLM planner."""
    forms = discover_forms(snapshot)
    dialogs = [n for n in snapshot.nodes if n.role == "dialog"]
    suggested = []
    for form in forms:
        missing = [f for f in form["fields"] if f["required"] and not f.get("current_value")]
        suggested.append(
            {
                "action": "fill_form",
                "target": form["form_ref"],
                "description": f"Fill {form['name']}",
                "required_missing_fields": len(missing),
            }
        )
    for node in snapshot.nodes:
        if "click" not in node.actions:
            continue
        blocked = []
        if node.states.get("disabled"):
            blocked.append("Element is disabled")
        suggested.append(
            {
                "action": "click",
                "target": node.ref,
                "description": f"Click {node.name or node.role}",
                "enabled": not blocked,
                "blocked_by": blocked,
            }
        )
    return {
        "context": {
            "page_type": "form" if forms else "document",
            "active_region": dialogs[0].name
            if dialogs
            else next((n.name for n in snapshot.nodes if n.role == "main"), ""),
            "dialog": dialogs[0].ref if dialogs else None,
        },
        "suggested_actions": suggested,
    }


def validate_expectations(
    before: AccessibilitySnapshot, after: AccessibilitySnapshot, expect: dict | None
) -> dict:
    """Evaluate an ``any_of`` expectation set against before/after snapshots."""
    if not expect:
        return {
            "satisfied": before.fingerprint != after.fingerprint,
            "matched": ["page_changed"] if before.fingerprint != after.fingerprint else [],
            "failures": [],
        }
    clauses = expect.get("any_of", [expect])
    matched, failures = [], []
    after_text = " ".join(
        filter(None, [n.name for n in after.nodes] + [str(n.value or "") for n in after.nodes])
    ).lower()
    for clause in clauses:
        ok = False
        label = json.dumps(clause, sort_keys=True)
        if clause.get("url_changed"):
            ok = before.page.get("url") != after.page.get("url")
        elif clause.get("dialog_opened"):
            ok = any(n.role == "dialog" for n in after.nodes) and not any(
                n.role == "dialog" for n in before.nodes
            )
        elif "text_visible" in clause:
            ok = str(clause["text_visible"]).lower() in after_text
        elif "element_visible" in clause:
            spec = clause["element_visible"]
            ok = any(
                (not spec.get("role") or n.role == spec["role"])
                and (not spec.get("name") or spec["name"].lower() in n.name.lower())
                for n in after.nodes
            )
        if ok:
            matched.append(label)
        else:
            failures.append(label)
    return {"satisfied": bool(matched), "matched": matched, "failures": failures}


def extract_by_schema(
    snapshot: AccessibilitySnapshot, schema: dict, *, include_evidence: bool = True
) -> dict:
    """Deterministically map semantic page nodes to a small JSON Schema.

    The extractor is intentionally conservative.  It uses exact/normalized labels,
    semantic aliases and node values; ambiguous or absent fields are returned in
    ``missing`` instead of being fabricated.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    data, evidence, confidence, missing = {}, {}, {}, []
    candidates = [n for n in snapshot.nodes if n.name or n.value not in (None, "")]
    for field_name, spec in properties.items():
        normalized = field_name.replace("_", " ").lower()
        tokens = {t for t in re.split(r"\W+", normalized) if t}
        scored = []
        for node in candidates:
            hay = f"{node.name} {node.description} {' '.join(node.path)}".lower()
            score = sum(1 for t in tokens if t in hay) / max(len(tokens), 1)
            if normalized in hay:
                score += 1.0
            if node.value not in (None, ""):
                score += 0.25
            scored.append((score, node))
        scored.sort(key=lambda x: (-x[0], x[1].ref))
        if not scored or scored[0][0] < 0.5:
            if field_name in required:
                missing.append(field_name)
            continue
        score, node = scored[0]
        value = node.value if node.value not in (None, "") else node.name
        if spec.get("type") == "array":
            value = [value]
        elif spec.get("type") == "number":
            match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
            if not match:
                if field_name in required:
                    missing.append(field_name)
                continue
            value = float(match.group().replace(",", "."))
        data[field_name] = value
        confidence[field_name] = round(min(0.99, 0.55 + score * 0.2), 2)
        if include_evidence:
            evidence[field_name] = {"ref": node.ref, "text": str(value), "role": node.role}
    return {
        "data": data,
        "evidence": evidence if include_evidence else {},
        "missing": missing,
        "confidence": confidence,
    }
