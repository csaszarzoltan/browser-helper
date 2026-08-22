"""ToolDef registry — capability-derived MCP tool surface (pre-dev stub).

SDK-free by design (spec §2.2 / §8.4): this module must never import ``mcp``
or ``main`` so registry-only unit tests run in SDK-less environments.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from capability_registry import CapabilityRegistry, CapabilityStatus

# Authoritative tool -> capability mapping (spec §4.3). The MCP layer owns
# parameter schemas (decision D4); the registry stays the source of truth for
# which capabilities exist and their readiness.
_TOOL_CAPABILITY = {
    "navigate": "browser.core",
    "click": "browser.core",
    "type": "browser.core",
    "screenshot": "browser.core",
    "snapshot": "agent.semantic",
    "get_tabs": "browser.core",
    "switch_tab": "browser.core",
    "close_tab": "browser.core",
    "session_status": "diagnostics.privacy",
    "export_cookies": "diagnostics.cookies",
    "search": "agent.search",
    "get_content": "agent.search",
    "run_flow": "agent.flow",
    "fleet_nodes": "workflow.local",
    "fleet_status": "workflow.local",
    "fleet_queue": "workflow.local",
    # Agent semantic tools
    "observe": "agent.semantic",
    "act": "agent.semantic",
    # Persistent memory tools (F1 fix — registered on server surface)
    "memory_remember": "memory.persistent",
    "memory_recall": "memory.persistent",
    "memory_forget": "memory.persistent",
    "memory_list": "memory.persistent",
    # Auth-session clone / cookie porting (v1.27.0, F1)
    "import_cookies": "diagnostics.cookies",
    "clone_session": "diagnostics.cookies",
    # Wait-for / assertion engine (v1.27.0, F2)
    "wait_for": "browser.core",
    "assert": "browser.core",
    # Form-intelligence (v1.27.0, F3)
    "form_fill": "browser.core",
    "form_extract": "browser.core",
    # Fleet run-batch (v1.27.0, F4)
    "fleet_run_batch": "workflow.local",
    # Download helper (v1.27.0, F5)
    "download": "browser.core",
    # Network interception (v1.27.0, F6)
    "network_block": "browser.core",
    "network_mock": "browser.core",
    # Agent testing helpers (v1.27.8)
    "get_notifications": "agent.testing",
    "notifications_start": "agent.testing",
    "get_network_requests": "browser.core",
    "get_console_errors": "agent.testing",
    "wait_js": "agent.testing",
    "element_state": "agent.testing",
    # Direct JS eval + page text alias (A1+A4)
    "eval": "browser.core",
    "get_page_text": "browser.core",
    # B5+B6: press_key / hover / scroll / reload / wait_network_idle
    "press_key": "browser.core",
    "hover": "browser.core",
    "scroll": "browser.core",
    "reload": "browser.core",
    "wait_network_idle": "browser.core",
    # C9+C10: rate_limiter_status + dialog_handle
    "rate_limiter_status": "browser.core",
    "dialog_handle": "browser.core",
}

# Authored JSON Schemas per tool (spec §8.1): `type: "object"` + `properties`
# with the exact required params. These are the pre-tester contract and the
# FastMCP inputSchema gate (non-empty per tool).
_TOOL_PARAM_SCHEMAS: dict[str, dict[str, Any]] = {
    "navigate": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to navigate to"}},
        "required": ["url"],
    },
    "click": {
        "type": "object",
        "properties": {"selector": {"type": "string", "description": "CSS selector"}},
        "required": ["selector"],
    },
    "type": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector"},
            "text": {"type": "string", "description": "Text to type"},
        },
        "required": ["selector", "text"],
    },
    "screenshot": {"type": "object", "properties": {}},
    "snapshot": {"type": "object", "properties": {}},
    "get_tabs": {"type": "object", "properties": {}},
    "observe": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "description": "semantic|accessibility (default semantic)"},
            "scope": {"type": "string", "description": "page|dialog|viewport (default page)"},
            "max_nodes": {"type": "integer", "description": "Max nodes (default 250)"},
            "interactive_only": {"type": "boolean", "description": "Only interactive elements (default false)"},
            "include_hidden": {"type": "boolean", "description": "Include hidden nodes (default false)"},
            "condensed": {"type": "boolean", "description": "Condensed semantic snapshot (default true)"},
        },
    },
    "act": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "click|fill|select|wait|navigate|select_tab|wait_for_element|wait_for_text|eval|screenshot"},
            "snapshot_id": {"type": "string", "description": "Snapshot id from observe (pin target)"},
            "ref": {"type": "string", "description": "AX ref of the element (from observe accessibility)"},
            "element_id": {"type": "string", "description": "Element id from semantic snapshot"},
            "selector": {"type": "string", "description": "CSS selector alternative"},
            "text": {"type": "string", "description": "Text to find or type"},
            "label": {"type": "string", "description": "Label for fill/select"},
            "url": {"type": "string", "description": "URL for navigate action"},
            "value": {"type": "string", "description": "Value for fill/type"},
            "fields": {"type": "array", "description": "List of {label, value} for fill"},
            "option": {"type": "string", "description": "Option for select"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 10)"},
            "expression": {"type": "string", "description": "JS expression for eval action"},
        },
        "required": ["action"],
    },
    "switch_tab": {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "Tab id"}},
        "required": ["id"],
    },
    "close_tab": {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "Tab id"}},
        "required": ["id"],
    },
    "session_status": {"type": "object", "properties": {}},
    "search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "engine": {"type": "string", "description": "perplexity|google|ddg|bing (default perplexity)"},
            "timeout": {"type": "integer", "description": "Max seconds to wait for the answer"},
        },
        "required": ["query"],
    },
    "get_content": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to load (optional — uses current page if omitted)"},
            "wait_ready": {"type": "boolean", "description": "Wait for page ready before extracting"},
        },
    },
    "run_flow": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Flow name"},
            "steps": {"type": "array", "description": "List of {action, url?, text?, selector?, value?, timeout?, expect?}"},
            "stop_on_error": {"type": "boolean"},
        },
        "required": ["steps"],
    },
    "fleet_nodes": {"type": "object", "properties": {}},
    "fleet_status": {"type": "object", "properties": {}},
    "fleet_queue": {"type": "object", "properties": {}},
    # Persistent memory tool schemas (F1 fix)
    "memory_remember": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Unique memory identifier"},
            "content": {"type": "string", "description": "Memory content text"},
            "metadata": {"type": "string", "description": "Optional JSON metadata string"},
        },
        "required": ["key", "content"],
    },
    "memory_recall": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (default 10)"},
        },
        "required": ["query"],
    },
    "memory_forget": {
        "type": "object",
        "properties": {
            "key_or_id": {"type": "string", "description": "Key or id to forget"},
        },
        "required": ["key_or_id"],
    },
    "memory_list": {
        "type": "object",
        "properties": {
            "filter": {"type": "string", "description": "Optional metadata filter"},
        },
    },
    # Auth-session clone / cookie porting (v1.27.0, F1)
    "export_cookies": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Source session id (optional — uses current session)"},
        },
        "required": ["session_id"],
    },
    "import_cookies": {
        "type": "object",
        "properties": {
            "cookies": {"type": "array", "description": "List of CDP CookieParam dicts: {name, value, domain, path?, expires?, httpOnly?, secure?, sameSite?}"},
            "session_id": {"type": "string", "description": "Target session id (optional — uses current session)"},
        },
        "required": ["cookies"],
    },
    "clone_session": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Source session id to clone (optional — uses current session)"},
        },
    },
    # Wait-for / assertion engine (v1.27.0, F2)
    "wait_for": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "selector|text|url (default selector)"},
            "value": {"type": "string", "description": "CSS selector, text substring, or URL substring"},
            "condition": {"type": "string", "description": "present|gone|visible (default present)"},
            "timeout": {"type": "integer", "description": "Max seconds to wait (default 10)"},
        },
        "required": ["value"],
    },
    "assert": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "selector|text|url (default selector)"},
            "value": {"type": "string", "description": "CSS selector, text substring, or URL substring"},
            "condition": {"type": "string", "description": "exists|not_exists|count|contains (default exists)"},
            "expected": {"oneOf": [{"type": "integer"}, {"type": "string"}], "description": "Expected count (int) or substring (str)"},
        },
        "required": ["value"],
    },
    # Form-intelligence (v1.27.0, F3)
    "form_fill": {
        "type": "object",
        "properties": {
            "fields": {"type": "array", "description": "List of {label|selector|placeholder, value, nth?} field descriptors"},
            "timeout": {"type": "integer", "description": "Max seconds per field (default 5)"},
        },
        "required": ["fields"],
    },
    "form_extract": {
        "type": "object",
        "properties": {},
    },
    # Fleet run-batch (v1.27.0, F4)
    "fleet_run_batch": {
        "type": "object",
        "properties": {
            "tasks": {"type": "array", "description": "List of {url, action?, assert_selector?, assert_text?, timeout?} — at least 1, max 50"},
            "concurrency": {"type": "integer", "description": "Parallel tasks (default 4, max 8)"},
        },
        "required": ["tasks"],
    },
    # Download helper (v1.27.0, F5)
    "download": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to download (navigates the current tab)"},
            "timeout": {"type": "integer", "description": "Max seconds to wait for the file (default 30)"},
        },
        "required": ["url"],
    },
    # Network interception (v1.27.0, F6)
    "network_block": {
        "type": "object",
        "properties": {
            "patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URL regex patterns to block (empty list clears)",
            },
        },
        "required": ["patterns"],
    },
    "network_mock": {
        "type": "object",
        "properties": {
            "mocks": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Mock rules: {pattern, status, body, content_type} (empty list clears)",
            },
        },
        "required": ["mocks"],
    },
    # Agent testing helpers (v1.27.8)
    "get_notifications": {
        "type": "object",
        "properties": {
            "since": {"type": "number", "description": "Only entries with timestamp >= this value (unix seconds)"},
            "limit": {"type": "integer", "description": "Max entries to return (default 50)"},
        },
    },
    "notifications_start": {
        "type": "object",
        "properties": {},
    },
    "get_network_requests": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Filter by URL path substring (e.g. '/api/')"},
            "method": {"type": "string", "description": "Filter by HTTP method (GET, POST, …)"},
            "status": {"type": "integer", "description": "Filter by HTTP status code"},
            "since": {"type": "number", "description": "Only entries with timestamp >= this value"},
            "limit": {"type": "integer", "description": "Max entries to return (default 100)"},
        },
    },
    "get_console_errors": {
        "type": "object",
        "properties": {
            "since": {"type": "number", "description": "Only errors with timestamp >= this value"},
            "limit": {"type": "integer", "description": "Max errors to return (default 50)"},
        },
    },
    "wait_js": {
        "type": "object",
        "properties": {
            "js": {"type": "string", "description": "JS expression that should return truthy when condition is met"},
            "timeout": {"type": "integer", "description": "Max seconds to wait (default 30, polls every 200ms)"},
        },
        "required": ["js"],
    },
    "element_state": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector of the element to inspect"},
        },
        "required": ["selector"],
    },
    # Direct JS eval (A1) — calls client.evaluate_js without snapshot
    "eval": {
        "type": "object",
        "properties": {
            "js": {"type": "string", "description": "JavaScript expression to evaluate in the page"},
            "timeout": {"type": "integer", "description": "Max seconds to wait (default 30)"},
        },
        "required": ["js"],
    },
    # Page text alias (A4) — calls client.get_page_text
    "get_page_text": {
        "type": "object",
        "properties": {
            "wait_ready": {"type": "boolean", "description": "Wait for page ready before extracting (default true)"},
            "timeout": {"type": "integer", "description": "Max seconds to wait for ready (default 20)"},
        },
    },
    # B5+B6: press_key / hover / scroll / reload / wait_network_idle
    "press_key": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key name (Enter, Escape, ArrowDown, Tab, Backspace, etc.)"},
            "selector": {"type": "string", "description": "Optional CSS selector to focus before pressing"},
        },
        "required": ["key"],
    },
    "hover": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector to hover over"},
        },
        "required": ["selector"],
    },
    "scroll": {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Horizontal scroll delta (default 0)"},
            "y": {"type": "integer", "description": "Vertical scroll delta (default 0)"},
            "selector": {"type": "string", "description": "Optional CSS selector of scrollable element"},
        },
    },
    "reload": {
        "type": "object",
        "properties": {
            "ignore_cache": {"type": "boolean", "description": "Bypass HTTP cache if true (hard reload, default false)"},
        },
    },
    "wait_network_idle": {
        "type": "object",
        "properties": {
            "timeout": {"type": "integer", "description": "Max seconds to wait (default 10)"},
            "quiet_ms": {"type": "integer", "description": "Ms of silence to confirm idle (default 500)"},
        },
    },
    # C9+C10: rate_limiter_status + dialog_handle
    "rate_limiter_status": {"type": "object", "properties": {}},
    "dialog_handle": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "accept|dismiss — dialog action"},
            "prompt_text": {"type": "string", "description": "Prompt text when accepting a prompt() dialog (optional)"},
        },
        "required": ["action"],
    },
}


@dataclass(frozen=True, slots=True)
class ToolDef:
    """A registered MCP tool (spec §4.1)."""

    name: str
    description: str
    parameters: dict[str, Any]
    capability_id: str
    status: CapabilityStatus
    handler: Callable[..., Awaitable[str]]


class ToolDefRegistry:
    """Sorted, deduplicated registry of ToolDefs (spec §4.2)."""

    def __init__(self, tool_defs: Iterable[ToolDef]) -> None:
        self._defs: list[ToolDef] = []
        seen: set[str] = set()
        for tool in sorted(tool_defs, key=lambda t: t.name):
            if tool.name in seen:
                raise ValueError(f"duplicate tool name: {tool.name}")
            if tool.status is CapabilityStatus.UNAVAILABLE:
                raise ValueError(
                    f"tool {tool.name!r} backed by UNAVAILABLE capability "
                    f"{tool.capability_id!r} — never register UNAVAILABLE tools"
                )
            seen.add(tool.name)
            self._defs.append(tool)

    def by_name(self, name: str) -> ToolDef | None:
        for tool in self._defs:
            if tool.name == name:
                return tool
        return None

    def capabilities(self) -> list[str]:
        return sorted({tool.capability_id for tool in self._defs})

    def __iter__(self) -> Iterator[ToolDef]:
        return iter(self._defs)

    def __len__(self) -> int:
        return len(self._defs)


def build_tool_defs(registry: CapabilityRegistry | None = None) -> ToolDefRegistry:
    """Derive the MCP tool surface from the capability registry (spec §4.2).

    Keeps READY + EXPERIMENTAL capabilities only; UNAVAILABLE capabilities
    never surface as tools.

    Pure registry bookkeeping: resolves each tool's handler *reference* from
    ``tools.py`` / ``fleet_tools.py`` without calling it, and builds ``ToolDef``
    records from the authored ``_TOOL_CAPABILITY`` / ``_TOOL_PARAM_SCHEMAS``
    tables. No engine, no SDK — runs in the RED phase so the 12-tool contract
    is locked before implementation. The handlers themselves stay stubbed.
    """
    capability = registry if registry is not None else CapabilityRegistry.default()
    ok_ids = {
        c.id
        for c in capability.capabilities
        if c.status is not CapabilityStatus.UNAVAILABLE
    }

    # Lazy handler resolution avoids engine import at module load (§2.2) and
    # circularity; handlers are resolved by name but never invoked here.
    from . import fleet_tools, tools  # lazy import — avoids engine import at module load
    from .memory import tools as memory_tools  # memory handlers

    def _handler(name: str):
        if name in ("fleet_nodes", "fleet_status", "fleet_queue", "fleet_run_batch"):
            return getattr(fleet_tools, name)
        if name.startswith("memory_"):
            return getattr(memory_tools, name)
        if name == "assert":
            return tools.assert_  # Python keyword — module uses assert_
        return getattr(tools, name)

    defs: list[ToolDef] = []
    for name, capability_id in _TOOL_CAPABILITY.items():
        if capability_id not in ok_ids:
            continue  # UNAVAILABLE capability → never surfaces (defense in depth)
        defs.append(
            ToolDef(
                name=name,
                description=(
                    f"MCP tool `{name}` — backed by capability `{capability_id}` "
                    f"(READY). See mcp-server-design.md §4.3."
                ),
                parameters=_TOOL_PARAM_SCHEMAS[name],
                capability_id=capability_id,
                status=next(c.status for c in capability.capabilities if c.id == capability_id),
                handler=_handler(name),
            )
        )
    return ToolDefRegistry(defs)
