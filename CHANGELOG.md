# Changelog

All notable changes to browser-helper will be documented in this file.

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
