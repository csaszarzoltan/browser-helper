"""Example: Session persistence via REST API.

Demonstrates the v1.8 session endpoints:
  - POST /api/v1/session/capture    (capture cookies + storage via CDP)
  - GET  /api/v1/session            (list sessions)
  - GET  /api/v1/session/{id}       (get session state)
  - POST /api/v1/session/restore    (restore a session)
  - POST /api/v1/session/cleanup    (remove expired sessions)
  - DELETE /api/v1/session/{id}     (delete a session)

Requires a running Browser Helper instance on localhost:8000 and a
reachable CDP WebSocket URL (ws://) — e.g. from a Chrome instance
started with --remote-debugging-port=9555.

Usage:
    python examples/session_persistence.py

Prerequisites:
    - Browser Helper server running on localhost:8000
    - Chrome running with remote debugging (ws:// CDP endpoint)
"""

from __future__ import annotations

import json
import sys

import httpx

BASE_URL = "http://localhost:8000"
CDP_URL = "ws://localhost:9555/devtools/page/example"  # replace with a real page target


def print_response(label: str, resp: httpx.Response) -> None:
    """Pretty-print the response."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    try:
        data = resp.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        print(resp.text)
    print()


def main() -> int:
    """Run the session persistence demo."""
    client = httpx.Client(base_url=BASE_URL, timeout=15)
    session_id = "demo-session"

    # 1. Capture current session state (cookies + localStorage + sessionStorage)
    print_response(
        "1. Capture session",
        client.post(
            "/api/v1/session/capture",
            json={"session_id": session_id, "cdp_url": CDP_URL},
        ),
    )

    # 2. List all sessions
    print_response("2. List sessions", client.get("/api/v1/session"))

    # 3. Get the captured session
    print_response(f"3. Get session {session_id}", client.get(f"/api/v1/session/{session_id}"))

    # 4. Restore it to a browser tab
    print_response(
        "4. Restore session",
        client.post(
            "/api/v1/session/restore",
            json={"session_id": session_id, "cdp_url": CDP_URL},
        ),
    )

    # 5. Run cleanup (removes expired sessions)
    print_response("5. Cleanup expired sessions", client.post("/api/v1/session/cleanup"))

    # 6. Delete the demo session
    print_response(f"6. Delete session {session_id}", client.delete(f"/api/v1/session/{session_id}"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
