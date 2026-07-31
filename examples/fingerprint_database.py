"""Example: Fingerprint database via REST API.

Demonstrates the v1.8 fingerprint template endpoints:
  - GET  /api/v1/fingerprints              (list templates)
  - POST /api/v1/fingerprints              (add a template)
  - GET  /api/v1/fingerprints/{name}       (get a template)
  - PUT  /api/v1/fingerprints/{name}       (update a template)
  - POST /api/v1/fingerprints/generate     (generate a random template)
  - POST /api/v1/fingerprints/{name}/export (export to JSON file)
  - POST /api/v1/fingerprints/import       (import from JSON file)
  - DELETE /api/v1/fingerprints/{name}     (delete a template)

Requires a running Browser Helper instance on localhost:8000.

Usage:
    python examples/fingerprint_database.py

Prerequisites:
    - Browser Helper server running on localhost:8000
"""

from __future__ import annotations

import json
import sys

import httpx

BASE_URL = "http://localhost:8000"


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
    """Run the fingerprint database demo."""
    client = httpx.Client(base_url=BASE_URL, timeout=15)

    # 1. List shipped templates (chrome-120, firefox-linux, safari-ios, edge-windows)
    print_response("1. List fingerprint templates", client.get("/api/v1/fingerprints"))

    # 2. Generate a random template for a browser type
    print_response(
        "2. Generate random chrome template",
        client.post("/api/v1/fingerprints/generate", json={"browser": "chrome"}),
    )

    # 3. Add a custom template (persisted immediately)
    print_response(
        "3. Add custom template",
        client.post(
            "/api/v1/fingerprints",
            json={
                "name": "demo-chrome",
                "browser": "chrome",
                "signals": {"timezone": "Europe/Berlin", "screen": {"width": 1440, "height": 900}},
                "config": {"timezone": "Europe/Berlin"},
            },
        ),
    )

    # 4. Get the template back
    print_response("4. Get template demo-chrome", client.get("/api/v1/fingerprints/demo-chrome"))

    # 5. Update a field
    print_response(
        "5. Update template demo-chrome",
        client.put("/api/v1/fingerprints/demo-chrome", json={"signals": {"timezone": "Europe/London"}}),
    )

    # 6. Export to a JSON file on the server
    print_response(
        "6. Export template",
        client.post("/api/v1/fingerprints/demo-chrome/export", json={"path": "/tmp/demo-chrome.json"}),
    )

    # 7. Import it back under the same name (overwrites)
    print_response(
        "7. Import template",
        client.post("/api/v1/fingerprints/import", json={"path": "/tmp/demo-chrome.json"}),
    )

    # 8. Clean up the demo template
    print_response("8. Delete template demo-chrome", client.delete("/api/v1/fingerprints/demo-chrome"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
