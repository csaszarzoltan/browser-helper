"""Consumer-path gate for the human pacing delay in CDPClient._send_command.

WHY THIS FILE EXISTS
--------------------
Measured 2026-10-06 (post-task review of v1.36.18): the delay *sampler* was proven and the
``asyncio.sleep`` that consumes its output was proven by nothing. Against the same 43-test
gate, all three of these mutants PASSED:

    src/cdp_client.py:78   self._rng = random.Random()              -> random.Random(12345)
    src/cdp_client.py:664  delay_ms = self.rate_limiter.get_delay()  -> delay_ms = 0.0
    src/cdp_client.py:667  await asyncio.sleep(delay_ms / 1000.0)    -> delay_ms / 1.0

Same class as the CDP ``keyPress`` incident: a green suite that is green about the half
nobody doubted. The sampler tests pin the draw; they never drive the send.

HOW THE CALL COMPLETES WITHOUT A CHROME
---------------------------------------
``_send_command`` registers its response future in ``self._pending`` BEFORE awaiting the
websocket send, and awaits the future only after. So the injected transport can resolve the
future from inside ``send()``: production then returns immediately, with no live CDP peer
and no timeout. The transport is the only injected object; the pacing block, the branch and
the unit conversion are production code under test.
"""

from __future__ import annotations

import asyncio

import pytest

from cdp_client import CDPClient, RateLimitConfig, RateLimiter


class _ResolvingWebSocket:
    """Injected transport: records payloads and resolves the pending future on send."""

    def __init__(self, client: CDPClient) -> None:
        self._client = client
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)
        for msg_id, fut in list(self._client._pending.items()):
            if not fut.done():
                fut.set_result({"ok": True, "id": msg_id})


def _paced_client(min_delay_ms: float, max_delay_ms: float, distribution: str = "uniform"):
    """Connected CDPClient with an injected transport and a recording clock.

    ``slept_ms`` accumulates what production passed to ``asyncio.sleep``, converted back to
    milliseconds, so an assertion can state the unit in the reader's terms.
    """
    config = RateLimitConfig(
        enabled=True,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
        distribution=distribution,
    )
    client = CDPClient(cdp_http_url="http://127.0.0.1:1")
    client._connected = True
    client.rate_limiter = RateLimiter(config=config)
    ws = _ResolvingWebSocket(client)
    client._ws = ws
    slept_ms: list[float] = []

    async def recording_sleep(seconds, *args, **kwargs):
        slept_ms.append(float(seconds) * 1000.0)

    return client, ws, slept_ms, recording_sleep


class TestSendPathConsumesTheDelay:
    """The value the sampler produces must reach asyncio.sleep, in the right unit."""

    @pytest.mark.asyncio
    async def test_send_command_sleeps_the_drawn_delay_in_seconds(self, monkeypatch):
        """The sleep receives delay_ms/1000 — not delay_ms, not a constant.

        Kills the ms/s mutant (``/ 1000.0`` -> ``/ 1.0``): production would sleep ~500 s
        instead of ~0.5 s. The assertion catches the three-orders-of-magnitude error without
        waiting for it.
        """
        client, ws, slept_ms, recording_sleep = _paced_client(500.0, 3000.0)
        monkeypatch.setattr(asyncio, "sleep", recording_sleep)

        result = await client._send_command("Runtime.evaluate", {"expression": "1"})

        assert result.get("ok") is True, f"send did not complete: {result!r}"
        assert len(ws.sent) == 1, f"expected one wire payload, got {len(ws.sent)}"
        assert len(slept_ms) == 1, f"expected exactly one pacing sleep, got {slept_ms}"
        slept = slept_ms[0]
        assert 500.0 <= slept <= 3000.0, (
            f"sleep received {slept} ms, outside the configured [500, 3000] ms window. "
            "The argument is in SECONDS, so a /1.0 conversion appears here as a value three "
            "orders of magnitude too large."
        )

    @pytest.mark.asyncio
    async def test_sleep_tracks_the_configured_window(self, monkeypatch):
        """Two different configs must produce two different sleeps.

        Kills ``delay_ms = 0.0`` (no sleep) and any hardcoded constant: with a constant both
        calls sleep the same amount. Also fails a mutant that skips the branch entirely.
        """
        observed: list[float] = []
        for low, high in ((100.0, 200.0), (800.0, 900.0)):
            client, _ws, slept_ms, recording_sleep = _paced_client(low, high)
            monkeypatch.setattr(asyncio, "sleep", recording_sleep)
            await client._send_command("Runtime.evaluate", {"expression": "1"})
            assert slept_ms, f"config [{low}, {high}] produced NO pacing sleep at all"
            assert low <= slept_ms[0] <= high, (
                f"sleep {slept_ms[0]} ms left the configured [{low}, {high}] ms window"
            )
            observed.append(slept_ms[0])

        assert observed[0] != observed[1], (
            f"the pacing sleep did not track the configured window: {observed}"
        )

    @pytest.mark.asyncio
    async def test_no_sleep_when_delay_is_zero(self, monkeypatch):
        """A zero delay must not sleep — the branch is real, not always-taken."""
        client, _ws, slept_ms, recording_sleep = _paced_client(0.0, 0.0)
        monkeypatch.setattr(asyncio, "sleep", recording_sleep)
        await client._send_command("Runtime.evaluate", {"expression": "1"})
        assert slept_ms == [], f"a zero delay still slept: {slept_ms}"

    @pytest.mark.asyncio
    async def test_each_send_draws_its_own_delay(self, monkeypatch):
        """Consecutive sends must not share one frozen draw.

        Kills a mutant that hoists the draw out of the send path or seeds a single shared
        RNG: over 20 sends every gap would be identical.
        """
        client, _ws, slept_ms, recording_sleep = _paced_client(500.0, 3000.0)
        monkeypatch.setattr(asyncio, "sleep", recording_sleep)
        for _ in range(20):
            await client._send_command("Runtime.evaluate", {"expression": "1"})

        assert len(slept_ms) == 20, f"expected 20 pacing sleeps, got {len(slept_ms)}"
        assert len({round(s, 6) for s in slept_ms}) > 1, (
            "every gap was identical — the sampler is not drawn per send"
        )


class TestSamplerIsNotFrozenAcrossInstances:
    """The constructor's own RNG line must be per-instance, not a shared seed.

    This is the mutant the post-task review named (``src/cdp_client.py:78``): every test in
    the sampler suite pins the draw by assigning ``rl._rng`` AFTER construction, so the
    constructor's own line never executes and a frozen seed there is invisible. The defect is
    *cross-instance* — one instance alone cannot show it — so the assertion needs two.
    """

    def test_two_limiters_do_not_share_a_frozen_seed(self):
        config = RateLimitConfig(
            enabled=True, min_delay_ms=500.0, max_delay_ms=3000.0, distribution="uniform"
        )
        first = RateLimiter(config=config)
        second = RateLimiter(config=config)
        draws_a = [first.get_delay() for _ in range(12)]
        draws_b = [second.get_delay() for _ in range(12)]

        assert draws_a != draws_b, (
            "two RateLimiter instances produced an identical draw sequence — "
            "the constructor's RNG is seeded with a constant (src/cdp_client.py:78), so every "
            "instance in a process would pace identically. Measured 2026-10-06: this mutant "
            "passed 43/43 sampler tests because each of them overwrites _rng after construction."
        )


class TestSendPathUsesTheProductionSampler:
    """The send path must call get_delay(), not re-implement or bypass it."""

    @pytest.mark.asyncio
    async def test_limiter_value_reaches_the_sleep(self, monkeypatch):
        """A stub limiter's value must appear as the sleep.

        Pins the seam directly: if production stops calling ``get_delay()``, this fails
        regardless of what the sampler does.
        """
        sentinel_ms = 1234.0
        calls: list[int] = []

        class _StubLimiter:
            def get_delay(self) -> float:
                calls.append(1)
                return sentinel_ms

        client, _ws, _slept, recording_sleep = _paced_client(500.0, 3000.0)
        client.rate_limiter = _StubLimiter()
        slept_ms: list[float] = []

        async def record(seconds, *a, **k):
            slept_ms.append(float(seconds) * 1000.0)

        monkeypatch.setattr(asyncio, "sleep", record)
        await client._send_command("Runtime.evaluate", {"expression": "1"})

        assert calls, "the send path never called rate_limiter.get_delay()"
        assert slept_ms == [sentinel_ms], (
            f"the limiter returned {sentinel_ms} ms but the sleep got {slept_ms} — the "
            "consumption path bypasses the sampler or converts units wrongly"
        )
