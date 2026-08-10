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

import os

from mcp.server.fastmcp import Context  # typing only — never called here

from .serialization import json_dumps, tool_error, tool_result

# Process-scoped session holder for MCP calls (no cookies over stdio).
_MCP_SESSION = {"session": None}


async def _mcp_session():
    """Return (sess, run_op) for an MCP tool call, minting the session once.

    Falls back to (None, run_op) — the shared default client — when the
    browser is unavailable (legacy behaviour).
    """
    from main import _set_current_session, chrome_mgr, _local_cdp_http, run_op, session_registry

    # Test isolation: BH_TEST_NO_CHROME=1 (set by the MCP integration test
    # harness) forbids launching a real browser from the server subprocess.
    # Fall straight back to the default (disconnected) client so CDP-gated
    # tools fail deterministically with the "not connected" error.
    if os.environ.get("BH_TEST_NO_CHROME") == "1":
        _set_current_session(None)
        return None, run_op

    sess = _MCP_SESSION["session"]
    if sess is not None and sess.session_id in session_registry._sessions:
        _set_current_session(sess)
        return sess, run_op
    # No session yet, or it was reaped — mint a fresh one.
    try:
        await chrome_mgr.launch()
        sess = await session_registry.create(_local_cdp_http())
        _MCP_SESSION["session"] = sess
    except Exception:
        sess = None  # fall back to default client (legacy)
    _set_current_session(sess)
    return sess, run_op


async def _target():
    """Return (client_obj, run_op) for a handler — session client or default."""
    from main import client

    sess, run_op = await _mcp_session()
    return (sess.client if sess is not None else client), run_op


async def navigate(url: str, ctx: Context | None = None) -> str:
    """Navigate the active browser tab to *url* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /navigate``.
    """
    if ctx is not None:
        ctx.info(f"navigate -> {url}")
    target, run_op = await _target()
    return json_dumps(await run_op("navigate", target.navigate, url))


async def click(selector: str, ctx: Context | None = None) -> str:
    """Click a CSS selector in the active tab (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /click``.
    """
    if ctx is not None:
        ctx.info(f"click -> {selector}")
    target, run_op = await _target()
    return json_dumps(await run_op("click", target.click, selector))


async def type(selector: str, text: str, ctx: Context | None = None) -> str:
    """Type *text* into the element matched by *selector* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /type``.
    """
    if ctx is not None:
        ctx.info(f"type {len(text)} chars into {selector}")
    target, run_op = await _target()
    return json_dumps(await run_op("type", target.type_text, selector, text))


async def screenshot(ctx: Context | None = None) -> str:
    """Capture a JPEG screenshot of the active tab (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /screenshot``.
    """
    if ctx is not None:
        ctx.info("capturing screenshot")
    target, run_op = await _target()
    return json_dumps(await run_op("screenshot", target.screenshot))


async def snapshot(ctx: Context | None = None) -> str:
    """Return a comprehensive page analysis (capability ``agent.semantic``, READY).

    Backed by the same engine as ``POST /page/analyze``.
    """
    if ctx is not None:
        ctx.info("analyzing page")
    target, run_op = await _target()
    return json_dumps(await run_op("page_analyze", target.analyze_page))


async def observe(
    mode: str = "semantic",
    scope: str = "page",
    max_nodes: int = 250,
    interactive_only: bool = False,
    include_hidden: bool = False,
    condensed: bool = True,
    ctx: Context | None = None,
) -> str:
    """Observe the page as accessibility tree or semantic snapshot (capability ``agent.semantic``, READY).

    Backed by the same engine as ``POST /agent/observe``.
    """
    if ctx is not None:
        ctx.info(f"observe mode={mode} scope={scope}")
    # Use internal snapshot functions directly (same as REST endpoint)
    from main import _capture_accessibility_snapshot, _capture_agent_snapshot, _set_current_session, paginate_snapshot
    
    sess, run_op = await _mcp_session()  # local function
    _set_current_session(sess)
    
    try:
        target = sess.client if sess else None
        if mode.lower() in {"accessibility", "ax"}:
            snap = await _capture_accessibility_snapshot(
                scope=("dialog" if True and scope == "page" else scope),
                include=None, interactive_only=interactive_only,
                include_hidden=include_hidden,
                target=target,
            )
            data = snap.as_dict(max_nodes=min(max(max_nodes, 1), 1000))
        else:
            snap = await _capture_agent_snapshot(condensed, target=target)
            data = paginate_snapshot(snap, 6000, max_nodes, None)
        return tool_result("observe", data)
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
    ctx: Context | None = None,
) -> str:
    """Act on the page: click, fill, select, wait, navigate (capability ``agent.semantic``, READY).

    Backed by the same engine as ``POST /agent/act``. Use with observe's snapshot_id/ref.
    """
    if ctx is not None:
        ctx.info(f"act -> {action}")
    import json as _json
    import urllib.request as _ur
    from mcp_server.tools import _MCP_SESSION

    sess, run_op = await _mcp_session()
    target_dict = {
        "snapshot_id": snapshot_id,
        "ref": ref,
        "element_id": element_id,
        "selector": selector,
        "text": text,
        "label": label,
        "url": url,
        "value": value,
        "backend_node_id": None,
    }
    body = {
        "action": action,
        "target": {k: v for k, v in target_dict.items() if v is not None},
        "url": url,
        "value": value,
        "fields": fields,
        "option": option,
        "timeout": timeout,
        "expression": expression,
    }
    # Route through the running service to get identical behaviour
    try:
        cookie = ""
        if _MCP_SESSION.get("session") is not None:
            cookie = _MCP_SESSION["session"].session_id
        req = _ur.Request(
            f"http://127.0.0.1:8020/agent/act",
            data=_json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Session-ID": cookie},
            method="POST",
        )
        with _ur.urlopen(req, timeout=60) as resp:
            result = _json.loads(resp.read().decode())
        return tool_result("act", result.get("data", {}))
    except Exception as exc:  # noqa: BLE001
        return tool_error("act", "operation_failed", str(exc))


async def get_tabs(ctx: Context | None = None) -> str:
    """List all open tabs ``{id, title, url, active}`` (capability ``browser.core``, READY).

    Backed by the same engine as ``GET /tabs``.
    """
    if ctx is not None:
        ctx.info("listing tabs")
    target, run_op = await _target()
    return json_dumps(await run_op("get_tabs", target.get_tabs))


async def switch_tab(id: str, ctx: Context | None = None) -> str:
    """Switch the active tab to *id* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /switch_tab/{tab_id}``.
    """
    if ctx is not None:
        ctx.info(f"switch_tab -> {id}")
    target, run_op = await _target()
    return json_dumps(await run_op("switch_tab", target.switch_tab, id))


async def close_tab(id: str, ctx: Context | None = None) -> str:
    """Close the tab *id* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /tab/close/{tab_id}``.
    """
    if ctx is not None:
        ctx.info(f"close_tab -> {id}")
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
        ctx.info("reading session persistence status")
    try:
        sessions = _session_mgr.list_sessions()
        return tool_result(
            "session_status",
            {"sessions": sessions, "total": len(sessions)},
        )
    except Exception as exc:  # noqa: BLE001 — normalize to the envelope contract
        return tool_error("session_status", "operation_failed", str(exc))


# ── High-level tools (capability agent.search / agent.flow) ────────


async def search(query: str, engine: str = "google", timeout: int = 45,
                 ctx: Context | None = None) -> str:
    """One-call web search (capability ``agent.search``, READY).

    Navigates to the engine, runs *query*, waits for the answer, and returns
    the result text — no manual sleeps or extra reads.

    Engines: ``google`` (default, fastest — works since stealth v1.24),
    ``perplexity`` (AI answer, slower ~45s), ``ddg``, ``bing``.
    """
    from main import agent_search, AgentSearchRequest  # lazy import

    if ctx is not None:
        ctx.info(f"search {engine}: {query[:60]}")
    resp = await agent_search(AgentSearchRequest(query=query, engine=engine, timeout=timeout))
    return json_dumps(resp)


async def get_content(url: str | None = None, wait_ready: bool = True,
                      ctx: Context | None = None) -> str:
    """Load a URL (or use the current page) and return its main content
    (capability ``agent.search``, READY).

    Filters nav/sidebar/footer noise — cleaner context for LLMs.
    """
    from main import client, run_op  # lazy import

    if ctx is not None:
        ctx.info(f"get_content url={url}")
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
        ctx.info(f"run_flow {name} ({len(steps or [])} steps)")
    steps = steps or []
    if not steps:
        return tool_error("run_flow", "invalid_params", "steps is required")
    req = AgentFlowRequest(
        name=name,
        steps=[AgentFlowStep(**s) for s in steps],
        stop_on_error=stop_on_error,
    )
    resp = await agent_run_flow(req)
    return json_dumps(resp)
