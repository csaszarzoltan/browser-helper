# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
  ([src/ws_manager.py](src/ws_manager.py),
  [src/schemas.py](src/schemas.py))

- **GUI dashboard** (`static/index.html`) — full-featured browser control panel
  served at `GET /`. Panels: Connection, Quick Actions, Screenshot Preview,
  Operation Log, Tabs, Network Log, Cookies, Script Runner, Session Manager,
  JS Console. Connects to the WS endpoint for live updates.

- **CDP Event Forwarder** (`src/cdp_events.py`) — `CDPEventForwarder` listens
  for CDP `Runtime.consoleAPICalled` and `Page.frameNavigated` events and
  broadcasts them to WebSocket clients as `console_log` and `navigation`
  messages.

- **WebSocket Manager** (`src/ws_manager.py`) — `WebSocketManager` tracks
  connected clients with per-client metrics, heartbeat loop (ping every 30s),
  stale-connection pruning after 3 missed pongs, broadcast and personal
  messaging.

- **Event schema** (`src/schemas.py`) — `WsMessage` envelope class plus 8
  factory functions: `make_hello`, `make_state_update`, `make_console_log`,
  `make_navigation`, `make_operation`, `make_ping`, `make_pong`, `make_error`.
  All messages carry ISO-8601 UTC timestamps.

- **CDPClient event callback API** (`src/cdp_client.py`) — `add_event_listener`
  and `remove_event_listener` methods for subscribing to CDP events by method
  name, plus event dispatch in the `_listener` loop.

- [docs/api-reference.md](docs/api-reference.md) — expanded WebSocket section
  with full message type table, schema details, and JS/client examples.
- [docs/advanced-features.md](docs/advanced-features.md) — added CDP Event
  Forwarding and WebSocket Streaming sections.
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

- 36 new interface tests for `ws_manager`, `schemas`, `cdp_events`, `main_ws`
  (all passing)
- 4 new interface tests for `WsMessage` schema (all passing)
- 5 new test files: `test_ws_manager.py`, `test_schemas.py`,
  `test_cdp_events.py`, `test_main_ws.py`, `test_dashboard.py`
- 25 tests skipped (Playwright/browser-level — out of scope)
- 19 behavioural stub tests still fail as expected (RED-phase → GREEN-phase
  transition, to be rewritten as real behavioural tests)

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
