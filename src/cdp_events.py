"""
CDP Event Forwarder — streams Chrome DevTools Protocol events
to WebSocket clients as structured ``console_log`` and ``navigation`` messages.

Connects to the CDP event stream, listens for ``Runtime.consoleAPICalled``
and ``Page.frameNavigated`` events, and forwards them to the dashboard
via the WebSocketManager.
"""

from src.cdp_client import CDPClient
from src.ws_manager import WebSocketManager


class CDPEventForwarder:
    """
    Forwards selected CDP events to WebSocket dashboard clients.

    After ``start()`` is called, the forwarder enables ``Runtime`` and ``Page``
    CDP domains and listens for console API calls and frame navigations.
    """

    def __init__(self, cdp_client: CDPClient, ws_manager: WebSocketManager):
        self._cdp_client = cdp_client
        self._ws_manager = ws_manager

    async def start(self) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError
