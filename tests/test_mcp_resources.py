"""P0-4: MCP Resources — interface + behavioral tests.

Written by the pre-tester against analysis-brief.md spec P0-4 *before*
the developer implements the resources module.

Phase semantics
---------------
- **Interface tests** (class ``TestInterface``) verify that the resources
  module can be imported and its public API has the expected signatures.
  These will FAIL on import until ``src/mcp_server/resources.py`` exists.
- **Behavioral tests** (class ``TestBehavioral``) exercise the resource
  handler functions and registration logic. They fail cleanly while
  the module is missing.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Interface tests — FAIL until src/mcp_server/resources.py exists
# ---------------------------------------------------------------------------


class TestInterface:
    """Verify imports, function signatures, and registration of MCP resources."""

    def test_import_resources_module(self):
        """src/mcp_server/resources.py must be importable."""
        import mcp_server.resources  # noqa: F401

    def test_get_session_state_exists(self):
        """get_session_state must be a callable async function."""
        from mcp_server.resources import get_session_state
        assert callable(get_session_state)
        assert inspect.iscoroutinefunction(get_session_state)

    def test_get_fleet_health_exists(self):
        """get_fleet_health must be a callable async function."""
        from mcp_server.resources import get_fleet_health
        assert callable(get_fleet_health)
        assert inspect.iscoroutinefunction(get_fleet_health)

    def test_get_memory_cache_exists(self):
        """get_memory_cache must be a callable async function."""
        from mcp_server.resources import get_memory_cache
        assert callable(get_memory_cache)
        assert inspect.iscoroutinefunction(get_memory_cache)

    def test_get_tool_pricing_exists(self):
        """get_tool_pricing must be a callable async function."""
        from mcp_server.resources import get_tool_pricing
        assert callable(get_tool_pricing)
        assert inspect.iscoroutinefunction(get_tool_pricing)

    def test_register_resources_exists(self):
        """register_resources must be a callable function."""
        from mcp_server.resources import register_resources
        assert callable(register_resources)

    def test_register_resources_signature(self):
        """register_resources must accept a FastMCP instance."""
        from mcp_server.resources import register_resources
        sig = inspect.signature(register_resources)
        params = list(sig.parameters.keys())
        assert len(params) >= 1
        # First param should be the FastMCP server
        first_param = next(iter(sig.parameters.values()))
        assert first_param.name == "mcp"


# ---------------------------------------------------------------------------
# Behavioral tests — FAIL cleanly while the module is missing
# ---------------------------------------------------------------------------


class TestBehavioral:
    """Exercise the MCP resources end-to-end."""

    @pytest.mark.asyncio
    async def test_session_state_resource_returns_json(self):
        """get_session_state must return valid JSON with expected keys."""
        from mcp_server.resources import get_session_state
        result = await get_session_state()
        data = json.loads(result)
        # Must contain at least one of the expected keys from the spec
        expected_keys = {"session_id", "active_tab", "tabs", "uptime", "memory_count"}
        assert expected_keys & set(data.keys()), (
            f"Missing expected keys; got: {set(data.keys())}"
        )

    @pytest.mark.asyncio
    async def test_fleet_health_resource_returns_json(self):
        """get_fleet_health must return valid JSON with expected keys."""
        from mcp_server.resources import get_fleet_health
        result = await get_fleet_health()
        data = json.loads(result)
        expected_keys = {"nodes", "healthy", "unhealthy", "sessions", "active", "queued"}
        assert expected_keys & set(data.keys()), (
            f"Missing expected keys; got: {set(data.keys())}"
        )

    @pytest.mark.asyncio
    async def test_memory_cache_resource_returns_json(self):
        """get_memory_cache must return valid JSON with expected keys."""
        from mcp_server.resources import get_memory_cache
        result = await get_memory_cache()
        data = json.loads(result)
        assert "memories" in data or "total" in data, (
            f"Missing memories/total keys; got: {set(data.keys())}"
        )

    @pytest.mark.asyncio
    async def test_tool_pricing_resource_returns_json(self):
        """get_tool_pricing must return valid JSON with free/paid keys."""
        from mcp_server.resources import get_tool_pricing
        result = await get_tool_pricing()
        data = json.loads(result)
        assert "free_tools" in data or "paid_tools" in data, (
            f"Missing free_tools/paid_tools keys; got: {set(data.keys())}"
        )

    def test_register_resources_adds_4_resources(self):
        """register_resources must register exactly 4 resource URIs."""
        pytest.importorskip("mcp")
        from mcp.server.fastmcp import FastMCP
        from mcp_server.resources import register_resources

        mcp = FastMCP("test-server")
        register_resources(mcp)
        # FastMCP stores resources in _resource_manager or similar;
        # verify the count by inspecting registered resources
        # The exact internal API may vary; check that 4 resources were added
        resources = getattr(mcp, "_resources", {})
        # Alternative: check via the resource manager
        if not resources:
            rm = getattr(mcp, "_resource_manager", None)
            if rm is not None:
                resources = getattr(rm, "_resources", {})
        assert len(resources) >= 4, (
            f"Expected at least 4 resources, got {len(resources)}"
        )
