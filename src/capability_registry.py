"""Truthful, privacy-safe product capability readiness registry.

This registry is intentionally declarative. It gives the API, dashboard, tests,
and documentation one vocabulary for distinguishing supported, experimental,
and unavailable product areas without exposing configuration secrets.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum


class CapabilityStatus(StrEnum):
    READY = "ready"
    EXPERIMENTAL = "experimental"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Capability:
    id: str
    title: str
    area: str
    status: CapabilityStatus
    description: str
    reason: str | None = None
    action: str | None = None

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class CapabilityRegistry:
    """Immutable collection with deterministic, versioned serialization."""

    def __init__(self, capabilities: Iterable[Capability]):
        items = tuple(sorted(capabilities, key=lambda item: item.id))
        if len({item.id for item in items}) != len(items):
            raise ValueError("Capability IDs must be unique")
        self.capabilities = items

    @classmethod
    def default(cls) -> CapabilityRegistry:
        return cls(
            (
                Capability(
                    "agent.semantic", "Semantic agent tools", "Agent Tools",
                    CapabilityStatus.READY,
                    "Observe, act, extract, and verify with accessibility-based references.",
                    action="Open Agent Tools",
                ),
                Capability(
                    "agent.search", "One-call web search", "Agent Tools",
                    CapabilityStatus.READY,
                    "Search an engine (perplexity/google/ddg/bing) and return the answer text in one call.",
                    action="Run Search",
                ),
                Capability(
                    "agent.flow", "E2E test flows", "Agent Tools",
                    CapabilityStatus.READY,
                    "Run ordered multi-step browser test flows with per-step reports.",
                    action="Run Flow",
                ),
                Capability(
                    "anti_detection.compositor", "Anti-detection composition", "Environments",
                    CapabilityStatus.EXPERIMENTAL,
                    "Compose fingerprint, proxy, stealth, and session policies.",
                    "The supplied compositor and fingerprint database still contain pre-development paths.",
                    "Review experimental API",
                ),
                Capability(
                    "behavioral.scroll", "Behavioral input middleware", "Automation",
                    CapabilityStatus.EXPERIMENTAL,
                    "Human-like scrolling and typing middleware.",
                    "Behavioral scroll and typing modules contain explicit NotImplementedError paths.",
                    "Use stable script actions",
                ),
                Capability(
                    "browser.core", "Visible browser control", "Live Browser",
                    CapabilityStatus.READY,
                    "Connect, navigate, capture, inspect, and manage the active Chrome tab.",
                    action="Open Live Browser",
                ),
                Capability(
                    "cloud.camofox", "Camofox cloud provider", "Environments",
                    CapabilityStatus.UNAVAILABLE,
                    "Launch Firefox-compatible managed browser sessions.",
                    "The provider is an explicit stub and is excluded from production use.",
                    "Use Browserbase, Steel, or local Chrome",
                ),
                Capability(
                    "dashboard.assistants", "Daily workflow assistants", "Dashboard",
                    CapabilityStatus.READY,
                    "Guided navigation, workflow, session, diagnostics, tab, network, and cookie helpers.",
                    action="Open Overview",
                ),
                Capability(
                    "diagnostics.privacy", "Privacy-safe diagnostics", "Diagnostics",
                    CapabilityStatus.READY,
                    "Filter and export bounded, redacted operation, network, and cookie metadata.",
                    action="Open Diagnostics",
                ),
                Capability(
                    "diagnostics.cookies", "Cookie export", "Diagnostics",
                    CapabilityStatus.READY,
                    "Export a session's full cookie jar as JSON via CDP Network.getAllCookies.",
                    action="Open Diagnostics",
                ),
                Capability(
                    "memory.persistent", "Persistent agent memory", "Agent Tools",
                    CapabilityStatus.READY,
                    "Remember, recall, forget, and list persistent memories across sessions.",
                    action="Open Memory",
                ),
                Capability(
                    "workflow.local", "Local workflow assistant", "Automation",
                    CapabilityStatus.READY,
                    "Validate, format, draft, and run bounded JSON action workflows.",
                    action="Open Automation",
                ),
            )
        )

    def as_dict(self) -> dict[str, object]:
        counts = {status.value: 0 for status in CapabilityStatus}
        for capability in self.capabilities:
            counts[capability.status.value] += 1
        return {
            "schema_version": 1,
            "summary": {"total": len(self.capabilities), **counts},
            "capabilities": [item.as_dict() for item in self.capabilities],
        }
