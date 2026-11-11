#!/usr/bin/env python3
"""Multi-agent tab isolation check for the browser-helper MCP server.

Starts a private headless Chrome on a free port (the person's own Chrome is never
touched), runs several MCP stdio servers against it the way parallel agents do,
and prints one PASS/FAIL line per check:

  own_tab        every agent reads its own page, never another agent's
  blank_survives an agent whose tab is still about:blank keeps it when another
                 agent starts (a cross-process orphan sweep must not close it)
  closed_tab     after one agent's tab is closed by hand, that agent gets a new
                 tab of its own and the others keep theirs
  exit_closes    an agent's tab is closed when its MCP server exits (stdin closed)
  sigterm_closes the same when the server is stopped with SIGTERM
  first_call_own an agent whose first call is a direct-client tool (get_page_text)
                 reads its own new tab, not another agent's page
  idle_closes    a tab idle past BH_MCP_IDLE_CLOSE_SEC is closed; the next call
                 gets a fresh tab

Usage:  .venv/bin/python scripts/check_tab_isolation.py
Exit code 0 only when every check passes.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from mcp_integration_helpers import StdioTransport

_INIT = {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "iso", "version": "1"}}
RESULTS: list[tuple[str, bool, str]] = []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pages(port: int) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


def _chrome(port: int, profile: str) -> subprocess.Popen:
    exe = shutil.which("google-chrome") or shutil.which("chromium") or "/opt/google/chrome/chrome"
    proc = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={port}",
                             f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            _pages(port)
            return proc
        except Exception:  # noqa: BLE001 — not up yet
            time.sleep(0.2)
    raise SystemExit("FAIL setup: headless Chrome did not start")


class Agent:
    _rid = 100

    def __init__(self, name: str, port: int, **env: str):
        self.name = name
        self.srv = StdioTransport("--transport", "stdio", timeout=60.0, env={
            "MCP_PROFILE": "compact", "BH_TEST_NO_CHROME": "0", "CHROME_AUTO_PORT": str(port), **env})
        self.srv.request("initialize", _INIT, req_id=1)

    def bh(self, action: str, args: dict) -> dict:
        Agent._rid += 1
        resp = self.srv.request("tools/call", {"name": "bh", "arguments": {"action": action, "args": args}},
                                req_id=Agent._rid)
        text = resp["result"]["content"][0]["text"]
        try:
            return json.loads(text)
        except ValueError:
            return {"status": "error", "error": {"message": text}}

    def js(self, expr: str):
        env = self.bh("eval", {"js": expr})
        data = env.get("data")
        if isinstance(data, dict) and "result" in data:
            data = data["result"]
        return data if env.get("status") == "ok" else f"ERR {env.get('error')}"

    def go(self, marker: str) -> None:
        self.bh("navigate", {"url": f"data:text/html,<title>{marker}</title>{marker}"})

    def close(self) -> None:
        self.srv.close()


def check(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)


def main() -> int:
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="bh-iso-")
    chrome = _chrome(port, profile)
    agents: list[Agent] = []
    try:
        a, b, c = (Agent(n, port) for n in "ABC")
        agents += [a, b, c]
        for ag in agents:
            ag.go(ag.name)
        seen = {ag.name: ag.js("document.title") for ag in agents}
        check("own_tab", all(seen[n] == n for n in seen), f"titles seen {seen}")

        d = Agent("D", port)
        agents.append(d)
        d.js("window.__m = 'D'")  # D's tab stays about:blank
        e = Agent("E", port)
        agents.append(e)
        e.js("1")  # E mints its own session and tab
        time.sleep(1)
        got = d.js("window.__m || ''")
        check("blank_survives", got == "D", f"D marker after E started: {got!r}")

        a_tab = next((t["id"] for t in _pages(port) if t.get("title") == "A"), None)
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{a_tab}", timeout=5).read()
        time.sleep(1)
        after = {ag.name: ag.js("document.title") for ag in (a, b, c)}
        ok = after["A"] not in ("B", "C") and after["B"] == "B" and after["C"] == "C"
        check("closed_tab", ok, f"titles after closing A's tab {after}")

        before = {t["id"] for t in _pages(port) if t.get("title") == "B"}
        b.close()
        agents.remove(b)
        time.sleep(3)
        left = {t["id"] for t in _pages(port) if t.get("title") == "B"}
        check("exit_closes", bool(before) and not left, f"B tabs before exit {len(before)}, after {len(left)}")

        f = Agent("F", port)
        agents.append(f)
        f.go("F")
        f.srv.proc.terminate()
        f.srv.proc.wait(timeout=15)
        agents.remove(f)
        time.sleep(1)
        left = [t for t in _pages(port) if t.get("title") == "F"]
        check("sigterm_closes", not left, f"F tabs after SIGTERM {len(left)}")

        g = Agent("G", port)
        agents.append(g)
        env = g.bh("get_page_text", {})
        text = json.dumps(env.get("data"))[:200]
        check("first_call_own", env.get("status") == "ok" and not any(m in text for m in ("\"C\"", ">C<", "D'")) and "C" not in text,
              f"G first get_page_text: {env.get('status')} {text}")

        h = Agent("H", port, BH_MCP_IDLE_CLOSE_SEC="3")
        agents.append(h)
        h.go("H")
        time.sleep(8)
        gone = not [t for t in _pages(port) if t.get("title") == "H"]
        again = h.js("document.title")
        check("idle_closes", gone and again == "", f"H tab closed after idle: {gone}; next call title {again!r}")
    finally:
        for ag in agents:
            try:
                ag.close()
            except Exception:  # noqa: BLE001,S110 — teardown
                pass
        chrome.terminate()
        shutil.rmtree(profile, ignore_errors=True)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"{'PASS' if not failed else 'FAIL'} tab isolation: {len(RESULTS) - len(failed)}/{len(RESULTS)}"
          + (f" failed {failed}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    os.chdir(REPO)
    raise SystemExit(main())
