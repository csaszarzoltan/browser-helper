# Changelog

All notable changes to browser-helper will be documented in this file.

## [Unreleased]

## [1.21.0] — 2026-08-08

#### Added

**Auto-launch & reliability**
- `_ensure_browser()`: any operation (navigate/eval/click/...) auto-launches Chrome (saved profile, port 9557) and connects to the LOCAL CDP when not running — no separate `/browser/launch` + `/connect` needed.
- Startup connects to the saved local port (not the CDPClient default 9555, which may be another machine's SSH tunnel).
- `_reap_orphan_headless()`: on startup, kills `--headless` Chrome processes not owned by live headless sessions (prevents GBs of RAM leaking after restarts — observed 483 orphans / ~22GB).

**Per-client sessions (tab isolation)**
- `SessionRegistry`: every HTTP client gets its own session (cookie `bh_session` / `X-Session-ID`), each owning a dedicated Chrome tab + its own CDP client. No client-side id generation — the server mints it.
- Hard cap (default 15, env `BH_MAX_SESSIONS`) with LRU eviction: the least-recently-used session's tab closes when the cap is reached; the client auto-heals a fresh tab on its next call.
- TTL reaper (30 min) closes idle sessions; auto-heal recreates dead tabs via HTTP `/json/new`.
- Optional per-profile cookie isolation: `POST /session/new?profile=<name>` launches a dedicated headless Chrome with that profile's user-data-dir.
- Endpoints: `POST /session/new`, `GET /sessions`, `POST /session/close`.

**One-call high-level agent endpoints**
- `POST /agent/search`: one call = navigate + wait for answer + extract text (perplexity/google/ddg/bing; handles streaming answers).
- `POST /agent/run-flow`: ordered E2E steps with per-step report (navigate/click_text/click/type/submit/wait_text/wait/eval/screenshot; `auto_wait` waits for page ready after navigate/click; `stop_on_error`).
- `POST /agent/diff`: visual comparison of two URLs (pixel-diff + diff artifact).
- `POST /agent/visual-regression`: multi-URL baseline record / compare with per-URL pass/fail + delta.
- `POST /agent/console`: console errors / JS exceptions / failed network requests (always-on bounded buffer).
- `POST /agent/flow-vlm`: run a flow then assess the final screenshot with a vision model (VLM_* env; graceful skip when unavailable).
- `GET /agent/flow-templates` + `POST /agent/flow-templates/{login|signup|search|checkout}`: parameterised E2E templates.
- Context-efficient extractors: `POST /page/content` (main content, nav/sidebar filtered), `/page/headline`, `/page/links`, `/page/forms`, `/page/table`, `/page/text?wait_ready=true`.

**MCP**
- New tools: `search`, `get_content`, `run_flow` (capabilities `agent.search`, `agent.flow`) — 15 tools total.
- MCP process-scoped session so MCP calls stay on one dedicated tab.

#### Fixed
- `run-flow` now includes the failing step in its report (was dropped on `stop_on_error`).
- `wait_for_ready` / search handle streaming answers (poll for substantive content, not DOM stability).
- Session routing: operations rebind onto the session's own client (REST endpoints pass the global client's bound method).

#### Security / ops
- `bh-watchdog.sh` cron script (30 min): alerts when chrome processes/RAM/headless exceed thresholds; optional auto-reap.
- VLM config in systemd unit; 401/403/429 treated as graceful skip.
### [1.20.1] — 2026-08-07

#### Added

**MCP Server** (`src/mcp_server/`, entry points in `pyproject.toml` `[project.scripts]`)
- Model Context Protocol server exposing the browser and fleet engine as MCP tools for Claude Code, Codex CLI, Cursor, and Windsurf. Backed by the capability registry (`src/capability_registry.py`): 12 READY-backed tools across `browser.core`, `agent.semantic`, `diagnostics.privacy`, and `workflow.local`; EXPERIMENTAL/UNAVAILABLE capabilities never surface (spec `docs/architecture/mcp-server-design.md`).
- Transports: `stdio` (default, for Claude Code/Codex/Cursor), `sse`, and `streamable-http` (`--http` maps to streamable-http; `http` is not a valid transport literal). Endpoints: `/mcp` (streamable-http), `/sse` (SSE).
- Entry points: `bh mcp` (Click router in `src/browser_helper/__main__.py`), `bh-mcp` / `browser-helper-mcp` (console scripts), and the argparse shim `python -m browser_helper.mcp` (`src/browser_helper/mcp.py`). Precedence CLI > env (`MCP_ENABLED`/`MCP_PORT`) > settings.json (`mcp_enabled`/`mcp_port`, default `8765`) > defaults.
- Browser tools (`src/mcp_server/tools.py`): `navigate`, `click`, `type`, `screenshot`, `snapshot`, `get_tabs`, `switch_tab`, `close_tab`, `session_status` — each calls the real engine in-process (`main.run_op` + `client.*`, the same path behind the REST endpoints; no LLM, no HTTP self-calls).
- Fleet tools (`src/mcp_server/fleet_tools.py`): read-only `fleet_nodes`, `fleet_status`, `fleet_queue` over the shared `get_fleet_coordinator()` singleton (SQLite `~/.browser-helper/fleet.db`, `FLEET_DB_PATH` override) — no register/allocate/release/sweep anywhere.
- Envelope contract (`src/mcp_server/serialization.py`): every tool returns a JSON string with the REST envelope shape (`status`/`operation`/`data`/`error`/`meta`); fleet and `session_status` handlers normalize their own exceptions, and engine failures inside `run_op` return the envelope — so agents can branch on `error.code`/`error.message` uniformly. (Caveat: a missing CDP connection raises `HTTPException` 400 in `run_op`'s pre-flight `ensure_connected()` before the handler can normalize — the agent sees a tool-call error, not an envelope.)
- Configuration: `MCPSettings` dataclass + `MCPTransport` enum (`src/mcp_server/config.py`); `mcp_enabled` gates only auto-start scenarios and never blocks explicit CLI start; `MCP_PORT` applies only to HTTP/SSE binds.
- Docs: [MCP Server](docs/mcp-server.md) — quick start, client config (Claude Code, Codex CLI, Cursor/Windsurf), 12-tool reference table, architecture, fleet integration, troubleshooting, verification commands.
- Tests: `tests/test_mcp_server.py` (55 tests) — interface contract, engine-binding assertions (anti-LLM gate), read-only fleet gates, real FastMCP `list_tools()` integration.

### [1.20.0] — 2026-08-04

#### Added
- Accessible visual workflow builder for navigate, click, type, wait-for-element, screenshot, page analysis, and page text actions.
- Bidirectional visual/JSON editing with explicit synchronization, validation, add, duplicate, reorder, and remove controls.
- Responsive workflow step cards, focus-visible states, screen-reader announcements, and local privacy-safe builder telemetry.
- TDD acceptance coverage in `tests/test_visual_workflow_builder_v219.py` and operator documentation in `docs/visual-workflow-builder.md`.
- Privacy-safe daily work launchpad and `GET /api/v1/launchpad` from v1.18.0.
- Fleet orchestration (v1.20.0): distributed multi-node browser fleet management under `/fleet/*` (see `src/fleet/api.py` and the `src/fleet/` package) — a coordinator registers worker nodes, probes their `/health` endpoints, schedules sessions across the least-loaded healthy node, queues allocation requests at capacity, and fails sessions over when a node dies.
  - Node registry (`src/fleet/node_registry.py`): `POST /fleet/nodes/register` (201/409), `POST /fleet/nodes/{node_id}/unregister` (200/404), `GET /fleet/nodes` with per-node health, load, and capability metadata.
  - Health checking (`src/fleet/health_checker.py`): async poller (15s interval, 30s cooldown on a down node); `GET /fleet/nodes/{node_id}/health`, `POST /fleet/nodes/health-check`, `POST /fleet/nodes/{node_id}/health-check`.
  - Session pool (`src/fleet/session_pool.py`): `POST /fleet/session` (200, 202 queued, 409 duplicate, 503 queue full / no healthy node), `GET /fleet/session/{session_id}`, `POST /fleet/session/{session_id}/release`, `GET /fleet/sessions`.
  - Queueing (`src/fleet/queue_manager.py`): FIFO queue (default depth 10) with TTL and 503 + `Retry-After` backpressure; `POST /fleet/queue/sweep` purges expired entries.
  - Failover (`src/fleet/failover.py`): `POST /fleet/failover` re-allocates a dead node's sessions with save/restore state transfer; the health poller triggers it automatically when a node goes unhealthy.
  - CLI (`src/fleet/cli.py`): `python -m fleet.cli node list` / `session list` over httpx, honouring `FLEET_API_URL`, `--base-url`, and `API_TOKEN`.
  - Dashboard: Fleet workspace tab in the dashboard plus the standalone `GET /fleet` console page (`static/fleet.html`).
  - SQLite state in `~/.browser-helper/fleet.db` (override with `FLEET_DB_PATH`; `src/fleet/storage.py`, WAL + foreign keys).
  - Contract coverage in `tests/test_fleet_v115.py` (29 integration tests).

- Task-oriented dashboard workspaces for Overview, Live Browser, Automation, Diagnostics, and Agent Tools.
- Persistent active context, Ctrl/Cmd+K command palette, connection-aware controls, safe destructive-action confirmation, and local privacy-preserving telemetry hooks.
- Dashboard accessibility improvements: skip navigation, landmarks, live announcements, visible focus, textual status, and reduced-motion support.
- Acceptance and integration coverage in `tests/test_dashboard_ux_v19.py`.
- Guided Live Browser flow for validated navigation, screenshot capture, agent observation, recent URL reuse, and accessible busy/error/success feedback.
- Privacy-safe guided run history with correlation IDs, timing, bounded session storage, retry, confirmed clear, and redacted JSON export.
- Workflow assistant with safe starter templates, shared schema-oriented validation, formatting, explicit 64 KB local drafts, privacy guidance, and busy-state protection.
- Privacy-safe session state assistant with validation, 5 MB JSON import, download, confirmed restore, sensitive editor clearing, and no dashboard persistence.
- Diagnostics operation-log assistant with search, status filtering, visible counts, confirmed clearing, and bounded redacted JSON/CSV export.
- Tab management assistant with non-destructive search, validated inline opening, Enter submission, accessible dynamic actions, confirmed closing, and context refresh.
- Network diagnostics assistant with capture-state feedback, non-destructive filters, connection-aware controls, sensitive query redaction, and bounded JSON/CSV export.
- Cookie privacy assistant with masked values, non-destructive metadata filtering, secure-status filtering, metadata-only export, and confirmed clearing.


### [1.8.0] — 2026-07-31

#### Added
- Deterministic per-run recovery advisor for execution failures, verification failures, missing evidence, and verified outcomes.
- `GET /api/v1/runs/{run_id}/recovery` with retry-safety classification and no automatic execution.
- Inline accessible recovery guidance in Diagnostics with privacy-safe local telemetry.
- TDD coverage in `tests/test_run_recovery_v20.py` and documentation in `docs/run-recovery-guidance.md`.
- Truthful verification inference for shared operations based only on explicit result evidence.
- Propagation of `verified`, `unverified`, and `failed` states into API metadata and correlated run records.
- Verification-state filtering and explanatory guidance in the Diagnostics run timeline.
- TDD coverage in `tests/test_run_verification_v20.py` and documentation in `docs/verified-outcomes.md`.
- End-to-end run correlation across shared operation responses, legacy operation entries, timeline records, and support exports.
- `GET /api/v1/runs/{run_id}` for retrieving one retained, redacted run.
- Copyable run IDs in Diagnostics with keyboard-accessible controls, live announcements, and local telemetry.
- TDD coverage in `tests/test_run_correlation_v20.py` and operator documentation in `docs/run-correlation.md`.
- Per-run redacted support JSON export from the unified Diagnostics timeline.
- `GET /api/v1/runs/{run_id}/support` with a versioned support contract and explicit privacy metadata.
- Defensive run lookup, accessible export controls, success/failure announcements, and local-only telemetry.
- TDD acceptance coverage in `tests/test_run_support_bundle_v20.py` and documentation in `docs/run-support-bundles.md`.
- Bounded, privacy-safe unified operation run timeline with generated run IDs, duration, status, and explicit verification state.
- `GET /api/v1/runs` and `DELETE /api/v1/runs` contracts for listing and clearing process-local run history.
- Accessible Diagnostics timeline with status filtering, refresh, safe clear, responsive layout, and local telemetry.
- TDD acceptance coverage in `tests/test_run_timeline_v20.py` and operator documentation in `docs/run-timeline.md`.
- Product readiness registry and `GET /api/v1/capabilities` contract for ready, experimental, and unavailable product areas.
- Accessible Overview readiness card with explicit reasons, manual refresh, local telemetry, and resilient failure feedback.
- Expanded active execution context showing the current CDP target and most recent operation.
- Acceptance coverage in `tests/test_capability_readiness_v20.py` and operator guide in `docs/capability-readiness.md`.

**Anti-Detection Compositor** (`src/anti_detection/compositor.py`)
- `AntiDetectCompositor` facade that composes a complete anti-detection profile: fingerprint spoofing (Canvas/WebGL/audio/navigator), proxy rotation strategy, session persistence, and stealth injection — selectable per browser session.
- Compose/test/export/import endpoints wired through the REST API; 64 tests.
- See [Anti-Detection Compositor](docs/anti-detection-compositor.md) and [examples/anti_detect_compositor.py](examples/anti_detect_compositor.py).

**Fingerprint Database** (`src/anti_detection/fingerprint_database.py`)
- JSON-backed fingerprint template database with 4 shipped defaults (`chrome-120`, `firefox-linux`, `safari-ios`, `edge-windows`) — note these DB names differ from the v1.7 profile types (`stealth-chrome-120` / `mobile-safari-ios`).
- Template add/get/remove/list, arbitrary template generation (`generate_template`), and load-on-init persistence — templates added via API now survive restarts.
- Export/import of template JSON files.
- See [Fingerprint Database](docs/fingerprint-database.md) and [examples/fingerprint_database.py](examples/fingerprint_database.py).

**Proxy Rotation** (`src/proxy_rotation_manager.py`)
- `ProxyRotationManager` wrapping `ProxyPool` with env-var auto-load (`PROXY_LIST`/`PROXY_FILE`).
- 5 rotation strategies: round-robin, random, sticky, by-tag, and health — 70 tests.
- Non-blocking async health checks (`health_check_async`/`health_check_all_async`, httpx.AsyncClient) that never stall the event loop.
- See [Proxy Rotation Manager](docs/proxy-rotation-manager.md) and [examples/proxy_rotation.py](examples/proxy_rotation.py).

**Session Persistence** (`src/session_manager.py`)
- `SessionManager` capture/restore of browser session state: cookies (`Network.getAllCookies`), storage (`Runtime.evaluate`), and WebSocket frames — 32 tests.
- See [Session Persistence](docs/session-persistence.md) and [examples/session_persistence.py](examples/session_persistence.py).

**REST API** (`src/main.py`)
- New `/api/v1` endpoints: `/api/v1/fingerprints/*` (generate, export, import), `/api/v1/session/*` (capture, restore, cleanup), `/api/v1/compose/*` (compose, test, export, import, resolve, resolve-stealth), `/api/v1/proxy/*` (health, stats, load-from-env) — 114 tests.

**Stealth Injection improvements** (`src/stealth_injector.py`)
- Real CDP injection via `Page.addScriptToEvaluateOnNewDocument` and correct `json.dumps` escaping of injected JS payloads.

#### Fixed

- **C1–C5 critical defects** (tech-lead review): detection tests no longer report fabricated passes without a CDP connection; `StealthInjector` performs real CDP script injection; session capture/restore works with real CDP clients; JS injection payloads correctly escaped; proxy health check performs a real `httpx` probe instead of marking everything unhealthy.
- **R1 — fingerprint persistence**: default-constructed `FingerprintDatabase()` now loads persisted files on init, so API-added templates survive restarts.
- **R2 — detection tester integrity**: `DetectionTester.run_all` fails on zero parsed checks (sannysoft/creepjs/fingerprintjs) instead of fabricating 3/3 passes from empty page text; real `parse_fingerprintjs` implemented.
- **R3 — event-loop stall**: `/proxy/health` handlers now await async probes — an unreachable proxy can no longer freeze the event loop for 10s+.

#### Tests

- 11 regression tests for R1/R2/R3 (load-on-init persistence, empty-page → 0/3 passed, 50ms-ticker loop-responsiveness).
- Overshoot target assertion made deterministic (random direction).
- 12 stale RED-phase markers removed, stale RED-phase tests cleaned from compositor and modules, 15 new ruff errors resolved.
- Anti-detection suite green at release: 509 passed / 0 failed (tech-lead approval run); full suite failures unchanged vs pre-sprint baseline.

#### Docs

- Expanded anti-detection documentation and examples (proxy rotation, profile manager, behavioral simulation, fingerprint randomization, cloud provider setup) and README feature table.
- New v1.8.0 per-feature guides: [Proxy Rotation Manager](docs/proxy-rotation-manager.md), [Fingerprint Database](docs/fingerprint-database.md), [Session Persistence](docs/session-persistence.md), [Anti-Detection Compositor](docs/anti-detection-compositor.md).
- New runnable examples: [examples/proxy_rotation.py](examples/proxy_rotation.py), [examples/fingerprint_database.py](examples/fingerprint_database.py), [examples/session_persistence.py](examples/session_persistence.py), [examples/anti_detect_compositor.py](examples/anti_detect_compositor.py).
- README: v1.8 features table, version/python/tests badges, `PROXY_LIST`/`PROXY_FILE` quick-start section, test count updated to 1,986 passed (v1.8.0 gate).

### [1.7.0] — 2026-07-30

#### Added

**Anti-Detection Profile Manager (Component 4)**
- Create browser profiles from 4 predefined fingerprint templates: `stealth-chrome-120`, `mobile-safari-ios`, `firefox-linux`, and `edge-windows` — each with realistic user-agent, screen, WebGL, canvas, audio, and timezone settings.
- `AntiDetectionProfile` dataclass extends the existing `Profile` with `profile_type` and `fingerprint` fields for anti-detection configuration.
- Profile selection strategies: `random` (uniform), `sticky` (session-pinned), and `geo-match` (timezone-based) — see `ProfileManager.select_profile_for_request()`.
- `ProfileValidator` static analysis detects inconsistencies (UA vs platform mismatches, missing fields) and provides remote checker references.
- See [Anti-Detection Profile Manager](docs/anti-detection-profile-manager.md).

**P1-1 Anti-Detection Signal Modules** (`src/anti_detection/signal_modules.py`)
- `CanvasFingerprinter` — JS patches to inject noise into canvas `toDataURL`/`toBlob`/`getImageData` calls with seeded hashing for deterministic per-session output.
- `WebGLSpoofer` — overrides `getParameter(37445)` (UNMASKED_VENDOR_WEBGL) and `getParameter(37446)` (UNMASKED_RENDERER_WEBGL) with profile-matched GPU strings.
- `NavigatorSpoofer` — patches `navigator.userAgent`, `platform`, `language`, `languages`, `hardwareConcurrency`, and `deviceMemory` via `Object.defineProperty`.
- `AudioContextRandomizer` — adds sub-percent variance to `AudioBuffer.getChannelData()` output to defeat audio fingerprinting.
- `ScreenColorConsistency` — ensures `screen.colorDepth` and `screen.pixelDepth` match the profile's declared depth.
- `TLSFingerprintAligner` — TTL and JA3 fingerprint alignment hooks for browser-based fingerprint consistency.

**P1-2 Fingerprint Randomization** (`src/anti_detection/fingerprint_randomizer.py`)
- `FingerprintRandomizer.build_canvas_patch()` — generates JS that offsets canvas readout RGBA values with profile-specific pixel offsets.
- `FingerprintRandomizer.build_webgl_patch()` — generates JS that overrides WebGL vendor and renderer strings.
- `FingerprintRandomizer.build_audio_patch()` — generates JS that adds noise to `AudioContext.createBuffer()` output.
- Integration with `FingerprintEngine` (`src/fingerprint_engine.py`) — per-session seeded noise generation with curated GPU vendor/renderer pools (NVIDIA, AMD, Intel, Apple) and `FingerprintConfig` dataclass for 14 configurable fingerprint dimensions.
- See [Fingerprint Randomization](docs/fingerprint-randomization.md).

**Behavioral Simulation Engine (Component 3)**
- `BehavioralSimulator` (`src/behavioral_sim.py`) — static-method API for generating human-like interaction patterns:
  - `wind_mouse_bezier()` — WindMouse physics + Bezier micro-correction for smooth mouse trajectories with variable velocity (200-800ms per 200px).
  - `keystroke_timing()` — per-character dwell/flight timing with ~5% typo+backspace probability, WPM range 40-80.
  - `scroll_sequence()` — momentum scroll with power-law decay (Incomplete Gamma), overshoot+correction in 30% of calls.
  - `click_position()` — Gaussian spatial jitter (sigma=4px) around element centre.
- `anti_detection.behavioral_simulation` — CDP-level simulators with WebSocket dispatch:
  - `MouseSimulator` — cubic Bezier mouse paths with variable velocity, dispatches `Input.dispatchMouseEvent`.
  - `TypingSimulator` — per-character dwell (80-250ms), burst variation, ~3% typos with backspace, dispatches `Input.dispatchKeyEvent`.
  - `ScrollSimulator` — momentum scroll with overshoot/correction, dispatches `Input.dispatchMouseEvent` wheel.
  - `ClickSimulator` — normal-distribution spatial jitter (sigma=4px), dispatches `Input.dispatchMouseEvent` click.
  - `TabFocusSimulator` — realistic focus/blur timing (10-60s loss), dispatches `Page.handleJavaScriptDialog`.
- See [Behavioral Simulation](docs/behavioral-simulation.md).

**Cloud Browser Provider Integration** (`src/browser_providers/`)
- Abstract `BaseProvider` with full lifecycle: `launch_sandbox()` → `get_cdp_endpoint()` → `mark_warm()` → `close_session()`.
- `BrowserbaseProvider` — connects to Browserbase API (`https://www.browserbase.com/api/v1`) using `BROWSERBASE_API_KEY` and `BROWSERBASE_PROJECT_ID` env vars. Launches sandboxed browser sessions, retrieves CDP WebSocket URLs.
- `SteelProvider` — connects to Steel Browser API (`https://api.steelbrowser.com/v1`) using `STEEL_API_KEY` env var. Supports headless browser sandbox sessions with CDP endpoints.
- `CloudSessionPool` — manages warm session pool with auto-scaling (`min_warm=1`, `max_warm=5`), TTL expiry (300s default), cost tracking, and provider fallback chain.
- `FallbackResult` tracks the provider chain attempted and per-step errors for observability.
- See [Cloud Provider Setup](docs/cloud-provider-setup.md).

**Fingerprint REST API** (`/profile/{name}/fingerprint`)
- `POST /profile/{name}/fingerprint` — generate a randomised fingerprint with 11 dimensions (canvas offset, WebGL, hardware concurrency, device memory, screen resolution, color depth, timezone, platform), optional `overrides` dict to pin specific values.
- `GET /profile/{name}/fingerprint` — retrieve the current `fingerprint` and `fingerprint_config` for a profile.
- `PUT /profile/{name}/fingerprint` — set fingerprint configuration (14 known config fields) with field-name validation.
- `POST /profile` (anti-detection variant) — create profiles from predefined types via `create_anti_detection_profile()`.
- See [Fingerprint REST API](docs/fingerprint-randomization.md#rest-api).

#### Fixed
- Restored `BrowserbaseProvider`, `SteelProvider`, and `CloudSessionPool` implementations from upstream with corrected test suite (102/102 tests passing, ruff clean).
- Removed duplicated return annotation syntax error in `profile_manager.py` that caused `SyntaxError` on import.
- Added `generate_fingerprint()` method from upstream merge for fingerprint profile compatibility.
- Cloud provider restore verified with cross-commit diff detection: 4 files, 791 insertions restored, no collateral damage.

### [1.5.0] - 2026-07-29

#### Added
- Post-action `verify_after` checks with visible text or selector verification and `verified`, `actual_text`, and elapsed-time evidence.
- One-call autocomplete form resolver that fills, emits input/change events, waits for popup options, and selects the first matching option.
- `include_hidden` accessibility observation for ignored or hidden AX nodes.
- `select_tab` and detailed `wait_for_element` agent actions.
- `page_with_history` form discovery, which performs bounded scrolling to trigger SPA lazy loading.
- Workflow replay contract aliases `recorded_id`, `on_error`, and recursive `data_overrides` while preserving the previous `recording_id` input.

#### Changed
- Agent Navigation Engine capability version advanced to 1.5.0.
- Workflow recording accepts the explicit `{"start": true}` contract.

### [1.4.0] - 2026-07-29

#### Fixed
- Prevented snapshot eviction during `/agent/act` with reference-counted pin/unpin and a 200-snapshot default capacity.
- Removed the pre-action re-observation race and added one-shot stale-ref recovery by accessible name.
- Added legacy-to-accessibility fallback for SPA dropdown and portal text missing from condensed snapshots.
- Exposed direct `target.backend_node_id` click/fill actions without requiring a snapshot.
- Replaced fragile placeholder CSS construction with literal input/textarea placeholder scanning.
- Added automatic modal accessibility scope and modal form discovery.

#### Added
- `pin_snapshot`, `auto_recover`, `fallback`, `search_text`, and `auto_modal` request controls.
- Process-local workflow record/stop/replay endpoints.
- Seven focused regressions covering the reported root causes and workflow replay.

### [1.2.0] — 2026-07-28

#### Added
- **Proxy rotation support** — `ProxyPool` manager with CRUD operations, health checks, and 4 rotation strategies (round-robin, random, least-used, sequential)
- **Proxy REST API** — `POST /proxy/pool` (add), `GET /proxy/pool` (list), `DELETE /proxy/pool/{name}` (remove), `GET /proxy/health/{name}` (health check), `GET /proxy/stats` (pool statistics)
- **`--proxy-server` flag integration** — Headless and visible Chrome sessions launch with `--proxy-server` via new `proxy` field in session launch requests
- **Proxy authentication support** — SOCKS5, HTTP, and HTTPS proxy auth with `user:pass@` credentials, redacted from logs
- **Proxy health monitoring** — Periodic health pings with configurable timeout, dead proxy eviction with auto-retry
- **Credential leak fix** — Chrome command-line `--proxy-server` flag now redacts `user:pass@` to `***:***@` before logging
- **123 new tests** — `test_proxy_manager.py`, `test_proxy_api.py`, `test_proxy_edge_cases.py` covering proxy pool CRUD, health checks, rotation strategies, authentication, and API integration

#### Changed
- `src/headless_manager.py` — Added `proxy` field to session launch, credential redaction in logging
- `src/chrome_manager.py` — Added `proxy` field to launch parameters
- `src/main.py` — Registered proxy REST endpoints
- `SKILL.md` — Added proxy setup and usage guide

### [1.1.0] — 2026-07-28

#### Added
- **`/form/fill` enhanced field lookup** — Fields now support `selector` (direct CSS), `placeholder` (exact match), and `nth` (index among matches) in addition to `label` smart lookup. Shorthand format: `{"selector": "#id", "text": "value"}`
- **Contenteditable support** — `smart_form_fill` detects `contenteditable` elements and sets `textContent` instead of `.value`
- **`/script` complete action list** — Documented all 28 supported actions in SKILL.md and endpoint docstring: `navigate`, `click`, `click_text`, `click_label`, `type`, `eval`, `form_fill`, `form_select`, `find_element`, `wait`, `wait_for_element`, `wait_text`, `wait_for_navigation`, `wait_for_network_idle`, `scroll`, `screenshot`, `full_page_screenshot`, `element_screenshot`, `get_text`, `pdf`, `upload_files`, `get_iframe_text`, `switch_to_iframe`, `get_page_outline`, `analyze_page`, `page_diff`, `close`
- **14 new tests** — `test_v11_features.py`: FormFillField model (selector/placeholder/nth), FormFillRequest backward compat, ScriptRequest, contenteditable detection

#### Changed
- `FormFillField` model: `label` is now optional (was required); added `selector`, `placeholder`, `nth` fields
- `smart_form_fill` JS rewritten: uses `findAllByLabel()` returning array + nth indexing, supports direct CSS selector and exact placeholder match
- SKILL.md `/form/fill` section fully rewritten with new field types and examples
- SKILL.md `/script` section now lists all 28 actions with params and descriptions

### [1.0.0] — 2026-07-28

#### Added
- LLM agent API: `/agent/capabilities`, `/agent/observe`, and `/agent/act`
- Stable snapshot-scoped element references and stale snapshot detection
- Token-budgeted cursor pagination and differential observations
- Artifact store with SHA-256, expiry metadata, and `/artifacts/{artifact_id}` download
- Dashboard controls for agent observation, discovery, and capture
- Targeted tests for agent runtime, artifacts, headless CDP execution, API errors, and endpoints

#### Changed
- Headless evaluation now executes `Runtime.evaluate` over CDP WebSocket
- Headless screenshots now execute `Page.captureScreenshot` and return artifacts
- Agent and headless APIs use a unified response envelope and proper non-2xx errors
- Project version and documented default port are consistently 1.0.0 and 8000


## [0.7.0] — 2026-07-27

### Added

- **Tab auto-activation (P0)** — Every interactive CDP operation (`navigate`, `evaluate`, `click`, `type`, `screenshot`, `full_page_screenshot`, `element_screenshot`, `get_page_text`, `dom_query`, `dom_click_all`, `get_cookies`, `set_cookie`, `clear_cookies`, `pdf`, `open_new_tab`, `close_tab`, `switch_tab`, `smart_form_fill`, `wait_for_element`, `click_by_text`, `click_label`, `checkbox_set_state`, `upload_files`, `form_select`, `get_iframe_text`, `switch_to_iframe`, `get_page_outline`) now calls `_activate_current()` (`Target.activateTarget`) before execution — transparently wakes the tab from discarding so it's ready
- **`POST /activate-tab/{tab_id}`** — Manually activate a specific tab by target ID
- **Checkbox/radio state visibility (P1)** — `POST /page/analyze` now returns `selected_options` (list of checked checkboxes/selected radios) and `visual_state` (dict mapping label → `{checked, type, value}` for all visible checkboxes/radios)
- **Condensed snapshot mode (P2)** — `POST /page/analyze?condensed=true` strips nav/sidebar/footer elements, returns only main content. Includes summary counts (`field_count`, `button_count`, `checkbox_count`, `radio_count`, `modal_count`) and reports `condensed_fallback: true` when no main container found
- **Batch checkbox/radio operations (P2)** — `POST /checkbox/select` and `POST /checkbox/deselect` for single (`{"text": "..."}`) or batch (`{"texts": ["...", "..."]}`) mode. Framework-safe label-based targeting with real CDP clicks
- **Screenshot confirmation (P2)** — `?confirm=screenshot` or `?confirm=analyze` query parameter on `/click/text`, `/click/label`, `/checkbox/select`, `/checkbox/deselect` endpoints. Standalone `POST /confirm-action` endpoint for arbitrary post-action confirmation
- **`POST /confirm-action`** — Standalone endpoint for screenshot/analyze confirmation after any action

## [0.5.0] — 2026-07-26

### Added

- **Visual regression testing** with screenshot diff engine (Pillow ImageChops.difference)
- **Baseline snapshot management** — capture, store, list, delete with profile-aware scoping
- **REST API** — `POST /screenshot/baseline`, `POST /screenshot/compare`, `GET /screenshot/baselines`, `DELETE /screenshot/baseline`
- **CI/CD-friendly JSON output** with configurable pass/fail threshold (default 0.1%)
- **Profile-aware baseline scoping** — baselines isolated per browser profile
- **38 new integration and edge-case tests** for screenshot diff, baseline management, and screenshot API

## [0.4.0] — 2026-07-26

### Added

- **ProfileManager** — create, read, update, delete browser profiles with JSON persistence (follows SettingsManager pattern)
- **Profile dataclass** — stores name, description, tags, data directory, extensions list, resource limits, and timestamps
- **Profile-aware headless sessions** — launch headless Chrome with a named profile's isolated data directory and extensions
- **Per-profile extension loading** — extensions stored per-profile, loaded automatically on session launch
- **Profile import/export (ZIP)** — export profile data + extensions as a ZIP archive; import from ZIP with validation and path-traversal protection
- **REST API for profile management** — `GET /profiles`, `POST /profiles`, `GET /profiles/{name}`, `PUT /profiles/{name}`, `DELETE /profiles/{name}`, `POST /profiles/{name}/export`, `POST /profiles/import`
- **83 new tests** covering ProfileManager CRUD, profile-aware headless sessions, profile import/export, and profile REST API endpoints

## [0.3.0] — 2026-07-26

### Added

- **Headless Chrome sessions** — launch, manage, and close headless Chrome instances via REST API
- **SessionPool** — manages concurrent headless sessions with configurable max limit (default 5)
- **HeadlessManager** — full session lifecycle: launch, navigate, evaluate, screenshot, batch screenshot
- **ResourceMonitor** — per-process CPU and memory tracking using psutil
- **Timeout guards** — auto-kill sessions exceeding configurable timeout (default 300s)
- **Resource limits** — auto-kill sessions exceeding CPU threshold (80%) or memory limit (512MB)
- **8 new REST endpoints**:
  - `POST /headless/launch` — launch new headless session
  - `POST /headless/close` — close session by ID
  - `GET /headless/sessions` — list active sessions with resource usage
  - `POST /headless/navigate` — navigate session to URL
  - `POST /headless/eval` — evaluate JavaScript in session
  - `POST /headless/screenshot` — take screenshot
  - `POST /headless/batch-screenshot` — multiple screenshots in sequence
  - `GET /headless/health` — pool stats and per-session resource usage
- **psutil dependency** for process resource monitoring
- **30 new tests** (resource monitor, headless manager, headless API)

### Changed

- `ChromeManager.launch()` now accepts `headless: bool = False` parameter
- When `headless=True`, Chrome is launched with `--headless=new` flag

## [0.2.0] — 2026-07-24

### Added

- WebSocket streaming and GUI dashboard
- FastAPI server with browser endpoints and image compression
- Core CDP client with WebSocket automation
- Docker containerization
- Session save/restore
- Network monitoring
- Smart form fill, click by text, wait for element/text/navigation
- Page analysis, diff, outline, iframe support
- Cookie management
- Tab management (list, scan, deep-scan, switch)
- Script execution engine
- PDF export
- Element and full-page screenshots

## 1.6.0 - 2026-07-30

### Added
- Zero-trust browser policy primitives with private-network denial.
- Redacted session replay events, expiring human takeover leases, deterministic workflow export, tenant fleet quotas and evaluation release gates.
- Six responsive enterprise operations consoles and additive `/api/v1/enterprise` endpoints.
- Deterministic domain, persistence, security, accessibility and route-contract tests.
