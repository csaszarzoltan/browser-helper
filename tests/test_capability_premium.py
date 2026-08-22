"""P0-1: Premium tier capability flag — interface + behavioral tests.

Written by the pre-tester against analysis-brief.md spec P0-1 *before*
the developer implements the premium tier feature.

Phase semantics
---------------
- **Interface tests** (class ``TestInterface``) verify imports, dataclass
  fields, new enum values, and function signatures. They must PASS
  immediately against the current codebase (Capability dataclass exists;
  premium field and CapabilityTier will be RED until added).
- **Behavioral tests** (class ``TestBehavioral``) exercise the premium
  filter logic (``filter_free_tools``, ``build_tool_defs(premium_only)``).
  They FAIL cleanly while the feature is missing.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from capability_registry import Capability, CapabilityRegistry, CapabilityStatus

# ---------------------------------------------------------------------------
# Interface tests — must PASS immediately
# ---------------------------------------------------------------------------


class TestInterface:
    """Verify the public contract of the premium tier feature."""

    def test_capability_is_frozen_dataclass(self):
        """Capability must remain a frozen dataclass."""
        from dataclasses import is_dataclass

        assert is_dataclass(Capability)
        # frozen=True is enforced by dataclass machinery; verify immutability
        cap = Capability(
            "test", "Test", "Area", CapabilityStatus.READY, "desc"
        )
        with pytest.raises(AttributeError):
            cap.premium = True  # type: ignore[misc]

    def test_capability_has_premium_field(self):
        """Capability must declare a 'premium' field (default False)."""
        field_names = {f.name for f in fields(Capability)}
        assert "premium" in field_names, (
            f"Capability missing 'premium' field; found: {field_names}"
        )

    def test_capability_premium_default_is_false(self):
        """premium must default to False for backward compat."""
        cap = Capability(
            "test", "Test", "Area", CapabilityStatus.READY, "desc"
        )
        assert cap.premium is False

    def test_premium_flag_appears_in_as_dict(self):
        """as_dict() must include the premium key."""
        cap = Capability(
            "test", "Test", "Area", CapabilityStatus.READY, "desc",
            premium=True,
        )
        d = cap.as_dict()
        assert "premium" in d
        assert d["premium"] is True

    def test_premium_flag_in_as_dict_default(self):
        """as_dict() on a default Capability shows premium=False."""
        cap = Capability(
            "test", "Test", "Area", CapabilityStatus.READY, "desc"
        )
        d = cap.as_dict()
        assert d["premium"] is False

    def test_capability_tier_enum_exists(self):
        """CapabilityTier enum must exist with FREE and PREMIUM values."""
        from capability_registry import CapabilityTier
        assert CapabilityTier.FREE.value == "free"
        assert CapabilityTier.PREMIUM.value == "premium"

    def test_filter_free_tools_function_exists(self):
        """filter_free_tools must be importable from registry."""
        from mcp_server.registry import filter_free_tools
        assert callable(filter_free_tools)

    def test_filter_free_tools_signature(self):
        """filter_free_tools must accept a ToolDefRegistry and return one."""
        from mcp_server.registry import filter_free_tools
        sig = inspect.signature(filter_free_tools)
        params = list(sig.parameters.keys())
        assert len(params) >= 1
        assert sig.return_annotation is not inspect.Parameter.empty


# ---------------------------------------------------------------------------
# Behavioral tests — must FAIL cleanly while the feature is missing
# ---------------------------------------------------------------------------


class TestBehavioral:
    """Exercise the premium tier feature end-to-end.

    Tests that import ``filter_free_tools`` or ``build_tool_defs`` with
    ``premium_only`` will fail with an ``ImportError`` or ``TypeError``
    until the developer adds the feature.
    """

    def _make_premium_registry(self):
        """Build a CapabilityRegistry with some premium capabilities."""
        caps = [
            Capability(
                "browser.core", "Browser", "Live",
                CapabilityStatus.READY, "Core browser", premium=False,
            ),
            Capability(
                "agent.search", "Search", "Agent",
                CapabilityStatus.READY, "Web search", premium=True,
            ),
            Capability(
                "anti_detection.compositor", "Stealth", "Environments",
                CapabilityStatus.EXPERIMENTAL, "Anti-detect", premium=True,
            ),
        ]
        return CapabilityRegistry(caps)

    def test_premium_capability_surfaces_in_full_registry(self):
        """Premium capabilities must appear in the full (unfiltered) registry."""
        from mcp_server.registry import build_tool_defs

        reg = self._make_premium_registry()
        tools = build_tool_defs(registry=reg)
        names = [t.name for t in tools]
        # search maps to agent.search (premium) — must be present
        assert "search" in names

    def test_premium_capability_excluded_from_free_registry(self):
        """filter_free_tools must remove tools backed by premium capabilities."""
        from mcp_server.registry import filter_free_tools

        reg = self._make_premium_registry()
        filtered = filter_free_tools(reg)
        names = [t.name for t in filtered]
        assert "search" not in names, (
            "search (agent.search, premium) should be excluded from free tools"
        )

    def test_free_tools_remain_after_filter(self):
        """filter_free_tools must keep non-premium tools intact."""
        from mcp_server.registry import filter_free_tools

        reg = self._make_premium_registry()
        filtered = filter_free_tools(reg)
        names = [t.name for t in filtered]
        # navigate maps to browser.core (not premium) — must remain
        assert "navigate" in names

    def test_build_tool_defs_premium_only_flag(self):
        """build_tool_defs(premium_only=True) returns only premium tools."""
        from mcp_server.registry import build_tool_defs

        reg = self._make_premium_registry()
        tools = build_tool_defs(registry=reg, premium_only=True)
        names = [t.name for t in tools]
        assert "search" in names
        assert "navigate" not in names

    def test_premium_tools_count_in_default_registry(self):
        """Default registry should have exactly 2 premium tools marked."""
        from mcp_server.registry import build_tool_defs

        reg = CapabilityRegistry.default()
        # After implementation, anti_detection.compositor and agent.search
        # should be marked premium. build_tool_defs(default) returns all tools;
        # filter_free_tools returns only non-premium. The difference is the
        # premium count.
        all_tools = build_tool_defs(registry=reg)
        from mcp_server.registry import filter_free_tools
        free_tools = filter_free_tools(reg)
        premium_count = len(list(all_tools)) - len(list(free_tools))
        assert premium_count == 2, (
            f"Expected 2 premium tools (anti_detection.compositor + agent.search), "
            f"got {premium_count}"
        )
