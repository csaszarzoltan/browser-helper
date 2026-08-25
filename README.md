# Browser Helper 🦎

![Version](https://img.shields.io/badge/version-1.32.0-blue)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Tests](https://img.shields.io/badge/tests-2630%20passed-brightgreen)

> ### 🔑 **You log in as a human. Your agent works as a machine.**
>
> Browser Helper drives your **real, visible Chrome** — not a hidden headless farm.
> That means you can sign in by hand to Google, Perplexity, LinkedIn, or any
> service that blocks bots with CAPTCHAs and "unusual activity" walls. Solve the
> challenge once; from that moment your AI agent operates inside **your
> authenticated session** — real cookies, real fingerprint, already trusted.
> [See how it works ↓](#human-login-agent-reuse)

**Fast, agent-first browser automation over the Chrome DevTools Protocol (CDP).**
Browser Helper sits between your AI agents and Chrome: it speaks compact JSON over
REST/MCP instead of megabytes of raw CDP traffic, keeps per-client browser sessions
isolated, and returns evidence — screenshots, console logs, network failures,
accessibility snapshots — with every answer.

| | |
|---|---|
| **What it is** | A lightweight FastAPI proxy that drives your real Chrome via CDP |
| **Who it is for** | AI agents (Hermes, Claude Code, Codex CLI, Cursor), QA automation, scrapers |
| **Interfaces** | REST API · 47-tool MCP server · WebSocket stream · GUI dashboard |
| **Why fast** | Local CDP + compact payloads; measured **1.9–2.2× faster than Playwright** on the same E2E journey (~1641ms vs ~3163ms) |
| **Killer feature** | The browser is **visible to you** — log in manually (Google, Perplexity, anything with CAPTCHA/bot-walls), and your agent reuses *your* logged-in session |
| **License / status** | Personal-lab project, actively developed — releases every few days |

---

## Table of contents

- [Why does this exist?](#why-does-this-exist)
- [30-second tour](#30-second-tour)
- [Install & run](#install--run)
- [The four interfaces](#the-four-interfaces)
  - [REST API](#rest-api)
  - [MCP server (47 tools)](#mcp-server-47-tools)
  - [WebSocket streaming](#websocket-streaming)
  - [GUI dashboard](#gui-dashboard)
- [Built for AI agents](#built-for-ai-agents)
- [Performance](#performance)
- [Fleet orchestration](#fleet-orchestration)
- [Sessions & isolation](#sessions--isolation)
- [Anti-detection toolkit](#anti-detection-toolkit)
- [Operations runbook](#operations-runbook)
- [Architecture](#architecture)
- [Use cases](#use-cases)
- [Documentation index](#documentation-index)
- [Development & testing](#development--testing)

---

## Why does this exist?

**The problem:** an AI agent running on a remote server needs to control Chrome on
your machine through an SSH tunnel. Raw CDP tools push megabytes of JSON down that
tunnel — every snapshot or screenshot takes seconds, and agents burn their context
window on payload noise.

**The solution:** Browser Helper runs **next to Chrome** and talks to it locally
(instant), while your agent sends small JSON commands through the tunnel:

```
POST /agent/act {"action":"click","target":{"ref":"e11"}}
→ {"status":"ok","data":{"clicked":true,"backend_node_id":130}}   ← ~113 ms round-trip
```

Compact commands in, compact answers out — with optional evidence bundles
(console/network/screenshot) when you *do* need the heavy stuff.

**And the part that solves bot-walls:** because Browser Helper drives your *real,
visible* Chrome, **you** can do the things bots can't. Open the browser window,
log in by hand — Google, Perplexity, LinkedIn, whatever throws CAPTCHAs and
"unusual activity" screens at automation. Solve the challenge once as a human;
from then on your agent operates inside **your authenticated session**, with your
cookies, in a browser that looks (and is) genuinely human-driven. The agent never
sees or handles your password — it inherits the logged-in state. Sessions can
also be exported/cloned (`/session/{sid}/export-cookies`, `/clone`) so other
agents or machines reuse the same login.

## 30-second tour

```bash
# 1. Health check
curl -s http://localhost:8000/health

# 2. Mint an isolated session (own tab, cookie jar) and navigate
curl -s -X POST "http://localhost:8000/session/new?url=https://example.com"

# 3. Observe the page as an accessibility tree
curl -s -X POST http://localhost:8000/agent/observe \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: <your-session-id>' \
  -d '{"mode":"accessibility","max_nodes":50,"include_console":true}'

# 4. Act on what you saw — click by ref, skip the return-snapshot for speed
curl -s -X POST http://localhost:8000/agent/act \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: <your-session-id>' \
  -d '{"action":"click","target":{"snapshot_id":"<snap>","ref":"e11"},"include_observation":false}'
```

Every response uses one envelope: `{"status", "operation", "data", "error", "meta"}`.
Agents can parse one shape forever.

## Install & run

### 1. Start Chrome with remote debugging

```bash
# Linux
google-chrome --remote-debugging-port=9555

# Windows
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9555

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9555
```

Or let Browser Helper launch Chrome itself: `python run.py --launch-chrome`.

### 2. Install and start

```bash
pip install -e .            # installs the `bh` CLI + dependencies
bh                          # starts on :8000, auto-connects to CDP
python run.py --port 8001   # alternative entry point with custom port
```

Minimal manual install also works: `pip install fastapi uvicorn websockets httpx Pillow` then `python run.py`.

### 3. Docker

```bash
docker build -t browser-helper .
docker run -p 8001:8001 -e API_TOKEN=my-secret-token \
  --add-host host.docker.internal:host-gateway \
  browser-helper
```

Chrome still runs on the host with `--remote-debugging-port=9555`; the container reaches it via `host.docker.internal`.

### Authentication

Set `API_TOKEN` to protect every endpoint except `/`, `/health`, `/ready`, `/ws`
and the OpenAPI docs:

```bash
API_TOKEN=my-secret-token bh
# clients send: Authorization: Bearer <token>
```

Unset = open API. Placeholder values (`changeme`, `your-token`, …) are rejected at startup.

---

## The four interfaces

### REST API

~90 endpoints, all speaking the same envelope. The everyday core:

**Navigate & interact**

| Endpoint | What it does |
|---|---|
| `POST /navigate?url=…&waitUntil=domContentLoaded` | Navigate + smart wait (`domContentLoaded` default ~400ms, `load`, `networkIdle`) |
| `POST /click`, `/click/text`, `/click/label` | Click by CSS selector, visible text, or label |
| `POST /type`, `/form/fill`, `/form/select` | Type into fields, fill forms by label, pick dropdown options |
| `POST /wait`, `/wait/text`, `/wait/navigation`, `/wait/network-idle` | Deterministic waits — no sleep-guessing |

**Observe**

| Endpoint | What it does |
|---|---|
| `POST /page/analyze` | Condensed page snapshot: buttons, forms, modals, checkbox states, iframes |
| `POST /agent/observe?include=console,network,screenshot` | Accessibility tree + evidence bundle in ONE call |
| `{"if_none_match_snapshot_id":"snap_…"}` | 304-style short-circuit → `{unchanged:true}` when the page didn't change |
| `GET /page/text`, `/page/outline`, `/page/diff`, `/tabs/deep-scan/{id}` | Text extraction, heading outline, state diff, deep tab scan |

**Agent high-level**

| Endpoint | What it does |
|---|---|
| `POST /agent/act` | One-call actions with `verify_after`, `expect`, `auto_recover`, pinned refs |
| `POST /agent/run-flow` | Ordered multi-step E2E flow with per-step report |
| `POST /agent/search` | Search engine query → extracted answer text |
| `POST /agent/diff`, `/agent/visual-regression` | Visual comparison / baseline regression |
| `POST /agent/console` | Console errors, JS exceptions, failed requests |
| `POST /agent/forms/discover` + `/fill` | Semantic form discovery & filling with validation feedback |

Full reference: [docs/api-reference.md](docs/api-reference.md) · Agent contracts: [docs/agent-api.md](docs/agent-api.md).

### MCP server (47 tools)

Ships a [Model Context Protocol](https://modelcontextprotocol.io) server exposing the
same engine as **47 MCP tools** — for Claude Code, Codex CLI, Cursor, Windsurf, any MCP client.
In-process, no HTTP self-calls, no LLM in the middle.

```bash
bh mcp                       # stdio (Claude Code, Codex CLI)
bh mcp --http --port 8765    # streamable HTTP (Cursor, Windsurf, remote clients)
```

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

Tool families: browser core (`navigate`, `click`, `type`, `screenshot`, `get_tabs`, …),
agent semantics (`observe`, `run_flow`, `flow_vlm`, `assert`, `wait_for`, …),
fleet read-only views, persistent memory (`memory_remember/recall/forget/list`),
diagnostics. Every tool mirrors a REST endpoint and returns the standard envelope.

Details & client configs: [docs/mcp-server.md](docs/mcp-server.md).

### WebSocket streaming

Connect to `ws://localhost:8000/ws` for live state updates, CDP events, console log
streaming, and an operation feed. Send `ping` for keep-alive, JSON messages for actions.

### GUI dashboard

Open `http://localhost:8000` in a browser:

- **Overview** — connection state, continue-your-work launchpad, operation history
- **Live Browser** — guided navigate/screenshot/observe flow, tab manager
- **Automation** — visual workflow builder (drag steps, switch to JSON), script runner
- **Diagnostics** — network capture with redaction, cookie inspector (values masked), bounded exports
- **Agent Tools** — observe/act playground, capabilities viewer
- **Fleet console** — node health, session pool, queue (`/fleet`)
- **Ctrl/Cmd+K command palette**, accessibility announcements, destructive-action confirmations

## Built for AI agents

Browser Helper's design goal is *agents finish journeys in seconds, not minutes*:

- **Session isolation** — each client mints its own tab + cookie jar via
  `POST /session/new` (`X-Session-ID` header / `bh_session` cookie). No cross-talk,
  no tab spam; LRU eviction + TTL reaper keep counts bounded.
- **Semantic targets** — click by accessibility `ref` from the latest snapshot;
  stale snapshots auto-recover by name/text; bare `backend_node_id` works without snapshots.
- **Speed knobs** — `include_observation:false` skips the return snapshot (~113ms act),
  `observe?include=` bundles evidence into one round-trip, `waitUntil=domContentLoaded`
  is the navigate default, and `if_none_match_snapshot_id` gives 304-style unchanged answers.
- **Evidence-backed honesty** — verification results (`verified:true/false`,
  `needs_attention`) tell the agent what *actually* happened; missing extract fields are
  reported as `missing`, never fabricated.
- **Service metrics** — `GET /service/metrics` reports p50/p95 latency per operation
  (JSON or `?format=prometheus`) so you benchmark real CDP-side numbers, not client-side guesses.
- **Self-healing ops** — keep-warm session re-minted every 5 min (no cold-start penalty),
  orphan-tab reaper, Chrome watchdog with pre-relaunch diagnostics (RSS, last op, session count).

A complete journey today measures **~1.4 s** where Playwright takes ~3.2 s — see
[docs/perf-prioritized.md](docs/perf-prioritized.md) and [docs/perf-phase2.md](docs/perf-phase2.md).

## Performance

Measured on a live journey (navigate → observe → act → verify), warm service:

| Operation | Browser Helper | Raw CDP over tunnel | Playwright (same journey) |
|-----------|---------------|---------------------|---------------------------|
| Navigate (domContentLoaded) | ~150–300ms | ~1–2s | — |
| Observe (AX tree, 50 nodes) | ~320–470ms | ~5–10s | — |
| Act (`include_observation:false`) | **~113ms** | ~500ms | — |
| Full journey | **~1.4s** | ~15–25s | ~3.2s |
| Screenshot | ~175ms | ~8–20s | — |
| GZip JSON responses | 74% smaller | — | — |

Benchmark methodology and the prioritized speed roadmap:
[docs/perf-prioritized.md](docs/perf-prioritized.md).

## Fleet orchestration

Run one coordinator plus N worker nodes; sessions schedule onto the least-loaded
healthy node, queue at capacity, and fail over when a node dies.

```bash
# Register a worker (returns node_id)
curl -X POST http://localhost:8000/fleet/nodes/register \
  -H 'Content-Type: application/json' \
  -d '{"url":"http://worker-1:8000","capabilities":["cdp","headless"],"capacity":5}'

# Allocate a session anywhere in the fleet
curl -X POST http://localhost:8000/fleet/session -d '{"ttl_seconds":300}' \
  -H 'Content-Type: application/json'
```

- Node registry, async health polling (15s, cooldown on failures)
- Session pool + FIFO queue with TTL backpressure (`202 queued` / `503 Retry-After`)
- `POST /fleet/failover` re-homes a dead node's sessions
- `POST /fleet/run-batch` runs N isolated tasks in parallel (per-task error isolation, `elapsed_ms`)
- CLI: `python -m fleet.cli node list` · Dashboard: `GET /fleet`

State: `~/.browser-helper/fleet.db` (override `FLEET_DB_PATH`). See [Fleet section below](#fleet-api) for the full endpoint table.

### Fleet API

| Method | Endpoint | Description | Success | Errors |
|--------|----------|-------------|---------|--------|
| POST | `/fleet/nodes/register` | Register a worker node | 201 | 409 duplicate URL |
| POST | `/fleet/nodes/{node_id}/unregister` | Soft-remove a node | 200 | 404 unknown node |
| GET | `/fleet/nodes` | List nodes with health + load | 200 | — |
| GET | `/fleet/nodes/{node_id}/health` | Probe one node's `/health` | 200 | 404 unknown node |
| POST | `/fleet/nodes/health-check` | Recheck every node now | 200 | — |
| POST | `/fleet/nodes/{node_id}/health-check` | Recheck one node now | 200 | 404 unknown node |
| POST | `/fleet/session` | Allocate a session (least-loaded node) | 200 | 202 queued, 409 duplicate id, 503 queue full |
| GET | `/fleet/session/{session_id}` | Session status | 200 | 404 unknown session |
| POST | `/fleet/session/{session_id}/release` | Release a session | 200 | 404 unknown session |
| GET | `/fleet/sessions` | List sessions (active/queued counts) | 200 | — |
| POST | `/fleet/queue/sweep` | Purge expired queue entries | 200 | — |
| POST | `/fleet/failover` | Fail a node's sessions over | 200 | — |
| POST | `/fleet/run-batch` | Run N parallel browsing tasks | 200 | per-task errors in report |
| GET | `/fleet` | Fleet console page (HTML) | 200 | — |

## Sessions & isolation

| Concern | Mechanism |
|---|---|
| Per-client tab | `POST /session/new` → dedicated tab, `X-Session-ID` echo |
| Cookie isolation | Optional profile per session (`?profile=name`) — own storage dir |
| Cap & fairness | Hard cap (default 30, env `BH_MAX_SESSIONS`) with LRU eviction + early-WARN at 80% |
| Idle cleanup | TTL reaper (default 1800s) closes abandoned tabs |
| Orphan tabs | Startup reaper closes headless/tabs not owned by live sessions |
| Keep-warm | Periodic warm session at `BH_KEEP_WARM_URL` so first calls stay fast |
| Auth-session portability | `/session/{sid}/export-cookies`, `/import-cookies`, `/clone` |

### Human login, agent reuse

The most practical workflow for bot-protected services. The browser Chrome window
is **visible on your desktop** — it's not a hidden headless instance:

1. **You log in as a human.** Open the tab (dashboard, or just use Chrome directly),
   go to Google / Perplexity / LinkedIn / your bank — solve the CAPTCHA, the 2FA,
   the "prove you're not a robot" dance exactly once.
2. **The agent inherits the session.** Every subsequent API call in that browser
   profile carries your real cookies and login state. No password ever passes
   through the API; the agent simply operates *while already logged in*.
3. **The login survives.** Cookies persist in the Chrome profile; sessions can be
   pinned, exported (`/session/{sid}/export-cookies`) or cloned
   (`POST /session/{sid}/clone`) to share the authenticated state with other
   agents or machines.
4. **Detection sees a human.** Because the login itself was performed manually in a
   real Chrome with a real fingerprint, services that block *bot sign-ups*
   (Google's "This browser isn't secure", Perplexity's Cloudflare wall) never
   trigger — automation only happens inside an already-trusted session.

This is why Browser Helper drives your everyday visible Chrome rather than an
isolated headless farm: the human does authentication, the machine does the work.

## Anti-detection toolkit

For scraping scenarios that need to look human:

- **Fingerprint database** — 4 shipped templates (chrome-120, firefox-linux, safari-ios, edge-windows), CRUD + generation ([docs](docs/fingerprint-database.md))
- **Stealth injection** — real CDP `Page.addScriptToEvaluateOnNewDocument` patches: navigator, canvas, WebGL, audio, screen; low/medium/high levels
- **Behavioral simulation** — WindMouse+Bezier mouse paths, keystroke timing with realistic typos, momentum scroll ([docs](docs/behavioral-simulation.md))
- **Proxy rotation** — 5 strategies (round-robin, random, sticky, by-tag, health-check), env-loaded pools ([docs](docs/proxy-rotation-manager.md))
- **Compositor** — one bundle combining fingerprint + proxy + stealth level + TTL ([docs](docs/anti-detection-compositor.md))
- **Cloud providers** — Browserbase / Steel adapters with warm pools and cost tracking ([docs](docs/cloud-provider-setup.md))

## Operations runbook

**Health & monitoring**

```bash
curl http://localhost:8000/health           # version, uptime, memory, CDP state
curl http://localhost:8000/status           # connected, tabs, sessions, last op
curl "http://localhost:8000/service/metrics?format=prometheus"   # p50/p95 per op
```

**Key environment variables**

| Variable | Default | Purpose |
|---|---|---|
| `API_TOKEN` | *(unset)* | Bearer protection on all endpoints |
| `PORT` | `8000` | HTTP port (`--port` overrides) |
| `BH_MAX_SESSIONS` | `30` | Per-client session hard cap (LRU eviction beyond) |
| `BH_KEEP_WARM_URL` | `http://127.0.0.1:8080/` | Warm-session target |
| `BH_KEEP_WARM_INTERVAL` | `300` | Keep-warm re-mint cadence (seconds); `BH_KEEP_WARM=0` disables |
| `CHROME_AUTO_PORT` | `9557` | CDP debug port preference order: env > settings > 9557 |
| `MCP_ENABLED` | `1` | Auto-start the MCP server with the service |
| `PROXY_LIST` / `PROXY_FILE` | — | Pre-load proxy rotation pool |
| `FLEET_DB_PATH` | `~/.browser-helper/fleet.db` | Fleet state location |

**Resilience behavior** (what the service does without you asking): Chrome watchdog
every 5 min with pre-relaunch diagnostics, idempotent `close_tab` (already-closed =
success, no ERROR storms), orphan-headless reaper at startup, session-cap early warning.

## Architecture

```
Your machine                        Remote server (AI agents)
┌──────────────────────────┐        ┌──────────────────────────┐
│ Chrome ◄─CDP :9555/9557─ │        │  Hermes / Claude Code /  │
│         ▲                │        │  Codex CLI / Cursor      │
│  ┌──────┴───────────┐    │ tunnel │          │               │
│  │ Browser Helper    │   │◄──────►│  compact JSON (REST)     │
│  │ :8000             │   │        │  MCP tools (stdio/http)  │
│  │ FastAPI + WS      │   │        │  WebSocket events        │
│  │ + MCP + dashboard │   │        │                          │
│  └───────────────────┘   │        └──────────────────────────┘
└──────────────────────────┘
     src/main.py (REST)      src/mcp_server/ (47 tools)
     src/cdp_client.py       src/fleet/ (orchestration)
     src/session_registry.py src/anti_detection/
```

Source map: `src/main.py` (FastAPI app, ~6900 lines, all REST endpoints),
`src/cdp_client.py` (CDP protocol client), `src/session_registry.py` (per-client
sessions), `src/mcp_server/registry.py::build_tool_defs()` (tool source of truth),
`src/fleet/` (multi-node orchestration).

## Use cases

1. **AI agent browser control** — Hermes/LLM agents drive Chrome through compact REST/MCP calls instead of raw CDP
2. **Agent behind a human login** — you sign in once (Google, Perplexity, anything with CAPTCHA/bot-walls); the agent works inside your authenticated session from then on — see [Human login, agent reuse](#human-login-agent-reuse)
3. **E2E testing without selectors** — semantic clicks by text/label/ref, deterministic waits, verified outcomes
4. **Web scraping** — extraction, screenshots, PDFs, anti-detection profiles at scale
5. **Session replay** — save/restore authenticated sessions, clone them across machines
6. **Network debugging** — capture requests, block/mock patterns, inspect console errors
7. **Multi-node fleets** — schedule parallel browsing across worker machines with failover
8. **SPA deep-dives** — extract sub-tabs and iframe content in single calls

## Documentation index

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Prerequisites, install, first run |
| [API Reference](docs/api-reference.md) | Complete endpoint docs with examples |
| [LLM Agent API](docs/agent-api.md) | Stable refs, observations, actions, artifacts |
| [Agent Navigation Engine](docs/agent-navigation-engine.md) | AX-tree observation, semantic forms, execute-task |
| [MCP Server](docs/mcp-server.md) | Transports, client configs, full 47-tool reference |
| [Perf roadmap](docs/perf-prioritized.md) · [Phase 2](docs/perf-phase2.md) | Speed design + benchmarks |
| [Tab Auto-Activation](docs/tab-auto-activation.md) | How transparent tab activation works |
| [Condensed Snapshot](docs/condensed-snapshot.md) · [Checkbox Operations](docs/checkbox-operations.md) · [Screenshot Confirmation](docs/screenshot-confirmation.md) | Feature guides |
| [Anti-Detection Profile Manager](docs/anti-detection-profile-manager.md) · [Fingerprint Randomization](docs/fingerprint-randomization.md) · [Behavioral Simulation](docs/behavioral-simulation.md) · [Cloud Provider Setup](docs/cloud-provider-setup.md) · [Proxy Rotation Manager](docs/proxy-rotation-manager.md) · [Fingerprint Database](docs/fingerprint-database.md) · [Session Persistence](docs/session-persistence.md) · [Anti-Detection Compositor](docs/anti-detection-compositor.md) | Stealth stack docs |
| [Engineering Standards](docs/engineering-standards.md) | Kötelező olvasmány kódírás előtt |
| [Decisions](docs/decisions/) · [Specs](docs/specs/) · [Methodology](docs/METHODOLOGY.md) | Döntések, követelmények, módszertan |
| [Changelog](CHANGELOG.md) | Version history |
| Examples: [browse-workflow](examples/browse-workflow.py) · [dashboard-demo](examples/dashboard-demo.py) · [checkbox_ops](examples/checkbox_ops.py) · [proxy_rotation](examples/proxy_rotation.py) · [session_persistence](examples/session_persistence.py) · [cloud_browser](examples/cloud_browser.py) | Runnable demos |

## Development & testing

```bash
pip install -e . && pip install pytest pytest-asyncio ruff

ruff check src/                                  # lint (must pass before commit)
pytest tests/test_mcp_server.py tests/test_agent_api.py tests/test_agent_highlevel.py -o addopts='' -q
                                                 # core suite (~69 tests, <20s)
pytest -q                                        # full suite (slow; use timeout)
bash scripts/release-validate.sh                 # release gate: version + 47 tools + docs consistency
```

Release process: feature branch → FF-merge to main → version bump
(`pyproject.toml`, `src/main.py`, `Dockerfile`, README badge) → CHANGELOG entry →
`release-validate.sh` green → tag → GitHub release → systemd restart → live `/health` check.

Current state: **2630 tests passing** historically; the fast gate used per release is
the selective suite above. Version history in [CHANGELOG.md](CHANGELOG.md).
