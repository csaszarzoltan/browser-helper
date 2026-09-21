"""v1.36 P1 — determinism fixes: silent wait/click failures + visibility predicate.

These pin the three behaviours the field report (`v1.36 buktatók`) exposed:

1. ``wait_for_text`` returned ``status: "ok"`` even when the inner JS reported
   ``status: "error"`` — callers checking ``result["status"] == "ok"`` believed
   a missing text was present.  (Buktató #5/#7 shape: silent failure.)
2. ``click_by_text`` returned a bare ``text not found`` with no candidates, so
   an agent could not self-correct.  (Buktató #5.)
3. The visibility predicate in the hot paths was ``el.offsetParent === null``,
   which filters out an element that is ITSELF ``position: fixed`` (sticky
   footer CTA, fixed-position submit) even though it is painted and clickable.
   A shared helper that also accepts non-zero rects fixes that class.

Python-side behaviour is tested with ``evaluate`` mocked (the established
pattern in ``tests/test_core.py``); the JS-side helper is additionally
exercised against a real Chrome tab at the end of the run.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cdp_client import CDPClient

SRC = Path(__file__).parent.parent / "src" / "cdp_client.py"


@pytest.fixture
def c() -> CDPClient:
    """Fresh CDPClient with no real connection."""
    return CDPClient(cdp_http_url="http://127.0.0.1:9555")


@pytest.fixture(autouse=True)
def _no_activate(c):
    """Skip tab activation — no Chrome needed for these assertions."""
    with patch.object(c, "_activate_current", new=AsyncMock(return_value=None)):
        yield


def _eval_return(inner: dict) -> dict:
    """Shape of what client.evaluate() returns for a JS string result."""
    return {"status": "ok", "result": json.dumps(inner), "type": "string"}


# ─── 1. wait_for_text must not report ok when the text never appeared ───


async def test_wait_for_text_timeout_reports_error_status(c):
    """A wait that timed out must NOT surface as status=ok.

    Regression guard: the outer envelope used to be hardcoded to "ok" while
    the inner JS payload carried the real error.
    """
    inner = {
        "status": "error",
        "error": "text not found after 5s: Welcome back",
    }
    with patch.object(c, "evaluate", new=AsyncMock(return_value=_eval_return(inner))):
        result = await c.wait_for_text("Welcome back", timeout=5)

    assert result.get("status") == "error", (
        f"timed-out wait_for_text surfaced as {result.get('status')!r}: {result}"
    )
    assert "not found" in json.dumps(result).lower()


async def test_wait_for_text_found_stays_ok(c):
    """The happy path keeps reporting ok and still finds the text."""
    inner = {"status": "ok", "text": "Welcome back", "found": True}
    with patch.object(c, "evaluate", new=AsyncMock(return_value=_eval_return(inner))):
        result = await c.wait_for_text("Welcome back", timeout=5)

    assert result.get("status") == "ok"


async def test_wait_for_text_disappear_timeout_reports_error(c):
    """``present=False`` timing out (text still there) is also an error."""
    inner = {
        "status": "error",
        "error": "text still present after 5s: Loading",
    }
    with patch.object(c, "evaluate", new=AsyncMock(return_value=_eval_return(inner))):
        result = await c.wait_for_text("Loading", timeout=5, present=False)

    assert result.get("status") == "error"
    assert "still present" in json.dumps(result).lower()


# ─── 1b. wait_for_condition must actually substitute the searched value ───


async def _capture_js(c, coro_fn, *args, **kwargs):
    """Run a CDP method while capturing the exact JS sent to the browser.

    Returns (result_dict, js_string).  ``evaluate`` is fully mocked, so the JS
    never reaches Chrome — this pins the TEMPLATE, not the browser.
    """
    captured: dict = {}

    async def fake_eval(js, *a, **kw):
        captured["js"] = js
        return {"result": json.dumps({"status": "error", "error": "timeout"})}

    with patch.object(c, "evaluate", new=fake_eval):
        result = await coro_fn(*args, **kwargs)
    return result, captured.get("js", "")


async def test_wait_for_condition_substitutes_selector_into_js(c):
    """``{v}`` was once a JS object literal, not a substitution.

    Regression guard: the emitted JS must reference the value the caller
    passed — the browser-side ``const v = <value>`` binding — and must not
    contain a literal ``{v}``, which JavaScript parses as an object and
    ``querySelector`` rejects (so the wait timed out 100% of the time while
    the Python envelope still reported status ``ok``).
    """
    _result, js = await _capture_js(c, c.wait_for_condition, "selector", "#myBtn", "visible", timeout=1)
    assert "{v}" not in js, f"literal {{v}} still in the emitted JS: {js[:300]}"
    assert "querySelector(v)" in js, f"selector check lost its value binding: {js[:300]}"


async def test_wait_for_condition_substitutes_text_into_js(c):
    """Same as above for the ``kind=text`` branch."""
    _result, js = await _capture_js(c, c.wait_for_condition, "text", "Hello", "present", timeout=1)
    assert "{v}" not in js, f"literal {{v}} still in the emitted JS: {js[:300]}"
    assert "includes(v)" in js, f"text check lost its value binding: {js[:300]}"


async def test_wait_for_condition_present_selector_uses_value_binding(c):
    """The plain ``selector``+``present`` branch binds the value too."""
    _result, js = await _capture_js(c, c.wait_for_condition, "selector", "#cta", "present", timeout=1)
    assert "{v}" not in js, f"literal {{v}} still in the emitted JS: {js[:300]}"
    assert "querySelector(v)" in js, f"present check lost its value binding: {js[:300]}"


# ─── 2. click_by_text failure must carry actionable candidates ───


async def test_click_by_text_not_found_surfaces_candidates(c):
    """The not-found error must list near-miss texts so an agent can retry.

    Field report: clicking "Már van fiókom" returned an unexplained error and
    the agent had no way to discover what text WAS on the page.
    """
    inner = {
        "status": "error",
        "error": "text not found: Már van fiókom (nth=0)",
        "candidates": ["Log in", "Sign up", "Forgot password?"],
    }
    with patch.object(c, "evaluate", new=AsyncMock(return_value=_eval_return(inner))):
        result = await c.click_by_text("Már van fiókom", timeout=1)

    assert result.get("status") == "error"
    blob = json.dumps(result)
    for near in ("Log in", "Sign up", "Forgot password?"):
        assert near in blob, f"candidate {near!r} missing from the error payload"
    assert "hint" in result, "error carries no actionable hint for the agent"


async def test_click_by_text_ok_path_unchanged(c):
    """The happy path still returns ok after the real CDP click."""
    inner = {
        "status": "ok", "tag": "A", "text": "Log in",
        "x": 10.0, "y": 20.0, "w": 60.0, "h": 20.0,
        "match_index": 0, "total_matches": 1,
    }
    client = c
    with patch.object(client, "evaluate", new=AsyncMock(return_value=_eval_return(inner))):
        with patch.object(client, "_send_command", new=AsyncMock(return_value=None)):
            result = await client.click_by_text("Log in", timeout=1)

    assert result.get("status") == "ok"
    assert result["result"]["cdp_click"] is True


# ─── 3. Shared visibility predicate for painted-but-fixed elements ───


def test_visibility_helper_exists_and_is_used():
    """The hot paths share one predicate instead of raw offsetParent checks.

    ``el.offsetParent === null`` is true for an element that is itself
    ``position: fixed``, so a fixed CTA/button was invisible to
    ``analyze_page`` and ``click_by_text``.  The helper also accepts a
    painted rect, keeping genuinely hidden elements out.
    """
    src = SRC.read_text()

    assert "__bhVisible" in src, (
        "no shared visibility helper (__bhVisible) in cdp_client.py — the "
        "fixed-position element class is still filtered out"
    )
    # The helper must accept non-zero rects, not only offsetParent.
    helper_at = src.index("function __bhVisible")
    helper_body = src[helper_at:helper_at + 900]
    assert "getBoundingClientRect" in helper_body, (
        "helper does not consider the element's rect"
    )
    assert "getComputedStyle" in helper_body, (
        "helper does not consider computed style (display/visibility/opacity)"
    )

    # analyze_page + click_by_text must route through the helper.
    assert "__bhVisible(el)" in src, "helper defined but not called"


def test_analyze_page_js_uses_helper_for_buttons():
    """analyze_page's button/inner-element loop uses the shared helper."""
    src = SRC.read_text()
    analyze_at = src.index("async def analyze_page")
    analyze_js = src[analyze_at:analyze_at + 6000]
    assert "__bhVisible" in analyze_js, (
        "analyze_page still filters interactive elements with offsetParent"
    )


def test_click_by_text_js_uses_helper():
    """click_by_text's finder uses the shared helper."""
    src = SRC.read_text()
    click_at = src.index("async def click_by_text")
    click_js = src[click_at:click_at + 6000]
    assert "__bhVisible" in click_js, (
        "click_by_text still filters candidate elements with offsetParent"
    )
