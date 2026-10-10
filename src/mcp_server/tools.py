"""Browser tool handlers — direct engine calls (spec §5.1–§5.8).

One explicit typed ``async def`` handler per browser tool. Each wraps
``main.run_op(...)`` / ``main.client.*`` directly — never HTTP, never an LLM
(decision D2, anti-LLM gate §8.2). Returns a JSON string with the REST
envelope shape built by :mod:`mcp_server.serialization`.

The engine singletons (``main.client``, ``main.run_op``, ``main._session_mgr``)
are imported lazily inside each handler body so importing this module never
pulls the heavy FastAPI engine stack, and so tests can patch ``main.run_op``
by attribute.

Per-client sessions: the MCP server has no HTTP cookie jar, so the first
browser-touching call mints one session (own tab) and reuses it for the life
of the process.  Keeps MCP tool calls on one dedicated tab instead of
spamming a new tab per call.
"""

from __future__ import annotations

import asyncio
import functools
import json as _json_mod
import logging
import os
import re
from typing import Any

from mcp.server.fastmcp import Context  # typing only — never called here

from .serialization import json_dumps, tool_error, tool_result

# Process-scoped session holder for MCP calls (no cookies over stdio).
_MCP_SESSION = {"session": None}


logger = logging.getLogger(__name__)


def _not_found(inner: dict) -> bool:
    """True when an engine result says the target element is not on the page yet."""
    if inner.get("status") != "error":
        return False
    err = str(inner.get("error", "")).lower()
    return "not found" in err or "no element" in err


async def _await_element(target, selector: str, timeout: float = 5.0) -> None:
    """Wait up to *timeout* seconds for a visible element matching *selector* (best effort)."""
    try:
        await target.wait_for_element(selector, int(timeout), True)
    except Exception as exc:  # noqa: BLE001 — the retry reports the real outcome
        logger.debug("auto-wait for %s failed: %s", selector, exc)


async def _session_tab_alive(sess) -> bool:
    """True while the MCP session's own page tab is still open in the browser."""
    # Bypass the 5 s tab-list cache: a tab closed a moment ago must read as gone.
    sess.client._tabs_cache = []
    sess.client._tabs_cache_ts = 0
    try:
        tabs = await sess.client.discover_tabs()
    except Exception:  # noqa: BLE001 — browser unreachable: let the normal path report it
        return True
    listed = any(tab.get("id") == sess.tab_id and tab.get("type") == "page" for tab in tabs)
    if not listed:
        return False
    # Listed is not the same as alive: Chrome can discard a background tab (Memory Saver)
    # and leave it in the list while it no longer answers. Probe it, at most every 5 s.
    import time as _time

    now = _time.monotonic()
    if now - getattr(sess, "_alive_checked_at", 0.0) < 5.0:
        return True
    try:
        await asyncio.wait_for(sess.client._send_command(
            "Runtime.evaluate", {"expression": "1", "returnByValue": True}), timeout=3.0)
    except Exception:  # noqa: BLE001 — no answer means the tab is gone for our purposes
        return False
    sess._alive_checked_at = now
    return True


async def _mcp_session():
    """Return (sess, run_op) for an MCP tool call, minting the session once.

    Falls back to (None, run_op) — the shared default client — when the
    browser is unavailable (legacy behaviour).
    """
    from main import _set_current_session, run_op, session_registry

    # Test isolation: BH_TEST_NO_CHROME=1 (set by the MCP integration test
    # harness) forbids launching a real browser from the server subprocess.
    # Fall straight back to the default (disconnected) client so CDP-gated
    # tools fail deterministically with the "not connected" error.
    if os.environ.get("BH_TEST_NO_CHROME") == "1":
        _set_current_session(None)
        return None, run_op

    sess = _MCP_SESSION["session"]
    if sess is not None and sess.session_id in session_registry._sessions and await _session_tab_alive(sess):
        _set_current_session(sess)
        return sess, (lambda op, method, *a, **kw: run_op(op, method, *a, sess_override=sess, **kw))
    if sess is not None:
        # The session's own tab is gone (closed by a person, or by a page that closed
        # it). Drop the session so the next call mints a fresh tab, instead of failing
        # with a stale tab id. The new id is reported by session_status.
        _MCP_SESSION["session"] = None
        _MCP_SESSION["replaced"] = _MCP_SESSION.get("replaced", 0) + 1
        try:
            await session_registry.destroy(sess.session_id)
        except Exception as exc:  # noqa: BLE001 — the old tab may already be gone
            logger.debug("dropping lost MCP session failed: %s", exc)
        # Mint the replacement now: the shared default client may already be detached
        # from the closed tab, and a call that falls back to it would fail.
        try:
            from main import _local_cdp_http, chrome_mgr

            await chrome_mgr.launch()
            fresh = await session_registry.create(_local_cdp_http())
            _MCP_SESSION["session"] = fresh
            _set_current_session(fresh)
            return fresh, (lambda op, method, *a, **kw: run_op(op, method, *a, sess_override=fresh, **kw))
        except Exception as exc:  # noqa: BLE001 — fall through to lazy minting on the next call
            logger.warning("could not mint a replacement MCP session: %s", exc)
    # P0-1: MCP stdio has no HTTP middleware — force auto-mint so the first
    # browser tool never 400s with "Missing session". Mirrors BH_SESSION_AUTO=1.
    try:
        from main import _session_auto as _mcp_auto
        _mcp_auto.set(True)
    except Exception as skip_exc:  # noqa: BLE001 — the engine import is optional here; the session still mints without the flag
        logger.debug("best-effort auto-session flag failed: %s", skip_exc)
    # No session cached yet — let run_op mint it lazily on the first browser
    # op (it launches Chrome and waits for the warm-up itself, avoiding the
    # double-launch race). session_hook caches the minted session so every
    # later tool call reuses the same tab instead of piling up new ones.
    def _cache_sess(s):
        _MCP_SESSION["session"] = s

    return None, (lambda op, method, *a, **kw: run_op(op, method, *a, session_hook=_cache_sess, **kw))


async def _tab_pinned_client(tab_id: str):
    """Return a CDPClient bound to *tab_id*, or a tool_error string.

    MCP-side twin of main._tab_client_for: dedupes onto the MCP session's own
    client when it already sits on the tab, else binds a cached throwaway
    client via connect_to_target (background attach, no focus steal).
    Unknown/unreachable tab → tool_error envelope naming the live tabs.
    """
    import json as _json

    from main import (
        _SENTINEL_SESSION,  # noqa: F401 — re-exported contract marker
        _assert_tab_exists,
        _tab_client_for,
    )

    ok = await _assert_tab_exists(tab_id)
    if ok is not True:
        # ok is an api_error JSONResponse — surface its message as tool_error
        try:
            body = _json.loads(bytes(ok.body).decode())
            detail = body.get("error", {}).get("message", "tab not found")
        except Exception:  # noqa: BLE001
            detail = f"Tab not found: {tab_id}"
        return tool_error("tab_id", "tab_not_found", detail)
    try:
        sess = _MCP_SESSION.get("session")
        return await _tab_client_for(tab_id, sess)
    except Exception as exc:  # noqa: BLE001
        return tool_error("tab_id", "attach_failed", f"Cannot attach to tab {tab_id}: {exc}")


async def _target():
    """Return (client_obj, run_op) for a handler — session client or default."""
    from main import client

    sess, run_op = await _mcp_session()
    return (sess.client if sess is not None else client), run_op


async def navigate(url: str, wait_until: str = "domcontentloaded", timeout: float = 15.0,
                   wait_for: str | None = None, ctx: Context | None = None) -> str:
    """Navigate the active browser tab to *url* (capability ``browser.core``, READY).

    Waits until the page reaches ``wait_until`` (``commit``, ``domcontentloaded``
    or ``load``) and returns the ready state. A page that does not get there
    within ``timeout`` seconds is an error, not a success.

    ``wait_for`` waits for content the page renders after load (single-page apps,
    dev servers): a CSS selector such as ``"#app .product"``, or ``"text:Welcome"``
    for visible text. If it does not appear within ``timeout`` the call is an error.

    Backed by the same engine as ``POST /navigate``.
    """
    if ctx is not None:
        await ctx.info(f"navigate -> {url} (wait_until={wait_until})")
    allowlist = _origin_allowlist()
    if allowlist is not None and not _origin_allowed(url, allowlist):
        return tool_error("navigate", "origin_not_allowed",
                          f"{url} is not in BH_ALLOWED_ORIGINS; allowed: {', '.join(allowlist)}")
    target, run_op = await _target()
    res = await run_op("navigate", target.navigate, url, wait_until=wait_until, timeout=timeout)
    if not wait_for or not isinstance(res, dict) or res.get("status") != "ok":
        return json_dumps(_redact_urls(res))
    if wait_for.startswith("text:"):
        waited = await run_op("navigate_wait_for", target.wait_for_text, wait_for[5:], int(timeout))
    else:
        waited = await run_op("navigate_wait_for", target.wait_for_element, wait_for, int(timeout), True)
    inner = (waited.get("data") or {}).get("result") if isinstance(waited, dict) else None
    if not (isinstance(inner, dict) and inner.get("status") == "ok") and not (
        isinstance(inner, dict) and inner.get("found") is True
    ):
        return tool_error("navigate", "wait_for_timeout",
                          f"{wait_for!r} did not appear within {timeout:g}s after the page loaded")
    res.setdefault("data", {})
    if isinstance(res["data"], dict):
        res["data"]["waited_for"] = wait_for
    return json_dumps(_redact_urls(res))


async def click(selector: str, expect: dict | None = None, ctx: Context | None = None) -> str:
    """Click a CSS selector in the active tab (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /click``. With ``expect`` the click goes
    through ``act`` so the result carries ``data.verification`` (see ``act``).
    """
    if ctx is not None:
        await ctx.info(f"click -> {selector}")
    if expect is not None:
        return await act("click", selector=selector, expect=expect, ctx=ctx)
    target, run_op = await _target()
    result = await run_op("click", target.click, selector)
    if isinstance(result, dict) and isinstance(result.get("data"), dict) and _not_found(result["data"]):
        await _await_element(target, selector)  # auto-wait, then one retry
        result = await run_op("click", target.click, selector)
    # Unwrap the run_op envelope: the inner data.status can be "error" even
    # though the envelope is "ok" — turn "Element not found" into a useful
    # tool result instead of a misleading success JSON.
    inner = result.get("data") if isinstance(result, dict) else None
    if isinstance(inner, dict) and inner.get("status") == "error":
        err = str(inner.get("error", ""))
        if "not found" in err.lower() or "no element" in err.lower():
            return tool_error("click", "element_not_found",
                              f"Element not found for selector {selector!r} on the current tab")
    return json_dumps(result)


async def type(selector: str, text: str, ctx: Context | None = None) -> str:
    """Type *text* into the element matched by *selector* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /type``.
    """
    if ctx is not None:
        await ctx.info(f"type {len(text)} chars into {selector}")
    target, run_op = await _target()
    result = await run_op("type", target.type_text, selector, text)
    inner = result.get("data") if isinstance(result, dict) else None
    if isinstance(inner, dict) and inner.get("status") == "error" and _not_found(inner):
        # Auto-wait: the field may still be rendering. Wait for it, then try once more.
        await _await_element(target, selector)
        result = await run_op("type", target.type_text, selector, text)
        inner = result.get("data") if isinstance(result, dict) else None
    if isinstance(inner, dict) and inner.get("status") == "error":
        err = str(inner.get("error", ""))
        if "not found" in err.lower() or "no element" in err.lower():
            return tool_error("type", "element_not_found",
                              f"Element not found for selector {selector!r} on the current tab")
    return json_dumps(result)


async def screenshot(ctx: Context | None = None) -> str:
    """Capture a JPEG screenshot of the active tab (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /screenshot``.
    """
    if ctx is not None:
        await ctx.info("capturing screenshot")
    target, run_op = await _target()
    return json_dumps(await run_op("screenshot", target.screenshot))


async def snapshot(ctx: Context | None = None) -> str:
    """Return a comprehensive page analysis (capability ``agent.semantic``, READY).

    Backed by the same engine as ``POST /page/analyze``.
    """
    if ctx is not None:
        await ctx.info("analyzing page")
    target, run_op = await _target()
    return json_dumps(await run_op("page_analyze", target.analyze_page))


async def observe(
    mode: str = "semantic",
    scope: str = "page",
    max_nodes: int = 250,
    interactive_only: bool = False,
    include_hidden: bool = False,
    condensed: bool = True,
    tab_id: str | None = None,
    include_network: bool = False,
    include_screenshot: bool = False,
    store_screenshot: bool = False,
    exclude_urls: list[str] | None = None,
    since_snapshot_id: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Observe the page as accessibility tree or semantic snapshot (capability ``agent.semantic``, READY).

    Backed by the same engine as ``POST /agent/observe``.

    Pass ``tab_id`` (from ``get_tabs``) to observe a DIFFERENT tab than the
    session's own — no context switch, so the observation can never return
    about:blank while the target tab is loaded.

    ``include_network`` / ``include_screenshot`` bundle page evidence into the
    observation; ``exclude_urls`` drops harness-internal traffic from the log
    and ``store_screenshot`` persists the shot as an artifact (P2, v1.36).
    """
    if ctx is not None:
        await ctx.info(f"observe mode={mode} scope={scope} tab_id={tab_id or 'session'}")
    # Use internal snapshot functions directly (same as REST endpoint)
    from main import (
        _capture_accessibility_snapshot,
        _capture_agent_snapshot,
        _set_current_session,
        artifact_store,
        paginate_snapshot,
    )

    _sess, _run_op = await _mcp_session()  # local function
    # 2026-09-02 heal fix: health-check via run_op before snapshot capture
    if _sess is not None:
        try:
            await _run_op("observe_heal_ping", _sess.client.get_tabs)
        except Exception as skip_exc:  # noqa: BLE001
            logger.debug("best-effort observe heal ping failed: %s", skip_exc)
    _set_current_session(_sess)

    try:
        target = _sess.client if _sess else None
        if tab_id:
            pinned = await _tab_pinned_client(tab_id)
            if isinstance(pinned, str):
                return pinned  # tool_error envelope (unknown tab / unreachable)
            target = pinned
        if mode.lower() in {"accessibility", "ax"}:
            snap = await _capture_accessibility_snapshot(
                scope=scope,
                include=None, interactive_only=interactive_only,
                include_hidden=include_hidden,
                target=target,
            )
            data = snap.as_dict(max_nodes=min(max(max_nodes, 1), 1000))
        else:
            snap = await _capture_agent_snapshot(condensed, target=target)
            data = paginate_snapshot(snap, 6000, max_nodes, None)
        if include_network and target is not None:
            try:
                await target.start_network_monitoring()
            except Exception as skip_exc:  # noqa: BLE001
                logger.debug("best-effort start network monitoring (observe) failed: %s", skip_exc)
            try:
                nlog = await target.get_network_log()
                entries = nlog.get("entries", []) if isinstance(nlog, dict) else []
            except Exception:  # noqa: BLE001
                entries = []
            if exclude_urls:
                entries = [e for e in entries
                           if not any(x in str(e.get("url", "")) for x in exclude_urls)]
            failures = [e for e in entries if isinstance(e.get("status"), int) and e["status"] >= 400]
            data["network"] = {"count": len(entries), "entries": entries[-100:],
                               "failures": failures[-20:], "failure_count": len(failures)}
        if include_screenshot and target is not None:
            try:
                shot = await target.screenshot(quality=60)
                data["screenshot"] = {"format": shot.get("format", "jpeg"),
                                      "size": shot.get("size", 0)}
                if store_screenshot and shot.get("data"):
                    import base64 as _b64

                    _art = artifact_store.put(
                        _b64.b64decode(shot["data"]), "image/jpeg", ".jpg",
                        {"source": "mcp_observe"},
                    )
                    data["screenshot"]["artifact_id"] = _art.get("artifact_id")
                    data["screenshot"]["artifact_url"] = f"/artifacts/{_art.get('artifact_id')}"
            except Exception as exc:  # noqa: BLE001
                data["screenshot"] = {"error": str(exc)}
        if since_snapshot_id:
            # Diff against an earlier observation of this session: lists what changed,
            # so an agent does not re-read a whole page after each action.
            diff = _observe_diff(mode, since_snapshot_id, snap)
            if diff is None:
                return tool_error("observe", "stale_snapshot",
                                  f"snapshot {since_snapshot_id!r} is missing or expired; observe again")
            data["diff"] = diff
        return tool_result("observe", _redact_urls(data))
    except Exception as exc:  # noqa: BLE001
        return tool_error("observe", "operation_failed", str(exc))


async def act(
    action: str,
    snapshot_id: str | None = None,
    ref: str | None = None,
    element_id: str | None = None,
    selector: str | None = None,
    text: str | None = None,
    label: str | None = None,
    url: str | None = None,
    value: str | None = None,
    fields: list[dict] | None = None,
    option: str | None = None,
    timeout: int = 10,
    expression: str | None = None,
    expect: dict | None = None,
    ctx: Context | None = None,
) -> str:
    """Act on the page: click, fill, select, wait, navigate (capability ``agent.semantic``, READY).

    Backed by the same engine as ``POST /agent/act``. Use with observe's snapshot_id/ref.
    """
    if ctx is not None:
        await ctx.info(f"act -> {action}")
    import json as _json

    from pydantic import ValidationError
    from starlette.requests import Request as _Request

    from main import AgentActionRequest, _set_current_session, agent_act

    # Same engine, same process: call the REST handler in-process instead of
    # a loopback HTTP request to a hard-coded port (which pointed at another
    # running instance and could not see this process's snapshot ids).
    _sess, _ = await _mcp_session()
    _set_current_session(_sess)
    target: dict = {
        k: v for k, v in {
            "snapshot_id": snapshot_id, "ref": ref, "element_id": element_id,
            "selector": selector, "text": text, "label": label, "url": url, "value": value,
        }.items() if v is not None
    }
    payload: dict = {"action": action}
    if target:
        payload["target"] = target
    # Only set fields are sent: explicit nulls are rejected by the REST schema.
    for k, v in (("url", url), ("value", value), ("fields", fields), ("option", option),
                 ("timeout", timeout), ("expression", expression), ("expect", expect)):
        if v is not None:
            payload[k] = v
    try:
        model = AgentActionRequest(**payload)
    except ValidationError as exc:
        return tool_error("act", "invalid_request", str(exc))

    raw = _json.dumps(payload).encode()

    async def _receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    request = _Request(
        {"type": "http", "method": "POST", "path": "/agent/act",
         "headers": [(b"content-type", b"application/json")]},
        _receive,
    )
    try:
        resp = await agent_act(request, model)
    except Exception as exc:  # noqa: BLE001 — e.g. 400 Missing session: report it in the envelope
        return tool_error("act", "operation_failed", str(exc))
    if isinstance(resp, dict):
        return tool_result("act", resp.get("data", {}))
    # Error responses come back as JSONResponse: surface the engine's code and message.
    body = _json.loads(bytes(resp.body) or b"{}")
    err = body.get("error") or {}
    if isinstance(err, str):
        err = {"code": "operation_failed", "message": err}
    return tool_error("act", err.get("code") or "operation_failed",
                      err.get("message") or str(body.get("detail") or body))


async def get_tabs(ctx: Context | None = None) -> str:
    """List all open tabs ``{id, title, url, active}`` (capability ``browser.core``, READY).

    Backed by the same engine as ``GET /tabs``.
    """
    if ctx is not None:
        await ctx.info("listing tabs")
    target, run_op = await _target()
    return json_dumps(_redact_urls(await run_op("get_tabs", target.get_tabs)))


async def switch_tab(id: str, ctx: Context | None = None) -> str:
    """Switch the active tab to *id* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /switch_tab/{tab_id}``.
    """
    if ctx is not None:
        await ctx.info(f"switch_tab -> {id}")
    target, run_op = await _target()
    return json_dumps(await run_op("switch_tab", target.switch_tab, id))


async def close_tab(id: str, ctx: Context | None = None) -> str:
    """Close the tab *id* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /tab/close/{tab_id}``.
    """
    if ctx is not None:
        await ctx.info(f"close_tab -> {id}")
    target, run_op = await _target()
    return json_dumps(await run_op("close_tab", target.close_tab, id))


async def session_status(ctx: Context | None = None) -> str:
    """Return session persistence status (capability ``diagnostics.privacy``, READY).

    Reads ``_session_mgr.list_sessions()`` directly — no CDP dependency; does
    NOT route through ``run_op`` (spec §5.8). Built with the local envelope
    helper, not ``main.api_success`` (no JSONResponse involved).
    """
    from main import _session_mgr  # lazy import — engine singleton

    if ctx is not None:
        await ctx.info("reading session persistence status")
    try:
        sessions = _session_mgr.list_sessions()
        own = _MCP_SESSION.get("session")
        return tool_result(
            "session_status",
            {
                "sessions": sessions,
                "total": len(sessions),
                # This MCP client's own tab; None until the first browser call.
                "mcp_tab_id": own.tab_id if own is not None else None,
                # How many times the own tab was lost and replaced by a fresh one.
                "mcp_tab_replaced": _MCP_SESSION.get("replaced", 0),
                # Which Chrome profile this server drives, and whether it is the user's own.
                "browser_profile": _browser_profile_info(),
                # A hand-off waiting for a person (await_user), or None.
                "handoff_pending": _MCP_SESSION.get("handoff"),
                # Emulation that stays on the page until cleared: viewport, geolocation, offline.
                "emulation": dict(_MCP_SESSION.get("emulation", {})),
            },
        )
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return tool_error("session_status", "operation_failed", str(exc))


async def mcp_export_cookies(session_id: str, ctx: Context | None = None) -> str:
    """Export every cookie for *session_id* as JSON text (capability ``diagnostics.cookies``, READY).

    Backed by the same engine as ``POST /session/{sid}/export-cookies``:
    resolves the session's CDP client and returns ``Network.getAllCookies``
    results with the stable keys ``name``, ``value``, ``domain``, ``path``,
    ``expires``, ``httpOnly``, ``secure``, ``sameSite``.
    """
    if ctx is not None:
        await ctx.info(f"export_cookies -> session {session_id}")
    try:
        from services.cookie_service import export_cookies

        result = await export_cookies(session_id)
        return tool_result("export_cookies", result)
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return tool_error("export_cookies", "operation_failed", str(exc))


# ── High-level tools (capability agent.search / agent.flow) ────────


async def search(query: str, engine: str = "google", timeout: int = 45,
                 ctx: Context | None = None) -> str:
    """One-call web search (capability ``agent.search``, READY).

    Navigates to the engine, runs *query*, waits for the answer, and returns
    the result text — no manual sleeps or extra reads.

    Engines: ``google`` (default, fastest — works since stealth v1.24),
    ``perplexity`` (AI answer, slower ~45s), ``ddg``, ``bing``.
    """
    from main import AgentSearchRequest, agent_search  # lazy import

    if ctx is not None:
        await ctx.info(f"search {engine}: {query[:60]}")
    await _mcp_session()  # the engine reads the session from context: set it for this call
    try:
        resp = await agent_search(AgentSearchRequest(query=query, engine=engine, timeout=timeout))
    except Exception as exc:  # noqa: BLE001 — every failure becomes an envelope
        return tool_error("search", "operation_failed", str(exc))
    return json_dumps(resp)


async def get_content(url: str | None = None, wait_ready: bool = True,
                      ctx: Context | None = None) -> str:
    """Load a URL (or use the current page) and return its main content
    (capability ``agent.search``, READY).

    Filters nav/sidebar/footer noise — cleaner context for LLMs.
    """
    from main import client  # lazy import

    if ctx is not None:
        await ctx.info(f"get_content url={url}")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    if url:
        await run_op_fn("get_content_navigate", target.navigate, url)
        if wait_ready:
            await run_op_fn("get_content_wait", target.wait_for_ready, 20)
    content = await target.get_main_content()
    return json_dumps({"status": "ok", "operation": "get_content",
                       "data": content, "error": None, "meta": {}})


async def run_flow(steps: list[dict], name: str = "flow", stop_on_error: bool = True,
                   ctx: Context | None = None) -> str:
    """Run an ordered E2E test flow (capability ``agent.flow``, READY).

    Each step: navigate / click_text / click / type / submit / wait_text /
    wait / eval.  Returns a per-step report.
    """
    from main import AgentFlowRequest, AgentFlowStep, agent_run_flow  # lazy import

    if ctx is not None:
        await ctx.info(f"run_flow {name} ({len(steps or [])} steps)")
    steps = steps or []
    if not steps:
        return tool_error("run_flow", "invalid_params", "steps is required")
    try:
        req = AgentFlowRequest(
            name=name,
            steps=[AgentFlowStep(**s) for s in steps],
            stop_on_error=stop_on_error,
        )
    except (TypeError, ValueError) as exc:
        return tool_error("run_flow", "invalid_params", f"a step is malformed: {exc}")
    await _mcp_session()  # the engine reads the session from context: set it for this call
    try:
        resp = await agent_run_flow(req)
    except Exception as exc:  # noqa: BLE001 — every failure becomes an envelope
        return tool_error("run_flow", "operation_failed", str(exc))
    return json_dumps(resp)


# ── Auth-session clone / cookie porting (v1.27.0, F1) ────────────────


async def _resolve_cookie_target(session_id: str | None):
    """Resolve the target CDP client + session for a cookie op.

    Returns ``(client, sess)`` where *client* is the session's client (when a
    session is given or minted) or the shared default client.  Raises
    KeyError with a message when an explicit *session_id* does not exist.

    Like the REST endpoints, cookie ops call the client methods DIRECTLY —
    never through ``main.run_op``.  ``run_op`` logs ``str(result)[:200]``
    into the operation timeline; cookie values must never land there
    (product security rule: "cookie-k soha nem log-ba/chatbe").
    """
    from main import _set_current_session, client, session_registry

    if session_id:
        sess = session_registry.get(session_id)
        if sess is None:
            raise KeyError(f"Session {session_id} not found")
        _set_current_session(sess)
        return sess.client, sess
    # No explicit session: use the process-scoped MCP session (or the
    # shared default client when the browser is unavailable).
    sess, _ = await _mcp_session()
    return (sess.client if sess is not None else client), sess


async def export_cookies(session_id: str | None = None, include_values: bool = False,
                         ctx: Context | None = None) -> str:
    """Export all cookies from a session (capability ``browser.core``, READY).

    Returns the cookie names, domains, paths, expiry and flags. Values are
    replaced by ``[redacted]`` unless ``include_values`` is true: a session cookie
    is a login, and the agent rarely needs its value. Use the values only to
    re-import into another session (``import_cookies``).
    """
    if ctx is not None:
        await ctx.info(f"export_cookies session={session_id} include_values={include_values}")
    try:
        target, _ = await _resolve_cookie_target(session_id)
        res = await target.get_cookies()
        if not include_values and isinstance(res, dict):
            res = dict(res)
            res["cookies"] = [{**c, "value": "[redacted]"} for c in res.get("cookies", [])]
            res["values_redacted"] = True
        return tool_result("export_cookies", res)
    except KeyError as exc:
        return tool_error("export_cookies", "session_not_found", str(exc))
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("export_cookies", "cookie_export_failed", str(exc))


async def import_cookies(cookies: list[dict], session_id: str | None = None,
                         ctx: Context | None = None) -> str:
    """Import cookies into a session (capability ``browser.core``, READY).

    Body cookies are CDP CookieParam shapes: {name, value, domain, path?,
    expires?, httpOnly?, secure?, sameSite?}.  Values are never echoed back
    into the operation log or chat — only a count is returned.
    """
    if ctx is not None:
        await ctx.info(f"import_cookies session={session_id} n={len(cookies or [])}")
    cookies = cookies or []
    try:
        target, _ = await _resolve_cookie_target(session_id)
        res = await target.set_cookies(cookies)
        return tool_result("import_cookies", res)
    except KeyError as exc:
        return tool_error("import_cookies", "session_not_found", str(exc))
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("import_cookies", "cookie_import_failed", str(exc))


async def clone_session(session_id: str | None = None, ctx: Context | None = None) -> str:
    """Clone a session: mint a new session and copy all cookies over
    (capability ``browser.core``, READY).

    The new session is immediately usable and carries the source session's
    authenticated state (Cloudflare cf_clearance, Google session, ...).
    Cookie values are never written to the operation log or chat — only the
    copy count is returned.
    """
    if ctx is not None:
        await ctx.info(f"clone_session source={session_id}")
    try:
        refusal = _test_isolation_refusal("clone_session")
        if refusal:
            return refusal
        _source, _src_sess = await _resolve_cookie_target(session_id)
        res = await _source.get_cookies()
        cookies = (res or {}).get("cookies", [])
        from main import _local_cdp_http, chrome_mgr
        from main import session_registry as _sr

        await chrome_mgr.launch()
        new_sess = await _sr.create(_local_cdp_http())
        imp = await new_sess.client.set_cookies(cookies)
        return tool_result("clone_session", {
            "session_id": new_sess.session_id,
            "cookies_copied": imp.get("imported", 0),
        })
    except KeyError as exc:
        return tool_error("clone_session", "session_not_found", str(exc))
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("clone_session", "clone_failed", str(exc))


# ── Wait-for / assertion engine (v1.27.0, F2) ────────────────────────


async def wait_for(value: str, kind: str = "selector", condition: str = "present",
                   timeout: int = 10, ctx: Context | None = None) -> str:
    """Wait until a DOM condition holds (capability ``browser.core``, READY).

    kind=selector|text|url, condition=present|gone|visible.  Deterministic —
    no guessy sleeps; returns ok once the condition holds, error on timeout.
    """
    from main import client

    if ctx is not None:
        await ctx.info(f"wait_for kind={kind} value={value} condition={condition} timeout={timeout}")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        res = await run_op_fn("wait_for", target.wait_for_condition,
                              kind, value, condition, timeout)
        failure = _engine_failure(res)
        if failure:
            return _wait_failure("wait_for", failure)
        return json_dumps({"status": "ok", "operation": "wait_for",
                           "data": res, "error": None, "meta": {}})
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("wait_for", "wait_failed", str(exc))


async def assert_(value: str, kind: str = "selector", condition: str = "exists",
                  expected: str | int | None = None, ctx: Context | None = None) -> str:
    """Assert a DOM condition (capability ``browser.core``, READY).

    Returns a structured pass/fail; a failed assertion is reported as an
    error so the agent's test fails deterministically.
    """
    from main import client

    if ctx is not None:
        await ctx.info(f"assert kind={kind} value={value} condition={condition} expected={expected}")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        res = await run_op_fn("assert", target.assert_elements,
                              kind, value, condition, expected)
        result = (res or {}).get("result") if isinstance(res, dict) else None
        if isinstance(result, dict) and result.get("passed") is False:
            return tool_error("assert", "assertion_failed",
                              f"Assertion failed: {condition} {kind}={value} (found={result.get('found')}, count={result.get('count')})")
        return json_dumps({"status": "ok", "operation": "assert",
                           "data": res, "error": None, "meta": {}})
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("assert", "assertion_failed", str(exc))


# ── Form-intelligence (v1.27.0, F3) ──────────────────────────────────


async def form_fill(fields: list[dict], timeout: int = 5, ctx: Context | None = None) -> str:
    """Fill SPA form fields by label/selector (capability ``browser.core``, READY).

    Each field: {label|selector|placeholder, value, nth?}.  Uses the
    value-setter technique (native setter + input/change/blur events) so
    React/Angular controlled inputs register the change.
    """
    from main import client

    if ctx is not None:
        await ctx.info(f"form_fill fields={len(fields or [])}")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        res = await run_op_fn("form_fill", target.smart_form_fill, fields or [], timeout)
        return json_dumps({"status": "ok", "operation": "form_fill",
                           "data": res, "error": None, "meta": {}})
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("form_fill", "form_fill_failed", str(exc))


async def form_extract(ctx: Context | None = None) -> str:
    """Extract the page's form structure (capability ``browser.core``, READY).

    Returns each form's fields: tag, type, name, label, placeholder,
    required, visible — feed the labels into form_fill.
    """
    from main import client

    if ctx is not None:
        await ctx.info("form_extract")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        res = await run_op_fn("form_extract", target.form_extract)
        return json_dumps({"status": "ok", "operation": "form_extract",
                           "data": res, "error": None, "meta": {}})
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("form_extract", "form_extract_failed", str(exc))


# ── Download helper (v1.27.0, F5) ───────────────────────────────────


async def download(url: str, timeout: int = 30, ctx: Context | None = None) -> str:
    """Download a file via the browser and store it as an artifact
    (capability ``browser.core``, READY).

    Returns the artifact record — fetch the file at
    ``GET /artifacts/{artifact_id}``.
    """
    from main import client

    if ctx is not None:
        await ctx.info(f"download url={url}")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="bh-dl-") as dl_dir:
            res = await run_op_fn("download", target.download_file, url, dl_dir, timeout)
            if not isinstance(res, dict) or res.get("status") != "ok":
                return tool_error("download", "download_failed",
                                  str(res.get("error", res)))
            path = res["path"]
            import asyncio
            import mimetypes

            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"

            def _read_file() -> bytes:
                with open(path, "rb") as f:
                    return f.read()

            binary = await asyncio.to_thread(_read_file)
            from main import artifact_store

            record = artifact_store.put(binary, mime, suffix=Path(path).suffix or None,
                                        metadata={"source_url": url, "name": res["name"]})
            return json_dumps({"status": "ok", "operation": "download",
                               "data": {"artifact": record, "file_name": res["name"],
                                        "size_bytes": res["size_bytes"]},
                               "error": None, "meta": {}})
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("download", "download_failed", str(exc))


# ── Network interception (v1.27.0, F6) ─────────────────────────────


async def network_block(patterns: list[str], ctx: Context | None = None) -> str:
    """Block network requests whose URL matches any regex *patterns*
    (capability ``browser.core``, READY).

    Matching requests fail with a network error (``Fetch.failRequest``) —
    useful for stubbing analytics/trackers or testing error paths.
    Empty list clears all blocks.
    """
    target, run_op = await _target()

    if ctx is not None:
        await ctx.info(f"network_block patterns={len(patterns)}")
    try:
        result = await run_op("network_block", target.set_network_block, patterns)
        if not isinstance(result, dict) or result.get("status") != "ok":
            return tool_error("network_block", "block_failed", str(result))
        return json_dumps({"status": "ok", "operation": "network_block",
                           "data": {"blocked": result.get("blocked", len(patterns))},
                           "error": None, "meta": {}})
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("network_block", "block_failed", str(exc))


async def network_mock(mocks: list[dict], ctx: Context | None = None) -> str:
    """Install URL-pattern request mocks (capability ``browser.core``, READY).

    Each mock: ``{"pattern": "regex", "status": 200, "body": "...",
    "content_type": "application/json"}``.  Matching requests receive the
    mocked response instead of hitting the network.  Empty list clears.
    """
    target, run_op = await _target()

    if ctx is not None:
        await ctx.info(f"network_mock mocks={len(mocks)}")
    try:
        result = await run_op("network_mock", target.set_request_mocks, mocks)
        if not isinstance(result, dict) or result.get("status") != "ok":
            return tool_error("network_mock", "mock_failed", str(result))
        return json_dumps({"status": "ok", "operation": "network_mock",
                           "data": {"mocks": result.get("mocks", len(mocks))},
                           "error": None, "meta": {}})
    except Exception as exc:  # noqa: BLE001 — tool boundary catch-all
        return tool_error("network_mock", "mock_failed", str(exc))


# ── Agent testing helpers (v1.27.8) ───────────────────────────────


async def get_notifications(
    since: float | None = None,
    limit: int = 50,
    ctx: Context | None = None,
) -> str:
    """Get captured toast/alert/notification messages (capability ``agent.testing``, READY).

    Uses a MutationObserver to watch for DOM changes matching common
    notification selectors (toast, alert, snackbar, notification, dialog).

    Call ``notifications_start`` first to begin monitoring.
    Returns ``{text, classes, tag, timestamp}`` objects.
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info("reading notifications")
    try:
        await target.start_notification_monitoring()
        js = "JSON.stringify(window.__bh_notifications__ || [])"
        result = await target.evaluate(js)
        raw = result.get("result", "[]") if isinstance(result, dict) else "[]"
        import json as _json
        entries = _json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(entries, list):
            entries = []
        if since is not None:
            entries = [e for e in entries if e.get("timestamp", 0) >= since]
        entries = entries[-limit:]
        return tool_result("get_notifications", {"count": len(entries), "entries": entries})
    except Exception as exc:  # noqa: BLE001
        return tool_error("get_notifications", "failed", str(exc))


async def notifications_start(ctx: Context | None = None) -> str:
    """Start monitoring for toast/alert/notification DOM changes (capability ``agent.testing``, READY).

    Injects a MutationObserver that watches for elements with classes like
    toast, alert, snackbar, notification, dialog, banner.
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info("starting notification monitoring")
    try:
        result = await target.start_notification_monitoring()
        return tool_result("notifications_start", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("notifications_start", "failed", str(exc))


async def get_network_requests(
    path: str | None = None,
    method: str | None = None,
    status: int | None = None,
    since: float | None = None,
    limit: int = 100,
    ctx: Context | None = None,
) -> str:
    """Get filtered network request log (capability ``browser.core``, READY).

    Returns request/response pairs collected by the CDP Network domain.
    Filter by URL path substring (``path``), HTTP method, status code, or
    timestamp.  Call ``POST /network/start`` or navigate first to populate.
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info("reading network requests")
    try:
        await target.start_network_monitoring()
        data = await target.get_network_log()
        entries = data.get("entries", [])
        if path:
            entries = [e for e in entries if path in e.get("url", "")]
        if method:
            m = method.upper()
            entries = [e for e in entries if e.get("method", "").upper() == m]
        if status:
            entries = [e for e in entries if e.get("status") == status]
        if since is not None:
            entries = [e for e in entries if e.get("timestamp", 0) >= since]
        entries = entries[-limit:]
        return tool_result("get_network_requests", {"count": len(entries), "entries": entries})
    except Exception as exc:  # noqa: BLE001
        return tool_error("get_network_requests", "failed", str(exc))


async def get_console_errors(
    since: float | None = None,
    limit: int = 50,
    ctx: Context | None = None,
) -> str:
    """Get persistent console errors (capability ``agent.testing``, READY).

    Returns error/exception level console entries WITHOUT clearing the buffer.
    Supports ``since`` for incremental reads (pass the timestamp of the last
    entry you saw).  Unlike the REST ``/agent/console`` (which clears on
    read), this is safe for ongoing monitoring.
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info("reading console errors")
    try:
        await target.start_console_monitoring()
        entries = target.get_console_entries(level="error")
        if since is not None:
            entries = [e for e in entries if e.get("timestamp", 0) >= since]
        entries = entries[-limit:]
        return tool_result("get_console_errors", {"count": len(entries), "entries": entries})
    except Exception as exc:  # noqa: BLE001
        return tool_error("get_console_errors", "failed", str(exc))


async def wait_js(
    js: str,
    timeout: int = 30,
    ctx: Context | None = None,
) -> str:
    """Wait for an arbitrary JS expression to become truthy (capability ``agent.testing``, READY).

    Polls every 200ms until the expression returns a truthy value or timeout.

    Examples::

        wait_js("document.querySelectorAll('.completed').length > 0")
        wait_js("window.__APP_STATE__?.loaded === true")
        wait_js("document.querySelector('#toast')?.innerText.includes('Saved')")
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info(f"waiting for JS (timeout={timeout}s)")
    poll_js = f"""(async function() {{
  const deadline = Date.now() + {int(timeout) * 1000};
  const poll = 200;
  while (Date.now() < deadline) {{
    try {{
      const result = {js};
      if (result) return JSON.stringify({{status: "ok", condition: "js_truthy", result: result}});
    }} catch (e) {{}}
    await new Promise(r => setTimeout(r, poll));
  }}
  return JSON.stringify({{status: "error", error: "timeout after {int(timeout)}s waiting for JS expression"}});
}})();"""
    try:
        result = await target.evaluate(poll_js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        import json as _json
        data = _json.loads(raw) if isinstance(raw, str) else raw
        failure = _engine_failure(data)
        if failure:
            return _wait_failure("wait_js", failure)
        return tool_result("wait_js", data)
    except Exception as exc:  # noqa: BLE001
        return tool_error("wait_js", "failed", str(exc))


async def eval(js: str, timeout: int = 30, tab_id: str | None = None, ctx: Context | None = None) -> str:
    """Execute JS directly and return the value (capability ``browser.core``, READY).

    Calls ``client.evaluate_js`` directly — no snapshot round-trip.

    Pass ``tab_id`` (from ``get_tabs``) to evaluate in a DIFFERENT tab than the
    session's own — the read is pinned to that tab via a background CDP attach
    (no focus steal, no context switch), so it can never land on about:blank.

    Examples::

        eval("document.title")
        eval("window.__APP_STATE__")
        eval("document.querySelectorAll('a').length")
        eval("document.title", tab_id="4D0598DB...")
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info(f"eval js ({len(js)} chars, timeout={timeout}s, tab_id={tab_id or 'session'})")
    try:
        if tab_id:
            pinned = await _tab_pinned_client(tab_id)
            if isinstance(pinned, str):
                return pinned  # tool_error envelope (unknown tab / unreachable)
            result = await _with_timeout("eval", pinned.evaluate_js(js), timeout)
        else:
            result = await _with_timeout("eval", target.evaluate_js(js), timeout)
        return tool_result("eval", result)
    except Exception as exc:  # noqa: BLE001
        code = "timeout" if isinstance(exc, TimeoutError) else "failed"
        return tool_error("eval", code, str(exc))


async def get_page_text(
    wait_ready: bool = True,
    timeout: int = 20,
    tab_id: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Get visible page text (capability ``browser.core``, READY).

    Optionally waits for the page to reach ready (network idle + stable DOM)
    before extracting, same as ``get_content`` with the cleaner main-content
    filter stripped.  Alias for ``client.get_page_text`` with wait handling.

    Pass ``tab_id`` (from ``get_tabs``) to read a DIFFERENT tab than the
    session's own — pinned via a background CDP attach, so observe-then-read
    round-trips can never drift onto about:blank.
    """
    target, run_op_fn = await _target()
    if ctx is not None:
        await ctx.info(f"get_page_text wait_ready={wait_ready} timeout={timeout} tab_id={tab_id or 'session'}")
    try:
        if tab_id:
            pinned = await _tab_pinned_client(tab_id)
            if isinstance(pinned, str):
                return pinned  # tool_error envelope (unknown tab / unreachable)
            if wait_ready:
                try:
                    await pinned.wait_for_ready(timeout)
                except Exception:  # noqa: BLE001,S110 — wait is best-effort
                    pass
            inner = await pinned.get_page_text()
            return tool_result("get_page_text", inner)
        if wait_ready:
            try:
                await run_op_fn("get_page_text_wait", target.wait_for_ready, timeout)
            except Exception:  # noqa: BLE001,S110 — wait is best-effort; text still readable
                pass
        # 2026-09-02 heal fix: run via run_op so _ensure_browser reconnects the
        # session tab after a Chrome restart (direct target.get_page_text hit
        # "Not connected to Chrome CDP" when the MCP session held a dead WS).
        result = await run_op_fn("get_page_text", target.get_page_text)
        # run_op wraps as {status, data, ...}; unwrap on success
        if isinstance(result, dict) and result.get("data") is not None:
            inner = result["data"]
            # inner may be {status:"ok", text, length} — keep envelope compat
            if isinstance(inner, dict) and "text" in inner:
                result = inner
        return tool_result("get_page_text", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("get_page_text", "failed", str(exc))


async def element_state(
    selector: str,
    ctx: Context | None = None,
) -> str:
    """Get the current state of a DOM element by CSS selector (capability ``agent.testing``, READY).

    Returns disabled, text, value, visible, tag, classes, type, and
    bounding rect.  Returns error if element not found.

    Examples::

        element_state("#my-button")
        element_state("input[name=email]")
        element_state(".completed:first-child")
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info(f"querying element: {selector}")
    import json as _json
    js = f"""(() => {{
  const el = document.querySelector({_json.dumps(selector)});
  if (!el) return JSON.stringify({{status: "error", error: "Element not found: " + {_json.dumps(selector)}}});
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  return JSON.stringify({{
    status: "ok",
    selector: {_json.dumps(selector)},
    tag: el.tagName.toLowerCase(),
    text: (el.textContent || "").trim().substring(0, 500),
    value: el.value || null,
    disabled: el.disabled || false,
    readonly: el.readOnly || false,
    visible: el.offsetParent !== null && style.display !== "none" && style.visibility !== "hidden",
    classes: el.className || "",
    id: el.id || null,
    type: el.type || null,
    placeholder: el.placeholder || null,
    rect: {{x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)}}
  }});
}})()"""
    try:
        result = await target.evaluate(js)
        raw = result.get("result", "{}") if isinstance(result, dict) else "{}"
        data = _json.loads(raw) if isinstance(raw, str) else raw
        if data.get("status") == "error":
            return tool_error("element_state", "not_found", data.get("error", "Element not found"))
        return tool_result("element_state", data)
    except Exception as exc:  # noqa: BLE001
        return tool_error("element_state", "failed", str(exc))


async def press_key(
    key: str,
    selector: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Press a keyboard key (capability ``browser.core``, READY).

    Optionally focuses *selector* first.  Key names: Enter, Escape,
    ArrowDown, ArrowUp, Tab, Backspace, etc.

    Examples::

        press_key("Enter")
        press_key("Escape")
        press_key("ArrowDown", selector="#dropdown")
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info(f"press_key {key}" + (f" @ {selector}" if selector else ""))
    try:
        result = await target.press_key(key, selector)
        if result.get("status") == "error":
            return tool_error("press_key", "not_found", result.get("error", "Element not found"))
        return tool_result("press_key", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("press_key", "failed", str(exc))


async def hover(selector: str, ctx: Context | None = None) -> str:
    """Hover over an element by CSS selector (capability ``browser.core``, READY).

    Resolves the element's center point, then dispatches a real CDP
    mouseMoved event — triggers CSS :hover and mouseenter handlers
    (dropdown menus, tooltips).

    Example: hover("#nav-menu") → dropdown opens.
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info(f"hover {selector}")
    try:
        result = await target.hover(selector)
        if result.get("status") == "error":
            return tool_error("hover", "not_found", result.get("error", "Element not found"))
        return tool_result("hover", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("hover", "failed", str(exc))


async def scroll(
    x: int = 0,
    y: int = 0,
    selector: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Scroll page or element by x, y pixels (capability ``browser.core``, READY).

    With *selector* scrolls that scrollable container instead of the window.

    Examples::

        scroll(y=500)                    # page down 500px
        scroll(selector=".chat-list", y=1000)
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info(f"scroll x={x} y={y}" + (f" @ {selector}" if selector else ""))
    try:
        result = await target.scroll(x, y, selector)
        if result.get("status") == "error":
            return tool_error("scroll", "not_found", result.get("error", "Element not found"))
        return tool_result("scroll", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("scroll", "failed", str(exc))


async def reload(
    ignore_cache: bool = False,
    ctx: Context | None = None,
) -> str:
    """Reload the current page (capability ``browser.core``, READY).

    Set *ignore_cache* to bypass the HTTP cache (hard reload).
    """
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info(f"reload ignore_cache={ignore_cache}")
    try:
        result = await target.reload(ignore_cache)
        return tool_result("reload", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("reload", "failed", str(exc))


async def wait_network_idle(
    timeout: int = 10,
    quiet_ms: int = 500,
    ctx: Context | None = None,
) -> str:
    """Wait until network is idle (capability ``browser.core``, READY).

    Returns once no network requests have been in flight for *quiet_ms*
    (default 500ms).  Use after form submissions or clicks that trigger
    AJAX calls so the next action never races in-flight requests.
    """
    target, run_op_fn = await _target()
    if ctx is not None:
        await ctx.info(f"wait_network_idle timeout={timeout}s quiet_ms={quiet_ms}")
    try:
        result = await run_op_fn(
            "wait_for_network_idle", target.wait_for_network_idle, timeout, quiet_ms
        )
        failure = _engine_failure(result)
        if failure:
            return _wait_failure("wait_network_idle", failure)
        return tool_result("wait_network_idle", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("wait_network_idle", "failed", str(exc))


async def rate_limiter_status(ctx: Context | None = None) -> str:
    """Return domain throttle + rate limiter state (capability ``browser.core``, READY).

    Shows the current interval, per-domain last-hit + remaining wait.
    Useful when ``navigate`` feels slow — tells you if the 4s domain
    throttle is holding the request.
    """
    if ctx is not None:
        await ctx.info("rate_limiter_status")
    try:
        import time as _time

        from domain_throttle import DEFAULT_MIN_INTERVAL_SEC
        from domain_throttle import domain_throttle as _dt
        from main import settings_mgr as _sm

        raw = _sm.get("domain_min_interval_sec", DEFAULT_MIN_INTERVAL_SEC)
        try:
            interval = float(raw)
        except (TypeError, ValueError):
            interval = DEFAULT_MIN_INTERVAL_SEC
        now = _time.monotonic()
        domains: dict[str, dict] = {}
        for dom, ts in list(_dt._last.items()):
            elapsed = now - ts
            remaining = max(0.0, interval - elapsed)
            domains[dom] = {"last_hit_ago_s": round(elapsed, 2), "remaining_wait_s": round(remaining, 2)}
        data = {"interval_sec": interval, "default_interval_sec": DEFAULT_MIN_INTERVAL_SEC, "domains": domains}
        return tool_result("rate_limiter_status", {"status": "ok", **data})
    except Exception as exc:  # noqa: BLE001
        return tool_error("rate_limiter_status", "failed", str(exc))


async def dialog_handle(
    action: str,
    prompt_text: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Accept or dismiss a JavaScript dialog (capability ``browser.core``, READY).

    Handles alert/confirm/prompt/beforeunload.  Use ``prompt_text`` when
    accepting a ``prompt()`` dialog to provide the input value.

    Examples::

        dialog_handle("accept")
        dialog_handle("dismiss")
        dialog_handle("accept", prompt_text="my answer")
    """
    if action not in ("accept", "dismiss"):
        return tool_error("dialog_handle", "invalid_action", "action must be 'accept' or 'dismiss'")
    target, _run_op = await _target()
    if ctx is not None:
        await ctx.info(f"dialog_handle {action}")
    try:
        if action == "accept":
            result = await target.dialog_accept(prompt_text)
        else:
            result = await target.dialog_dismiss()
        return tool_result("dialog_handle", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("dialog_handle", "failed", str(exc))

# ── 6× E2E validation — thin MCP wrappers over the REST engine ──

# ── Group 1: semantic DOM & a11y ────────────────────────────────

async def browser_get_accessibility_tree(
    token_limit: int = 6000,
    max_nodes: int = 250,
    interactive_only: bool = False,
    scope: str = "page",
    include_hidden: bool = False,
    ctx = None,
) -> str:
    """Token-optimized ARIA a11y tree (roles/names/states, not raw HTML) (capability ``agent.semantic``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_get_accessibility_tree scope={scope} max_nodes={max_nodes}")
    try:
        target, run_op_fn = await _target()
        # 2026-09-02 heal fix: health-check the session tab via run_op so a
        #  dead WS reconnects before the snapshot capture (otherwise
        #  "Not connected to Chrome CDP").
        try:
            await run_op_fn("a11y_heal_ping", target.get_tabs)
        except Exception as skip_exc:  # noqa: BLE001 — heal is best-effort; capture will retry
            logger.debug("best-effort a11y heal ping failed: %s", skip_exc)
        from main import _capture_accessibility_snapshot
        snap = await _capture_accessibility_snapshot(
            scope=scope, interactive_only=interactive_only, include_hidden=include_hidden, target=target
        )
        data = snap.as_dict(max_nodes=min(max(1, int(max_nodes)), 1000))
        txt = data.get("text", "") or ""
        limit = min(max(int(token_limit), 100), 20000) * 4
        if len(txt) > limit:
            data["text"] = txt[:limit]
            data["truncated"] = True
        return tool_result("browser_get_accessibility_tree", data)
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_get_accessibility_tree", "observation_failed", str(exc))


def _suggest_playwright_locator(node: object) -> str:
    role = (getattr(node, "role", "") or "").lower()
    name = (getattr(node, "name", "") or "").strip()
    esc = name.replace("'", r"\'")
    if role and name:
        return f"getByRole('{role}', {{ name: '{esc}' }})"
    if name:
        return f"getByLabel('{esc}')"
    if role:
        return f"getByRole('{role}')"
    return ""


async def browser_find_semantic_elements(
    query: str | None = None,
    role: str | None = None,
    max_results: int = 20,
    suggest_locator: bool = True,
    ctx = None,
) -> str:
    """Map interactive elements to Playwright-stable locators (capability ``agent.semantic``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_find_semantic_elements query={query!r} role={role}")
    try:
        from main import _capture_accessibility_snapshot
        target, _ = await _target()
        snap = await _capture_accessibility_snapshot(scope="page", include=None, target=target)
        q = (query or "").casefold()
        r = (role or "").casefold()
        cands = []
        for n in snap.nodes:
            nm = (getattr(n, "name", "") or "").casefold()
            ro = (getattr(n, "role", "") or "").casefold()
            if r and ro != r:
                continue
            if q and q not in nm and q not in ro:
                continue
            item = {
                "role": n.role,
                "name": n.name,
                "ref": getattr(n, "ref", None),
                "backend_node_id": getattr(n, "backend_node_id", None),
                "selector_hint": getattr(n, "selector_hint", "") or n.name[:80],
            }
            if suggest_locator:
                item["suggested_locator"] = _suggest_playwright_locator(n)
            cands.append(item)
            if len(cands) >= min(max(1, int(max_results)), 100):
                break
        return tool_result("browser_find_semantic_elements", {"count": len(cands), "elements": cands, "snapshot_id": snap.snapshot_id})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_find_semantic_elements", "discovery_failed", str(exc))


async def browser_get_page_structure(
    include_iframes: bool = True,
    max_chars: int = 6000,
    ctx = None,
) -> str:
    """Concise page structure: forms + buttons + dialogs (+ optional iframes) (capability ``agent.semantic``, READY)."""
    if ctx is not None:
        await ctx.info("browser_get_page_structure")
    try:
        target, _ = await _target()
        from main import _capture_accessibility_snapshot as _cap_ax
        from main import _capture_agent_snapshot, discover_forms, paginate_snapshot
        snap_sem = await _capture_agent_snapshot(condensed=True, target=target)
        page = paginate_snapshot(snap_sem, max_chars=int(min(max(int(max_chars), 500), 20000)), max_elements=80, cursor=None)
        ax = await _cap_ax(scope="page", target=target)
        forms = discover_forms(ax)
        dialogs = [n.as_dict() for n in ax.nodes if (getattr(n, "role", "") or "").lower() in ("dialog", "alertdialog")]
        iframes = []
        if include_iframes:
            try:
                tmp = await target.evaluate("JSON.stringify([...document.querySelectorAll('iframe')].map((f,i)=>({index:i,src:f.src,title:f.title})))")
                raw = tmp.get("result", "[]") if isinstance(tmp, dict) else "[]"
                import json as _j
                iframes = _j.loads(raw) if isinstance(raw, str) else raw
            except Exception:  # noqa: BLE001
                iframes = []
        return tool_result("browser_get_page_structure", {
            "forms": forms,
            "buttons": page.get("elements", [])[:40],
            "dialogs": dialogs[:10],
            "iframes": iframes if include_iframes else [],
            "visible_text_len": len(page.get("text", "")),
            "snapshot_id": ax.snapshot_id,
        })
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_get_page_structure", "discovery_failed", str(exc))


# ── Group 2: deterministic interactions ─────────────────────────

_NEGOTIATE = {"domContentLoaded", "load", "networkIdle"}


async def browser_navigate(
    url: str,
    wait_until: str | None = None,
    settle: bool = False,
    timeout: int = 10,
    origins: list[dict] | None = None,
    storage_state: list[dict] | dict | None = None,
    make_active: bool | None = None,
    ctx = None,
) -> str:
    """Navigate with load strategy (capability ``browser.core``, READY). P0-3: origins / storageState before paint.

    ``make_active`` (default true) brings the navigated tab to the foreground;
    pass ``false`` to keep the current foreground tab (P0 navigate-active).
    The response always carries ``tab_id`` / ``active_tab_id``.
    """
    if ctx is not None:
        await ctx.info(f"browser_navigate {url} wait_until={wait_until} settle={settle} origins={bool(origins or storage_state)}")
    try:
        if wait_until and wait_until not in _NEGOTIATE:
            return tool_error("browser_navigate", "invalid_wait_until", "must be domContentLoaded|load|networkIdle")
        allowlist = _origin_allowlist()
        if allowlist is not None and not _origin_allowed(url, allowlist):
            return tool_error("browser_navigate", "origin_not_allowed",
                              f"{url} is not in BH_ALLOWED_ORIGINS; allowed: {', '.join(allowlist)}")
        target, run_op = await _target()
        # P0-3: normalize storage_state alias
        payload_origins = origins
        if storage_state is not None:
            if isinstance(storage_state, dict) and "origins" in storage_state:
                ss = storage_state["origins"]
                if isinstance(ss, list):
                    payload_origins = (payload_origins or []) + ss
            elif isinstance(storage_state, list):
                payload_origins = (payload_origins or []) + storage_state
        # Inject via addScript before navigate so first paint sees the value
        if payload_origins:
            import json as _j
            parts: list[str] = []
            for _o in payload_origins if isinstance(payload_origins, list) else []:
                if not isinstance(_o, dict):
                    continue
                for _kv in (_o.get("localStorage") or _o.get("local_storage") or []):
                    _k = _kv.get("name") if isinstance(_kv, dict) else None
                    _v = _kv.get("value") if isinstance(_kv, dict) else None
                    if _k is None or _v is None:
                        continue
                    parts.append(f"try{{localStorage.setItem({_j.dumps(str(_k))},{_j.dumps(str(_v))});}}catch(e){{}}")
            if parts:
                try:
                    await target.add_script_to_evaluate_on_new_document("".join(parts))
                except Exception as skip_exc:  # noqa: BLE001 — best-effort localStorage seed; navigation continues without it
                    logger.debug("best-effort localStorage seed (session) failed: %s", skip_exc)
        # wait_until is honoured: domContentLoaded and load map onto navigate;
        # networkIdle navigates, then waits for the network to go quiet.
        ready = {"domContentLoaded": "domcontentloaded", "load": "load"}.get(wait_until or "", "domcontentloaded")
        res = await run_op("navigate", target.navigate, url, wait_until=ready, timeout=float(timeout))
        if wait_until == "networkIdle" and isinstance(res, dict) and res.get("status") == "ok":
            idle = await run_op("navigate_idle", target.wait_for_network_idle, int(timeout), 500)
            failure = _engine_failure(idle)
            if failure:
                return _wait_failure("browser_navigate", failure)
        # P0 navigate-active: surface the resolved tab and honor make_active=false
        if isinstance(res, dict):
            _d = res.get("data")
            if isinstance(_d, dict):
                _d.setdefault("active_tab_id", _d.get("tab_id"))
                if make_active is False:
                    _d["make_active"] = False
        if settle:
            try:
                tout = min(max(int(timeout), 1), 30)
                extra = await run_op("navigate_settle", target.wait_for_network_idle, tout, 800)  # type: ignore[arg-type]
                if isinstance(res, dict):
                    d = res.get("data") or {}
                    d["settle"] = extra if isinstance(extra, dict) else {}
            except Exception as skip_exc:  # noqa: BLE001
                logger.debug("best-effort navigate settle failed: %s", skip_exc)
        return tool_result("browser_navigate", res.get("data", res) if isinstance(res, dict) else res)
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_navigate", "navigation_failed", str(exc))


async def browser_interact(
    selector: str,
    action: str = "click",
    text: str | None = None,
    option: str | None = None,
    wait_visible: bool = True,
    wait_ms: int = 8000,
    scroll_into_view: bool = True,
    ctx = None,
) -> str:
    """One-call click/fill/press/select with actionability checks (capability ``browser.core``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_interact {action} {selector}")
    try:
        al = (action or "click").lower().strip()
        if al in {"type", "fill"}:
            al = "fill"
        if al not in {"click", "fill", "press", "select"}:
            return tool_error("browser_interact", "invalid_action", "action must be click|fill|press|select")
        target, run_op = await _target()
        if wait_visible:
            tout = min(max(int(wait_ms), 0), 30000)
            if tout:
                sec = max(1, tout // 1000)
                ww = await run_op("browser_interact_wait", target.wait_for_element, selector, sec, True)  # type: ignore[arg-type]
                inner = (ww or {}).get("result", {}) if isinstance(ww, dict) else {}
                if isinstance(inner, dict) and inner.get("status") != "ok":
                    return tool_error("browser_interact", "not_actionable", f"selector {selector!r} not visible after {tout}ms")
        if scroll_into_view:
            try:
                await target.evaluate(f"document.querySelector({__import__('json').dumps(selector)})?.scrollIntoView({{block:'center', behavior:'instant'}})")
            except Exception as skip_exc:  # noqa: BLE001
                logger.debug("best-effort scroll into view failed: %s", skip_exc)
        if al == "click" and text and action == "press":
            al = "press"
        if al == "click":
            out = await run_op("click", target.click, selector)
        elif al == "fill":
            if text is None:
                return tool_error("browser_interact", "missing_text", "fill requires text/value")
            out = await run_op("type", target.type_text, selector, text)
        elif al == "press":
            key = text.strip() if (selector and text and text.strip()) else (text or selector)
            out = await run_op("press_key", target.press_key, key, selector if selector != key else None)
        elif al == "select":
            if text is None and option is None:
                return tool_error("browser_interact", "missing_option", "select requires option / text")
            out = await run_op("select", target.form_select, "label", selector, option or text or "")
        else:
            return tool_error("browser_interact", "unknown_action", al)
        return tool_result("browser_interact", out.get("data", out) if isinstance(out, dict) else out)
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_interact", "interaction_failed", str(exc))


async def browser_upload_file(
    selector: str,
    path: str,
    filename: str | None = None,
    ctx = None,
) -> str:
    """Upload a sandboxed file via <input type=file> (capability ``browser.core``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_upload_file {selector} <- {path}")
    try:
        from pathlib import Path as _P
        sb = _P("/tmp/bh-upload-sandbox").resolve()
        alt = (_P.home() / ".browser-helper" / "uploads").resolve()
        p = _P(path).resolve()
        if not (p.is_relative_to(sb) or p.is_relative_to(alt)):
            return tool_error("browser_upload_file", "bad_path", "file must be inside /tmp/bh-upload-sandbox or ~/.browser-helper/uploads")
        if not p.exists():
            return tool_error("browser_upload_file", "not_found", f"file does not exist: {path}")
        files_arg = [str(p)]
        target, run_op = await _target()
        if filename and filename.strip():
            import shutil as _sh
            import tempfile as _tmp
            suffix = _P(filename).suffix or _P(path).suffix
            base_dir = str(sb if sb.exists() else alt)
            _P(base_dir).mkdir(parents=True, exist_ok=True)
            with _tmp.NamedTemporaryFile(delete=False, dir=base_dir, suffix=suffix or None) as tmp:
                _sh.copyfile(str(p), tmp.name)
                renamed = _P(tmp.name).parent / filename
                try:
                    _P(tmp.name).rename(renamed)
                except OSError:
                    renamed = _P(tmp.name)
                files_arg = [str(renamed)]
        out = await run_op("upload_files", target.upload_files, selector, files_arg)
        return tool_result("browser_upload_file", out.get("data", out) if isinstance(out, dict) else out)
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_upload_file", "upload_failed", str(exc))


async def browser_download_file(
    url: str,
    timeout: int = 30,
    ctx = None,
) -> str:
    """Download a URL into the artifact store via the browser (sandboxed) (capability ``browser.core``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_download_file {url}")
    try:
        import mimetypes as _mime
        import tempfile as _tmp
        target, run_op = await _target()
        with _tmp.TemporaryDirectory(prefix="bh-dl-") as dl_dir:
            raw = await run_op("download", target.download_file, url, dl_dir, int(timeout))
            if not isinstance(raw, dict) or raw.get("status") != "ok":
                return tool_error("browser_download_file", "download_failed", str((raw or {}).get("error", raw)))
            path = raw["path"]
            mime = _mime.guess_type(path)[0] or "application/octet-stream"
            from pathlib import Path as _P
            def _read() -> bytes:
                with open(path, "rb") as f:
                    return f.read()
            import asyncio as _aio
            blob = await _aio.to_thread(_read)
            from main import artifact_store
            rec = artifact_store.put(blob, mime, suffix=_P(path).suffix or None, metadata={"source_url": url, "name": raw["name"]})
        return tool_result("browser_download_file", {"artifact": rec, "file_name": raw["name"], "size_bytes": raw["size_bytes"]})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_download_file", "download_failed", str(exc))


# ── Group 3: diagnostics ─────────────────────────────────────

async def browser_get_console_logs(
    level: str = "error",
    since: float | None = None,
    limit: int = 50,
    ctx = None,
) -> str:
    """Fetch browser console logs with stack traces by level (capability ``agent.testing``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_get_console_logs level={level}")
    try:
        target, _ = await _target()
        try:
            await target.start_console_monitoring()
        except Exception as skip_exc:  # noqa: BLE001
            logger.debug("best-effort start console monitoring failed: %s", skip_exc)
        if (level or "error").lower() == "all":
            entries = target.console_entries if hasattr(target, "console_entries") else []
        elif (level or "error").lower() == "error":
            entries = target.get_console_entries("error") if hasattr(target, "get_console_entries") else []
        else:
            lv = (level or "").lower()
            all_e = target.get_console_entries("error") + target.get_console_entries("warning") if hasattr(target, "get_console_entries") else []
            entries = [e for e in all_e if (e.get("level", "") or "").lower() == lv]
            if not entries:
                entries = target.get_console_entries(level) if hasattr(target, "get_console_entries") else []
        if since is not None:
            entries = [e for e in entries if e.get("timestamp", 0) >= float(since)]
        entries = (entries or [])[-min(max(1, int(limit)), 200):]
        return tool_result("browser_get_console_logs", {"count": len(entries), "entries": entries})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_get_console_logs", "failed", str(exc))


async def browser_get_network_activity(
    path: str | None = None,
    method: str | None = None,
    status_min: int | None = None,
    since: float | None = None,
    limit: int = 100,
    ctx = None,
) -> str:
    """Failed requests, api timings, payloads — filtered CDP network log (capability ``browser.core``, READY)."""
    if ctx is not None:
        await ctx.info("browser_get_network_activity")
    try:
        target, _ = await _target()
        try:
            await target.start_network_monitoring()
        except Exception as skip_exc:  # noqa: BLE001
            logger.debug("best-effort start network monitoring failed: %s", skip_exc)
        raw = await target.get_network_log()
        entries = raw.get("entries", []) if isinstance(raw, dict) else []
        if path:
            entries = [e for e in entries if path in e.get("url", "")]
        if method:
            m = method.upper()
            entries = [e for e in entries if (e.get("method", "") or "").upper() == m]
        if status_min is not None:
            entries = [e for e in entries if (e.get("status") or 0) >= int(status_min)]
        if since is not None:
            entries = [e for e in entries if e.get("timestamp", 0) >= float(since)]
        entries = entries[-min(max(1, int(limit)), 500):]
        return tool_result("browser_get_network_activity", {"count": len(entries), "entries": entries})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_get_network_activity", "failed", str(exc))


async def browser_wait_for_condition(
    js: str | None = None,
    selector: str | None = None,
    visible: bool = True,
    timeout: int = 10,
    ctx = None,
) -> str:
    """Wait for a JS predicate or a selector (capability ``agent.testing``, READY)."""
    if not js and not selector:
        return tool_error("browser_wait_for_condition", "invalid_params", "one of js or selector is required")
    if js and selector:
        return tool_error("browser_wait_for_condition", "invalid_params", "js and selector are mutually exclusive")
    if ctx is not None:
        await ctx.info(f"browser_wait_for_condition {('js' if js else 'selector')}")
    try:
        target, _ = await _target()
        tout = min(max(int(timeout), 1), 60)
        if js:
            poll_js = f"""(async function() {{
  const deadline = Date.now() + {tout * 1000};
  const poll = 200;
  while (Date.now() < deadline) {{
    try {{ const r = {js}; if (r) return JSON.stringify({{status:"ok", js_truthy:true}}); }} catch(e) {{}}
    await new Promise(r => setTimeout(r, poll));
  }}
  return JSON.stringify({{status:"error", error:"timeout after {tout}s"}});
}})();"""
            out = await target.evaluate(poll_js)
            raw = out.get("result", "{}") if isinstance(out, dict) else "{}"
            import json as _j
            data = _j.loads(raw) if isinstance(raw, str) else raw
            if data.get("status") == "error":
                return tool_error("browser_wait_for_condition", "timeout", data.get("error", "timeout"))
            return tool_result("browser_wait_for_condition", data)
        out = await target.wait_for_element(selector, tout, bool(visible))
        inner = (out or {}).get("result", {}) if isinstance(out, dict) else {}
        if isinstance(inner, dict) and inner.get("status") == "error":
            return tool_error("browser_wait_for_condition", "timeout", inner.get("error", "timeout"))
        return tool_result("browser_wait_for_condition", out)
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_wait_for_condition", "failed", str(exc))


# ── Group 4: visual proof ────────────────────────────────────

async def browser_take_screenshot(
    scope: str = "viewport",
    selector: str | None = None,
    quality: int = 80,
    ctx = None,
) -> str:
    """Screenshots: viewport, full page, or a single component (capability ``browser.core``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_take_screenshot scope={scope}")
    try:
        target, run_op = await _target()
        sc = (scope or "viewport").lower().strip()
        if sc not in {"viewport", "full", "element"}:
            return tool_error("browser_take_screenshot", "invalid_scope", "scope must be viewport|full|element")
        if sc == "element":
            if not selector:
                return tool_error("browser_take_screenshot", "missing_selector", "selector required when scope=element")
            out = await run_op("element_screenshot", target.element_screenshot, selector, int(quality))
        elif sc == "full":
            out = await run_op("full_screenshot", target.full_screenshot, int(quality))
        else:
            out = await run_op("screenshot", target.screenshot, int(quality))
        if not isinstance(out, dict):
            return tool_error("browser_take_screenshot", "failed", str(out))
        data = out.get("data", out) if isinstance(out, dict) else out
        return tool_result("browser_take_screenshot", data)
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_take_screenshot", "failed", str(exc))


async def browser_highlight_elements(
    selectors: list[str],
    duration_ms: int = 4000,
    ctx = None,
) -> str:
    """Draw transient highlight overlays around selectors (capability ``agent.testing``, READY)."""
    if not selectors or not isinstance(selectors, list):
        return tool_error("browser_highlight_elements", "invalid_params", "selectors must be a non-empty list")
    if len(selectors) > 10:
        return tool_error("browser_highlight_elements", "too_many", "at most 10 selectors")
    if ctx is not None:
        await ctx.info(f"browser_highlight_elements {len(selectors)} targets")
    try:
        target, _ = await _target()
        import json as _j
        dur = min(max(int(duration_ms), 500), 30000)
        boots = r"""
((selectors, dur) => {
  document.querySelectorAll('[data-bh-highlight]').forEach(e => e.remove());
  const styleId = 'bh-highlight-style';
  if (!document.getElementById(styleId)) {
    const s = document.createElement('style');
    s.id = styleId;
    s.textContent = '[data-bh-highlight]{position:absolute;border:3px solid #ff2d2d;box-shadow:0 0 0 2px rgba(255,45,45,.35), inset 0 0 0 2px #ff2d2d;pointer-events:none;z-index:2147483646;border-radius:6px;}';
    document.head.appendChild(s);
  }
  let count = 0;
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      const d = document.createElement('div');
      d.setAttribute('data-bh-highlight','1');
      const scY = window.scrollY, scX = window.scrollX;
      d.style.left = (r.left + scX) + 'px';
      d.style.top = (r.top + scY) + 'px';
      d.style.width = r.width + 'px';
      d.style.height = r.height + 'px';
      document.documentElement.appendChild(d);
      count++;
    }
  }
  setTimeout(() => document.querySelectorAll('[data-bh-highlight]').forEach(e=>e.remove()), dur);
  return JSON.stringify({status:'ok', selectors, highlighted: count, duration_ms: dur});
})(SELECTORS, DUR);
"""
        js = boots.replace("SELECTORS", _j.dumps(list(selectors))).replace("DUR", str(dur))
        out = await target.evaluate(js)
        raw = out.get("result", "{}") if isinstance(out, dict) else "{}"
        import json as _j2
        data = _j2.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict) and data.get("status") == "error":
            return tool_error("browser_highlight_elements", "highlight_failed", str(data.get("error")))
        return tool_result("browser_highlight_elements", data if isinstance(data, dict) else {"raw": data})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_highlight_elements", "failed", str(exc))


# ── Group 5: Playwright spec export ──────────────────────────

_RECORD_AC: dict[str, str] = {}


async def browser_start_recorder(
    name: str | None = None,
    ac: str | None = None,
    ctx = None,
) -> str:
    """Start recording browser steps (capability ``agent.flow``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_start_recorder {name or '-'} ac={ac}")
    try:
        from main import AgentRecordRequest, agent_record
        resp = await agent_record(AgentRecordRequest(start=True, name=name))
        raw = getattr(resp, "body", None)
        data = None
        if raw is not None:
            import json as _j
            body = raw if isinstance(raw, (bytes, bytearray)) else (raw if isinstance(raw, (str,)) else None)
            if body is not None:
                try:
                    data = _j.loads(body if isinstance(body, str) else body.decode())
                except ValueError:
                    data = None
        if data is None:
            import main as _m
            rid = getattr(_m, "active_recording_id", None)
            for k, v in getattr(_m, "agent_recordings", {}).items():
                if k == rid:
                    data = {"status": "ok", "data": v}
                    break
        inner = (data or {}).get("data", data) if isinstance(data, dict) else {}
        redisc = inner.get("recording_id") if isinstance(inner, dict) else None
        if isinstance(inner, dict) and redisc and ac:
            _RECORD_AC[redisc] = str(ac)
        return tool_result("browser_start_recorder", inner if isinstance(inner, dict) else {"raw": inner})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_start_recorder", "record_start_failed", str(exc))


async def browser_record_step(
    step: str,
    selector: str | None = None,
    action: str | None = None,
    value: str | None = None,
    ctx = None,
) -> str:
    """Append one human-annotated step to the active recording (capability ``agent.flow``, READY)."""
    if not step or not isinstance(step, str):
        return tool_error("browser_record_step", "invalid_step", "step must be a non-empty description")
    if ctx is not None:
        await ctx.info(f"browser_record_step: {step}")
    try:
        import main as _m
        rid = getattr(_m, "active_recording_id", None)
        if not rid or rid not in getattr(_m, "agent_recordings", {}):
            return tool_error("browser_record_step", "no_active_recording", "call browser_start_recorder first")
        rec = _m.agent_recordings[rid]
        rec.setdefault("steps", []).append({
            "step": step, "selector": selector, "action": action or "step", "value": value,
            "ac": _RECORD_AC.get(rid),
        })
        return tool_result("browser_record_step", {"recording_id": rid, "step_index": len(rec["steps"]), "step": step})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_record_step", "record_failed", str(exc))


def _render_playwright_spec(recording: dict, suite_name: str | None = None) -> str:
    import re as _re
    name = suite_name or recording.get("name") or recording.get("recording_id") or "recorded"
    safe_suite = _re.sub(r"[^A-Za-z0-9_\- ]+", "_", str(name))[:80] or "recorded"
    ac = ""
    for st in recording.get("steps", []):
        if st.get("ac"):
            ac = str(st["ac"]).strip()
            break
    lines: list[str] = []
    lines.append("import { test, expect } from '@playwright/test';")
    lines.append("")
    if ac:
        lines.append(f"// {ac}")
    lines.append(f"test.describe('{safe_suite}', () => {{")
    test_title = ac or (recording.get("name") or "recorded flow")
    title_esc = str(test_title).replace("'", r"\'")
    lines.append(f"  test('{title_esc}', async ({{ page }}) => {{")
    seen_navigate = False
    for st in recording.get("steps", []):
        act = (st.get("action") or st.get("kind") or "step").lower()
        sel = st.get("selector") or st.get("target", {}) or ""
        val = st.get("value")
        step = st.get("step") or act
        step_esc = str(step).replace("'", r"\'")
        sel_s = str(sel).replace("'", r"\'") if sel else ""
        if act in ("navigate", "goto") and sel_s and sel_s.startswith("http"):
            lines.append(f"    // {step_esc}")
            lines.append(f"    await page.goto('{sel_s}');")
            seen_navigate = True
        elif act == "click" and sel_s:
            lines.append(f"    // {step_esc}")
            if sel_s.startswith("[data-testid"):
                import re as _re2
                m = _re2.search(r"data-testid=['\"]([^'\"]+)", sel_s)
                tid = m.group(1) if m else sel_s
                lines.append(f"    await page.getByTestId('{tid}').click();")
            elif sel_s.startswith("getBy"):
                lines.append(f"    await page.{sel_s}.click();")
            else:
                lines.append(f"    await page.locator('{sel_s}').click();")
        elif act in ("fill", "type") and sel_s:
            v = (val or "").replace("'", r"\'")
            lines.append(f"    // {step_esc}")
            if sel_s.startswith("getBy"):
                lines.append(f"    await page.{sel_s}.fill('{v}');")
            else:
                lines.append(f"    await page.locator('{sel_s}').fill('{v}');")
        elif act == "assert" and sel_s:
            lines.append(f"    // {step_esc}")
            lines.append(f"    await expect(page.locator('{sel_s}')).toBeVisible();")
        else:
            lines.append(f"    // {step_esc} ({act})")
            if sel_s:
                lines.append(f"    //   selector: {sel_s}")
            if val:
                lines.append(f"    //   value: {(val or '')[:80]}")
    if seen_navigate is False:
        lines.append("    // (no explicit navigate recorded — add page.goto(...) for the entry URL)")
    lines.append("  });")
    lines.append("});")
    lines.append("")
    return "\n".join(lines)


async def browser_export_playwright_spec(
    suite_name: str | None = None,
    recording_id: str | None = None,
    stop_recording: bool = True,
    ctx = None,
) -> str:
    """Export a recording as a Playwright TypeScript .spec.ts (capability ``agent.flow``, READY)."""
    if ctx is not None:
        await ctx.info("browser_export_playwright_spec")
    try:
        import main as _m
        rid = str(recording_id).strip() if recording_id else getattr(_m, "active_recording_id", None)
        if not rid or rid not in getattr(_m, "agent_recordings", {}):
            return tool_error("browser_export_playwright_spec", "no_recording", "no such recording — call browser_start_recorder first")
        rec = dict(_m.agent_recordings[rid])
        spec = _render_playwright_spec(rec, suite_name)
        from main import artifact_store
        art = artifact_store.put(spec.encode("utf-8"), "text/x.typescript", ".ts", metadata={"recording_id": rid, "suite_name": suite_name or rec.get("name", rid)})
        if stop_recording:
            _m.active_recording_id = None
        return tool_result("browser_export_playwright_spec", {"suite_name": suite_name or rec.get("name", rid), "recording_id": rid, "artifact": art, "spec": spec})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_export_playwright_spec", "export_failed", str(exc))


# ── Group 6: session & state isolation ────────────────────

async def browser_inject_storage_state(
    cookies: list[dict] | None = None,
    origins: list[dict] | None = None,
    tenant: str | None = None,
    ctx = None,
) -> str:
    """Inject JWT/cookies + localStorage state — skip redundant logins (capability ``diagnostics.cookies``, READY)."""
    if ctx is not None:
        await ctx.info(f"browser_inject_storage_state tenant={tenant or '-'}")
    try:
        target, _ = await _target()
        cookies = cookies or []
        counts: dict[str, int] = {"cookies": 0, "origins": 0}
        for c in cookies:
            nm = c.get("name"); val = c.get("value")
            if not nm or val is None:
                continue
            try:
                await target.set_cookies([{
                    "name": str(nm), "value": str(val),
                    "domain": c.get("domain"), "path": c.get("path") or "/",
                    "sameSite": c.get("sameSite"), "expires": c.get("expires"),
                    "httpOnly": c.get("httpOnly"), "secure": c.get("secure"),
                }])
                counts["cookies"] += 1
            except Exception as skip_exc:  # noqa: BLE001
                logger.debug("best-effort cookie import failed: %s", skip_exc)
        for origin_entry in (origins or []):
            items = origin_entry.get("localStorage") or origin_entry.get("local_storage") or []
            for kv in items:
                nm = kv.get("name"); val = kv.get("value")
                if not nm or val is None:
                    continue
                try:
                    import json as _j
                    await target.evaluate(f"localStorage.setItem({_j.dumps(str(nm))}, {_j.dumps(str(val))})")
                    counts["origins"] += 1
                except Exception as skip_exc:  # noqa: BLE001
                    logger.debug("best-effort origin localStorage import failed: %s", skip_exc)
        if tenant and str(tenant).strip():
            try:
                import json as _j
                await target.evaluate(f"localStorage.setItem('tenant', {_j.dumps(str(tenant).strip())})")
                counts["origins"] += 1
            except Exception as skip_exc:  # noqa: BLE001
                logger.debug("best-effort tenant localStorage import failed: %s", skip_exc)
        return tool_result("browser_inject_storage_state", {"injected": counts, "tenant": tenant})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_inject_storage_state", "injection_failed", str(exc))


async def browser_reset_session(
    scope: str = "site",
    ctx = None,
) -> str:
    """Clear state between tests (capability ``browser.core``, READY).

    scope ``site`` (default): the cookies and local/session storage of the page's
    own site only. ``profile``: every cookie and the HTTP cache of the whole Chrome
    profile, which can log you out of every site (your own profile is used by
    default), so it must be asked for explicitly. ``cookies`` and ``storage`` act on
    the current site. ``all`` (legacy) is the current site's cookies and storage plus
    the HTTP cache, which is profile-wide.
    """
    sc = (scope or "site").lower().strip()
    if sc not in {"site", "profile", "cookies", "storage", "all"}:
        return tool_error("browser_reset_session", "invalid_scope",
                          "scope must be site|profile (cookies|storage|all act on the current site)")
    if ctx is not None:
        await ctx.info(f"browser_reset_session scope={sc}")
    try:
        target, _ = await _target()
        done: dict[str, object] = {}
        if sc == "profile":
            try:
                await target._send_command("Network.clearBrowserCookies")
                done["cookies"] = "profile"
            except Exception as exc:  # noqa: BLE001
                return tool_error("browser_reset_session", "clear_cookies_failed", str(exc))
            try:
                await target.clear_browser_cache()  # type: ignore[attr-defined]
                done["cache"] = True
            except Exception:  # noqa: BLE001
                done["cache"] = False
        if sc in ("site", "cookies", "all"):
            try:
                done["cookies"] = await _clear_site_cookies(target)
            except Exception as exc:  # noqa: BLE001
                return tool_error("browser_reset_session", "clear_cookies_failed", str(exc))
        if sc in ("site", "storage", "all"):
            try:
                await target.evaluate("localStorage.clear(); sessionStorage.clear();")
                done["storage"] = True
            except Exception as exc:  # noqa: BLE001
                return tool_error("browser_reset_session", "clear_storage_failed", str(exc))
        if sc == "all":
            # Legacy scope: also the HTTP cache. The cache is profile-wide, not per site.
            try:
                await target.clear_browser_cache()  # type: ignore[attr-defined]
                done["cache"] = True
            except Exception:  # noqa: BLE001
                done["cache"] = False
        return tool_result("browser_reset_session", {"scope": sc, "cleared": done})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_reset_session", "failed", str(exc))


async def _clear_site_cookies(target) -> int:
    """Delete the cookies that apply to the page's current URL. Returns how many were removed."""
    href = await target.evaluate("location.href")
    url = ((href or {}).get("result") or href or "") if isinstance(href, dict) else str(href or "")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return 0
    cookies = (await target._send_command("Network.getCookies", {"urls": [url]})).get("cookies", [])
    for cookie in cookies:
        await target._send_command("Network.deleteCookies", {
            "name": cookie["name"], "domain": cookie["domain"], "path": cookie.get("path", "/")})
    return len(cookies)


# ---------------------------------------------------------------------------
# Testing helpers: viewport, PDF, geolocation, offline, performance, drag,
# and a small accessibility audit. All run on the caller's session tab.
# ---------------------------------------------------------------------------


def _test_isolation_refusal(op: str) -> str | None:
    """Refuse an operation that would launch a real Chrome during test isolation.

    Mirrors the BH_TEST_NO_CHROME guard in main.py: tests must never attach to
    or start a browser, so the call fails in the envelope instead.
    """
    if os.environ.get("BH_TEST_NO_CHROME") == "1":
        return tool_error(op, "chrome_unavailable",
                          "Chrome CDP unavailable: BH_TEST_NO_CHROME test isolation")
    return None


def _envelope_errors(op: str):
    """Turn an exception from a browser call into a tool error envelope.

    Without a connected browser the call must fail inside the envelope
    (status: error), the same way the older browser tools do, not crash the tool.
    """
    def wrap(fn):
        @functools.wraps(fn)
        async def inner(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — every failure becomes an envelope
                return tool_error(op, "operation_failed", str(exc))
        return inner
    return wrap


def _cdp_data(env) -> tuple[Any, str | None]:
    """Unwrap a run_op result into ``(data, error_message)``.

    ``run_op`` returns an ``api_success`` dict on success and a ``JSONResponse``
    on failure. Either can carry the method's own error status.
    """
    if hasattr(env, "body"):
        env = _json_mod.loads(bytes(env.body) or b"{}")
    if not isinstance(env, dict):
        return env, None
    if env.get("status") == "error":
        err = env.get("error") or {}
        return None, (err.get("message") if isinstance(err, dict) else str(err))
    data = env.get("data")
    if isinstance(data, dict) and data.get("status") == "error":
        return None, str(data.get("error", "error"))
    return data, None


async def _eval_json(run_op, op: str, js: str) -> tuple[Any, str | None]:
    """Run JS in the page and parse a JSON string it returns."""
    target, _ = await _target()
    env = await run_op(op, target._send_command, "Runtime.evaluate",
                       {"expression": js, "returnByValue": True})
    data, err = _cdp_data(env)
    if err:
        return None, err
    raw = ((data or {}).get("result") or {}).get("value")
    if (data or {}).get("exceptionDetails"):
        return None, str(data["exceptionDetails"].get("text", "script error"))
    try:
        return _json_mod.loads(raw) if isinstance(raw, str) else raw, None
    except ValueError:
        return None, "page script returned non-JSON output"


@_envelope_errors("set_viewport")
async def set_viewport(width: int, height: int, device_scale_factor: float = 1.0,
                       mobile: bool = False, ctx: Context | None = None) -> str:
    """Set the viewport size for the active tab (capability ``browser.core``, READY).

    Uses Emulation.setDeviceMetricsOverride. Pass width=0 and height=0 to clear
    the override. Set ``mobile=True`` for a phone layout (touch, mobile meta viewport).
    """
    if ctx is not None:
        await ctx.info(f"set_viewport -> {width}x{height}")
    target, run_op = await _target()
    if width <= 0 or height <= 0:
        env = await run_op("set_viewport", target._send_command,
                           "Emulation.clearDeviceMetricsOverride", {})
        _, err = _cdp_data(env)
        if err:
            return tool_error("set_viewport", "viewport_failed", err)
        _note_emulation("viewport", None)
        return tool_result("set_viewport", {"cleared": True})
    params = {"width": width, "height": height,
              "deviceScaleFactor": device_scale_factor, "mobile": mobile}
    env = await run_op("set_viewport", target._send_command,
                       "Emulation.setDeviceMetricsOverride", params)
    _, err = _cdp_data(env)
    if err:
        return tool_error("set_viewport", "viewport_failed", err)
    _note_emulation("viewport", {"width": width, "height": height, "mobile": mobile})
    return tool_result("set_viewport", {"width": width, "height": height,
                                        "device_scale_factor": device_scale_factor,
                                        "mobile": mobile})


@_envelope_errors("print_pdf")
async def print_pdf(landscape: bool = False, print_background: bool = True,
                    scale: float = 1.0, ctx: Context | None = None) -> str:
    """Render the active page to PDF and store it as an artifact (capability ``browser.core``, READY).

    Returns the artifact record; fetch the file at ``GET /artifacts/{artifact_id}``.
    """
    import base64 as _b64

    from main import artifact_store

    if ctx is not None:
        await ctx.info("print_pdf")
    target, run_op = await _target()
    env = await run_op("print_pdf", target._send_command, "Page.printToPDF", {
        "landscape": landscape, "printBackground": print_background, "scale": scale,
    })
    data, err = _cdp_data(env)
    if err:
        return tool_error("print_pdf", "print_failed", err)
    encoded = (data or {}).get("data")
    if not encoded:
        return tool_error("print_pdf", "print_failed", "Chrome returned no PDF data")
    art = artifact_store.put(_b64.b64decode(encoded), "application/pdf", ".pdf",
                             {"source": "mcp_print_pdf"})
    return tool_result("print_pdf", {"artifact_id": art.get("artifact_id"),
                                     "artifact_url": f"/artifacts/{art.get('artifact_id')}"})


@_envelope_errors("set_geolocation")
async def set_geolocation(latitude: float, longitude: float, accuracy: float = 100.0,
                          grant: bool = True, ctx: Context | None = None) -> str:
    """Override the browser geolocation for the active tab (capability ``browser.core``, READY).

    Uses Emulation.setGeolocationOverride. With ``grant=True`` (default) the
    geolocation permission is granted for the current page's origin, so a page
    calling navigator.geolocation receives the position without a prompt. The
    page must be on an http(s) origin; ``file://`` and ``about:`` pages have none.
    """
    if ctx is not None:
        await ctx.info(f"set_geolocation -> {latitude},{longitude}")
    target, run_op = await _target()
    granted_origin = None
    if grant:
        origin, err = await _eval_json(run_op, "set_geolocation", "JSON.stringify(location.origin)")
        if err or not origin or origin == "null":
            return tool_error("set_geolocation", "no_origin",
                              "the page has no http(s) origin; navigate to a web page first, or pass grant=false")
        env = await run_op("set_geolocation", target._send_command, "Browser.grantPermissions",
                           {"permissions": ["geolocation"], "origin": origin})
        _, err = _cdp_data(env)
        if err:
            return tool_error("set_geolocation", "geolocation_failed", err)
        granted_origin = origin
    env = await run_op("set_geolocation", target._send_command,
                       "Emulation.setGeolocationOverride",
                       {"latitude": latitude, "longitude": longitude, "accuracy": accuracy})
    _, err = _cdp_data(env)
    if err:
        return tool_error("set_geolocation", "geolocation_failed", err)
    _note_emulation("geolocation", {"latitude": latitude, "longitude": longitude})
    return tool_result("set_geolocation", {"latitude": latitude, "longitude": longitude,
                                           "accuracy": accuracy, "permission_granted_for": granted_origin})


@_envelope_errors("set_offline")
async def set_offline(offline: bool, ctx: Context | None = None) -> str:
    """Simulate the network going offline (or back online) for the active tab (capability ``browser.core``, READY).

    Uses Network.emulateNetworkConditions with no latency or throttling. Use it
    to test offline behaviour; set ``offline=False`` to restore the network.
    """
    if ctx is not None:
        await ctx.info(f"set_offline -> {offline}")
    target, run_op = await _target()
    env = await run_op("set_offline", target._send_command,
                       "Network.emulateNetworkConditions",
                       {"offline": offline, "latency": 0,
                        "downloadThroughput": -1, "uploadThroughput": -1})
    _, err = _cdp_data(env)
    if err:
        return tool_error("set_offline", "network_emulation_failed", err)
    _note_emulation("offline", True if offline else None)
    return tool_result("set_offline", {"offline": offline})


_PERF_JS = """(() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const paint = {};
  for (const p of performance.getEntriesByType('paint')) paint[p.name] = Math.round(p.startTime);
  return JSON.stringify({
    navigation_ms: {
      ttfb: Math.round(nav.responseStart || 0),
      dom_content_loaded: Math.round(nav.domContentLoadedEventEnd || 0),
      load: Math.round(nav.loadEventEnd || 0)
    },
    paint_ms: paint,
    resources: performance.getEntriesByType('resource').length,
    js_heap_used_bytes: performance.memory ? performance.memory.usedJSHeapSize : null
  });
})()"""


@_envelope_errors("get_performance_metrics")
async def get_performance_metrics(ctx: Context | None = None) -> str:
    """Load timing for the current page (capability ``browser.core``, READY).

    Returns navigation timings (TTFB, DOMContentLoaded, load), paint timings
    (first paint, first contentful paint), resource count and JS heap size, all
    from the browser's Performance API. Values are in milliseconds.
    """
    if ctx is not None:
        await ctx.info("get_performance_metrics")
    import asyncio

    _, run_op = await _target()
    # Read timings only after the load event: before it, loadEventEnd and
    # domContentLoadedEventEnd are still 0 and would look like a fast page.
    for _ in range(20):
        state, err = await _eval_json(run_op, "get_performance_metrics", "JSON.stringify(document.readyState)")
        if err or state == "complete":
            break
        await asyncio.sleep(0.5)
    data, err = await _eval_json(run_op, "get_performance_metrics", _PERF_JS)
    if err:
        return tool_error("get_performance_metrics", "metrics_failed", err)
    return tool_result("get_performance_metrics", data)


@_envelope_errors("drag")
async def drag(from_selector: str, to_selector: str, steps: int = 12,
               ctx: Context | None = None) -> str:
    """Drag one element onto another with the mouse (capability ``browser.core``, READY).

    Presses on the centre of ``from_selector``, moves in ``steps`` steps to the
    centre of ``to_selector``, then releases. Works for HTML5 pointer-based
    drag-and-drop widgets (sliders, sortable lists, board games).
    """
    if ctx is not None:
        await ctx.info(f"drag {from_selector} -> {to_selector}")
    target, run_op = await _target()
    centre_js = (
        "(s => { const e = document.querySelector(s); if (!e) return null;"
        " const r = e.getBoundingClientRect();"
        " return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2}); })"
    )
    start, err = await _eval_json(run_op, "drag_locate",
                                  f"{centre_js}({_json_mod.dumps(from_selector)})")
    if err or start is None:
        return tool_error("drag", "element_not_found", err or f"no element for {from_selector!r}")
    end, err = await _eval_json(run_op, "drag_locate",
                                f"{centre_js}({_json_mod.dumps(to_selector)})")
    if err or end is None:
        return tool_error("drag", "element_not_found", err or f"no element for {to_selector!r}")

    async def _mouse(kind: str, x: float, y: float, buttons: int) -> str | None:
        # Press, drag-move and release all carry the left button; a release sent
        # with button "none" is ignored by Chrome, so the drop never lands.
        pressed = kind != "mouseMoved" or buttons
        env = await run_op("drag", target._send_command, "Input.dispatchMouseEvent", {
            "type": kind, "x": x, "y": y, "button": "left" if pressed else "none",
            "buttons": buttons, "clickCount": 1 if kind != "mouseMoved" else 0})
        _, e = _cdp_data(env)
        return e

    sx, sy, ex, ey = start["x"], start["y"], end["x"], end["y"]
    for failed in [await _mouse("mouseMoved", sx, sy, 0),
                   await _mouse("mousePressed", sx, sy, 1)]:
        if failed:
            return tool_error("drag", "drag_failed", failed)
    n = max(1, int(steps))
    for i in range(1, n + 1):
        x = sx + (ex - sx) * i / n
        y = sy + (ey - sy) * i / n
        if await _mouse("mouseMoved", x, y, 1):
            return tool_error("drag", "drag_failed", "mouse move failed mid-drag")
    failed = await _mouse("mouseReleased", ex, ey, 0)
    if failed:
        return tool_error("drag", "drag_failed", failed)
    return tool_result("drag", {"from": {"x": sx, "y": sy}, "to": {"x": ex, "y": ey}, "steps": n})


_A11Y_JS = """(() => {
  const issues = [];
  const add = (rule, el) => issues.push({rule, tag: el.tagName.toLowerCase(),
    id: el.id || null, text: (el.innerText || el.getAttribute('alt') || '').trim().slice(0, 80)});
  if (!document.documentElement.getAttribute('lang')) issues.push({rule: 'html-has-lang', tag: 'html'});
  if (!document.title || !document.title.trim()) issues.push({rule: 'document-title', tag: 'head'});
  for (const img of document.querySelectorAll('img')) if (!img.hasAttribute('alt')) add('image-alt', img);
  for (const b of document.querySelectorAll('button, [role=button]')) {
    const name = (b.innerText || b.getAttribute('aria-label') || b.getAttribute('title') || '').trim();
    if (!name) add('button-name', b);
  }
  for (const a of document.querySelectorAll('a[href]')) {
    const name = (a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '').trim();
    if (!name && !a.querySelector('img[alt]')) add('link-name', a);
  }
  for (const i of document.querySelectorAll('input, select, textarea')) {
    if (i.type === 'hidden' || i.type === 'submit' || i.type === 'button') continue;
    const labelled = i.labels && i.labels.length || i.getAttribute('aria-label') || i.getAttribute('aria-labelledby') || i.getAttribute('title');
    if (!labelled) add('input-label', i);
  }
  const ids = {};
  for (const e of document.querySelectorAll('[id]')) ids[e.id] = (ids[e.id] || 0) + 1;
  for (const [id, n] of Object.entries(ids)) if (n > 1) issues.push({rule: 'duplicate-id', tag: 'id', id});
  let last = 0;
  for (const h of document.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
    const lvl = Number(h.tagName[1]);
    if (last && lvl > last + 1) add('heading-order', h);
    last = lvl;
  }
  const counts = {};
  for (const i of issues) counts[i.rule] = (counts[i.rule] || 0) + 1;
  return JSON.stringify({total: issues.length, by_rule: counts, issues: issues.slice(0, 50)});
})()"""


_AXE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "static", "vendor", "axe-core", "axe.min.js")
_AXE_RUN_JS = """(async () => {
  const r = await axe.run(document, {resultTypes: ["violations"]});
  const impact = {};
  for (const v of r.violations) impact[v.impact || "unknown"] = (impact[v.impact || "unknown"] || 0) + 1;
  return JSON.stringify({
    engine: "axe-core " + axe.version,
    total: r.violations.length,
    by_impact: impact,
    violations: r.violations.slice(0, 50).map(v => ({
      id: v.id, impact: v.impact, help: v.help, help_url: v.helpUrl,
      nodes: v.nodes.length,
      targets: v.nodes.slice(0, 3).map(n => n.target.join(" "))
    }))
  });
})()"""


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


async def _axe_audit(target) -> dict | None:
    """Run the vendored axe-core on the page. None when it cannot run here."""
    from cdp_client import CDPError

    try:
        source = await asyncio.to_thread(_read_text, _AXE_PATH)
    except OSError:
        return None
    try:
        probe = await target._send_command("Runtime.evaluate", {
            "expression": "typeof axe", "returnByValue": True})
        if ((probe or {}).get("result") or {}).get("value") != "function":
            await target._send_command("Runtime.evaluate", {
                "expression": source, "returnByValue": True})
        r = await target._send_command("Runtime.evaluate", {
            "expression": _AXE_RUN_JS, "returnByValue": True, "awaitPromise": True})
        if (r or {}).get("exceptionDetails"):
            return None
        raw = ((r or {}).get("result") or {}).get("value")
        return _json_mod.loads(raw) if isinstance(raw, str) else None
    except (CDPError, OSError, ValueError, KeyError):
        return None


_SENSITIVE_URL_KEYS = re.compile(
    r"(token|session|sid|auth|key|secret|password|passwd|jwt|code|signature|sig|apikey|access)",
    re.IGNORECASE)


def _redact_pairs(pairs: str) -> str:
    """Redact the values of token-like key=value pairs in a query or a fragment."""
    out = []
    for piece in pairs.split("&"):
        key, eq, _value = piece.partition("=")
        out.append(f"{key}=[redacted]" if eq and _SENSITIVE_URL_KEYS.search(key) else piece)
    return "&".join(out)


def redact_url(url: str) -> str:
    """Hide the values of token-like parameters in the query and in the fragment.

    OAuth redirects put tokens in the fragment (``#access_token=...``), so both are covered.
    """
    if not url or ("?" not in url and "#" not in url):
        return url
    head, hash_sep, fragment = url.partition("#")
    base, q_sep, query = head.partition("?")
    if q_sep:
        query = _redact_pairs(query)
    if hash_sep:
        fragment = _redact_pairs(fragment) if "=" in fragment else fragment
    return base + (q_sep + query if q_sep else "") + (hash_sep + fragment if hash_sep else "")


def _redact_urls(payload):
    """Return *payload* with every ``url`` string value redacted (recursively)."""
    if isinstance(payload, dict):
        return {k: (redact_url(v) if k == "url" and isinstance(v, str) else _redact_urls(v))
                for k, v in payload.items()}
    if isinstance(payload, list):
        return [_redact_urls(v) for v in payload]
    return payload


def _origin_allowlist() -> list[str] | None:
    """Origins the agent may navigate to, from BH_ALLOWED_ORIGINS; None means no restriction."""
    raw = os.environ.get("BH_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return None
    return [o.strip().rstrip("/").lower() for o in raw.split(",") if o.strip()]


def _origin_allowed(url: str, allowlist: list[str]) -> bool:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}".lower()
    return origin in allowlist


def _chrome_profile_on_port(port: int) -> str | None:
    """The --user-data-dir of the Chrome process listening on *port*, or None when none is found."""
    import glob

    needle = f"--remote-debugging-port={port}"
    for path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(path, "rb") as fh:
                args = fh.read().split(b"\0")
        except OSError:
            continue
        line = [a.decode("utf-8", "replace") for a in args if a]
        if not any(a == needle for a in line):
            continue
        for a in line:
            if a.startswith("--user-data-dir="):
                return a.split("=", 1)[1]
    return None


def _browser_profile_info() -> dict:
    """Which Chrome profile and port this server uses, and whether that is the user's own profile."""
    from main import settings_mgr

    profile = settings_mgr.get("chrome_profile_dir") or ""
    port = int(settings_mgr.get("chrome_debug_port") or 9557)
    overridden = bool(os.environ.get("BH_CHROME_PROFILE_DIR", "").strip())
    running = _chrome_profile_on_port(port)
    info = {
        "profile_dir": profile,
        "debug_port": port,
        "source": "BH_CHROME_PROFILE_DIR" if overridden else "settings.json",
        "is_user_default_profile": "google-chrome/Default" in profile or profile.endswith("/Default"),
        "chrome_on_port_profile": running,
    }
    if running and profile and os.path.normpath(running) != os.path.normpath(profile):
        info["warning"] = (f"the Chrome on port {port} uses {running}, not the configured {profile}; "
                           "the agent will act in the browser that is running")
    return info


@_envelope_errors("accessibility_audit")
async def accessibility_audit(ctx: Context | None = None) -> str:
    """Check the active page for common accessibility problems (capability ``browser.core``, READY).

    A built-in heuristic subset, not a full WCAG engine: missing lang and title,
    images without alt, buttons and links without a name, inputs without a label,
    duplicate ids, and skipped heading levels. Returns counts per rule and up to 50 issues.
    """
    if ctx is not None:
        await ctx.info("accessibility_audit")
    target, run_op = await _target()
    axe = await _axe_audit(target)
    if axe is not None:
        return tool_result("accessibility_audit", axe)
    # axe-core could not run on this page: fall back to the built-in heuristic and say so.
    data, err = await _eval_json(run_op, "accessibility_audit", _A11Y_JS)
    if err:
        return tool_error("accessibility_audit", "audit_failed", err)
    return tool_result("accessibility_audit", {"engine": "heuristic", **(data or {})})


# ---------------------------------------------------------------------------
# Human hand-off, form controls and overlays.
# ---------------------------------------------------------------------------


def _observe_diff(mode: str, since_snapshot_id: str, snap) -> dict | None:
    """Diff the new observation against an earlier one. None when the old snapshot is gone."""
    if mode == "accessibility":
        from main import ax_snapshots

        old = ax_snapshots.get(since_snapshot_id)
        if old is None:
            return None
        old_refs = {n.ref: n.as_dict() for n in old.nodes}
        new_refs = {n.ref: n.as_dict() for n in snap.nodes}
        changed = [v for k, v in new_refs.items() if old_refs.get(k) != v]
        return {"from_snapshot_id": old.snapshot_id, "to_snapshot_id": snap.snapshot_id,
                "changed": old.fingerprint != snap.fingerprint,
                "nodes_changed": changed,
                "refs_removed": sorted(set(old_refs) - set(new_refs))}
    from agent_runtime import diff_snapshots
    from main import snapshot_store

    try:
        old = snapshot_store.get(since_snapshot_id)
    except Exception:  # noqa: BLE001 — StaleSnapshotError: the caller re-observes
        return None
    return diff_snapshots(old, snap)


async def _with_timeout(op: str, coro, timeout: float):
    """Await *coro* for at most *timeout* seconds. Returns the value, or raises TimeoutError."""
    import asyncio

    try:
        return await asyncio.wait_for(coro, timeout=max(0.1, float(timeout)))
    except TimeoutError as exc:
        raise TimeoutError(f"{op} timed out after {timeout}s") from exc


def _note_emulation(key: str, value) -> None:
    """Remember an emulation that stays active on the page (None clears it), for session_status."""
    state = _MCP_SESSION.setdefault("emulation", {})
    if value is None:
        state.pop(key, None)
    else:
        state[key] = value


def _engine_failure(res) -> str | None:
    """The failure message inside an engine result, or None when it succeeded.

    The engine wraps a timed-out wait as an ok envelope whose method result has
    status "error". Callers must report that as an error, not as success.
    """
    if not isinstance(res, dict):
        return None
    if res.get("status") == "error":
        err = res.get("error")
        return err.get("message", "failed") if isinstance(err, dict) else str(err or "failed")
    data = res.get("data")
    if isinstance(data, dict):
        if data.get("status") == "error":
            return str(data.get("error") or "failed")
        inner = data.get("result")
        if isinstance(inner, dict) and inner.get("status") == "error":
            return str(inner.get("error") or "failed")
    return None


def _wait_failure(op: str, msg: str) -> str:
    """Error envelope for a failed wait: code timeout when the wait ran out of time."""
    code = "timeout" if "timeout" in msg.lower() or "timed out" in msg.lower() else "wait_failed"
    return tool_error(op, code, msg)


@_envelope_errors("await_user")
async def await_user(url_contains: str | None = None, selector: str | None = None,
                     text: str | None = None, timeout: float = 300.0, poll_ms: int = 1000,
                     reason: str | None = None, ctx: Context | None = None) -> str:
    """Hand a step to a person in the visible browser, then resume (capability ``browser.core``, READY).

    Use it for logins, CAPTCHAs, two-factor prompts and confirmations that the agent
    must not handle. Give at least one condition: ``url_contains`` (the URL includes
    this text), ``selector`` (an element exists) or ``text`` (the page shows this text).
    ``reason`` says what the person must do (shown in session_status and, if the
    system has one, as a desktop notification).

    While waiting, session_status reports the pending hand-off. When the conditions hold
    the page is checked again: an error page is not a success, and the call says so.
    After ``timeout`` seconds without the conditions it returns an error.
    """
    import asyncio as _asyncio
    import time as _time

    if not any((url_contains, selector, text)):
        return tool_error("await_user", "invalid_params",
                          "give at least one of url_contains, selector or text")
    if ctx is not None:
        await ctx.info(f"await_user: {reason or 'waiting for a person to finish a step'}")
    _, run_op = await _target()
    started = _time.monotonic()
    _MCP_SESSION["handoff"] = {"reason": reason or "step for a person", "since": started}
    _notify_person(reason)
    try:
        probe = (
            "JSON.stringify({url: location.href, state: document.readyState, "
            f"sel: {_json_mod.dumps(selector)} ? !!document.querySelector({_json_mod.dumps(selector)}) : null, "
            f"txt: {_json_mod.dumps(text)} ? document.body.innerText.includes({_json_mod.dumps(text)}) : null, "
            "title: document.title})"
        )
        loop = _asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, float(timeout))
        last: dict = {}
        while True:
            data, err = await _eval_json(run_op, "await_user", probe)
            if err:
                return tool_error("await_user", "page_unreadable", err)
            last = data or {}
            ok = (
                (url_contains is None or url_contains in last.get("url", ""))
                and (selector is None or bool(last.get("sel")))
                and (text is None or bool(last.get("txt")))
            )
            if ok:
                break
            if loop.time() >= deadline:
                return tool_error("await_user", "timeout",
                                  f"conditions not met within {timeout:g}s; current url {last.get('url')!r}")
            await _asyncio.sleep(max(0.1, poll_ms / 1000.0))
    finally:
        _MCP_SESSION.pop("handoff", None)
    # Resume check: the person may have ended on an error page, or the page may still be loading.
    url = last.get("url", "")
    if url.startswith("chrome-error:"):
        return tool_error("await_user", "error_page", f"the page after the hand-off is an error page ({url})")
    if last.get("state") != "complete":
        return tool_error("await_user", "still_loading", "the page after the hand-off is still loading; call again")
    return tool_result("await_user", {
        "url": redact_url(url), "title": last.get("title", ""), "matched": True,
        "reason": reason, "waited_s": round(_time.monotonic() - started, 1),
    })


def _notify_person(reason: str | None) -> None:
    """Best-effort desktop notification that a person is needed. Silent when unavailable."""
    import shutil
    import subprocess

    if shutil.which("notify-send") is None:
        return
    try:
        subprocess.Popen(["notify-send", "Browser Helper", reason or "A step needs you in the browser"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


@_envelope_errors("select_option")
async def select_option(selector: str, value: str | None = None, label: str | None = None,
                        index: int | None = None, ctx: Context | None = None) -> str:
    """Choose one option of a <select> element (capability ``browser.core``, READY).

    Give exactly one of ``value`` (the option's value attribute), ``label`` (its
    visible text) or ``index`` (zero-based position). The change and input events
    are fired so page scripts see the new value.
    """
    chosen = [(k, v) for k, v in (("value", value), ("label", label), ("index", index)) if v is not None]
    if len(chosen) != 1:
        return tool_error("select_option", "invalid_params", "give exactly one of value, label or index")
    by, val = chosen[0]
    if ctx is not None:
        await ctx.info(f"select_option {selector} by {by}")
    _, run_op = await _target()
    js = (
        "(function(sel, by, val){"
        " const el = document.querySelector(sel);"
        " if (!el) return JSON.stringify({error: 'not_found'});"
        " if (el.tagName !== 'SELECT') return JSON.stringify({error: 'not_select', tag: el.tagName});"
        " let idx = -1;"
        " if (by === 'index') idx = Number(val);"
        " else for (let i = 0; i < el.options.length; i++) {"
        "   const o = el.options[i];"
        "   if ((by === 'value' && o.value === val) || (by === 'label' && o.text.trim() === val)) { idx = i; break; }"
        " }"
        " if (!(idx >= 0 && idx < el.options.length)) return JSON.stringify({error: 'no_such_option'});"
        " el.selectedIndex = idx;"
        " el.dispatchEvent(new Event('input', {bubbles: true}));"
        " el.dispatchEvent(new Event('change', {bubbles: true}));"
        " return JSON.stringify({value: el.value, label: el.options[idx].text.trim(), index: idx});"
        "})"
        f"({_json_mod.dumps(selector)}, {_json_mod.dumps(by)}, {_json_mod.dumps(val)})"
    )
    data, err = await _eval_json(run_op, "select_option", js)
    if err:
        return tool_error("select_option", "select_failed", err)
    data = data or {}
    if "error" in data:
        code = data["error"]
        messages = {
            "not_found": f"no element matches {selector!r}",
            "not_select": f"element is <{data.get('tag', '?').lower()}>, not a select",
            "no_such_option": f"no option matches {by}={val!r}",
        }
        return tool_error("select_option", code, messages.get(code, code))
    return tool_result("select_option", data)


_OVERLAY_JS = r"""(function(maxClicks){
  // Labels in the common languages of cookie banners and modal notices.
  const accept = /^(accept( all( cookies)?)?|allow( all)?|i agree|agree|got it|ok|okay|continue|i understand|understood|reject( all)?|decline( all)?|refuse( all)?|deny|no thanks|not now|later|skip|close|dismiss|alle akzeptieren|akzeptieren|alle ablehnen|ablehnen|verstanden|schlie(ss|ß)en|elfogadom|elfogad(ás|om)|összes elfogadása|elutasít(om)?|bezár|accepter|tout accepter|j'accepte|refuser|tout refuser|fermer|aceptar|aceptar todo|rechazar|cerrar|entendido|×|✕|✖|x)$/i;
  const closeLike = /close|dismiss|fermer|schlie(ss|ß)en|bezár|cerrar|×|✕|✖/i;
  const container = /cookie|consent|gdpr|banner|overlay|modal|popup|dialog|notice|notification|privacy|toast/i;
  const clicked = [];
  const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  // The overlay a button belongs to: a dialog, a modal, a fixed/sticky box or a named container.
  const overlayOf = (e) => {
    for (let n = e; n && n !== document.body && n !== document.documentElement; n = n.parentElement || (n.getRootNode() && n.getRootNode().host)) {
      if (n.nodeType !== 1) continue;
      const s = getComputedStyle(n);
      if (n.getAttribute('role') === 'dialog' || n.getAttribute('role') === 'alertdialog' || n.getAttribute('aria-modal') === 'true') return n;
      if ((s.position === 'fixed' || s.position === 'sticky') && visible(n)) return n;
      if (container.test((n.id || '') + ' ' + (typeof n.className === 'string' ? n.className : '') + ' ' + (n.getAttribute('aria-label') || ''))) return n;
    }
    return null;
  };
  // Buttons in the page and in open shadow roots (cookie banners are often web components).
  const buttons = [];
  const collect = (root) => {
    root.querySelectorAll('button, a[role=button], input[type=button], input[type=submit], [role=button], [aria-label]').forEach((b) => buttons.push(b));
    root.querySelectorAll('*').forEach((el) => { if (el.shadowRoot && el.shadowRoot.mode !== 'closed') collect(el.shadowRoot); });
  };
  collect(document);
  const answered = new Set();  // one decision per overlay: a second click would answer a second prompt
  for (const b of buttons) {
    if (clicked.length >= maxClicks) break;
    const text = (b.innerText || b.value || '').trim();
    const aria = (b.getAttribute('aria-label') || '').trim();
    const label = text || aria;
    const isClose = closeLike.test(aria) || closeLike.test(text);
    if (!(accept.test(label) || accept.test(aria) || isClose) || !visible(b)) continue;
    const overlay = overlayOf(b);
    // An overlay answered in an earlier pass stays on the page: skip it, or the loop clicks it again.
    if (!overlay || answered.has(overlay) || overlay.hasAttribute('data-bh-dismissed')) continue;
    answered.add(overlay);
    overlay.setAttribute('data-bh-dismissed', '1');
    b.click();
    clicked.push(label || aria);
  }
  return JSON.stringify({clicked: clicked});
})"""


@_envelope_errors("dismiss_overlays")
async def dismiss_overlays(max_clicks: int = 3, wait_ms: int = 2000,
                           ctx: Context | None = None) -> str:
    """Accept or close cookie banners, consent prompts and modal notices (capability ``browser.core``, READY).

    Looks in the page and in open shadow roots for buttons labelled as accept,
    reject, close or dismiss (English, German, Hungarian, French, Spanish, and
    the close icons) that sit inside a dialog, a modal or a fixed/sticky box.
    Clicks at most one button per overlay and at most ``max_clicks`` in total.
    Banners often appear after load, so it keeps looking for up to ``wait_ms``
    milliseconds (default 2000, max 10000). Returns the labels it clicked.
    """
    import asyncio as _asyncio

    if ctx is not None:
        await ctx.info("dismiss_overlays")
    _, run_op = await _target()
    limit = max(0, min(int(max_clicks), 10))
    deadline = _asyncio.get_running_loop().time() + max(0, min(int(wait_ms), 10000)) / 1000.0
    clicked: list[str] = []
    while True:
        remaining = max(0, limit - len(clicked))
        data, err = await _eval_json(run_op, "dismiss_overlays", f"{_OVERLAY_JS}({remaining})")
        if err:
            return tool_error("dismiss_overlays", "dismiss_failed", err)
        clicked.extend((data or {}).get("clicked", []))
        if len(clicked) >= limit or _asyncio.get_running_loop().time() >= deadline:
            break
        await _asyncio.sleep(0.3)
    return tool_result("dismiss_overlays", {"clicked": clicked})
