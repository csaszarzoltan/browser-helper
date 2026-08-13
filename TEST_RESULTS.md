# Test Results

## 2026-08-13 — Release validation (v1.27.3, MCP live E2E + memory flags)

Environment: Python 3.11.15, project venv (`.venv`), dedicated headless test Chrome
(`CHROME_AUTO_PORT`) — the production Chrome on port 9555 is never touched.

### Full regression

```bash
PYTHONPATH=.:src .venv/bin/pytest tests/ -q \
  --ignore=tests/test_chrome_live.py
```

Result: **2636 passed, 1 skipped, 41 xfailed, 32 xpassed** in 285.12s (0:04:45).

### MCP live E2E (dedicated test Chrome)

```bash
PYTHONPATH=.:src .venv/bin/pytest tests/test_mcp_live_e2e.py -q
```

Result: **4 passed** — `initialize`, `get_tabs`, `navigate`, `session_status` all
drive a real Chrome instance via the MCP stdio transport (no mocks, no HTTP
loopback). The fixture launches its own headless profile + port
(`CHROME_AUTO_PORT`), so the production Chrome (9555) is never touched.

### What changed since the last report (2026-07-29)

- MCP live E2E now runs against a **dedicated test Chrome** (own profile + port via
  `CHROME_AUTO_PORT`); production Chrome untouched, deterministic tests.
- Explicit session routing (`sess_override`/`session_hook`) replaces the
  contextvar approach — tool tasks now see the right session for `Page.navigate`.
- `CHROME_AUTO_PORT` env-first in both `_local_cdp_http()` and
  `chrome_manager.launch()`.
- Tab-cache invalidation in `navigate()` before `Page.navigate` (the 5s
  `discover_tabs` cache returned stale lists).
- Chrome launch now uses memory-friendly flags (`--disable-dev-shm-usage`,
  `--renderer-process-limit=8`) — the service was OOM-killed once (1.2 GB peak
  with 18 renderer processes); 8 GB swapfile added to the host as well.
- Release hygiene: `scripts/release-validate.sh` checks version/tool-count
  consistency (pyproject == main.py == README == CHANGELOG == Docker label;
  MCP tool count from `build_tool_defs()` — 32 tools).

### Known deviations

- `data:` URLs: a tab navigated to a `data:` URL shows URL `''` / title
  `about:blank` in Chrome's `/json` tab list — the navigate E2E test asserts the
  *returned* URL instead.
- The production service runs with `--debug-port 9557` while the live Chrome is
  on 9555 (known config drift, not a test failure).
- 1 skipped test: requires a live browser session that is intentionally not
  started in the CI-style run.
