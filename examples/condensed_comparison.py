"""Example: Compare condensed vs full page snapshot.

Requires a running Browser Helper instance on localhost:8001.

Usage:
    python examples/condensed_comparison.py

Prerequisites:
    - A page open in the browser (the example navigates to a news site)
    - Browser Helper server running
"""

import httpx

BASE_URL = "http://localhost:8001"


def print_stats(label: str, page: dict) -> None:
    """Print a compact summary of the snapshot."""
    print(f"\n{'─' * 50}")
    print(f"  {label}")
    print(f"{'─' * 50}")
    print(f"  URL:              {page.get('url', '?')[:70]}")
    print(f"  Title:            {page.get('title', '?')[:50]}")
    print(f"  Buttons found:    {len(page.get('buttons', []))}")
    print(f"  Form fields:      {len(page.get('form_fields', []))}")
    print(f"  Text preview len: {page.get('text_length', 0)}")
    print(f"  Condensed?        {page.get('condensed_fallback', None)}")

    # Summary counts (condensed only)
    for key in ("field_count", "button_count", "checkbox_count", "radio_count", "modal_count"):
        if key in page:
            print(f"  {key}: {page[key]}")

    # Show first 3 button labels for context
    buttons = page.get("buttons", [])
    if buttons:
        print(f"\n  First {min(3, len(buttons))} button(s):")
        for b in buttons[:3]:
            print(f"    - {b.get('text', '?')[:60]} @ ({b.get('x')}, {b.get('y')})")


def main():
    client = httpx.Client(base_url=BASE_URL, timeout=15)

    # Navigate to a typical page with nav/sidebar/footer
    print(">>> Navigating to a page with structure...")
    resp = client.post("/navigate", params={"url": "https://httpbin.org"})
    print(f"    Status: {resp.json().get('status')}\n")

    # 1. Full snapshot (standard)
    print(">>> Fetching FULL snapshot...")
    full_resp = client.post("/page/analyze")
    full_data = full_resp.json()
    full_page = full_data.get("result", {}).get("page", {})

    print_stats("FULL SNAPSHOT (includes nav, sidebar, footer)", full_page)

    # 2. Condensed snapshot
    print("\n>>> Fetching CONDENSED snapshot...")
    cond_resp = client.post("/page/analyze", params={"condensed": "true"})
    cond_data = cond_resp.json()
    cond_page = cond_data.get("result", {}).get("page", {})

    print_stats("CONDENSED SNAPSHOT (main content only)", cond_page)

    # 3. Summary comparison
    print(f"\n{'=' * 50}")
    print("  COMPARISON SUMMARY")
    print(f"{'=' * 50}")
    print(f"  {'Metric':25s} {'Full':>8s} {'Condensed':>10s}")
    print(f"  {'─' * 25} {'─' * 8} {'─' * 10}")
    print(f"  {'Buttons':25s} {len(full_page.get('buttons', [])):>8d} {len(cond_page.get('buttons', [])):>10d}")
    print(f"  {'Form fields':25s} {len(full_page.get('form_fields', [])):>8d} {len(cond_page.get('form_fields', [])):>10d}")
    print(f"  {'Text length':25s} {full_page.get('text_length', 0):>8d} {cond_page.get('text_length', 0):>10d}")

    client.close()


if __name__ == "__main__":
    main()
