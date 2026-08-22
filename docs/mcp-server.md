# MCP Server

**Since:** v1.21.0

Browser Helper ships a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that exposes the browser and fleet engine as MCP **tools**. Any MCP-capable client — Claude Code, Codex CLI, Cursor, Windsurf, or a custom agent — can drive the same engine the REST API uses, in-process, with no HTTP round-trips and no LLM in the loop.

The server is implemented in `src/mcp_server/` (see `docs/architecture/mcp-server-design.md` for the full architecture spec) and exposes **47 tools** derived from the capability registry (28 browser/fleet + 4 persistent memory + 6 agent testing).

---

## 1. Quick start

### Stdio (local agents — Claude Code, Codex CLI)

```bash
cd /path/to/browser-helper
python -m browser_helper.mcp            # stdio (default transport)
```

Or via the `bh` CLI router (same command):

```bash
bh mcp                                  # stdio (default)
```

On startup you see:

```
Browser Helper MCP server — transport=stdio tools=32 host=127.0.0.1 port=8765
```

The server then speaks JSON-RPC over stdin/stdout. Stdio is the transport for local, single-process agents. **No port is bound** in stdio mode — the port/host settings are ignored.

### Streamable HTTP (remote agents — Cursor, Windsurf, or any HTTP client)

```bash
bh mcp --http --host 0.0.0.0 --port 8765
# equivalent:
bh mcp --transport streamable-http --host 0.0.0.0 --port 8765
```

The MCP endpoint is `http://<host>:<port>/mcp`. This is the modern HTTP transport (the `2025-03-26` protocol); legacy clients that only speak SSE can use `--sse`:

```bash
bh mcp --sse --host 0.0.0.0 --port 8765   # endpoint http://<host>:<port>/sse
```

> **Transport values are `stdio`, `sse`, `streamable-http`.** `http` is not a valid transport literal in the MCP SDK — always use `streamable-http` (the `--http` flag maps to it).

### All entry points

| Command | Transport | Notes |
|---------|-----------|-------|
| `python -m browser_helper.mcp` | any (argparse: `--transport`) | Original shim; `--help` exits 0 |
| `bh mcp` | any (Click: `--http`/`--sse`/`--stdio`/`--transport`) | CLI router from `src/browser_helper/__main__.py` |
| `bh-mcp` | any (Click) | Console-script entry point (`pyproject.toml` `[project.scripts]`) |
| `browser-helper-mcp` | any (Click) | Alias entry point |

`bh-mcp` and `browser-helper-mcp` are Click *groups*; the command is invoked as `bh-mcp mcp` (or you can use `bh mcp` / `python -m browser_helper.mcp` directly).

---

## 2. Client configuration

### Claude Code / Claude Desktop (stdio)

Add to `~/.claude.json` under `mcpServers`, or use `claude mcp add`:

```json
{
  "mcpServers": {
    "browser-helper": {
      "command": "python",
      "args": ["-m", "browser_helper.mcp"],
      "cwd": "/path/to/browser-helper"
    }
  }
}
```

If Browser Helper is installed with `pip install -e .` (entry points `bh`, `bh-mcp`, `browser-helper-mcp`), the `cwd` is unnecessary:

```bash
claude mcp add browser-helper -- bh mcp
```

### Codex CLI (stdio)

```bash
# run from the repo root, or use --cwd / add cwd in config
codex mcp add browser-helper -- python -m browser_helper.mcp
```

Codex speaks stdio MCP over the child process; Browser Helper must be launchable from wherever Codex runs.

### Cursor / Windsurf (streamable HTTP)

Cursor and Windsurf configure MCP servers with a `url` (HTTP transport). First start the server with the HTTP transport bound to a reachable address:

```bash
bh mcp --http --host 0.0.0.0 --port 8765
```

Then add a server with URL `http://localhost:8765/mcp`:

**Cursor** — Project or global `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "browser-helper": {
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

**Windsurf** — `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "browser-helper": {
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

If the agent runs on a different machine, replace `localhost` with the host running Browser Helper (and bind `--host 0.0.0.0` — or bind a private interface and tunnel).

---

## 3. Tool reference (47 tools)

All 47 tools are backed by READY capabilities from `src/capability_registry.py`. UNAVAILABLE capabilities (`cloud.camofox`) and EXPERIMENTAL ones (`anti_detection.compositor`, `behavioral.scroll`) never surface as tools — the tool set is derived from the registry, not hand-maintained.

### Browser tools — `src/mcp_server/tools.py`

Each maps 1:1 to the engine call behind a REST endpoint (same `main.run_op` + `client.*` path, in-process).

| Tool | Parameters | Capability | Engine binding | REST mirror |
|------|-----------|------------|----------------|-------------|
| `navigate` | `url` (str, required) | `browser.core` | `run_op("navigate", client.navigate, url)` | `POST /navigate` |
| `click` | `selector` (str, required) | `browser.core` | `run_op("click", client.click, selector)` | `POST /click` |
| `type` | `selector` (str, required), `text` (str, required) | `browser.core` | `run_op("type", client.type_text, selector, text)` | `POST /type` |
| `screenshot` | — | `browser.core` | `run_op("screenshot", client.screenshot)` | `POST /screenshot` |
| `snapshot` | — | `agent.semantic` | `run_op("page_analyze", client.analyze_page)` | `POST /page/analyze` |
| `get_tabs` | — | `browser.core` | `run_op("get_tabs", client.get_tabs)` | `GET /tabs` |
| `switch_tab` | `id` (str, required) | `browser.core` | `run_op("switch_tab", client.switch_tab, id)` | `POST /switch_tab/{tab_id}` |
| `close_tab` | `id` (str, required) | `browser.core` | `run_op("close_tab", client.close_tab, id)` | `POST /tab/close/{tab_id}` |
| `session_status` | — | `diagnostics.privacy` | `_session_mgr.list_sessions()` (no CDP dependency) | `GET /api/v1/session` |
| `get_notifications` | `since` (float, opt), `limit` (int, opt) | `agent.testing` | `window.__bh_notifications__` (MutationObserver) | `GET /notifications` |
| `notifications_start` | — | `agent.testing` | `start_notification_monitoring()` | `POST /notifications/start` |
| `get_network_requests` | `path` (str, opt), `method` (str, opt), `status` (int, opt), `since` (float, opt), `limit` (int, opt) | `browser.core` | `get_network_log()` + filters | `GET /network/requests` |
| `get_console_errors` | `since` (float, opt), `limit` (int, opt) | `agent.testing` | `get_console_entries(level="error")` | `GET /console/errors` |
| `wait_js` | `js` (str, required), `timeout` (int, opt) | `agent.testing` | `evaluate()` + JS poll loop | `POST /wait/js` |
| `element_state` | `selector` (str, required) | `agent.testing` | `evaluate()` + `querySelector` | `GET /element/{selector}` |
| `eval` | `js` (str, required), `timeout` (int, opt) | `browser.core` | `client.evaluate_js(js)` (no snapshot) | `POST /eval` |
| `get_page_text` | `wait_ready` (bool, opt), `timeout` (int, opt) | `browser.core` | `client.get_page_text()` (+ `wait_for_ready` if `wait_ready`) | `GET/POST /page/text` |
| `press_key` | `key` (str, required), `selector` (str, opt) | `browser.core` | `client.press_key(key, selector)` | `POST /press_key` |
| `hover` | `selector` (str, required) | `browser.core` | `client.hover(selector)` (`mouseMoved`) | `POST /hover` |
| `scroll` | `x` (int, opt), `y` (int, opt), `selector` (str, opt) | `browser.core` | `client.scroll(x, y, selector)` | `POST /scroll` |
| `reload` | `ignore_cache` (bool, opt) | `browser.core` | `Page.reload` | `POST /reload` |
| `wait_network_idle` | `timeout` (int, opt), `quiet_ms` (int, opt) | `browser.core` | `client.wait_for_network_idle` | `POST /wait/network-idle` |
| `rate_limiter_status` | — | `browser.core` | `domain_throttle` state + interval | `GET /rate_limiter/status` |
| `dialog_handle` | `action` (str, required), `prompt_text` (str, opt) | `browser.core` | `Page.handleJavaScriptDialog` | `POST /dialog/handle` |

### Fleet tools — `src/mcp_server/fleet_tools.py`

All three are **read-only** — they use the same `get_fleet_coordinator()` singleton the REST router uses, and call only read methods (no register/unregister/allocate/release/sweep).

| Tool | Parameters | Capability | Data payload | REST mirror |
|------|-----------|------------|--------------|-------------|
| `fleet_nodes` | — | `workflow.local` | `{nodes, total, healthy, unhealthy}` | `GET /fleet/nodes` |
| `fleet_status` | — | `workflow.local` | `{sessions, total, active, queued}` | `GET /fleet/sessions` |
| `fleet_queue` | — | `workflow.local` | `{queue, size, max_queue}` | (peek of the allocation queue) |

Fleet reads are marked `meta.read_only: true` in their response envelopes.

### Return contract

Every tool returns a **JSON string** with the REST envelope shape:

```json
{
  "status": "ok",
  "operation": "navigate",
  "data": {"ok": true, "url": "https://example.com", "title": "Example Domain"},
  "error": null,
  "meta": {}
}
```

On failure, handlers return the same envelope with `status: "error"` and an `error: {code, message, details}` object — for example when an engine call fails (timeout, element not found, engine exception):

```json
{"status": "error", "operation": "navigate", "data": null,
 "error": {"code": "operation_failed", "message": "Connection refused", "details": null},
 "meta": {}}
```

Fleet and `session_status` handlers catch their own exceptions and always normalize to this envelope. Browser handlers (which route through `main.run_op`) return the envelope for failures that occur inside the engine call; note that a missing CDP connection is a **pre-flight** check — `run_op` raises `fastapi.HTTPException` (400, "Not connected to CDP. Call POST /connect first.") before the handler can normalize, and FastMCP surfaces that as a tool-call error to the agent. Start Browser Helper / connect to CDP first, then retry.

---

## 4. Architecture

```
MCP client                    Browser Helper process
(Claude Code, Codex,          ┌──────────────────────────────────┐
 Cursor, Windsurf, ...)       │  mcp_server/cli.py  (entry point) │
       │                      │        │                          │
       │  JSON-RPC            │  mcp_server/server.py (MCPServer) │
       │  over stdio          │        │ FastMCP lifecycle        │
       │  or HTTP/SSE         │  mcp_server/registry.py           │
       ▼                      │  (ToolDefRegistry ← CapabilityRegistry)
┌──────────────┐              │        │                          │
│  FastMCP SDK │              │  mcp_server/tools.py ──┐          │
│  (transports)│              │  mcp_server/fleet_tools.py        │
└──────┬───────┘              │        │                          │
       │                      │  main.run_op + client.* (engine)  │
       │                      │  fleet.api.get_fleet_coordinator()│
       │                      │  session_manager._session_mgr     │
       │                      └──────────────┬───────────────────┘
       │                                     │  in-process, direct calls
       │                                     ▼
       │                              Chrome (CDP, :9555)
```

- **Direct engine calls, no LLM.** Tools call `main.run_op(...)` / `main.client.*` / the fleet coordinator **in-process** — the exact functions behind the REST endpoints. No HTTP self-calls, no LLM client anywhere in `mcp_server/` (an anti-LLM test gate enforces this).
- **One server per process.** All tools share the module-level engine singletons (`main.client`, `main._session_mgr`, `get_fleet_coordinator()`), the same state the REST API operates on.
- **Capability-derived surface.** `mcp_server/registry.py` holds the authoritative tool→capability mapping and authored JSON Schemas; `build_tool_defs()` filters to READY + EXPERIMENTAL and the registry itself rejects UNAVAILABLE backings. `MCPServer` registers each `ToolDef` with FastMCP.
- **Import weight.** Engine imports stay lazy inside handler bodies — `--help`, registry-only tests, and server construction never pull the full FastAPI stack.

### Module layout

```
src/mcp_server/
├── __init__.py        # re-exports create_mcp_server, MCPServer, __version__
├── config.py          # MCPSettings dataclass + MCPTransport enum + load_mcp_settings()
├── registry.py        # ToolDef + ToolDefRegistry (capability-derived, status-filtered)
├── server.py          # MCPServer: FastMCP lifecycle + tool registration + run()
├── tools.py           # 9 browser tool handlers (navigate, click, type, …)
├── fleet_tools.py     # 3 read-only fleet handlers
├── serialization.py   # envelope normalization (json_dumps, tool_result, tool_error)
└── cli.py             # argparse main() + Click mcp command + entry-point app
src/browser_helper/
├── mcp.py             # python -m browser_helper.mcp shim (sys.path bootstrap)
└── __main__.py        # bh CLI router group (bh mcp)
```

---

## 5. Configuration

Settings resolve with precedence **CLI > env > settings.json > defaults** (`load_mcp_settings()` in `src/mcp_server/config.py`).

| Setting | Type | Default | Applies to | Notes |
|---------|------|---------|------------|-------|
| `MCP_ENABLED` / `mcp_enabled` | bool | `False` | auto-start gate only | Never blocks explicit CLI start — if you invoke `bh mcp`, the server runs |
| `MCP_PORT` / `mcp_port` | int | `8765` | sse, streamable-http | Ignored by stdio (no port is bound) |
| `--transport` / `--http` / `--sse` / `--stdio` | str | `stdio` | all | Valid literals: `stdio`, `sse`, `streamable-http`; invalid value → error before server start |
| `--host` | str | `127.0.0.1` | sse, streamable-http | Use `0.0.0.0` to expose to other machines |
| `--port` | int | settings `mcp_port` | sse, streamable-http | |
| `--enabled` | bool | `False` | startup flag | Sets `enabled=True` in settings (mirrors `MCP_ENABLED`) |

`mcp_enabled` gates **auto-start** scenarios only (e.g. a future `run.py --with-mcp` / Docker sidecar); it deliberately does not block the documented on-demand entry points.

---

## 6. Fleet integration

The three fleet tools give MCP agents read-only visibility into the fleet coordinator (the same process-wide singleton the `/fleet/*` REST router uses):

- **`fleet_nodes`** — `coordinator.registry.snapshot()` → `{nodes, total, healthy, unhealthy}` (mirrors `GET /fleet/nodes`).
- **`fleet_status`** — `coordinator.pool.list_sessions()` + `registry.snapshot()` → `{sessions, total, active, queued}` (mirrors `GET /fleet/sessions`).
- **`fleet_queue`** — `coordinator.queue.peek()` (FIFO, **non-consuming**) + `size()` → `{queue, size, max_queue}`.

Fleet state lives in SQLite at `~/.browser-helper/fleet.db` (override with `FLEET_DB_PATH`). The MCP server and the REST API share the same database and the same coordinator — an agent using `fleet_status` sees exactly what `/fleet/sessions` reports.

All three tools are pure reads: they never register, unregister, allocate, release, or sweep (enforced by the `test_fleet_tools_never_mutate` gate).

---

## 7. Troubleshooting

### "Not connected to CDP. Call POST /connect first."

Browser tools (`navigate`, `click`, `type`, `screenshot`, `snapshot`, `get_tabs`, `switch_tab`, `close_tab`) require a live CDP connection. Without one, `run_op` raises `HTTPException` 400 *before* the engine call — the agent sees a tool-call error with that message rather than an envelope. Start Browser Helper (or launch Chrome with `--remote-debugging-port=9555` and connect) before calling them. `session_status` and the fleet tools work without a browser connection.

### The agent sees only 47 tools

47 is the correct count for v1.28.0 (37 browser/fleet + 4 persistent memory + 6 agent testing). The surface is derived from READY capabilities (`browser.core`, `agent.semantic`, `diagnostics.privacy`, `workflow.local`, `memory.persistent`, `agent.testing`); EXPERIMENTAL capabilities (`anti_detection.compositor`, `behavioral.scroll`) and UNAVAILABLE ones are deliberately not exposed.

### stdio mode hangs / "port already in use"

In stdio mode no port is bound — the `MCP_PORT`/`--port` settings are ignored. If you see a port error, you are running an HTTP transport; pick a free port (`bh mcp --http --port 8766`) or check what is listening:

```bash
ss -ltnp | grep 8765
```

### Client cannot reach the HTTP endpoint

- Confirm the server is bound to an address the client can reach: `--host 0.0.0.0` for other machines, `127.0.0.1` for local clients only.
- Confirm the URL: streamable-http → `http://host:8765/mcp`, SSE → `http://host:8765/sse`.
- Streamable-http is session-based: clients must keep the `Mcp-Session-Id` header from the `initialize` response for subsequent requests (a fresh request without a session id returns `-32600 Missing session ID`).

### `--transport http` fails

`http` is not a valid MCP transport literal. Use `streamable-http` (or the `--http` flag):

```bash
bh mcp --transport streamable-http   # ✓
bh mcp --http                        # ✓ (same)
bh mcp --transport http              # ✗ invalid choice
```

### Verification commands

```bash
cd /path/to/browser-helper
export PATH="$PWD/.venv/bin:$PATH"

python -m browser_helper.mcp --help            # exits 0, prints transports
bh mcp --help                                  # Click help (entry point)
python -c "from mcp_server.registry import build_tool_defs; print(len(list(build_tool_defs())))"   # → 47
python -m pytest tests/test_mcp_server.py -q   # 55 tests: interface, engine binding, fleet reads, FastMCP
```

---

## 8. Source links

- Design spec: `docs/architecture/mcp-server-design.md`
- Reference analysis: `analysis/mcp-reference-analysis.md`
- Implementation: `src/mcp_server/` (config, registry, server, tools, fleet_tools, serialization, cli)
- Entry shim: `src/browser_helper/mcp.py`; CLI router: `src/browser_helper/__main__.py`
- Engine singletons: `src/main.py` (`run_op`, `client`, `_session_mgr`); fleet: `src/fleet/api.py`
- Capability registry: `src/capability_registry.py`
- Tests: `tests/test_mcp_server.py` (55 tests)
