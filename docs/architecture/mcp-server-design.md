# MCP Server Architecture & Tool-to-Capability Mapping

**Task:** `t_fb1e9391` — Design the MCP (Model Context Protocol) server for browser-helper.
**Repo:** `/home/zoltan/browser-helper` (v1.27.3, branch `main`)
**Date:** 2026-08-07
**Root task:** `t_4e2ec7fa` — *BROWSER-HELPER: MCP Server for Browser Fleet Orchestration*
**Inputs:** `analysis/mcp-reference-analysis.md` (parent `t_35b41891`, git `3861965`) — every FastMCP SDK claim below was verified against `mcp==1.28.1` in that analysis and re-verified live in this session (`inspect.signature` on the installed SDK, 2026-08-07).

This document is the implementation blueprint for the developer worker. It fixes the
module layout, the transport/configuration contract, the ToolDef↔capability_registry
mapping (the single source of truth for the MCP tool surface), the direct-call engine
binding for every tool, the CLI entry point, and the read-only fleet tool set, and it
closes the two open design questions the reference analysis flagged (§4.3, §5.1).

---

## 1. Scope & Design Decisions

### 1.1 Decisions made here (settled, binding)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Module root is **`src/mcp_server/`** (a package) | Root task AC#1 names `src/mcp_server/` explicitly. |
| D2 | Tools call the **real engine in-process** — the exact functions behind the REST endpoints (`main.run_op` + `client.*`), not HTTP, not an LLM | AC#1 "no facade, no mock"; reference analysis §4.2 (the reference's route-through-LLM pattern is explicitly **not** copied). In-process direct calls keep the MCP server a sidecar that shares the browser state; HTTP self-calls would add a port dependency and a failure mode for no benefit. |
| D3 | Tool set is **derived from `CapabilityRegistry`** (READY + EXPERIMENTAL only) via the `ToolDefRegistry`; UNAVAILABLE capabilities never surface as tools | AC#3; analysis §4.3. |
| D4 | Tool parameter JSON Schemas are **authored in the MCP layer** (explicit typed handlers, no `exec()` synthesis) | Analysis §4.4. Extending the registry with `input_schema` fields is explicitly out of scope (see §4.5) — keep registry changes additive-only and this-cycle minimal. |
| D5 | Transports are the three real FastMCP literals — **`stdio` | `sse` | `streamable-http`**; settings keys **`MCP_ENABLED`** (bool, default False) and **`MCP_PORT`** (int, default 8765); stdio ignores the port | AC#2; analysis §3.3. `"http"` is not a valid transport value in `mcp` 1.28.1. |
| D6 | `python -m browser_helper.mcp` is the CLI entry, implemented as a thin bootstrap shim that installs `src/` on `sys.path` and delegates to `mcp_server.cli:main` | AC#4. The repo has a flat `src/` layout (`run.py` uses this exact pattern); there is no installable `browser_helper` package today. |
| D7 | Fleet tools are **read-only**: `fleet_nodes()`, `fleet_status()`, `fleet_queue()` — no register/unregister/allocate/release/sweep | AC#5; analysis risk register ("fleet tools marked read-only but accidentally mutating" → map only read methods). |
| D8 | Dependency: `mcp>=1.0.0,<2.0.0` | Analysis §5.1. |
| D9 | MCP server runs **standalone** (own process for stdio; own process or mounted ASGI app for streamable-http); FastAPI embedding is documented but optional | Analysis §3.3 recommendation. |

### 1.2 Naming & identity

- **Server name (MCP):** `browser-helper` — this is what appears in Claude Code / Codex / Cursor client lists.
- **Server instructions:** one-paragraph capability summary generated from `CapabilityRegistry.default().as_dict()` (status-aware; see §4.6).
- **Tool naming:** plain snake_case, no prefix (`navigate`, `click`, `type`, `screenshot`, `snapshot`, `get_tabs`, `switch_tab`, `close_tab`, `session_status`, `fleet_nodes`, `fleet_status`, `fleet_queue`) — the root task's AC#1 list verbatim. Tool *descriptions* surface the backing capability id and registry status so clients can reason about availability.
- **Logging:** `browser-helper.mcp` logger; per-call `Context.info()`; long fleet reads use `Context.report_progress()`.

### 1.3 Concurrency & lifecycle model

| Concern | Design |
|---|---|
| Shared state | The MCP server runs **one FastMCP server per process**; all tools share the module-level `main.client` / `main._session_mgr` / `get_fleet_coordinator()` singletons — exactly the state the REST API operates on. A second in-process server instance is **not** supported (FastMCP itself tolerates it, but the engine singletons are process-scoped by design). |
| Concurrency | FastMCP handles tool calls concurrently; the underlying `CDPClient` serializes CDP commands with a message-id lock and the fleet SQLite layer uses a single-writer lock. **No additional locking in the MCP layer.** |
| Lifecycle | Stdio: `asyncio.run(main())` → `run_stdio_async()`. HTTP: `asyncio.run(main())` → `run_streamable_http_async()` / `run_sse_async()`. No custom lifespan needed (engine singletons are lazy; `get_fleet_coordinator()` builds on first use). |
| Import weight | `main` import is ~0.5 s and instantiates the CDP client + settings manager but does **not** launch Chrome (launch is explicit via `/browser/launch` or `CHROME_AUTO_LAUNCH`). Acceptable for a server process; tests may import `mcp_server.registry` alone (no `main`) for pure registry assertions. |

---

## 2. Module Structure

```
src/mcp_server/
├── __init__.py        # package marker; re-exports create_mcp_server, MCPServer, __version__
├── config.py          # MCPSettings dataclass + transport enum + load_mcp_settings(); CLI overrides
├── registry.py        # ToolDef dataclass + ToolDefRegistry (capability-derived, status-filtered)
├── server.py          # MCPServer: FastMCP lifecycle + tool registration + run() entry
├── tools.py           # engine_* handler implementations (navigate, click, type, …) — one fn per tool
├── fleet_tools.py     # read-only fleet handlers (fleet_nodes / fleet_status / fleet_queue)
├── serialization.py   # json serialization helpers (envelopes, exceptions → MCP error strings)
└── cli.py             # main(argv): argparse for --transport/--host/--port; startup banner; run()
```

Entry shim (top level, **not** under `src/mcp_server/`):

```
src/browser_helper/
└── mcp.py             # python -m browser_helper.mcp → sys.path bootstrap → mcp_server.cli:main
```

### 2.1 Module responsibilities

| Module | Owns | Explicitly does NOT own |
|---|---|---|
| `config.py` | `MCPTransport` enum (`stdio`/`sse`/`streamable-http`), `MCPSettings` dataclass (`transport`, `enabled`, `host`, `port`, `server_name`, `instructions`), `load_mcp_settings()` reading `SettingsManager` + env + CLI overrides | settings persistence (that stays in `settings_manager.py`); FastMCP construction |
| `registry.py` | `ToolDef` (name, description, parameters JSON Schema, capability_id, status, handler ref), `ToolDefRegistry` (iterable, `by_name`, `capabilities()`), `build_tool_defs()` deriving tools from `CapabilityRegistry.default()` filtered to READY+EXPERIMENTAL, `_TOOL_PARAM_SCHEMAS` (the authored schemas) | engine calls; FastMCP |
| `server.py` | `MCPServer` class: lazy FastMCP creation, `register_tools()` loop over `ToolDefRegistry`, `run(transport)` dispatching to `run_stdio_async` / `run_sse_async` / `run_streamable_http_async`, module-level `create_mcp_server(settings=None)` factory | tool logic (delegates to `tools.py`/`fleet_tools.py`) |
| `tools.py` | One explicit typed `async def` handler per browser tool; each wraps `main.run_op(...)` / `main.client.*` directly; `Context` injection for logging/progress | fleet (delegates to `fleet_tools.py`); FastMCP |
| `fleet_tools.py` | The three read-only fleet handlers; `get_fleet_coordinator()` singleton reuse; queue via `coordinator.queue.peek()/size()` | any write path |
| `serialization.py` | `json_dumps()`, `tool_result()`, `tool_error()` — envelope normalization, `ensure_ascii=False`, error → `{"error": ...}` strings | transport |
| `cli.py` | `main(argv=None)`, argparse (`--transport`, `--host`, `--port`, `--enabled`), startup banner, `asyncio.run` | FastMCP |

### 2.2 Import conventions (must be followed exactly)

- All imports use the flat `src/` layout: `from main import client, run_op, _session_mgr, api_success`, `from fleet.api import get_fleet_coordinator`, `from capability_registry import CapabilityRegistry`, `from settings_manager import SettingsManager`. This is what the repo's existing modules and tests do (see `fleet/api.py`'s lazy `from main import ...` inside functions).
- `mcp_server/` modules import **no** FastMCP SDK symbols at module import time except in `server.py` (and `registry.py` stays 100% SDK-free so unit tests never need the `mcp` package installed — see §8.4).
- `main` imports stay **lazy inside handler bodies** (import cost + engine side effects only when a tool is actually invoked). `server.py` may import `main` lazily too (in `create_mcp_server`), keeping `python -m browser_helper.mcp --help` and registry-only tests fast.
- No circularity: `server.py` → `registry.py` → (schemas only); `server.py` → `tools.py` → `fleet_tools.py`; `cli.py` → `server.py` + `config.py`.

---

## 3. Configuration (settings.py integration)

### 3.1 Current state (verified)

- `src/settings_manager.py` defines `DEFAULT_SETTINGS` with exactly 5 keys: `chrome_profile_dir`, `chrome_debug_port`, `chrome_path`, `chrome_launched_port`, `chrome_pid`; persisted to `src/settings.json`.
- There is **no `settings.py`**; `SettingsManager` is the settings layer. Root task AC#2's "settings.py" is satisfied by `settings_manager.py` (the reference analysis §6 says exactly this).

### 3.2 Additions (made by the developer task, spec'd here)

```python
DEFAULT_SETTINGS = {
    ...existing 5 keys...,
    "mcp_enabled": False,   # default OFF — existing deployments unchanged
    "mcp_port": 8765,       # distinct from 8020 (dashboard) and 9555 (Chrome debug)
}
```

- Keys are lowercase `mcp_enabled` / `mcp_port` to match the existing snake_case convention (`chrome_debug_port`).
- The `8765` default was chosen in the parent analysis because it does not collide with
  the API port (`8000`) or the Chrome CDP debug port (`9555`). The "8020 dashboard" port
  cited in the parent analysis is not actually referenced anywhere in the current repo
  (verified 2026-08-07) — `8000`/`9555` are the two real in-use ports; `8765` stays clear
  of both.
- `MCPSettings` in `config.py` reads them via `SettingsManager().get("mcp_enabled", False)` / `get("mcp_port", 8765)`; env vars `MCP_ENABLED` / `MCP_PORT` override; CLI flags override both (precedence: CLI > env > settings.json > defaults).
- `MCP_ENABLED` semantics: config flag + documented in README; the MCP server is **always startable on demand** (CLI/`python -m browser_helper.mcp` ignores `mcp_enabled`, since a user explicitly asking for the server wants it). `mcp_enabled` gates only **auto-start** scenarios (e.g. a future `run.py --with-mcp` flag / Docker sidecar). This split avoids the trap where "enabled=False" blocks the documented entry point.
- `MCP_PORT` applies **only** to `sse` / `streamable-http` binds. stdio is a subprocess pipe — no port is bound; pre-tester tests must not assert port usage for stdio (analysis §6.3).

### 3.3 Transport configuration contract

| Setting | Type | Default | Applies to | Notes |
|---|---|---|---|---|
| `MCP_ENABLED` / `mcp_enabled` | bool | `False` | auto-start gate | never blocks explicit CLI start |
| `MCP_PORT` / `mcp_port` | int | `8765` | sse, streamable-http | ignored by stdio |
| `--transport` (CLI) | str | `stdio` | all | one of `stdio` / `sse` / `streamable-http`; invalid value → argparse error before any server starts |
| `--host` (CLI) | str | `127.0.0.1` | sse, streamable-http | ignored by stdio |
| `--port` (CLI) | int | from settings | sse, streamable-http | ignored by stdio |

`FastMCP(host=..., port=...)` are passed through from `MCPSettings`; `mount_path`/`streamable_http_path` keep SDK defaults (`/mcp` for streamable-http) unless a future settings key is added.

---

## 4. ToolDef Registry & Capability Mapping

### 4.1 `ToolDef` dataclass (`registry.py`)

```python
@dataclass(frozen=True, slots=True)
class ToolDef:
    name: str                 # MCP tool name, e.g. "navigate"
    description: str          # client-visible description (includes capability id + status)
    parameters: dict[str, Any]  # JSON Schema (draft-07 style) for the tool's input
    capability_id: str        # backing capability_registry id, e.g. "browser.core"
    status: CapabilityStatus  # READY | EXPERIMENTAL (UNAVAILABLE never registered)
    handler: Callable[..., Awaitable[str]]  # direct-call engine handler (tools.py / fleet_tools.py)
```

### 4.2 `ToolDefRegistry` (`registry.py`)

- `__init__(tool_defs: Iterable[ToolDef])` — validates unique names, sorts by name (deterministic registration order, mirrors `CapabilityRegistry`'s sorted discipline).
- `by_name(name) -> ToolDef | None`.
- `capabilities() -> list[str]` — capability ids backing the registered tools.
- `__iter__()` — registration loop source for `MCPServer.register_tools()`.
- `build_tool_defs(registry: CapabilityRegistry | None = None) -> ToolDefRegistry` — the derivation function: iterates `CapabilityRegistry.default().capabilities`, keeps `status in {READY, EXPERIMENTAL}`, looks up the tool definitions whose `capability_id` matches, and refuses (loud error) to register a tool whose backing capability is UNAVAILABLE (defense-in-depth; see §4.4).

### 4.3 The tool-to-capability mapping (authoritative)

`browser.core` (READY) and `agent.semantic` (READY) are the two capability areas the tool surface draws from; the registry keeps ids/titles/status authoritative, the MCP layer owns parameter schemas (D4).

| MCP tool (AC#1) | capability_registry id | Status | Engine binding (direct call, §5) | REST surface it mirrors |
|---|---|---|---|---|
| `navigate(url)` | `browser.core` | READY | `main.run_op("navigate", client.navigate, url)` | `POST /navigate` (main.py:1212) |
| `click(selector)` | `browser.core` | READY | `main.run_op("click", client.click, selector)` | `POST /click` (main.py:1227) |
| `type(selector, text)` | `browser.core` | READY | `main.run_op("type", client.type_text, selector, text)` | `POST /type` (main.py:1245) |
| `screenshot()` | `browser.core` | READY | `main.run_op("screenshot", client.screenshot)` | `POST /screenshot` (main.py:1759) |
| `snapshot()` | `agent.semantic` | READY | `main.run_op("page_analyze", client.analyze_page)` | `POST /page/analyze` (main.py:1450) |
| `get_tabs()` | `browser.core` | READY | `main.run_op("get_tabs", client.get_tabs)` | `GET /tabs` (main.py:1946) |
| `switch_tab(id)` | `browser.core` | READY | `main.run_op("switch_tab", client.switch_tab, id)` | `POST /switch_tab/{tab_id}` (main.py:1987) |
| `close_tab(id)` | `browser.core` | READY | `main.run_op("close_tab", client.close_tab, id)` | `POST /tab/close/{tab_id}` (main.py:2259) |
| `session_status()` | `diagnostics.privacy` | READY | `_session_mgr.list_sessions()` (sync) + CDP/`state` summary — see §5.8 | `GET /api/v1/session` (main.py:4048) |
| `fleet_nodes()` | `workflow.local` (fleet capability) | READY | `get_fleet_coordinator().registry.snapshot()` — see §5.9 | `GET /fleet/nodes` (fleet/api.py:252) |
| `fleet_status()` | `workflow.local` (fleet capability) | READY | `get_fleet_coordinator().pool.list_sessions()` + `registry.snapshot()` — see §5.9 | `GET /fleet/sessions` (fleet/api.py:391) |
| `fleet_queue()` | `workflow.local` (fleet capability) | READY | `get_fleet_coordinator().queue.peek()` + `queue.size()` — see §5.9 | (no dedicated REST read; mirrors the queue tier of `POST /fleet/session` 202-responses) |

All 64 tools are READY-backed (37 browser/fleet + 4 memory + 6 agent testing + 17 E2E validation). No EXPERIMENTAL capability maps to a tool this cycle:
`anti_detection.compositor` and `behavioral.scroll` are EXPERIMENTAL and must **not** be
exposed (their modules contain explicit `NotImplementedError` paths — registry `reason`
fields). If a later cycle ships them, adding a tool is a one-line registry extension.

### 4.4 Status filter & defense-in-depth

1. `build_tool_defs()` filters to `status in {READY, EXPERIMENTAL}` — `cloud.camofox` (UNAVAILABLE) and friends never produce tools.
2. `ToolDefRegistry.__init__` re-checks: a `ToolDef` whose `status` is UNAVAILABLE raises `ValueError` — a stale hand-authored def cannot slip through.
3. `MCPServer.register_tools()` iterates the registry and calls `mcp.add_tool(handler, name=..., description=...)` — a UNAVAILABLE def would have been rejected in step 2 before reaching FastMCP.
4. Registry `reason`/`action` fields surface in tool descriptions where non-null (e.g. EXPERIMENTAL tools would carry "experimental — use with caution").

### 4.5 Why the registry is NOT extended with `input_schema` (decision D4, closing analysis §4.3 option (a))

The reference analysis offered two options: (a) extend `Capability` with an optional
`input_schema` field, or (b) an MCP-side mapping table. This spec chooses **(b)**:

- `CapabilityRegistry` is a **frozen, versioned, REST-facing contract** consumed by
  `/api/v1/capabilities`, dashboard, and 1200+ tests. Adding fields is backward-compatible
  but expands the public contract for zero MCP benefit.
- A `Capability` describes a *product area* (`browser.core` → many endpoints), while an
  MCP tool is a *single call* with its own schema — the cardinality is 1 capability : N
  tools. Embedding schemas in the registry would put N tools' schemas on one capability.
- Tool parameters must be derived from **handler signatures** anyway (FastMCP introspects
  the typed functions — D4/analysis §4.4), so a separate authored schema would duplicate
  what the signature already declares. The `_TOOL_PARAM_SCHEMAS` table is the thin,
  reviewable bridge and doubles as the pre-tester's contract (non-empty `inputSchema` per
  tool).
- Registry **stays the single source of truth for which capabilities exist and their
  readiness** (AC#3's actual intent — "capabilities stay consistent with the REST API
  surface"); the MCP layer owns call shapes.

### 4.6 Server instructions generation

`MCPServer` builds `instructions` from `CapabilityRegistry.default().as_dict()`: a short
paragraph listing READY/EXPERIMENTAL capabilities with their `action` hints and the
UNAVAILABLE list with `reason`/`action` (so an agent never asks for Camofox). The
`CapabilityStatus` values are reused verbatim — no second vocabulary.

---

## 5. Tool Implementations (direct engine calls)

### 5.1 Universal handler pattern

Every handler is an explicit typed `async def` (no `exec()`, no `**kwargs`), takes an
optional trailing `Context` parameter (FastMCP injection — verified in 1.28.1), wraps the
real engine call, and returns a **JSON string** (FastMCP returns `str` verbatim; anything
else is `json.dumps`-ed by the SDK — analysis §2.3). Errors are caught and returned as
`{"status": "error", ...}` JSON strings — MCP has no HTTP status codes, so the REST
`api_error` JSONResponse cannot be returned; the envelope is normalized by
`serialization.py`.

```python
# tools.py (shape; actual file has all 9 handlers + docstrings)
from mcp.server.fastmcp import Context   # typing only — see §8.4 note

async def navigate(url: str, ctx: Context | None = None) -> str:
    """Navigate the active browser tab to *url*.

    Backed by capability `browser.core` (READY) — same engine as POST /navigate.
    """
    from main import run_op, client          # lazy import — engine singletons
    if ctx: ctx.info(f"navigate -> {url}")
    return json_dumps(await run_op("navigate", client.navigate, url))
```

- **Direct call, verified no-LLM:** the handler body calls `client.navigate` (CDPClient,
  `cdp_client.py:291`) via `run_op` — the same path as the REST endpoint. No
  `chat_with_tools`, no LLM client import anywhere in `mcp_server/`.
- **Connection guard:** `run_op` begins with `ensure_connected()` and returns
  `api_error(..., "operation_failed", ...)` if the CDP client is not connected — the MCP
  tool surfaces that as `{"status": "error", "error": {...}}`, exactly the REST contract.
  `navigate`/`click`/`type`/`screenshot`/`snapshot`/`get_tabs`/`switch_tab`/`close_tab`
  therefore never crash the MCP session on a disconnected browser.

### 5.2 `navigate(url: str) -> str`

`run_op("navigate", client.navigate, url)`. Invalidates the tab cache (same as the
endpoint). REST mirror: `POST /navigate` (main.py:1212).

### 5.3 `click(selector: str) -> str`

`run_op("click", client.click, selector)` — CSS selector click, CDP-backed.
REST mirror: `POST /click` (main.py:1227).

### 5.4 `type(selector: str, text: str) -> str`

`run_op("type", client.type_text, selector, text)`. REST mirror: `POST /type` (main.py:1245).

### 5.5 `screenshot() -> str`

`run_op("screenshot", client.screenshot)` — returns `{"data": "<base64 JPEG q70>"}` in
`data`; the handler passes the base64 through (agents may want to view it; the string is
already JSON). REST mirror: `POST /screenshot` (main.py:1759).

### 5.6 `snapshot() -> str`

`run_op("page_analyze", client.analyze_page)` — the same comprehensive
URL/title/buttons/modals/forms/text analysis as `POST /page/analyze` (main.py:1450),
which uses `client.analyze_page()` + `SnapshotStore`. (The reference analysis suggested
`AccessibilityTreeBuilder` directly; the endpoint is the better single-call contract and
keeps snapshot-store semantics — the tool is named `snapshot` per AC#1, and it returns
the page-analyze payload.)

### 5.7 Tab tools

- `get_tabs() -> str`: `run_op("get_tabs", client.get_tabs)` — list of `{id, title, url, active}`. REST mirror `GET /tabs` (main.py:1946).
- `switch_tab(id: str) -> str`: `run_op("switch_tab", client.switch_tab, id)`. REST mirror `POST /switch_tab/{tab_id}` (main.py:1987).
- `close_tab(id: str) -> str`: `run_op("close_tab", client.close_tab, id)` — **note:** the REST route is `POST /tab/close/{tab_id}` (main.py:2259), not `/close_tab`; the MCP tool keeps the AC#1 name `close_tab` while calling the same engine method. The mapping table's "REST surface" column documents the real route.

### 5.8 `session_status() -> str`

Design decision: the AC#1 name `session_status()` maps to the **session persistence
layer** (`diagnostics.privacy` / session_manager), consistent with the reference analysis
table. Handler:

1. `from main import _session_mgr` (lazy).
2. `sessions = _session_mgr.list_sessions()` — sync, returns `{session_id, age, expired, url, created_at, last_active}` per session (session_manager.py:273).
3. Wrap as `{"status": "ok", "operation": "session_status", "data": {"sessions": sessions, "total": len(sessions)}}` — the REST `GET /api/v1/session` envelope shape (main.py:4048), built directly (no JSONResponse).

(Do **not** route this through `run_op` — there is no CDP-backed engine call here and
`ensure_connected()` would wrongly fail the tool when the browser is disconnected but
saved sessions exist.)

### 5.9 Fleet tools (read-only; `fleet_tools.py`)

All three use `get_fleet_coordinator()` (`fleet/api.py:123`) — the same process-wide
singleton the REST router uses; first call opens `~/.browser-helper/fleet.db` (honours
`FLEET_DB_PATH`). **Read-only methods only** — no `register/unregister/allocate/release/
sweep/failover` anywhere (AC#5 + analysis risk register). `Context.report_progress()`
is used for the two multi-source reads.

- `fleet_nodes() -> str`: `coordinator.registry.snapshot()` → `{nodes, total, healthy, unhealthy}`. Mirrors `GET /fleet/nodes` data payload (fleet/api.py:252). Pure read (SQLite `SELECT`s).
- `fleet_status() -> str`: `coordinator.pool.list_sessions()` + `coordinator.registry.snapshot()` → `{sessions, total, active, queued}` (active = status in `{"active","allocated","idle"}`; queued = `queued` flag — same arithmetic as `GET /fleet/sessions`, fleet/api.py:391). Pure read.
- `fleet_queue() -> str`: `coordinator.queue.peek()` (FIFO order, no consumption — `FleetQueueManager.peek`, queue_manager.py:158) + `coordinator.queue.size()` → `{queue: [...], size: N, max_queue: coordinator.queue.max_queue}`. Pure read (the storage layer's `peek_queue` is a SELECT ordered by `queue_position`).

Envelope: `{"status": "ok", "operation": "fleet_*", "data": ..., "meta": {"read_only": true}}`
— built via `serialization.py`, not `fleet/api._success` (that helper imports `main` and
returns REST-shaped payloads; the MCP layer keeps one envelope builder).

### 5.10 Return contract summary (`serialization.py`)

| Case | Output |
|---|---|
| `run_op` success dict | `json.dumps(payload, ensure_ascii=False)` — verbatim REST envelope |
| `run_op` error dict (status "error") | same, serialized as-is (client sees `error.code`/`error.message`) |
| Exception in handler | `json.dumps({"status": "error", "operation": <tool>, "error": {"code": "mcp_tool_error", "message": str(exc)}})` |
| fleet/session handlers | standard `api_success`-shaped envelope built locally |

Handlers never raise into FastMCP (which would surface as a generic `-32603` tool error);
they normalize to the envelope so agents get the same `status/error` vocabulary as the
REST API.

---

## 6. Server Initialization & Lifecycle (`server.py`)

### 6.1 Construction (lazy, test-friendly — mirrors reference analysis §7 "lazy server creation")

```python
class MCPServer:
    def __init__(self, settings: MCPSettings | None = None):
        self.settings = settings or load_mcp_settings()
        self._mcp: FastMCP | None = None

    @property
    def mcp(self) -> FastMCP:                # memoized builder
        if self._mcp is None:
            self._mcp = FastMCP(
                name=self.settings.server_name,          # "browser-helper"
                instructions=self._build_instructions(),  # from CapabilityRegistry
                host=self.settings.host,
                port=self.settings.port,
                log_level="INFO",
            )
            self.register_tools(self._mcp)
        return self._mcp

    def register_tools(self, mcp: FastMCP) -> None:
        for tool in build_tool_defs():       # ToolDefRegistry iteration
            mcp.add_tool(tool.handler, name=tool.name, description=tool.description)

    async def run(self, transport: MCPTransport | str | None = None) -> None:
        t = MCPTransport(self.settings.transport if transport is None else transport)
        if t is MCPTransport.STDIO:          await self.mcp.run_stdio_async()
        elif t is MCPTransport.SSE:          await self.mcp.run_sse_async()
        else:                                await self.mcp.run_streamable_http_async()
```

### 6.2 Transport runners (verified against mcp 1.28.1 — analysis §2.5)

| Transport | Runner | Notes |
|---|---|---|
| `stdio` | `run_stdio_async()` | default; `MCP_PORT`/`host` ignored |
| `sse` | `run_sse_async()` | binds `host:port`, `/sse` + `/messages/` |
| `streamable-http` | `run_streamable_http_async()` | binds `host:port`, `/mcp` (modern clients: `claude mcp add ... --transport http`) |

**`run_http_async()` does not exist** — never use it. `FastMCP.run(transport="http")` is
also invalid (only `stdio|sse|streamable-http` literals). The `MCPTransport` enum
guarantees valid values at the type level, and `cli.py` validates CLI input against it.

### 6.3 Module factory

```python
def create_mcp_server(settings: MCPSettings | None = None) -> MCPServer:
    """Expose a module-level factory (no monkey-patching — analysis §7)."""
    return MCPServer(settings=settings)
```

---

## 7. CLI Entry Point (`python -m browser_helper.mcp`)

### 7.1 The shim (`src/browser_helper/mcp.py`)

```python
"""`python -m browser_helper.mcp` — MCP server entry (browser-helper).

Bootstrap shim: the repo uses a flat `src/` layout (see run.py), so this
module puts `src/` on sys.path and delegates to mcp_server.cli.
"""
import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mcp_server.cli import main  # noqa: E402  (after sys.path fix)

if __name__ == "__main__":
    raise SystemExit(main())
```

- `python -m browser_helper.mcp` works from the repo root **and** from anywhere (the shim
  resolves `src/` relative to its own file, like `run.py`).
- The `browser_helper` namespace is a tiny package containing only `mcp.py` this cycle —
  no `src/browser_helper/__init__.py` conflicts with anything (there is no existing
  `browser_helper` package; flat `src/` modules are imported as top-level names).
- `mcp_server.cli:main` is the single real entry; `cli.py` is also directly runnable as
  `python -m mcp_server.cli` (useful in tests).

### 7.2 `cli.main(argv=None) -> int`

```
usage: python -m browser_helper.mcp [--transport {stdio,sse,streamable-http}]
                                    [--host HOST] [--port PORT]

  --transport   MCP transport: stdio (default, for Claude Code / Codex / Cursor),
                sse, or streamable-http (remote agents)
  --host        bind address for sse/streamable-http (default 127.0.0.1)
  --port        bind port for sse/streamable-http (default: settings mcp_port or 8765)
```

Flow: parse args → `load_mcp_settings(overrides=...)` → print startup banner
(`Browser Helper MCP server — transport=stdio · tools=32 · capabilities=READY:4/EXPERIMENTAL:2 …`)
→ `asyncio.run(MCPServer(settings).run(transport))`. `argparse` errors exit non-zero
before any import of `mcp` or `main`.

### 7.3 Client configuration examples (for the developer task's README/docs work)

**Claude Code (stdio):**
```json
// ~/.claude.json → mcpServers (or `claude mcp add`)
{"mcpServers": {"browser-helper": {"command": "python", "args": ["-m", "browser_helper.mcp"], "cwd": "/path/to/browser-helper"}}}
```

**Codex CLI (stdio):**
```bash
codex mcp add browser-helper -- python -m browser_helper.mcp
# (run from the repo root, or pass cwd)
```

**Remote agent (streamable-http):**
```bash
python -m browser_helper.mcp --transport streamable-http --host 0.0.0.0 --port 8765
# client: {"mcpServers": {"browser-helper": {"url": "http://HOST:8765/mcp"}}}
```

**SSE (legacy clients):**
```bash
python -m browser_helper.mcp --transport sse --port 8765
# client: {"mcpServers": {"browser-helper": {"url": "http://HOST:8765/sse"}}}
```

---

## 8. Testing Strategy (contract for the pre-tester, `t_0e1239b7`)

The pre-tester builds `tests/test_mcp_server.py` against this spec. Mandatory assertions
(from analysis §10, made concrete):

### 8.1 Registry/derivation unit tests (no `mcp` SDK needed)

- `build_tool_defs()` returns the full registry-derived surface (64 tools as of v1.34.0; the count grows as capabilities are added — §4.3 lists the v1.21.0 baseline).
- Every tool's `capability_id` exists in `CapabilityRegistry.default()`; every backing
  capability is READY or EXPERIMENTAL; **no** UNAVAILABLE capability appears.
- `ToolDefRegistry` rejects duplicate names and rejects a UNAVAILABLE `ToolDef`
  (`ValueError`).
- `_TOOL_PARAM_SCHEMAS` is non-empty per tool and contains `type: "object"` +
  `properties` with the exact required params (`navigate`→`url`; `click`→`selector`;
  `type`→`selector,text`; `switch_tab`/`close_tab`→`id`; others → `{}`).

### 8.2 Direct-call contract (the anti-LLM gate)

- Patch `main.run_op` / `main.client.*` with `AsyncMock`s; call each handler; assert the
  **exact engine call** (`run_op("navigate", client.navigate, url)` etc.).
- Assert **no LLM client import**: scan `mcp_server/` sources for `openai`, `anthropic`,
  `chat_with_tools` → absent.
- Assert handlers return JSON strings parseable with the REST envelope shape
  (`status`/`operation`/`data` or `error`).

### 8.3 FastMCP integration (real server, real `mcp` package)

- `MCPServer().mcp` constructs; `list_tools()` via the SDK's tool manager returns 12
  tools, each with **non-empty `inputSchema`** (the signature-introspection gate).
- Tools are registered under the exact AC#1 names.
- `python -m browser_helper.mcp --help` exits 0 and prints transports; an invalid
  `--transport` exits non-zero before server start.
- Optional (slow-marked): start `run_streamable_http_async()` on an ephemeral port and
  call `tools/list` over HTTP; stdio transport start is verified by process spawn in the
  developer's own E2E (stdio framing is the SDK's job, not re-tested here).

### 8.4 Pitfall for the pre-tester

`tests/test_mcp_server.py` must be runnable in the repo's `.venv` **with `mcp` installed**
(developer task pins `mcp>=1.0.0,<2.0.0` and runs `uv sync`/`pip install`). Registry-only
tests in 8.1 keep `mcp` out of `registry.py`'s import chain so they also run in
SDK-less environments — do not import `mcp_server.server` in those tests.

---

## 9. Sequence Diagrams

### 9.1 Tool invocation — browser tools (stdio client, e.g. Claude Code)

```
┌──────────┐  initialize  ┌───────────────────────────┐  add_tool ×12   ┌─────────────────┐
│ MCP client│────────────▶│ MCPServer (FastMCP, stdio) │───────────────▶│ ToolDefRegistry  │
│ (Claude   │             │  name="browser-helper"     │  build_tool_defs│ (capability-     │
│  Code)    │             │  instructions←registry     │◀────────────────│  derived, READY/ │
└──────────┘              └───────────────────────────┘                 │  EXPERIMENTAL)   │
```

```
client                    MCPServer/stdio                 tools.navigate            main (engine singletons)
   │  tools/call: navigate(url)                              │                             │
   │──────────────────────────▶│  FastMCP validates args      │                             │
   │                           │  (typed signature → schema)  │                             │
   │                           │─────────────────────────────▶│  ctx.info("navigate…")      │
   │                           │                              │  from main import run_op,   │
   │                           │                              │        client  (lazy)       │
   │                           │                              │────────────────────────────▶│
   │                           │                              │  run_op("navigate",         │
   │                           │                              │    client.navigate, url)    │
   │                           │                              │  ensure_connected()         │
   │                           │                              │  await client.navigate(url) │
   │                           │                              │  log_operation + broadcast  │
   │                           │                              │◀── api_success envelope ───│
   │                           │◀── json string ──────────────│                             │
   │◀── {"status":"ok",…} ─────│  (str verbatim, no re-encode)│                             │
```

The MCP client → FastMCP hop is JSON-RPC over the stdio pipe; the tool body is a plain
Python `await`. **No LLM is involved after the client's own tool-selection step.**

### 9.2 Tool invocation — fleet read (streamable-http, remote agent)

```
agent                  FastMCP (streamable-http :8765/mcp)      fleet_tools.fleet_status        FleetCoordinator
  │  tools/call: fleet_status()                                      │                              │
  │──────────────────────────────────▶│  ctx.report_progress(0,1)    │                              │
  │                                   │─────────────────────────────▶│  get_fleet_coordinator()     │
  │                                   │                              │  (builds once; keyed on     │
  │                                   │                              │   FLEET_DB_PATH)            │
  │                                   │                              │────────────────────────────▶│
  │                                   │                              │  pool.list_sessions()       │
  │                                   │                              │  registry.snapshot()        │
  │                                   │                              │◀── {sessions,total,…} ─────│
  │                                   │◀── json string ──────────────│                              │
  │◀── {"status":"ok","data":{…}} ────│                              │                              │
```

### 9.3 Error path — browser not connected

```
client        FastMCP          tools.navigate                 main.run_op
  │ tools/call │                  │                              │
  │───────────▶│─────────────────▶│  ensure_connected()          │
  │            │                  │  → not connected             │
  │            │                  │  api_error("operation_failed", 400)   [dict]
  │            │◀── json: {"status":"error","error":{"code":…}} ──│
  │◀── tool result ───│           (never raises; MCP session stays alive)  │
```

---

## 10. Dependencies

```toml
# pyproject.toml — added under [project.dependencies]
"mcp>=1.0.0,<2.0.0",
```

- Brings pydantic/starlette/httpx-sse transitively — already present via fastapi/uvicorn/httpx.
- **Do NOT add:** `mcp[cli]`, the unrelated `fastmcp` pip package, `sse-starlette`
  (`mcp.server.sse` ships its own), or any LLM client (analysis §5.2).

---

## 11. Developer Task Handoff (implementation checklist)

1. Add `"mcp>=1.0.0,<2.0.0"` to `pyproject.toml`; `uv sync` (or `.venv/bin/pip install`).
2. `settings_manager.py`: add `mcp_enabled: False`, `mcp_port: 8765` to `DEFAULT_SETTINGS`.
3. Create `src/mcp_server/` package per §2 with the module responsibilities in §2.1.
4. Implement `registry.py` first (SDK-free), then `tools.py` + `fleet_tools.py`, then
   `server.py`, `cli.py`, shim `src/browser_helper/mcp.py`, `serialization.py`.
5. Verify locally:
   - `cd /home/zoltan/browser-helper && .venv/bin/python -m browser_helper.mcp --help`
   - `.venv/bin/python -c "from mcp_server.registry import build_tool_defs; print(len(list(build_tool_defs())))"` → `12`
   - `.venv/bin/python - <<'PY'` … `MCPServer().mcp` construct + tool count via SDK `list_tools`.
6. README: add **"MCP Server"** section with the client config examples from §7.3.
7. CHANGELOG: entry under an `[Unreleased]`/next-version heading.
8. Commit + push; pre-tester (`t_0e1239b7`) then builds `tests/test_mcp_server.py` against §8.

## 12. Out of Scope (explicit)

- Embedding FastMCP inside the FastAPI app (`app.mount("/mcp", …)`) — documented option
  (analysis §3.3), not built this cycle.
- `input_schema` on `Capability` — decision D4 / §4.5.
- MCP resources/prompts/auth/OAuth — none in AC; FastMCP defaults only.
- Auto-start wiring (`run.py --with-mcp` / Docker sidecar) — `mcp_enabled` key is added
  now, wiring is a follow-up.
- EXPERIMENTAL capability tools (anti-detection, behavioral) — explicitly excluded per §4.3.

## 13. Source Links

- Reference pattern: `/home/zoltan/ai-vibe-coding-kit/src/ai_vibe_coding/mcp_server.py`
  (`MCPServerConfig:27`, `_make_typed_tool_fn:48`, `MCPServer:96`, `_create_mcp_server:121`,
  `_register_mcp_tool:147`, `_handle_tool_call:174`, `run_stdio:214`, `run_http:226`,
  `CostTracker:243`, `to_mcp_server:302`)
- Verified SDK: `mcp==1.28.1` (`mcp/server/fastmcp/__init__.py` — `run()` literals,
  `run_stdio_async`/`run_sse_async`/`run_streamable_http_async`, no `run_http_async`,
  `Context` members incl. `info`/`report_progress`)
- Capability registry: `/home/zoltan/browser-helper/src/capability_registry.py` (8 caps;
  READY: `agent.semantic`, `browser.core`, `dashboard.assistants`, `diagnostics.privacy`,
  `workflow.local`; EXPERIMENTAL: `anti_detection.compositor`, `behavioral.scroll`;
  UNAVAILABLE: `cloud.camofox`)
- Engine singletons: `src/main.py` (`client:212`, `_session_mgr:81`, `run_op:923`,
  `api_success:807`, `api_error:814`, `navigate:1212`, `click:1227`, `type:1245`,
  `page_analyze:1450`, `screenshot:1759`, `tabs:1946`, `switch_tab:1987`,
  `tab_close:2259`, `api_session_list:4048`)
- Fleet: `src/fleet/api.py` (`FleetCoordinator:63`, `get_fleet_coordinator:123`,
  `list_nodes:252`, `session_status:359`, `list_sessions:391`), `src/fleet/queue_manager.py`
  (`peek:158`, `size:154`), `src/fleet/storage.py` (`peek_queue`, `queue_size:680`),
  `src/fleet/node_registry.py` (`snapshot:225`), `src/fleet/session_pool.py`
  (`list_sessions:352`, `status:348`)
- Session manager: `src/session_manager.py` (`list_sessions:273`)
- Settings: `src/settings_manager.py` (`DEFAULT_SETTINGS:38`)
- Entry pattern: `run.py` (sys.path bootstrap), `conftest.py` (tests add `src/`)
- Parent analysis: `analysis/mcp-reference-analysis.md` (git `3861965`)
