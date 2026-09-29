"""v1.36.8: /session/new must only accept http(s) (and about:blank) targets.

Found by an independent review on 2026-09-28 and confirmed live against
Chrome 154.0.8037.57: ``POST /session/new?url=data:text/html,<h1>x</h1>``
opened a real tab.  A ``data:`` document's contents are then readable back
through ``/text`` and ``observe`` — a caller that only holds a loopback API
token can exfiltrate anything a page can render into its own origin context.

``file://`` happened to be rejected by Chrome itself (503 today), but relying
on that is not a control: it is one Chrome version away from not rejecting it.
``workflow_catalog.py`` already enforces an http(s) allowlist, so this is an
inconsistency rather than a new design.

The allowlist lives in ``main._validate_tab_url`` so every tab-creating entry
point (REST, MCP, agent) shares it.
"""

import pytest

import main as bh_main


ALLOWED = [
    "http://example.com/",
    "https://example.com/path?q=1&r=2#frag",
    "about:blank",
    "",  # default target
]

REJECTED = [
    "file:///etc/passwd",
    "data:text/html,<h1>x</h1>",
    "javascript:alert(1)",
    "chrome://settings",
    "chrome-extension://abc/page.html",
    "vbscript:msgbox(1)",
    "blob:http://example.com/1234",
    "view-source:http://example.com/",
]


@pytest.mark.parametrize("url", ALLOWED)
def test_allows_http_https_and_blank(url):
    out = bh_main._validate_tab_url(url)
    assert out is not None


@pytest.mark.parametrize("url", REJECTED)
def test_rejects_non_http_schemes(url):
    assert bh_main._validate_tab_url(url) is None, (
        f"{url!r} must be rejected: a non-http(s) scheme gives the caller a "
        f"document whose content reads back through /text and /observe"
    )


def test_rejects_control_characters():
    assert bh_main._validate_tab_url("https://x.com/\r\nX-Evil: 1") is None
    assert bh_main._validate_tab_url("https://x.com/\n") is None


def test_rejects_empty_host_but_allows_bare_about():
    # "https://" with no host is not a navigable target.
    assert bh_main._validate_tab_url("https://") is None
    # but the CDP default must still work
    assert bh_main._validate_tab_url("about:blank") is not None


def test_allows_loopback_http():
    """The keep-warm URL itself is 127.0.0.1 — the allowlist must not break it."""
    assert bh_main._validate_tab_url("http://127.0.0.1:8080/") is not None
    assert bh_main._validate_tab_url("http://localhost:8020/health") is not None
