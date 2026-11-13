"""Cross-process country lease for the one shared Urban VPN.

Chrome has one VPN exit at a time and every agent runs its own MCP server
process, so the lease state lives in a small JSON file guarded by ``flock``.
Agents that want the same country share it; an agent that wants another
country waits in a FIFO queue until the last holder of the current country
releases (``vpn disconnect``, process exit, or a dead pid / max hold time).
"""

from __future__ import annotations

import asyncio
import atexit
import fcntl
import json
import os
import time
from pathlib import Path

MAX_HOLD_SEC = float(os.environ.get("BH_VPN_MAX_HOLD_SEC", "1800"))
_STATE = Path(os.environ.get("BH_VPN_LEASE_FILE", str(Path.home() / ".cache" / "browser-helper" / "vpn_lease.json")))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _Locked:
    """Context manager: exclusive flock on the state file, yields the loaded state, saves on exit."""

    def __enter__(self) -> dict:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(str(_STATE) + ".lock", "w")  # closed in __exit__
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        try:
            self.state = json.loads(_STATE.read_text())
        except (OSError, ValueError):
            self.state = {}
        self.state.setdefault("holders", {})
        self.state.setdefault("queue", [])
        now = time.time()
        self.state["holders"] = {p: h for p, h in self.state["holders"].items()
                                 if _alive(int(p)) and now - h["since"] < MAX_HOLD_SEC}
        self.state["queue"] = [q for q in self.state["queue"] if _alive(q["pid"])]
        return self.state

    def __exit__(self, *exc) -> None:
        tmp = _STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        tmp.replace(_STATE)
        self._fh.close()


def _norm(country: str) -> str:
    return country.strip().upper()


def _can_go(state: dict, pid: int, country: str) -> bool:
    if any(h["country"] != country for p, h in state["holders"].items() if int(p) != pid):
        return False
    ahead = [q for q in state["queue"] if q["pid"] != pid]
    mine = next((q for q in state["queue"] if q["pid"] == pid), None)
    if mine is None:
        return not any(q["country"] != country for q in ahead)
    return not any(q["country"] != country and q["ts"] < mine["ts"] for q in ahead)


async def acquire(country: str, wait: float = 300.0, pid: int | None = None) -> dict:
    """Take (or share) the lease for *country*. Returns {ok, waited} or {ok: False, code, message, holders}."""
    pid = pid or os.getpid()
    country = _norm(country)
    start = time.monotonic()
    queued = False
    while True:
        with _Locked() as st:
            if _can_go(st, pid, country):
                st["queue"] = [q for q in st["queue"] if q["pid"] != pid]
                st["holders"][str(pid)] = {"country": country, "since": time.time()}
                atexit.register(release, pid)
                return {"ok": True, "waited": round(time.monotonic() - start, 1)}
            if not queued:
                st["queue"].append({"pid": pid, "country": country, "ts": time.time()})
                queued = True
            holders = sorted({h["country"] for h in st["holders"].values()})
        if time.monotonic() - start >= wait:
            with _Locked() as st:
                st["queue"] = [q for q in st["queue"] if q["pid"] != pid]
            return {"ok": False, "code": "vpn_busy",
                    "message": f"VPN in use for {', '.join(holders)} by other agents; waited {wait:.0f}s for {country}",
                    "holders": holders}
        await asyncio.sleep(1.0)


def release(pid: int | None = None) -> int:
    """Drop this process's lease and queue entry. Returns how many other holders remain."""
    pid = pid or os.getpid()
    try:
        with _Locked() as st:
            st["holders"].pop(str(pid), None)
            st["queue"] = [q for q in st["queue"] if q["pid"] != pid]
            return len(st["holders"])
    except OSError:
        return 0
