"""Unit tests for the domain-level navigation throttle."""

import asyncio
import time

import pytest

from domain_throttle import DEFAULT_MIN_INTERVAL_SEC, DomainThrottle


@pytest.mark.asyncio
async def test_first_navigation_is_immediate():
    """The first navigation to a domain must not wait."""
    throttle = DomainThrottle()
    waited = await throttle.wait("https://google.com/search?q=test")
    assert waited == 0.0


@pytest.mark.asyncio
async def test_second_navigation_waits_for_interval():
    """A second navigation to the same domain within the interval must wait."""
    throttle = DomainThrottle()
    await throttle.wait("https://google.com/search?q=1")
    waited = await throttle.wait("https://google.com/search?q=2")
    assert waited >= DEFAULT_MIN_INTERVAL_SEC - 0.2
    assert waited <= DEFAULT_MIN_INTERVAL_SEC + 1.0


@pytest.mark.asyncio
async def test_different_domains_are_independent():
    """Different domains must not throttle each other."""
    throttle = DomainThrottle()
    await throttle.wait("https://google.com/")
    waited = await throttle.wait("https://github.com/")
    assert waited == 0.0


@pytest.mark.asyncio
async def test_www_is_a_different_netloc():
    """www.google.com is a distinct netloc — throttling is netloc-based.

    The user asked for domain-per-netloc throttling; subdomains (www, maps,
    ...) are separate keys so one busy subdomain does not stall the others.
    """
    throttle = DomainThrottle()
    await throttle.wait("https://google.com/")
    waited = await throttle.wait("https://www.google.com/")
    assert waited == 0.0


@pytest.mark.asyncio
async def test_port_is_stripped_for_domain_key():
    """A different port on the same host shares the same throttle key."""
    throttle = DomainThrottle()
    await throttle.wait("https://example.com/")
    waited = await throttle.wait("https://example.com:8080/")
    assert waited > 0.0


@pytest.mark.asyncio
async def test_custom_interval():
    """A custom interval overrides the default."""
    throttle = DomainThrottle()
    await throttle.wait("https://example.com/")
    waited = await throttle.wait("https://example.com/", min_interval=0.5)
    assert 0.4 <= waited <= 1.5


@pytest.mark.asyncio
async def test_force_bypasses_wait():
    """force=True must skip the wait entirely."""
    throttle = DomainThrottle()
    await throttle.wait("https://google.com/")
    waited = await throttle.wait("https://google.com/", force=True)
    assert waited == 0.0


@pytest.mark.asyncio
async def test_zero_interval_disables_throttle():
    """min_interval <= 0 disables the throttle."""
    throttle = DomainThrottle()
    await throttle.wait("https://google.com/")
    waited = await throttle.wait("https://google.com/", min_interval=0)
    assert waited == 0.0


@pytest.mark.asyncio
async def test_schemeless_and_invalid_urls_never_wait():
    """URLs without a domain (data:, about:, garbage) never wait."""
    throttle = DomainThrottle()
    await throttle.wait("data:text/html,<title>x</title>")
    waited = await throttle.wait("data:text/html,<title>y</title>")
    assert waited == 0.0
    await throttle.wait("not a url")
    waited2 = await throttle.wait("not a url")
    assert waited2 == 0.0


def test_domain_of_parses_netloc():
    """_domain_of extracts and lowercases the netloc."""
    throttle = DomainThrottle()
    assert throttle._domain_of("https://Google.com/path?q=1") == "google.com"
    assert throttle._domain_of("http://sub.example.co.uk:8080/x") == "sub.example.co.uk"
    assert throttle._domain_of("data:text/html,<title>x</title>") == ""


@pytest.mark.asyncio
async def test_interval_grows_with_more_navigations():
    """Each subsequent navigation within the window waits for the full gap."""
    throttle = DomainThrottle()
    await throttle.wait("https://google.com/")
    w1 = await throttle.wait("https://google.com/")
    w2 = await throttle.wait("https://google.com/")
    assert w1 > 0 and w2 > 0
    assert w1 >= DEFAULT_MIN_INTERVAL_SEC - 0.2
    assert w2 >= DEFAULT_MIN_INTERVAL_SEC - 0.2


@pytest.mark.asyncio
async def test_concurrent_waiters_serialize():
    """Concurrent waiters for the same domain must serialize (no stampede)."""
    throttle = DomainThrottle()
    await throttle.wait("https://google.com/")
    start = time.monotonic()
    results = await asyncio.gather(
        throttle.wait("https://google.com/"),
        throttle.wait("https://google.com/"),
    )
    elapsed = time.monotonic() - start
    assert all(w > 0 for w in results)
    # Two waiters, each needing ~2s, must take >= ~4s total.
    assert elapsed >= 2 * DEFAULT_MIN_INTERVAL_SEC - 0.5


@pytest.mark.asyncio
async def test_reset_clears_history():
    """reset() clears the per-domain history."""
    throttle = DomainThrottle()
    await throttle.wait("https://google.com/")
    assert throttle.last_hit("google.com") > 0
    throttle.reset()
    assert throttle.last_hit("google.com") == 0.0
