"""Privacy-safe persistent recipes for repeatable browser environments."""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

_ALLOWED_RUNTIMES = {"visible", "headless", "browserbase", "steel"}
_ALLOWED_PROXY_STRATEGIES = {None, "round-robin", "random", "sticky", "by-tag", "health-check"}
_SECRET_KEY = re.compile(r"(?i)(secret|password|token|api_?key|authorization|cookie|credential)")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class EnvironmentStore:
    """Small JSON store with atomic writes and no credential fields."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or Path.home() / ".browser-helper" / "environments.json")
        self._lock = Lock()
        self._items: dict[str, dict[str, Any]] = {}
        self._active_id: str | None = None
        self._load()

    @staticmethod
    def _validate(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Environment must be a JSON object")  # noqa: TRY004
        forbidden = [str(key) for key in payload if _SECRET_KEY.search(str(key))]
        if forbidden:
            raise ValueError("Credential and secret fields are not allowed in environment recipes")
        name = str(payload.get("name", "")).strip()
        if not name or len(name) > 100:
            raise ValueError("name must contain 1 to 100 characters")
        runtime = str(payload.get("runtime", "visible")).strip().lower()
        if runtime not in _ALLOWED_RUNTIMES:
            raise ValueError(f"runtime must be one of: {', '.join(sorted(_ALLOWED_RUNTIMES))}")
        proxy_strategy = payload.get("proxy_strategy")
        if proxy_strategy not in _ALLOWED_PROXY_STRATEGIES:
            raise ValueError("proxy_strategy is not supported")

        def optional_ref(key: str) -> str | None:
            value = payload.get(key)
            if value in (None, ""):
                return None
            value = str(value).strip()
            if not _SAFE_ID.fullmatch(value):
                raise ValueError(f"{key} contains unsupported characters")
            return value

        tags = payload.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 20:
            raise ValueError("tags must be an array with no more than 20 entries")
        safe_tags = []
        for tag in tags:
            value = str(tag).strip()
            if value and value not in safe_tags:
                if len(value) > 40:
                    raise ValueError("tags must be 40 characters or fewer")
                safe_tags.append(value)

        return {
            "name": name,
            "description": str(payload.get("description", "")).strip()[:500],
            "runtime": runtime,
            "profile": optional_ref("profile"),
            "proxy_strategy": proxy_strategy,
            "proxy_group": optional_ref("proxy_group"),
            "fingerprint_template": optional_ref("fingerprint_template"),
            "provider": optional_ref("provider"),
            "tags": safe_tags,
        }

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data.get("environments", []) if isinstance(data, dict) else []
            self._items = {
                item["environment_id"]: item
                for item in items
                if isinstance(item, dict) and _SAFE_ID.fullmatch(str(item.get("environment_id", "")))
            }
            active = data.get("active_environment_id") if isinstance(data, dict) else None
            self._active_id = active if active in self._items else None
        except (OSError, ValueError, TypeError):
            self._items = {}
            self._active_id = None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "active_environment_id": self._active_id,
            "environments": sorted(self._items.values(), key=lambda item: (item["name"].lower(), item["environment_id"])),
        }
        fd, temp_name = tempfile.mkstemp(prefix="environments-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe = self._validate(payload)
        now = datetime.now(UTC).isoformat()
        item = {
            "schema_version": 1,
            "environment_id": f"env_{uuid.uuid4().hex[:16]}",
            **safe,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            if any(existing["name"].casefold() == safe["name"].casefold() for existing in self._items.values()):
                raise ValueError("An environment with this name already exists")
            self._items[item["environment_id"]] = item
            self._save()
        return dict(item)

    @property
    def active_id(self) -> str | None:
        with self._lock:
            return self._active_id

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {**item, "active": item["environment_id"] == self._active_id}
                for item in sorted(self._items.values(), key=lambda value: value["name"].lower())
            ]

    def get(self, environment_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(str(environment_id)[:100])
            return ({**item, "active": environment_id == self._active_id} if item else None)

    def activate(self, environment_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(str(environment_id)[:100])
            if item is None:
                return None
            self._active_id = item["environment_id"]
            self._save()
            return {**item, "active": True}

    def delete(self, environment_id: str) -> str:
        with self._lock:
            safe_id = str(environment_id)[:100]
            if safe_id == self._active_id:
                return "active"
            if safe_id not in self._items:
                return "missing"
            del self._items[safe_id]
            self._save()
            return "deleted"
