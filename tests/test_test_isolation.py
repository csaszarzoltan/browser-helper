"""The suite must not reach the user's live Chrome (9557) or the live service (8020).

conftest.py refuses those requests in-process. Live tests opt out with BH_LIVE=1.
"""

import asyncio
import os

import httpx
import pytest


@pytest.mark.skipif(os.environ.get("BH_LIVE") == "1", reason="live run: the guard is off on purpose")
def test_a_request_to_the_live_browser_is_refused():
    async def go():
        async with httpx.AsyncClient(timeout=2) as client:
            await client.get("http://127.0.0.1:9557/json/version")

    with pytest.raises(httpx.ConnectError, match="test isolation"):
        asyncio.run(go())


def test_a_request_to_an_ordinary_local_port_is_not_refused():
    # The guard must not block the tests' own fake servers and mocks.
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(204))) as client:
            return (await client.get("http://127.0.0.1:9/json")).status_code

    if os.environ.get("BH_LIVE") == "1":
        pytest.skip("live run: the guard is off")
    assert asyncio.run(go()) == 204
