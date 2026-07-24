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
import base64
from typing import Any, Optional

import httpx
import websockets

logger = logging.getLogger("browser-helper.cdp")


class CDPError(Exception):
    """CDP protocol error."""
    pass


class CDPDisconnectedError(CDPError):
    """Raised when a CDP operation fails because the connection disconnected."""
    pass


class CDPClient:
    """Async CDP client for Chrome browser automation."""

    def __init__(
        self,
        cdp_http_url: str = "http://127.0.0.1:9555",
        websocket_factory: Optional[callable] = None,
        command_timeout: float = 30.0,
    ):
        self.cdp_http_url = cdp_http_url.rstrip("/")
        self._ws_factory = websocket_factory
        self._command_timeout = command_timeout
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._target_id: Optional[str] = None
        self._message_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = False
        self._tabs: list[dict] = []
        self._active_tab_id: Optional[str] = None
        self._network_entries: list[dict] = []
        self._network_monitoring = False
        # Event callbacks: method_name -> list of async callbacks
        self._event_callbacks: dict[str, list] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tabs_count(self) -> int:
        """Return number of page tabs."""
        return len([t for t in self._tabs if t.get("type") == "page"])

    # ─── Connection ───────────────────────────────────────────────

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
        """
        tabs = await self.discover_tabs()
        self._tabs = tabs

        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            raise CDPError("No page targets found in Chrome")

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

        self._ws = await websockets.connect(ws_url, max_size=50 * 1024 * 1024)
        self._target_id = target_id
        self._active_tab_id = target_id
        self._connected = True
        self._message_id = 0
        self._pending = {}
        self._network_entries = []

        asyncio.create_task(self._listener())

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

                # Network logging
                method = msg.get("method", "")
                if self._network_monitoring and method.startswith("Network."):
                    entry = {
                        "method": method,
                        "timestamp": msg.get("params", {}).get("timestamp", 0),
                        "request_id": msg.get("params", {}).get("requestId", ""),
                    }
                    if method == "Network.requestWillBeSent":
                        req = msg.get("params", {}).get("request", {})
                        entry["url"] = req.get("url", "")
                        entry["type"] = req.get("type", "")
                        entry["method"] = req.get("method", "")
                    elif method == "Network.responseReceived":
                        resp = msg.get("params", {}).get("response", {})
                        entry["url"] = resp.get("url", "")
                        entry["status"] = resp.get("status", 0)
                        entry["status_text"] = resp.get("statusText", "")
                        entry["mime_type"] = resp.get("mimeType", "")
                        entry["size"] = resp.get("encodedDataLength", 0)
                    self._network_entries.append(entry)

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

    # ─── Page operations ─────────────────────────────────────────

    async def navigate(self, url: str) -> dict:
        """Navigate to URL."""
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
        """Click element by CSS selector via real CDP mouse events."""
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
        x, y = pos.get("x", 0), pos.get("y", 0)
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        return {"status": "ok", "selector": selector, "position": {"x": x, "y": y}}

    async def type_text(self, selector: str, text: str) -> dict:
        """Type text into element by CSS selector."""
        js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return {{'status': 'error', 'error': 'Element not found'}};"
            f"  el.focus(); el.value = '';"
            f"  el.dispatchEvent(new Event('input', {{bubbles: true}}));"
            f"  el.dispatchEvent(new Event('change', {{bubbles: true}}));"
            f"  return {{'status': 'ok'}};"
            f"}})()"
        )
        result = await self.evaluate(js)
        if result.get("status") == "error":
            return result
        await self._send_command("Input.insertText", {"text": text})
        return {"status": "ok", "selector": selector, "chars": len(text)}

    async def screenshot(self, quality: int = 70) -> dict:
        """Take viewport screenshot, return base64 JPEG."""
        result = await self._send_command("Page.captureScreenshot", {
            "format": "jpeg", "quality": quality, "fromSurface": True,
        })
        data = result.get("data", "")
        return {"status": "ok", "data": data, "format": "jpeg", "size": len(data)}

    async def get_page_text(self) -> dict:
        """Extract main text content from page."""
        result = await self.evaluate(
            "document.body ? document.body.innerText.substring(0, 10000) : 'no body'"
        )
        text = result.get("result", "") or ""
        return {"status": "ok", "text": text, "length": len(text)}

    # ─── NEW: Full page screenshot ───────────────────────────────

    async def full_page_screenshot(self, quality: int = 70) -> dict:
        """
        Capture full-page screenshot by scrolling and stitching.

        Uses CDP to capture the full rendered page (everything scrollable).
        """
        # Get full page dimensions
        dims = await self.evaluate(
            "(function() { return {"
            "  width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth, document.documentElement.clientWidth),"
            "  height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight, document.documentElement.clientHeight)"
            "}; })()"
        )
        if dims.get("status") == "error":
            return dims
        d = dims.get("result", {})
        viewport = await self.evaluate(
            "(function() { return {w: window.innerWidth, h: window.innerHeight}; })()"
        )
        vp = viewport.get("result", {})

        width = int(d.get("width", 1024))
        height = int(d.get("height", 768))
        vh = int(vp.get("h", 768))

        # Set device metrics to full page height
        await self._send_command("Emulation.setDeviceMetricsOverride", {
            "width": min(width, 1920),
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": False,
        })

        # Now capture
        result = await self._send_command("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": quality,
            "fromSurface": True,
            "captureBeyondViewport": True,
        })

        # Restore viewport
        await self._send_command("Emulation.setDeviceMetricsOverride", {
            "width": min(width, 1280),
            "height": vh,
            "deviceScaleFactor": 1,
            "mobile": False,
        })

        data = result.get("data", "")
        return {"status": "ok", "data": data, "format": "jpeg", "size": len(data),
                "page_width": width, "page_height": height}

    # ─── NEW: Element screenshot ──────────────────────────────────

    async def element_screenshot(self, selector: str, quality: int = 80) -> dict:
        """Capture screenshot of a specific element."""
        js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return null;"
            f"  const r = el.getBoundingClientRect();"
            f"  return {{x: r.x, y: r.y, w: r.width, h: r.height}};"
            f"}})()"
        )
        result = await self.evaluate(js)
        rect = result.get("result")
        if not rect:
            return {"status": "error", "error": f"Element not found: {selector}"}

        clip = await self._send_command("Page.captureScreenshot", {
            "format": "jpeg",
            "quality": quality,
            "clip": {
                "x": rect["x"], "y": rect["y"],
                "width": rect["w"], "height": rect["h"],
                "scale": 1,
            },
        })
        data = clip.get("data", "")
        return {"status": "ok", "data": data, "format": "jpeg", "size": len(data),
                "selector": selector, "rect": rect}

    # ─── NEW: PDF export ──────────────────────────────────────────

    async def pdf(self, options: dict = None) -> dict:
        """Generate PDF of current page.

        Options: landscape, printBackground, paperWidth, paperHeight,
                 marginTop, marginBottom, marginLeft, marginRight, scale
        """
        opts = {
            "printBackground": True,
            "preferCSSPageSize": True,
            "landscape": False,
            "paperWidth": 8.27,
            "paperHeight": 11.69,
            "marginTop": 0.4,
            "marginBottom": 0.4,
            "marginLeft": 0.4,
            "marginRight": 0.4,
            "scale": 1.0,
        }
        if options:
            opts.update(options)
        result = await self._send_command("Page.printToPDF", opts)
        data = result.get("data", "")
        return {"status": "ok", "data": data, "format": "pdf", "size": len(data)}

    # ─── NEW: Cookie management ───────────────────────────────────

    async def get_cookies(self) -> dict:
        """Get all browser cookies."""
        result = await self._send_command("Network.getAllCookies")
        cookies = result.get("cookies", [])
        return {"status": "ok", "cookies": cookies, "count": len(cookies)}

    async def set_cookie(self, name: str, value: str, **kwargs) -> dict:
        """Set a cookie with optional domain, path, secure, httpOnly, etc."""
        params = {"name": name, "value": value, **kwargs}
        try:
            await self._send_command("Network.setCookie", params)
            return {"status": "ok", "cookie": {"name": name, **kwargs}}
        except CDPError as e:
            return {"status": "error", "error": str(e)}

    async def clear_cookies(self) -> dict:
        """Clear all browser cookies."""
        await self._send_command("Network.clearBrowserCookies")
        return {"status": "ok"}

    # ─── NEW: DOM query ───────────────────────────────────────────

    async def dom_query(self, selector: str, attribute: Optional[str] = None) -> dict:
        """Query DOM elements by CSS selector.

        Returns text content of each match, or a specific attribute if given.
        """
        if attribute:
            js = (
                f"Array.from(document.querySelectorAll({json.dumps(selector)})).map(el => el.getAttribute({json.dumps(attribute)}))"
            )
        else:
            js = (
                f"Array.from(document.querySelectorAll({json.dumps(selector)})).map(el => el.textContent.trim())"
            )
        result = await self.evaluate(js)
        items = result.get("result") or []
        return {"status": "ok", "selector": selector, "count": len(items), "items": items,
                "attribute": attribute}

    async def dom_click_all(self, selector: str) -> dict:
        """Click ALL elements matching a selector (e.g. all 'Load more' buttons)."""
        js = (
            f"Array.from(document.querySelectorAll({json.dumps(selector)})).forEach((el, i) => "
            f"  setTimeout(() => el.click(), i * 200)"
            f");"
        )
        await self.evaluate(js)
        return {"status": "ok", "selector": selector}

    # ─── NEW: Network monitoring ──────────────────────────────────

    async def start_network_monitoring(self) -> dict:
        """Start tracking network requests."""
        if not self._network_monitoring:
            await self._send_command("Network.enable")
            self._network_entries = []
            self._network_monitoring = True
        return {"status": "ok", "monitoring": True}

    async def stop_network_monitoring(self) -> dict:
        """Stop tracking network requests."""
        if self._network_monitoring:
            await self._send_command("Network.disable")
            self._network_monitoring = False
        return {"status": "ok", "monitoring": False}

    async def get_network_log(self) -> dict:
        """Get collected network requests."""
        entries = list(self._network_entries)
        return {"status": "ok", "entries": entries, "count": len(entries)}

    async def clear_network_log(self) -> dict:
        """Clear network log."""
        self._network_entries = []
        return {"status": "ok"}

    # ─── NEW: Batch script execution ──────────────────────────────

    async def execute_script(self, steps: list[dict]) -> dict:
        """
        Execute a batch of operations sequentially.

        Each step: {"action": "navigate"|"click"|"type"|"eval"|"screenshot"|"wait"|...,
                     "params": {...}}

        Returns list of results.
        """
        results = []
        for i, step in enumerate(steps):
            action = step.get("action", "")
            params = step.get("params", {})
            try:
                if action == "navigate":
                    res = await self.navigate(params["url"])
                elif action == "click":
                    res = await self.click(params["selector"])
                elif action == "type":
                    res = await self.type_text(params["selector"], params["text"])
                elif action == "eval":
                    res = await self.evaluate(params["js"])
                elif action == "screenshot":
                    res = await self.screenshot(params.get("quality", 70))
                elif action == "full_page_screenshot":
                    res = await self.full_page_screenshot(params.get("quality", 70))
                elif action == "element_screenshot":
                    res = await self.element_screenshot(params["selector"], params.get("quality", 80))
                elif action == "wait":
                    await asyncio.sleep(params.get("ms", 1000) / 1000)
                    res = {"status": "ok", "waited_ms": params.get("ms", 1000)}
                elif action == "scroll":
                    await self._scroll_by(params.get("x", 0), params.get("y", 0))
                    res = {"status": "ok", "x": params.get("x", 0), "y": params.get("y", 0)}
                elif action == "get_text":
                    res = await self.get_page_text()
                elif action == "pdf":
                    res = await self.pdf(params)
                else:
                    res = {"status": "error", "error": f"Unknown action: {action}"}
            except Exception as e:
                res = {"status": "error", "error": str(e), "step": i, "action": action}
            res["step"] = i
            res["action"] = action
            results.append(res)
        return {"status": "ok", "steps": len(steps), "results": results,
                "failed": sum(1 for r in results if r.get("status") == "error")}

    async def _scroll_by(self, x: int = 0, y: int = 0):
        """Scroll page by x, y pixels."""
        await self.evaluate(f"window.scrollBy({x}, {y})")
        await asyncio.sleep(0.1)

    # ─── NEW: Session management ──────────────────────────────────

    async def session_save(self) -> dict:
        """Save browser session (cookies + localStorage)."""
        cookies_result = await self.get_cookies()
        cookies = cookies_result.get("cookies", [])

        ls_result = await self.evaluate(
            "JSON.stringify(window.localStorage || {})"
        )
        try:
            local_storage = json.loads(ls_result.get("result") or "{}")
        except (json.JSONDecodeError, TypeError):
            local_storage = {}

        # Also save sessionStorage
        ss_result = await self.evaluate(
            "JSON.stringify(window.sessionStorage || {})"
        )
        try:
            session_storage = json.loads(ss_result.get("result") or "{}")
        except (json.JSONDecodeError, TypeError):
            session_storage = {}

        session_data = {
            "cookies": cookies,
            "localStorage": local_storage,
            "sessionStorage": session_storage,
            "url": await self._get_current_url(),
        }
        return {"status": "ok", "session": session_data}

    async def session_restore(self, session_data: dict) -> dict:
        """Restore browser session (cookies + localStorage)."""
        restored = {"cookies": 0, "localStorage": 0}

        # Restore URL first
        url = session_data.get("url", "")
        if url:
            await self.navigate(url)
            await asyncio.sleep(1)

        # Restore cookies
        for cookie in session_data.get("cookies", []):
            try:
                await self.set_cookie(
                    cookie.get("name"),
                    cookie.get("value"),
                    domain=cookie.get("domain", ""),
                    path=cookie.get("path", "/"),
                    secure=cookie.get("secure", False),
                    httpOnly=cookie.get("httpOnly", False),
                )
                restored["cookies"] += 1
            except Exception:
                pass

        # Restore localStorage
        ls = session_data.get("localStorage", {})
        for key, value in ls.items():
            escaped_key = json.dumps(key)
            escaped_value = json.dumps(value)
            await self.evaluate(
                f"localStorage.setItem({escaped_key}, {escaped_value})"
            )
            restored["localStorage"] += 1

        # Restore sessionStorage
        ss = session_data.get("sessionStorage", {})
        for key, value in ss.items():
            escaped_key = json.dumps(key)
            escaped_value = json.dumps(value)
            await self.evaluate(
                f"sessionStorage.setItem({escaped_key}, {escaped_value})"
            )

        return {"status": "ok", "restored": restored}

    async def _get_current_url(self) -> str:
        result = await self.evaluate("window.location.href")
        return result.get("result") or ""

    # ─── NEW: Tab management ──────────────────────────────────────

    async def open_new_tab(self, url: str = "about:blank") -> dict:
        """Open a new browser tab."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(f"{self.cdp_http_url}/json/new?{url}")
            resp.raise_for_status()
            target = resp.json()
        return {"status": "ok", "tab_id": target.get("id"),
                "url": target.get("url", url), "title": target.get("title", "")}

    async def close_tab(self, tab_id: str) -> dict:
        """Close a browser tab."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self.cdp_http_url}/json/close/{tab_id}")
            resp.raise_for_status()
        return {"status": "ok", "tab_id": tab_id}

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
        await self.close()
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

    # ─── NEW: Disable/enable JS ───────────────────────────────────

    async def disable_javascript(self) -> dict:
        """Disable JavaScript execution on the page."""
        await self._send_command("Emulation.setScriptExecutionDisabled", {"value": True})
        return {"status": "ok"}

    async def enable_javascript(self) -> dict:
        """Re-enable JavaScript execution."""
        await self._send_command("Emulation.setScriptExecutionDisabled", {"value": False})
        return {"status": "ok"}

    # ─── NEW: Misc helpers ────────────────────────────────────────

    async def get_performance_metrics(self) -> dict:
        """Get page performance metrics."""
        result = await self._send_command("Performance.getMetrics")
        metrics = result.get("metrics", [])
        return {"status": "ok", "metrics": {m["name"]: m["value"] for m in metrics}}

    # ─── Disconnect / Close ───────────────────────────────────────

    async def disconnect(self):
        """Alias for close()."""
        await self.close()

    async def close(self):
        """Close CDP connection."""
        self._connected = False
        if self._network_monitoring:
            try:
                await self._send_command("Network.disable")
            except Exception:
                pass
            self._network_monitoring = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending = {}
        self._target_id = None
