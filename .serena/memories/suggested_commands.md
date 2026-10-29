# Suggested commands (Linux)

- Setup: `python -m venv .venv && .venv/bin/pip install -e ".[dev,mcp]"` (same as CI).
- Run API + dashboard: `.venv/bin/python run.py` (`--port N`, `--launch-chrome`); health: `curl -s http://127.0.0.1:8000/health`.
- Diagnose: `bh doctor` (read-only: Chrome debug port, profile flag, service, `API_TOKEN`).
- Start Chrome for the tool: `google-chrome --remote-debugging-port=9557 --user-data-dir="$HOME/bh-chrome-profile"`.
- Lint (CI gate): `.venv/bin/ruff check src/`.
- Tests: `.venv/bin/python -m pytest` (full suite, xdist parallel; host memory gate applies). Quick subset: `-m quick`.
- Release check: `scripts/release-validate.sh`.
