"""Deterministic, non-automatic recovery guidance for operation runs."""
from __future__ import annotations

from typing import Any

_READ_ONLY_OPERATIONS = {
    "agent_observe",
    "capabilities",
    "get_text",
    "health",
    "page_analyze",
    "page_outline",
    "screenshot",
    "status",
    "tabs",
}


class RecoveryAdvisor:
    """Translate safe run metadata into bounded, user-readable recovery guidance."""

    def advise(self, run: dict[str, Any]) -> dict[str, Any]:
        operation = str(run.get("operation") or "unknown")[:100]
        status = str(run.get("status") or "incomplete")
        verification = str(run.get("verification") or "unverified")
        normalized = operation.removeprefix("ws:").lower()
        read_only = normalized in _READ_ONLY_OPERATIONS or any(
            marker in normalized for marker in ("observe", "analyze", "screenshot", "status")
        )

        if verification == "failed":
            return {
                "schema_version": 1,
                "category": "verification_failure",
                "retry_safety": "review",
                "recommended_action": "inspect_evidence",
                "summary": "The command executed, but explicit evidence did not confirm the expected outcome.",
                "steps": [
                    "Inspect the run evidence and current page state.",
                    "Refresh the page observation or screenshot before changing the target.",
                    "Review possible side effects before retrying the operation.",
                ],
                "automatic_retry": False,
            }

        if status == "error":
            safety = "safe" if read_only else "review"
            return {
                "schema_version": 1,
                "category": "execution_failure",
                "retry_safety": safety,
                "recommended_action": "retry" if read_only else "review_then_retry",
                "summary": "The operation did not complete successfully.",
                "steps": [
                    "Check the active browser connection and execution context.",
                    "Confirm that the target tab or session is still available.",
                    "Retry only after reviewing whether the operation may have side effects.",
                ],
                "automatic_retry": False,
            }

        if verification == "unverified":
            return {
                "schema_version": 1,
                "category": "evidence_missing",
                "retry_safety": "review",
                "recommended_action": "verify",
                "summary": "The command completed without supported proof of the user goal.",
                "steps": [
                    "Capture a fresh screenshot or semantic observation.",
                    "Check the expected URL, text, element, or state change.",
                    "Do not repeat a mutating action until its side effects are understood.",
                ],
                "automatic_retry": False,
            }

        return {
            "schema_version": 1,
            "category": "none",
            "retry_safety": "not_needed",
            "recommended_action": "none",
            "summary": "The operation has explicit evidence of the expected outcome.",
            "steps": [],
            "automatic_retry": False,
        }
