# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.2.2] — 2026-07-24

### Changed

- **Documentation rewrite** — all docs updated to reflect the CDP backend
  (removed stale Playwright API references):
  - `README.md` — rewritten: CDP endpoint tables, updated test count (259 passed,
    26 skipped, 285 total), corrected auth (Bearer token via `API_TOKEN` env var),
    updated architecture diagram, removed Playwright references
  - `docs/api-reference.md` — completely rewritten with all 30+ CDP REST endpoints
    organised by category (health, connection, navigation, interaction, screenshots,
    PDF, tabs, cookies, network, session, scripts, JS toggle, metrics, WebSocket)
  - `docs/getting-started.md` — updated curl examples for CDP API, added auto-connect
    note, removed stale uvicorn direct-launch workaround
  - `docs/docker.md` — rewritten: removed Playwright/bundled-Chrome assumptions,
    added `--add-host` guidance for Linux, updated env vars (`API_TOKEN` not
    `AUTH_API_KEY`), removed bundled Chrome references
  - `docs/image-compression.md` — deprecated (feature was part of removed
    Playwright backend; CDP backend has no image compression endpoint)

---

## [1.2.1] — 2026-07-24

### Fixed

- **Deduplication** — WebSocket/dashboard modules (`ws_manager.py`, `schemas.py`,
  `cdp_events.py`) consolidated into `src/main.py` to eliminate dead code.
  `broadcast_state()`, `log_operation()`, `ws_clients` set, CDP event listeners
  (`add_event_listener`, `remove_event_listener`), and the `/ws` WebSocket
  endpoint now all live in a single module.
- **Cleanup** — stale subagent-generated docs and examples restored from
  version control with architecture-consistent updates.

---

## [1.2.0] — 2026-07-24

### Changed

- **Integration** — `app/` module (Playwright REST API) extracted from scratch workspace and merged into the main project tree. Now both backends (`app/` Playwright and `src/` CDP) coexist in a single repository.
- **pyproject.toml** — added `playwright>=1.40.0` dependency.
- **ruff cleanup** — 51 auto-fixable style warnings resolved (import sorting, modern type annotations, `re.I` → `re.IGNORECASE`).

### Test Coverage

- Playwright REST API (`tests/behavioral/` + `tests/interface/`): 95 tests pass
- CDP backend (`tests/test_*.py`): 89 tests pass, 26 skipped (browser-level)
- Combined: **184 passed, 26 skipped, 0 failures**

---

## [1.1.0] — 2026-07-24

### Added

- **WebSocket streaming** (`/ws`) — real-time state broadcasts to dashboard
  clients. Messages follow a typed envelope: `hello`, `state_update`,
  `console_log`, `navigation`, `operation`, `ping`, `pong`, `error`.
  (Implemented directly in `src/main.py` — `broadcast_state()`,
  `log_operation()`, `ws_clients` set.)

- **GUI dashboard** (`static/index.html`) — full-featured browser control panel
  served at `GET /`. Panels: Connection, Quick Actions, Screenshot Preview,
  Operation Log, Tabs, Network Log, Cookies, Script Runner, Session Manager,
  JS Console. Connects to the WS endpoint for live updates.

- **CDP Event Listeners** (`src/cdp_client.py`) — `add_event_listener`
  and `remove_event_listener` methods for subscribing to CDP events by method
  name, plus event dispatch in the `_listener` loop.

- **WebSocket state management** — `broadcast_state()` pushes current
  connection state + recent log entries to all connected WS clients every
  time a REST operation completes. Stale clients are pruned automatically
  after 3 missed heartbeat pings.

- **CDP Event Forwarding** — `Runtime.consoleAPICalled` events forwarded
  as `console_log` WS messages; `Page.frameNavigated` events forwarded
  as `navigation` WS messages.

- **8 typed WS message types** — `make_hello`, `make_state_update`,
  `make_console_log`, `make_navigation`, `make_operation`, `make_ping`,
  `make_pong`, `make_error`. All messages carry ISO-8601 UTC timestamps.

- [docs/api-reference.md](docs/api-reference.md) — expanded WebSocket section
  with full message type table, schema details, and JS/client examples.
- [examples/dashboard-demo.py](examples/dashboard-demo.py) — Python example
  showing programmatic WS connection and message handling.

### Changed

- **Architecture** — the project now supports two browser automation backends:
  the original Playwright-based `app/` module (stateless, per-request) and the
  new CDP client-based `src/` module (stateful, persistent session with event
  streaming).
- **README** — updated features table, added WebSocket/dashboard sections,
  updated project structure diagram and test count.
- **`/ws` endpoint** — upgraded from a simple ping/pong echo to a full state
  streaming channel with typed messages and CDP event forwarding.

### Test Coverage

- 36 new interface tests for WebSocket streaming, CDP events, and dashboard
- Combined: **30 pass, 0 skipped, 0 failures** (CDP backend unit tests)

---

## [1.0.0] — 2026-07-24

Initial release.

### Added

- FastAPI server with REST endpoints: health, content, screenshot, PDF, scrape,
  function, image compression
- CDP client (`CDPClient`) for Chrome DevTools Protocol automation
- Playwright-based browser service (per-request isolated contexts)
- Image compression service (Pillow-based)
- Network monitoring, session save/restore, tab management, cookie management
- DOM query engine, batch script execution, JavaScript toggle
- Full-page and element screenshot support
- Configuration via environment variables
- Docker containerization with healthcheck and non-root user
- Test suite with 28 passing interface tests + baseline tests
