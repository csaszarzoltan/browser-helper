"""Example: Anti-detection profile management via REST API.

Creates, lists, and manages anti-detection browser profiles
with predefined fingerprint templates.

Requires a running Browser Helper instance on localhost:8000.

Usage:
    python examples/anti_detection_profiles.py

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
    """Run the anti-detection profile demo."""
    client = httpx.Client(base_url=BASE_URL, timeout=10)

    # 1. Create an anti-detection profile from a predefined template
    print_response(
        "1. Create anti-detection profile (stealth-chrome-120)",
        client.post(
            "/profiles",
            json={
                "name": "demo-stealth",
                "description": "Demo stealth profile",
                "profile_type": "stealth-chrome-120",
            },
        ),
    )

    # 2. Create a mobile Safari profile
    print_response(
        "2. Create mobile profile (mobile-safari-ios)",
        client.post(
            "/profiles",
            json={
                "name": "demo-mobile",
                "description": "Demo mobile profile",
                "profile_type": "mobile-safari-ios",
            },
        ),
    )

    # 3. List all profiles
    print_response(
        "3. List all profiles",
        client.get("/profiles"),
    )

    # 4. Get profile details (includes fingerprint)
    print_response(
        "4. Get profile details (demo-stealth)",
        client.get("/profiles/demo-stealth"),
    )

    # 5. Generate a randomized fingerprint for the profile
    print_response(
        "5. Generate randomized fingerprint",
        client.post(
            "/profile/demo-stealth/fingerprint",
            json={"overrides": {"timezone": "Europe/Berlin"}},
        ),
    )

    # 6. Get the fingerprint + fingerprint_config
    print_response(
        "6. Get fingerprint + config",
        client.get("/profile/demo-stealth/fingerprint"),
    )

    # 7. Set fingerprint config
    print_response(
        "7. Set fingerprint config",
        client.put(
            "/profile/demo-stealth/fingerprint",
            json={
                "timezone": "America/New_York",
                "locale": "en-US",
                "hardware_concurrency": 8,
                "device_memory": 16,
                "color_depth": 30,
            },
        ),
    )

    # 8. Delete the demo profiles
    print_response(
        "8. Delete demo-stealth profile",
        client.delete("/profiles/demo-stealth"),
    )
    print_response(
        "9. Delete demo-mobile profile",
        client.delete("/profiles/demo-mobile"),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
