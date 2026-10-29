# browser-helper: core

- Remote Chrome control: REST API + MCP server + GUI dashboard. Drives the user's real Chrome over CDP (port 9557).
- Entry points: `run.py` (API + dashboard, :8000); `bh` CLI (`src/browser_helper/__main__.py`, `doctor.py`); MCP server in `src/mcp_server/` (`cli.py`, `registry.py`, `*_tools.py`, `memory/`).
- Main source map (`src/`): `main.py` (API), `cdp_client.py`, `chrome_manager.py`, `session_manager.py`, `agent_runtime.py`, `agent_navigation.py`, `capability_registry.py`, `anti_detection/`, `fleet/`, `browser_providers/`, `services/`, `static/` (dashboard assets).
- Tests: `tests/` (~140 files), `conftest.py` at root and `tests/conftest.py`. Chrome is stubbed; no test touches a live browser.
- Machine-specific `src/settings.json` (Chrome path, profile dir) is gitignored; never commit it.
- Specs and decisions: `.specs/features/` (feature briefs/specs), `docs/specs/`, `docs/decisions/`. `docs/` is mostly English, but `docs/engineering-standards.md` is Hungarian.
- Invariant: REST responses use the envelope `status, operation, data, error, meta`; errors are `{"error": {"code", "message"}}`.

See `mem:tech_stack`, `mem:suggested_commands`, `mem:conventions`, `mem:task_completion`.
