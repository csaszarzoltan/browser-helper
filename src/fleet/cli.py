"""Fleet CLI — thin httpx wrapper over the fleet REST API (analysis-brief §8.5).

Usage::

    python -m fleet.cli node list       # → GET  http://localhost:8000/fleet/nodes
    python -m fleet.cli session list    # → GET  http://localhost:8000/fleet/sessions

The coordinator base URL comes from ``FLEET_API_URL`` (default
``http://localhost:8000``) and the Bearer token from ``API_TOKEN`` (the same
variable the server's auth middleware reads).  When the coordinator is
unreachable the CLI prints a readable message and exits 0 — the integration
tests exercise the CLI without a live server, so a clean, explanatory report
is the contract, not a non-zero exit.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"


def _base_url() -> str:
    """Resolve the coordinator base URL from ``FLEET_API_URL``."""
    return os.environ.get("FLEET_API_URL", DEFAULT_BASE_URL).rstrip("/")


def _headers() -> dict[str, str]:
    """Attach the Bearer token when ``API_TOKEN`` is set (mirrors main.py)."""
    token = os.environ.get("API_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _fetch(path: str) -> dict[str, Any] | None:
    """GET ``path`` on the coordinator; None when unreachable or erroring."""
    url = f"{_base_url()}{path}"
    try:
        resp = httpx.get(url, headers=_headers(), timeout=5.0)
    except httpx.HTTPError as exc:
        print(f"fleet: coordinator unreachable at {url} ({type(exc).__name__}: {exc})")
        return None
    if resp.status_code >= 400:
        print(
            f"fleet: coordinator returned HTTP {resp.status_code} for {path}"
        )
        return None
    try:
        body = resp.json()
    except ValueError:
        print(f"fleet: unexpected non-JSON response from {url}")
        return None
    return body if isinstance(body, dict) else {}


def _node_list() -> int:
    """``fleet node list`` — print registered nodes and a health summary."""
    body = _fetch("/fleet/nodes")
    if body is None:
        return 0
    data = body.get("data") or {}
    nodes = data.get("nodes") or []
    print(
        f"node list: {len(nodes)} nodes "
        f"({data.get('healthy', 0)} healthy, {data.get('unhealthy', 0)} unhealthy)"
    )
    for node in nodes:
        state = "healthy" if node.get("healthy") else "unhealthy"
        print(
            f"  {node.get('node_id')}  {node.get('url')}  "
            f"{node.get('active_sessions', 0)}/{node.get('capacity', 0)} sessions  {state}"
        )
    return 0


def _session_list() -> int:
    """``fleet session list`` — print fleet sessions and a status summary."""
    body = _fetch("/fleet/sessions")
    if body is None:
        return 0
    data = body.get("data") or {}
    sessions = data.get("sessions") or []
    print(
        f"session list: {len(sessions)} sessions "
        f"({data.get('active', 0)} active, {data.get('queued', 0)} queued)"
    )
    for session in sessions:
        print(
            f"  {session.get('session_id')}  {session.get('status')}  "
            f"node={session.get('node_id')}  {session.get('node_url')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse ``node list`` / ``session list`` and dispatch to the REST API."""
    parser = argparse.ArgumentParser(
        prog="fleet.cli",
        description="Fleet orchestration CLI (thin wrapper over the REST API).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    node_parser = sub.add_parser("node", help="fleet node operations")
    node_sub = node_parser.add_subparsers(dest="action", required=True)
    node_sub.add_parser("list", help="list registered fleet nodes")

    session_parser = sub.add_parser("session", help="fleet session operations")
    session_sub = session_parser.add_subparsers(dest="action", required=True)
    session_sub.add_parser("list", help="list fleet sessions")

    args = parser.parse_args(argv)

    if args.command == "node" and args.action == "list":
        return _node_list()
    if args.command == "session" and args.action == "list":
        return _session_list()
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
