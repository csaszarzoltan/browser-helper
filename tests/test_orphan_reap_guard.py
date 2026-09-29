"""v1.36.4: the orphan-Chrome reaper must never kill a live browser's children.

Root cause of the ~40-minute Chrome deaths (observed 2026-09-24): the
watchdog's ``_reap_orphan_headless()`` scan pattern also matched the MAIN
browser and its renderer children.  It killed 6-12 PIDs every 5 minutes;
killing a live browser's renderers destabilises it until the whole browser
exits — then the watchdog relaunches, sessions die, and every call 400/503s
for minutes.  That is what looked like "BH keeps stopping" while the
service itself never restarted (NRestarts=0).

New contract: only orphan TOP-level browser processes may be killed —
never a ``--type=`` child, and never anything parented to a live process
(``ppid == 1`` required).
"""
import subprocess
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, "src")
sys.path.insert(0, ".")

import main as M  # noqa: E402

# Simulated pgrep output: main browser (parented to the BH service), two
# renderers (parented to a zygote), one TRUE orphan (ppid=1) from a previous
# run, one live headless session browser.
_PGREP_ALL = (
    "100 BROWSER --remote-debugging-port=9557\n"
    "101 RENDERER --type=renderer x\n"
    "102 RENDERER --type=renderer y\n"
    "103 ORPHAN --headless=new\n"
    "104 HEADLESS --headless=new\n"
)
_PGREP_MAIN = "100 BROWSER --remote-debugging-port=9557\n"
_META = {
    "100": ("477829", False),  # main browser, child of the BH service
    "101": ("200", True),      # renderer child
    "102": ("200", True),      # renderer child
    "103": ("1", False),       # TRUE orphan — the only killable one
    "104": ("1", False),       # orphan-looking but owned by a live session
}


def _run_reap(monkeypatch):
    killed = []

    def fake_run(cmd, *a, **k):
        m = MagicMock()
        # Order matters: the broad scan and the main-port scan BOTH contain
        # "remote-debugging-port=", so the port-specific pattern must be
        # tested first.  Matching the wrong one returned the full process
        # list for the main-port scan, which made every pid look "owned" and
        # the reaper a no-op — a failure that hid behind a plausible mock.
        pattern = cmd[2] if len(cmd) > 2 else ""
        if cmd[0] == "pgrep" and "headless" not in pattern:
            m.stdout = _PGREP_MAIN
        elif cmd[0] == "pgrep":
            m.stdout = _PGREP_ALL
        elif cmd[0] == "kill":
            killed.append(cmd[-1])
            m.stdout = ""
        else:
            m.stdout = ""
        return m

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(M, "_chrome_proc_meta", lambda pid: _META[pid])
    monkeypatch.setattr(
        M.headless_mgr.pool, "all_sessions",
        lambda: [MagicMock(chrome_pid=104)],
    )
    return M._reap_orphan_headless(), killed


def test_reaper_kills_only_true_orphan_browser(monkeypatch):
    """Only PID 103 (ppid=1, no --type=, not a live session) may die."""
    n, killed = _run_reap(monkeypatch)
    assert killed == ["103"]
    assert n == 1


def test_reaper_never_kills_live_browser_children(monkeypatch):
    """Main browser + renderers survive even when not in main_pids/live."""
    killed = []

    def fake_run(cmd, *a, **k):
        m = MagicMock()
        pattern = cmd[2] if len(cmd) > 2 else ""
        if cmd[0] == "pgrep" and "headless" not in pattern:
            m.stdout = ""  # main-port scan finds nothing (worst case)
        elif cmd[0] == "pgrep":
            m.stdout = _PGREP_ALL
        elif cmd[0] == "kill":
            killed.append(cmd[-1])
            m.stdout = ""
        else:
            m.stdout = ""
        return m

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(M, "_chrome_proc_meta", lambda pid: _META[pid])
    # The main-port scan finds NOTHING (worst case) — only the new guards
    # stand between the reaper and the live browser.  The live headless
    # session (104) stays in the pool so it remains owned.
    monkeypatch.setattr(
        M.headless_mgr.pool, "all_sessions",
        lambda: [MagicMock(chrome_pid=104)],
    )
    n, _ = M._reap_orphan_headless(), killed
    assert "100" not in killed  # main browser survives on ppid guard alone
    assert "101" not in killed  # renderer survives on --type= guard
    assert "102" not in killed
    assert killed == ["103"]
    assert n == 1
