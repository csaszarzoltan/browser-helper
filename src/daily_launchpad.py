"""Privacy-safe aggregation for the daily work launchpad.

This module intentionally exposes only bounded operational metadata. It never
copies run details, workflow step values, environment credentials, URLs, page
content, cookies, or storage values into the launchpad response.
"""
from __future__ import annotations

from typing import Any


def _workflow_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow_id": str(item.get("workflow_id", ""))[:100],
        "name": str(item.get("name", "Untitled workflow"))[:100],
        "version": max(1, int(item.get("version", 1))),
        "step_count": min(len(item.get("steps", [])) if isinstance(item.get("steps"), list) else 0, 100),
        "parameter_count": min(len(item.get("parameters", [])) if isinstance(item.get("parameters"), list) else 0, 50),
    }


def _run_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(item.get("run_id", ""))[:80],
        "operation": str(item.get("operation", "operation"))[:100],
        "status": item.get("status") if item.get("status") in {"error", "incomplete"} else "incomplete",
        "verification": item.get("verification") if item.get("verification") in {"verified", "unverified", "failed"} else "unverified",
        "duration_ms": max(0.0, round(float(item.get("duration_ms", 0)), 2)),
        "timestamp": str(item.get("timestamp", ""))[:40],
    }


def build_daily_launchpad(
    *,
    environments: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    connected: bool,
    tab_count: int,
) -> dict[str, Any]:
    """Build a bounded, deterministic launchpad view from existing stores."""
    active = next((item for item in environments if item.get("active")), None)
    active_environment = None
    if active:
        active_environment = {
            "environment_id": str(active.get("environment_id", ""))[:100],
            "name": str(active.get("name", "Environment"))[:100],
            "runtime": str(active.get("runtime", "visible"))[:30],
        }

    attention = [item for item in runs if item.get("status") in {"error", "incomplete"} or item.get("verification") == "failed"]
    attention_summaries = [_run_summary(item) for item in attention[:5]]
    workflow_summaries = [_workflow_summary(item) for item in workflows[:5]]

    if not connected:
        next_action = {"id": "connect_browser", "label": "Connect a browser", "workspace": "overview", "reason": "Browser actions are unavailable until Chrome is connected."}
    elif attention_summaries:
        next_action = {"id": "review_failures", "label": "Review runs needing attention", "workspace": "diagnostics", "reason": "Resolve recent failures before repeating the workflow."}
    elif not active_environment:
        next_action = {"id": "choose_environment", "label": "Choose an environment", "workspace": "environments", "reason": "A reusable environment makes repeated work safer and faster."}
    elif workflow_summaries:
        next_action = {"id": "run_workflow", "label": "Open saved workflows", "workspace": "automation", "reason": "A saved workflow is ready for review and reuse."}
    else:
        next_action = {"id": "start_browser_task", "label": "Start a browser task", "workspace": "browser", "reason": "Navigate, capture, or observe the active page."}

    return {
        "schema_version": 1,
        "connected": bool(connected),
        "tab_count": max(0, min(int(tab_count), 10000)),
        "active_environment": active_environment,
        "next_action": next_action,
        "summary": {
            "saved_workflows": len(workflows),
            "attention_runs": len(attention),
            "saved_environments": len(environments),
        },
        "recent_workflows": workflow_summaries,
        "attention_runs": attention_summaries,
        "privacy": {
            "page_content_included": False,
            "run_details_included": False,
            "secrets_included": False,
        },
    }
