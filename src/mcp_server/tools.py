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
    # P0-1: MCP stdio has no HTTP middleware — force auto-mint so the first
    # browser tool never 400s with "Missing session". Mirrors BH_SESSION_AUTO=1.
    try:
        from main import _session_auto as _mcp_auto
        _mcp_auto.set(True)
    except Exception:
        pass
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
    }
    # Only include set fields — the REST schema rejects explicit nulls with
    # 422 Unprocessable (observed 2026-09-02: MCP act navigate 422 because
    # "url": null / "fields": null were sent alongside).
    for _k in ("url", "value", "fields", "option", "timeout", "expression"):
        _v = locals().get(_k)
        if _v is not None:
            body[_k] = _v
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
        ctx.info(f"browser_get_accessibility_tree scope={scope} max_nodes={max_nodes}")
    try:
        from main import _capture_accessibility_snapshot
        target, _ = await _target()
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
        ctx.info(f"browser_find_semantic_elements query={query!r} role={role}")
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
        ctx.info("browser_get_page_structure")
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
    ctx = None,
) -> str:
    """Navigate with load strategy (capability ``browser.core``, READY). P0-3: origins / storageState before paint."""
    if ctx is not None:
        ctx.info(f"browser_navigate {url} wait_until={wait_until} settle={settle} origins={bool(origins or storage_state)}")
    try:
        target, run_op = await _target()
        if wait_until and wait_until not in _NEGOTIATE:
            return tool_error("browser_navigate", "invalid_wait_until", "must be domContentLoaded|load|networkIdle")
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
                except Exception:
                    pass
        res = await run_op("navigate", target.navigate, url)
        if settle:
            try:
                tout = min(max(int(timeout), 1), 30)
                extra = await run_op("navigate_settle", target.wait_for_network_idle, tout, 800)  # type: ignore[arg-type]
                if isinstance(res, dict):
                    d = res.get("data") or {}
                    d["settle"] = extra if isinstance(extra, dict) else {}
            except Exception:  # noqa: BLE001
                pass
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
        ctx.info(f"browser_interact {action} {selector}")
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
            except Exception:  # noqa: BLE001
                pass
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
        ctx.info(f"browser_upload_file {selector} <- {path}")
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
                except Exception:
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
        ctx.info(f"browser_download_file {url}")
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
        ctx.info(f"browser_get_console_logs level={level}")
    try:
        target, _ = await _target()
        try:
            await target.start_console_monitoring()
        except Exception:  # noqa: BLE001
            pass
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
        ctx.info("browser_get_network_activity")
    try:
        target, _ = await _target()
        try:
            await target.start_network_monitoring()
        except Exception:  # noqa: BLE001
            pass
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
        ctx.info(f"browser_wait_for_condition {('js' if js else 'selector')}")
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
        ctx.info(f"browser_take_screenshot scope={scope}")
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
        ctx.info(f"browser_highlight_elements {len(selectors)} targets")
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
        ctx.info(f"browser_start_recorder {name or '-'} ac={ac}")
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
                except Exception:
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
        if isinstance(inner, dict) and redisc:
            if ac:
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
        ctx.info(f"browser_record_step: {step}")
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
        ctx.info("browser_export_playwright_spec")
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
        ctx.info(f"browser_inject_storage_state tenant={tenant or '-'}")
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
            except Exception:  # noqa: BLE001
                pass
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
                except Exception:  # noqa: BLE001
                    pass
        if tenant and str(tenant).strip():
            try:
                import json as _j
                await target.evaluate(f"localStorage.setItem('tenant', {_j.dumps(str(tenant).strip())})")
                counts["origins"] += 1
            except Exception:  # noqa: BLE001
                pass
        return tool_result("browser_inject_storage_state", {"injected": counts, "tenant": tenant})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_inject_storage_state", "injection_failed", str(exc))


async def browser_reset_session(
    scope: str = "all",
    ctx = None,
) -> str:
    """Clear cache / cookies / storage between tests (capability ``browser.core``, READY)."""
    sc = (scope or "all").lower().strip()
    if sc not in {"cookies", "storage", "all"}:
        return tool_error("browser_reset_session", "invalid_scope", "scope must be cookies|storage|all")
    if ctx is not None:
        ctx.info(f"browser_reset_session scope={sc}")
    try:
        target, _ = await _target()
        done: dict[str, bool] = {}
        if sc in ("cookies", "all"):
            try:
                await target.clear_browser_cookies()  # type: ignore[attr-defined]
                done["cookies"] = True
            except AttributeError:
                await target._send_command("Network.clearBrowserCookies")
                done["cookies"] = True
            except Exception as exc:  # noqa: BLE001
                return tool_error("browser_reset_session", "clear_cookies_failed", str(exc))
        if sc in ("storage", "all"):
            try:
                await target.evaluate("localStorage.clear(); sessionStorage.clear();")
                done["storage"] = True
            except Exception as exc:  # noqa: BLE001
                return tool_error("browser_reset_session", "clear_storage_failed", str(exc))
        if sc == "all":
            try:
                await target.clear_browser_cache()  # type: ignore[attr-defined]
                done["cache"] = True
            except Exception:  # noqa: BLE001
                done["cache"] = False
        return tool_result("browser_reset_session", {"scope": sc, "cleared": done})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_reset_session", "failed", str(exc))
