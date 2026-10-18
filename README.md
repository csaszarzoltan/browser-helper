# Browser Helper

![Version](https://img.shields.io/badge/version-1.36.21-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

Browser Helper lets AI agents work in your everyday Chrome. It runs next to Chrome,
talks to it over the Chrome DevTools Protocol, and gives agents compact JSON over REST
or **78 tools** over [MCP](https://modelcontextprotocol.io). Screenshots, console logs
and network failures come back only when you ask for them.

- **Your real browser.** It drives a Chrome window you can see, not a hidden headless
  one. Sign in yourself, including any CAPTCHA or 2FA step, and the agent continues in
  that same session.
- **Small answers.** Every REST response uses one envelope: `status`, `operation`,
  `data`, `error`, `meta`.
- **Built for agents.** Each client gets its own tab and cookie jar. Actions target
  elements by snapshot reference, and an unchanged page can be reported as unchanged
  instead of being sent again.

Works with Claude Code, Codex CLI, Cursor, Windsurf and any MCP client, or with plain
HTTP from scripts and QA pipelines.

In a project benchmark at v1.28.4, one end-to-end journey took about 1.6 s with Browser
Helper and 3.2 s with Playwright. See [docs/perf-phase2.md](docs/perf-phase2.md).

## Quick start

### 1. Start Chrome with remote debugging

Browser Helper looks for Chrome on port **9557** by default. Give Chrome its own profile
directory, because recent Chrome versions ignore the debugging port on the default profile.

```bash
# Linux
google-chrome --remote-debugging-port=9557 --user-data-dir="$HOME/bh-chrome-profile"

# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9557 --user-data-dir="$HOME/bh-chrome-profile"

# Windows (PowerShell)
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9557 --user-data-dir="$env:USERPROFILE\bh-chrome-profile"
```

Or let Browser Helper start Chrome for you: `python run.py --launch-chrome`.

### 2. Install and run

```bash
git clone https://github.com/csaszarzoltan/browser-helper.git
cd browser-helper
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e ".[mcp]"                # the API and the MCP server
python run.py                          # API and dashboard on http://127.0.0.1:8000
```

Check that it is up:

```bash
curl -s http://127.0.0.1:8000/health
```

Then open http://127.0.0.1:8000 in a browser for the dashboard.

If something does not connect, run `bh doctor`. It checks the Chrome debug port, the Chrome
profile flag, the service and `API_TOKEN`, and prints the fix for each problem. It only reads.

### 3. Docker (Linux)

```bash
docker build -t browser-helper .
docker run --rm --network host -e API_TOKEN=<a-long-random-secret> browser-helper
```

Host networking is Linux-only. The service connects to Chrome at `127.0.0.1`, so on
macOS and Windows the container cannot reach a Chrome running on the host. Run
`python run.py` there instead. The container listens on all interfaces, so set `API_TOKEN`.

## Connect an AI agent (MCP)

Install with the `mcp` extra (step 2 above). The MCP server uses the same Chrome on
port 9557, so start Chrome first.

**Claude Code**

```bash
claude mcp add browser-helper -- /absolute/path/to/browser-helper/.venv/bin/bh mcp
```

**Any client with a JSON config** (Cursor, Windsurf and others)

```json
{
  "mcpServers": {
    "browser-helper": {
      "command": "/absolute/path/to/browser-helper/.venv/bin/bh",
      "args": ["mcp"]
    }
  }
}
```

**Remote or HTTP clients:** run `bh mcp --http --port 8765` and point the client at
`http://localhost:8765/mcp`.

The tools cover browser control (`navigate`, `click`, `type`, `screenshot`, `get_tabs`),
agent helpers (`observe`, `act`, `run_flow`, `assert`, `wait_for`), fleet work,
persistent memory (`memory_remember`, `memory_recall`) and diagnostics. The full
reference is in [docs/mcp-server.md](docs/mcp-server.md).

## Use the REST API

The usual pattern is: open a session, observe the page, act on it. After step 1, send
the session id in the `X-Session-ID` header.

```bash
# 1. Open an isolated session with its own tab. The session id comes back in the X-Session-ID header.
curl -i -X POST "http://127.0.0.1:8000/session/new?url=https://example.com"

# 2. Read the page as an accessibility tree, with console errors
curl -s -X POST http://127.0.0.1:8000/agent/observe \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: <your-session-id>' \
  -d '{"max_nodes": 50, "include_console": true}'

# 3. Click an element by its ref from step 2. include_observation:false skips the reply snapshot.
curl -s -X POST http://127.0.0.1:8000/agent/act \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: <your-session-id>' \
  -d '{"action": "click", "target": {"snapshot_id": "<snap>", "ref": "e11"}, "include_observation": false}'
```

Browser calls without a session id get `400 Missing session`. Send `X-Session-Auto: true`
or set `BH_SESSION_AUTO=1` if you want the service to create one for you.

| Task | Endpoint |
|---|---|
| Navigate | `POST /navigate?url=…` |
| Click by visible text | `POST /click/text` |
| Run a multi-step flow with a report | `POST /agent/run-flow` |
| Search and extract an answer | `POST /agent/search` |
| Console errors and failed requests | `POST /agent/console` |
| Condensed page snapshot | `POST /page/analyze` |

There are more than 200 endpoints in `src/main.py` and `src/fleet/api.py`. Request and
response contracts are in [docs/agent-api.md](docs/agent-api.md).

## Dashboard

Open http://127.0.0.1:8000 for:

- **Overview**: connection state and recent operations
- **Live Browser**: navigate, take screenshots, manage tabs
- **Automation**: a workspace that edits workflow steps as JSON (it never runs them)
- **Diagnostics**: network, console and cookie inspection
- **Agent Tools**: an observe/act playground
- **Fleet console**: node health and sessions at `/fleet`

## Configuration

Set these environment variables before `python run.py`. The flags `--host`, `--port` and
`--debug-port` override them for one run.

| Variable | Default | Purpose |
|---|---|---|
| `API_TOKEN` | unset | Requires `Authorization: Bearer <token>` on every endpoint except `/`, `/health`, `/ready`, `/ws` and `/api/v1/capabilities`. Placeholder values such as `changeme` are rejected. |
| `HOST` (`--host`) | `127.0.0.1` | Bind address. Use `0.0.0.0` only together with `API_TOKEN`. |
| `PORT` (`--port`) | `8000` | HTTP port |
| `CHROME_AUTO_PORT` (`--debug-port`) | `9557` | Chrome remote-debugging port |
| `BH_MAX_SESSIONS` | `30` | Session cap |
| `BH_MAX_TABS` | `0` (no limit) | Tab budget. Beyond it, `/session/new` returns `429 tab_budget_exhausted`. |
| `BH_KEEP_WARM` / `BH_KEEP_WARM_INTERVAL` | on / `300` s | Refreshes a warm session on that interval, so the first call after idle stays fast. `BH_KEEP_WARM=0` turns it off. |
| `FLEET_DB_PATH` | see `src/fleet/storage.py` | Location of the fleet database |

## Security

- The API listens on `127.0.0.1` by default. For an agent on another machine, keep that
  and reach it through an SSH tunnel rather than opening the port.
- If you bind to `0.0.0.0`, set `API_TOKEN` first.
- Sign-in happens in the Chrome window, not through the API.
- Browser Helper does not guarantee that a site accepts automation. If a site shows a
  challenge, solve it yourself in the visible window, and check the site's terms before
  you automate it.

## Testing and anti-detection tools

For testing your own sites and personal automation, the project includes fingerprint
templates, stealth injection, human-like mouse, typing and scroll simulation, proxy
rotation and cloud-browser adapters. Each one is described in `docs/`:
[anti-detection compositor](docs/anti-detection-compositor.md),
[behavioral simulation](docs/behavioral-simulation.md),
[proxy rotation](docs/proxy-rotation-manager.md),
[cloud providers](docs/cloud-provider-setup.md).

## Fleet (several machines)

Run one coordinator and several worker nodes. Sessions go to the least-loaded healthy
node, wait in a queue when every node is full, and move to another node if one dies.

```bash
curl -X POST http://127.0.0.1:8000/fleet/nodes/register \
  -H 'Content-Type: application/json' \
  -d '{"url": "http://worker-1:8000", "capabilities": ["cdp"], "capacity": 5}'
```

The fleet console is at `/fleet`. The endpoints are defined in `src/fleet/api.py`.

## Architecture

```
AI agent ──REST / MCP / WebSocket──▶ Browser Helper (FastAPI, :8000) ──CDP──▶ Chrome (127.0.0.1:9557)
```

- `src/main.py`: the FastAPI app and REST endpoints
- `src/mcp_server/`: the MCP server. `registry.py` defines the tools.
- `src/cdp_client.py`: the Chrome DevTools Protocol client
- `src/session_registry.py`: per-client sessions
- `src/fleet/`: multi-node orchestration
- `src/anti_detection/`: fingerprint, stealth and behavior modules

## Documentation

| Guide | What it covers |
|---|---|
| [Agent API](docs/agent-api.md) | Request and response contracts for agents |
| [MCP server](docs/mcp-server.md) | Transports, client setup, tool reference |
| [Agent navigation engine](docs/agent-navigation-engine.md) | Accessibility-tree observation and semantic forms |
| [Visual workflow builder](docs/visual-workflow-builder.md) | The dashboard workspace for workflow steps |
| [Session persistence](docs/session-persistence.md) | Keeping and moving logged-in sessions |
| [Performance](docs/perf-phase2.md) | Benchmarks and the speed roadmap |
| [Engineering standards](docs/engineering-standards.md) | Required reading before changing code |
| [Changelog](CHANGELOG.md) | Version history |

The `examples/` folder has example scripts for session persistence, proxy rotation,
checkbox operations and cloud browsers.

## Development

```bash
pip install -e ".[dev,mcp]"            # adds pytest, ruff and the test plugins
ruff check src/                        # lint
pytest tests/test_mcp_server.py tests/test_agent_api.py tests/test_agent_highlevel.py -o addopts='' -q   # quick core check
pytest                                 # full suite (slow, runs in parallel)
scripts/release-validate.sh            # version, tool count and docs consistency
```

The tests stub Chrome and do not touch the Chrome on port 9557.

## License

No license has been chosen yet. Until one is added, the code is not licensed for reuse.
