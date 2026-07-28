"""LLM-oriented browser observation, stable references, pagination and actions."""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass


@dataclass
class Snapshot:
    snapshot_id: str
    created_at: float
    url: str
    title: str
    text: str
    elements: list[dict]
    raw: dict
    fingerprint: str


class StaleSnapshotError(ValueError):
    pass


class ElementNotFoundError(ValueError):
    pass


class SnapshotStore:
    def __init__(self, max_snapshots: int = 50, ttl_seconds: int = 1800):
        self.max_snapshots = max_snapshots
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, Snapshot] = {}

    def add(self, raw: dict) -> Snapshot:
        page = raw.get("page", raw.get("result", raw)) if isinstance(raw, dict) else {}
        if isinstance(page, dict) and "page" in page and isinstance(page["page"], dict):
            page = page["page"]
        url = str(page.get("url", ""))
        title = str(page.get("title", ""))
        text = str(page.get("text", page.get("text_preview", "")))
        elements = self._extract_elements(page)
        canonical = json.dumps({"url": url, "title": title, "text": text, "elements": elements}, sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        snapshot_id = f"snap_{uuid.uuid4().hex[:16]}"
        for index, element in enumerate(elements, 1):
            element["element_id"] = f"e{index}"
            element["snapshot_id"] = snapshot_id
        snap = Snapshot(snapshot_id, time.time(), url, title, text, elements, page, fingerprint)
        self._items[snapshot_id] = snap
        self._prune()
        return snap

    @staticmethod
    def _extract_elements(page: dict) -> list[dict]:
        result: list[dict] = []
        groups = {
            "buttons": "button", "links": "link", "form_fields": "field",
            "inputs": "field", "checkboxes": "checkbox", "radios": "radio",
            "selects": "select", "modals": "dialog",
        }
        seen: set[str] = set()
        for key, default_role in groups.items():
            values = page.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, str):
                    item = {"name": item}
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("text") or item.get("label") or item.get("placeholder") or "").strip()
                selector = item.get("selector") or item.get("css_selector")
                role = str(item.get("role") or item.get("type") or default_role)
                key_sig = json.dumps([role, name, selector], ensure_ascii=False)
                if key_sig in seen:
                    continue
                seen.add(key_sig)
                result.append({
                    "role": role, "name": name, "selector": selector,
                    "visible": item.get("visible", True), "enabled": item.get("enabled", True),
                    "checked": item.get("checked"), "value": item.get("value"),
                })
        return result

    def get(self, snapshot_id: str) -> Snapshot:
        snap = self._items.get(snapshot_id)
        if snap is None or time.time() - snap.created_at > self.ttl_seconds:
            self._items.pop(snapshot_id, None)
            raise StaleSnapshotError(f"Snapshot {snapshot_id!r} is missing or expired")
        return snap

    def resolve(self, snapshot_id: str, element_id: str) -> dict:
        snap = self.get(snapshot_id)
        for element in snap.elements:
            if element["element_id"] == element_id:
                return element
        raise ElementNotFoundError(f"Element {element_id!r} not found in {snapshot_id!r}")

    def _prune(self) -> None:
        now = time.time()
        self._items = {k: v for k, v in self._items.items() if now - v.created_at <= self.ttl_seconds}
        while len(self._items) > self.max_snapshots:
            oldest = min(self._items, key=lambda k: self._items[k].created_at)
            del self._items[oldest]


def encode_cursor(offset: int, snapshot_id: str) -> str:
    payload = json.dumps({"o": offset, "s": snapshot_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str, snapshot_id: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if payload["s"] != snapshot_id or int(payload["o"]) < 0:
            raise ValueError
        return int(payload["o"])
    except Exception as exc:
        raise ValueError("Invalid or stale cursor") from exc


def paginate_snapshot(snap: Snapshot, max_chars: int, max_elements: int, cursor: str | None = None) -> dict:
    max_chars = min(max(max_chars, 256), 50000)
    max_elements = min(max(max_elements, 1), 500)
    offset = decode_cursor(cursor, snap.snapshot_id) if cursor else 0
    text = snap.text[offset: offset + max_chars]
    element_start = min(offset // max_chars * max_elements, len(snap.elements))
    elements = snap.elements[element_start: element_start + max_elements]
    next_offset = offset + len(text)
    truncated = next_offset < len(snap.text) or element_start + len(elements) < len(snap.elements)
    return {
        "snapshot_id": snap.snapshot_id,
        "fingerprint": snap.fingerprint,
        "page": {"url": snap.url, "title": snap.title},
        "text": text,
        "elements": elements,
        "truncated": truncated,
        "omitted": {
            "text_chars": max(0, len(snap.text) - next_offset),
            "elements": max(0, len(snap.elements) - element_start - len(elements)),
        },
        "next_cursor": encode_cursor(next_offset, snap.snapshot_id) if truncated else None,
    }


def diff_snapshots(old: Snapshot, new: Snapshot) -> dict:
    old_keys = {(e["role"], e["name"], e.get("selector")) for e in old.elements}
    new_keys = {(e["role"], e["name"], e.get("selector")) for e in new.elements}
    return {
        "from_snapshot_id": old.snapshot_id,
        "to_snapshot_id": new.snapshot_id,
        "changed": old.fingerprint != new.fingerprint,
        "url_changed": old.url != new.url,
        "title_changed": old.title != new.title,
        "text_changed": old.text != new.text,
        "elements_added": [dict(zip(("role", "name", "selector"), x)) for x in sorted(new_keys - old_keys)],
        "elements_removed": [dict(zip(("role", "name", "selector"), x)) for x in sorted(old_keys - new_keys)],
    }
