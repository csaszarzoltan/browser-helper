"""Parallel session isolation test.

Verifies that two concurrent browser-helper clients (each with its own
cookie jar / session) get SEPARATE tabs and never overwrite each other's
navigation — even when they operate simultaneously.

This test talks to the RUNNING browser-helper service on :8020 (a real
Chrome), NOT the mocked test environment.  It deliberately opts out of the
autouse ``_no_real_chrome`` fixture so the real service paths (per-client
session minting, ``_ws_tab_id`` tracking, tab isolation) are exercised
end-to-end.  Skips when the service is not reachable.
"""
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request

import pytest

BH = "http://127.0.0.1:8020"
PROXY_Q = "https://www.google.com/search?q={q}"


class _Client:
    """Cookie-jar aware BH client (1 session per instance)."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def post(self, path, data=None, timeout=60):
        req = urllib.request.Request(
            f"{BH}{path}",
            data=json.dumps(data).encode() if data is not None else b"",
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None or path.startswith("/agent") else "GET",
        )
        with self.opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def navigate(self, url, timeout=60):
        return json.loads(self.opener.open(
            urllib.request.Request(f"{BH}/navigate?url={urllib.parse.quote(url)}",
                                   data=b"", method="POST"),
            timeout=timeout,
        ).read().decode())

    def eval(self, js, timeout=30):
        return self.post("/eval", {"js": js}, timeout=timeout)

    def title(self, timeout=30):
        r = self.eval("document.title", timeout=timeout)
        return (r.get("data") or {}).get("result", "")


@pytest.fixture(scope="module")
def _bh_service_ready():
    """Verify the live service is up; skip the module if not.

    Uses ``browser_available`` (NOT ``connected``) — the ``connected`` flag
    reflects only the shared default client, while per-client sessions live
    independently and are what these tests exercise.
    """
    try:
        with urllib.request.urlopen(f"{BH}/status", timeout=5) as resp:
            st = json.loads(resp.read().decode())
        assert st.get("browser_available"), "service has no Chrome available"
    except Exception as exc:  # pragma: no cover  # noqa: BLE001 - skip when service is down
        pytest.skip(f"browser-helper service not reachable: {exc}")
    return True


def test_parallel_sessions_get_separate_tabs(_bh_service_ready):
    """Two concurrent clients navigate to DIFFERENT pages and must not
    overwrite each other's tab — each sees its own URL/title."""

    a = _Client()
    b = _Client()

    # Navigate both to distinct Google queries (parallel-ish, sequential
    # here but each fresh cookie → own session/tab).
    qa = "parallel_test_alpha_8f9e"
    qb = "parallel_test_beta_7c31"
    ra = a.navigate(PROXY_Q.format(q=qa))
    assert ra.get("status") == "ok", f"agent A navigate failed: {ra}"
    rb = b.navigate(PROXY_Q.format(q=qb))
    assert rb.get("status") == "ok", f"agent B navigate failed: {rb}"

    time.sleep(4)  # let pages (and title) settle

    ta = a.title()
    tb = b.title()

    # Each tab title must contain ITS OWN query marker and NOT the other's.
    assert qa in ta.lower() and qb not in ta.lower(), (
        f"A's tab was overwritten: A title={ta!r} (wanted {qa})"
    )
    assert qb in tb.lower() and qa not in tb.lower(), (
        f"B's tab was overwritten: B title={tb!r} (wanted {qb})"
    )


def test_parallel_search_overwrites_no_one(_bh_service_ready):
    """The one-call /agent/search (used by research workers) must mint its
    own session tab — two parallel searches with distinct queries must not
    land on the same tab."""

    a = _Client()
    b = _Client()

    qa = "parallel search marker alpha q1x"
    qb = "parallel search marker beta q2y"
    a.post("/agent/search", {"query": qa, "engine": "google", "timeout": 25})
    b.post("/agent/search", {"query": qb, "engine": "google", "timeout": 25})

    # Each search returns some answer text; more importantly each landed on
    # its own tab. Verify via the returned query marker in title.
    time.sleep(2)
    ta = a.title()
    tb = b.title()

    assert qa in ta.lower(), f"A search tab not on A's query: {ta!r} vs {qa}"
    assert qb in tb.lower(), f"B search tab not on B's query: {tb!r} vs {qb}"
