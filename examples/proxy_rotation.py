"""Example: Proxy rotation manager via REST API.

Demonstrates the v1.8 proxy rotation endpoints:
  - POST /api/v1/proxy/load-from-env   (PROXY_LIST / PROXY_FILE)
  - POST /api/v1/proxy                 (add proxies)
  - GET  /api/v1/proxy                 (list proxies)
  - GET  /api/v1/proxy/health          (health summary)
  - POST /api/v1/proxy/health          (run health checks)
  - GET  /api/v1/proxy/stats           (usage statistics)
  - DELETE /api/v1/proxy/{id}          (remove a proxy)

Requires a running Browser Helper instance on localhost:8000.

Usage:
    PROXY_LIST="socks5://user:pass@host:1080" python examples/proxy_rotation.py

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
    """Run the proxy rotation demo."""
    client = httpx.Client(base_url=BASE_URL, timeout=15)

    # 1. Load proxies from PROXY_LIST / PROXY_FILE env vars
    print_response(
        "1. Load proxies from env (PROXY_LIST / PROXY_FILE)",
        client.post("/api/v1/proxy/load-from-env"),
    )

    # 2. Add proxies explicitly (type auto-detected from scheme)
    print_response(
        "2. Add proxies",
        client.post(
            "/api/v1/proxy",
            json={
                "proxies": [
                    {"url": "socks5://user:pass@host1:1080", "type": "SOCKS5", "tags": ["us"]},
                    {"url": "http://host2:3128", "tags": ["eu"]},
                ]
            },
        ),
    )

    # 3. List the pool
    print_response("3. List proxies", client.get("/api/v1/proxy"))

    # 4. Health summary (no probe)
    print_response("4. Health summary", client.get("/api/v1/proxy/health"))

    # 5. Run health checks (async, non-blocking)
    print_response("5. Health check all", client.post("/api/v1/proxy/health", json={}))

    # 6. Usage stats
    print_response("6. Pool stats", client.get("/api/v1/proxy/stats"))

    # 7. Remove the first proxy (if any)
    proxies = client.get("/api/v1/proxy").json().get("proxies", [])
    if proxies:
        proxy_id = proxies[0]["id"]
        print_response(f"7. Delete proxy {proxy_id}", client.delete(f"/api/v1/proxy/{proxy_id}"))
    else:
        print("\n7. No proxies to delete — pool is empty.\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
