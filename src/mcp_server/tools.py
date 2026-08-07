"""Browser tool handlers — direct engine calls (spec §5.1–§5.8).

One explicit typed ``async def`` handler per browser tool. Each wraps
``main.run_op(...)`` / ``main.client.*`` directly — never HTTP, never an LLM
(decision D2, anti-LLM gate §8.2). Returns a JSON string with the REST
envelope shape built by :mod:`mcp_server.serialization`.

The engine singletons (``main.client``, ``main.run_op``, ``main._session_mgr``)
are imported lazily inside each handler body so importing this module never
pulls the heavy FastAPI engine stack, and so tests can patch ``main.run_op``
by attribute.
"""

from __future__ import annotations

from mcp.server.fastmcp import Context  # typing only — never called here

from .serialization import json_dumps, tool_error, tool_result


async def navigate(url: str, ctx: Context | None = None) -> str:
    """Navigate the active browser tab to *url* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /navigate``: ``run_op("navigate", client.navigate, url)``.
    """
    from main import client, run_op  # lazy import — engine singletons

    if ctx is not None:
        ctx.info(f"navigate -> {url}")
    return json_dumps(await run_op("navigate", client.navigate, url))


async def click(selector: str, ctx: Context | None = None) -> str:
    """Click a CSS selector in the active tab (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /click``: ``run_op("click", client.click, selector)``.
    """
    from main import client, run_op  # lazy import — engine singletons

    if ctx is not None:
        ctx.info(f"click -> {selector}")
    return json_dumps(await run_op("click", client.click, selector))


async def type(selector: str, text: str, ctx: Context | None = None) -> str:
    """Type *text* into the element matched by *selector* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /type``: ``run_op("type", client.type_text, selector, text)``.
    """
    from main import client, run_op  # lazy import — engine singletons

    if ctx is not None:
        ctx.info(f"type {len(text)} chars into {selector}")
    return json_dumps(await run_op("type", client.type_text, selector, text))


async def screenshot(ctx: Context | None = None) -> str:
    """Capture a JPEG screenshot of the active tab (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /screenshot``: ``run_op("screenshot", client.screenshot)``.
    """
    from main import client, run_op  # lazy import — engine singletons

    if ctx is not None:
        ctx.info("capturing screenshot")
    return json_dumps(await run_op("screenshot", client.screenshot))


async def snapshot(ctx: Context | None = None) -> str:
    """Return a comprehensive page analysis (capability ``agent.semantic``, READY).

    Backed by the same engine as ``POST /page/analyze``:
    ``run_op("page_analyze", client.analyze_page)``.
    """
    from main import client, run_op  # lazy import — engine singletons

    if ctx is not None:
        ctx.info("analyzing page")
    return json_dumps(await run_op("page_analyze", client.analyze_page))


async def get_tabs(ctx: Context | None = None) -> str:
    """List all open tabs ``{id, title, url, active}`` (capability ``browser.core``, READY).

    Backed by the same engine as ``GET /tabs``: ``run_op("get_tabs", client.get_tabs)``.
    """
    from main import client, run_op  # lazy import — engine singletons

    if ctx is not None:
        ctx.info("listing tabs")
    return json_dumps(await run_op("get_tabs", client.get_tabs))


async def switch_tab(id: str, ctx: Context | None = None) -> str:
    """Switch the active tab to *id* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /switch_tab/{tab_id}``:
    ``run_op("switch_tab", client.switch_tab, id)``.
    """
    from main import client, run_op  # lazy import — engine singletons

    if ctx is not None:
        ctx.info(f"switch_tab -> {id}")
    return json_dumps(await run_op("switch_tab", client.switch_tab, id))


async def close_tab(id: str, ctx: Context | None = None) -> str:
    """Close the tab *id* (capability ``browser.core``, READY).

    Backed by the same engine as ``POST /tab/close/{tab_id}``:
    ``run_op("close_tab", client.close_tab, id)``.
    """
    from main import client, run_op  # lazy import — engine singletons

    if ctx is not None:
        ctx.info(f"close_tab -> {id}")
    return json_dumps(await run_op("close_tab", client.close_tab, id))


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
