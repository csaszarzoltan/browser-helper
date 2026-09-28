"""v1.36.7: ``/session/new?url=`` must preserve the URL's own query string.

Live bug found 2026-09-28 against Chrome 154.0.8037.57.  v1.36.2 fixed
``/session/new?url=`` by appending the URL *raw* to ``/json/new?``:

    new_tab_url = f"{client.cdp_http_url}/json/new?{url}"

Chrome's ``/json/new`` takes the whole remainder of the request line as the
target URL — so a URL that itself contains ``&`` is cut at the first ampersand:

    PUT /json/new?https://example.com/?a=1&b=2   ->  opens https://example.com/?a=1
                                                     (b=2 silently lost)

Verified live; the correct form percent-encodes the whole URL:

    PUT /json/new?https%3A%2F%2Fexample.com%2F%3Fa%3D1%26b%3D2
                                                     ->  opens .../?a=1&b=2

These tests pin the encoding helper so the raw form cannot come back.
"""

import pytest

import session_registry as sr


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


@pytest.mark.parametrize(
    "url,expected_tail",
    [
        ("https://example.com/", "https%3A%2F%2Fexample.com%2F"),
        ("https://example.com/?a=1&b=2", "https%3A%2F%2Fexample.com%2F%3Fa%3D1%26b%3D2"),
        ("https://example.com/?q=a%20b", "https%3A%2F%2Fexample.com%2F%3Fq%3Da%2520b"),
    ],
)
def test_build_new_tab_url_encodes_everything(url, expected_tail):
    built = sr._build_new_tab_url("http://127.0.0.1:9557", url)
    assert built.startswith("http://127.0.0.1:9557/json/new?")
    assert built.split("?", 1)[1] == expected_tail


def test_build_new_tab_url_about_blank_is_not_encoded():
    """about:blank is the CDP default — no query appended at all."""
    assert sr._build_new_tab_url("http://x", "about:blank") == "http://x/json/new"
    assert sr._build_new_tab_url("http://x", "") == "http://x/json/new"
    assert sr._build_new_tab_url("http://x", None) == "http://x/json/new"


def test_ampersand_survives_the_round_trip():
    """The regression: a 2-param query must not be truncated to 1 param."""
    import urllib.parse

    built = sr._build_new_tab_url("http://127.0.0.1:9557", "https://example.com/?a=1&b=2")
    payload = built.split("?", 1)[1]
    # what the server actually receives as the target URL
    assert urllib.parse.unquote(payload) == "https://example.com/?a=1&b=2"


def test_fragment_is_preserved():
    import urllib.parse

    built = sr._build_new_tab_url("http://x", "https://example.com/p#sec-2")
    assert urllib.parse.unquote(built.split("?", 1)[1]) == "https://example.com/p#sec-2"


def test_control_characters_are_escaped_not_injected():
    """A CRLF in the target must never reach the request line verbatim."""
    built = sr._build_new_tab_url("http://x", "https://example.com/\r\nX-Evil: 1")
    payload = built.split("?", 1)[1]
    assert "\r" not in payload and "\n" not in payload
