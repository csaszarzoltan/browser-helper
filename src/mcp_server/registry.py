"""ToolDef registry — capability-derived MCP tool surface (pre-dev stub).

SDK-free by design (spec §2.2 / §8.4): this module must never import ``mcp``
or ``main`` so registry-only unit tests run in SDK-less environments.
"""

from __future__ import annotations

import os
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
    "set_viewport": "browser.core",
    "print_pdf": "browser.core",
    "set_geolocation": "browser.core",
    "set_offline": "browser.core",
    "get_performance_metrics": "browser.core",
    "drag": "browser.core",
    "accessibility_audit": "browser.core",
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
    # 6× E2E recorder/validation (v1.34 — 6 csoportos validációs csomag)
    "browser_get_accessibility_tree": "agent.semantic",
    "browser_find_semantic_elements": "agent.semantic",
    "browser_get_page_structure": "agent.semantic",
    "browser_navigate": "browser.core",
    "browser_interact": "browser.core",
    "browser_upload_file": "browser.core",
    "browser_download_file": "browser.core",
    "browser_get_console_logs": "agent.testing",
    "browser_get_network_activity": "browser.core",
    "browser_wait_for_condition": "agent.testing",
    "browser_take_screenshot": "browser.core",
    "browser_highlight_elements": "agent.testing",
    "browser_start_recorder": "agent.flow",
    "browser_record_step": "agent.flow",
    "browser_export_playwright_spec": "agent.flow",
    "browser_inject_storage_state": "diagnostics.cookies",
    "browser_reset_session": "browser.core",
    # P1-2/P1-3/P2 (discovery + bulk recorder + locale diff + hybrid idle)
    "browser_discover_tests": "agent.testing",
    "browser_export_batch_spec": "agent.flow",
    "browser_visual_diff_locale": "agent.testing",
    "browser_rate_hybrid_idle": "browser.core",
}

# Authored JSON Schemas per tool (spec §8.1): `type: "object"` + `properties`
# with the exact required params. These are the pre-tester contract and the
# FastMCP inputSchema gate (non-empty per tool).
_TOOL_PARAM_SCHEMAS: dict[str, dict[str, Any]] = {
    "set_viewport": {
        "type": "object",
        "properties": {
            "width": {"type": "integer", "description": "Viewport width in CSS px; 0 clears the override"},
            "height": {"type": "integer", "description": "Viewport height in CSS px; 0 clears the override"},
            "device_scale_factor": {"type": "number", "description": "Device pixel ratio (default 1)"},
            "mobile": {"type": "boolean", "description": "Phone layout with touch and mobile viewport (default false)"},
        },
        "required": ["width", "height"],
    },
    "print_pdf": {
        "type": "object",
        "properties": {
            "landscape": {"type": "boolean", "description": "Landscape orientation (default false)"},
            "print_background": {"type": "boolean", "description": "Print CSS backgrounds (default true)"},
            "scale": {"type": "number", "description": "Scale factor, 0.1 to 2 (default 1)"},
        },
    },
    "set_geolocation": {
        "type": "object",
        "properties": {
            "latitude": {"type": "number", "description": "Latitude in degrees"},
            "longitude": {"type": "number", "description": "Longitude in degrees"},
            "accuracy": {"type": "number", "description": "Accuracy in metres (default 100)"},
            "grant": {"type": "boolean", "description": "Grant the geolocation permission for the page origin so navigator.geolocation works without a prompt (default true)"},
        },
        "required": ["latitude", "longitude"],
    },
    "set_offline": {
        "type": "object",
        "properties": {"offline": {"type": "boolean", "description": "true to go offline, false to restore"}},
        "required": ["offline"],
    },
    "get_performance_metrics": {"type": "object", "properties": {}},
    "drag": {
        "type": "object",
        "properties": {
            "from_selector": {"type": "string", "description": "CSS selector of the element to drag"},
            "to_selector": {"type": "string", "description": "CSS selector of the drop target"},
            "steps": {"type": "integer", "description": "Mouse-move steps between the two points (default 12)"},
        },
        "required": ["from_selector", "to_selector"],
    },
    "accessibility_audit": {"type": "object", "properties": {}},
    "navigate": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to navigate to"}},
        "required": ["url"],
    },
    "click": {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector"},
            "expect": {"type": "object", "description": "Expected outcome after the click, e.g. {url_changed: true} or {text_visible: \"...\"}. The result is in data.verification.satisfied."},
        },
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
            "tab_id": {"type": "string", "description": "Observe this tab instead of the session's tab — no context switch (P0 tab_id)"},
            "include_network": {"type": "boolean", "description": "Bundle the network log into the observation (default false)"},
            "include_screenshot": {"type": "boolean", "description": "Bundle a viewport screenshot into the observation (default false)"},
            "store_screenshot": {"type": "boolean", "description": "Store the bundled screenshot as an artifact and return artifact_id (P2)"},
            "exclude_urls": {"type": "array", "items": {"type": "string"}, "description": "URL substrings to drop from the bundled network log (P2)"},
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
            "expect": {"type": "object", "description": "Expected outcome, checked after the action. Clauses: {url_changed: true}, {dialog_opened: true}, {text_visible: \"...\"}, {element_visible: {role, name}}, or {any_of: [clause, ...]}. The result is in data.verification.satisfied."},
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
    # Fleet run-batch — P0-2 bulk executor (workers/retries/shard/reporter)
    "fleet_run_batch": {
        "type": "object",
        "properties": {
            "tasks": { "type": "array", "description": "List of {url, action?, assert_selector?, assert_text?, timeout?, id?} — at least 1, max 100" },
            "concurrency": { "type": "integer", "description": "Parallel tasks (default 4, max 16)" },
            "workers": { "type": "integer", "description": "Alias for concurrency — workers wins when set (1-32)" },
            "retries": { "type": "integer", "description": "Retries per failed task (0-3, default 0)" },
            "timeoutPerTest":  { "type": "integer", "description": "Per-test timeout override in seconds (1-300, falls back to task.timeout)" },
            "shard": { "type": "string", "description": "Shard filter '1/2' (index/total) — only that slice runs" },
            "reporter": { "type": "string", "description": "Reporter(s) comma-separated: html,json,junit — artifact ids returned" },
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
            "tab_id": {"type": "string", "description": "Eval in this tab instead of the session's tab — no context switch (P0 tab_id)"},
        },
        "required": ["js"],
    },
    # Page text alias (A4) — calls client.get_page_text
    "get_page_text": {
        "type": "object",
        "properties": {
            "wait_ready": {"type": "boolean", "description": "Wait for page ready before extracting (default true)"},
            "timeout": {"type": "integer", "description": "Max seconds to wait for ready (default 20)"},
            "tab_id": {"type": "string", "description": "Read this tab instead of the session's tab — no context switch (P0 tab_id)"},
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
    "rate_limiter_status": { "type": "object", "properties": {} },
    "dialog_handle": {
        "type": "object",
        "properties": {
            "action": { "type": "string", "description": "accept|dismiss — dialog action" },
            "prompt_text": { "type": "string", "description": "Prompt text when accepting a prompt() dialog (optional)" },
        },
        "required": ["action"],
    },
    # 6× E2E recorder/validation — group 1: a11y
    "browser_get_accessibility_tree": {
        "type": "object",
        "properties": {
            "token_limit": { "type": "integer", "description": "Max tokens of serialized ARIA tree (default 6000, capped 20000)" },
            "max_nodes": { "type": "integer", "description": "Max AX nodes to return (default 250, capped 1000)" },
            "interactive_only": { "type": "boolean", "description": "Only interactive (focusable/clickable) nodes (default false)" },
            "scope": { "type": "string", "description": "page|dialog|viewport (default page)" },
            "include_hidden": { "type": "boolean", "description": "Include aria-hidden nodes (default false)" },
        },
    },
    "browser_find_semantic_elements": {
        "type": "object",
        "properties": {
            "query": { "type": "string", "description": "Accessible name / role filter substring (e.g. 'Login', 'submit')" },
            "role": { "type": "string", "description": "Optional ARIA role filter (button, link, textbox, …)" },
            "max_results": { "type": "integer", "description": "Max candidates to return (default 20, capped 100)" },
            "suggest_locator": { "type": "boolean", "description": "Include Playwright getByRole/getByLabel/getByTestId suggestion per element (default true)" },
        },
    },
    "browser_get_page_structure": {
        "type": "object",
        "properties": {
            "include_iframes": { "type": "boolean", "description": "Include iframe list (default true)" },
            "max_chars": { "type": "integer", "description": "Max visible-text chars (default 6000, capped 20000)" },
        },
    },
    # group 2: deterministic interactions
    "browser_navigate": {
        "type": "object",
        "properties": {
            "url": { "type": "string", "description": "Target URL to navigate to" },
            "wait_until": { "type": "string", "description": "domContentLoaded|load|networkIdle (default domContentLoaded)" },
            "settle": { "type": "boolean", "description": "Extra SPA settle: wait for network-idle + readyState=complete after load (maps/maps-heavy pages, default false)" },
            "timeout": { "type": "integer", "description": "Max seconds for the whole navigation (default 10, clamped 1-30)" },
            "origins": { "type": "array", "items": { "type": "object" }, "description": "Playwright-style origins: [{origin, localStorage:[{name,value}]}] — injected BEFORE navigate via addScriptToEvaluateOnNewDocument (receiptlens.locale=fr parity)" },
            "storage_state": { "type": "object", "description": "Alias for origins — {origins:[{origin,localStorage:[{name,value}]}]} or origins list directly" },
            "make_active": { "type": "boolean", "description": "Bring the navigated tab to the foreground after navigate (default true; false keeps the current foreground tab — P0 navigate-active)" },
        },
        "required": ["url"],
    },
    "browser_interact": {
        "type": "object",
        "properties": {
            "selector": { "type": "string", "description": "CSS selector of the target" },
            "action": { "type": "string", "description": "click|fill|press|select|type (default click). 'type' and 'fill' are aliases" },
            "text": { "type": "string", "description": "Text to type/fill or key name for press (Enter, Escape, …)" },
            "option": { "type": "string", "description": "Option value/text for select" },
            "wait_visible": { "type": "boolean", "description": "Wait until the selector is visible before acting (default true — actionability check)" },
            "wait_ms": { "type": "integer", "description": "Max wait for visibility (default 8000, clamped 0-30000)" },
            "scroll_into_view": { "type": "boolean", "description": "Scroll the element into view before acting (default true)" },
        },
        "required": ["selector"],
    },
    "browser_upload_file": {
        "type": "object",
        "properties": {
            "selector": { "type": "string", "description": "CSS selector of <input type=file>" },
            "path": { "type": "string", "description": "Sandbox file to upload (absolute path under /tmp/bh-upload-sandbox or the browser sandbox dir)" },
            "filename": { "type": "string", "description": "Optional override filename reported to the page (default: basename of path)" },
        },
        "required": ["selector", "path"],
    },
    "browser_download_file": {
        "type": "object",
        "properties": {
            "url": { "type": "string", "description": "URL to download (navigates the tab)" },
            "timeout": { "type": "integer", "description": "Max seconds to wait (default 30)" },
        },
        "required": ["url"],
    },
    # group 3: diagnostics
    "browser_get_console_logs": {
        "type": "object",
        "properties": {
            "level": { "type": "string", "description": "error|warning|info|all (default error)" },
            "since": { "type": "number", "description": "Only entries with timestamp >= this (unix seconds)" },
            "limit": { "type": "integer", "description": "Max entries (default 50, capped 200)" },
        },
    },
    "browser_get_network_activity": {
        "type": "object",
        "properties": {
            "path": { "type": "string", "description": "Filter by URL path substring (e.g. '/api/')" },
            "method": { "type": "string", "description": "Filter by HTTP method" },
            "status_min": { "type": "integer", "description": "Minimum HTTP status (e.g. 400 for failures)" },
            "since": { "type": "number", "description": "Only entries with timestamp >= this" },
            "limit": { "type": "integer", "description": "Max entries (default 100, capped 500)" },
        },
    },
    "browser_wait_for_condition": {
        "type": "object",
        "properties": {
            "js": { "type": "string", "description": "JS expression returning truthy when ready, e.g. \"window.map && window.map.loaded() === true\"" },
            "selector": { "type": "string", "description": "Alternative: CSS selector to wait for (mutually exclusive with js)" },
            "visible": { "type": "boolean", "description": "For selector mode: wait until visible (default true)" },
            "timeout": { "type": "integer", "description": "Max seconds to wait (default 10, clamped 1-60)" },
        },
    },
    # group 4: visual proof
    "browser_take_screenshot": {
        "type": "object",
        "properties": {
            "scope": { "type": "string", "description": "viewport|full|element (default viewport)" },
            "selector": { "type": "string", "description": "Required when scope=element — CSS selector of the component" },
            "quality": { "type": "integer", "description": "JPEG quality 1-100 (default 80)" },
        },
    },
    "browser_highlight_elements": {
        "type": "object",
        "properties": {
            "selectors": { "type": "array", "items": { "type": "string" }, "description": "CSS selectors to highlight (1-10)" },
            "duration_ms": { "type": "integer", "description": "Overlay lifetime in ms (default 4000, clamped 500-30000)" },
        },
        "required": ["selectors"],
    },
    # group 5: Playwright spec export
    "browser_start_recorder": {
        "type": "object",
        "properties": {
            "name": { "type": "string", "description": "Human recording name (default rec_<hex>)" },
            "ac": { "type": "string", "description": "Gherkin acceptance criterion id to associate (e.g. AC-042)" },
        },
    },
    "browser_record_step": {
        "type": "object",
        "properties": {
            "step": { "type": "string", "description": "Human step description (e.g. \"Click Login\")" },
            "selector": { "type": "string", "description": "Stable selector/locator used (Playwright locator string)" },
            "action": { "type": "string", "description": "click|fill|press|select|navigate|assert…" },
            "value": { "type": "string", "description": "Optional value/expected text" },
        },
        "required": ["step"],
    },
    "browser_export_playwright_spec": {
        "type": "object",
        "properties": {
            "suite_name": { "type": "string", "description": "describe() title (default: recording name)" },
            "recording_id": { "type": "string", "description": "Recording id to export (default: active recording)" },
            "stop_recording": { "type": "boolean", "description": "Stop the recording after export (default true)" },
        },
    },
    # group 6: session/state isolation
    "browser_inject_storage_state": {
        "type": "object",
        "properties": {
            "cookies": { "type": "array", "items": { "type": "object" }, "description": "Cookie list {name, value, domain?, path?, sameSite?, expires?}" },
            "origins": { "type": "array", "items": { "type": "object" }, "description": "localStorage origins [{origin, localStorage:[{name,value}]}]" },
            "tenant": { "type": "string", "description": "Optional e2e tenant id injected into localStorage['tenant'] (e.g. demo-e2e-$RUN_ID)" },
        },
    },
    "browser_reset_session": {
        "type": "object",
        "properties": {
            "scope": { "type": "string", "description": "cookies|storage|all (default all)" },
        },
    },
    # P1-2/P1-3/P2 (bulk + discovery + locale diff + hybrid idle)
    "browser_discover_tests": {
        "type": "object",
        "properties": {
            "pattern": { "type": "string", "description": "Glob pattern relative to root, e.g. e2e/us_*.spec.ts (default that)" },
            "root": { "type": "string", "description": "Root dir for glob (default cwd)" },
        },
    },
    "browser_export_batch_spec": {
        "type": "object",
        "properties": {
            "recordings": { "type": "array", "items": { "type": "string" }, "description": "Recording ids or step-dicts to merge into one .spec.ts" },
            "suite_name": { "type": "string", "description": "describe() title (default Batch of N)" },
        },
    },
    "browser_visual_diff_locale": {
        "type": "object",
        "properties": {
            "url": { "type": "string", "description": "URL of the page to diff per locale" },
            "locales": { "type": "array", "items": { "type": "string" }, "description": "Locale values, e.g. ['en','fr'] (default en,fr)" },
            "storage_key": { "type": "string", "description": "localStorage key for locale, e.g. receiptlens.locale (default that)" },
            "h1_selector": { "type": "string", "description": "H1 selector for text assertion (default h1)" },
            "threshold": { "type": "number", "description": "Pixel delta threshold (default 0.001)" },
        },
        "required": ["url"],
    },
    "browser_rate_hybrid_idle": {
        "type": "object",
        "properties": {
            "url": { "type": "string", "description": "Optional URL to navigate before the hybrid idle wait" },
            "timeout": { "type": "integer", "description": "Max seconds for idle (default 10)" },
            "quiet_ms": { "type": "integer", "description": "Quiet window ms for network idle (default 500)" },
        },
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


# Tool profiles (env ``MCP_PROFILE``). ``full`` is the default and exposes every
# READY/EXPERIMENTAL tool; ``core`` is an opt-in subset that keeps the tool list
# (and therefore the per-turn context cost of ``tools/list``) small.
_CORE_TOOLS = frozenset({
    "navigate", "observe", "act", "screenshot", "get_page_text", "get_tabs",
    "switch_tab", "close_tab", "wait_for", "assert", "session_status",
    "get_console_errors",
})
_PROFILES: dict[str, frozenset[str] | None] = {"full": None, "core": _CORE_TOOLS}

# Usage hints shown to the model. Measured on local pages (scratch/mcp-tuning):
# snapshot (page_analyze) was ~2.9x the observe(semantic) output on a 300-row page.
# One usage description per tool, shown to the model. Each says when to use the tool
# and which overlapping tool to use instead. Keep these in step with the handlers.
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "set_viewport": "Set the viewport size of the active tab (width, height). Use mobile=true for a phone layout. width=0 and height=0 clear the override.",
    "print_pdf": "Render the active page to PDF and store it as an artifact. Returns artifact_id and artifact_url.",
    "set_geolocation": "Override the browser geolocation (latitude, longitude) and grant the permission for the current page, so navigator.geolocation returns that position. grant=false skips the permission.",
    "set_offline": "Simulate the network going offline (offline=true) or back online (offline=false). For offline-behaviour tests.",
    "get_performance_metrics": "Load timings of the current page from the Performance API: TTFB, DOMContentLoaded, load, first paint, first contentful paint, resource count, JS heap. Milliseconds.",
    "drag": "Drag one element onto another with the mouse (from_selector to to_selector). For drag-and-drop widgets such as sliders, sortable lists and boards.",
    "accessibility_audit": "Heuristic accessibility check of the active page: missing lang and title, images without alt, unnamed buttons and links, unlabelled inputs, duplicate ids, skipped heading levels. Counts per rule and up to 50 issues. Not a full WCAG audit.",
    'observe': 'Preferred way to see the page. Returns compact accessibility-tree nodes, each with an element_id for act(). Paginated (next_cursor). Use it to find targets before acting. Measured: about 2.9x smaller than snapshot on a 300-row page.',
    'snapshot': 'Page analysis summary: title, buttons, forms, modals, alerts, text preview. NOT an accessibility tree and it returns no element_ids. Use observe to find targets. Larger than observe on big pages.',
    'act': "Perform one action on a target. Preferred: element_id plus snapshot_id from observe. Alternatives: selector or text. Actions: click, fill, select, wait, navigate. On failure returns the engine's error code and message (e.g. element_not_found).",
    'click': 'Click the first element matching a CSS selector in the active tab. For targets from observe, use act with element_id instead.',
    'type': 'Type text into the element matched by a CSS selector. For observe targets use act(action=fill). For several labelled fields use form_fill.',
    'hover': 'Hover over an element by CSS selector. Use it to reveal menus and tooltips.',
    'press_key': 'Press a keyboard key (e.g. Enter, Escape, Tab), optionally on a selector.',
    'scroll': 'Scroll the page, or one element, by x and y pixels.',
    'form_fill': 'Fill several form fields at once, matched by label or selector. Use form_extract first to see the field labels.',
    'form_extract': "List the page's form fields with labels and types. Read-only. Use it before form_fill.",
    'browser_interact': 'One call for click, fill, press or select, with actionability checks (waits until the element is visible and enabled). Prefer it over click/type when the target may still be loading.',
    'browser_find_semantic_elements': 'Map interactive elements to stable Playwright-style locators (getByRole and similar). Use when a test must survive DOM changes.',
    'browser_get_accessibility_tree': 'Token-optimised ARIA tree (roles, names, states; no raw HTML). Same idea as observe with other filters: scope, interactive_only, include_hidden.',
    'browser_get_page_structure': 'Concise structure of forms, buttons and dialogs (optionally iframes). Smaller than snapshot for a quick overview.',
    'get_page_text': 'Visible text of the page. Use it to read content. Use observe to find targets to click.',
    'get_content': 'Load a URL (or use the current page) and return its main content. For reading and research, not for interacting.',
    'search': 'One-call web search. Returns the extracted answer text.',
    'navigate': 'Navigate the active tab to a URL. For load strategy, cookies or storage state use browser_navigate.',
    'browser_navigate': 'Navigate with a chosen load strategy (wait_until), an optional settle wait, and optional origins or storage_state applied before the page renders.',
    'reload': 'Reload the current page. ignore_cache bypasses the cache.',
    'get_tabs': 'List open tabs with id, title, url and active flag. Call it before switch_tab or close_tab.',
    'switch_tab': 'Make tab id the active tab.',
    'close_tab': 'Close the tab with the given id. Get ids from get_tabs.',
    'browser_reset_session': 'Clear cache, cookies and storage between tests. scope selects what is cleared.',
    'clone_session': "Create a new session holding a copy of this session's cookies.",
    'session_status': 'Persistence status of all sessions (age, url, expired). Use it to see which sessions are alive.',
    'export_cookies': 'Export all cookies of a session as JSON.',
    'import_cookies': 'Import cookies into a session.',
    'browser_inject_storage_state': 'Inject cookies and localStorage (e.g. a saved login) so the page starts logged in. Use it to skip logins in tests.',
    'screenshot': 'JPEG screenshot of the active tab (viewport). For full page or one element use browser_take_screenshot.',
    'browser_take_screenshot': 'Screenshot of the viewport, the full page (scope), or one element (selector). Prefer it over screenshot when you need more than the viewport.',
    'browser_highlight_elements': 'Draw temporary highlight boxes around selectors, so a person can see what is targeted. For debugging.',
    'eval': 'Run JavaScript in the page and return its value. For state no other tool exposes. For checks prefer assert, wait_js or element_state.',
    'assert': 'Assert a DOM condition on the page (value, kind, condition, expected) and return pass or fail. For tests.',
    'wait_for': 'Wait until a DOM condition holds (value, kind, condition, timeout). Use it instead of fixed sleeps.',
    'wait_js': 'Wait until a JavaScript expression becomes truthy (js, timeout).',
    'wait_network_idle': 'Wait until no network requests are pending for quiet_ms.',
    'browser_wait_for_condition': 'Wait for a JavaScript predicate (js) or for a selector to be visible.',
    'browser_rate_hybrid_idle': 'Navigate and wait for hybrid network-idle, for pages that never go fully idle. quiet_ms sets the quiet window.',
    'element_state': 'State of one element by CSS selector: visible, enabled, checked, value. For assertions.',
    'get_console_errors': 'Persistent console errors since a time (since, limit). Use it to check for JavaScript errors in a test.',
    'browser_get_console_logs': 'Console logs with stack traces, filtered by level and since. Use it when get_console_errors is not enough, for example for info or log output.',
    'get_network_requests': 'Filtered network request log (path, method, status). For inspecting requests.',
    'browser_get_network_activity': 'Failed requests and API timings with payloads, from the filtered network log. Use it to debug API calls.',
    'network_block': 'Block requests whose URL matches any of the regex patterns. For testing failure paths.',
    'network_mock': 'Install URL-pattern mocks that return fake responses. For tests without a backend.',
    'notifications_start': 'Start capturing toast, alert and notification DOM changes. Call it before get_notifications.',
    'get_notifications': 'Toast, alert and notification messages captured since a time. Requires notifications_start first.',
    'dialog_handle': 'Accept or dismiss the next JavaScript dialog (alert, confirm, prompt), optionally with prompt text.',
    'rate_limiter_status': 'Domain throttle and rate-limiter state. Use it when requests are being delayed.',
    'download': 'Download a file through the browser into the artifact store and return where it was stored.',
    'browser_download_file': 'Download a URL into the artifact store through the sandboxed browser.',
    'browser_upload_file': 'Set files on an input type=file from the sandboxed artifact store.',
    'browser_visual_diff_locale': 'Visual diff of the page across locales (locales, h1_selector, threshold) against a baseline. For localisation tests.',
    'browser_discover_tests': 'Find test spec files by glob pattern under root.',
    'browser_start_recorder': 'Start recording user steps into a named recording (name). Then add annotated steps with browser_record_step.',
    'browser_record_step': 'Add one annotated step (step, selector, action, value) to the active recording.',
    'browser_export_playwright_spec': 'Export a recording as a Playwright TypeScript .spec.ts file (recording_id, or stop_recording).',
    'browser_export_batch_spec': 'Merge several recordings into one combined .spec.ts file (recordings, suite_name).',
    'run_flow': 'Run an ordered list of steps as an E2E test with a per-step report. stop_on_error controls whether a failure stops the run.',
    'fleet_nodes': 'List fleet worker nodes and their health.',
    'fleet_status': 'Report the fleet session status across worker nodes. Use fleet_nodes for node health and fleet_queue for pending work.',
    'fleet_queue': 'Peek at the allocation queue without consuming it.',
    'fleet_run_batch': 'Run many independent browsing tasks in parallel (tasks, workers, retries, shard). Returns per-task results.',
    'memory_remember': 'Store a fact under a key (content, optional metadata). Persists across sessions.',
    'memory_recall': 'Search stored memories by keyword, ranked by relevance.',
    'memory_list': 'List stored memories, optionally filtered.',
    'memory_forget': 'Delete a memory by key or id.',
}


def resolve_profile(profile: str | None = None) -> frozenset[str] | None:
    """Return the allowed tool names for a profile, or None for ``full``.

    ``profile`` wins over ``MCP_PROFILE``; unknown names raise ``ValueError``.
    """
    name = (profile if profile is not None else os.environ.get("MCP_PROFILE", "")).strip().lower() or "full"
    if name not in _PROFILES:
        raise ValueError(f"unknown MCP profile {name!r}; expected one of {sorted(_PROFILES)}")
    return _PROFILES[name]


def build_tool_defs(registry: CapabilityRegistry | None = None, profile: str | None = None) -> ToolDefRegistry:
    """Derive the MCP tool surface from the capability registry (spec §4.2).

    Keeps READY + EXPERIMENTAL capabilities only; UNAVAILABLE capabilities
    never surface as tools. ``profile`` (or env ``MCP_PROFILE``) optionally
    narrows the surface to a named subset (see ``resolve_profile``).
    """
    allowed = resolve_profile(profile)
    # Pure registry bookkeeping: resolves each tool's handler *reference* from
    # ``tools.py`` / ``fleet_tools.py`` without calling it, and builds ``ToolDef``
    # records from the authored ``_TOOL_CAPABILITY`` / ``_TOOL_PARAM_SCHEMAS``
    # tables. No engine, no SDK.
    capability =registry if registry is not None else CapabilityRegistry.default()
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
        if name in ("browser_discover_tests", "browser_export_batch_spec", "browser_visual_diff_locale", "browser_rate_hybrid_idle"):
            from . import discovery_tools  # lazy — P1-2/P1-3/P2 wrappers
            return getattr(discovery_tools, name)
        if name.startswith("memory_"):
            return getattr(memory_tools, name)
        if name == "assert":
            return tools.assert_  # Python keyword — module uses assert_
        return getattr(tools, name)

    defs: list[ToolDef] = []
    for name, capability_id in _TOOL_CAPABILITY.items():
        if capability_id not in ok_ids:
            continue  # UNAVAILABLE capability → never surfaces (defense in depth)
        if allowed is not None and name not in allowed:
            continue  # outside the selected profile
        defs.append(
            ToolDef(
                name=name,
                description=_TOOL_DESCRIPTIONS[name],
                parameters=_TOOL_PARAM_SCHEMAS[name],
                capability_id=capability_id,
                status=next(c.status for c in capability.capabilities if c.id == capability_id),
                handler=_handler(name),
            )
        )
    return ToolDefRegistry(defs)
