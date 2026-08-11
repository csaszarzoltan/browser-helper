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


async def mcp_export_cookies(session_id: str, ctx: Context | None = None) -> str:
    """Export every cookie for *session_id* as JSON text (capability ``diagnostics.cookies``, READY).

    Backed by the same engine as ``POST /session/{sid}/export-cookies``:
    resolves the session's CDP client and returns ``Network.getAllCookies``
    results with the stable keys ``name``, ``value``, ``domain``, ``path``,
    ``expires``, ``httpOnly``, ``secure``, ``sameSite``.
    """
    if ctx is not None:
        ctx.info(f"export_cookies -> session {session_id}")
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


async def export_cookies(session_id: str | None = None, ctx: Context | None = None) -> str:
    """Export all cookies from a session (capability ``browser.core``, READY).

    Returns CDP Cookie objects (name, value, domain, path, expires,
    httpOnly, secure, sameSite) for re-import into another session.

    Cookie values travel only over the direct client call and are never
    written to the operation log or chat.
    """
    if ctx is not None:
        ctx.info(f"export_cookies session={session_id}")
    try:
        target, _ = _resolve_cookie_target(session_id)
        res = await target.get_cookies()
        return tool_result("export_cookies", res)
    except KeyError as exc:
        return tool_error("export_cookies", "session_not_found", str(exc))
    except Exception as exc:
        return tool_error("export_cookies", "cookie_export_failed", str(exc))


async def import_cookies(cookies: list[dict], session_id: str | None = None,
                         ctx: Context | None = None) -> str:
    """Import cookies into a session (capability ``browser.core``, READY).

    Body cookies are CDP CookieParam shapes: {name, value, domain, path?,
    expires?, httpOnly?, secure?, sameSite?}.  Values are never echoed back
    into the operation log or chat — only a count is returned.
    """
    if ctx is not None:
        ctx.info(f"import_cookies session={session_id} n={len(cookies or [])}")
    cookies = cookies or []
    try:
        target, _ = _resolve_cookie_target(session_id)
        res = await target.set_cookies(cookies)
        return tool_result("import_cookies", res)
    except KeyError as exc:
        return tool_error("import_cookies", "session_not_found", str(exc))
    except Exception as exc:
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
        ctx.info(f"clone_session source={session_id}")
    try:
        source, src_sess = _resolve_cookie_target(session_id)
        res = await source.get_cookies()
        cookies = (res or {}).get("cookies", [])
        from main import _local_cdp_http, chrome_mgr, session_registry as _sr

        await chrome_mgr.launch()
        new_sess = await _sr.create(_local_cdp_http())
        imp = await new_sess.client.set_cookies(cookies)
        return tool_result("clone_session", {
            "session_id": new_sess.session_id,
            "cookies_copied": imp.get("imported", 0),
        })
    except KeyError as exc:
        return tool_error("clone_session", "session_not_found", str(exc))
    except Exception as exc:
        return tool_error("clone_session", "clone_failed", str(exc))


# ── Wait-for / assertion engine (v1.27.0, F2) ────────────────────────


async def wait_for(kind: str = "selector", value: str = "", condition: str = "present",
                   timeout: int = 10, ctx: Context | None = None) -> str:
    """Wait until a DOM condition holds (capability ``browser.core``, READY).

    kind=selector|text|url, condition=present|gone|visible.  Deterministic —
    no guessy sleeps; returns ok once the condition holds, error on timeout.
    """
    from main import client, run_op

    if ctx is not None:
        ctx.info(f"wait_for kind={kind} value={value} condition={condition} timeout={timeout}")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        res = await run_op_fn("wait_for", target.wait_for_condition,
                              kind, value, condition, timeout)
        return json_dumps({"status": "ok", "operation": "wait_for",
                           "data": res, "error": None, "meta": {}})
    except Exception as exc:
        return tool_error("wait_for", "wait_failed", str(exc))


async def assert_(kind: str = "selector", value: str = "", condition: str = "exists",
                  expected: int | str | None = None, ctx: Context | None = None) -> str:
    """Assert a DOM condition (capability ``browser.core``, READY).

    Returns a structured pass/fail; a failed assertion is reported as an
    error so the agent's test fails deterministically.
    """
    from main import client, run_op

    if ctx is not None:
        ctx.info(f"assert kind={kind} value={value} condition={condition} expected={expected}")
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
    except Exception as exc:
        return tool_error("assert", "assertion_failed", str(exc))


# ── Form-intelligence (v1.27.0, F3) ──────────────────────────────────


async def form_fill(fields: list[dict], timeout: int = 5, ctx: Context | None = None) -> str:
    """Fill SPA form fields by label/selector (capability ``browser.core``, READY).

    Each field: {label|selector|placeholder, value, nth?}.  Uses the
    value-setter technique (native setter + input/change/blur events) so
    React/Angular controlled inputs register the change.
    """
    from main import client, run_op

    if ctx is not None:
        ctx.info(f"form_fill fields={len(fields or [])}")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        res = await run_op_fn("form_fill", target.smart_form_fill, fields or [], timeout)
        return json_dumps({"status": "ok", "operation": "form_fill",
                           "data": res, "error": None, "meta": {}})
    except Exception as exc:
        return tool_error("form_fill", "form_fill_failed", str(exc))


async def form_extract(ctx: Context | None = None) -> str:
    """Extract the page's form structure (capability ``browser.core``, READY).

    Returns each form's fields: tag, type, name, label, placeholder,
    required, visible — feed the labels into form_fill.
    """
    from main import client, run_op

    if ctx is not None:
        ctx.info("form_extract")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        res = await run_op_fn("form_extract", target.form_extract)
        return json_dumps({"status": "ok", "operation": "form_extract",
                           "data": res, "error": None, "meta": {}})
    except Exception as exc:
        return tool_error("form_extract", "form_extract_failed", str(exc))
