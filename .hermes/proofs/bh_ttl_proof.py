"""Live stability proof: does Chrome survive a full session-TTL cycle?

The bug this guards against: `destroy()` closed the last page tab, headed
Chrome exited cleanly (`exit status 0`), the watchdog relaunched 30-40 min
later, and the cycle repeated for months.  The fix mints an anchor tab
before the close.

A short test cannot prove this — the cycle is 1800s of session TTL plus
keep-warm ticks.  So: watch the lifecycle log across at least one full TTL
window and report every Chrome exit with its reason and the tab count around
it.

Pass criteria:
  * no "exit status 0" that is NOT explained by an intentional shutdown
  * the browser is still up at the end
  * the anchor tab is present at the end

Usage: .venv/bin/python bh_ttl_proof.py [minutes]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:9557"
HEALTH = "http://127.0.0.1:8020/health"
LIFECYCLE = Path("/tmp/bh-chrome-lifecycle.log")

MINUTES = int(sys.argv[1]) if len(sys.argv) > 1 else 40
DEADLINE = time.time() + MINUTES * 60


def page_tabs() -> list[str]:
    try:
        with urllib.request.urlopen(f"{CDP}/json", timeout=6) as r:
            return [
                t["id"]
                for t in json.load(r)
                if t.get("type") == "page"
            ]
    except Exception:  # noqa: BLE001 — observer
        return []


def lifecycle_size() -> int:
    try:
        return LIFECYCLE.stat().st_size
    except OSError:
        return 0


def health() -> dict:
    try:
        with urllib.request.urlopen(HEALTH, timeout=6) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)}


print(f"watching {MINUTES} min (session TTL is 30 min) — one full cycle")
print(f"baseline page tabs: {len(page_tabs())}")
print(f"lifecycle log at byte {lifecycle_size()}")
print()

mark = lifecycle_size()
launches = exits = 0
last_report = 0

while time.time() < DEADLINE:
    time.sleep(60)
    elapsed = int(time.time() - (DEADLINE - MINUTES * 60))

    # read any new lifecycle lines
    try:
        with open(LIFECYCLE, "rb") as fh:  # noqa: BLE001
            fh.seek(mark)
            new = fh.read().decode("utf-8", "replace")
        mark += len(new)
    except OSError:  # noqa: PTH107
        new = ""

    for line in new.splitlines():
        if "launch " in line:
            launches += 1
            print(f"  [{elapsed:>3}min] LAUNCH  {line.strip()[:90]}")
        elif "exit " in line:
            exits += 1
            print(f"  [{elapsed:>3}min] EXIT    {line.strip()[:90]}")
            print(f"           page tabs now: {len(page_tabs())}")

    h = health()
    if int(time.time() - last_report) >= 300:
        last_report = time.time()
        print(
            f"  [{elapsed:>3}min] heartbeat: connected={h.get('connected')} "
            f"uptime={h.get('uptime_seconds', 0):.0f}s page_tabs={len(page_tabs())}"
        )

    if h.get("connected") is False and elapsed > 2:
        print(f"  [{elapsed:>3}min] !! browser DOWN at {elapsed} min — the bug is back")
        break

print()
print("=" * 62)
tabs = page_tabs()
h = health()
print(f"minutes watched : {MINUTES}")
print(f"launches        : {launches}")
print(f"exits           : {exits}")
print(f"connected       : {h.get('connected')}")
print(f"uptime_seconds  : {h.get('uptime_seconds', 0):.0f}")
print(f"page tabs now   : {len(tabs)}")

ok = True
if h.get("connected") is not True:
    print("FAIL: browser not connected at the end")
    ok = False
if launches > 0:
    print(f"FAIL: {launches} relaunch(es) — Chrome died again inside the window")
    ok = False
if exits > 0:
    print(f"FAIL: {exits} exit(s) — Chrome still self-exits")
    ok = False
if len(tabs) < 1:
    print("FAIL: no page tab left to hold the browser")
    ok = False

print()
print("RESULT: PASS" if ok else "RESULT: FAIL")
sys.exit(0 if ok else 1)
