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
    from main import _set_current_session, run_op, session_registry

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
        return sess, (lambda op, method, *a, **kw: run_op(op, method, *a, sess_override=sess, **kw))
    # No session cached yet — let run_op mint it lazily on the first browser
    # op (it launches Chrome and waits for the warm-up itself, avoiding the
    # double-launch race). session_hook caches the minted session so every
    # later tool call reuses the same tab instead of piling up new ones.
    def _cache_sess(s):
        _MCP_SESSION["session"] = s

    return None, (lambda op, method, *a, **kw: run_op(op, method, *a, session_hook=_cache_sess, **kw))


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
    result = await run_op("click", target.click, selector)
    # Unwrap the run_op envelope: the inner data.status can be "error" even
    # though the envelope is "ok" — turn "Element not found" into a useful
    # tool result instead of a misleading success JSON.
    inner = result.get("data") if isinstance(result, dict) else None
    if isinstance(inner, dict) and inner.get("status") == "error":
        err = str(inner.get("error", ""))
        if "not found" in err.lower() or "no element" in err.lower():
            return json_dumps({"status": "error", "error": f"Element not found for selector {selector!r} on the current tab"})
    return json_dumps(result)


async def type(selector: str, text: str, ctx: Context | None = None) -> str:
    """Type *text* into the element matched by *selector* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /type``.
    """
    if ctx is not None:
        ctx.info(f"type {len(text)} chars into {selector}")
    target, run_op = await _target()
    result = await run_op("type", target.type_text, selector, text)
    inner = result.get("data") if isinstance(result, dict) else None
    if isinstance(inner, dict) and inner.get("status") == "error":
        err = str(inner.get("error", ""))
        if "not found" in err.lower() or "no element" in err.lower():
            return json_dumps({"status": "error", "error": f"Element not found for selector {selector!r} on the current tab"})
    return json_dumps(result)


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
    from main import (
        _capture_accessibility_snapshot,
        _capture_agent_snapshot,
        _set_current_session,
        paginate_snapshot,
    )
    
    _sess, _run_op = await _mcp_session()  # local function
    _set_current_session(_sess)

    try:
        target = _sess.client if _sess else None
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

    _sess, _run_op = await _mcp_session()
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
        import asyncio

        cookie = ""
        if _MCP_SESSION.get("session") is not None:
            cookie = _MCP_SESSION["session"].session_id

        def _blocking_act_request() -> dict:
            req = _ur.Request(
                "http://127.0.0.1:8020/agent/act",
                data=_json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "X-Session-ID": cookie},
                method="POST",
            )
            with _ur.urlopen(req, timeout=60) as resp:
                return _json.loads(resp.read().decode())

        result = await asyncio.to_thread(_blocking_act_request)
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
    from main import AgentSearchRequest, agent_search  # lazy import

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
    from main import client  # lazy import

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


async def export_cookies(session_id: str, ctx: Context | None = None) -> str:
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
        ctx.info(f"import_cookies session={session_id} n={len(cookies or [])}")
    cookies = cookies or []
    try:
        target, _ = _resolve_cookie_target(session_id)
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
        ctx.info(f"clone_session source={session_id}")
    try:
        _source, _src_sess = _resolve_cookie_target(session_id)
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
        ctx.info(f"wait_for kind={kind} value={value} condition={condition} timeout={timeout}")
    sess, run_op_fn = await _mcp_session()
    target = sess.client if sess is not None else client
    try:
        res = await run_op_fn("wait_for", target.wait_for_condition,
                              kind, value, condition, timeout)
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
        ctx.info(f"form_fill fields={len(fields or [])}")
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
        ctx.info("form_extract")
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
        ctx.info(f"download url={url}")
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
    from main import client, run_op

    if ctx is not None:
        ctx.info(f"network_block patterns={len(patterns)}")
    try:
        result = await run_op("network_block", client.set_network_block, patterns)
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
    from main import client, run_op

    if ctx is not None:
        ctx.info(f"network_mock mocks={len(mocks)}")
    try:
        result = await run_op("network_mock", client.set_request_mocks, mocks)
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
        ctx.info("reading notifications")
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
        ctx.info("starting notification monitoring")
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
        ctx.info("reading network requests")
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
        ctx.info("reading console errors")
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
        ctx.info(f"waiting for JS (timeout={timeout}s)")
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
        return tool_result("wait_js", data)
    except Exception as exc:  # noqa: BLE001
        return tool_error("wait_js", "failed", str(exc))


async def eval(js: str, timeout: int = 30, ctx: Context | None = None) -> str:
    """Execute JS directly and return the value (capability ``browser.core``, READY).

    Calls ``client.evaluate_js`` directly — no snapshot round-trip.

    Examples::

        eval("document.title")
        eval("window.__APP_STATE__")
        eval("document.querySelectorAll('a').length")
    """
    target, _run_op = await _target()
    if ctx is not None:
        ctx.info(f"eval js ({len(js)} chars, timeout={timeout}s)")
    try:
        result = await target.evaluate_js(js)
        return tool_result("eval", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("eval", "failed", str(exc))


async def get_page_text(
    wait_ready: bool = True,
    timeout: int = 20,
    ctx: Context | None = None,
) -> str:
    """Get visible page text (capability ``browser.core``, READY).

    Optionally waits for the page to reach ready (network idle + stable DOM)
    before extracting, same as ``get_content`` with the cleaner main-content
    filter stripped.  Alias for ``client.get_page_text`` with wait handling.
    """
    target, run_op_fn = await _target()
    if ctx is not None:
        ctx.info(f"get_page_text wait_ready={wait_ready} timeout={timeout}")
    try:
        if wait_ready:
            try:
                await run_op_fn("get_page_text_wait", target.wait_for_ready, timeout)
            except Exception:  # noqa: BLE001,S110 — wait is best-effort; text still readable
                pass
        result = await target.get_page_text()
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
        ctx.info(f"querying element: {selector}")
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
        ctx.info(f"press_key {key}" + (f" @ {selector}" if selector else ""))
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
        ctx.info(f"hover {selector}")
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
        ctx.info(f"scroll x={x} y={y}" + (f" @ {selector}" if selector else ""))
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
        ctx.info(f"reload ignore_cache={ignore_cache}")
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
        ctx.info(f"wait_network_idle timeout={timeout}s quiet_ms={quiet_ms}")
    try:
        result = await run_op_fn(
            "wait_for_network_idle", target.wait_for_network_idle, timeout, quiet_ms
        )
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
        ctx.info("rate_limiter_status")
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
        ctx.info(f"dialog_handle {action}")
    try:
        if action == "accept":
            result = await target.dialog_accept(prompt_text)
        else:
            result = await target.dialog_dismiss()
        return tool_result("dialog_handle", result)
    except Exception as exc:  # noqa: BLE001
        return tool_error("dialog_handle", "failed", str(exc))
