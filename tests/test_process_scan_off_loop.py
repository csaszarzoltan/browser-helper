"""A process scan must not hold up the event loop.

``ps`` reads /proc entries. When one of those processes is stuck in I/O the scan
waits, and a synchronous subprocess call on the loop thread stalls every request.
Observed 2026-10-12: the service answered nothing for about 19 minutes, while a
journalctl process sat in I/O wait.
"""

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_a_stuck_process_scan_does_not_stall_the_event_loop(monkeypatch):
    import chrome_manager

    def stuck_scan(profile_dir):
        time.sleep(1.0)  # stands in for a `ps` waiting on a process stuck in I/O

    monkeypatch.setattr(chrome_manager, "_find_chrome_with_profile", stuck_scan)
    monkeypatch.setattr(chrome_manager, "_PROCESS_SCAN_TIMEOUT_S", 0.4, raising=False)

    async def run():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        tick_task = asyncio.create_task(ticker())
        start = time.monotonic()
        try:
            await chrome_manager._find_chrome_with_profile_async("/profile")
        except TimeoutError:
            pass
        elapsed = time.monotonic() - start
        tick_task.cancel()
        return elapsed, ticks

    elapsed, ticks = asyncio.run(run())
    assert elapsed < 0.9, f"the scan held the loop for {elapsed:.2f}s"
    assert ticks >= 4, f"the loop ticked {ticks} times while the scan was stuck"


def test_a_synchronous_scan_on_the_loop_stalls_it_control(monkeypatch):
    # Control for the ticker above: the same stuck scan, called directly on the loop
    # thread (the old behaviour), must freeze the ticker. Otherwise the ticker proves nothing.
    import chrome_manager

    monkeypatch.setattr(chrome_manager, "_find_chrome_with_profile", lambda profile_dir: time.sleep(0.5))

    async def run():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        tick_task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        chrome_manager._find_chrome_with_profile("/profile")
        tick_task.cancel()
        return ticks

    assert asyncio.run(run()) <= 1


def test_a_timed_out_scan_raises_instead_of_reporting_no_browser(monkeypatch):
    # "no browser holds the profile" lets launch() clear the singleton lock. A scan
    # that never answered says nothing about that, so it must not return None.
    import chrome_manager

    monkeypatch.setattr(chrome_manager, "_find_chrome_with_profile", lambda profile_dir: time.sleep(1.0))
    monkeypatch.setattr(chrome_manager, "_PROCESS_SCAN_TIMEOUT_S", 0.1, raising=False)
    try:
        asyncio.run(chrome_manager._find_chrome_with_profile_async("/profile"))
    except TimeoutError:
        return
    raise AssertionError("a timed-out scan returned a result")


def test_a_scan_that_finishes_returns_its_result(monkeypatch):
    import chrome_manager

    monkeypatch.setattr(chrome_manager, "_find_chrome_with_profile", lambda profile_dir: 9557)
    assert asyncio.run(chrome_manager._find_chrome_with_profile_async("/profile")) == 9557
