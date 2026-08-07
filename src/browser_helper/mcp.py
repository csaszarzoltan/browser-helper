"""``python -m browser_helper.mcp`` — MCP server entry (browser-helper).

Bootstrap shim: the repo uses a flat ``src/`` layout (see run.py), so this
module puts ``src/`` on sys.path and delegates to mcp_server.cli.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mcp_server.cli import main  # import after sys.path fix (flat src/ layout)

if __name__ == "__main__":
    raise SystemExit(main())
