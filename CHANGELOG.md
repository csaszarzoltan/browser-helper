# Changelog

All notable changes to browser-helper will be documented in this file.

## [Unreleased]

## [1.27.4] — 2026-08-13

#### Added
- **Domain-level navigation throttle** — a per-netloc rate limiter that prevents hammering external sites (Google, GitHub, …) when multiple systems share one browser-helper instance. Navigations to the same domain within `domain_min_interval_sec` (default **4.0s**, configurable via `settings.json` or `POST /settings`) are held back. Implemented in `src/domain_throttle.py`, enforced inside `run_op` so every entry point (REST `/navigate`, `/search`, `/download`, MCP `navigate`) is covered.
- **`scripts/release-validate.sh`** — single-source release validation: checks pyproject == `main.py` == README badge == CHANGELOG == Dockerfile label, and the MCP tool count (from `build_tool_defs()`) against the docs.

#### Changed
- **Dockerfile image version label 1.20.0 → 1.27.3** — the label now matches the pyproject version (release-hygiene pitfall: the version lives in two places).
- **Docs tool counts 12/15/19 → 32** — `README.md`, `docs/mcp-server.md`, `docs/mcp-memory.md`, `docs/architecture/mcp-server-design.md` now all agree on 32 tools (28 browser/fleet + 4 memory).
- **pytest markers deduplicated** — `pyproject.toml` had two `quick` and two `integration` marker definitions; merged into one each.
- **TEST_RESULTS.md refreshed** (2026-08-13) — 2636 passed, 1 skipped, 41 xfailed, 32 xpassed; MCP live E2E 4/4.

## [1.27.3] — 2026-08-12

#### Fixed
- **MCP live E2E now runs against a dedicated test Chrome** — the test fixture launches its own headless profile on its own port (passed via `CHROME_AUTO_PORT`), so the production Chrome (port 9555) is never touched by the test suite. No more flaky `PUT /json/new` HTTP 500 from tab accumulation on the live browser.
- **MCP tool sessions route explicitly (`sess_override`/`session_hook`)** — tool calls ran on the global browser-level WebSocket because the `_current_session` contextvar doesn't survive FastMCP task isolation, so `Page.navigate` failed with "browser-level attach failed". `run_op` now accepts an explicit session override and the MCP layer caches the minted session.
- **`CHROME_AUTO_PORT` env takes precedence** in both `_local_cdp_http()` and `chrome_manager.launch()` — a test-specified port previously never reached the MCP subprocess (it kept dialing the production 9555).
- **`CDPClient.navigate` invalidates the tab cache before navigating** — the 5s `discover_tabs` cache returned stale tab lists for data:/same-origin navigations.
- **`run_op` materializes results once** — async/sync generators, lists and dicts are converted before logging/serialization, eliminating the `"Cannot reuse already used iterator"` crash (the operation logger consumed a generator, then the response serializer tried to consume it again).
- **`POST /navigate` auto-waits for network idle + DOM stability** (best-effort, 8s cap) so the response's `connected: true` is truthful.
- **`409 Conflict` for existing-but-disconnected sessions** — a session whose CDP connection is lost now returns a clear 409 instead of a misleading success envelope (503 stays for real launch/connect infra failures).
- **Placeholder API tokens rejected with 401** — `changeme`, `your-token`, `replace-me`, … no longer silently open the API.

#### Added
- **`GET /mcp-status`** — SDK-free MCP readiness + per-session tool visibility: `{"sessions": [{"id", "mcp_connected", "tools"}], "mcp_enabled", "tool_count"}`.
- **`MCP_ENABLED=1` in the systemd unit** — MCP is now on by default; `/mcp-status` reports `mcp_enabled: true`.

#### Changed
- **`session_registry.create()` drops the client tab cache** before `connect_to_target`, so the WebSocket binds to the freshly opened tab (was: stale-cache tab mismatch after `discover_tabs`).

## [1.27.2] — 2026-08-12

#### Fixed
- **`POST /type` returns 404 "Element not found"** when the selector matches nothing (was: misleading 200 OK — same envelope bug as `/click` in v1.27.1). The `/type` endpoint now unwraps the inner CDP status.
- **Behavioral engine `type_text` no longer types blindly into the void** — when `document.querySelector` returns null, it returns `{status: "error", error: "Element not found: <selector>"}` immediately instead of typing into thin air (the non-behavioral path checked the element; the behavioral path did not).
- **MCP `click`/`type` tools unwrap inner errors** — a missing element now surfaces as a clear tool error, not a misleading success envelope.
- **systemd service now runs from the HOME clone** (`/home/zoltan/browser-helper`) — the kanban workspace clone was deleted by cleanup, which left the service stuck in "activating" with no API. The workspace clone is not a reliable base for systemd.
- **Browser-helper watchdog cron** — `browser-helper-watchdog.sh` runs every minute (no_agent); silent when healthy, restarts the service and notifies if `/health` stops responding.

## [1.27.1] — 2026-08-11

#### Fixed
- **`POST /navigate` accepts the URL in the JSON body** (`{"url": "..."}`) in addition to the legacy `?url=` query param. Previously a body-only caller got a bare 422 and — worse — their session stayed on `about:blank`, so subsequent clicks silently ran on a blank tab (the "Uncaught" agent-incident). A missing URL now returns a clear, actionable 422: `"Missing 'url' — pass it as ?url=... query param OR JSON body {...}"`.
- **`POST /click` returns 404 "Element not found"** when the selector matches nothing on the current tab (was: misleading 200 OK wrapping `{status: "error"}` inside `data`, which callers misread as a successful click). The unwrap now checks the inner CDP status.
- **`CDPClient.click` treats an empty/undefined JS result as "Element not found"** — previously a JS exception inside `scrollIntoView`/`getBoundingClientRect` produced `ok @ (0,0)` and dispatched a click on the page corner. Now it returns `{status: "error", error: "Element not found: ..."}`.
- **`BehavioralSimulator.keystroke_timing` is deterministic** — the RNG was seeded with `hash(text)` (PYTHONHASHSEED-randomized per process) and then reseeded with a fresh unseeded `Random()`, making typo generation fully non-deterministic and the `test_occasional_typo_backspace` test flaky. Now seeds via `crc32(text)` and drops the dead reseed. Verified: 20/20 runs pass across different `PYTHONHASHSEED`s.
- **scipy added to the dev venv** — fixes the two pre-existing rate-limiter KS tests (`ModuleNotFoundError: scipy`).

## [1.27.0] — 2026-08-11

#### Added — Agent Toolkit (6 features)

- **F1 — Auth-session clone**: `POST /session/{sid}/export-cookies`, `POST /session/{sid}/import-cookies`, `POST /session/{sid}/clone` + `CDPClient.set_cookies` (bulk). MCP: `export_cookies`, `import_cookies`, `clone_session`. Lets you port a logged-in session (e.g. Cloudflare `cf_clearance`) across profiles/browsers.
- **F2 — Wait-for / assertion engine**: `POST /wait/for` (selector|text|url × present|gone|visible) + `POST /assert` (exists|not_exists|count|contains, 409 on failure) + `CDPClient.wait_for_condition` / `assert_elements`. MCP: `wait_for`, `assert`. Deterministic UI testing — no sleep-guessing.
- **F3 — Form-intelligence**: `POST /form/extract` + `CDPClient.form_extract` (label/type/required/visible per field). MCP: `form_fill`, `form_extract`. Discover SPA forms before filling.
- **F4 — Fleet run-batch**: `POST /fleet/run-batch` — parallel isolated browsing tasks (1-8 concurrency), per-task error isolation, aggregated report. MCP: `fleet_run_batch`.
- **F5 — Download helper**: `POST /page/download` + `CDPClient.download_file` (Browser.setDownloadBehavior + poll), artifacts stored via `ArtifactStore` (`GET /artifacts/{id}`). MCP: `download`.
- **F6 — Network interception**: `POST /network/block` + `CDPClient.set_network_block` (Fetch.failRequest, regex patterns); `POST /network/mock` (existing) now has MCP: `network_block`, `network_mock`. Block analytics/trackers or test error paths deterministically.

## [1.26.3] — 2026-08-11

#### Fixed
- **Chrome double-launch storm (watchdog vs run_op)**: when a request path (`run_op`) triggered `chrome_mgr.launch()`, the in-flight launch was invisible to the health watchdog — a watchdog tick landing inside the warm-up window (CDP port momentarily unreachable) decided "Chrome not running" and launched a SECOND Chrome. The two instances fought over the profile SingletonLock and both died, producing `json/new` 500s and repeated launch storms. **Fix:** `ChromeManager._launch_in_progress` flag — set at the start of `launch()`, cleared on every return path. A concurrent `launch()` waits for the in-flight one and reuses its result; the watchdog skips relaunching when a launch is already in progress. Verified live: 5 watchdog cycles, 0 restarts, `Chrome launched on port 9557 (PID …)` reuses the same PID.

## [1.26.2] — 2026-08-10

#### Fixed
- **Chrome restart loop (user-observed: "Chrome újraindul túl gyakran")**: the health watchdog watched the GLOBAL client's WS state (`client.is_connected`). Since v1.24 all traffic runs on per-session CDPClients, so the global client was often disconnected while Chrome was perfectly healthy — and `_reap_orphan_tabs` closing unowned tabs killed its page-target WS. The watchdog misread this as "Chrome dead" and auto-restarted every 5 min (repeating the 10s proxy warm-up + soft-start hold + possible auth-dialog flash). **Fix:** watchdog now probes the CDP HTTP port (`/json/version`); the global client attaches to the **browser-level WebSocket** (`/devtools/browser/<id>`) via new `CDPClient.connect_browser()`, which survives tab churn. Verified live: 3-session churn keeps `connected: true`; a full watchdog cycle runs with zero restarts.
- **`_ws_tab_id` overwritten to None in `connect()`**: the Fix-1 tab-drift binding (`self._ws_tab_id = target_id`) was immediately clobbered by a leftover `self._ws_tab_id = None` — the drift guard/listener filter never worked for clients attached via `connect()`. Removed the stale line.

#### Changed
- `_ensure_global_client_attached()` helper: startup, watchdog, and auto-launch paths all use browser-level attach.

## [1.26.1] — 2026-08-10

#### Fixed
- **Parallel session isolation (3-layer)**: `_ws_tab_id` tracking + listener filter (external targets ignored), `_send_command` drift-guard, 1-tab-per-session enforcement (`/navigate` roams + closes old tab, `/tab/new` navigates existing). Fixes cross-session screenshot/eval/observe bleed under parallel agent load.
- **`/agent/search` parallel tab-overwrite**: eager `_resolve_session_client()` before the first `run_op` so the navigate lands on the caller's OWN tab from the very first call (was racing on the shared default tab).
- **Port priority**: `CHROME_AUTO_PORT` (run.py `--debug-port`) now wins over `settings.json` at auto-connect — prevents silent reattach to the wrong Chrome (9555 SSH tunnel vs 9557 VNC Chrome).
- **Proxy-extension soft-start force-hold**: `ChromeManager._launched_at` + `await_chrome_ready()` called from `_ensure_browser()` and `run_op()` — requests arriving during the warm-up window are held instead of bypassing the proxy (auth-dialog flash).

#### Added
- **MCP `observe` + `act` tools** (`agent.semantic`): the REST-only agent endpoints now have an MCP surface (was `Invalid argument 'name'`). 21 MCP tools total.
- **Parallel session isolation regression test**: `tests/test_parallel_session_isolation.py` — two concurrent cookie-jar clients navigate + `/agent/search` without tab overwrite (skips when live service down).

#### Changed
- **Test infra**: conftest seeds `PYTHONPATH` for subprocess CLI tests (root-conftest path fix); MCP e2e helpers tolerate notification-interleaved responses; fleet/memory CLI tests green. **Full suite: 2559 passed, 0 failed.**

## [1.26.0] — 2026-08-09

#### Added
- **Persistent MCP memory store**: SQLite + FTS5 keyword search with recency tie-breaking (`MemoryStore` in `src/mcp_server/memory/store.py`). WAL journal mode, parameterized SQL, FTS5 match-term quoting. Embeddings table reserved for optional future vector ranking.
- **MCP memory tools**: `memory_remember`, `memory_recall`, `memory_forget`, `memory_list` — async handlers with input validation and normalized error envelopes. Registered on MCP server surface (19 tools total).
- **`browser-helper memory` CLI**: `bh memory add|search|list|delete` wired into the main entry point.
- **Memory config**: `MemorySettings` dataclass with `BROWSER_HELPER_MEMORY_DB` env override and CLI > env > settings > default precedence.
- **Chrome soft-start warmup**: proxy extension warmup increased from 3s to 10s (`extension_warmup_sec` setting, default 10) — VPN Unlimited service worker needs time to initialize before first navigation.
- Surface-level regression tests: `build_tool_defs()` + FastMCP tool list assertions verify memory tools are exposed.
- Corrupt-store regression test: garbage-bytes store returns clean `operation_failed` error envelope with no traceback.

#### Fixed
- **MCP memory tools registration**: memory tool handlers were dead code for MCP clients — now properly registered in `_TOOL_CAPABILITY` + `_TOOL_PARAM_SCHEMAS` with `memory.persistent` capability.
- **Corrupt SQLite store**: `sqlite3.DatabaseError` on non-database files now returns a clean error envelope instead of unhandled traceback.

#### Tests
- 128/128 touched-module tests passed (test_memory 59/59, test_mcp_server 55/55, test_mcp_integration 14/14).
- Full suite: 2626 collected / 2584 passed / 1 failed (flaky stochastic assertion in untouched module) / 42 skipped.

#### Docs
- `docs/mcp-memory.md`: persistent memory feature documentation.

## [1.25.0] — 2026-08-09

#### Added
- **Rate limiter** (`RateLimitConfig` + `RateLimiter`): emberi tempójú CDP parancsok — uniform/log-normal delay a `_send_command` előtt (bot-detection).
- `GET/POST /rate/config` API: részleges frissítés, validáció (min≤max, distribution), 422 hibákkal.
- **Proxy pool enhanced**: geo-taggolás (`set_geo`/`get_geo`), típus-szűrés (`get_proxy(type=...)`, `get_pool(type=...)`), circuit breaker (3 egymás utáni hiba → 30s cooling), konkurrens `health_check_all` (ThreadPool), legacy formátum backcompat.
- **Google keresés feloldva**: a stealth v1.24 javítások (plugins, window.chrome, permissions, natív UA) + behavioral engine átvitték a Google bot-detectionjét — nincs több CAPTCHA a VPS IP-ről.
- **`/agent/search` engine default: `google`** (2-5s — a perplexity 45s helyett); `perplexity` továbbra is elérhető opcióként.
- MCP `search` tool default: `google`.
- `close_tab()`: `_activate_current()` hívás a close előtt (konzisztens tab-lifecycle).
- SKILL.md: `/connect/remote`, `/rate/config`, `/scroll/config` route-ok dokumentálva.

#### Fixed
- **Teljes teszt-suite ZÖLD: 2493 passed / 0 failed** (a nap eleji 203 failed-hez képest).
- `test_rate_limiter`: defaults teszt sorrend-független (saját reset).
- MCP teszt-izoláció: `BH_TEST_NO_CHROME=1` — a subprocess nem csatlakozik az élő Chrome-hoz.

## [1.24.0] — 2026-08-09

#### Added
- **Behavioral Engine** (`behavioral_engine.py`): automatikus emberi bemenet a CDPClient számára.
- `HumanProfile`: session-enként konzisztens profil (seed=session_id), WPM, mouse params, scroll mode.
- `BehavioralEngine`: WindMouse+Bezier görbék, keystroke dwell/flight, scroll sequence — CDP Input.dispatch* parancsokkal.
- `CDPClient.enable_behavioral(profile)`: click/type automatikusan emberiesítve, ha engedélyezve.
- Session registry: session létrehozáskor automatikusan HumanProfile → enable_behavioral(). A kliensnek semmit sem kell kérnie.

#### Fixed
- **Stealth v2**: navigator.plugins valós Chrome PDF objektumok, window.chrome+runtime, navigator.permissions.query=granted.
- Eltávolítva a hamis Chrome/120 UA → Chrome 151 natív UA használata.

## [1.23.5] — 2026-08-09

#### Fixed
- navigator.plugins: [1,2,3,4,5] → valós Chrome plugin objektumok (Cloudflare/DataDome detekció).
- window.chrome + chrome.runtime hozzáadva.
- navigator.permissions.query: granted.
- Eltávolítva hamis Chrome/120 user-agent → natív Chrome 151 UA.

## [1.23.4] — 2026-08-09

#### Added
- **Chrome health watchdog** (`chrome-health-watchdog`): 5 percenként futó háttérfeladat — (1) megöli az elárvult Chrome folyamatokat (minden `--headless` + nem-main `remote-debugging-port`), (2) ha a fő Chrome meghalt, auto-restart + reconnect. Megelőzi a RAM-felhalmozódást és az "Chrome started but CDP not responding" állapotot.

#### Fixed
- **Orphan reaper kiterjesztve** (`reap-orphans-v2`): a régi `_reap_orphan_headless()` csak a `remote-debugging-port=19`-et kereste, és nem védte a main Chrome-ot (9557). Most minden Chrome-ot felmér, kihagyja a live session-ök és a main Chrome PID-jeit, a többit megöli.

#### Verified
- Szimulált orphan Chrome (12 process) → restart után "Reaped 8 orphaned Chrome PID(s)", 0 orphan maradt, a main Chrome (9557) érintetlen.
- Service log: "Chrome health watchdog started (every 300s)".

## [1.23.3] — 2026-08-09

#### Fixed
- **Chrome nem indul a VNC újraindítása után** (`xauthority-fix`): a Chrome a `child_env`-ben csak a `DISPLAY`-t kapta, a `XAUTHORITY`-t nem. Ha a VNC (:1) újraindult, az `/root/.Xauthority` cookie megváltozott, és a Chrome "Invalid MIT-MAGIC-COOKIE-1 key" + "Missing X server" hibával azonnal kilépett → "Chrome started but CDP not responding on port 9557" → minden művelet 503. Mostantól a `chrome_manager.launch()` a `XAUTHORITY`-t is átadja a gyerek processnek (a systemd unit által létrehozott `/tmp/.Xauthority-zoltan` prioritással).

#### Verified
- VNC restart után: Chrome auto-launch → connected, teljes smoke (navigate/observe/eval/screenshot/click+confirm) átmegy, 1 session / 1 tab.

## [1.23.2] — 2026-08-09

#### Fixed
- **`confirm` ág session-konzisztens** (`click-confirm-session`): a `/click/text`, `/click/label`, `/checkbox/select` és `/checkbox/deselect` endpointok `?confirm=screenshot|analyze` ága korábban a globális default clienten futott (a before/after `_confirm_with_*` hívások), nem a hívó session tabján. Mostantól mind a before-állapot, mind a confirm a `_resolve_session_client()` feloldott session clientén megy — a kattintás és a screenshot ugyanazon a tabon.

#### Verified
- `/click/text?confirm=screenshot` élőben: 1 cookie-jar kliens = 1 session, confirmation mező megjön, eval ugyanazon a tabon.

## [1.23.1] — 2026-08-09

#### Fixed
- **Tab-spam a `/agent/console`-nál** (`console-session-fix`): a `/agent/console` és `/recording/status` endpointok nem mintteltek session-t, ha a kliensnek még nem volt — hogyha egy kliens ezekkel kezdett (pl. az `e2e_dashboard.py` első hívásként `/agent/console`-t hív `clear_first`-rel), akkor cookie nélkül maradt, és MINDEN következő hívása új session + új tabot hozott létre. Mostantól mindkét endpoint `_resolve_session_client()`-et használ, így az első hívás is mintel session-t + küld cookie-t → 1 kliens / 1 tab.

#### Verified
- e2e_dashboard.py teljes futtatása: **1 session / 1 tab** a végén (korábban 7 session + 6 üres tab nagyjából ugyanazért a futtatásért).

## [1.23.0] — 2026-08-09

#### Fixed
- **Per-client session izoláció az agent/page endpointokon** (`d0d9e64`): a `/agent/observe`, `/agent/act`, `/page/analyze`, `/screenshot/baseline`, `/screenshot/compare`, `/confirm-action`, `/agent/forms/discover`, `/agent/forms/fill`, `/agent/extract`, `/agent/available-actions`, `/agent/execute-task` és `/agent/run-flow` endpointok a globális default client helyett a hívó session-jének dedikált tabján futnak. Új `_resolve_session_client()` helper: session hiányában lazily mintel (cookie + `X-Session-ID`), majd a session clientre irányít. Korábban ezek az endpointok a közös tabon futottak — több kliens esetén kereszthatások és tab-spam alakult ki.
- **`/navigate` után session tab-id frissítés** (`d0d9e64`): cross-origin navigációkor a Chrome új targetet hozhat létre; a session `tab_id` mostantól a client `_active_tab_id`-jére frissül navigálás után, így a későbbi observe/analyze a helyes tabot látja.
- **CDP target-életciklus követés** (`d0d9e64`): a `_listener()` figyeli a `Target.targetCreated`/`targetDestroyed` eseményeket (page típusú targetokra), frissíti az `_active_tab_id`-t és érvényteleníti a tab cache-t.

#### Changed
- `_capture_accessibility_snapshot()` és `_capture_agent_snapshot()` `target` paramétert kapnak — a hívó session clientjére irányíthatók.

#### Verified
- 2-kliens izolációs teszt (cookie-jar A: example.com, B: example.org): observe / eval / page/analyze / agent/act mindegyike a saját tabját látja, tab-szám = 2.
- 35 agent API teszt passzol (test_agent_api / test_agent_advanced / test_agent_navigation).

## [1.22.0] — 2026-08-08

#### Fixed
- **Tab-szivárgás cookie nélküli klienseknél** (`f149a19`): a `close_tab` mostantól a CDP HTTP `/json/close`-t használ (WS nélkül is működik), és a `SessionRegistry.create()` minden mintelés előtt **bezárja a gazdátlan tabokat** — a fizikai tab-szám sosem haladja meg a capet, még cookie-jar nélküli klienseknél sem (élesen: 25 cookie nélküli hívás → 15 tab, korábban korlátlan).
- **MCP kontrakt-tesztek 15 tool-ra** (`dc97659`): `EXPECTED_TOOLS`/`EXPECTED_CAPABILITY`/`EXPECTED_REQUIRED_PARAMS` frissítve a `search`/`get_content`/`run_flow` tool-okkal; a `run_flow` `steps` paramétere kötelező.
- **`/status` félrevezető `connected: false`** (`966b706`): új `browser_available` mező — a default client és a session-ök külön élnek; ha bármelyik elérhető, a böngésző használható.

#### Changed
- **VLM a llm-gw `hermes-vision` modelljére állítva** (`09365be`): `VLM_BASE_URL=http://localhost:8000/v1`, `VLM_MODEL=hermes-vision`, `VLM_TIMEOUT=90` — nincs külső provider-függőség. A `vision_check` a reasoning-modell `content`-jét és `reasoning`-jét is olvassa; `max_tokens` 500.

#### Added
- **Diff-VLM** (`6c1fadd`): a `/agent/diff` a diff-képet a vision modelllel értékelteti ("mi változott?" szövegesen); ha a diff-kép nem készül, a B screenshotját elemzi. A válasz `vlm` mezője tartalmazza.

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
