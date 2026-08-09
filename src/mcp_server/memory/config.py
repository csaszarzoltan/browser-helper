"""MemoryStore settings — mirrors src/mcp_server/config.py pattern.

Owns: ``MemorySettings`` dataclass (store path, search limit, vector mode)
and ``load_memory_settings()`` with CLI > env > settings.json > defaults
precedence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_DB = str(Path.home() / ".browser-helper" / "memory.db")
"""Default SQLite DB location for the memory store."""

#: Env var overrides — mirrors the MCP_ENABLED / MCP_PORT convention.
_ENV_KEYS = {
    "store_path": "BROWSER_HELPER_MEMORY_DB",
    "search_limit": "BROWSER_HELPER_MEMORY_SEARCH_LIMIT",
    "vector_mode": "BROWSER_HELPER_MEMORY_VECTOR",
}


@dataclass
class MemorySettings:
    """Memory store configuration."""

    store_path: str = DEFAULT_MEMORY_DB
    search_limit: int = 10
    vector_mode: bool = False


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def load_memory_settings(overrides: dict[str, Any] | None = None) -> MemorySettings:
    """Load memory settings (CLI > env > settings > defaults).

    Precedence mirrors ``load_mcp_settings`` (CLI > env > settings.json >
    dataclass defaults). ``overrides`` wins over everything; env vars fill in
    values not overridden; a SettingsManager key is the next fallback.
    """
    overrides = overrides or {}

    def _pick(name: str, default: Any) -> Any:
        if name in overrides and overrides[name] is not None:
            return overrides[name]
        env_key = _ENV_KEYS.get(name)
        if env_key and env_key in os.environ and os.environ[env_key] != "":
            return os.environ[env_key]
        try:
            from settings_manager import SettingsManager

            sm = SettingsManager()
            return sm.get(name, default)
        except Exception:  # noqa: BLE001 — settings lookup must never break the memory feature
            return default

    return MemorySettings(
        store_path=str(_pick("store_path", DEFAULT_MEMORY_DB)),
        search_limit=int(_pick("search_limit", 10)),
        vector_mode=_as_bool(_pick("vector_mode", False)),
    )
