# MCP Reference Analysis — ai-vibe-coding-kit `mcp_server.py`

**Task:** `t_35b41891` — Analyze the reference MCP server pattern and document integration requirements.
**Input repo:** `/home/zoltan/ai-vibe-coding-kit` (v0.13.0, `src/ai_vibe_coding/mcp_server.py`)
**Target repo (consumer of this analysis):** `/home/zoltan/browser-helper` (v1.20.0)
**Date:** 2026-08-07

This document is the unblocking deliverable for the browser-helper MCP server work
(`t_4e2ec7fa` root, `t_fb1e9391` architecture design, `t_0e1239b7` pre-test).
Every API claim below was verified against the **installed** `mcp` SDK in the
ai-vibe-coding-kit venv (`mcp==1.28.1`), not against docs alone.

---

## 1. File Inventory & Current State Assessment

### 1.1 The reference file: `mcp_server.py` (361 lines)

| Section | Lines | Content |
|---|---|---|
| Module docstring | 1–10 | Purpose: expose `LLMClient` + `ToolDef` set as an MCP server over stdio/HTTP for Claude Code, Codex, Cursor, Windsurf |
| `MCPServerConfig` dataclass | 26–34 | `name`, `instructions`, `transport` (`"stdio"`/`"http"`), `host`, `port` |
| `MCPToolCallCost` dataclass | 37–45 | Per-tool cost/observability counters |
| `_make_typed_tool_fn()` | 48–93 | **Runtime function-synthesis** helper: converts a JSON Schema into a typed async function via `exec()` so FastMCP can introspect signatures |
| `MCPServer` class | 96–240 | `__init__`, `_create_mcp_server()`, `_default_instructions()`, `_register_mcp_tool()`, `_handle_tool_call()`, `run_stdio()`, `run_stdio_async()`, `run_http()`, `get_cost_summary()`, `reset_costs()` |
| `CostTracker` class | 243–298 | Thread-safe in-memory cost aggregation (`record_call`, `get_summary`, `reset`) |
| `to_mcp_server()` | 302–348 | Convenience factory (monkey-patched onto `LLMClient` at line 352) |

### 1.2 What the reference does NOT do (equally important)

- It is a **wrapper of an LLM client + tool schema registry**, not an implementation
  of tool logic. `_handle_tool_call` re-routes every MCP call back through
  `chat_with_tools()` — i.e., the LLM re-decides tool name + arguments. This is a
  **detour the browser-helper port must NOT copy** (see §4.2): browser-helper
  tools must call the real engine directly with the arguments MCP already
  validated.
- No auth, no resources, no prompts, no progress reporting, no sampling.
- Cost tracking is in-memory only (no persistence).
- `transport` config value is **aspirational** — `run_http()` ignores it and always
  uses `transport="sse"` (see §3 for the real SDK behaviour).

---

## 2. Exact FastMCP APIs Used (verified against mcp==1.28.1)

Source: `mcp/server/fastmcp/__init__.py` + live `inspect.signature()` on the
installed SDK in `/home/zoltan/ai-vibe-coding-kit/.venv`.

### 2.1 Import path

```python
from mcp.server.fastmcp import FastMCP
```

### 2.2 Constructor — `FastMCP.__init__`

```python
FastMCP(
    name: str | None = None,
    instructions: str | None = None,
    website_url: str | None = None,
    icons: list[Icon] | None = None,
    auth_server_provider: OAuthAuthorizationServerProvider | None = None,
    token_verifier: TokenVerifier | None = None,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    *,
    tools: list[Tool] | None = None,
    debug: bool = False,
    log_level: Literal['DEBUG','INFO','WARNING','ERROR','CRITICAL'] = 'INFO',
    host: str = '127.0.0.1',
    port: int = 8000,
    mount_path: str = '/',
    sse_path: str = '/sse',
    message_path: str = '/messages/',
    streamable_http_path: str = '/mcp',
    json_response: bool = False,
    stateless_http: bool = False,
    warn_on_duplicate_resources: bool = True,
    warn_on_duplicate_tools: bool = True,
    warn_on_duplicate_prompts: bool = True,
    dependencies: Collection[str] = (),
    lifespan: ... | None = None,
    auth: AuthSettings | None = None,
    transport_security: TransportSecuritySettings | None = None,
)
```

The reference uses only `name`, `instructions`, `host`, `port`.
**The `tools=` kwarg exists but the reference does not use it** — it registers via
`add_tool()` in a loop instead.

### 2.3 Tool registration — `FastMCP.add_tool`

```python
add_tool(fn, name: str | None = None, title: str | None = None,
         description: str | None = None,
         annotations: ToolAnnotations | None = None,
         icons: list[Icon] | None = None,
         meta: dict[str, Any] | None = None,
         structured_output: bool | None = None) -> None
```

- `fn` is introspected for its **type annotations** to build the MCP `inputSchema`
  (JSON Schema). This is why the reference synthesizes typed functions from JSON
  Schemas via `exec()` — unannotated `**kwargs` would produce an unusable schema.
- Return value must be JSON-serializable; for string outputs it is returned
  verbatim, otherwise `json.dumps()`-ed by the reference handler.

### 2.4 Transport runner — `FastMCP.run`

```python
run(transport: Literal['stdio', 'sse', 'streamable-http'] = 'stdio',
    mount_path: str | None = None) -> None
```

- **`"http"` is NOT a valid transport value** — the reference's `MCPServerConfig.transport
  = "http"` default and `run_http()` naming are misleading; `run_http()` actually calls
  `run(transport="sse")`.
- `streamable-http` is the modern HTTP transport (single endpoint, `mount_path`
  defaults to `/mcp`). `sse` is the legacy HTTP/SSE transport (`/sse` + `/messages/`).

### 2.5 Async runners (present in 1.28.1)

| Method | Signature | Notes |
|---|---|---|
| `run_stdio_async()` | `() -> None` | Async stdio run |
| `run_sse_async(mount_path=None)` | `() -> None` | Async SSE run |
| `run_streamable_http_async()` | (exists) | Async streamable-HTTP run |
| `run_http_async()` | **DOES NOT EXIST** | `AttributeError` in 1.28.1 — do not use |

### 2.6 `Context` (FastMCP tool-injection)

FastMCP injects a `Context` argument into tool functions when declared (by name)
as the last parameter. Verified members of 1.28.1:

`client_id`, `request_id`, `session`, `request_context`, `info`, `debug`, `warning`,
`error`, `log`, `report_progress`, `read_resource`, `elicit`, `elicit_url`,
`close_sse_stream`, `close_standalone_sse_stream`, `fastmcp`, plus pydantic model
helpers. (No `read_text` in this version.)

Useful for browser-helper: `Context.info(...)` for per-call logging and
`Context.report_progress(...)` for long-running fleet operations.

### 2.7 Availability of HTTP/SSE modules (verified)

```python
import mcp.server.streamable_http  # OK — available
import mcp.server.sse              # OK — available
```

---

## 3. Transport Configuration Approach (reference vs. reality)

### 3.1 The reference's approach (config dataclass)

```python
@dataclass
class MCPServerConfig:
    name: str = "ai-vibe-coding-assistant"
    instructions: str | None = None
    transport: str = "stdio"      # "stdio" or "http"
    host: str = "127.0.0.1"
    port: int = 8000
```

with runners:

```python
def run_stdio(self):   self._mcp_server.run(transport="stdio")
async def run_stdio_async(self):  await self._mcp_server.run_stdio_async()
def run_http(self):    self._mcp_server.run(transport="sse")
```

### 3.2 Gaps in the reference transport layer (verified against 1.28.1)

| # | Reference claim | Reality in mcp 1.28.1 | Impact |
|---|---|---|---|
| 1 | `transport="http"` is a valid value | `run()` accepts only `stdio` / `sse` / `streamable-http` | Config default `"http"` is never honored |
| 2 | `run_http()` starts an HTTP server | It starts SSE (`run(transport="sse")`) | Misleading name; works but not modern |
| 3 | `host`/`port` passed to `FastMCP()` configure HTTP | They configure the HTTP transports' bind address | Correct usage, but only relevant for sse/streamable-http |
| 4 | `port` in `MCPServerConfig` | `FastMCP(port=...)` — yes | Fine |
| 5 | Async HTTP runner exists | `run_http_async()` missing; `run_sse_async()` + `run_streamable_http_async()` exist | Use the correct method names |

### 3.3 Recommended transport design for browser-helper

- **stdio** → `await server.run_stdio_async()` (or `run(transport="stdio")`).
  Default for CLI agents (Claude Code, Codex CLI, Cursor, Windsurf all launch
  stdio subprocesses).
- **HTTP** → `run(transport="streamable-http")` with `streamable_http_path="/mcp"`,
  which is the endpoint modern MCP clients (`claude mcp add ... --transport http`)
  expect. SSE remains a valid fallback: `run(transport="sse")`.
- **Do NOT** copy the reference's `transport="http"` string or `run_http()` naming
  verbatim. The architecture spec (`t_fb1e9391`) should standardize on
  `"stdio" | "sse" | "streamable-http"` and settings keys `MCP_ENABLED` / `MCP_PORT`
  (per root task `t_4e2ec7fa` AC#2) mapped to `FastMCP(port=MCP_PORT)` +
  `run(transport=...)`.
- If HTTP must be embedded into the existing FastAPI `app` (`src/main.py`), note
  that FastMCP's HTTP transports bring their own ASGI app/starlette routes
  (`mount_path`, `sse_path`, `message_path`, `streamable_http_path`). Mounting is
  possible (`app.mount("/mcp", ...)`) but adds complexity; the reference keeps
  transport fully standalone, which is the simpler and proven path. Recommend:
  standalone process (CLI entry `python -m browser_helper.mcp`) for stdio, and
  either standalone or mounted for streamable-http.

---

## 4. ToolDef → browser-helper Capability Mapping

### 4.1 The reference `ToolDef` (from `src/ai_vibe_coding/structured.py`)

```python
@dataclass
class ToolDef:
    name: str                 # e.g. "get_weather"
    description: str
    parameters: dict[str, Any]  # JSON Schema dict
```

Also relevant from `structured.py` (imported by the reference):

- `chat_with_tools(client, prompt, tools, *, system_prompt, model, require_approval)`
  → `ToolCallResult(tool_name, arguments, raw_response)` — the LLM-decides-tool
  routing used by `_handle_tool_call`.
- `chat_json(client, prompt, ...)` — JSON-mode chat helper.
- Approval channels (`CLIApprovalChannel`, `SlackApprovalChannel`,
  `TelegramApprovalChannel`, `CallableApprovalChannel`) — optional, gated tools.

### 4.2 The critical architectural difference: route-through-LLM vs. direct call

The reference's `_handle_tool_call()` **does NOT execute the tool** — it sends the
MCP-received `(tool_name, arguments)` back through `chat_with_tools()` so the LLM
re-picks the tool and arguments, then returns `result.arguments`. This is by design
for its use case (an LLM client exporter) but is **wrong for browser-helper**:

- browser-helper tools have real implementations with real side effects (navigate,
  click, type, screenshot). Re-routing through an LLM would double-spend tokens,
  add latency, and could change arguments.
- The MCP client (Claude Code etc.) already decided the tool+args; the server must
  execute them faithfully.
- Also: the reference builds a prompt and calls `chat_with_tools` in a thread
  executor (`loop.run_in_executor`) — a sync-over-async pattern browser-helper
  doesn't need.

**Recommendation:** browser-helper MCP tools = thin async wrappers that call the
real engine functions directly. `ToolDef`-equivalent metadata (name, description,
JSON-Schema parameters) should be **derived from `capability_registry.py`** so the
MCP surface stays in sync with the REST API (root task AC#3).

### 4.3 ToolDef ↔ capability_registry mapping (browser-helper)

`capability_registry.py` (verified, 111 lines) defines:

```python
class CapabilityStatus(StrEnum): READY / EXPERIMENTAL / UNAVAILABLE

@dataclass(frozen=True, slots=True)
class Capability:
    id: str            # e.g. "browser.core", "agent.semantic", "workflow.local"
    title: str
    area: str
    status: CapabilityStatus
    description: str
    reason: str | None = None
    action: str | None = None
    def as_dict(self) -> dict[str, object]: ...

class CapabilityRegistry:
    def default(cls) -> CapabilityRegistry   # 8 capabilities
    def as_dict(self) -> dict[str, object]   # schema_version, summary, capabilities
```

**Mapping proposal** (to be finalized by code-architect, `t_fb1e9391`):

| MCP tool (root AC#1) | capability_registry entry | Real engine (root AC#4) |
|---|---|---|
| `navigate(url)` | `browser.core` (READY) | `src/main.py:async def navigate(url)` (line 1212) |
| `click(selector)` | `browser.core` | `src/main.py:click_element` (1227) |
| `type(selector, text)` | `browser.core` | `src/main.py:type_text` (1245) |
| `screenshot()` | `browser.core` | `src/main.py:screenshot` (1759) |
| `snapshot()` | `agent.semantic` (READY) | `src/agent_navigation.py:AccessibilityTreeBuilder.build` |
| `get_tabs()` | `browser.core` | `src/main.py:GET /tabs` (1946) |
| `switch_tab(id)` | `browser.core` | `src/main.py:switch_tab` (1987) |
| `close_tab(id)` | `browser.core` | main.py tab close endpoint |
| `session_status()` | `diagnostics.privacy` | `src/session_manager.py:SessionManager` |
| `fleet_nodes()` / `fleet_list` / `fleet_status` / `fleet_queue` | `workflow.local` (or new fleet capability) | `src/fleet/api.py:FleetCoordinator` + `NodeRegistry` + `FleetQueueManager` |

Notes on the mapping mechanics:

- The registry is **status-aware** (`READY`/`EXPERIMENTAL`/`UNAVAILABLE`). MCP
  tool registration should only expose READY (and optionally EXPERIMENTAL) tools;
  UNAVAILABLE capabilities (e.g. `cloud.camofox`) must never surface as tools.
  Registry `reason`/`action` fields can be surfaced in tool descriptions.
- Registry entries have no JSON-Schema parameters today — the tool-parameter
  schemas will be **authored in the MCP layer** (each tool's params) while the
  registry keeps IDs/titles/status authoritative. Two options: (a) extend
  `Capability` with an optional `input_schema: dict | None = None` field
  (backward-compatible, keeps single source of truth), or (b) a separate mapping
  table in the MCP module keyed by capability id. Option (a) is cleaner and keeps
  the registry the single vocabulary the tests/docs already rely on; flag for
  code-architect decision.

### 4.4 How to register a tool without `exec()`-synthesis

The reference's `_make_typed_tool_fn()` (lines 48–93) generates typed functions
via `exec()` because it must bridge arbitrary JSON Schemas to FastMCP's signature
introspection. browser-helper has a **fixed, known tool set** — write explicit
typed async functions instead:

```python
async def navigate(url: str) -> str:
    """Navigate the active tab to a URL."""
    result = await main.navigate(url)   # real engine
    return json.dumps(result, ensure_ascii=False)

mcp.add_tool(navigate, name="navigate", description="Navigate the active tab to a URL")
```

Benefits: no `exec`, static analyzers/ruff happy, no `locals()` filtering
hack, tool bodies are reviewable. If a generic ToolDef→function bridge is still
desired for future dynamic tools, keep the reference's approach as an optional
utility but do not make it the primary registration path.

---

## 5. Dependencies to Add (browser-helper)

### 5.1 Required

- **`mcp>=1.0.0,<2.0.0`** — the FastMCP SDK. ai-vibe-coding-kit pins exactly this
  range (`pyproject.toml` line 15) and it resolves to 1.28.1 today; pin the same
  range for consistency and to inherit verified behaviour above.
  - Verified against 1.28.1: `FastMCP`, `add_tool`, `run` with
    `stdio|sse|streamable-http`, `Context`, `run_stdio_async`, `run_sse_async`,
    `run_streamable_http_async`, `mcp.server.streamable_http` + `mcp.server.sse`
    imports.
  - Requires Python ≥ 3.10 in practice; browser-helper is already `>=3.10`
    (pyproject) with ruff target py311. OK.
- **`mcp` brings its own transitive deps** (pydantic, starlette/uvicorn, httpx-sse,
  etc.) — already largely present in browser-helper (fastapi, uvicorn, httpx).
  No new heavy deps beyond `mcp` itself.
- **CLI entry** (`python -m browser_helper.mcp`) needs the package importable as
  `browser_helper` — verify the src layout/package name (repo currently has
  `src/` top-level modules, e.g. `src/main.py`, imported as `main`; a `browser_helper`
  package name may not exist yet — architecture spec must settle the import path,
  e.g. `src/browser_helper/mcp.py` vs. `src/mcp_server/` as root task AC#1 suggests).

### 5.2 Not required (do not add)

- No `mcp[cli]` extras, no `fastmcp` pip package (that's a different, unrelated
  project — the SDK is `mcp`).
- No `sse-starlette` — `mcp.server.sse` ships its own; do not double-add.
- No new LLM dependency: browser-helper tools call engines directly, NOT
  `chat_with_tools` (that would require `openai`/`anthropic` clients — explicitly
  out of scope).

### 5.3 Version pin recommendation

```toml
mcp>=1.0.0,<2.0.0
```

Add under `[project.dependencies]` in `/home/zoltan/browser-helper/pyproject.toml`,
then `uv sync` / `.venv/bin/pip install 'mcp>=1.0.0,<2.0.0'` before tests.

---

## 6. Configuration Surface (settings integration)

Root task AC#2: config via existing `settings.py` with `MCP_ENABLED`, `MCP_PORT`.

Current state (verified):

- `src/settings.json` holds only Chrome-related keys
  (`chrome_profile_dir`, `chrome_debug_port`, `chrome_path`, `chrome_launched_port`,
  `chrome_pid`).
- `src/settings_manager.py` defines `DEFAULT_SETTINGS` with the same 5 keys and
  auto-detection; there is **no `settings.py`** and no MCP keys yet.

Requirements for the port:

1. Add `MCP_ENABLED: bool = False` (default off — don't change behaviour of
   existing deployments) and `MCP_PORT: int = 8765` (or similar non-8020/9555 port)
   to `DEFAULT_SETTINGS` + `settings.json` persistence layer.
2. `MCPServerConfig`-equivalent in browser-helper should read from settings_manager,
   not hardcode.
3. stdio transport ignores port (it's a subprocess pipe); `MCP_PORT` only applies
   to `streamable-http`/`sse` binds. Document this in the architecture spec so the
   pre-tester's tests don't assert port usage for stdio.

---

## 7. Reference Pattern Cheat-Sheet (for code-architect / developer)

What to **reuse** from `mcp_server.py`:
- `FastMCP(name=..., instructions=..., host=..., port=...)` constructor shape.
- Lazy server creation (`self._mcp_server = None` + `_create_mcp_server()` memoization)
  so tests can construct the wrapper without starting a server.
- `add_tool(fn, name=..., description=...)` per tool, in a loop over a declarative
  registry (their loop over `self.tools`, ours over capability-derived tools).
- Return-string contract: `str` verbatim, else `json.dumps(...)`.
- Cost/observability accumulator pattern (`CostTracker` + `threading.Lock`) — a
  useful model for browser-helper's `mcp_*` call metrics, but adapt to
  `Context.info()`/structured logging instead of a bespoke class if fleet metrics
  already exist.
- Module docstring + `__all__` discipline.

What to **change**:
- ❌ `exec()`-based `_make_typed_tool_fn` — write explicit typed async functions.
- ❌ Route-through-LLM `_handle_tool_call` — call the real engine directly.
- ❌ `transport="http"` default / `run_http()` naming — use
  `stdio` / `sse` / `streamable-http` literals and correct runner methods.
- ❌ `run_http_async()` — does not exist; use `run_streamable_http_async()` /
  `run_sse_async()`.
- ❌ Monkey-patching (`LLMClient.to_mcp_server = ...`) — browser-helper has no
  LLMClient to patch; expose a module-level factory `create_mcp_server(settings)`.

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Copying the route-through-LLM pattern by inertia | High | High (tokens, latency, arg drift) | This doc §4.2; AC on pre-tester to assert tools call engines directly (no LLM client involved) |
| `transport="http"` string copied → server fails or misbehaves | Medium | Medium | §3.3; pin valid literals; integration test that starts stdio AND streamable-http |
| FastMCP signature-introspection mismatch (unannotated handlers → empty inputSchema) | Medium | High (tools unusable by clients) | Explicit typed signatures per §4.4; integration test calls `list_tools()` and asserts non-empty `inputSchema` per tool |
| Package/import layout mismatch (`browser_helper` vs `src/` flat modules) | Medium | High (CLI entry broken) | Settle in architecture spec first; pre-tester contract check covers `python -m browser_helper.mcp` |
| Registry drift: MCP tools diverge from capability registry | Medium | Medium | Derive tool set from `CapabilityRegistry`; only READY/EXPERIMENTAL exposed |
| `MCP_PORT` collides with existing ports (8020 dashboard, 9555 Chrome) | Low | Medium | Default to a distinct port (e.g. 8765), document in settings |
| fleet tools marked read-only but accidentally mutating | Low | High | Map only read methods (`list_nodes`, `session_status`, `queue.peek`); pre-tester asserts no write endpoints exposed |

---

## 9. Source Links

- Reference file: `/home/zoltan/ai-vibe-coding-kit/src/ai_vibe_coding/mcp_server.py`
- ToolDef + routing: `/home/zoltan/ai-vibe-coding-kit/src/ai_vibe_coding/structured.py`
- Dependency pin: `/home/zoltan/ai-vibe-coding-kit/pyproject.toml` (`mcp>=1.0.0,<2.0.0`)
- Installed SDK: `mcp==1.28.1` in `/home/zoltan/ai-vibe-coding-kit/.venv`
  (`mcp/server/fastmcp/__init__.py` — signatures verified via `inspect.signature`)
- Capability registry: `/home/zoltan/browser-helper/src/capability_registry.py`
- REST engine endpoints: `/home/zoltan/browser-helper/src/main.py` (navigate:1212,
  click:1227, type:1245, screenshot:1759, tabs:1946, switch_tab:1987)
- Fleet layer: `/home/zoltan/browser-helper/src/fleet/api.py`
  (`FleetCoordinator:63`, `list_nodes:252`, `session_status:359`, `list_sessions:391`,
  `queue: FleetQueueManager` in `src/fleet/queue_manager.py`)
- Session manager: `/home/zoltan/browser-helper/src/session_manager.py` (`SessionManager:40`)
- Agent navigation: `/home/zoltan/browser-helper/src/agent_navigation.py`
  (`AccessibilityTreeBuilder:141`)
- Settings: `/home/zoltan/browser-helper/src/settings_manager.py` +
  `/home/zoltan/browser-helper/src/settings.json`

---

## 10. Downstream Handoff Notes

- **code-architect (`t_fb1e9391`)** — use §2 (API surface), §3.3 (transport design),
  §4.3 (tool mapping), §6 (settings) as the technical foundation for
  `docs/architecture/mcp-server-design.md`.
- **pre-tester** — the acceptance criteria must include: (1) tools call real engine
  directly (no LLM), (2) `list_tools()` returns non-empty `inputSchema` per tool,
  (3) stdio + streamable-http both start, (4) only READY/EXPERIMENTAL registry
  capabilities exposed, (5) `python -m browser_helper.mcp` entry works, (6) fleet
  tools are read-only.
- **developer** — pin `mcp>=1.0.0,<2.0.0`; write explicit typed handlers; use
  `run(transport=...)` literals correctly.
