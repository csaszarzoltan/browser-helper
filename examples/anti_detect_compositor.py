"""Example: Anti-Detection Compositor via REST API.

Demonstrates the v1.8 compositor endpoints:
  - POST /api/v1/compose              (compose a full anti-detection profile)
  - POST /api/v1/compose/resolve      (resolve fingerprint template -> JS patches)
  - POST /api/v1/compose/resolve-stealth (resolve stealth patches for a level)
  - POST /api/v1/compose/export       (export a bundle to JSON)
  - POST /api/v1/compose/import       (import a bundle from JSON)
  - POST /api/v1/compose/test         (run a detection test; needs CDP)

Requires a running Browser Helper instance on localhost:8000.

Usage:
    python examples/anti_detect_compositor.py

Prerequisites:
    - Browser Helper server running on localhost:8000
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
    """Run the anti-detection compositor demo."""
    client = httpx.Client(base_url=BASE_URL, timeout=30)

    bundle = {
        "name": "us-shopper",
        "fingerprint_template": "chrome-120",
        "fingerprint_config": {"timezone": "America/New_York"},
        "proxy_strategy": "round-robin",
        "stealth_level": "high",
        "session_ttl": 1800,
    }

    # 1. Compose a full anti-detection profile
    print_response("1. Compose anti-detection profile", client.post("/api/v1/compose", json=bundle))

    # 2. Resolve a fingerprint template into config + JS patches
    print_response(
        "2. Resolve fingerprint template",
        client.post(
            "/api/v1/compose/resolve",
            json={"template_name": "chrome-120", "overrides": {"timezone": "Europe/Berlin"}},
        ),
    )

    # 3. Resolve stealth patches for a level
    print_response(
        "3. Resolve stealth patches (high)",
        client.post("/api/v1/compose/resolve-stealth", json={"level": "high"}),
    )

    # 4. Export the bundle to a JSON file on the server
    print_response(
        "4. Export bundle",
        client.post("/api/v1/compose/export", json={"name": "us-shopper", "path": "/tmp/us-shopper.json"}),
    )

    # 5. Import the bundle back
    print_response(
        "5. Import bundle",
        client.post("/api/v1/compose/import", json={"path": "/tmp/us-shopper.json"}),
    )

    # 6. Run a detection test (requires a reachable CDP endpoint)
    print_response(
        "6. Detection test",
        client.post(
            "/api/v1/compose/test",
            json={"bundle": {"name": "us-shopper", "fingerprint_template": "chrome-120"}, "cdp_url": CDP_URL},
        ),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
