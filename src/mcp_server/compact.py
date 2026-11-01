"""Compact MCP profile: two tools (``bh`` and ``describe``) in place of the full surface.

Every action of the full profile stays callable as ``bh(action, args)``; the schema
of an action is fetched on demand with ``describe(action)``. This keeps the
``tools/list`` payload (paid in every turn) at a few KB instead of ~57 KB.

Selected with env ``MCP_PROFILE=compact``.
"""

from __future__ import annotations

import difflib
import inspect
from typing import Any

from mcp.server.fastmcp import Context  # typing only — FastMCP injects it by annotation

from .registry import ToolDef, ToolDefRegistry
from .serialization import tool_error, tool_result

_BH_DESCRIPTION = (
    "Run one browser-helper action: bh(action, args). The actions are the enum of "
    "'action'; args is that action's argument object. Call describe(action) for an "
    "action's arguments before the first use. Typical flow: navigate, observe, act."
)
_DESCRIBE_DESCRIPTION = (
    "Without action: list every action of bh with a one-line summary. With action: "
    "its full description and argument schema."
)


def _summary(description: str) -> str:
    """First sentence of a tool description, for the action list."""
    first = description.split(". ", 1)[0].strip()
    return first if first.endswith(".") else first + "."


def _accepted_kwargs(handler) -> tuple[set[str], bool]:
    """Names the handler takes (without ctx) and whether it takes **kwargs."""
    params = inspect.signature(handler).parameters.values()
    takes_var = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    return {p.name for p in params if p.kind is not inspect.Parameter.VAR_KEYWORD and p.name != "ctx"}, takes_var


def _unknown_action(operation: str, action: str, names: list[str]) -> str:
    close = difflib.get_close_matches(action, names, n=3)
    hint = f" Did you mean: {', '.join(close)}?" if close else ""
    return tool_error(
        operation, "unknown_action",
        f"unknown action {action!r}.{hint} describe() lists the actions.",
        {"actions": names} if not close else {"did_you_mean": close},
    )


def compact_tool_defs(full: ToolDefRegistry) -> ToolDefRegistry:
    """Build the two-tool registry that fronts *full*."""
    from jsonschema import Draft202012Validator

    by_name = {t.name: t for t in full}
    names = sorted(by_name)

    async def bh(action: str, args: dict | None = None, ctx: Context | None = None) -> str:
        tool = by_name.get(action)
        if tool is None:
            return _unknown_action("bh", action, names)
        args = dict(args or {})
        accepted, takes_var = _accepted_kwargs(tool.handler)
        unknown = sorted(set(args) - accepted)
        if unknown and not takes_var:
            return tool_error(
                action, "invalid_args",
                f"unknown argument(s) {unknown} for {action}; accepted: {sorted(accepted)}. "
                f"describe({action!r}) gives the schema.",
            )
        errors = sorted(Draft202012Validator(tool.parameters).iter_errors(args), key=lambda e: list(e.path))
        if errors:
            where = lambda e: ".".join(str(p) for p in e.path) or "args"  # noqa: E731
            return tool_error(
                action, "invalid_args",
                "; ".join(f"{where(e)}: {e.message}" for e in errors[:5])
                + f". describe({action!r}) gives the schema.",
            )
        kwargs = dict(args)
        if "ctx" in inspect.signature(tool.handler).parameters:
            kwargs["ctx"] = ctx
        return await tool.handler(**kwargs)

    async def describe(action: str | None = None, ctx: Context | None = None) -> str:
        if action is None:
            return tool_result("describe", {
                "actions": {n: _summary(by_name[n].description) for n in names},
            })
        tool = by_name.get(action)
        if tool is None:
            return _unknown_action("describe", action, names)
        return tool_result("describe", {
            "action": tool.name,
            "description": tool.description,
            "args_schema": tool.parameters,
        })

    bh_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": names},
            "args": {"type": "object", "description": "Arguments of the action"},
        },
        "required": ["action"],
    }
    describe_schema = {
        "type": "object",
        "properties": {"action": {"type": "string", "description": "Action to describe; omit to list all"}},
    }
    status = next(iter(full)).status
    return ToolDefRegistry([
        ToolDef("bh", _BH_DESCRIPTION, bh_schema, "browser.core", status, bh),
        ToolDef("describe", _DESCRIBE_DESCRIPTION, describe_schema, "browser.core", status, describe),
    ])
