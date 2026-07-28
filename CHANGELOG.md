# Changelog

All notable changes to browser-helper will be documented in this file.

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
