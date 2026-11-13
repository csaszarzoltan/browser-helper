import asyncio
import os

import pytest

from mcp_server import vpn_lease


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(vpn_lease, "_STATE", tmp_path / "lease.json")


def _other_pid():
    return os.getppid()  # a live pid that is not ours


def test_same_country_shared():
    a = asyncio.run(vpn_lease.acquire("hu", wait=1, pid=os.getpid()))
    b = asyncio.run(vpn_lease.acquire("HU", wait=1, pid=_other_pid()))
    assert a["ok"] and b["ok"]


def test_other_country_waits_then_times_out():
    asyncio.run(vpn_lease.acquire("HU", wait=1, pid=_other_pid()))
    r = asyncio.run(vpn_lease.acquire("DE", wait=1.2, pid=os.getpid()))
    assert not r["ok"] and r["code"] == "vpn_busy" and r["holders"] == ["HU"]


def test_release_lets_waiter_in():
    asyncio.run(vpn_lease.acquire("HU", wait=1, pid=_other_pid()))

    async def go():
        t = asyncio.create_task(vpn_lease.acquire("DE", wait=10, pid=os.getpid()))
        await asyncio.sleep(0.5)
        vpn_lease.release(_other_pid())
        return await t

    assert asyncio.run(go())["ok"]


def test_dead_pid_pruned():
    with vpn_lease._Locked() as st:
        st["holders"]["99999999"] = {"country": "HU", "since": 0}
    assert asyncio.run(vpn_lease.acquire("DE", wait=1, pid=os.getpid()))["ok"]
