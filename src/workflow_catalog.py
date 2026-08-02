"""Durable, versioned and parameterized browser workflow catalog."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_PLACEHOLDER = re.compile(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}")
_TYPES = {"string", "number", "boolean", "url", "enum", "secret"}


class WorkflowCatalog:
    """Atomic JSON catalog retaining immutable workflow versions."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or Path.home() / ".browser-helper" / "workflows.json")
        self._lock = Lock()
        self._workflows: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            groups = payload.get("workflows", {}) if isinstance(payload, dict) else {}
            self._workflows = {
                str(key): versions
                for key, versions in groups.items()
                if isinstance(versions, list) and versions
            }
        except (OSError, ValueError, TypeError):
            self._workflows = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "workflows": self._workflows}
        fd, temporary = tempfile.mkstemp(prefix="workflows-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _validate(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Workflow must be a JSON object")  # noqa: TRY004
        name = str(payload.get("name", "")).strip()
        if not name or len(name) > 100:
            raise ValueError("name must contain 1 to 100 characters")
        steps = payload.get("steps")
        if not isinstance(steps, list) or not steps or len(steps) > 100:
            raise ValueError("steps must contain between 1 and 100 actions")
        if any(not isinstance(step, dict) or not str(step.get("action", "")).strip() for step in steps):
            raise ValueError("Every step must be an object with an action")

        definitions = payload.get("parameters", [])
        if not isinstance(definitions, list) or len(definitions) > 50:
            raise ValueError("parameters must be an array with at most 50 entries")
        parameters: list[dict[str, Any]] = []
        seen: set[str] = set()
        for definition in definitions:
            if not isinstance(definition, dict):
                raise ValueError("Each parameter must be an object")  # noqa: TRY004
            parameter_name = str(definition.get("name", "")).strip()
            parameter_type = str(definition.get("type", "string")).strip().lower()
            if not _NAME.fullmatch(parameter_name) or parameter_name in seen:
                raise ValueError(f"Invalid or duplicate parameter: {parameter_name}")
            if parameter_type not in _TYPES:
                raise ValueError(f"Unsupported parameter type: {parameter_type}")
            choices = definition.get("choices", [])
            if parameter_type == "enum" and (not isinstance(choices, list) or not choices):
                raise ValueError(f"Enum parameter {parameter_name} requires choices")
            seen.add(parameter_name)
            item = {
                "name": parameter_name,
                "type": parameter_type,
                "required": bool(definition.get("required", False)),
                "description": str(definition.get("description", ""))[:300],
            }
            if "default" in definition and parameter_type != "secret":
                item["default"] = definition["default"]
            if parameter_type == "enum":
                item["choices"] = [str(value)[:100] for value in choices[:50]]
            parameters.append(item)

        placeholders = set(_PLACEHOLDER.findall(json.dumps(steps, ensure_ascii=False)))
        missing = sorted(placeholders - seen)
        if missing:
            raise ValueError(f"Undefined workflow parameters: {', '.join(missing)}")
        return {
            "name": name,
            "description": str(payload.get("description", "")).strip()[:1000],
            "tags": list(dict.fromkeys(str(tag).strip()[:40] for tag in payload.get("tags", []) if str(tag).strip()))[:20],
            "parameters": parameters,
            "steps": copy.deepcopy(steps),
        }

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe = self._validate(payload)
        workflow_id = f"wf_{uuid.uuid4().hex[:16]}"
        return self._append(workflow_id, safe, 1)

    def create_version(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe = self._validate(payload)
        with self._lock:
            versions = self._workflows.get(str(workflow_id)[:100])
            if not versions:
                raise KeyError(workflow_id)
            version = versions[-1]["version"] + 1
        return self._append(str(workflow_id)[:100], safe, version)

    def _append(self, workflow_id: str, safe: dict[str, Any], version: int) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        item = {
            "schema_version": 1,
            "workflow_id": workflow_id,
            "version": version,
            "archived": False,
            **safe,
            "created_at": now,
        }
        with self._lock:
            if version == 1 and any(group[-1]["name"].casefold() == safe["name"].casefold() for group in self._workflows.values()):
                raise ValueError("A workflow with this name already exists")
            self._workflows.setdefault(workflow_id, []).append(item)
            self._save()
        return copy.deepcopy(item)

    def list(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            items = [copy.deepcopy(versions[-1]) for versions in self._workflows.values()]
        if not include_archived:
            items = [item for item in items if not item["archived"]]
        return sorted(items, key=lambda item: item["name"].casefold())

    def get(self, workflow_id: str, version: int | None = None) -> dict[str, Any] | None:
        with self._lock:
            versions = self._workflows.get(str(workflow_id)[:100], [])
            if not versions:
                return None
            item = versions[-1] if version is None else next((entry for entry in versions if entry["version"] == version), None)
            return copy.deepcopy(item) if item else None

    def versions(self, workflow_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._workflows.get(str(workflow_id)[:100], []))

    def archive(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock:
            versions = self._workflows.get(str(workflow_id)[:100])
            if not versions:
                return None
            versions[-1]["archived"] = True
            self._save()
            return copy.deepcopy(versions[-1])

    @staticmethod
    def _coerce(definition: dict[str, Any], value: Any) -> Any:
        kind = definition["type"]
        if kind in {"string", "secret"}:
            return str(value)
        if kind == "number":
            if isinstance(value, bool):
                raise ValueError(f"{definition['name']} must be a number")
            return float(value)
        if kind == "boolean":
            if isinstance(value, bool):
                return value
            if str(value).lower() in {"true", "1", "yes"}:
                return True
            if str(value).lower() in {"false", "0", "no"}:
                return False
            raise ValueError(f"{definition['name']} must be a boolean")
        if kind == "url":
            text = str(value).strip()
            parsed = urlparse(text)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"{definition['name']} must be an HTTP or HTTPS URL")
            return text
        if kind == "enum":
            text = str(value)
            if text not in definition.get("choices", []):
                raise ValueError(f"{definition['name']} must be one of the configured choices")
            return text
        raise ValueError(f"Unsupported parameter type: {kind}")

    def resolve(self, workflow_id: str, values: dict[str, Any], version: int | None = None) -> dict[str, Any]:
        item = self.get(workflow_id, version)
        if item is None:
            raise KeyError(workflow_id)
        values = values if isinstance(values, dict) else {}
        resolved: dict[str, Any] = {}
        recorded: dict[str, Any] = {}
        for definition in item["parameters"]:
            name = definition["name"]
            value = values.get(name, definition.get("default"))
            if value is None and definition["required"]:
                raise ValueError(f"Missing required parameter: {name}")
            if value is None:
                continue
            resolved[name] = self._coerce(definition, value)
            recorded[name] = "[REDACTED]" if definition["type"] == "secret" else resolved[name]

        def replace(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: replace(child) for key, child in value.items()}
            if isinstance(value, list):
                return [replace(child) for child in value]
            if isinstance(value, str):
                exact = _PLACEHOLDER.fullmatch(value)
                if exact and exact.group(1) in resolved:
                    return resolved[exact.group(1)]
                return _PLACEHOLDER.sub(lambda match: str(resolved.get(match.group(1), match.group(0))), value)
            return value

        return {
            "schema_version": 1,
            "workflow_id": item["workflow_id"],
            "version": item["version"],
            "name": item["name"],
            "steps": replace(item["steps"]),
            "recorded_parameters": recorded,
        }
