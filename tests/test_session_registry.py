"""Unit tests for the per-client SessionRegistry (tab isolation)."""

import asyncio
import pytest

from session_registry import SessionRegistry


class FakeClient:
    """Minimal stand-in for CDPClient used by the registry."""

    _counter = 0

    def __init__(self, cdp_http_url: str = "http://127.0.0.1:9557"):
        self.cdp_http_url = cdp_http_url
        self.closed = False
        self.tab_closed = False

    async def open_new_tab(self, url: str = "about:blank") -> dict:
        FakeClient._counter += 1
        return {"status": "ok", "tab_id": f"tab-{FakeClient._counter}", "url": url, "title": ""}

    async def connect_to_target(self, tab_id: str) -> dict:
        return {"status": "ok", "target_id": tab_id, "cdp_url": "ws://fake"}

    async def _open_tab_http(self, client, url: str) -> str:
        FakeClient._counter += 1
        return f"tab-{FakeClient._counter}"

    async def close_tab(self, tab_id: str) -> dict:
        self.tab_closed = True
        return {"status": "ok", "tab_id": tab_id}

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def registry(monkeypatch):
    reg = SessionRegistry(ttl=0.05)
    monkeypatch.setattr("session_registry.CDPClient", FakeClient)

    async def fake_open_tab(client, url="about:blank"):
        FakeClient._counter += 1
        return f"tab-{FakeClient._counter}"

    monkeypatch.setattr(reg, "_open_tab_http", fake_open_tab)
    return reg


@pytest.mark.asyncio
async def test_create_mints_session_with_tab(registry):
    sess = await registry.create("http://127.0.0.1:9557")
    assert sess.session_id
    assert sess.tab_id.startswith("tab-")
    assert registry.get(sess.session_id) is sess
    assert registry.count == 1


@pytest.mark.asyncio
async def test_get_unknown_returns_none(registry):
    assert registry.get("nope") is None


@pytest.mark.asyncio
async def test_two_sessions_are_isolated(registry):
    a = await registry.create("http://127.0.0.1:9557")
    b = await registry.create("http://127.0.0.1:9557")
    assert a.session_id != b.session_id
    assert a.tab_id != b.tab_id
    assert registry.count == 2
    assert registry.get(a.session_id) is a
    assert registry.get(b.session_id) is b


@pytest.mark.asyncio
async def test_destroy_closes_tab_and_removes(registry):
    sess = await registry.create("http://127.0.0.1:9557")
    assert await registry.destroy(sess.session_id) is True
    assert registry.get(sess.session_id) is None
    assert sess.client.closed is True
    assert sess.client.tab_closed is True
    assert await registry.destroy(sess.session_id) is False  # idempotent


@pytest.mark.asyncio
async def test_cleanup_reaps_idle_sessions(registry):
    reg = registry
    reg._ttl = 0.2
    a = await reg.create("http://127.0.0.1:9557")
    b = await reg.create("http://127.0.0.1:9557")
    # Age b artificially so it exceeds the TTL; touch a to keep it fresh.
    b.last_seen -= 1.0
    reg.get(a.session_id)  # touch → fresh
    reaped = await reg.cleanup()
    assert reaped == 1
    assert reg.get(a.session_id) is a
    assert reg.get(b.session_id) is None


@pytest.mark.asyncio
async def test_close_all_destroys_everything(registry):
    await registry.create("http://127.0.0.1:9557")
    await registry.create("http://127.0.0.1:9557")
    await registry.close_all()
    assert registry.count == 0


@pytest.mark.asyncio
async def test_reaper_loop_reaps(registry):
    await registry.create("http://127.0.0.1:9557")
    registry.start_reaper()
    await asyncio.sleep(0.2)  # reaper interval = min(ttl, 60) = 0.05
    assert registry.count == 0
