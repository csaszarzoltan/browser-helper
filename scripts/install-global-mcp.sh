#!/usr/bin/env bash
# Register this checkout's MCP server in the user's Codex configuration.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$repo_root/.venv/bin/python"

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--dry-run" ) ]]; then
    echo "Usage: $0 [--dry-run]" >&2
    exit 2
fi
if [[ ! -x "$python_bin" ]]; then
    echo "Missing virtual environment: $python_bin" >&2
    echo "Create it and install the project's MCP dependencies first." >&2
    exit 1
fi
command -v codex >/dev/null || { echo "Codex CLI is required." >&2; exit 1; }
PYTHONPATH="$repo_root/src" "$python_bin" -c \
    'from mcp.server.fastmcp import FastMCP; from mcp_server.cli import app'

# The Click entry point prints its banner to stderr, preserving JSON-RPC stdout.
# Absolute paths make the server launchable from any project's working directory.
install_command=(codex mcp add browser-helper --env "PYTHONPATH=$repo_root/src"
    -- "$python_bin" -m mcp_server.cli mcp --stdio)

if [[ "${1:-}" == "--dry-run" ]]; then
    printf '%q ' "${install_command[@]}"
    printf '\n'
    exit 0
fi

"${install_command[@]}"
codex mcp get browser-helper
echo "Browser Helper registered for all Codex projects. Restart your Codex session."
