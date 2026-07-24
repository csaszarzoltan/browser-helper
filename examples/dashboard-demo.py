#!/usr/bin/env python3
"""
Browser Helper — WebSocket Dashboard Demo
==========================================

Demonstrates how to connect to the WebSocket streaming endpoint and consume
real-time messages: state updates, CDP events (console logs, navigation),
and heartbeat pings.

Prerequisites:
  - Chrome running with --remote-debugging-port=9555
  - Browser Helper CDP server running on http://localhost:8000
    (run: `uvicorn src.main:app --host 0.0.0.0 --port 8000`)

Usage:
  python examples/dashboard-demo.py

If Browser Helper is on a different host/port, set BH_URL:
  BH_URL=http://192.168.1.100:8000 python examples/dashboard-demo.py
"""

import asyncio
import json
import os
import sys
import time

import websockets

BH_URL = os.environ.get("BH_URL", "http://localhost:8000")
# Derive WS URL from HTTP URL
WS_URL = BH_URL.replace("http://", "ws://").replace("https://", "wss://")
WS_URL = f"{WS_URL}/ws"


def color(s, code):
    """Return string wrapped in ANSI color code."""
    return f"\033[{code}m{s}\033[0m"


def fmt_timestamp(iso_str):
    """Shorten ISO timestamp to HH:MM:SS."""
    if not iso_str:
        return "—"
    return iso_str[11:19]


async def main():
    print("=" * 60)
    print("  Browser Helper — WebSocket Dashboard Demo")
    print("=" * 60)
    print()
    print(f"  Connecting to {WS_URL} ...")
    print()

    # Track message counts
    counts: dict[str, int] = {}
    start = time.monotonic()

    try:
        async with websockets.connect(WS_URL, ping_interval=None) as ws:
            print(color("  ✓ Connected", "92"))
            print()

            async for raw in ws:
                elapsed = time.monotonic() - start
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    print(f"  [parse error] {raw[:100]}")
                    continue

                msg_type = msg.get("type", "unknown")
                counts[msg_type] = counts.get(msg_type, 0) + 1

                # ── Handle each message type ──────────────────────
                if msg_type == "hello":
                    state = msg.get("state", {})
                    log = msg.get("recent_log", [])
                    print(color(f"  [hello @ {elapsed:.1f}s]  Connected: {state.get('connected')}  "
                                f"Tabs: {state.get('tabs_count')}  "
                                f"Last op: {state.get('last_operation')}", "94"))
                    if log:
                        print(f"         Recent ops ({len(log)}):")
                        for entry in log[-3:]:
                            print(f"           • {entry.get('operation', '?')} "
                                  f"[{entry.get('status', '?')}] "
                                  f"{entry.get('duration_ms', '?')}ms")

                elif msg_type == "state_update":
                    state = msg.get("state", {})
                    print(f"  [state_update @ {elapsed:.1f}s]  "
                          f"Connected: {state.get('connected')}  "
                          f"Tabs: {state.get('tabs_count')}")

                elif msg_type == "console_log":
                    level = msg.get("level", "log")
                    text = msg.get("message", "")
                    # Colour-code by log level
                    level_colors = {"warn": "93", "error": "91", "info": "94", "debug": "90"}
                    c = level_colors.get(level, "0")
                    print(f"  [{color(f'console {level}', c)} @ {elapsed:.1f}s]  {text[:120]}")

                elif msg_type == "navigation":
                    url = msg.get("url", "")
                    print(f"  [{color('navigation', '96')} @ {elapsed:.1f}s]  {url}")

                elif msg_type == "operation":
                    op = msg.get("operation", "?")
                    status = msg.get("status", "?")
                    dur = msg.get("duration_ms", "?")
                    print(f"  [{color('operation', '95')} @ {elapsed:.1f}s]  "
                          f"{op} [{status}] {dur}ms")

                elif msg_type == "ping":
                    # Respond to heartbeat pings
                    await ws.send("pong")
                    # Print only every 10th ping to avoid spam
                    if counts.get("ping", 0) % 10 == 1:
                        print(f"  [{color('ping', '90')} @ {elapsed:.1f}s]  "
                              f"(missed pongs would trigger pruning)")

                elif msg_type == "pong":
                    print(f"  [{color('pong', '90')} @ {elapsed:.1f}s]  "
                          f"(heartbeat acknowledged)")

                elif msg_type == "error":
                    print(f"  [{color('error', '91')} @ {elapsed:.1f}s]  "
                          f"{msg.get('message', '')}  code={msg.get('code', '—')}")

                else:
                    print(f"  [{color(msg_type, '93')} @ {elapsed:.1f}s]  "
                          f"{json.dumps(msg)[:120]}")

                # Exit after receiving a pong or after 15 seconds of messages
                if msg_type == "pong" and counts.get("ping", 0) > 0:
                    print()
                    print(color("  First heartbeat round-trip complete. Exiting.", "92"))
                    break
                if elapsed > 15:
                    print()
                    print(color("  15 seconds elapsed. Exiting.", "93"))
                    break

    except websockets.exceptions.WebSocketException as e:
        print(color(f"  [FAIL] WebSocket error: {e}", "91"), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print()
        print("  Interrupted by user.")
        sys.exit(0)
    finally:
        # Summary
        print()
        print("=" * 60)
        print(f"  Session summary — {sum(counts.values())} messages received:")
        for msg_type, count in sorted(counts.items()):
            print(f"    {msg_type}: {count}")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
