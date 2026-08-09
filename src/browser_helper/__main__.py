"""Browser Helper top-level CLI (``bh``) — CLI router exposing subcommands.

The ``mcp`` and ``memory`` commands are defined once in their modules
(``mcp_server.cli`` / ``mcp_server.memory.cli``) and registered here so the
``bh`` group and the ``bh-mcp`` / ``browser-helper-mcp`` entry points all
share a single implementation.

Usage::

    bh mcp --help
    bh memory --help
    python -m browser_helper mcp --help
"""

from __future__ import annotations

import click

from mcp_server.cli import mcp
from mcp_server.memory.cli import memory


@click.group(name="bh", help="Browser Helper CLI")
def bh() -> None:
    """Browser Helper command-line interface."""


bh.add_command(mcp)
bh.add_command(memory)


if __name__ == "__main__":
    bh()
