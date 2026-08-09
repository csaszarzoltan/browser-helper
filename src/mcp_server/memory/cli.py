"""browser-helper memory CLI — persistent agent memory.

Mirrors the hookrelay ``alerts`` CLI pattern: subcommands add|search|list|delete.

The group is registered on the ``bh`` Click group in
``browser_helper/__main__.py`` and is also directly runnable as
``python -m mcp_server.memory.cli`` (subprocess tests use this form).

Each subcommand opens its own :class:`MemoryStore` on the configured DB
path (env override ``BROWSER_HELPER_MEMORY_DB`` wins) so concurrent CLI
invocations never share a connection — WAL mode keeps them safe.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from .config import load_memory_settings
from .store import MemoryStore

_GROUP_HELP = (
    "Persistent agent memory.\n\n"
    "Subcommands: add, search, list, delete. "
    "Store: SQLite at ~/.browser-helper/memory.db (override with "
    "BROWSER_HELPER_MEMORY_DB)."
)


@click.group(name="memory", help=_GROUP_HELP)
def memory() -> None:
    """Browser Helper memory commands."""


def _run(coro) -> Any:
    """Run an async store call to completion and return its result."""
    return asyncio.run(coro)


def _print_entry(entry: dict[str, Any]) -> None:
    click.echo(f"#{entry['id']}  [{entry['key']}]  ({entry['updated_at']})")
    click.echo(f"  {entry['content']}")
    if entry.get("metadata"):
        click.echo(f"  meta: {json.dumps(entry['metadata'], ensure_ascii=False)}")
    click.echo("")


@memory.command(name="add")
@click.option("--key", required=True, help="Memory key (unique identifier)")
@click.option("--content", required=True, help="Memory content text")
@click.option("--metadata", default=None, help="Optional JSON metadata string")
def memory_add(key: str, content: str, metadata: str | None) -> None:
    """Store a memory entry (upsert by key)."""
    settings = load_memory_settings()
    store = MemoryStore(db_path=settings.store_path)

    meta: dict[str, Any] | None = None
    if metadata:
        try:
            parsed = json.loads(metadata)
        except (TypeError, ValueError) as exc:
            raise click.ClickException(f"metadata must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise click.ClickException("metadata must be a JSON object")
        meta = parsed

    entry = _run(store.remember(key=key, content=content, metadata=meta))
    click.echo(
        f"stored #{entry['id']} key={entry['key']!r} "
        f"(updated_at={entry['updated_at']})"
    )


@memory.command(name="search")
@click.option("--query", required=True, help="Search query")
@click.option("--limit", default=10, type=int, help="Max results")
def memory_search(query: str, limit: int) -> None:
    """Search memories by keyword."""
    settings = load_memory_settings()
    store = MemoryStore(db_path=settings.store_path)
    entries = _run(store.recall(query=query, limit=limit))
    if not entries:
        click.echo("no matches")
        return
    click.echo(f"{len(entries)} match(es):\n")
    for entry in entries:
        _print_entry(entry)


@memory.command(name="list")
@click.option("--filter", "filter_expr", default=None, help="Filter by metadata prefix")
def memory_list(filter_expr: str | None) -> None:
    """List all stored memories."""
    settings = load_memory_settings()
    store = MemoryStore(db_path=settings.store_path)
    entries = _run(store.list_entries(filter_expr=filter_expr))
    if not entries:
        click.echo("no memories stored")
        return
    click.echo(f"{len(entries)} entr(ies):\n")
    for entry in entries:
        _print_entry(entry)


@memory.command(name="delete")
@click.option("--key-or-id", required=True, help="Key or ID of memory to delete")
def memory_delete(key_or_id: str) -> None:
    """Delete a memory entry."""
    settings = load_memory_settings()
    store = MemoryStore(db_path=settings.store_path)
    removed = _run(store.forget(key_or_id))
    if removed:
        click.echo(f"deleted {key_or_id!r}")
    else:
        click.echo(f"nothing to delete for {key_or_id!r}")


if __name__ == "__main__":
    memory(prog_name="memory")
