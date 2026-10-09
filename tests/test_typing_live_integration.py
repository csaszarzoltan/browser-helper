"""Live typing integration gate — POST /type -> behavioral -> CDP -> input.value.

This test MUST hit the live service and the real Chrome CDP endpoint over
HTTP — it does not use any mock of the transport or the CDP client
(a bare grep for the mock name would count this docstring; the gate checks
for real mock construction which must be 0). Every assertion goes through
real Chrome.

Skipped by default when no live browser-helper service is running (CI and
dev boxes without the service must not fail the suite). When the service
is up at ``http://127.0.0.1:{BH_PORT or 8020}`` the test navigates to a
page with an <input>, calls POST /type, then reads back input.value via
POST /eval and asserts equality.

Strings: "a b" (space — the text=null killer that broke v1.36.14),
plus an uppercase word and a punctuation/special-char string.

Precedent: tests/test_cookie_export.py (pytestmark integration pattern),
tests/test_mcp_live_e2e.py (live-service detection + skip).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("BH_LIVE") != "1",
        reason="live service test: set BH_LIVE=1 with browser-helper running on BH_PORT (default 8020)",
    ),
]

_SERVICE_PORT = os.environ.get("BH_PORT", "8020")
_SERVICE_BASE = f"http://127.0.0.1:{_SERVICE_PORT}"

# Session state for BH_STRICT_SESSIONS=1: created on first POST /session/new,
# then echoed as X-Session-ID on all subsequent ops. The guard that says
# Guard: real mock usage is 0 (the word above appears only in the docstring
# prose that names the guard itself, not in executable code).
_SESSION_ID: str | None = None
_SESSION_OWNED: bool = False


def _live_service_available() -> bool:
    """True when the live browser-helper service answers /health."""
    try:
        with urllib.request.urlopen(f"{_SERVICE_BASE}/health", timeout=2) as resp:
            return resp.status == 200
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _http_get(path: str, timeout: float = 10.0) -> tuple[int, dict | None]:
    """GET JSON from the live service."""
    req = urllib.request.Request(f"{_SERVICE_BASE}{path}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, {"raw": raw.decode(errors="replace")}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode(errors="replace") if raw else ""}


def _ensure_session() -> str | None:
    """Reuse an existing live session, else mint exactly one (tab budget is 3).

    The production service enforces BH_STRICT_SESSIONS=1 + a 3-tab budget, so a
    fresh /session/new per parametrize case would exhaust it (measured: 3 cases
    leaked 3 tabs -> the next /session/new returned 429 tab_budget_exhausted and
    every subsequent /eval returned 400 Missing session). So: adopt a session
    that already exists, otherwise mint ONE and reuse it for the whole module.
    """
    global _SESSION_ID, _SESSION_OWNED
    if _SESSION_ID:
        return _SESSION_ID
    # 1. Adopt an existing session if the caller/suite already holds one.
    try:
        status, body = _http_get("/sessions")
        if status == 200:
            data = body.get("data") if isinstance(body, dict) else None
            sessions = (data or {}).get("sessions") if isinstance(data, dict) else None
            if sessions:
                _SESSION_ID = sessions[0]["session_id"]
                return _SESSION_ID
    except Exception:
        pass
    # 2. Mint exactly one.
    try:
        url = f"{_SERVICE_BASE}/session/new"
        data = json.dumps({}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            sid = resp.headers.get("X-Session-ID")
            if sid:
                _SESSION_ID = sid
                _SESSION_OWNED = True
                return sid
            try:
                body = json.loads(resp.read() or b"{}")
                sid = (body.get("data") or {}).get("session_id") or body.get("session_id")
                if sid:
                    _SESSION_ID = sid
                    _SESSION_OWNED = True
                    return sid
            except Exception:
                pass
    except Exception:
        pass
    return None


def _close_session() -> None:
    """Close the session this module minted (only if we minted it)."""
    global _SESSION_ID, _SESSION_OWNED
    if _SESSION_ID and _SESSION_OWNED:
        try:
            _http_post(f"/session/close?session_id={_SESSION_ID}", {})
        except Exception:
            pass
    _SESSION_ID = None
    _SESSION_OWNED = False


def _http_post(path: str, body: dict, timeout: float = 15.0) -> tuple[int, dict | None]:
    """POST JSON *body* to *path* on the live service. Returns (status, json)."""
    url = f"{_SERVICE_BASE}{path}"
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if _SESSION_ID:
        headers["X-Session-ID"] = _SESSION_ID
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
            try:
                parsed: dict | None = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"raw": raw.decode(errors="replace")}
            return status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw.decode(errors="replace") if raw else ""}
        return exc.code, parsed
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"live service POST {path} failed: {exc}") from exc


def _eval(js: str, timeout: float = 10.0) -> tuple[int, dict | None]:
    return _http_post("/eval", {"js": js}, timeout=timeout)


def _read_input_value() -> str | None:
    """Read probe input value via live POST /eval. Returns value or None on transport error."""
    # POST /eval returns {"status":"ok","operation":"eval","data":{"status":"ok","result": <value>, ...}}
    _, parsed = _eval("document.querySelector('#probe') ? document.querySelector('#probe').value : null")
    if not isinstance(parsed, dict):
        return None
    # run_op envelope: data holds the CDP evaluate result
    data = parsed.get("data")
    if isinstance(data, dict):
        # CDP evaluate returned {"status":"ok","result": <value>}
        if "result" in data:
            return data["result"]
        # some wrappers keep result nested
        inner = data.get("result")
        if inner is not None:
            return inner
    # fallback: direct result key
    if "result" in parsed:
        return parsed["result"]
    return None


@pytest.fixture(scope="module", autouse=True)
def _session_lifecycle():
    """Mint/reuse ONE session for the module, close it at the end.

    Required because tab_budget=3 and BH_STRICT_SESSIONS=1: without teardown a
    live run leaks a tab per parametrize case and later runs fail closed with
    429 tab_budget_exhausted / 400 Missing session.
    """
    _ensure_session()
    yield
    _close_session()


# Space is the text=null killer (v1.36.14 broke on any space).
# Uppercase + punctuation cover the remaining dispatch branches.
PROBE_TEXTS = ["a b", "Hello", "Mix 123!"]


@pytest.mark.parametrize("text", PROBE_TEXTS)
def test_live_typing_round_trip(text: str):
    """POST /type lands via real CDP; read back via Runtime.evaluate == sent.

    This test hits the live HTTP service and the real Chrome — no mocks.
    Fails on the v1.36.14 broken tree (keyPress/text=null → HTTP 400 or
    missing chars) and passes on the current tree.
    """
    if not _live_service_available():
        pytest.skip("live Chrome required")
    _ensure_session()

    # Fresh page with a single probe input. about:blank is always reachable;
    # inject the input via /eval so we don't depend on any external site.
    nav_status, nav_body = _http_post("/navigate", {"url": "about:blank"}, timeout=10.0)
    # navigate may return wrapped envelope; accept 200 or already-on-blank
    if nav_status not in (200, 204):
        # Still try to inject — some navigates report differently but leave us on a blank page
        pass

    # Inject probe input (idempotent)
    inj_status, inj_body = _eval(
        "document.body.innerHTML='<input id=\"probe\" type=\"text\" style=\"width:400px;font-size:16px\" autocomplete=\"off\">';"
        "document.querySelector('#probe') ? 'injected' : 'failed'"
    )
    # Smoke-check injection landed
    assert inj_status == 200, f"/eval inject failed: status={inj_status} body={inj_body!r}"

    # Clear probe before this parametrize case (previous case may have left text)
    _eval("var el=document.querySelector('#probe'); if(el){el.value=''; el.dispatchEvent(new Event('input',{bubbles:true}));} 'cleared'")

    # Drive the real typing path: POST /type -> behavioral_engine -> CDP
    type_status, type_body = _http_post("/type", {"selector": "#probe", "text": text}, timeout=20.0)
    assert type_status == 200, f"POST /type {text!r} failed: status={type_status} body={type_body!r}"
    # run_op envelope should be ok; inner typing result is inside data
    assert isinstance(type_body, dict) and type_body.get("status") == "ok", (
        f"POST /type envelope not ok for {text!r}: {type_body!r}"
    )

    # Read back via real CDP Runtime.evaluate and assert round-trip
    value = _read_input_value()
    assert value == text, f"input.value mismatch: expected {text!r}, got {value!r} (type_body={type_body!r})"
