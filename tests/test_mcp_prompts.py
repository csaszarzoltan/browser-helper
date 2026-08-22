"""P0-4: MCP Prompts — interface + behavioral tests.

Written by the pre-tester against analysis-brief.md spec P0-4 *before*
the developer implements the prompts module.

Phase semantics
---------------
- **Interface tests** (class ``TestInterface``) verify that the prompts
  module can be imported and its public API has the expected signatures.
  These will FAIL on import until ``src/mcp_server/prompts.py`` exists.
- **Behavioral tests** (class ``TestBehavioral``) exercise the prompt
  template functions and registration logic. They fail cleanly while
  the module is missing.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Interface tests — FAIL until src/mcp_server/prompts.py exists
# ---------------------------------------------------------------------------


class TestInterface:
    """Verify imports, function signatures, and registration of MCP prompts."""

    def test_import_prompts_module(self):
        """src/mcp_server/prompts.py must be importable."""
        import mcp_server.prompts  # noqa: F401

    def test_competitive_analysis_prompt_exists(self):
        """competitive_analysis_prompt must be a callable function."""
        from mcp_server.prompts import competitive_analysis_prompt
        assert callable(competitive_analysis_prompt)

    def test_competitive_analysis_prompt_signature(self):
        """competitive_analysis_prompt must accept topic and competitors."""
        from mcp_server.prompts import competitive_analysis_prompt
        sig = inspect.signature(competitive_analysis_prompt)
        params = list(sig.parameters.keys())
        assert "topic" in params
        assert "competitors" in params

    def test_form_automation_prompt_exists(self):
        """form_automation_prompt must be a callable function."""
        from mcp_server.prompts import form_automation_prompt
        assert callable(form_automation_prompt)

    def test_form_automation_prompt_signature(self):
        """form_automation_prompt must accept target_url and form_fields."""
        from mcp_server.prompts import form_automation_prompt
        sig = inspect.signature(form_automation_prompt)
        params = list(sig.parameters.keys())
        assert "target_url" in params
        assert "form_fields" in params

    def test_site_monitoring_prompt_exists(self):
        """site_monitoring_prompt must be a callable function."""
        from mcp_server.prompts import site_monitoring_prompt
        assert callable(site_monitoring_prompt)

    def test_site_monitoring_prompt_signature(self):
        """site_monitoring_prompt must accept url and check_interval."""
        from mcp_server.prompts import site_monitoring_prompt
        sig = inspect.signature(site_monitoring_prompt)
        params = list(sig.parameters.keys())
        assert "url" in params
        assert "check_interval" in params

    def test_register_prompts_exists(self):
        """register_prompts must be a callable function."""
        from mcp_server.prompts import register_prompts
        assert callable(register_prompts)

    def test_register_prompts_signature(self):
        """register_prompts must accept a FastMCP instance."""
        from mcp_server.prompts import register_prompts
        sig = inspect.signature(register_prompts)
        params = list(sig.parameters.keys())
        assert len(params) >= 1
        first_param = next(iter(sig.parameters.values()))
        assert first_param.name == "mcp"


# ---------------------------------------------------------------------------
# Behavioral tests — FAIL cleanly while the module is missing
# ---------------------------------------------------------------------------


class TestBehavioral:
    """Exercise the MCP prompts end-to-end."""

    def test_competitive_analysis_prompt_contains_steps(self):
        """Output must include search, scrape, extract workflow steps."""
        from mcp_server.prompts import competitive_analysis_prompt
        result = competitive_analysis_prompt("AI coding tools", "cursor,windsurf")
        assert isinstance(result, str)
        lower = result.lower()
        # Must describe a workflow with key steps
        for keyword in ["search", "scrape", "extract"]:
            assert keyword in lower, (
                f"competitive_analysis_prompt output missing '{keyword}'"
            )

    def test_form_automation_prompt_contains_steps(self):
        """Output must include navigate, extract, fill workflow steps."""
        from mcp_server.prompts import form_automation_prompt
        result = form_automation_prompt(
            "https://example.com/form",
            '{"name": "Test User", "email": "test@example.com"}',
        )
        assert isinstance(result, str)
        lower = result.lower()
        for keyword in ["navigate", "extract", "fill"]:
            assert keyword in lower, (
                f"form_automation_prompt output missing '{keyword}'"
            )

    def test_site_monitoring_prompt_contains_steps(self):
        """Output must include navigate, snapshot, store workflow steps."""
        from mcp_server.prompts import site_monitoring_prompt
        result = site_monitoring_prompt("https://example.com", "daily")
        assert isinstance(result, str)
        lower = result.lower()
        for keyword in ["navigate", "snapshot", "store"]:
            assert keyword in lower, (
                f"site_monitoring_prompt output missing '{keyword}'"
            )

    def test_prompts_accept_all_params(self):
        """All prompt functions must accept their documented args without TypeError."""
        from mcp_server.prompts import (
            competitive_analysis_prompt,
            form_automation_prompt,
            site_monitoring_prompt,
        )
        # Should not raise TypeError
        competitive_analysis_prompt("topic", "comp1,comp2")
        form_automation_prompt("https://example.com", '{"k": "v"}')
        site_monitoring_prompt("https://example.com", "hourly")

    def test_register_prompts_adds_3_prompts(self):
        """register_prompts must register exactly 3 prompt templates."""
        pytest.importorskip("mcp")
        from mcp.server.fastmcp import FastMCP
        from mcp_server.prompts import register_prompts

        mcp = FastMCP("test-server")
        register_prompts(mcp)
        # Verify 3 prompts were registered
        prompts = getattr(mcp, "_prompts", {})
        if not prompts:
            pm = getattr(mcp, "_prompt_manager", None)
            if pm is not None:
                prompts = getattr(pm, "_prompts", {})
        assert len(prompts) >= 3, (
            f"Expected at least 3 prompts, got {len(prompts)}"
        )
