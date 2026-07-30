# Changelog

All notable changes to browser-helper will be documented in this file.

### [1.7.0] — 2026-07-30

#### Added
- **Anti-Detection Profile Manager (Component 4)** — create, configure, and manage browser fingerprint profiles with per-profile anti-detection settings, fingerprint configuration, and persistent storage.
- **P1-1/P1-2 Anti-Detection Modules** — behavioral anti-detection modules with full test coverage, preventing browser fingerprinting and automation detection.
- **Behavioral Simulation Engine (Component 3)** — realistic human-like behavior simulation engine for browser automation, reducing detection risk.
- **Cloud Browser Provider Integration** — `BrowserbaseProvider`, `SteelProvider`, and `CloudSessionPool` implementations for cloud-hosted browser sessions with proper error handling, lifecycle management, and test coverage.
- **Fingerprint REST API** — endpoints for fingerprint configuration, `generate_all_scripts` profile method, and `ProfileManager.fingerprint_config` methods.

#### Fixed
- Restored cloud provider implementations (Browserbase, Steel, CloudSessionPool) from upstream with corrected test suite.
- Removed duplicated return annotation syntax error in `profile_manager.py` that caused `SyntaxError` on import.
- Added `generate_fingerprint` method from upstream merge for fingerprint profile compatibility.

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
