"""
CDP Client — async WebSocket connection to Chrome DevTools Protocol.

Connects to a local Chrome instance via CDP, discovers tabs through the
/json HTTP endpoint, and provides clean async methods for browser automation.

Usage:
    client = CDPClient()
    await client.connect()
    await client.navigate("https://example.com")
    result = await client.evaluate("document.title")
    await client.close()
"""

import json
import logging
import asyncio
from typing import Any, Optional

import httpx
import websockets

logger = logging.getLogger("browser-helper.cdp")


class CDPError(Exception):
    """CDP protocol error."""
    pass


class CDPClient:
    """Async CDP client for Chrome browser automation."""

    def __init__(self, cdp_http_url: str = "http://127.0.0.1:9555"):
        self.cdp_http_url = cdp_http_url.rstrip("/")
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._target_id: Optional[str] = None
        self._message_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = False
        self._tabs: list[dict] = []
        self._active_tab_id: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tabs_count(self) -> int:
        """Return number of page tabs."""
        return len([t for t in self._tabs if t.get("type") == "page"])

    async def discover_tabs(self) -> list[dict]:
        """Fetch open tabs from /json endpoint."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self.cdp_http_url}/json")
            resp.raise_for_status()
            return resp.json()

    async def connect(self, cdp_url: Optional[str] = None) -> dict:
        """
        Auto-connect to Chrome CDP.

        Discovers available tabs via /json, then connects to the first page
        target (or a specific one matching cdp_url).

        If cdp_url is provided, it's used as the WebSocket URL directly.

        Returns connection info dict.
        """
        tabs = await self.discover_tabs()
        self._tabs = tabs

        # Filter to page targets only
        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            raise CDPError("No page targets found in Chrome")

        # Pick target: match url if given, else first page
        target = None
        if cdp_url:
            for t in pages:
                if cdp_url in t.get("url", ""):
                    target = t
                    break
        if not target:
            target = pages[0]

        target_id = target["id"]
        ws_url = target["webSocketDebuggerUrl"]

        # Connect WebSocket
        self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        self._target_id = target_id
        self._active_tab_id = target_id
        self._connected = True

        # Start message listener
        self._message_id = 0
        self._pending = {}
        asyncio.create_task(self._listener())

        # Enable CDP domains
        await self._send_command("Page.enable")
        await self._send_command("Runtime.enable")

        return {
            "status": "ok",
            "target_id": target_id,
            "title": target.get("title", ""),
            "url": target.get("url", ""),
            "tabs_count": len(pages),
            "cdp_url": ws_url,
        }

    async def _listener(self):
        """Background listener for CDP WebSocket messages."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if not future.done():
                        if "error" in msg:
                            future.set_exception(CDPError(msg["error"].get("message", str(msg["error"]))))
                        else:
                            future.set_result(msg.get("result", {}))
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.warning(f"CDP listener error: {e}")
        finally:
            self._connected = False

    async def _send_command(self, method: str, params: dict = None) -> dict:
        """Send CDP command and wait for result."""
        if not self._ws or not self._connected:
            raise CDPError("Not connected to Chrome CDP")
        self._message_id += 1
        msg_id = self._message_id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future
        await self._ws.send(json.dumps(payload))
        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise CDPError(f"CDP command timeout: {method}")

    async def navigate(self, url: str) -> dict:
        """Navigate to URL and wait for page load."""
        result = await self._send_command("Page.navigate", {"url": url})
        return {"status": "ok", "frame_id": result.get("frameId", ""), "url": url}

    async def evaluate(self, js_code: str) -> dict:
        """Execute JavaScript in page and return result."""
        result = await self._send_command("Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            return {
                "status": "error",
                "error": result["exceptionDetails"].get("text", str(result["exceptionDetails"])),
                "result": None,
            }
        return {
            "status": "ok",
            "result": result.get("result", {}).get("value"),
            "type": result.get("result", {}).get("type", "undefined"),
        }

    async def evaluate_js(self, js_code: str) -> dict:
        """Alias for evaluate()."""
        return await self.evaluate(js_code)

    async def click(self, selector: str) -> dict:
        """Click element by CSS selector."""
        js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return {{'status': 'error', 'error': 'Element not found: {json.dumps(selector)}'}};"
            f"  el.scrollIntoView({{behavior: 'instant', block: 'center'}});"
            f"  const rect = el.getBoundingClientRect();"
            f"  return {{'status': 'ok', 'x': rect.x + rect.width/2, 'y': rect.y + rect.height/2, 'tag': el.tagName}};"
            f"}})()"
        )
        eval_result = await self.evaluate(js)
        if eval_result.get("status") == "error":
            return eval_result
        pos = eval_result.get("result", {})
        # Use CDP Input.dispatchMouseEvent for a real click
        x, y = pos.get("x", 0), pos.get("y", 0)
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        })
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        })
        return {"status": "ok", "selector": selector, "position": {"x": x, "y": y}}

    async def type_text(self, selector: str, text: str) -> dict:
        """Type text into element by CSS selector."""
        js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return {{'status': 'error', 'error': 'Element not found'}};"
            f"  el.focus();"
            f"  el.value = '';"
            f"  el.dispatchEvent(new Event('input', {{bubbles: true}}));"
            f"  el.dispatchEvent(new Event('change', {{bubbles: true}}));"
            f"  return {{'status': 'ok'}};"
            f"}})()"
        )
        result = await self.evaluate(js)
        if result.get("status") == "error":
            return result
        # Type each character via CDP Input.insertText for realistic typing
        await self._send_command("Input.insertText", {"text": text})
        return {"status": "ok", "selector": selector, "chars": len(text)}

    async def screenshot(self, quality: int = 70) -> dict:
        """Take screenshot, return base64 JPEG."""
        result = await self._send_command("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": quality,
            "fromSurface": True,
        })
        data = result.get("data", "")
        return {"status": "ok", "data": data, "format": "jpeg", "size": len(data)}

    async def get_page_text(self) -> dict:
        """Extract main text content from page."""
        result = await self.evaluate(
            "document.body ? document.body.innerText.substring(0, 10000) : 'no body'"
        )
        return {"status": "ok", "text": result.get("result", ""), "length": len(result.get("result", "") or "")}

    async def get_tabs(self) -> list[dict]:
        """List open page tabs with titles and URLs."""
        tabs = await self.discover_tabs()
        pages = [t for t in tabs if t.get("type") == "page"]
        return [
            {
                "id": t["id"],
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "active": t["id"] == self._active_tab_id,
            }
            for t in pages
        ]

    async def switch_tab(self, tab_id: str) -> dict:
        """Switch to a different tab by target ID."""
        tabs = await self.discover_tabs()
        target = next((t for t in tabs if t["id"] == tab_id), None)
        if not target:
            raise CDPError(f"Tab not found: {tab_id}")
        # Close current WebSocket
        await self.close()
        # Connect to new tab
        ws_url = target["webSocketDebuggerUrl"]
        self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        self._target_id = tab_id
        self._active_tab_id = tab_id
        self._connected = True
        self._message_id = 0
        self._pending = {}
        asyncio.create_task(self._listener())
        await self._send_command("Page.enable")
        await self._send_command("Runtime.enable")
        return {"status": "ok", "tab_id": tab_id, "title": target.get("title", "")}

    async def disconnect(self):
        """Alias for close()."""
        await self.close()

    async def close(self):
        """Close CDP connection."""
        self._connected = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        # Cancel pending futures
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending = {}
        self._target_id = None
