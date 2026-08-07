"""Browser Helper top-level CLI (``bh``) — CLI router exposing subcommands.

The ``mcp`` command is defined once in ``mcp_server.cli`` and registered
here so the ``bh`` group and the ``bh-mcp`` / ``browser-helper-mcp`` entry
points all share a single implementation.

Usage::

    bh mcp --help
    python -m browser_helper mcp --help
"""

from __future__ import annotations

import click

from mcp_server.cli import mcp


@click.group(name="bh", help="Browser Helper CLI")
def bh() -> None:
    """Browser Helper command-line interface."""


bh.add_command(mcp)


if __name__ == "__main__":
    bh()
