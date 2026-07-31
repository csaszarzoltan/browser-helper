"""Example: Fingerprint engine and randomization API.

Demonstrates using the FingerprintEngine, FingerprintRandomizer,
and signal modules to generate JS patches for browser fingerprint
evasion — both programmatically and via REST API.

This file contains two usage modes:
1. Programmatic (offline) — uses FingerprintEngine + FingerprintRandomizer
2. REST API — uses /profile/{name}/fingerprint endpoints

Running this file requires a running Browser Helper on localhost:8000.

Usage:
    python examples/fingerprint_api.py

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
    """Run the fingerprint API demo."""
    client = httpx.Client(base_url=BASE_URL, timeout=10)

    # 1. Create a profile to work with
    print_response(
        "1. Create profile for fingerprint demo",
        client.post(
            "/profiles",
            json={
                "name": "fp-demo",
                "description": "Fingerprint demo profile",
                "profile_type": "stealth-chrome-120",
            },
        ),
    )

    # 2. Generate initial fingerprint with overrides
    print_response(
        "2. Generate fingerprint with timezone override",
        client.post(
            "/profile/fp-demo/fingerprint",
            json={
                "overrides": {
                    "timezone": "Europe/London",
                    "platform": "MacIntel",
                    "hardware_concurrency": 12,
                },
            },
        ),
    )

    # 3. Retrieve the fingerprint + config
    print_response(
        "3. Retrieve fingerprint + config",
        client.get("/profile/fp-demo/fingerprint"),
    )

    # 4. Set fingerprint configuration
    print_response(
        "4. Set fingerprint config (device + screen)",
        client.put(
            "/profile/fp-demo/fingerprint",
            json={
                "device_memory": 32,
                "screen_width": 2560,
                "screen_height": 1440,
                "locale": "en-GB",
                "canvas_noise_seed": 42,
            },
        ),
    )

    # 5. Generate again — picks up the config defaults
    print_response(
        "5. Generate fingerprint with new config defaults",
        client.post("/profile/fp-demo/fingerprint"),
    )

    # 6. Attempt to set an unknown config field (should 422)
    print_response(
        "6. Attempt invalid config field (expect 422)",
        client.put(
            "/profile/fp-demo/fingerprint",
            json={"unknown_field": "value"},
        ),
    )

    # 7. Clean up
    print_response(
        "7. Delete fp-demo profile",
        client.delete("/profiles/fp-demo"),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
