"""Memory entry dataclass — pre-dev stub.

Target shape for each stored memory entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryEntry:
    """A single memory entry persisted in the store."""

    key: str
    content: str
    id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    source_session: str = ""
