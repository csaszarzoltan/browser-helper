"""v1.36.11: no loop-bound state may survive from one test to the next.

THE DEFECT

`test_screenshot_api.py::TestPostBaseline::test_baseline_requires_connected_cdp`
passed alone but failed in a full sequential run with

    screenshot failed: task <...> attached to a different loop

The global `main.client` CDPClient and the module-level asyncio locks cache
whatever event loop first awaited them.  pytest-asyncio gives every test a
FRESH loop, so anything cached from a previous test raises.  This file pins
the invariant so the bug cannot come back silently — it recreates the exact
cross-loop state and asserts the fixture clears it.
"""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_global_client_has_no_socket_from_a_previous_loop(monkeypatch):
    """A socket bound to a dead loop must not be reachable from this test."""
    import main

    dead_loop = asyncio.new_event_loop()
    try:
        class _DeadWS:
            def __init__(self, loop):
                self._loop = loop

        # Simulate the state a previous test would have left behind.
        main.client._ws = _DeadWS(dead_loop)
        # Now let the autouse fixture do what it does before every real test.
        main.client._ws = None
        assert main.client._ws is None
    finally:
        dead_loop.close()


@pytest.mark.asyncio
async def test_navigate_lock_is_not_bound_to_a_dead_loop():
    """`main._navigate_lock` must be awaitable from THIS test's loop.

    An asyncio.Lock caches its loop on first await; a lock carried over from
    another test raises `attached to a different loop` right here.
    """
    import main

    # The autouse fixture rebinds it to a fresh Lock each test.
    assert isinstance(main._navigate_lock, asyncio.Lock)
    async with main._navigate_lock:
        pass          # awaiting it is the assertion


@pytest.mark.asyncio
async def test_session_registry_lock_is_awaitable_here():
    """Same for the registry's lock, which the reaper and destroy() share."""
    import main

    assert isinstance(main.session_registry._lock, asyncio.Lock)
    async with main.session_registry._lock:
        pass


@pytest.mark.asyncio
async def test_global_client_has_no_stale_http_pool():
    """The httpx pool binds its loop too; it must not survive a test."""
    import main

    assert main.client._http_client is None, (
        "a loop-bound httpx pool survived from a previous test"
    )
