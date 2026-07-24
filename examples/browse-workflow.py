#!/usr/bin/env python3
"""
Browser Helper — Complete Workflow Example
===========================================

Demonstrates a typical automation pipeline using the Browser Helper REST API:

  1. Connect to Chrome via CDP
  2. Navigate to a search engine
  3. Type a query and submit
  4. Wait for results
  5. Extract result links and titles
  6. Take a screenshot and PDF
  7. Capture network requests
  8. Save the session for later replay

Prerequisites:
  - Chrome running with --remote-debugging-port=9555
  - Browser Helper server running on http://localhost:8000
    (run: `uvicorn src.main:app --host 0.0.0.0 --port 8000`)

Usage:
  python examples/browse-workflow.py

If Browser Helper is on a different host/port, set BH_URL:
  BH_URL=http://192.168.1.100:8000 python examples/browse-workflow.py
"""

import base64
import json
import os
import sys
import urllib.request
import urllib.error

BH_URL = os.environ.get("BH_URL", "http://localhost:8000")


def api(path, method="POST", body=None):
    """Send a request to the Browser Helper API and return parsed JSON."""
    url = f"{BH_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        return {"status": "error", "error": err_body, "http_code": e.code}


def check(resp, step):
    """Abort with a clear message if the API response indicates an error."""
    if resp.get("status") == "error":
        print(f"  [FAIL] {step}: {resp.get('error', resp)}")
        sys.exit(1)
    print(f"  [OK]   {step}")


def main():
    print("=" * 60)
    print("Browser Helper — Complete Workflow Demonstration")
    print("=" * 60)

    # ------------------------------------------------------------------ #
    # 1. Health check (no CDP connection needed)
    # ------------------------------------------------------------------ #
    print("\n[1] Checking server health ...")
    health = api("/health", "GET")
    check(health, "health check")
    print(f"      uptime: {health.get('uptime_seconds', '?')}s")
    print(f"      memory: {health.get('memory_mb', '?')} MB")

    # ------------------------------------------------------------------ #
    # 2. Connect to CDP
    # ------------------------------------------------------------------ #
    print("\n[2] Connecting to Chrome CDP ...")
    conn = api("/connect", "POST")
    check(conn, "CDP connect")
    print(f"      target: {conn.get('result', {}).get('title', '?')}")
    print(f"      tabs:   {conn.get('result', {}).get('tabs_count', '?')}")

    # ------------------------------------------------------------------ #
    # 3. Navigate to a page
    # ------------------------------------------------------------------ #
    print('\n[3] Navigating to https://httpbin.org/links/10 ...')
    nav = api("/navigate?url=https://httpbin.org/links/10", "POST")
    check(nav, "navigate")
    print(f"      frame: {nav.get('result', {}).get('frame_id', '?')[:16]}...")

    # ------------------------------------------------------------------ #
    # 4. Get visible page text
    # ------------------------------------------------------------------ #
    print("\n[4] Extracting visible text ...")
    text_resp = api("/get_text", "POST")
    check(text_resp, "get_text")
    text = text_resp.get("result", {}).get("text", "")
    print(f"      text length: {len(text)} chars")
    print(f"      preview:     {text[:120]}...")

    # ------------------------------------------------------------------ #
    # 5. Query DOM — extract all links
    # ------------------------------------------------------------------ #
    print('\n[5] Querying all <a> links ...')
    dom = api("/dom_query", "POST", {"selector": "a", "attribute": "href"})
    check(dom, "dom_query")
    links = dom.get("result", {}).get("items", [])
    print(f"      found {len(links)} links")
    for link in links[:5]:
        print(f"        - {link}")
    if len(links) > 5:
        print(f"        ... and {len(links) - 5} more")

    # ------------------------------------------------------------------ #
    # 6. Execute JavaScript
    # ------------------------------------------------------------------ #
    print("\n[6] Running JavaScript to get document title ...")
    js_resp = api("/eval", "POST", {"js": "document.title"})
    check(js_resp, "eval")
    print(f"      page title: {js_resp.get('result', {}).get('result', '?')}")

    # ------------------------------------------------------------------ #
    # 7. Header stats via JS
    # ------------------------------------------------------------------ #
    print("\n[7] Counting DOM elements via JS ...")
    count_js = (
        "JSON.stringify({"
        "  links: document.querySelectorAll('a').length,"
        "  paragraphs: document.querySelectorAll('p').length,"
        "  divs: document.querySelectorAll('div').length,"
        "  images: document.querySelectorAll('img').length"
        "})"
    )
    stats = api("/eval", "POST", {"js": count_js})
    check(stats, "DOM stats")
    print(f"      page stats: {stats.get('result', {}).get('result', '?')}")

    # ------------------------------------------------------------------ #
    # 8. Take a screenshot
    # ------------------------------------------------------------------ #
    print("\n[8] Taking screenshot ...")
    ss = api("/screenshot", "POST")
    check(ss, "screenshot")
    img_data = ss.get("result", {}).get("data", "")
    if img_data:
        with open("screenshot.jpg", "wb") as f:
            f.write(base64.b64decode(img_data))
        print(f"      saved: screenshot.jpg ({len(img_data)} bytes base64)")

    # ------------------------------------------------------------------ #
    # 9. Export as PDF
    # ------------------------------------------------------------------ #
    print("\n[9] Exporting page as PDF ...")
    pdf_resp = api("/pdf", "POST")
    check(pdf_resp, "PDF export")
    pdf_data = pdf_resp.get("result", {}).get("data", "")
    if pdf_data:
        with open("page.pdf", "wb") as f:
            f.write(base64.b64decode(pdf_data))
        print(f"      saved: page.pdf ({len(pdf_data)} bytes base64)")

    # ------------------------------------------------------------------ #
    # 10. Start network monitoring, reload, view log
    # ------------------------------------------------------------------ #
    print("\n[10] Starting network monitoring ...")
    net_start = api("/network/start", "POST")
    check(net_start, "network start")

    print("      Reloading page to capture requests ...")
    api("/navigate?url=https://httpbin.org/links/10", "POST")

    net_log = api("/network/log", "GET")
    check(net_log, "network log")
    entries = net_log.get("result", {}).get("entries", [])
    print(f"      captured {len(entries)} network entries")
    for entry in entries[:4]:
        url = entry.get("url", "?")
        method = entry.get("method", "?")
        status = entry.get("status", "?")
        print(f"        [{status}] {method} {url[:80]}")

    # Stop monitoring
    api("/network/stop", "POST")
    print("      network monitoring stopped")

    # ------------------------------------------------------------------ #
    # 11. Save browser session
    # ------------------------------------------------------------------ #
    print("\n[11] Saving browser session ...")
    session = api("/session/save", "POST")
    check(session, "session save")
    session_data = session.get("result", {}).get("session", {})
    with open("session_backup.json", "w") as f:
        json.dump(session_data, f, indent=2)
    print(f"      saved: session_backup.json")
    print(f"      cookies:      {len(session_data.get('cookies', []))}")
    print(f"      localStorage: {len(session_data.get('localStorage', {}))} keys")

    # ------------------------------------------------------------------ #
    # 12. Verify tab management
    # ------------------------------------------------------------------ #
    print("\n[12] Listing open tabs ...")
    tabs = api("/tabs", "GET")
    check(tabs, "list tabs")
    tab_list = tabs.get("result", [])
    print(f"      open tabs: {len(tab_list)}")
    for t in tab_list:
        active = " [active]" if t.get("active") else ""
        print(f"        - {t.get('title', '?')} ({t.get('url', '?')[:60]}){active}")

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 60)
    print("Workflow completed successfully!")
    print("=" * 60)
    print(f"\nFiles created in current directory:")
    for fname in ["screenshot.jpg", "page.pdf", "session_backup.json"]:
        if os.path.exists(fname):
            size_kb = os.path.getsize(fname) / 1024
            print(f"  - {fname} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
