"""MCP server — interface + behavioral test suite (pre-dev RED contract).

Written by the pre-tester against ``docs/architecture/mcp-server-design.md``
(spec §8) — *before* the developer task (t_4e2ec7fa) implements the module.

Phase semantics
---------------
- **Interface tests** (class ``TestInterface``) assert the public contract:
  module layout, ``MCPServer`` factory, tool handler signatures/type hints,
  ``ToolDefRegistry`` derivation from ``CapabilityRegistry``, CLI entry point.
  They must PASS immediately against the stub harness shipped in
  ``src/mcp_server/``.
- **Behavioral tests** (class ``TestBehavioral``) exercise real code paths
  (browser tool handlers via the engine, fleet handlers via a live
  ``FleetCoordinator`` on a temp fleet.db). They FAIL with
  ``NotImplementedError`` during RED and become active after the developer
  replaces the stubs with the real engine bindings.

Gating (spec §8.4)
------------------
``mcp_server`` is SDK-free except ``server.py``/``cli.py`` (which import
``mcp``). Tests that need the FastMCP integration guard with
``pytest.importorskip("mcp")`` so the suite is runnable in an environment
where the SDK is not yet installed — but once the package exists the tests
FAIL loudly (never silently skip) on the missing behavior.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Constants from the spec (authoritative tool surface, §4.3 / §1.2)
# ---------------------------------------------------------------------------

EXPECTED_TOOLS = [
    "navigate",
    "click",
    "type",
    "screenshot",
    "snapshot",
    "get_tabs",
    "switch_tab",
    "close_tab",
    "session_status",
    "search",
    "get_content",
    "run_flow",
    "fleet_nodes",
    "fleet_status",
    "fleet_queue",
    "memory_remember",
    "memory_recall",
    "memory_forget",
    "memory_list",
]

# tool -> required parameter names (spec §8.1: exact required params)
EXPECTED_REQUIRED_PARAMS = {
    "navigate": ["url"],
    "click": ["selector"],
    "type": ["selector", "text"],
    "screenshot": [],
    "snapshot": [],
    "get_tabs": [],
    "switch_tab": ["id"],
    "close_tab": ["id"],
    "session_status": [],
    "search": ["query"],
    "get_content": [],
    "run_flow": ["steps"],
    "fleet_nodes": [],
    "fleet_status": [],
    "fleet_queue": [],
    "memory_remember": ["key", "content"],
    "memory_recall": ["query"],
    "memory_forget": ["key_or_id"],
    "memory_list": [],
}

# tool -> (capability_id, expected status)
EXPECTED_CAPABILITY = {
    "navigate": ("browser.core", "ready"),
    "click": ("browser.core", "ready"),
    "type": ("browser.core", "ready"),
    "screenshot": ("browser.core", "ready"),
    "snapshot": ("agent.semantic", "ready"),
    "get_tabs": ("browser.core", "ready"),
    "switch_tab": ("browser.core", "ready"),
    "close_tab": ("browser.core", "ready"),
    "session_status": ("diagnostics.privacy", "ready"),
    "search": ("agent.search", "ready"),
    "get_content": ("agent.search", "ready"),
    "run_flow": ("agent.flow", "ready"),
    "fleet_nodes": ("workflow.local", "ready"),
    "fleet_status": ("workflow.local", "ready"),
    "fleet_queue": ("workflow.local", "ready"),
    "memory_remember": ("memory.persistent", "ready"),
    "memory_recall": ("memory.persistent", "ready"),
    "memory_forget": ("memory.persistent", "ready"),
    "memory_list": ("memory.persistent", "ready"),
}

TOOL_MODULES = {
    "navigate": "tools",
    "click": "tools",
    "type": "tools",
    "screenshot": "tools",
    "snapshot": "tools",
    "get_tabs": "tools",
    "switch_tab": "tools",
    "close_tab": "tools",
    "session_status": "tools",
    "search": "tools",
    "get_content": "tools",
    "run_flow": "tools",
    "fleet_nodes": "fleet_tools",
    "fleet_status": "fleet_tools",
    "fleet_queue": "fleet_tools",
    "memory_remember": "memory.tools",
    "memory_recall": "memory.tools",
    "memory_forget": "memory.tools",
    "memory_list": "memory.tools",
}


def _require_pkg(name: str, what: str) -> None:
    """Fail the test with a clear message if a package is missing."""
    if not pytest.importorskip(name, reason=f"{what} not installed"):
        raise AssertionError(f"{what} not installed")  # pragma: no cover


def _load_tool_handlers() -> dict[str, object]:
    """Return {tool_name: handler} from mcp_server.tools / fleet_tools / memory.tools.

    Raises ModuleNotFoundError (fail) when the module is absent.
    """
    import mcp_server.fleet_tools
    import mcp_server.memory.tools
    import mcp_server.tools

    handlers = {
        name: getattr(mcp_server.tools, name)
        for name in EXPECTED_TOOLS
        if TOOL_MODULES[name] == "tools"
    }
    handlers.update(
        {
            name: getattr(mcp_server.fleet_tools, name)
            for name in EXPECTED_TOOLS
            if TOOL_MODULES[name] == "fleet_tools"
        }
    )
    handlers.update(
        {
            name: getattr(mcp_server.memory.tools, name)
            for name in EXPECTED_TOOLS
            if TOOL_MODULES[name] == "memory.tools"
        }
    )
    return handlers


# ---------------------------------------------------------------------------
# 1. Interface tests — contract surface (PASS in RED)
# ---------------------------------------------------------------------------


class TestInterface:
    """Public contract: module layout, classes, signatures, registry, CLI."""

    # -- package / module layout ------------------------------------------

    def test_mcp_server_package_exists(self):
        import mcp_server

        assert mcp_server.__version__  # spec §2: re-exports __version__

    def test_module_files_exist(self):
        root = Path(__file__).parent.parent / "src" / "mcp_server"
        for fname in ("config.py", "registry.py", "server.py", "tools.py",
                      "fleet_tools.py", "serialization.py", "cli.py"):
            assert (root / fname).is_file(), f"missing {fname}"

    def test_cli_shim_exists(self):
        shim = Path(__file__).parent.parent / "src" / "browser_helper" / "mcp.py"
        assert shim.is_file()

    def test_public_api_reexports(self):
        from mcp_server import MCPServer, create_mcp_server  # noqa: F401

        assert callable(create_mcp_server)

    # -- MCPServer / factory ----------------------------------------------

    def test_mcpserver_class_exists(self):
        from mcp_server.server import MCPServer

        assert inspect.isclass(MCPServer)

    def test_mcpserver_constructor(self):
        from mcp_server.server import MCPServer

        sig = inspect.signature(MCPServer.__init__)
        assert "settings" in sig.parameters
        assert sig.parameters["settings"].default is None

    def test_mcpserver_has_mcp_property(self):
        from mcp_server.server import MCPServer

        assert isinstance(inspect.getattr_static(MCPServer, "mcp"), property)

    def test_mcpserver_has_register_tools_and_run(self):
        from mcp_server.server import MCPServer

        for name in ("register_tools", "run"):
            assert callable(getattr(MCPServer, name)), f"missing {name}"

    def test_create_mcp_server_returns_mcpserver(self):
        from mcp_server import MCPServer, create_mcp_server

        server = create_mcp_server()
        assert isinstance(server, MCPServer)

    # -- config ------------------------------------------------------------

    def test_mcp_settings_dataclass(self):
        from dataclasses import is_dataclass

        from mcp_server.config import MCPSettings

        assert is_dataclass(MCPSettings)

    def test_mcp_settings_fields(self):
        from mcp_server.config import MCPSettings

        names = set(MCPSettings.__dataclass_fields__)
        for field in ("transport", "enabled", "host", "port", "server_name", "instructions"):
            assert field in names, f"missing field {field}"

    def test_mcp_settings_defaults(self):
        from mcp_server.config import MCPSettings

        cfg = MCPSettings()
        assert cfg.transport == "stdio"
        assert cfg.server_name == "browser-helper"
        assert cfg.port == 8765

    def test_transport_enum_values(self):
        from mcp_server.config import MCPTransport

        values = {item.value for item in MCPTransport}
        assert values == {"stdio", "sse", "streamable-http"}

    def test_load_mcp_settings_callable(self):
        from mcp_server.config import load_mcp_settings

        assert callable(load_mcp_settings)

    # -- registry ----------------------------------------------------------

    def test_tool_def_dataclass(self):
        from dataclasses import is_dataclass

        from mcp_server.registry import ToolDef

        assert is_dataclass(ToolDef)

    def test_tool_def_fields(self):
        from mcp_server.registry import ToolDef

        names = set(ToolDef.__dataclass_fields__)
        for field in ("name", "description", "parameters", "capability_id", "status", "handler"):
            assert field in names, f"missing field {field}"

    def test_tool_def_registry_class(self):
        from mcp_server.registry import ToolDefRegistry

        assert inspect.isclass(ToolDefRegistry)
        for method in ("by_name", "capabilities"):
            assert callable(getattr(ToolDefRegistry, method)), f"missing {method}"

    def test_build_tool_defs_returns_tooldefregistry(self):
        from mcp_server.registry import ToolDefRegistry, build_tool_defs

        result = build_tool_defs()
        assert isinstance(result, ToolDefRegistry)

    def test_build_tool_defs_exact_tool_set(self):
        from mcp_server.registry import build_tool_defs

        names = sorted(tool.name for tool in build_tool_defs())
        assert names == sorted(EXPECTED_TOOLS)

    def test_every_tool_def_backed_by_capability(self):
        from capability_registry import CapabilityRegistry
        from mcp_server.registry import build_tool_defs

        cr = CapabilityRegistry.default()
        ids = {item.id for item in cr.capabilities}
        for tool in build_tool_defs():
            assert tool.capability_id in ids, f"{tool.name} → unknown capability"
            assert (tool.capability_id, tool.status.value) == EXPECTED_CAPABILITY[tool.name]

    def test_no_unavailable_capability_surfaces(self):
        from capability_registry import CapabilityStatus
        from mcp_server.registry import build_tool_defs

        for tool in build_tool_defs():
            assert tool.status is not CapabilityStatus.UNAVAILABLE

    def test_tooldef_registry_rejects_duplicate_names(self):
        from mcp_server.registry import ToolDefRegistry, build_tool_defs

        defs = list(build_tool_defs())
        with pytest.raises(ValueError):
            ToolDefRegistry(defs + [defs[0]])

    def test_tooldef_registry_rejects_unavailable(self):
        from capability_registry import CapabilityStatus
        from mcp_server.registry import ToolDef, ToolDefRegistry

        tool = ToolDef(
            name="nope",
            description="x",
            parameters={},
            capability_id="cloud.camofox",
            status=CapabilityStatus.UNAVAILABLE,
            handler=lambda: "",
        )
        with pytest.raises(ValueError):
            ToolDefRegistry([tool])

    def test_tooldef_registry_by_name_and_capabilities(self):
        from mcp_server.registry import build_tool_defs

        registry = build_tool_defs()
        assert registry.by_name("navigate") is not None
        assert registry.by_name("does_not_exist") is None
        assert registry.capabilities()

    # -- parameter schemas (§8.1) ------------------------------------------

    def test_schemas_nonempty_object_per_tool(self):
        from mcp_server.registry import _TOOL_PARAM_SCHEMAS, build_tool_defs

        for tool in build_tool_defs():
            schema = _TOOL_PARAM_SCHEMAS[tool.name]
            assert schema.get("type") == "object", f"{tool.name}: not object"
            assert "properties" in schema, f"{tool.name}: missing properties"

    def test_schemas_exact_required_params(self):
        from mcp_server.registry import _TOOL_PARAM_SCHEMAS, build_tool_defs

        for tool in build_tool_defs():
            schema = _TOOL_PARAM_SCHEMAS[tool.name]
            assert set(schema.get("required", [])) == set(
                EXPECTED_REQUIRED_PARAMS[tool.name]
            ), f"{tool.name}: required params mismatch"

    # -- tool handler signatures & type hints ------------------------------

    def test_all_tool_handlers_exist(self):
        handlers = _load_tool_handlers()
        assert set(handlers) == set(EXPECTED_TOOLS)

    def test_handlers_are_async_functions(self):
        for name, handler in _load_tool_handlers().items():
            assert inspect.iscoroutinefunction(handler), f"{name} not async"

    def test_handler_signatures_and_hints(self):
        handlers = _load_tool_handlers()
        for name, handler in handlers.items():
            sig = inspect.signature(handler)
            params = list(sig.parameters)
            required = [
                p for p in params
                if p != "ctx"
                and sig.parameters[p].default is inspect.Parameter.empty
            ]
            assert required == EXPECTED_REQUIRED_PARAMS[name], (
                f"{name}: required params {required} != {EXPECTED_REQUIRED_PARAMS[name]}"
            )
            # return annotation must be str (string-typed)
            ann = sig.return_annotation
            assert ann is str or ann == "str", f"{name}: return annotation {ann!r}"

    def test_handlers_accept_optional_ctx(self):
        handlers = _load_tool_handlers()
        for handler in handlers.values():
            sig = inspect.signature(handler)
            if "ctx" in sig.parameters:
                assert sig.parameters["ctx"].default is not inspect.Parameter.empty

    def test_handler_docstrings_mention_capability(self):
        handlers = _load_tool_handlers()
        for name, handler in handlers.items():
            # Docstrings may be inherited from a wrapped function; accept the
            # capability mention anywhere in the docstring or signature text.
            doc = (handler.__doc__ or "") + repr(inspect.signature(handler))
            assert doc.strip(), f"{name}: empty docstring"
            assert "browser.core" in doc or "fleet" in doc or \
                "capability" in doc.lower(), f"{name}: docstring lacks capability"

    def test_tools_module_no_llm_imports(self):
        """Anti-LLM gate (§8.2): mcp_server/ must never import LLM clients."""
        root = Path(__file__).parent.parent / "src" / "mcp_server"
        sources = "\n".join(
            p.read_text(encoding="utf-8") for p in root.glob("*.py")
        )
        for banned in ("openai", "anthropic", "chat_with_tools"):
            assert banned not in sources, f"LLM import leaked into mcp_server: {banned}"

    # -- CLI entry point ---------------------------------------------------

    def test_cli_main_callable(self):
        from mcp_server.cli import main

        assert callable(main)

    def test_shim_delegates_to_cli(self):
        shim = Path(__file__).parent.parent / "src" / "browser_helper" / "mcp.py"
        text = shim.read_text(encoding="utf-8")
        assert "mcp_server.cli" in text
        assert "__main__" in text

    def test_cli_help_exits_zero(self):
        _require_pkg("mcp", "mcp SDK")
        repo = Path(__file__).parent.parent
        env = {**sys._xoptions.get("syspath", {}), "PYTHONPATH": str(repo / "src")}
        proc = subprocess.run(
            [sys.executable, "-m", "browser_helper.mcp", "--help"],
            cwd=repo, capture_output=True, text=True, timeout=60, env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert "transport" in proc.stdout

    def test_cli_invalid_transport_exits_nonzero(self):
        _require_pkg("mcp", "mcp SDK")
        repo = Path(__file__).parent.parent
        env = {**sys._xoptions.get("syspath", {}), "PYTHONPATH": str(repo / "src")}
        proc = subprocess.run(
            [sys.executable, "-m", "browser_helper.mcp", "--transport", "http"],
            cwd=repo, capture_output=True, text=True, timeout=60, env=env,
            check=False,
        )
        assert proc.returncode != 0


# ---------------------------------------------------------------------------
# 2. Behavioral tests — real code paths (FAIL with NotImplementedError in RED)
# ---------------------------------------------------------------------------


class TestBehavioralBrowser:
    """navigate/click/type/screenshot/snapshot/get_tabs/switch_tab/close_tab.

    Each handler must call the real engine path (``main.run_op`` +
    ``client.*``) — the anti-LLM gate of spec §5.1 — and return a JSON string
    with the REST envelope shape.
    """

    @pytest.fixture(autouse=True)
    def _patch_run_op(self, monkeypatch):
        """Replace ``main.run_op`` with a recorder (spec §5.1 lazy import).

        The real handlers do ``from main import run_op`` *inside the function
        body* (lazy import), so patching ``tools.run_op`` would not intercept
        them post-implementation — the patch must land on ``main.run_op``.
        """
        calls: list[tuple] = []

        async def fake_run_op(operation, method, *args, **kwargs):
            calls.append((operation, method, args))
            return {
                "status": "ok",
                "operation": operation,
                "data": {"ok": True, "url": args[0] if args else None},
            }

        monkeypatch.setattr("main.run_op", fake_run_op)
        return calls

    def _assert_engine_call(self, calls, expected_operation, expected_args):
        assert len(calls) == 1, f"expected exactly one engine call, got {calls}"
        operation, method, args = calls[0]
        assert operation == expected_operation
        assert args == expected_args
        # the method must be a real CDPClient engine method, not an LLM call
        # (spec §5.1 anti-LLM gate). snapshot is special: operation
        # "page_analyze" binds client.analyze_page. Bound methods are
        # ephemeral objects, so compare the underlying function object.
        from main import client

        # operation -> CDPClient method name (spec §5.2-5.7); snapshot maps
        # operation "page_analyze" to client.analyze_page; type maps to
        # client.type_text.
        engine_method = {
            "page_analyze": "analyze_page",
            "type": "type_text",
        }.get(expected_operation, expected_operation)
        assert getattr(method, "__func__", None) is getattr(
            getattr(client, engine_method), "__func__", None
        ), (
            f"engine method mismatch: expected client.{engine_method}, "
            f"got {method!r}"
        )

    async def test_navigate_engine_call(self, _patch_run_op):
        from mcp_server import tools

        result = await tools.navigate("https://example.com")
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["status"] == "ok"
        self._assert_engine_call(_patch_run_op, "navigate", ("https://example.com",))

    async def test_click_engine_call(self, _patch_run_op):
        from mcp_server import tools

        result = await tools.click("#submit")
        assert isinstance(result, str)
        assert json.loads(result)["status"] == "ok"
        self._assert_engine_call(_patch_run_op, "click", ("#submit",))

    async def test_type_engine_call(self, _patch_run_op):
        from mcp_server import tools

        result = await tools.type("#email", "a@b.co")
        assert isinstance(result, str)
        assert json.loads(result)["status"] == "ok"
        self._assert_engine_call(_patch_run_op, "type", ("#email", "a@b.co"))

    async def test_screenshot_engine_call(self, _patch_run_op):
        from mcp_server import tools

        result = await tools.screenshot()
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["status"] == "ok"
        self._assert_engine_call(_patch_run_op, "screenshot", ())

    async def test_snapshot_engine_call(self, _patch_run_op):
        from mcp_server import tools

        result = await tools.snapshot()
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["status"] == "ok"
        self._assert_engine_call(_patch_run_op, "page_analyze", ())

    async def test_get_tabs_engine_call(self, _patch_run_op):
        from mcp_server import tools

        result = await tools.get_tabs()
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["status"] == "ok"
        self._assert_engine_call(_patch_run_op, "get_tabs", ())

    async def test_switch_tab_engine_call(self, _patch_run_op):
        from mcp_server import tools

        result = await tools.switch_tab("tab_7")
        assert isinstance(result, str)
        assert json.loads(result)["status"] == "ok"
        self._assert_engine_call(_patch_run_op, "switch_tab", ("tab_7",))

    async def test_close_tab_engine_call(self, _patch_run_op):
        from mcp_server import tools

        result = await tools.close_tab("tab_9")
        assert isinstance(result, str)
        assert json.loads(result)["status"] == "ok"
        self._assert_engine_call(_patch_run_op, "close_tab", ("tab_9",))


class TestBehavioralSession:
    """session_status — persistence layer, no CDP dependency (§5.8)."""

    async def test_session_status_returns_envelope(self):
        _require_pkg("mcp", "mcp SDK")
        from mcp_server import tools

        result = await tools.session_status()
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["status"] == "ok"
        assert payload["operation"] == "session_status"
        assert "sessions" in payload["data"]
        assert "total" in payload["data"]


class TestBehavioralFleet:
    """fleet_nodes / fleet_status / fleet_queue — read-only, live coordinator
    on a temp fleet.db (spec §5.9)."""

    @pytest.fixture(autouse=True)
    def _fleet_db(self, tmp_path, monkeypatch):
        db_path = tmp_path / "fleet.db"
        monkeypatch.setenv("FLEET_DB_PATH", str(db_path))
        yield db_path

    async def test_fleet_nodes_envelope(self):
        _require_pkg("mcp", "mcp SDK")
        import mcp_server.fleet_tools as ft

        result = await ft.fleet_nodes()
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["status"] == "ok"
        assert payload["operation"] == "fleet_nodes"
        assert set(payload["data"].keys()) >= {"nodes", "total", "healthy", "unhealthy"}

    async def test_fleet_status_envelope(self):
        _require_pkg("mcp", "mcp SDK")
        import mcp_server.fleet_tools as ft

        result = await ft.fleet_status()
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["status"] == "ok"
        assert payload["operation"] == "fleet_status"
        assert set(payload["data"].keys()) >= {"sessions", "total", "active", "queued"}

    async def test_fleet_queue_envelope(self):
        _require_pkg("mcp", "mcp SDK")
        import mcp_server.fleet_tools as ft

        result = await ft.fleet_queue()
        assert isinstance(result, str)
        payload = json.loads(result)
        assert payload["status"] == "ok"
        assert payload["operation"] == "fleet_queue"
        assert set(payload["data"].keys()) >= {"queue", "size", "max_queue"}

    async def test_fleet_queue_reads_real_queue(self):
        _require_pkg("mcp", "mcp SDK")
        import mcp_server.fleet_tools as ft
        from fleet.api import get_fleet_coordinator

        coordinator = get_fleet_coordinator()
        await coordinator.queue.enqueue(session_id="req_1")
        await coordinator.queue.enqueue(session_id="req_2")

        result = await ft.fleet_queue()
        payload = json.loads(result)
        assert payload["data"]["size"] == 2
        assert len(payload["data"]["queue"]) == 2
        # peek must NOT consume: a second call sees the same two entries
        again = json.loads(await ft.fleet_queue())
        assert again["data"]["size"] == 2

    async def test_fleet_status_reads_real_pool_and_registry(self):
        _require_pkg("mcp", "mcp SDK")
        import mcp_server.fleet_tools as ft
        from fleet.api import get_fleet_coordinator

        coordinator = get_fleet_coordinator()
        await coordinator.registry.register(url="ws://127.0.0.1:1",
                                            node_id="node_1", capacity=2)
        await coordinator.registry.update_health("node_1", healthy=True)
        await coordinator.storage.add_session(
            session_id="sess_1", node_id="node_1",
            node_url="ws://127.0.0.1:1", status="active",
        )

        result = await ft.fleet_status()
        payload = json.loads(result)
        assert payload["data"]["total"] == 1
        assert payload["data"]["active"] == 1

    async def test_fleet_nodes_reads_real_registry(self):
        _require_pkg("mcp", "mcp SDK")
        import mcp_server.fleet_tools as ft
        from fleet.api import get_fleet_coordinator

        coordinator = get_fleet_coordinator()
        await coordinator.registry.register(url="ws://127.0.0.1:1",
                                            node_id="node_1", capacity=2)
        await coordinator.registry.update_health("node_1", healthy=True)

        result = await ft.fleet_nodes()
        payload = json.loads(result)
        assert payload["data"]["total"] == 1
        assert payload["data"]["healthy"] == 1
        assert payload["data"]["unhealthy"] == 0

    async def test_fleet_tools_never_mutate(self):
        """AC#5 gate: fleet reads must not register/enqueue anything."""
        _require_pkg("mcp", "mcp SDK")
        import mcp_server.fleet_tools as ft
        from fleet.api import get_fleet_coordinator

        coordinator = get_fleet_coordinator()
        await ft.fleet_nodes()
        await ft.fleet_status()
        await ft.fleet_queue()
        counts = await coordinator.registry.storage.node_counts()
        assert counts["total"] == 0
        assert await coordinator.registry.storage.queue_size() == 0


class TestBehavioralFastMCP:
    """Real FastMCP server integration (spec §8.3)."""

    def test_mcp_server_constructs_and_registers_12_tools(self):
        _require_pkg("mcp", "mcp SDK")
        from mcp_server.server import MCPServer

        server = MCPServer()
        mcp = server.mcp  # memoized builder; registers tools
        assert mcp is not None
        tools = asyncio.run(mcp.list_tools())
        assert len(tools) == len(EXPECTED_TOOLS)
        names = {t.name for t in tools}
        assert names == set(EXPECTED_TOOLS)

    def test_fastmcp_tools_have_nonempty_input_schema(self):
        _require_pkg("mcp", "mcp SDK")
        from mcp_server.server import MCPServer

        server = MCPServer()
        tools = asyncio.run(server.mcp.list_tools())
        for tool in tools:
            schema = tool.inputSchema
            assert schema and schema.get("type") == "object"
            assert "properties" in schema
            # FastMCP drops an empty `required` list from the schema (SDK
            # behavior); when present it must match the spec exactly.
            if schema.get("required") is not None:
                assert schema["required"] == EXPECTED_REQUIRED_PARAMS[tool.name]
            assert set(schema.get("properties", {}).keys()) >= set(
                EXPECTED_REQUIRED_PARAMS[tool.name]
            )

    def test_server_instructions_mention_capabilities(self):
        _require_pkg("mcp", "mcp SDK")
        from mcp_server.server import MCPServer

        server = MCPServer()
        instructions = server.mcp.instructions
        assert instructions and "browser.core" in instructions
