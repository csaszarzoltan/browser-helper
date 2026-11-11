"""Urban VPN control: pick a country in the Urban VPN extension and connect.

Drives the extension's own popup page (opened as a background tab of the
browser-helper Chrome) over raw CDP, then confirms the result from the
extension's ``chrome.storage.local`` state. No engine import; only the CDP
HTTP endpoint is needed.

Also a one-command CLI that prints one PASS/FAIL line::

    python src/mcp_server/vpn.py            # connect Hungary
    python src/mcp_server/vpn.py DE         # connect Germany
    python src/mcp_server/vpn.py status
    python src/mcp_server/vpn.py off
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request

try:  # package import (MCP server); the CLI run below has no package
    from .serialization import tool_error, tool_result
except ImportError:  # pragma: no cover — CLI path
    tool_error = tool_result = None

EXT_ID = os.environ.get("BH_URBANVPN_ID", "eppiocemhmnlbhjplcgkofciiegomcon")
POPUP = f"chrome-extension://{EXT_ID}/popup/index.html"

# Reads only the connection and country code from the state key: the extension's
# storage also holds its proxy credentials, which must never leave the browser.
_JS_STATE = """chrome.storage.local.get('LOCATION_PROCESSOR_STATE').then(o => {
  let s = o.LOCATION_PROCESSOR_STATE; if (typeof s === 'string') s = JSON.parse(s);
  s = s || {};
  const ip = (document.body.innerText.match(/\\b\\d{1,3}(?:\\.\\d{1,3}){3}\\b/) || [null])[0];
  const name = document.querySelector('.location-view__name')?.innerText.trim() || null;
  return {connection: s.connection || 'UNKNOWN', code: s.location?.code || null, name, ip,
          playing: !!document.querySelector('.play-button--playing')};
})"""

_JS_PICK = """((want) => {
  want = want.toLowerCase();
  const opts = [...document.querySelectorAll('.selector-option')];
  if (!opts.length) { document.querySelector('.location-view')?.click(); return {open: true}; }
  const hit = opts.find(o => (o.querySelector('img')?.alt || '').toLowerCase() === want)
           || opts.find(o => (o.querySelector('.selector-option__name')?.innerText || '').trim().toLowerCase() === want)
           || opts.find(o => (o.querySelector('.selector-option__name')?.innerText || '').toLowerCase().startsWith(want));
  if (!hit) return {missing: true, names: [...new Set(opts.map(o => o.innerText.trim()))]};
  const name = hit.querySelector('.selector-option__name').innerText.trim();
  const code = (hit.querySelector('img')?.alt || '').toUpperCase();
  hit.click();
  return {picked: name, code};
})(%s)"""


def _cdp_base() -> str:
    env_port = os.environ.get("CHROME_AUTO_PORT")
    if env_port:
        return f"http://127.0.0.1:{env_port}"
    try:
        from main import _local_cdp_http  # the engine's saved port, when importable

        return _local_cdp_http()
    except Exception:  # noqa: BLE001 — CLI or engine-less run
        return f"http://127.0.0.1:{os.environ.get('BH_CDP_PORT', '9557')}"


def _http_json(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


class _Page:
    """Minimal CDP page connection: evaluate JS, close the tab."""

    def __init__(self, ws, base: str, tab_id: str):
        self.ws, self.base, self.tab_id, self._id = ws, base, tab_id, 0

    async def eval(self, js: str):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate", "params": {
            "expression": js, "returnByValue": True, "awaitPromise": True}}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), 10))
            if msg.get("id") == mid:
                res = msg.get("result", {})
                if "exceptionDetails" in res:
                    return None
                return res.get("result", {}).get("value")


async def _open_popup(base: str):
    import websockets

    version = await asyncio.to_thread(_http_json, f"{base}/json/version")
    async with websockets.connect(version["webSocketDebuggerUrl"], max_size=None) as bws:
        await bws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                   "params": {"url": POPUP, "background": True}}))
        while True:
            msg = json.loads(await asyncio.wait_for(bws.recv(), 10))
            if msg.get("id") == 1:
                tab_id = msg["result"]["targetId"]
                break
    for _ in range(20):
        tabs = await asyncio.to_thread(_http_json, f"{base}/json/list")
        tab = next((t for t in tabs if t["id"] == tab_id), None)
        if tab and tab.get("webSocketDebuggerUrl"):
            return tab_id, tab["webSocketDebuggerUrl"]
        await asyncio.sleep(0.25)
    raise RuntimeError("popup tab did not appear")


async def _wait(page: _Page, pred, timeout: float, step: float = 0.5):
    end = time.monotonic() + timeout
    state = None
    while time.monotonic() < end:
        state = await page.eval(_JS_STATE)
        if state and pred(state):
            return state, True
        await asyncio.sleep(step)
    return state, False


async def run(action: str = "connect", country: str = "HU", timeout: float = 45.0) -> dict:
    """Do *action* (connect | disconnect | status). Returns {ok, ...} or {ok: False, code, message}."""
    import websockets

    base = _cdp_base()
    try:
        tab_id, ws_url = await _open_popup(base)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": "browser_unreachable",
                "message": f"Chrome CDP at {base} unreachable or popup failed: {exc}"}
    try:
        async with websockets.connect(ws_url, max_size=None) as ws:
            page = _Page(ws, base, tab_id)
            state, ready = await _wait(page, lambda s: s.get("name") is not None, 15)
            if not ready:
                return {"ok": False, "code": "extension_not_ready",
                        "message": f"Urban VPN popup did not load ({POPUP}); is the extension installed and enabled?"}
            if action == "status":
                return {"ok": True, **_public(state)}
            if action == "disconnect":
                if state["playing"] or state["connection"] == "CONNECTED":
                    await page.eval("document.querySelector('.play-button')?.click()")
                state, done = await _wait(page, lambda s: s["connection"] != "CONNECTED" and not s["playing"], timeout)
                return {"ok": done, **_public(state)} if done else {
                    "ok": False, "code": "timeout", "message": "still connected", **_public(state)}

            want = country.strip()
            same = lambda s: s["connection"] == "CONNECTED" and (
                (s.get("code") or "").upper() == want.upper() or (s.get("name") or "").lower() == want.lower())
            if same(state):
                return {"ok": True, "changed": False, **_public(state)}
            picked = None
            for _ in range(20):
                res = await page.eval(_JS_PICK % json.dumps(want))
                if res and res.get("missing"):
                    return {"ok": False, "code": "unknown_country",
                            "message": f"no Urban VPN location matches {want!r}",
                            "locations": res["names"]}
                if res and res.get("picked"):
                    picked = res
                    break
                await asyncio.sleep(0.5)
            if picked is None:
                return {"ok": False, "code": "selector_failed", "message": "country list did not open"}
            target = picked["code"] or want
            hit = lambda s: s["connection"] == "CONNECTED" and (s.get("code") or "").upper() == target.upper()
            state, done = await _wait(page, hit, min(8.0, timeout))
            if not done and not state.get("playing") and state.get("connection") != "CONNECTING":
                await page.eval("document.querySelector('.play-button')?.click()")  # picked but idle: press play
            if not done:
                state, done = await _wait(page, hit, timeout)
            if not done:
                return {"ok": False, "code": "timeout",
                        "message": f"{picked['picked']} selected but not connected after {timeout:.0f}s",
                        **_public(state)}
            await asyncio.sleep(1.5)  # the IP line updates after the state
            state = await page.eval(_JS_STATE) or state
            return {"ok": True, "changed": True, **_public(state)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": "failed", "message": str(exc)}
    finally:
        try:
            await asyncio.to_thread(_http_json, f"{base}/json/close/{tab_id}")
        except Exception:  # noqa: BLE001,S110 — /json/close returns text, not JSON; the tab is gone either way
            pass


def _public(state: dict | None) -> dict:
    state = state or {}
    return {"connection": state.get("connection"), "country": state.get("name"),
            "code": state.get("code"), "ip": state.get("ip")}


async def vpn(action: str = "connect", country: str = "HU", timeout: int = 45, ctx=None) -> str:
    """MCP handler: Urban VPN connect / disconnect / status (capability ``browser.core``)."""
    if os.environ.get("BH_TEST_NO_CHROME") == "1":
        return tool_error("vpn", "not_connected", "browser disabled (BH_TEST_NO_CHROME=1)")
    if action not in ("connect", "disconnect", "status"):
        return tool_error("vpn", "invalid_args", "action must be connect, disconnect or status")
    res = await run(action, country, float(timeout))
    if not res.pop("ok"):
        code, msg = res.pop("code", "failed"), res.pop("message", "failed")
        return tool_error("vpn", code, msg, res or None)
    return tool_result("vpn", res)


def _main(argv: list[str]) -> int:
    import logging

    logging.disable(logging.INFO)  # the engine import logs at INFO; the CLI prints one line
    arg = (argv[0] if argv else "HU").strip()
    action, country = {"status": ("status", "HU"), "off": ("disconnect", "HU")}.get(arg.lower(), ("connect", arg))
    res = asyncio.run(run(action, country))
    if res.get("ok"):
        print(f"PASS vpn {action}: {res.get('connection')} {res.get('country') or ''} ip={res.get('ip')}")
        return 0
    print(f"FAIL vpn {action}: {res.get('code')}: {res.get('message')}")
    if res.get("locations"):
        print("locations: " + ", ".join(res["locations"]))
    return 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
