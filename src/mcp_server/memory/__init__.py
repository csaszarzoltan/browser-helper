"""MCP memory submodule — persistent agent memory for browser-helper.

Provides: MemoryStore (SQLite + FTS5), MCP tool handlers, CLI surface.
"""

from .store import MemoryStore
from .types import MemoryEntry

__all__ = ["MemoryEntry", "MemoryStore"]
