"""Unit tests for the orphan-headless reaper (_reap_orphan_headless)."""

import pytest
from unittest.mock import MagicMock, patch

from main import _reap_orphan_headless


class FakeHandle:
    def __init__(self, pid):
        self.chrome_pid = pid


class FakePool:
    def __init__(self, pids):
        self._handles = [FakeHandle(p) for p in pids]

    def all_sessions(self):
        return self._handles


def test_reaps_none_when_no_headless(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(stdout="", returncode=0),
    )
    assert _reap_orphan_headless() == 0


def test_reaps_orphans_not_in_pool(monkeypatch):
    # pgrep finds 3 headless PIDs; pool owns only 2222 → 1111, 3333 reaped.
    out = MagicMock(stdout="1111\n2222\n3333\n")
    kills = []

    def fake_run(cmd, **kw):
        if cmd[0] == "pgrep":
            return out
        kills.append(cmd[2])  # the PID argument of `kill -9 <pid>`
        return MagicMock(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    class FakeMgr:
        pool = FakePool([2222])

    monkeypatch.setattr("main.headless_mgr", FakeMgr())
    assert _reap_orphan_headless() == 2
    assert kills == ["1111", "3333"]  # the PIDs passed to kill -9


def test_keeps_live_session_pids(monkeypatch):
    out = MagicMock(stdout="5000\n5001\n")
    kills = []

    def fake_run(cmd, **kw):
        if cmd[0] == "pgrep":
            return out
        kills.append(cmd[1])
        return MagicMock(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    class FakeMgr:
        pool = FakePool([5000, 5001])

    monkeypatch.setattr("main.headless_mgr", FakeMgr())
    assert _reap_orphan_headless() == 0
    assert kills == []


def test_handles_pgrep_error(monkeypatch):
    def fake_run(cmd, **kw):
        raise FileNotFoundError("no pgrep")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert _reap_orphan_headless() == 0
