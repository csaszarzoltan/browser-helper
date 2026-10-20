"""``bh doctor``: check the Chrome connection and say how to fix each failure.

Read-only: it sends two GET requests (Chrome's ``/json/version`` and the
service's ``/ready``), reads ``/proc`` for the Chrome command line on Linux,
and opens no tab.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

import click

PLACEHOLDER_TOKENS = {
    "changeme", "your-token", "replace-me", "placeholder", "changethis",
    "your_token_here", "your_api_token_here", "token_here",
}


@dataclass
class Check:
    name: str
    status: str  # PASS | FAIL | WARN | SKIP
    detail: str
    fix: str = ""


def chrome_command(port: int) -> str:
    profile = "$HOME/bh-chrome-profile"
    flags = f"--remote-debugging-port={port} --user-data-dir=\"{profile}\""
    system = platform.system()
    if system == "Darwin":
        return f'"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" {flags}'
    if system == "Windows":
        return f'chrome.exe --remote-debugging-port={port} --user-data-dir="%USERPROFILE%\\bh-chrome-profile"'
    return f"google-chrome {flags}"


def _get_json(url: str, timeout: float) -> tuple[int, dict | None]:
    """GET *url*; return (status, body). Status 0 means nothing answered."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def check_chrome(host: str, port: int, timeout: float) -> tuple[Check, dict | None]:
    status, body = _get_json(f"http://{host}:{port}/json/version", timeout)
    if status == 200 and isinstance(body, dict):
        return Check("Chrome debug port", "PASS", f"{body.get('Browser', 'Chrome')} answers on {host}:{port}"), body
    return Check(
        "Chrome debug port", "FAIL", f"nothing answers on {host}:{port}",
        "Start Chrome with its own profile directory (Chrome 136+ ignores the port on the default "
        f"profile):\n    {chrome_command(port)}",
    ), None


def _parse_cmdline(raw: bytes) -> list[str]:
    """Split a /proc cmdline into arguments.

    Chrome's main process rewrites its argv into one space-separated string, so
    splitting on NUL alone leaves a single argument and the flags are not found.
    """
    return [a for a in re.split(r"[\0 ]+", raw.decode("utf-8", "replace")) if a]


def _chrome_proc(port: int) -> tuple[str, list[str]] | None:
    """(pid, command line) of the process started with this debugging port (Linux only)."""
    if not os.path.isdir("/proc"):
        return None
    want = f"--remote-debugging-port={port}"
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                args = _parse_cmdline(fh.read())
        except OSError:
            continue
        if want in args:
            return pid, args
    return None


def _chrome_args(port: int) -> list[str] | None:
    found = _chrome_proc(port)
    return found[1] if found else None


def check_profile(port: int) -> Check:
    args = _chrome_args(port)
    if args is None:
        return Check("Chrome profile", "SKIP", "command line not readable on this system")
    if any(a.startswith("--user-data-dir=") and a.split("=", 1)[1] for a in args):
        return Check("Chrome profile", "PASS", "started with its own --user-data-dir")
    return Check(
        "Chrome profile", "WARN", "no --user-data-dir on the command line",
        f"Restart Chrome with:\n    {chrome_command(port)}",
    )


def _cgroup_unit(pid: str) -> str | None:
    """Name of the systemd service whose control group holds *pid*, if any."""
    try:
        with open(f"/proc/{pid}/cgroup", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    m = re.search(r"/([^/\s]+\.service)(?:/|\s|$)", text)
    return m.group(1) if m else None


def _kill_mode(unit: str) -> str | None:
    """The unit's KillMode, read with `systemctl show` (read-only); None when unreadable."""
    try:
        out = subprocess.run(
            ["systemctl", "show", "-p", "KillMode", "--value", unit],
            capture_output=True, text=True, timeout=3, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def check_restart(port: int) -> Check:
    """Would restarting the service that runs Chrome also close Chrome?"""
    found = _chrome_proc(port)
    if found is None:
        return Check("Restart", "SKIP", "Chrome process not readable on this system")
    unit = _cgroup_unit(found[0])
    if unit is None:
        return Check("Restart", "PASS", "Chrome is not inside a systemd service, so a service restart leaves it running")
    mode = _kill_mode(unit)
    if mode == "process":
        return Check("Restart", "PASS", f"{unit} has KillMode=process, so a restart leaves Chrome running")
    return Check(
        "Restart", "WARN",
        f"Chrome runs inside {unit} (KillMode={mode or 'unknown'}); restarting it closes Chrome and your sign-ins",
        f"Add a drop-in, then reload:\n    sudo mkdir -p /etc/systemd/system/{unit}.d\n"
        f"    printf '[Service]\\nKillMode=process\\n' | sudo tee /etc/systemd/system/{unit}.d/keep-chrome.conf\n"
        "    sudo systemctl daemon-reload",
    )


def check_service(host: str, api_port: int, timeout: float) -> Check:
    status, _ = _get_json(f"http://{host}:{api_port}/ready", timeout)
    if status == 200:
        return Check("Service", "PASS", f"/ready is true on {host}:{api_port}")
    if status == 503:
        return Check(
            "Service", "FAIL", f"the service runs on {host}:{api_port} but is not connected to Chrome",
            "Check the Chrome debug port above, then restart the service so it reconnects.",
        )
    return Check(
        "Service", "WARN", f"nothing answers on {host}:{api_port}",
        "Only needed for REST and the dashboard (not for `bh mcp`). Start it with: python run.py",
    )


def check_token(token: str | None) -> Check:
    if not token:
        return Check("API_TOKEN", "WARN", "not set (fine on 127.0.0.1, required for 0.0.0.0)")
    if token.strip().lower() in PLACEHOLDER_TOKENS:
        return Check(
            "API_TOKEN", "FAIL", "set to a placeholder, so the service answers 401 to everything",
            "Set a long random value, or unset it for local use.",
        )
    return Check("API_TOKEN", "PASS", "set")


def run_checks(host: str, debug_port: int, api_port: int, timeout: float = 2.0) -> list[Check]:
    chrome, _ = check_chrome(host, debug_port, timeout)
    checks = [chrome]
    checks.append(check_profile(debug_port) if chrome.status == "PASS" else Check(
        "Chrome profile", "SKIP", "Chrome is not reachable"))
    checks.append(check_restart(debug_port) if chrome.status == "PASS" else Check(
        "Restart", "SKIP", "Chrome is not reachable"))
    checks.append(check_service(host, api_port, timeout))
    checks.append(check_token(os.environ.get("API_TOKEN")))
    return checks


@click.command(name="doctor", help="Check the Chrome connection and print the fix for each problem")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--debug-port", type=int, default=None, help="Chrome debug port (default: CHROME_AUTO_PORT or 9557)")
@click.option("--api-port", type=int, default=None, help="Service port (default: PORT or 8000)")
@click.option("--timeout", type=float, default=2.0, show_default=True)
def doctor(host: str, debug_port: int | None, api_port: int | None, timeout: float) -> None:
    debug_port = debug_port or int(os.environ.get("CHROME_AUTO_PORT") or 9557)
    api_port = api_port or int(os.environ.get("PORT") or 8000)
    failed = False
    for c in run_checks(host, debug_port, api_port, timeout):
        click.echo(f"{c.status:<5} {c.name}: {c.detail}")
        if c.fix:
            click.echo(f"      fix: {c.fix}")
        failed = failed or c.status == "FAIL"
    sys.exit(1 if failed else 0)
