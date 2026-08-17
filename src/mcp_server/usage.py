"""MCP server usage — SQLite-backed usage tracking and analytics.

Tracks tool call counts, revenue, errors, and per-tool statistics.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class UsageStats:
    """Aggregated usage statistics for a single tool."""

    tool_name: str
    call_count: int
    paid_count: int
    free_count: int
    error_count: int
    total_revenue_cents: int
    last_called_at: str


class UsageTracker:
    """SQLite-backed tool usage tracker.

    Records each tool call and provides aggregated statistics.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                is_paid INTEGER NOT NULL DEFAULT 0,
                price_cents INTEGER NOT NULL DEFAULT 0,
                error INTEGER NOT NULL DEFAULT 0,
                called_at TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def record_call(
        self,
        tool_name: str,
        is_paid: bool = False,
        price_cents: int = 0,
        error: bool = False,
    ) -> None:
        """Record a single tool call.

        Args:
            tool_name: Name of the tool that was called.
            is_paid: Whether this was a paid call.
            price_cents: Price in cents (0 for free calls).
            error: Whether this call resulted in an error.
        """
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO tool_calls (tool_name, is_paid, price_cents, error, called_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (tool_name, int(is_paid), price_cents, int(error), now),
        )
        self._conn.commit()

    def get_stats(self, tool_name: str | None = None) -> list[UsageStats]:
        """Get aggregated usage statistics.

        Args:
            tool_name: Filter to a specific tool, or None for all tools.

        Returns:
            List of UsageStats, one per tool.
        """
        if tool_name:
            rows = self._conn.execute(
                "SELECT tool_name, "
                "  COUNT(*) as call_count, "
                "  SUM(CASE WHEN is_paid = 1 THEN 1 ELSE 0 END) as paid_count, "
                "  SUM(CASE WHEN is_paid = 0 THEN 1 ELSE 0 END) as free_count, "
                "  SUM(error) as error_count, "
                "  SUM(CASE WHEN is_paid = 1 THEN price_cents ELSE 0 END) as total_revenue_cents, "
                "  MAX(called_at) as last_called_at "
                "FROM tool_calls WHERE tool_name = ? GROUP BY tool_name",
                (tool_name,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT tool_name, "
                "  COUNT(*) as call_count, "
                "  SUM(CASE WHEN is_paid = 1 THEN 1 ELSE 0 END) as paid_count, "
                "  SUM(CASE WHEN is_paid = 0 THEN 1 ELSE 0 END) as free_count, "
                "  SUM(error) as error_count, "
                "  SUM(CASE WHEN is_paid = 1 THEN price_cents ELSE 0 END) as total_revenue_cents, "
                "  MAX(called_at) as last_called_at "
                "FROM tool_calls GROUP BY tool_name"
            ).fetchall()
        return [
            UsageStats(
                tool_name=row["tool_name"],
                call_count=row["call_count"],
                paid_count=row["paid_count"] or 0,
                free_count=row["free_count"] or 0,
                error_count=row["error_count"] or 0,
                total_revenue_cents=row["total_revenue_cents"] or 0,
                last_called_at=row["last_called_at"],
            )
            for row in rows
        ]

    def get_total_revenue(self) -> int:
        """Get total revenue in cents from all paid calls."""
        result = self._conn.execute(
            "SELECT COALESCE(SUM(price_cents), 0) as total FROM tool_calls WHERE is_paid = 1"
        ).fetchone()
        return result["total"] if result else 0

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
