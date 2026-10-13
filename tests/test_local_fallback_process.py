"""The local headless fallback must not leave a Chrome running that nothing can stop.

Found 2026-10-13: _launch_local_headless started Chrome, kept no handle to it, and piped its
stderr without reading it (a full pipe blocks Chrome). Nothing could terminate the process.
The fallback now keeps the process, and close_local_session stops it. The browser itself is
replaced by a fake process: this test must not start Chrome (see tests/conftest.py).
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


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


def test_the_local_fallback_chrome_is_stopped_when_it_is_closed(monkeypatch):
    from browser_providers import session_pool

    launched = []

    async def fake_exec(*cmd, **kwargs):
        if cmd[0] == "which":
            return _FakeWhich()
        process = _FakeProcess(4242)
        launched.append((process, kwargs))
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

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
    assert closed is True and process.terminated is True
    assert again is False
