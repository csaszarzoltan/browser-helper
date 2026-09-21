"""v1.36 API-contract guards: unique OpenAPI operationIds + session reuse.

Two server-level bugs from the field report are pinned here:

1. **Duplicate OpenAPI operationIds.**  A route registered for several methods
   emits one operation per method but FastAPI derives a single ``unique_id``
   per ROUTE, so the emitted document carried duplicate ``operationId`` values
   (observed: 11 duplicates, 13 emitter warnings) — an invalid spec that breaks
   client generators.  ``_split_multimethod_routes`` divides such routes into
   one single-method APIRoute each.

2. **``/session/new`` tab explosion.**  The endpoint used to mint a brand-new
   session + Chrome tab on EVERY call, so an agent that called it per request
   opened one tab per request (observed in the field: 18 calls → 18 tabs → the
   30-session LRU cap evicted live tabs and broke ``switch_tab``).  It is now
   idempotent: an existing valid session is reused (``reused: true``) and a
   fast-repeat caller gets an in-band ``warnings`` entry naming the fix.

3. **Auto-mint tab-leak (v1.36.1).**  The 1.32 ``X-Session-Auto`` /
   ``BH_SESSION_AUTO=1`` fallback re-opened the leak one level down: every
   header-less ``/eval`` / ``/navigate`` minted a fresh session + tab
   (observed: 1 agent page → 9 about:blank tabs).  ``BH_STRICT_SESSIONS=1``
   kills the auto-mint — header-less browser ops get 400, new tabs only via
   explicit ``POST /session/new``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import main  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


# ─── 1. OpenAPI operationId uniqueness ───


def test_openapi_has_no_duplicate_operation_ids():
    """Every generated operation must carry a unique operationId."""
    spec = main.app.openapi()
    ids = [
        op["operationId"]
        for ops in spec["paths"].values()
        for op in ops.values()
        if isinstance(op, dict) and op.get("operationId")
    ]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate operationIds in the OpenAPI document: {sorted(dupes)}"


def test_openapi_emits_no_duplicate_id_warnings():
    """The spec generator itself must stay silent about duplicate ids."""
    import importlib
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(main)
        main.app.openapi()
    dupes = [str(w.message) for w in caught if "Duplicate Operation ID" in str(w.message)]
    assert not dupes, f"spec emitter still warns about duplicates: {dupes}"


def test_multimethod_route_is_split_per_method():
    """No single APIRoute may carry more than one real method.

    Guards the mechanism, not just the symptom: without the split FastAPI
    reuses one unique_id for every operation of that route.  Checked per
    ROUTE, not per path — several single-method routes may legitimately share
    a path (that is exactly what the split produces).
    """
    offenders = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            real = {m for m in route.methods if m != "HEAD"}
            if len(real) > 1:
                offenders.append((route.path, sorted(real)))
    assert not offenders, (
        f"routes still carrying several methods (their operations would share "
        f"one operationId): {offenders}"
    )


def test_dualmethod_endpoint_still_serves_both_methods():
    """The split must not change routing: GET and POST both still work."""
    for method in ("get", "post"):
        resp = getattr(client, method)("/page/text")
        assert resp.status_code not in (404, 405), (
            f"{method.upper()} /page/text broke after the route split: "
            f"HTTP {resp.status_code}"
        )


# ─── 3. /agent/act navigate accepts target.url as an alias ───


def test_act_navigate_accepts_target_url_alias(monkeypatch):
    """``{"action": "navigate", "target": {"url": ...}}`` must navigate.

    Regression guard for the field report: agents kept sending the URL inside
    ``target``, but the strict AgentTarget model silently dropped the extra
    key and the call failed with a bare ``url is required``.  Top-level
    ``url`` stays canonical; ``target.url`` is a tolerant alias.
    """
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient as _TC

    monkeypatch.setattr(type(main.client), "is_connected",
                        property(lambda self: True))
    main.client.navigate = AsyncMock(
        return_value={"status": "ok", "url": "https://example.test/"})
    api = _TC(main.app)

    resp = api.post("/agent/act", json={
        "action": "navigate",
        "target": {"url": "https://example.test/"},
        "observe_after": False,
    })
    assert resp.status_code == 200, resp.text
    main.client.navigate.assert_awaited_once_with("https://example.test/")


def test_act_navigate_without_any_url_names_the_fix(monkeypatch):
    """No url anywhere ⇒ the 422 names the exact payload shape to send."""
    from fastapi.testclient import TestClient as _TC

    monkeypatch.setattr(type(main.client), "is_connected",
                        property(lambda self: True))
    api = _TC(main.app)

    resp = api.post("/agent/act", json={
        "action": "navigate",
        "observe_after": False,
    })
    body = resp.json()
    blob = __import__("json").dumps(body)
    assert "top-level url" in blob or '"url": "https://' in blob, (
        f"navigate without url does not show the fix: {blob[:300]}"
    )


# ─── 2. /session/new idempotency + tab-spam detector ───


# ─── 3. P2 convenience: artifact URL for screenshots + network URL filter ───


def test_observe_schema_exposes_p2_params():
    """The observe contract must advertise the two convenience parameters."""
    from mcp_server.registry import build_tool_defs

    defs = {d.name: d for d in build_tool_defs()}
    props = defs["observe"].parameters.get("properties", {})
    assert "store_screenshot" in props, "observe schema lost store_screenshot"
    assert "exclude_urls" in props, "observe schema lost exclude_urls"
    assert "include_network" in props, "observe schema lost include_network"
    assert "include_screenshot" in props, "observe schema lost include_screenshot"


def test_observe_model_accepts_p2_fields():
    """AgentObserveRequest carries the P2 fields so REST callers can use them."""
    m = main.AgentObserveRequest(include_network=True, include_screenshot=True,
                                 store_screenshot=True,
                                 exclude_urls=["/api/v1/proxy", "127.0.0.1:8020"])
    assert m.store_screenshot is True
    assert m.exclude_urls == ["/api/v1/proxy", "127.0.0.1:8020"]


def test_exclude_urls_filters_network_entries():
    """The exclusion predicate drops harness traffic but keeps app calls."""
    entries = [
        {"url": "http://127.0.0.1:8020/agent/observe", "status": 200},
        {"url": "http://127.0.0.1:8080/api/login", "status": 200},
        {"url": "http://127.0.0.1:8080/api/items", "status": 500},
        {"url": "https://cdn.example.com/app.js", "status": 200},
    ]
    excl = ["127.0.0.1:8020"]
    kept = [e for e in entries if not any(x in str(e.get("url", "")) for x in excl)]
    assert [e["url"] for e in kept] == [
        "http://127.0.0.1:8080/api/login",
        "http://127.0.0.1:8080/api/items",
        "https://cdn.example.com/app.js",
    ]
    failures = [e for e in kept if isinstance(e.get("status"), int) and e["status"] >= 400]
    assert len(failures) == 1 and failures[0]["url"].endswith("/api/items")


def test_observe_bundles_network_entries(monkeypatch):
    """observe(include_network=True) embeds the page's network log."""
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient as _TC

    monkeypatch.setattr(type(main.client), "is_connected",
                        property(lambda self: True))
    main.client.analyze_page_condensed = AsyncMock(return_value={
        "status": "ok",
        "page": {"url": "https://example.test/", "title": "Demo",
                 "buttons": [], "form_fields": [], "modals": [],
                 "text_preview": "hello", "text_length": 5,
                 "selected_options": [], "visual_state": {}},
    })
    main.client.start_network_monitoring = AsyncMock(return_value={"status": "ok"})
    main.client.get_network_log = AsyncMock(return_value={"status": "ok", "entries": [
        {"url": "http://127.0.0.1:8080/api/login", "status": 200},
        {"url": "http://127.0.0.1:8020/agent/observe", "status": 200},
    ]})
    api = _TC(main.app)

    resp = api.post("/agent/observe", json={
        "include_network": True,
        "exclude_urls": ["127.0.0.1:8020"],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    net = (body.get("data") or {}).get("network")
    assert net is not None, "include_network produced no network bundle"
    urls = [e.get("url") for e in net.get("entries", [])]
    assert any("8080" in u for u in urls), f"app traffic missing: {urls}"
    assert not any("8020" in u for u in urls), f"harness traffic not excluded: {urls}"


def test_observe_store_screenshot_returns_artifact(monkeypatch):
    """observe(include_screenshot+store) returns a fetchable artifact id."""
    import base64 as _b64
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient as _TC

    monkeypatch.setattr(type(main.client), "is_connected",
                        property(lambda self: True))
    main.client.analyze_page_condensed = AsyncMock(return_value={
        "status": "ok",
        "page": {"url": "https://example.test/", "title": "Demo",
                 "buttons": [], "form_fields": [], "modals": [],
                 "text_preview": "hello", "text_length": 5,
                 "selected_options": [], "visual_state": {}},
    })
    tiny_jpg = _b64.b64encode(b"\xff\xd8\xff\xe0FAKEJPEG").decode()
    main.client.screenshot = AsyncMock(
        return_value={"data": tiny_jpg, "format": "jpeg", "size": 12})
    api = _TC(main.app)

    resp = api.post("/agent/observe", json={
        "include_screenshot": True,
        "store_screenshot": True,
    })
    assert resp.status_code == 200, resp.text
    shot = (resp.json().get("data") or {}).get("screenshot")
    assert shot is not None, "no screenshot bundle"
    assert shot.get("artifact_id"), "store_screenshot produced no artifact_id"
    assert shot.get("artifact_url", "").startswith("/artifacts/")

    get = api.get(shot["artifact_url"])
    assert get.status_code == 200, f"artifact not fetchable: {get.status_code}"


def test_session_new_reuses_existing_session(monkeypatch):
    """A caller that already has a session gets it back, not a new tab."""

    class _FakeSession:
        session_id = "deadbeef-0000-0000-0000-000000000001"
        tab_id = "TAB0000000000001"

        class client:  # noqa: N801 — attribute named to mirror the real Session
            @staticmethod
            async def navigate(url):
                return {"status": "ok", "url": url}

    monkeypatch.setattr(main.session_registry, "get",
                        lambda sid: _FakeSession() if sid == _FakeSession.session_id else None)

    resp = client.post("/session/new?url=about:blank",
                       headers={"X-Session-ID": _FakeSession.session_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body.get("data") or body.get("result") or {}
    assert data.get("reused") is True, f"existing session was not reused: {body}"
    assert data.get("session_id") == _FakeSession.session_id
    assert any("ONCE" in w for w in data.get("warnings", [])), (
        "reuse response does not tell the caller to call /session/new only once"
    )


def test_session_new_spam_detector_warns_after_threshold(monkeypatch):
    """ >3 mints in 60s from one caller ⇒ an in-band warning naming the fix. """
    created = {"n": 0}

    class _Fresh:
        def __init__(self, i):
            self.session_id = f"fresh-{i}"
            self.tab_id = f"TAB{i}"

    async def _fake_create(*a, **kw):
        created["n"] += 1
        return _Fresh(created["n"])

    # No existing session → every call takes the mint path.
    monkeypatch.setattr(main.session_registry, "get", lambda sid: None)
    monkeypatch.setattr(main.session_registry, "create", _fake_create)
    main._session_mint_log.clear()

    warned = False
    for _ in range(5):
        body = client.post("/session/new?url=about:blank").json()
        data = body.get("data") or body.get("result") or {}
        if any("sessions in the last 60s" in w for w in data.get("warnings", [])):
            warned = True
            break

    assert warned, (
        "no tab-spam warning after repeated /session/new calls — a per-request "
        "caller would keep opening tabs silently"
    )
    main._session_mint_log.clear()


def test_strict_sessions_blocks_automint(monkeypatch):
    """BH_STRICT_SESSIONS=1: header-less op gets 400, no tab minted.

    Regression for the field leak where every header-less /eval + auto-mint
    opt-in opened a fresh about:blank tab (1 agent page → 9 empty tabs).
    """
    from unittest.mock import AsyncMock

    monkeypatch.setenv("BH_STRICT_SESSIONS", "1")
    monkeypatch.setenv("BH_SESSION_AUTO", "1")
    # The module-level _STRICT_SESSIONS flag is read at import; the test
    # process imported main without the env var, so force the cached flag
    # too (production sets the env before import, so both agree there).
    # monkeypatch.setattr restores it automatically after the test.
    monkeypatch.setattr(main, "_STRICT_SESSIONS", True)
    # If the code still mints, this mock would be called — it must not be.
    created = {"n": 0}

    async def _fail_on_create(*a, **kw):
        created["n"] += 1
        raise AssertionError("auto-mint must not run in strict mode")

    monkeypatch.setattr(main.session_registry, "create", _fail_on_create)
    monkeypatch.setattr(main.session_registry, "get", lambda sid: None)
    main.client.navigate = AsyncMock(return_value={"status": "ok"})

    resp = client.post("/navigate?url=https://example.test/",
                       headers={"X-Session-Auto": "true"})
    assert resp.status_code == 400, (
        f"strict mode did not block header-less navigate: {resp.status_code} {resp.text[:300]}"
    )
    assert "Missing session" in resp.text
    assert created["n"] == 0, "strict mode minted a tab anyway"
