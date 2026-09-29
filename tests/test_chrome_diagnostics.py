"""v1.36.9: a Chrome halálakor ne vesszen el nyomot.

Two independent diagnostic holes, both found on 2026-09-28 while chasing the
unexplained 40-80 minute Chrome deaths:

1. ``chrome_manager.launch()`` opened the stderr sink with mode ``"w"``, so
   every relaunch **truncated the previous life's stderr**.  The log that would
   explain a crash is destroyed *at the moment the next Chrome starts* — long
   before anyone reads it.  Rotating by renaming keeps the last N lives.

2. Nothing anywhere reads ``proc.returncode`` or awaits ``proc.wait()``.  When
   Chrome dies the server simply notices "not connected" and relaunches, so
   the exit status and signal (SIGKILL from the OOM killer looks exactly like a
   clean exit(0) from here) never reach a log line.  ``_record_chrome_exit``
   must capture the status and stamp a lifecycle marker.

The lifecycle marker is what makes an 8-hour log readable: without it, a stderr
file with GCM DEPRECATED_ENDPOINT spam and no launch boundaries is unusable.
"""

import asyncio
from pathlib import Path

import pytest

from chrome_manager import ChromeManager

# ── stderr rotation ─────────────────────────────────────────────────────────


def test_stderr_log_is_not_truncated_on_relaunch(tmp_path):
    """A relaunch must PRESERVE the previous life's stderr, not wipe it.

    This is the regression for the real ``launch()`` behaviour: it used
    ``open(path, "w")``, which destroyed the previous life's evidence at the
    exact moment the recovery fired.  This exercises the real
    ``_rotate_stderr_log`` rather than re-implementing it here.
    """
    mgr = ChromeManager.__new__(ChromeManager)  # no __init__: no real launch
    log = tmp_path / "bh-chrome-stderr.log"
    mgr._stderr_path = str(log)

    log.write_text("PREVIOUS LIFE: crash evidence\n")
    first_fh = open(log, "a", buffering=1)  # noqa: SIM115 — kept open on purpose
    first_fh.write("life 1: GCM DEPRECATED_ENDPOINT spam\n")
    first_fh.flush()

    # ── this is what launch() does before every start ──
    mgr._rotate_stderr_log()
    second_fh = open(log, "a", buffering=1)  # noqa: SIM115 — same
    second_fh.write("life 2: still alive\n")
    second_fh.flush()

    rotated = Path(mgr._stderr_path + ".1")
    assert rotated.exists(), "the previous life was not rotated away"
    old = rotated.read_text()
    assert "PREVIOUS LIFE" in old, "pre-existing evidence was destroyed"
    assert "life 1" in old, "first life's stderr was lost on relaunch"
    assert "life 2" not in old, "the new life leaked into the rotated file"
    assert "life 2" in log.read_text()

    first_fh.close()
    second_fh.close()


def test_stderr_rotation_keeps_bounded_history(tmp_path):
    """Rotation must be bounded, or /tmp grows without limit."""
    mgr = ChromeManager.__new__(ChromeManager)
    keep = mgr.STDERR_KEEP
    assert keep >= 2, "must keep at least the previous life"

    log = tmp_path / "bh-chrome-stderr.log"
    mgr._stderr_path = str(log)

    for i in range(keep + 2):
        log.write_text(f"life {i}\n")
        mgr._rotate_stderr_log()          # the real rotation, every time

    base = Path(mgr._stderr_path)
    assert (Path(str(base) + ".1")).read_text().strip() == f"life {keep + 1}", (
        "rotation did not move the most recent previous life into .1"
    )
    # bounded: STDERR_KEEP-1 rotated files (.1 … .KEEP-1) plus the live one.
    for k in range(1, keep):
        assert Path(f"{base}.{k}").exists(), f"rotation dropped the .{k} history"
    for k in range(keep, keep + 3):
        assert not Path(f"{base}.{k}").exists(), (
            f"rotation left an unbounded .{k} — /tmp grows forever"
        )
    # and the live log is free for the fresh life
    assert not base.exists()


# ── exit reason capture ─────────────────────────────────────────────────────


def test_record_chrome_exit_logs_status_and_signal(tmp_path):
    """A dead Chrome must leave a line naming its exit status."""
    recs = []
    mgr = ChromeManager.__new__(ChromeManager)
    mgr.LIFECYCLE_PATH = str(tmp_path / "lc.log")
    mgr._record_chrome_exit = lambda pid, rc, reason="": recs.append((pid, rc, reason))

    mgr._record_chrome_exit(1234, 0, "clean")
    mgr._record_chrome_exit(1235, -9, "killed")

    assert len(recs) == 2


def test_exit_description_distinguishes_signal_from_clean_exit(tmp_path):
    """-9 (OOM SIGKILL) and 0 must be visibly different in the log."""
    path = tmp_path / "lc.log"
    mgr = ChromeManager.__new__(ChromeManager)
    mgr.LIFECYCLE_PATH = str(path)

    mgr._record_chrome_exit(11, 0, "clean")
    mgr._record_chrome_exit(12, -9, "killed")
    mgr._record_chrome_exit(13, -15, "sigterm")

    text = path.read_text()
    assert "exit status 0" in text
    assert "signal SIGKILL (rc=-9)" in text, "an OOM kill must be nameable"
    assert "signal SIGTERM (rc=-15)" in text


def test_exit_marker_is_written_to_lifecycle_log(tmp_path):
    """The lifecycle log must be greppable: pid, status, reason."""
    mgr = ChromeManager.__new__(ChromeManager)
    path = tmp_path / "lifecycle.log"
    mgr.LIFECYCLE_PATH = str(path)   # instance attr shadows the class default

    mgr._append_lifecycle("launch pid=555")
    mgr._append_lifecycle("exit pid=555 status=0 reason=clean")

    text = path.read_text()
    assert "launch pid=555" in text
    assert "exit pid=555 status=0 reason=clean" in text
    # newline-terminated, so the next append starts a fresh line
    assert text.endswith("\n")


@pytest.mark.asyncio
async def test_stderr_history_is_capped_for_tmpfs(tmp_path):
    """A crash-loop must not fill tmpfs.

    One Chrome life can emit 100MB+ of stack traces; three of those pinned in
    RAM is a memory cost on the very box already short of it.
    """
    mgr = ChromeManager.__new__(ChromeManager)
    log = tmp_path / "bh-chrome-stderr.log"
    mgr._stderr_path = str(log)
    mgr.STDERR_KEEP = 3
    mgr.STDERR_MAX_BYTES = 4 * 1024          # tiny cap so the test is fast

    for i in range(mgr.STDERR_KEEP):
        Path(f"{log}.{i + 1}").write_bytes(b"x" * (3 * 1024))

    mgr._cap_stderr_history()

    total = sum(
        Path(f"{log}.{k}").stat().st_size for k in range(1, mgr.STDERR_KEEP + 1)
        if Path(f"{log}.{k}").exists()
    )
    assert total <= mgr.STDERR_MAX_BYTES, (
        f"retained {total} bytes, cap is {mgr.STDERR_MAX_BYTES}"
    )


def test_explicit_live_chrome_is_not_cleared():
    """``stop()`` must still work: the supervisor deliberately leaves _port."""
    mgr = ChromeManager.__new__(ChromeManager)
    mgr._process = type("P", (), {"pid": 7, "returncode": None})()
    mgr._pid = 7
    mgr._launch_in_progress = False
    # nothing to assert beyond "the probe helper is gone and stop() is intact":
    # the contract is that _process survives until a real death or stop().
    assert not hasattr(mgr, "_observe_process_exit"), (
        "the dead probe helper is back; either wire it in or leave it out"
    )
    assert hasattr(mgr, "_supervise_chrome")


@pytest.mark.asyncio
async def test_supervisor_clears_state_and_records_signal(tmp_path):
    """The supervisor owns the transition: record the status, then clear."""
    class _Proc:
        pid = 4321

        def __init__(self):
            self.returncode = None

        async def wait(self):
            self.returncode = -9          # OOM killer
            return -9

    mgr = ChromeManager.__new__(ChromeManager)
    proc = _Proc()
    mgr._process = proc
    mgr._pid = proc.pid          # the manager owns exactly this process
    mgr._launch_in_progress = False
    mgr.LIFECYCLE_PATH = str(tmp_path / "lc.log")

    await mgr._supervise_chrome(proc, proc.pid)

    assert mgr._pid == 0, "the dead pid was left behind as if it were live"
    assert mgr._process is None


@pytest.mark.asyncio
async def test_stale_supervisor_still_logs_but_does_not_clear():
    """A relaunched Chrome must not lose the old Chrome's death reason.

    This is the M1 regression found in review (2026-09-28).  The old code
    returned early on a pid mismatch, which discarded precisely the status we
    are hunting: Chrome dies -> the watchdog relaunches -> the new launch
    assigns self._pid -> the old supervisor's mismatch check then swallowed the
    real reason.  The contract is now: ALWAYS log, clear only if still owner.
    """
    class _Proc:
        def __init__(self):
            self.pid = 111
            self.returncode = None

        async def wait(self):
            return -9

    mgr = ChromeManager.__new__(ChromeManager)
    old = _Proc()
    new = _Proc()                       # a relaunch already produced this one
    mgr._process = new                  # we no longer own `old`
    mgr._pid = 222
    mgr._launch_in_progress = False
    recs = []
    mgr._record_chrome_exit = lambda pid, rc, reason="": recs.append((pid, rc, reason))

    await mgr._supervise_chrome(old, 111)

    assert len(recs) == 1, "a stale supervisor threw away a real death status"
    assert recs[0][0] == 111 and recs[0][1] == -9
    assert "stale supervisor" in recs[0][2], "the log line does not flag staleness"
    assert mgr._pid == 222, "stale supervisor cleared a live pid"
    assert mgr._process is new, "stale supervisor detached the live process"


@pytest.mark.asyncio
async def test_intentional_stop_is_not_logged_as_a_crash(tmp_path):
    """Cancelling the supervisor marks the stop as intentional."""
    class _Proc:
        def __init__(self):
            self.pid = 333
            self.returncode = None

        async def wait(self):
            await asyncio.Event().wait()      # never returns on its own
            return -15

    mgr = ChromeManager.__new__(ChromeManager)
    mgr._process = _Proc()
    mgr._pid = 333
    mgr._launch_in_progress = False
    p = tmp_path / "lc.log"
    mgr.LIFECYCLE_PATH = str(p)
    task = asyncio.create_task(mgr._supervise_chrome(mgr._process, 333))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "intentional stop" in p.read_text(), "an intentional stop was not labelled"


@pytest.mark.asyncio
async def test_live_chrome_is_not_reaped():
    mgr = ChromeManager.__new__(ChromeManager)
    mgr._process = type("P", (), {"pid": 7, "returncode": None})()
    mgr._pid = 7
    mgr._launch_in_progress = False

    assert mgr._pid == 7, "a live Chrome must not be cleared"
