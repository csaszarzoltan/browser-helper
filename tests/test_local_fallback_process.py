"""The local headless fallback must not leave a Chrome running that nothing can stop.

Found 2026-10-13: _launch_local_headless started Chrome, kept no handle to it, and piped its
stderr without reading it (a full pipe blocks Chrome). Nothing could terminate the process.
The fallback now keeps the process, and close_local_session stops it. The browser itself is
replaced by a fake process: this test must not start Chrome (see tests/conftest.py).
"""

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(autouse=True)
def _no_real_signals(monkeypatch):
    """Record the signals sent to process groups instead of sending them: the fake pid is not ours."""
    sent = []
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: sent.append((pgid, sig)))
    return sent


class _FakeProcess:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None
        self.terminated = False

    async def wait(self):
        return 0

    def terminate(self):
        self.terminated = True
        self.returncode = 0


class _FakeWhich:
    async def wait(self):
        return 0


def test_the_local_fallback_chrome_is_stopped_when_it_is_closed(monkeypatch, _no_real_signals):
    from browser_providers import session_pool

    launched = []

    async def fake_exec(*cmd, **kwargs):
        if cmd[0] == "which":
            return _FakeWhich()
        process = _FakeProcess(4242)
        launched.append((process, kwargs))
        return process

    async def devtools_at(port, timeout=15.0):
        return f"ws://127.0.0.1:{port}/devtools/browser/abc"

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(session_pool, "_wait_for_devtools", devtools_at)

    async def scenario():
        chain = session_pool.FallbackChain(providers=[])
        session = await chain._launch_local_headless(None)
        closed = await chain.close_local_session(session.session_id)
        again = await chain.close_local_session(session.session_id)
        return session, closed, again

    session, closed, again = asyncio.run(scenario())
    process, kwargs = launched[0]
    assert session.session_id == "local-4242"
    assert kwargs["stderr"] == asyncio.subprocess.DEVNULL, "a stderr pipe nobody reads blocks Chrome"
    assert closed is True and (process.pid, signal.SIGTERM) in _no_real_signals
    assert again is False


def _fake_chrome(monkeypatch, launched):
    async def fake_exec(*cmd, **kwargs):
        if cmd[0] == "which":
            return _FakeWhich()
        process = _FakeProcess(4242)
        process.kwargs = kwargs
        launched.append((process, cmd))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


def test_the_session_points_at_the_devtools_socket_of_the_chrome_it_started(monkeypatch):
    from browser_providers import session_pool

    launched, asked = [], []

    async def devtools_at(port, timeout=15.0):
        asked.append(port)
        return f"ws://127.0.0.1:{port}/devtools/browser/abc"

    _fake_chrome(monkeypatch, launched)
    monkeypatch.setattr(session_pool, "_wait_for_devtools", devtools_at)

    async def scenario():
        chain = session_pool.FallbackChain(providers=[])
        return await chain._launch_local_headless("probe")

    session = asyncio.run(scenario())
    _, cmd = launched[0]
    port = asked[0]
    assert f"--remote-debugging-port={port}" in cmd, "Chrome must listen on the port the session names"
    assert session.cdp_url == f"ws://127.0.0.1:{port}/devtools/browser/abc"


def test_without_a_profile_chrome_gets_a_profile_of_its_own_that_is_removed_on_close(monkeypatch):
    from browser_providers import session_pool

    launched = []

    async def devtools_at(port, timeout=15.0):
        return f"ws://127.0.0.1:{port}/devtools/browser/abc"

    _fake_chrome(monkeypatch, launched)
    monkeypatch.setattr(session_pool, "_wait_for_devtools", devtools_at)

    async def scenario():
        chain = session_pool.FallbackChain(providers=[])
        session = await chain._launch_local_headless(None)
        user_dir = next(a.split("=", 1)[1] for a in launched[0][1] if a.startswith("--user-data-dir="))
        existed = os.path.isdir(user_dir)
        await chain.close_local_session(session.session_id)
        return user_dir, existed

    user_dir, existed = asyncio.run(scenario())
    assert ".config/google-chrome" not in user_dir, "without a profile Chrome must not take the person's profile"
    assert existed is True
    assert not os.path.isdir(user_dir)


def test_closing_signals_the_whole_chrome_group_so_no_helper_writes_into_the_profile(monkeypatch, _no_real_signals):
    """Chrome's helper processes write into the profile while it shuts down; they must die with the browser."""
    from browser_providers import session_pool

    launched = []

    async def devtools_at(port, timeout=15.0):
        return f"ws://127.0.0.1:{port}/devtools/browser/abc"

    _fake_chrome(monkeypatch, launched)
    monkeypatch.setattr(session_pool, "_wait_for_devtools", devtools_at)

    async def scenario():
        chain = session_pool.FallbackChain(providers=[])
        session = await chain._launch_local_headless(None)
        await chain.close_local_session(session.session_id)

    asyncio.run(scenario())
    process, _ = launched[0]
    assert process.kwargs["start_new_session"] is True, "Chrome must lead its own process group"
    assert (process.pid, signal.SIGTERM) in _no_real_signals
    assert (process.pid, signal.SIGKILL) in _no_real_signals, "stragglers of the group are killed before the profile is removed"


def test_a_chrome_that_never_opens_devtools_is_stopped_and_the_launch_fails(monkeypatch, _no_real_signals):
    from browser_providers import session_pool

    launched = []

    async def never(port, timeout=15.0):
        raise RuntimeError("no devtools")

    _fake_chrome(monkeypatch, launched)
    monkeypatch.setattr(session_pool, "_wait_for_devtools", never)

    async def scenario():
        chain = session_pool.FallbackChain(providers=[])
        try:
            await chain._launch_local_headless(None)
        except RuntimeError as exc:
            return str(exc), dict(chain._local_processes)
        return None, dict(chain._local_processes)

    message, tracked = asyncio.run(scenario())
    user_dir = next(a.split("=", 1)[1] for a in launched[0][1] if a.startswith("--user-data-dir="))
    assert message == "no devtools"
    assert (launched[0][0].pid, signal.SIGTERM) in _no_real_signals
    assert tracked == {}
    assert not os.path.isdir(user_dir)
