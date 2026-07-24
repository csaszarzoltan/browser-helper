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

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import quote

import httpx
import websockets

logger = logging.getLogger("browser-helper.cdp")


class CDPError(Exception):
    """CDP protocol error."""


class CDPDisconnectedError(CDPError):
    """Raised when a CDP operation fails because the connection disconnected."""


class CDPClient:
    """Async CDP client for Chrome browser automation."""

    def __init__(
        self,
        cdp_http_url: str = "http://127.0.0.1:9555",
        websocket_factory: Any = None,
        command_timeout: float = 30.0,
    ):
        self.cdp_http_url = cdp_http_url.rstrip("/")
        self._ws_factory = websocket_factory
        self._command_timeout = command_timeout
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._target_id: str | None = None
        self._message_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = False
        self._tabs: list[dict] = []
        self._active_tab_id: str | None = None
        self._network_entries: list[dict] = []
        self._network_monitoring = False
        # Event callbacks: method_name -> list of async callbacks
        self._event_callbacks: dict[str, list] = {}
        # ── Performance optimizations ──
        self._http_client: httpx.AsyncClient | None = None
        """Reusable HTTP client (keep-alive, connection pooling)."""
        self._tabs_cache: list[dict] = []
        self._tabs_cache_ts: float = 0
        self._tabs_cache_ttl: float = 5.0  # seconds

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tabs_count(self) -> int:
        """Return number of page tabs."""
        return len([t for t in self._tabs if t.get("type") == "page"])

    # ─── Connection ───────────────────────────────────────────────

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create shared HTTP client (keep-alive + connection pooling)."""
        if self._http_client is None or self._http_client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=30)
            self._http_client = httpx.AsyncClient(timeout=5.0, limits=limits)
        return self._http_client

    async def discover_tabs(self) -> list[dict]:
        """Fetch open tabs from /json endpoint (cached up to 5 seconds)."""
        now = time.monotonic()
        if self._tabs_cache and (now - self._tabs_cache_ts) < self._tabs_cache_ttl:
            return self._tabs_cache
        client = await self._get_http_client()
        resp = await client.get(f"{self.cdp_http_url}/json")
        resp.raise_for_status()
        self._tabs_cache = resp.json()
        self._tabs_cache_ts = now
        return self._tabs_cache

    async def connect(self, cdp_url: str | None = None) -> dict:
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

                # Dispatch registered event callbacks
                ev_method = msg.get("method", "")
                if ev_method in self._event_callbacks:
                    for cb in self._event_callbacks[ev_method]:
                        try:
                            cb(msg)
                        except Exception:  # noqa: BLE001
                            logger.warning("Event callback error for %s", ev_method)

        except websockets.exceptions.ConnectionClosed:
            self._connected = False
            # Fail any pending futures with CDPDisconnectedError
            exc = CDPDisconnectedError("Connection closed by remote")
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(exc)
            self._pending.clear()
        except Exception as e:
            logger.warning(f"CDP listener error: {e}")
        finally:
            self._connected = False

    async def _send_command(self, method: str, params: dict | None = None) -> dict:
        """Send CDP command and wait for result."""
        if not self._ws or not self._connected:
            raise CDPError("Not connected to Chrome CDP")
        self._message_id += 1
        msg_id = self._message_id
        payload = {"id": msg_id, "method": method, "params": params or {}}
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        await self._ws.send(json.dumps(payload))
        try:
            result = await asyncio.wait_for(future, timeout=self._command_timeout)
            return result
        except TimeoutError:
            self._pending.pop(msg_id, None)
            raise CDPError(f"CDP command timeout: {method}")

    # ─── Event callback API ────────────────────────────────────────

    def add_event_listener(self, method: str, callback) -> None:
        """Register an async callback for a CDP event method.

        Args:
            method: CDP event method name (e.g. ``Runtime.consoleAPICalled``).
            callback: Async callable receiving the full CDP message dict.
        """
        if method not in self._event_callbacks:
            self._event_callbacks[method] = []
        self._event_callbacks[method].append(callback)

    def remove_event_listener(self, method: str, callback) -> None:
        """Unregister a previously added event callback."""
        if method in self._event_callbacks:
            self._event_callbacks[method] = [
                cb for cb in self._event_callbacks[method] if cb is not callback
            ]

    # ─── Page operations ─────────────────────────────────────────

    async def navigate(self, url: str) -> dict:
        """Navigate to URL."""
        await self._activate_current()
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

    # ─── Activate current tab ─────────────────────────────────────

    async def _activate_current(self) -> None:
        """Bring the currently connected tab to the foreground.

        Sends ``Target.activateTarget`` so Chrome wakes the tab and the
        user sees it being active.
        """
        if self._active_tab_id:
            try:
                await self._send_command("Target.activateTarget",
                                         {"targetId": self._active_tab_id})
                await asyncio.sleep(0.1)
            except Exception:
                pass  # Best-effort — tab might already be active

    # ─── Smart form fill ──────────────────────────────────────────

    async def smart_form_fill(self, fields: list[dict], timeout: int = 5) -> dict:
        """Fill form fields by label text — no CSS selectors needed.

        *fields* is a list of ``{"label": "...", "value": "..."}``.
        The method finds each field by label, placeholder, name, or
        aria-label, types the value, and returns per-field results.
        """
        await self._activate_current()
        js = r"""
(function() {
  const fields = """ + json.dumps(fields) + r""";
  const maxWait = """ + str(int(timeout * 1000)) + r""";
  const results = [];

  function findInput(label) {
    const low = label.toLowerCase().trim();

    // 1. Label → input via <label for=""> or <label> wrapping
    const labels = document.querySelectorAll("label");
    for (let lb of labels) {
      const lbl = (lb.textContent || "").toLowerCase().trim();
      if (!lbl.includes(low)) continue;

      // <label for="id">
      if (lb.getAttribute("for")) {
        const el = document.getElementById(lb.getAttribute("for"));
        if (el) return el;
      }
      // <label> wrapping <input>
      const wrapped = lb.querySelector("input, textarea, select");
      if (wrapped) return wrapped;
    }

    // 2. Placeholder match
    const byPlaceholder = document.querySelector(
      "input[placeholder*='" + CSS.escape(label) + "'], " +
      "textarea[placeholder*='" + CSS.escape(label) + "']"
    );
    if (byPlaceholder) return byPlaceholder;

    // 3. Name / aria-label match
    const byAttr = document.querySelector(
      "input[name*='" + CSS.escape(label) + "'], " +
      "input[aria-label*='" + CSS.escape(label) + "'], " +
      "textarea[name*='" + CSS.escape(label) + "'], " +
      "textarea[aria-label*='" + CSS.escape(label) + "']"
    );
    if (byAttr) return byAttr;

    // 4. Adjacent label (previous sibling or parent)
    const all = document.querySelectorAll("input, textarea");
    for (let el of all) {
      let prev = el.previousElementSibling;
      if (prev && (prev.textContent || "").toLowerCase().includes(low)) return el;
      let parent = el.parentElement;
      if (parent && (parent.textContent || "").toLowerCase().includes(low) &&
          parent.children.length < 4) return el;
    }

    return null;
  }

  const deadline = Date.now() + maxWait;
  fields.forEach(function(f) {
    try {
      const el = findInput(f.label);
      if (!el) {
        results.push({label: f.label, status: "error", error: "field not found"});
        return;
      }

      // Wait a bit for element to be interactive
      while (Date.now() < deadline) {
        if (el.offsetParent !== null) break;
      }

      el.focus();
      el.value = "";
      el.value = f.value;
      el.dispatchEvent(new Event("input", {bubbles: true}));
      el.dispatchEvent(new Event("change", {bubbles: true}));
      el.dispatchEvent(new Event("blur", {bubbles: true}));

      const tag = el.tagName.toLowerCase();
      const type = el.type || "";
      results.push({
        label: f.label,
        status: "ok",
        tag: tag,
        type: type,
        filled: f.value.substring(0, 50),
      });
    } catch(e) {
      results.push({label: f.label, status: "error", error: e.message});
    }
  });

  return JSON.stringify({fields_filled: results.length, results: results});
})();
"""
        result = await self.evaluate(js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed", "raw": str(raw)[:200]}
        return {"status": "ok", "fields": fields, "result": data}

    # ─── Wait for element ─────────────────────────────────────────

    async def wait_for_element(self, selector: str, timeout: int = 10,
                               visible: bool = True) -> dict:
        """Wait until an element matching *selector* appears in DOM.

        Polls every 200 ms. Returns the element's tag and text when found.
        """
        await self._activate_current()
        js = f"""
(async function() {{
  const deadline = Date.now() + {timeout * 1000};
  const poll = 200;
  while (Date.now() < deadline) {{
    const el = document.querySelector({json.dumps(selector)});
    if (el) {{
      const isVisible = el.offsetParent !== null;
      if (!{str(visible).lower()} || isVisible) {{
        return JSON.stringify({{
          status: "ok",
          tag: el.tagName,
          text: (el.textContent || "").trim().substring(0, 200),
          visible: isVisible,
          rect: {{w: el.offsetWidth, h: el.offsetHeight}}
        }});
      }}
    }}
    await new Promise(r => setTimeout(r, poll));
  }}
  return JSON.stringify({{status: "error", error: "timeout after " + {timeout} + "s"}});
}})();
"""
        result = await self.evaluate(js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed"}
        return {"status": "ok", "selector": selector, "timeout": timeout, "result": data}

    # ─── Click by text ────────────────────────────────────────────

    async def click_by_text(self, text: str, timeout: int = 5,
                            container_selector: str | None = None,
                            nth: int = 0) -> dict:
        """Click an element by its visible text content.

        Searches all visible ``a``, ``button``, ``input[type=submit]``,
        and ``[role=button]`` elements whose text matches. Clicks the
        first match using real CDP mouse events.

        If *container_selector* is given, restricts search to elements
        inside that CSS selector (e.g. "accept-modal" to only search
        within a modal).

        If *nth* is given (0-indexed), clicks the Nth matching element
        instead of the first. Useful for lists of identical buttons
        (e.g. "Edit", "Delete" in a table).
        """
        await self._activate_current()
        container_js = ""
        if container_selector:
            container_js = f"const container = document.querySelector({json.dumps(container_selector)}); if (!container) return JSON.stringify({{status: 'error', error: 'container not found: {json.dumps(container_selector)}'}});"
        js = f"""
(function() {{
{container_js}
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const deadline = Date.now() + {timeout * 1000};
  const nth = {nth};

  function findAll() {{
    const root = {('document' if not container_selector else 'container')};
    const results = [];
    const seen = new Set();

    // Priority: interactive elements
    const interactive = root.querySelectorAll(
      "a, button, input[type=submit], input[type=button], [role=button]"
    );
    for (let el of interactive) {{
      if (el.offsetParent === null) continue;
      const txt = (el.textContent || "").toLowerCase().trim();
      if (txt === low || txt.includes(low)) {{
        const key = txt + ":" + Math.round(el.getBoundingClientRect().x) + ":" + Math.round(el.getBoundingClientRect().y);
        if (!seen.has(key)) {{
          seen.add(key);
          results.push(el);
        }}
      }}
    }}

    // Fallback: clickable spans/divs
    if (results.length === 0) {{
      const all = root.querySelectorAll("[onclick], span, div");
      for (let el of all) {{
        if (el.offsetParent === null) continue;
        const txt = (el.textContent || "").toLowerCase().trim();
        if (txt === low) {{
          const key = txt + ":" + Math.round(el.getBoundingClientRect().x);
          if (!seen.has(key)) {{
            seen.add(key);
            results.push(el);
          }}
        }}
      }}
    }}

    return results;
  }}

  while (Date.now() < deadline) {{
    const matches = findAll();
    if (matches.length > nth) {{
      const el = matches[nth];
      el.scrollIntoView({{behavior: "instant", block: "center"}});
      const r = el.getBoundingClientRect();
      return JSON.stringify({{
        status: "ok",
        tag: el.tagName,
        text: (el.textContent || "").trim().substring(0, 100),
        x: r.x + r.width/2,
        y: r.y + r.height/2,
        w: r.width,
        h: r.height,
        match_index: nth,
        total_matches: matches.length,
      }});
    }}
  }}
  return JSON.stringify({{status: "error", error: "text not found: " + target.substring(0, 50) + " (nth=" + nth + ")"}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "parse failed"}
        if data.get("status") == "error":
            return data
        # Perform real CDP click at the position
        x, y = data.get("x", 0), data.get("y", 0)
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        data["cdp_click"] = True
        return {"status": "ok", "text": text, "result": data}

    # ─── NEW: Find element by text ────────────────────────────────

    async def find_element_by_text(self, text: str, tag: str | None = None,
                                    return_selector: bool = True) -> dict:
        """Find a visible element by its text content.

        Returns the element's position, CSS selector, and attributes.
        Does NOT click it — use click_by_text / click_label for that.

        *tag* restricts to a specific HTML tag (button, a, input, label, etc.).
        *return_selector* generates a unique CSS selector for the element.
        """
        await self._activate_current()
        tag_filter = ""
        if tag:
            tag_filter = f"el.tagName.toLowerCase() === {json.dumps(tag.lower())} &&"
        js = f"""
(function() {{
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const deadline = Date.now() + 5000;

  function getSelector(el) {{
    if (el.id) return "#" + CSS.escape(el.id);
    let path = [];
    let cur = el;
    while (cur && cur !== document.body) {{
      let tag = cur.tagName.toLowerCase();
      if (cur.id) {{ path.unshift("#" + CSS.escape(cur.id)); break; }}
      let parent = cur.parentElement;
      if (parent) {{
        let idx = 1;
        for (let sib of parent.children) {{
          if (sib === cur) break;
          if (sib.tagName === cur.tagName) idx++;
        }}
        tag += ":nth-child(" + idx + ")";
      }}
      path.unshift(tag);
      cur = parent;
    }}
    return path.join(" > ");
  }}

  while (Date.now() < deadline) {{
    const all = document.querySelectorAll("*");
    const results = [];
    for (let el of all) {{
      if (el.offsetParent === null) continue;
      if (!({tag_filter} true)) continue;
      const txt = (el.textContent || "").trim().toLowerCase();
      if (txt === low) {{
        const r = el.getBoundingClientRect();
        results.push({{
          tag: el.tagName,
          text: (el.textContent || "").trim().substring(0, 100),
          selector: getSelector(el),
          x: Math.round(r.x + r.width/2),
          y: Math.round(r.y + r.height/2),
          w: Math.round(r.width),
          h: Math.round(r.height),
          id: el.id || "",
          name: el.getAttribute("name") || "",
          type: el.type || "",
          href: el.getAttribute("href") || "",
          is_interactive: ["A","BUTTON","INPUT","SELECT","TEXTAREA","LABEL"].includes(el.tagName),
        }});
        if (results.length >= 10) break;
      }}
    }}
    if (results.length > 0) return JSON.stringify({{status: "ok", matches: results, count: results.length}});
  }}
  return JSON.stringify({{status: "error", error: "element not found: " + target.substring(0, 50)}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "parse failed"}
        return {"status": "ok", "text": text, "result": data}

    # ─── NEW: Click by label text (framework-safe) ────────────────

    async def click_label(self, text: str, timeout: int = 5) -> dict:
        """Click a <label> element whose text matches.

        Unlike click_by_text which clicks visible DIV/SPAN/BUTTON elements,
        this targets actual HTML <label> elements.  Framework forms
        (React, Vue, Symfony) only respond to real <label> clicks that
        toggle the associated input — plain element clicks don't register.

        Searches labels by priority:
        1. Exact match on <label> text
        2. Partial match (fallback)
        Automatically scrolls the label into view and uses real CDP
        mouse events so framework two-way binding fires correctly.
        """
        await self._activate_current()
        js = f"""
(function() {{
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const deadline = Date.now() + {timeout * 1000};

  function findLabel() {{
    while (Date.now() < deadline) {{
      const labels = document.querySelectorAll("label");
      let best = null, bestMatch = 0;
      for (let lb of labels) {{
        if (lb.offsetParent === null) continue;
        const txt = (lb.textContent || "").trim().toLowerCase();
        if (txt === low) {{ best = lb; bestMatch = 2; break; }}
        if (txt.includes(low) && bestMatch < 2) {{ best = lb; bestMatch = 1; }}
      }}
      if (best) return best;
    }}
    return null;
  }}

  const el = findLabel();
  if (!el) return JSON.stringify({{status: "error", error: "label not found: " + target.substring(0, 50)}});

  el.scrollIntoView({{behavior: "instant", block: "center"}});
  const r = el.getBoundingClientRect();
  // Click the label with real CDP mouse events (framework-safe)
  return JSON.stringify({{
    status: "ok",
    tag: "LABEL",
    text: (el.textContent || "").trim().substring(0, 100),
    forAttr: el.getAttribute("for") || "",
    x: r.x + r.width / 2,
    y: r.y + r.height / 2,
    w: r.width,
    h: r.height,
  }});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "parse failed"}
        if data.get("status") == "error":
            return data
        # Real CDP click
        x, y = data.get("x", 0), data.get("y", 0)
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await self._send_command("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        return {"status": "ok", "label": text, "result": data}

    async def click(self, selector: str) -> dict:
        """Click element by CSS selector via real CDP mouse events."""
        await self._activate_current()
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
        """Type text into an element found by CSS selector."""
        await self._activate_current()
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

    async def screenshot(self, quality: int = 0) -> dict:
        """Take viewport screenshot, return base64 JPEG.

        Quality: 0 = auto (adjusts based on page size), 1-100 = explicit.
        Auto-quality saves 30-50% bandwidth on simple pages.
        """
        if quality == 0:
            # Auto-quality: detect page complexity
            info = await self.evaluate(
                "(function(){return {textLen:(document.body?.innerText||'').length,"
                "imgs:document.images.length,els:document.querySelectorAll('*').length}})()"
            )
            r = info.get("result", {}) if info.get("status") == "ok" else {}
            el_count = r.get("els", 1000) if r else 1000
            # Simple page (few elements) → lower quality still looks good
            quality = 85 if el_count > 500 else 60
        result = await self._send_command("Page.captureScreenshot", {
            "format": "jpeg", "quality": min(quality, 95), "fromSurface": True,
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

    async def full_page_screenshot(self, quality: int = 0) -> dict:
        """
        Capture full-page screenshot by scrolling and stitching.

        Uses CDP to capture the full rendered page (everything scrollable).
        Quality: 0 = auto (adjusts based on page complexity).
        """
        if quality == 0:
            info = await self.evaluate(
                "document.querySelectorAll('*').length"
            )
            el_count = info.get("result", 1000) if info.get("status") == "ok" else 1000
            quality = 85 if el_count > 500 else 60
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

    async def element_screenshot(self, selector: str, quality: int = 0) -> dict:
        """Capture screenshot of a specific element.

        Quality: 0 = auto (adjusts based on element size).
        """
        if quality == 0:
            quality = 75  # default auto quality for elements
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

    async def pdf(self, options: dict | None = None) -> dict:
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

    # ─── NEW: File upload via CDP ──────────────────────────────────

    async def upload_files(self, selector: str, file_paths: list[str]) -> dict:
        """Upload files by setting the value of a file input element.

        *selector* is a CSS selector for ``<input type="file">``.
        *file_paths* are absolute paths to the files on the local machine.

        Uses the CDP ``DOM.setFileInputFiles`` method which bypasses the
        browser's file dialog — works even when the picker is hidden.
        """
        await self._activate_current()
        # Find the element node via Runtime
        find_js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (!el) return null;"
            f"  if (el.tagName !== 'INPUT' || (el.type !== 'file' && !el.getAttribute('capture')))"
            f"    return null;"
            f"  // Resolve backend node ID for CDP"
            f"  return 1;"
            f"}})()"
        )
        result = await self.evaluate(find_js)
        if result.get("status") == "error" or result.get("result") is None:
            return {"status": "error", "error": f"File input not found: {selector}"}

        # Get backend node ID from the element
        get_node_js = (
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  const backend = window.__backendNodeId;"
            f"  return 1;"
            f"}})()"
        )

        # Use DOM.querySelector to get the backend node ID
        doc_result = await self._send_command("DOM.getDocument", {"depth": 0})
        doc_node_id = doc_result.get("root", {}).get("nodeId", 0)

        query_result = await self._send_command("DOM.querySelector", {
            "nodeId": doc_node_id,
            "selector": selector,
        })
        node_id = query_result.get("nodeId", 0)
        if not node_id:
            return {"status": "error", "error": f"Element not found via DOM: {selector}"}

        # Set file input files using CDP
        await self._send_command("DOM.setFileInputFiles", {
            "nodeId": node_id,
            "files": file_paths,
        })

        # Fire change event for JS frameworks
        await self.evaluate(
            f"(function() {{"
            f"  const el = document.querySelector({json.dumps(selector)});"
            f"  if (el) el.dispatchEvent(new Event('change', {{bubbles: true}}));"
            f"}})()"
        )

        return {
            "status": "ok",
            "selector": selector,
            "files": file_paths,
            "count": len(file_paths),
        }

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

    async def dom_query(self, selector: str, attribute: str | None = None) -> dict:
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

        Each step: {"action": "...", "params": {...}}

        Supported actions: navigate, click, type, eval, screenshot,
        full_page_screenshot, element_screenshot, wait, wait_for_element,
        wait_text, wait_for_navigation, scroll, get_text, pdf,
        click_text, form_fill, analyze_page, close.
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
                elif action in ("wait", "sleep"):
                    await asyncio.sleep(params.get("ms", 1000) / 1000)
                    res = {"status": "ok", "waited_ms": params.get("ms", 1000)}
                elif action == "wait_for_element":
                    res = await self.wait_for_element(
                        params["selector"],
                        params.get("timeout", 10),
                        params.get("visible", True),
                    )
                elif action == "wait_text":
                    res = await self.wait_for_text(
                        params["text"],
                        params.get("timeout", 10),
                        params.get("present", True),
                    )
                elif action == "wait_for_navigation":
                    res = await self.wait_for_navigation(
                        params.get("timeout", 10),
                    )
                elif action == "scroll":
                    await self._scroll_by(params.get("x", 0), params.get("y", 0))
                    res = {"status": "ok", "x": params.get("x", 0), "y": params.get("y", 0)}
                elif action == "click_text":
                    res = await self.click_by_text(
                        params["text"],
                        params.get("timeout", 5),
                        params.get("container_selector", None),
                        params.get("nth", 0),
                    )
                elif action == "form_fill":
                    res = await self.smart_form_fill(
                        params["fields"],
                        params.get("timeout", 5),
                    )
                elif action == "analyze_page":
                    res = await self.analyze_page()
                elif action == "click_label":
                    res = await self.click_label(
                        params["text"],
                        params.get("timeout", 5),
                    )
                elif action == "wait_for_network_idle":
                    res = await self.wait_for_network_idle(
                        params.get("timeout", 10),
                        params.get("quiet_ms", 500),
                    )
                elif action == "page_diff":
                    res = await self.page_diff(
                        params.get("previous_snapshot"),
                    )
                elif action == "upload_files":
                    res = await self.upload_files(
                        params["selector"],
                        params["files"],
                    )
                elif action == "find_element":
                    res = await self.find_element_by_text(
                        params["text"],
                        params.get("tag"),
                    )
                elif action == "get_text":
                    res = await self.get_page_text()
                elif action == "pdf":
                    res = await self.pdf(params)
                elif action == "close":
                    await self.close()
                    res = {"status": "ok", "action": "close"}
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
            resp = await client.put(f"{self.cdp_http_url}/json/new?{quote(url)}")
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
        """Switch to a different tab by target ID.

        Auto-refreshes tab cache on stale-ID miss.
        """
        tabs = await self.discover_tabs()
        target = next((t for t in tabs if t["id"] == tab_id), None)
        if not target:
            # Cache miss — force fresh discovery and retry once
            self._tabs_cache = []
            self._tabs_cache_ts = 0
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

    # ─── Multi-tab scan (no tab switch needed) ─────────────────────

    async def get_tab_content_direct(self, target_id: str) -> dict:
        """Extract page text from any tab WITHOUT switching to it.

        Uses a temporary CDP WS connection to Runtime.evaluate
        directly on the target.  Much faster than switch + read.
        Returns partial data on timeout / error.
        """
        client = await self._get_http_client()
        try:
            resp = await client.get(f"{self.cdp_http_url}/json", timeout=5.0)
            all_targets = resp.json()
        except Exception as e:
            return {"status": "error", "error": f"fetch targets: {e}"}

        target = next((t for t in all_targets if t["id"] == target_id), None)
        if not target:
            return {"status": "error", "error": f"Target not found: {target_id}"}
        ws_url = target.get("webSocketDebuggerUrl", "")
        if not ws_url:
            return {"status": "error", "error": "No WS URL"}

        try:
            ws = await asyncio.wait_for(
                websockets.connect(ws_url, max_size=50 * 1024 * 1024, open_timeout=5),
                timeout=8,
            )
        except Exception as e:
            return {"status": "error", "error": f"WS connect: {e}", "target_id": target_id}

        mid = 1
        pending = {}

        async def _send(method, params=None):
            """Send a CDP command and wait for response."""
            nonlocal mid
            if params is None:
                params = {}
            f = asyncio.get_event_loop().create_future()
            pending[mid] = f
            try:
                await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
                mid += 1
                async with asyncio.timeout(6):
                    async for raw in ws:
                        r = json.loads(raw)
                        if r.get("id") in pending:
                            pending.pop(r["id"]).set_result(r)
                            break
                    return await asyncio.wait_for(f, timeout=5)
            except asyncio.TimeoutError:
                pending.pop(mid - 1, None)
                return {"error": "timeout", "method": method}
            except Exception as e:
                pending.pop(mid - 1, None)
                return {"error": str(e), "method": method}

        async def _eval(expr, timeout=6):
            """Evaluate JS and return result."""
            r = await _send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return r

        try:
            async with asyncio.timeout(12):
                # Step 1: Activate the target to wake it from discarding
                await _send("Target.activateTarget", {"targetId": target_id})

                # Step 2: Small delay for the tab to initialize
                await asyncio.sleep(0.3)

                # Step 3: Now evaluate JS
                t_res = await _eval("document.title")
                title = ""
                if isinstance(t_res, dict):
                    title = t_res.get("result", {}).get("result", {}).get("value", "")

                txt_res = await _eval("document.body ? document.body.innerText.substring(0,5000) : ''")
                page_text = ""
                if isinstance(txt_res, dict):
                    page_text = txt_res.get("result", {}).get("result", {}).get("value", "")

                url_res = await _eval("window.location.href")
                url = ""
                if isinstance(url_res, dict):
                    url = url_res.get("result", {}).get("result", {}).get("value", "")
        except asyncio.TimeoutError:
            try:
                await ws.close()
            except Exception:
                pass
            return {"status": "error", "error": "overall timeout", "target_id": target_id}
        except Exception as e:
            try:
                await ws.close()
            except Exception:
                pass
            return {"status": "error", "error": str(e), "target_id": target_id}
        finally:
            try:
                await ws.close()
            except Exception:
                pass

        return {
            "status": "ok",
            "target_id": target_id,
            "title": title[:200] or "",
            "url": url or "",
            "text": (page_text or "")[:5000],
            "text_length": len(page_text or ""),
        }

    async def scan_all_tabs(self, max_concurrent: int = 5) -> list[dict]:
        """Extract content from ALL open tabs WITHOUT switching active tab.

        Scans tabs in parallel (up to *max_concurrent* at a time).
        Each tab has a hard 12s timeout — unresponsive tabs are skipped.

        Returns structured data for every page tab — title, URL, text preview.
        """
        tabs = await self.discover_tabs()
        page_tabs = [t for t in tabs if t.get("type") == "page"]

        async def _scan_one(tab):
            try:
                async with asyncio.timeout(12):
                    content = await self.get_tab_content_direct(tab["id"])
            except Exception:
                content = {"status": "error", "error": "unexpected error", "target_id": tab["id"]}
            return {
                "id": tab["id"],
                "title": content.get("title", tab.get("title", "")),
                "url": content.get("url", tab.get("url", "")),
                "text_preview": (content.get("text") or "")[:500],
                "text_length": content.get("text_length", 0),
                "active": tab["id"] == self._active_tab_id,
                "scan_status": content.get("status", "error"),
            }

        # Run in batches to avoid overloading Chrome's WS endpoint
        results = []
        for i in range(0, len(page_tabs), max_concurrent):
            batch = page_tabs[i: i + max_concurrent]
            batch_results = await asyncio.gather(*[_scan_one(t) for t in batch])
            results.extend(batch_results)

        return results

    # ─── Page analysis: comprehensive page state ─────────────────
    async def analyze_page(self) -> dict:
        """Analyze the current page and return structured information.

        Returns URL, title, visible buttons (tag, text, position, disabled, in_modal),
        open modals (with buttons, tabs, state), form fields, and visible text.

        Replaces 3-4 separate eval calls with one comprehensive response.
        """
        await self._activate_current()
        js = r"""
(function() {
  const result = {};

  // Metadata
  result.url = window.location.href;
  result.title = document.title;

  // Visible buttons
  result.buttons = [];
  const interactive = document.querySelectorAll(
    "a, button, input[type=submit], input[type=button], [role=button]"
  );
  interactive.forEach(function(el) {
    if (el.offsetParent === null) return;
    const txt = (el.textContent || "").trim();
    if (!txt && !el.getAttribute("aria-label")) return;
    const r = el.getBoundingClientRect();
    const inModal = el.closest("[class*=modal], [class*=popup], [role=dialog]") !== null;
    result.buttons.push({
      tag: el.tagName,
      text: txt.substring(0, 100) || (el.getAttribute("aria-label") || "").substring(0, 100),
      x: Math.round(r.x + r.width/2),
      y: Math.round(r.y + r.height/2),
      w: Math.round(r.width),
      h: Math.round(r.height),
      disabled: el.disabled === true,
      in_modal: inModal,
    });
  });

  // Open modals
  result.modals = [];
  const modalEls = document.querySelectorAll(
    "[class*=modal][class*=in], [class*=modal].show, [role=dialog]:not([hidden])"
  );
  modalEls.forEach(function(m) {
    if (m.offsetParent === null && !m.classList.contains("in") && !m.classList.contains("show")) return;
    var info = {
      id: m.id || "",
      cls: m.className.substring(0, 80),
      buttons: [],
      tabs: [],
    };
    // Buttons inside modal
    m.querySelectorAll("button, a[role=button], input[type=submit]").forEach(function(b) {
      if (b.offsetParent === null) return;
      var bt = (b.textContent || "").trim() || (b.getAttribute("aria-label") || "");
      if (bt) info.buttons.push({text: bt.substring(0, 80), disabled: b.disabled === true});
    });
    // Tabs inside modal (tab-unread indicators)
    m.querySelectorAll("li").forEach(function(li) {
      var sp = li.querySelectorAll("span");
      if (sp.length >= 2) {
        info.tabs.push({
          name: (sp[0].textContent || "").trim(),
          has_unread: (sp[1].textContent || "").trim().length > 0,
        });
      }
    });
    info.modal_text = (m.textContent || "").trim().substring(0, 500);
    result.modals.push(info);
  });

  // Form fields — enhanced with label context + error detection
  result.form_fields = [];
  document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select").forEach(function(el) {
  if (el.offsetParent === null) return;
  var label = "";
  var id = el.id;
  if (id) {
    var lbl = document.querySelector("label[for='" + CSS.escape(id) + "']");
    if (lbl) label = (lbl.textContent || "").trim();
  }
  if (!label && el.parentElement) {
    var pl = el.parentElement.querySelector("label");
    if (pl) label = (pl.textContent || "").trim();
  }
  if (!label) label = el.getAttribute("placeholder") || el.getAttribute("aria-label") || el.name || "";

  // ── Section context: find the closest heading or bold text ──
  var section = "";
  var walk = el;
  for (var s = 0; s < 10; s++) {
    walk = walk.parentElement;
    if (!walk) break;
    var found = walk.querySelector("h1, h2, h3, h4, h5, h6, strong, b");
    if (found) { section = (found.textContent || "").trim().substring(0, 80); break; }
  }

  // ── Validation error detection ──
  var hasError = false;
  var errorText = "";
  // Check if the element has validation classes
  var cls = el.className;
  if (cls && (cls.indexOf("error") >= 0 || cls.indexOf("invalid") >= 0 || cls.indexOf("danger") >= 0)) {
    hasError = true;
  }
  // Check parent for error classes
  if (!hasError && walk) {
    var errorEl = walk.querySelector(".has-error, .error, .alert-danger, [class*=error], [class*=invalid], .help-block, .field-error, .form-error");
    if (errorEl) {
      hasError = true;
      errorText = (errorEl.textContent || "").trim().substring(0, 120);
    }
  }
  // Check for error text next to the field
  if (!hasError && el.nextElementSibling) {
    var ns = el.nextElementSibling;
    if (ns.className.indexOf("error") >= 0 || ns.className.indexOf("help") >= 0) {
      hasError = true;
      errorText = (ns.textContent || "").trim().substring(0, 120);
    }
  }

  result.form_fields.push({
    tag: el.tagName,
    type: el.type || "",
    name: el.name || "",
    label: label.substring(0, 80),
    value: (el.value || "").substring(0, 80),
    placeholder: (el.placeholder || "").substring(0, 40),
    section: section,
    required: el.required === true,
    checked: el.checked === true,
    has_error: hasError,
    error_text: errorText,
  });
  });

  // Alert / success / error messages
  result.alerts = [];
  document.querySelectorAll(
    ".alert, .alert-success, .alert-danger, .alert-error, .alert-info, .alert-warning, [class*=message], [class*=toast], [class*=notification]"
  ).forEach(function(a) {
    if (a.offsetParent === null) return;
    var t = (a.textContent || "").trim().substring(0, 300);
    if (t) result.alerts.push(t);
  });

  // Text summary
  result.text_preview = (document.body ? document.body.innerText.substring(0, 2000) : "");
  result.text_length = document.body ? (document.body.innerText || "").length : 0;

  return JSON.stringify(result);
})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed", "raw": str(raw)[:200]}
        return {"status": "ok", "page": data}

    # ─── Wait for text content ────────────────────────────────────
    async def wait_for_text(self, text: str, timeout: int = 10,
                            present: bool = True) -> dict:
        """Wait until *text* appears (or disappears) from the page.

        Polls every 300ms. Unlike wait_for_element (CSS selector based),
        this watches the visible text content of the page body.
        Use for SPAs where content updates without DOM element changes.
        """
        await self._activate_current()
        js = f"""
(async function() {{
  const target = {json.dumps(text)};
  const low = target.toLowerCase().trim();
  const present = {str(present).lower()};
  const deadline = Date.now() + {timeout * 1000};
  const poll = 300;

  while (Date.now() < deadline) {{
    const bodyText = (document.body ? document.body.innerText || "" : "").toLowerCase().trim();
    const found = bodyText.includes(low) || document.title.toLowerCase().includes(low);

    if (present && found) {{
      return JSON.stringify({{status: "ok", text: target.substring(0, 100), found: true}});
    }}

    if (!present && !found) {{
      return JSON.stringify({{status: "ok", text: target.substring(0, 100), disappeared: true}});
    }}

    await new Promise(r => setTimeout(r, poll));
  }}

  const msg = present
    ? "text not found after " + {timeout} + "s: " + target.substring(0, 50)
    : "text still present after " + {timeout} + "s: " + target.substring(0, 50);
  return JSON.stringify({{status: "error", error: msg}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed"}
        return {"status": "ok", "text": text, "timeout": timeout, "result": data}

    # ─── Wait for navigation (URL change) ─────────────────────────
    async def wait_for_navigation(self, timeout: int = 10) -> dict:
        """Wait until the page URL changes (SPA navigation).

        Stores the current URL on first call, then polls until it changes.
        Returns the new URL when detected.
        """
        await self._activate_current()
        current = await self.evaluate("window.location.href")
        old_url = current.get("result", "") or ""

        js = f"""
(async function() {{
  const oldUrl = {json.dumps(old_url)};
  const deadline = Date.now() + {timeout * 1000};
  const poll = 200;

  while (Date.now() < deadline) {{
    const newUrl = window.location.href;
    const newTitle = document.title;
    if (newUrl !== oldUrl) {{
      return JSON.stringify({{
        status: "ok",
        old_url: oldUrl,
        new_url: newUrl,
        title: newTitle,
      }});
    }}
    await new Promise(r => setTimeout(r, poll));
  }}

  return JSON.stringify({{status: "error", error: "URL did not change after " + {timeout} + "s"}});
}})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            data = {"error": "parse failed"}
        return {"status": "ok", "timeout": timeout, "result": data}

    # ─── Wait for network idle ────────────────────────────────────

    async def wait_for_network_idle(self, timeout: int = 10,
                                     quiet_ms: int = 500) -> dict:
        """Wait until no network requests have been made for *quiet_ms*.

        Useful after form submissions or button clicks that trigger
        async AJAX calls — ensures the next action won't race with
        in-flight requests.

        Polls CDP Network events.  Returns immediately if the network
        has been quiet for *quiet_ms*; raises timeout error otherwise.
        """
        await self._activate_current()
        # Enable Network domain if not already
        await self._send_command("Network.enable")
        # Keep track of in-flight requests
        requests = set()
        deadline = time.monotonic() + timeout

        # Listen for request/response events
        async def on_request(evt):
            req_id = evt.get("params", {}).get("requestId", "")
            if req_id:
                requests.add(req_id)
        async def on_response(evt):
            req_id = evt.get("params", {}).get("requestId", "")
            if req_id and req_id in requests:
                requests.remove(req_id)
        async def on_loading(evt):
            req_id = evt.get("params", {}).get("requestId", "")
            if req_id and req_id in requests:
                requests.remove(req_id)

        self._event_callbacks.setdefault("Network.requestWillBeSent", []).append(on_request)
        self._event_callbacks.setdefault("Network.responseReceived", []).append(on_response)
        self._event_callbacks.setdefault("Network.loadingFinished", []).append(on_loading)

        try:
            while time.monotonic() < deadline:
                if not requests:
                    # Network is quiet — wait *quiet_ms* to confirm
                    await asyncio.sleep(quiet_ms / 1000)
                    if not requests:
                        return {"status": "ok", "quiet_ms": quiet_ms,
                                "idle": True}
                await asyncio.sleep(0.1)
            return {"status": "ok", "quiet_ms": quiet_ms,
                    "idle": False, "pending": len(requests)}
        finally:
            # Clean up callbacks
            for cb_list in self._event_callbacks.values():
                for cb in (on_request, on_response, on_loading):
                    if cb in cb_list:
                        cb_list.remove(cb)

    # ─── Page diff: detect what changed after an action ────────────

    async def page_diff(self, previous_snapshot: dict | None = None) -> dict:
        """Compare current page state with a previous snapshot.

        Takes an optional *previous_snapshot* (from a prior analyze_page call).
        If omitted, returns the current snapshot as a baseline for future diff
        calls (call twice: first to get baseline, second to detect changes).

        Returns added/removed buttons, new modals, new errors, text changes,
        URL change, etc.  Designed for LLM consumption — tells the agent
        *what happened* without needing to re-analyze the whole page.
        """
        current = await self.analyze_page()
        if previous_snapshot is None:
            return {"status": "ok", "baseline": True, "snapshot": current}

        prev_page = previous_snapshot.get("page") or previous_snapshot
        curr_page = current.get("page") or current

        changes = {}

        # URL change
        old_url = prev_page.get("url", "")
        new_url = curr_page.get("url", "")
        if old_url != new_url:
            changes["url_changed"] = {"from": old_url, "to": new_url}

        # Button changes (by position + text)
        old_btns = {(b["x"], b["y"]): b["text"] for b in prev_page.get("buttons", [])}
        new_btns = {(b["x"], b["y"]): b["text"] for b in curr_page.get("buttons", [])}
        added = [{"text": t, "x": x, "y": y} for (x, y), t in new_btns.items()
                 if (x, y) not in old_btns]
        removed = [{"text": t, "x": x, "y": y} for (x, y), t in old_btns.items()
                   if (x, y) not in new_btns]
        if added:
            changes["buttons_added"] = added
        if removed:
            changes["buttons_removed"] = removed

        # Modal changes
        old_modals = [m["id"] for m in prev_page.get("modals", [])]
        new_modals = [m["id"] for m in curr_page.get("modals", [])]
        opened = [m for m in curr_page.get("modals", []) if m["id"] not in old_modals]
        closed = [m for m in prev_page.get("modals", []) if m["id"] not in new_modals]
        if opened:
            changes["modals_opened"] = opened
        if closed:
            changes["modals_closed"] = closed

        # Error changes
        old_errors = [f for f in prev_page.get("form_fields", []) if f.get("has_error")]
        new_errors = [f for f in curr_page.get("form_fields", []) if f.get("has_error")]
        old_err_count = len(old_errors)
        new_err_count = len(new_errors)
        if old_err_count != new_err_count:
            changes["errors_changed"] = {"before": old_err_count, "after": new_err_count}
            errs = [f for f in new_errors if f.get("error_text")]
            if errs:
                changes["current_errors"] = [f["error_text"] for f in errs[:5]]

        # Alert changes
        old_alerts = set(prev_page.get("alerts", []))
        new_alerts = set(curr_page.get("alerts", []))
        new_alert_msgs = list(new_alerts - old_alerts)
        if new_alert_msgs:
            changes["new_alerts"] = new_alert_msgs[:5]

        # Text length change
        old_len = prev_page.get("text_length", 0)
        new_len = curr_page.get("text_length", 0)
        if old_len != new_len:
            changes["text_length_changed"] = {"from": old_len, "to": new_len}

        if not changes:
            changes["no_changes"] = True

        return {"status": "ok", "changed": len(changes) > 0
                if "no_changes" not in changes else False,
                "changes": changes, "snapshot": current}

    # ─── Deep scan: extract all sub-tabs + iframes ────────────────

    async def deep_scan_tab(self, tab_id: str | None = None) -> dict:
        """Deep-extract ALL content from a tab: sub-tabs, iframes, meta.

        Switches to the tab, then runs a comprehensive JS that:
        - Detects all sub-tab navigation links (hash, data-tab, ARIA)
        - Clicks each one and captures the visible content
        - Extracts iframe content (same-origin) or marks cross-origin
        - Returns everything as structured JSON

        Pass tab_id=None to scan the currently active tab.
        """
        # Step 1: Activate + switch to the tab if specified
        await self._activate_current()
        if tab_id and tab_id != self._active_tab_id:
            await self.switch_tab(tab_id)
        await self._activate_current()  # Re-activate after switch

        # Step 2: Run deep scan JS
        js = r"""
(function() {
  const result = {};
  const MAX_TEXT = 3000;

  // ─── HELPER: collect visible text from a container ───
  function getText(el) {
    if (!el) return "";
    var t = el.innerText || el.textContent || "";
    return t.trim().substring(0, MAX_TEXT);
  }

  // ─── SUB-TAB DETECTION ───
  var tabSources = [];

  // Pattern 1: hash-based links (a[href^="#]"])
  document.querySelectorAll("a[href^='#']").forEach(function(a) {
    var hash = a.getAttribute("href").substring(1);
    if (hash && a.offsetParent !== null && a.textContent.trim()) {
      tabSources.push({el: a, hash: hash, label: a.textContent.trim().substring(0, 40)});
    }
  });

  // Pattern 2: data-tab attributes
  document.querySelectorAll("[data-tab]").forEach(function(el) {
    var tab = el.getAttribute("data-tab");
    if (tab && el.offsetParent !== null) {
      tabSources.push({el: el, hash: tab, label: el.textContent.trim().substring(0, 40) || tab});
    }
  });

  // Pattern 3: ARIA tabs
  document.querySelectorAll("[role=tab]").forEach(function(el) {
    var controls = el.getAttribute("aria-controls");
    if (controls && el.offsetParent !== null) {
      tabSources.push({el: el, hash: controls, label: el.textContent.trim().substring(0, 40)});
    }
  });

  // Deduplicate by label
  var seen = {};
  var tabs = [];
  tabSources.forEach(function(ts) {
    if (!seen[ts.label]) {
      seen[ts.label] = true;
      tabs.push(ts);
    }
  });

  // Limit to 15 tabs max
  if (tabs.length > 15) tabs = tabs.slice(0, 15);

  result._sub_tabs = [];
  tabs.forEach(function(tab) {
    try {
      tab.el.click();
      // Busy-wait up to 1500ms for content update
      var deadline = Date.now() + 1500;
      var content = "";
      var panel = null;
      while (Date.now() < deadline) {
        var p = document.getElementById(tab.hash);
        if (p && p.textContent.trim().length > 20) {
          panel = p;
          content = getText(p);
          break;
        }
        var ap = document.querySelector("[role=tabpanel]:not([hidden])");
        if (ap && ap.textContent.trim().length > 30) {
          panel = ap;
          content = getText(ap);
          break;
        }
        var tc = document.querySelector(".tab-content.active, .tab-pane.active, [class*='tab-pane'][class*='active']");
        if (tc && tc.textContent.trim().length > 30) {
          panel = tc;
          content = getText(tc);
          break;
        }
      }
      if (!content) {
        content = getText(document.body);
      }
      result._sub_tabs.push({
        label: tab.label,
        content: content.substring(0, MAX_TEXT),
        len: content.length
      });
    } catch(e) {
      result._sub_tabs.push({label: tab.label, error: e.message});
    }
  });

  // ─── IFRAMES ───
  result._iframes = [];
  document.querySelectorAll("iframe").forEach(function(f, i) {
    try {
      var doc = f.contentDocument || (f.contentWindow ? f.contentWindow.document : null);
      var txt = "";
      var title = "";
      if (doc) {
        txt = (doc.body ? doc.body.innerText : "").substring(0, 1000);
        title = doc.title || "";
      }
      result._iframes.push({
        idx: i, src: f.src || "", id: f.id || "",
        w: f.offsetWidth, h: f.offsetHeight,
        title: title, text_preview: txt.substring(0, 300),
        text_len: txt.length,
        accessible: !!doc
      });
    } catch(e) {
      result._iframes.push({
        idx: i, src: f.src || "", id: f.id || "",
        w: f.offsetWidth, h: f.offsetHeight,
        accessible: false, error: "cross-origin"
      });
    }
  });

  // ─── CURRENT STATE ───
  var allLinks = document.querySelectorAll("a, button, [role=tab]");
  var interactive = [];
  allLinks.forEach(function(el) {
    if (el.offsetParent !== null && el.textContent.trim()) {
      var tag = el.tagName.toLowerCase();
      var txt = el.textContent.trim().substring(0, 40);
      interactive.push(tag + ":" + txt);
    }
  });

  result._meta = {
    title: document.title,
    url: window.location.href,
    tabsFound: tabs.length,
    tabsExtracted: result._sub_tabs.length,
    iframesFound: document.querySelectorAll("iframe").length,
    interactiveElements: interactive.length,
    readyState: document.readyState
  };

  return JSON.stringify(result);
})();
"""
        eval_result = await self.evaluate(js)
        raw = eval_result.get("result", "{}") if isinstance(eval_result, dict) else "{}"

        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "JS parse failed", "raw": str(raw)[:500]}

        return {
            "status": "ok",
            "tab_id": tab_id or self._active_tab_id,
            "meta": data.get("_meta", {}),
            "sub_tabs": data.get("_sub_tabs", []),
            "iframes": data.get("_iframes", []),
            "interactive": data.get("_meta", {}).get("interactiveElements", 0),
        }

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
        """Close CDP connection and clean up resources."""
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
        # Fail all pending futures with CDPDisconnectedError
        exc = CDPDisconnectedError("Connection closed")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()
        self._tabs_cache = []
        self._tabs_cache_ts = 0
        # Close shared HTTP client
        if self._http_client and not self._http_client.is_closed:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None
        return {"status": "ok"}
        self._target_id = None

    # ─── Reconnect / retry ────────────────────────────────────────

    MAX_RECONNECT_ATTEMPTS = 3
    RECONNECT_BASE_DELAY = 1.0  # seconds

    async def _reconnect_with_backoff(self) -> dict:
        """Attempt to reconnect up to *MAX_RECONNECT_ATTEMPTS* times with
        exponential backoff.

        Returns:
            The connect result dict on success.

        Raises:
            CDPDisconnectedError: If all attempts fail.
        """
        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_RECONNECT_ATTEMPTS + 1):
            try:
                return await self.connect()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.MAX_RECONNECT_ATTEMPTS:
                    delay = self.RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                    logger.info(
                        "Reconnect attempt %d/%d failed, retrying in %.1fs…",
                        attempt, self.MAX_RECONNECT_ATTEMPTS, delay,
                    )
                    await asyncio.sleep(delay)
        raise CDPDisconnectedError(
            f"Reconnect failed after {self.MAX_RECONNECT_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    async def _run_with_reconnect(self, method, *args, **kwargs) -> dict:
        """Run a CDP operation, automatically reconnecting on disconnect.

        If the operation raises ``CDPDisconnectedError``, attempts to
        reconnect via ``_reconnect_with_backoff`` and retries once.
        """
        try:
            result = await method(*args, **kwargs)
            return result
        except CDPDisconnectedError:
            await self._reconnect_with_backoff()
            return await method(*args, **kwargs)
