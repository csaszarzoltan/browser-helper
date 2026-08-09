"""MemoryStore settings — pre-dev stub.

Mirrors src/mcp_server/config.py pattern: store path, search limit, vector mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MemorySettings:
    """Memory store configuration."""

    store_path: str = ""
    search_limit: int = 10
    vector_mode: bool = False


def load_memory_settings(overrides: dict[str, Any] | None = None) -> MemorySettings:
    """Load memory settings (CLI > env > settings > defaults)."""
    return MemorySettings()
