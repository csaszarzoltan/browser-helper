# Session Persistence

**Since:** v1.8.0

`SessionManager` (`src/session_manager.py`) captures and restores browser session state — cookies, localStorage, sessionStorage — through real CDP commands, persists it as JSON, and pools WebSocket connections for reuse. Sessions expire after a configurable timeout and are cleaned up in the background. All of it is exposed through the `/api/v1/session/*` REST API.

## Overview

- **Cookies** — captured via `Network.getAllCookies`, restored via `Network.setCookies`
- **Storage** — localStorage and sessionStorage serialized with `Runtime.evaluate` and re-applied key by key on restore
- **WebSocket pooling** — CDP WebSocket connections cached per URL and reused; all closed on cleanup
- **Timeout & cleanup** — sessions idle longer than `session_timeout` (default 3600s) are reported expired; `cleanup()` removes them and closes cached sockets; a background loop runs every `cleanup_interval` (default 300s)
- **Storage** — `~/.browser-helper/sessions/<session_id>.json`

The REST endpoints require a `cdp_url` (`ws://` or `wss://`) pointing at a real CDP endpoint. If the endpoint is unreachable, the response carries an explicit `warning` field instead of fabricated state (review fix C1/C3).

## REST API — `/api/v1/session/*`

### POST /api/v1/session/capture

Snapshot the current state of a browser session.

**Request:**
```json
{
  "session_id": "checkout-flow",
  "cdp_url": "ws://localhost:9555/devtools/page/abc123"
}
```

**Response:**
```json
{
  "status": "ok",
  "session": {
    "session_id": "checkout-flow",
    "cookies": [{"name": "sessionid", "value": "abc123", "domain": ".example.com"}],
    "local_storage": {"cart": "[{\"sku\":\"x\"}]"},
    "url": "https://example.com/cart",
    "created_at": 1712345678.9,
    "last_active": 1712345678.9
  }
}
```

`422` if `session_id` is missing or `cdp_url` is not a `ws://`/`wss://` URL. If the CDP connection fails, the response still has `status: "ok"` plus `"warning": "CDP unavailable: <error>"`.

### POST /api/v1/session/restore

Restore a previously captured session to a browser tab.

**Request:**
```json
{
  "session_id": "checkout-flow",
  "cdp_url": "ws://localhost:9555/devtools/page/abc123"
}
```

**Response:** `{"status": "ok", "session_id": "checkout-flow"}` — `404` if the session was never captured, `422` for a missing `session_id` or invalid `cdp_url`.

### GET /api/v1/session

List all managed sessions with expiry info:

```json
{
  "status": "ok",
  "sessions": [
    {
      "session_id": "checkout-flow",
      "age": 42.5,
      "expired": false,
      "url": "https://example.com/cart",
      "created_at": 1712345678.9,
      "last_active": 1712345678.9
    }
  ]
}
```

### GET /api/v1/session/{session_id}

Full session state (cookies, storage, url, timestamps). `404` if not found.

### DELETE /api/v1/session/{session_id}

Delete a session file. `404` if not found.

### POST /api/v1/session/cleanup

Run cleanup now: remove expired sessions and close all cached WebSockets.

**Response:** `{"status": "ok", "removed": 1}` — `removed` is the number of expired session files deleted.

## Python API

```python
import asyncio

from session_manager import SessionManager

async def main():
    mgr = SessionManager(session_timeout=3600.0, cleanup_interval=300.0)

    # WebSocket pooling — reuse a connection per CDP URL
    ws = mgr.get_cached_ws("ws://localhost:9555/devtools/page/abc123")
    if ws is None:
        ws = await connect()          # your CDP client
        mgr.cache_ws("ws://localhost:9555/devtools/page/abc123", ws)

    # Capture / restore via CDP
    state = await mgr.capture(cdp_client=client, session_id="checkout-flow", url="https://example.com/cart")
    await mgr.restore(cdp_client=client, state=state)

    # Expiry + cleanup
    mgr.list_sessions()
    mgr.is_expired("checkout-flow")
    await mgr.start_cleanup_loop()    # background task
    await mgr.stop_cleanup_loop()

asyncio.run(main())
```

## Storage Layout

```
~/.browser-helper/sessions/
└── checkout-flow.json
```

Each session is one JSON file with `session_id`, `cookies`, `local_storage`, `session_storage`, `url`, `created_at`, `last_active`. Corrupted files are skipped with a warning.

## Related

- Source: [`src/session_manager.py`](../src/session_manager.py)
- Example: [examples/session_persistence.py](../examples/session_persistence.py)
