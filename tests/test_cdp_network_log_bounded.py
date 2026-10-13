"""The network log of a tab must not grow without limit.

Found 2026-10-13: get_network_requests and observe(include_network) turn network monitoring on,
and it stays on until the connection closes. Every Network.* event of the tab is then appended
to the log, and nothing trims it: measured 2.1 KB per request, linear. An MCP process that
serves a busy tab for days keeps growing. The log now keeps only the newest events.
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

#: The bound the test expects. The product code keeps at most this many events.
LIMIT = 2000


def _request_events(i):
    rid = str(i)
    ts = 1000.0 + i * 0.01
    return [
        {"method": "Network.requestWillBeSent", "params": {"requestId": rid, "timestamp": ts,
            "request": {"url": f"https://app.test/api/item/{i}", "method": "GET", "type": "XHR"}}},
        {"method": "Network.responseReceived", "params": {"requestId": rid, "timestamp": ts + 0.1,
            "response": {"url": f"https://app.test/api/item/{i}", "status": 200, "statusText": "OK",
                         "mimeType": "application/json", "encodedDataLength": 2048}}},
        {"method": "Network.dataReceived", "params": {"requestId": rid, "timestamp": ts + 0.2, "dataLength": 1024}},
        {"method": "Network.loadingFinished", "params": {"requestId": rid, "timestamp": ts + 0.3, "encodedDataLength": 2048}},
    ]


class _FakeSocket:
    """Yields the CDP messages the listener would read from the websocket."""

    def __init__(self, messages):
        self._messages = messages

    def __aiter__(self):
        async def messages():
            for message in self._messages:
                yield json.dumps(message)
        return messages()


def test_the_network_log_keeps_only_the_newest_events():
    from cdp_client import CDPClient

    client = CDPClient(cdp_http_url="http://127.0.0.1:1")
    client._network_monitoring = True
    client._ws = _FakeSocket([event for i in range(1000) for event in _request_events(i)])
    asyncio.run(client._listener())

    entries = client._network_entries
    assert len(entries) <= LIMIT, f"{len(entries)} events kept, the log is unbounded"
    assert entries[-1]["request_id"] == "999", "the newest request must be the one kept"
