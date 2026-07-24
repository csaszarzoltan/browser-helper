"""WebSocket Connection Manager for browser-helper."""

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import WebSocket

from schemas import make_hello

logger = logging.getLogger("browser-helper.ws_manager")


class _ClientRecord:
    __slots__ = ("connected_at", "last_activity", "messages_sent", "missed_pongs", "ws")

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.missed_pongs = 0
        self.messages_sent = 0
        now = datetime.now(UTC).isoformat()
        self.connected_at = now
        self.last_activity = now


class WebSocketManager:
    """Manages connected WebSocket clients for real-time dashboard streaming."""

    def __init__(self, heartbeat_interval: int = 30, max_missed_pongs: int = 3):
        self._heartbeat_interval = heartbeat_interval
        self._max_missed_pongs = max_missed_pongs
        self._clients: dict[str, _ClientRecord] = {}
        self._heartbeat_task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket, client_id: str) -> None:
        record = _ClientRecord(ws)
        self._clients[client_id] = record
        try:
            await ws.send_json(make_hello(state={}, recent_log=[]))
            record.messages_sent += 1
        except Exception:
            self._clients.pop(client_id, None)
            raise
        logger.info("WS client %s connected (%d total)", client_id, len(self._clients))

    async def disconnect(self, client_id: str) -> None:
        self._clients.pop(client_id, None)

    async def broadcast(self, payload: dict) -> None:
        stale = []
        for cid, rec in list(self._clients.items()):
            try:
                await rec.ws.send_json(payload)
                rec.messages_sent += 1
                rec.last_activity = datetime.now(UTC).isoformat()
            except Exception:  # noqa: BLE001
                stale.append(cid)
        for cid in stale:
            self._clients.pop(cid, None)

    async def send_personal(self, client_id: str, payload: dict) -> None:
        rec = self._clients.get(client_id)
        if rec is None:
            return
        try:
            await rec.ws.send_json(payload)
            rec.messages_sent += 1
            rec.last_activity = datetime.now(UTC).isoformat()
        except Exception:  # noqa: BLE001
            self._clients.pop(client_id, None)

    async def start_heartbeat(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def get_stats(self) -> dict:
        clients_info = [
            {
                "client_id": cid,
                "messages_sent": rec.messages_sent,
                "missed_pongs": rec.missed_pongs,
                "connected_at": rec.connected_at,
                "last_activity": rec.last_activity,
            }
            for cid, rec in self._clients.items()
        ]
        return {
            "connected_count": len(self._clients),
            "clients": clients_info,
            "heartbeat_interval": self._heartbeat_interval,
            "max_missed_pongs": self._max_missed_pongs,
        }

    @property
    def active_count(self) -> int:
        return len(self._clients)

    def _record_pong(self, client_id: str) -> None:
        rec = self._clients.get(client_id)
        if rec is not None:
            rec.missed_pongs = 0
            rec.last_activity = datetime.now(UTC).isoformat()

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            ping = {"type": "ping"}
            stale = []
            for cid, rec in list(self._clients.items()):
                try:
                    await rec.ws.send_json(ping)
                    rec.messages_sent += 1
                    rec.missed_pongs += 1
                except Exception:  # noqa: BLE001
                    stale.append(cid)
            for cid in stale:
                self._clients.pop(cid, None)
            for cid, rec in list(self._clients.items()):
                if rec.missed_pongs >= self._max_missed_pongs:
                    self._clients.pop(cid, None)
                    logger.info("WS client %s pruned (%d missed pongs)", cid, rec.missed_pongs)
