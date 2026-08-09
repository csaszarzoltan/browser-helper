"""browser-helper memory CLI — pre-dev stub.

Mirrors the hookrelay ``alerts`` CLI pattern: subcommands add|search|list|delete.
"""

from __future__ import annotations

import click


@click.group(name="memory", help="Persistent agent memory")
def memory() -> None:
    """Browser Helper memory commands."""


@memory.command(name="add")
@click.option("--key", required=True, help="Memory key (unique identifier)")
@click.option("--content", required=True, help="Memory content text")
@click.option("--metadata", default=None, help="Optional JSON metadata string")
def memory_add(key: str, content: str, metadata: str | None) -> None:
    """Store a memory entry (upsert by key)."""
    raise NotImplementedError


@memory.command(name="search")
@click.option("--query", required=True, help="Search query")
@click.option("--limit", default=10, type=int, help="Max results")
def memory_search(query: str, limit: int) -> None:
    """Search memories by keyword."""
    raise NotImplementedError


@memory.command(name="list")
@click.option("--filter", "filter_expr", default=None, help="Filter by metadata prefix")
def memory_list(filter_expr: str | None) -> None:
    """List all stored memories."""
    raise NotImplementedError


@memory.command(name="delete")
@click.option("--key-or-id", required=True, help="Key or ID of memory to delete")
def memory_delete(key_or_id: str) -> None:
    """Delete a memory entry."""
    raise NotImplementedError
