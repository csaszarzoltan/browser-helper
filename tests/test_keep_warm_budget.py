"""v1.36.6: the keep-warm cycle must verify the /session/new response.

Real defect found reviewing v1.36.5 (2026-09-28): the loop did

    await hx.post(f".../session/new", params={"url": warm_url})
    logger.info("Keep-warm session ensured at %s", warm_url)

``/session/new`` answers ``429 tab_budget_exhausted`` when ``BH_MAX_TABS`` is
spent.  That is a normal response, NOT an exception, so the bare ``except``
never fired and the loop logged a warm tab it never got — then quietly stopped
warming for the rest of the process lifetime.

The behaviour now lives in ``main._ensure_keep_warm_session``, which returns a
bool.  These tests call it directly.
"""

import logging

import pytest

import main as bh_main


class _Resp:
    def __init__(self, status_code, body="{}"):
        self.status_code = status_code
        self.text = body

    def json(self):
        import json

        try:
            return json.loads(self.text or "{}")
        except Exception:
            return {}


class _FakeAsyncClient:
    """httpx.AsyncClient stand-in returning a scripted response code."""

    code = 200
    posts: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        type(self).posts.append((url, kw.get("params")))
        return _Resp(type(self).code)


@pytest.fixture
def fake_http(monkeypatch):
    import httpx

    _FakeAsyncClient.posts = []
    _FakeAsyncClient.code = 200
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [200, 201, 204])
async def test_returns_true_on_2xx(fake_http, code):
    fake_http.code = code
    assert await bh_main._ensure_keep_warm_session("http://127.0.0.1:8080/") is True
    assert fake_http.posts, "must actually POST /session/new"
    url, params = fake_http.posts[0]
    assert url.endswith("/session/new")
    assert params == {"url": "http://127.0.0.1:8080/"}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 403, 404, 429, 500, 503])
async def test_returns_false_on_non_2xx(fake_http, code, caplog):
    """The regression: 429 tab_budget_exhausted must NOT report success."""
    fake_http.code = code
    with caplog.at_level(logging.INFO, logger="browser-helper"):
        result = await bh_main._ensure_keep_warm_session("http://127.0.0.1:8080/")
    assert result is False
    assert fake_http.posts, "must still have attempted the warm-up"
    assert not any(
        "ensured" in r.getMessage().lower() for r in caplog.records
    ), f"HTTP {code} was logged as a successful warm-up: {caplog.text}"


@pytest.mark.asyncio
async def test_returns_false_on_transport_error(monkeypatch):
    """A connection error is best-effort, never an exception that kills the loop."""

    class _Boom:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise OSError("connection refused")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    assert await bh_main._ensure_keep_warm_session("http://127.0.0.1:8080/") is False


@pytest.mark.asyncio
async def test_refusal_is_recoverable(fake_http):
    """429 then 200 — the loop recovers, proving a refusal isn't terminal."""
    fake_http.code = 429
    assert await bh_main._ensure_keep_warm_session("u") is False
    fake_http.code = 200
    assert await bh_main._ensure_keep_warm_session("u") is True
    assert len(fake_http.posts) == 2


@pytest.mark.asyncio
async def test_uses_configured_bh_port(monkeypatch, fake_http):
    """The helper must honour BH_PORT like the old inline code did."""
    monkeypatch.setenv("BH_PORT", "9999")
    fake_http.code = 200
    await bh_main._ensure_keep_warm_session("http://x/")
    url, _ = fake_http.posts[0]
    assert "127.0.0.1:9999" in url


# ── the warm tab must never eat a client's slot ────────────────────────────

@pytest.mark.asyncio
async def test_skips_when_budget_full(monkeypatch, fake_http, caplog):
    """If clients already hold every slot, keep-warm must not take one."""
    monkeypatch.setattr(bh_main.session_registry, "_tab_budget", 3, raising=False)
    monkeypatch.setattr(bh_main.session_registry, "tabs_in_use", lambda: 3, raising=False)
    with caplog.at_level(logging.INFO, logger="browser-helper"):
        result = await bh_main._ensure_keep_warm_session("http://x/")
    assert result is False
    assert not fake_http.posts, "must not POST /session/new with a full budget"


@pytest.mark.asyncio
async def test_skips_when_one_slot_left_but_clients_need_it(monkeypatch, fake_http):
    """3/3 used => skip.  2/3 used => the warm tab may take the free slot."""
    monkeypatch.setattr(bh_main.session_registry, "_tab_budget", 3, raising=False)

    monkeypatch.setattr(bh_main.session_registry, "tabs_in_use", lambda: 3, raising=False)
    assert await bh_main._ensure_keep_warm_session("http://x/") is False
    assert not fake_http.posts

    monkeypatch.setattr(bh_main.session_registry, "tabs_in_use", lambda: 2, raising=False)
    fake_http.code = 200
    assert await bh_main._ensure_keep_warm_session("http://x/") is True
    assert len(fake_http.posts) == 1


@pytest.mark.asyncio
async def test_unlimited_budget_never_blocks_keep_warm(monkeypatch, fake_http):
    """BH_MAX_TABS=0 (off) must not gate the warm tab at all."""
    monkeypatch.setattr(bh_main.session_registry, "_tab_budget", 0, raising=False)
    monkeypatch.setattr(bh_main.session_registry, "tabs_in_use", lambda: 99, raising=False)
    fake_http.code = 200
    assert await bh_main._ensure_keep_warm_session("http://x/") is True
    assert len(fake_http.posts) == 1
