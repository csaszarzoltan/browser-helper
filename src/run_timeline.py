"""Bounded, privacy-safe in-memory timeline for browser operations."""
from __future__ import annotations

import re
import uuid
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:access_?token|api_?key|password|secret|session|token)\s*[=:]\s*)[^\s&,;]+"),
)


def redact_detail(value: object, limit: int = 500) -> str:
    text = str(value or "")[:limit]
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


class RunStore:
    """Thread-safe newest-first operation timeline with bounded retention."""

    def __init__(self, max_runs: int = 100):
        if max_runs < 1 or max_runs > 1000:
            raise ValueError("max_runs must be between 1 and 1000")
        self._runs: deque[dict[str, Any]] = deque(maxlen=max_runs)
        self._lock = Lock()

    def record(
        self,
        operation: str,
        status: str,
        duration_ms: float,
        details: object = "",
        *,
        verification: str = "unverified",
    ) -> dict[str, Any]:
        item = {
            "schema_version": 1,
            "run_id": f"run_{uuid.uuid4().hex[:16]}",
            "timestamp": datetime.now(UTC).isoformat(),
            "operation": str(operation)[:100],
            "status": status if status in {"success", "error", "incomplete"} else "incomplete",
            "duration_ms": round(float(duration_ms), 2),
            "verification": verification if verification in {"verified", "unverified", "failed"} else "unverified",
            "details": redact_detail(details),
        }
        with self._lock:
            self._runs.appendleft(item)
        return dict(item)

    def list_runs(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._lock:
            items = list(self._runs)
        if status in {"success", "error", "incomplete"}:
            items = [item for item in items if item["status"] == status]
        return [dict(item) for item in items[:safe_limit]]

    def get(self, run_id: str) -> dict[str, Any] | None:
        """Return a defensive copy of one run, or ``None`` when absent."""
        safe_id = str(run_id)[:80]
        with self._lock:
            for item in self._runs:
                if item["run_id"] == safe_id:
                    return dict(item)
        return None

    def clear(self) -> int:
        with self._lock:
            count = len(self._runs)
            self._runs.clear()
        return count
