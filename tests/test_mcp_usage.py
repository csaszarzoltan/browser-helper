"""P1-2: Usage tracking + analytics — interface + behavioral tests.

Written by the pre-tester against analysis-brief.md spec P1-2 *before*
the developer implements the usage module.

Phase semantics
---------------
- **Interface tests** (class ``TestInterface``) verify that the usage
  module can be imported and its public API has the expected signatures.
  These will FAIL on import until ``src/mcp_server/usage.py`` exists.
- **Behavioral tests** (class ``TestBehavioral``) exercise the SQLite-backed
  UsageTracker: recording calls, revenue aggregation, error tracking, and
  tool filtering. They fail cleanly while the module is missing.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Interface tests — FAIL until src/mcp_server/usage.py exists
# ---------------------------------------------------------------------------


class TestInterface:
    """Verify imports, dataclass fields, and method signatures of the usage module."""

    def test_import_usage_module(self):
        """src/mcp_server/usage.py must be importable."""
        import mcp_server.usage  # noqa: F401

    def test_usage_stats_dataclass_exists(self):
        """UsageStats must be a dataclass."""
        from dataclasses import is_dataclass

        from mcp_server.usage import UsageStats
        assert is_dataclass(UsageStats)

    def test_usage_stats_fields(self):
        """UsageStats must have the required fields."""
        from mcp_server.usage import UsageStats
        names = {f.name for f in fields(UsageStats)}
        required = {
            "tool_name", "call_count", "paid_count",
            "free_count", "error_count", "total_revenue_cents",
            "last_called_at",
        }
        assert required.issubset(names), (
            f"Missing fields: {required - names}"
        )

    def test_usage_tracker_class_exists(self):
        """UsageTracker must be a class."""
        from mcp_server.usage import UsageTracker
        assert inspect.isclass(UsageTracker)

    def test_usage_tracker_init_signature(self):
        """UsageTracker.__init__ must accept db_path."""
        from mcp_server.usage import UsageTracker
        sig = inspect.signature(UsageTracker.__init__)
        params = list(sig.parameters.keys())
        assert "db_path" in params or "self" in params

    def test_usage_tracker_record_call_exists(self):
        """UsageTracker.record_call must be a callable method."""
        from mcp_server.usage import UsageTracker
        assert callable(UsageTracker.record_call)

    def test_usage_tracker_record_call_signature(self):
        """record_call must accept tool_name, is_paid, price_cents, error."""
        from mcp_server.usage import UsageTracker
        sig = inspect.signature(UsageTracker.record_call)
        params = list(sig.parameters.keys())
        assert "tool_name" in params
        assert "is_paid" in params

    def test_usage_tracker_get_stats_exists(self):
        """UsageTracker.get_stats must be a callable method."""
        from mcp_server.usage import UsageTracker
        assert callable(UsageTracker.get_stats)

    def test_usage_tracker_get_total_revenue_exists(self):
        """UsageTracker.get_total_revenue must be a callable method."""
        from mcp_server.usage import UsageTracker
        assert callable(UsageTracker.get_total_revenue)


# ---------------------------------------------------------------------------
# Behavioral tests — FAIL cleanly while the module is missing
# ---------------------------------------------------------------------------


class TestBehavioral:
    """Exercise the UsageTracker end-to-end with in-memory SQLite."""

    @pytest.fixture
    def tracker(self):
        """Create a fresh in-memory UsageTracker for each test."""
        from mcp_server.usage import UsageTracker
        return UsageTracker(db_path=":memory:")

    def test_record_and_retrieve_call(self, tracker):
        """Record one call and verify it appears in get_stats."""
        tracker.record_call("navigate", is_paid=False)
        stats = tracker.get_stats(tool_name="navigate")
        assert len(stats) == 1
        assert stats[0].tool_name == "navigate"
        assert stats[0].call_count == 1

    def test_paid_call_increments_revenue(self, tracker):
        """A paid call must add its price to total_revenue_cents."""
        tracker.record_call("search", is_paid=True, price_cents=3)
        assert tracker.get_total_revenue() == 3

    def test_free_call_no_revenue(self, tracker):
        """A free call must not change revenue."""
        tracker.record_call("navigate", is_paid=False, price_cents=0)
        assert tracker.get_total_revenue() == 0

    def test_error_call_tracked(self, tracker):
        """error=True must increment the error_count."""
        tracker.record_call("search", is_paid=True, price_cents=3, error=True)
        stats = tracker.get_stats(tool_name="search")
        assert len(stats) == 1
        assert stats[0].error_count == 1

    def test_tool_filter(self, tracker):
        """get_stats(tool_name=X) must filter to only that tool."""
        tracker.record_call("navigate", is_paid=False)
        tracker.record_call("search", is_paid=True, price_cents=3)
        stats = tracker.get_stats(tool_name="search")
        assert len(stats) == 1
        assert stats[0].tool_name == "search"

    def test_multiple_calls_aggregate(self, tracker):
        """10 calls to the same tool must aggregate into one stats record."""
        for _ in range(10):
            tracker.record_call("search", is_paid=True, price_cents=3)
        stats = tracker.get_stats(tool_name="search")
        assert len(stats) == 1
        assert stats[0].call_count == 10
        assert stats[0].paid_count == 10
        assert stats[0].total_revenue_cents == 30
