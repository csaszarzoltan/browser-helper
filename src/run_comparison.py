"""Privacy-safe deterministic comparison of two retained operation runs."""
from __future__ import annotations

from typing import Any

_SAFE_FIELDS = ("operation", "status", "verification")


def _summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(run.get("run_id", ""))[:80],
        "timestamp": run.get("timestamp"),
        "operation": str(run.get("operation", ""))[:100],
        "status": run.get("status", "incomplete"),
        "verification": run.get("verification", "unverified"),
        "duration_ms": round(float(run.get("duration_ms", 0.0)), 2),
    }


def compare_runs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compare bounded metadata only; never repeat run detail text."""
    left_summary = _summary(left)
    right_summary = _summary(right)
    differences = {
        field: {
            "left": left_summary[field],
            "right": right_summary[field],
            "changed": left_summary[field] != right_summary[field],
        }
        for field in _SAFE_FIELDS
    }
    return {
        "schema_version": 1,
        "left": left_summary,
        "right": right_summary,
        "duration_delta_ms": round(right_summary["duration_ms"] - left_summary["duration_ms"], 2),
        "differences": differences,
        "privacy": {
            "run_text_included": False,
            "page_content_included": False,
            "credentials_included": False,
        },
    }
