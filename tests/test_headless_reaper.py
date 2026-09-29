"""Unit tests for the orphan-headless reaper (_reap_orphan_headless).

v1.36.8 update: the pre-v1.36.4 version of this file asserted the OLD contract
("kill every headless PID not in the pool").  That contract was the bug — the
scan matched the main browser and its renderer children too, killed them every
5 minutes, and destabilised the live Chrome until it exited, which is what
looked like a BH outage.

The current contract (see tests/test_orphan_reap_guard.py for the full
simulated process tree):
  * a candidate must be a top-level browser process — no ``--type=`` flag
  * it must be a TRUE orphan — ``ppid == 1``
  * it must not belong to a live headless session

These tests supply ``_chrome_proc_meta`` explicitly, so they exercise the
guards rather than whatever ``ps`` happens to return on the test host.
"""

from unittest.mock import MagicMock

import main as M
import subprocess
from main import _reap_orphan_headless


class FakeHandle:
    def __init__(self, pid):
        self.chrome_pid = pid


class FakePool:
    def __init__(self, pids):
        self._handles = [FakeHandle(p) for p in pids]

    def all_sessions(self):
        return self._handles


def _install(monkeypatch, pgrep_out, meta, main_out="", owned=()):
    """Wire subprocess.run + _chrome_proc_meta and return the kill recorder."""
    kills = []

    def fake_run(cmd, *a, **k):
        m = MagicMock(returncode=0, stdout="")
        s = str(cmd)
        if cmd[0] == "pgrep":
            if "remote-debugging-port=" in s and "chrome.*" not in s:
                m.stdout = main_out
            else:
                m.stdout = pgrep_out
        elif cmd[0] == "kill":
            kills.append(cmd[-1])
        return m

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(M, "_chrome_proc_meta", lambda pid: meta.get(str(pid), ("1", False)))

    class FakeMgr:
        pool = FakePool(list(owned))

    monkeypatch.setattr(M, "headless_mgr", FakeMgr())
    return kills


def test_reaps_none_when_no_headless(monkeypatch):
    _install(monkeypatch, pgrep_out="", meta={})
    assert _reap_orphan_headless() == 0


def test_reaps_orphans_not_in_pool(monkeypatch):
    """Two true orphans (ppid=1) die; the pooled one is untouched."""
    # 1111 and 3333 are orphans (ppid=1); 2222 is the same but pool-owned.
    meta = {
        "1111": ("1", False),
        "2222": ("1", False),
        "3333": ("1", False),
    }
    kills = _install(
        monkeypatch,
        pgrep_out="1111\n2222\n3333\n",
        meta=meta,
        main_out="5555\n",
        owned=[2222],
    )
    assert _reap_orphan_headless() == 2
    assert sorted(kills) == ["1111", "3333"]


def test_keeps_live_session_pids(monkeypatch):
    """A headless browser owned by a live session is never killed."""
    meta = {"5000": ("1", False), "5001": ("1", False)}
    kills = _install(
        monkeypatch,
        pgrep_out="5000\n5001\n",
        meta=meta,
        owned=[5000, 5001],
    )
    assert _reap_orphan_headless() == 0
    assert kills == []


def test_never_kills_renderer_children(monkeypatch):
    """A ``--type=`` child of a live zygote is off limits even if ppid==1."""
    meta = {
        "7001": ("1", True),   # orphan-looking, but a renderer/zygote child
        "7002": ("7000", False),  # parented to a live process
    }
    kills = _install(monkeypatch, pgrep_out="7001\n7002\n", meta=meta)
    assert _reap_orphan_headless() == 0
    assert kills == []


def test_handles_pgrep_error(monkeypatch):
    def fake_run(cmd, *a, **k):
        raise FileNotFoundError("no pgrep")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _reap_orphan_headless() == 0
