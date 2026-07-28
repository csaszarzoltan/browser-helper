"""Example: Batch checkbox selection and deselection.

Requires a running Browser Helper instance on localhost:8000.

Usage:
    python examples/checkbox_ops.py

Prerequisites:
    - A page with checkboxes/radios open in the browser that has visible labels
    - Browser Helper server running
"""

import json

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


def main():
    client = httpx.Client(base_url=BASE_URL, timeout=10)

    # ------------------------------------------------------------------
    # 1. Navigate to a form page with checkboxes
    # ------------------------------------------------------------------
    print_response(
        "1. Navigate to a sample form page",
        client.post("/navigate", params={"url": "https://httpbin.org/forms/post"}),
    )

    # ------------------------------------------------------------------
    # 2. Analyze the page (check selected_options / visual_state)
    # ------------------------------------------------------------------
    analyze = client.post("/page/analyze")
    data = analyze.json()
    page = data.get("result", {}).get("page", {})

    print("Checkboxes found:")
    for field in page.get("form_fields", []):
        if field.get("type") in ("checkbox", "radio"):
            print(
                f"  [{field['type']}] {field.get('label', '?'):30s}"
                f" checked={field.get('checked')}"
            )

    print("\nSelected options (checked items):")
    for opt in page.get("selected_options", []):
        print(f"  {opt.get('label', '?'):30s} type={opt.get('type')}")

    print("\nVisual state (all checkbox/radio states):")
    for label, state in page.get("visual_state", {}).items():
        print(f"  {label:30s} → {state}")

    # ------------------------------------------------------------------
    # 3. Select a single checkbox by label
    # ------------------------------------------------------------------
    print_response(
        "3. Select single checkbox",
        client.post(
            "/checkbox/select",
            json={"text": "I am not a bot", "timeout": 5},
        ),
    )

    # ------------------------------------------------------------------
    # 4. Select multiple checkboxes in batch
    # ------------------------------------------------------------------
    print_response(
        "4. Batch select checkboxes",
        client.post(
            "/checkbox/select",
            json={"texts": ["Other comments:", "Email"], "timeout": 5},
        ),
    )

    # ------------------------------------------------------------------
    # 5. Deselect a single checkbox
    # ------------------------------------------------------------------
    print_response(
        "5. Deselect single checkbox",
        client.post(
            "/checkbox/deselect",
            json={"text": "Email", "timeout": 5},
        ),
    )

    # ------------------------------------------------------------------
    # 6. Batch deselect with confirmation
    # ------------------------------------------------------------------
    print_response(
        "6. Batch deselect with screenshot confirmation",
        client.post(
            "/checkbox/deselect?confirm=screenshot",
            json={"texts": ["Other comments:", "I am not a bot"], "timeout": 5},
        ),
    )

    # ------------------------------------------------------------------
    # 7. Verify final state
    # ------------------------------------------------------------------
    print_response(
        "7. Final page analysis (verify state changes)",
        client.post("/page/analyze"),
    )

    client.close()


if __name__ == "__main__":
    main()
