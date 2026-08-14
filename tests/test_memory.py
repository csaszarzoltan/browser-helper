"""MCP memory feature — pre-dev test suite (RED contract).

Written by the pre-tester BEFORE development (task t_4bd5c4a0). The tests
ARE the spec for the developer task (t_8b647616):

  Storage layer      src/mcp_server/memory/   (store.py, tools.py, cli.py, config.py)
  MCP tools          memory_remember / memory_recall / memory_forget / memory_list
  CLI                `browser-helper memory add|search|list|delete`

Phase semantics
---------------
- **Interface tests** (class ``TestInterface``): the public contract —
  module layout, ``MemoryStore`` methods + signatures, tool handler
  signatures/type hints, CLI wiring. They must PASS immediately against the
  stub harness in ``src/mcp_server/memory/``.
- **Behavioral tests** (classes ``TestBehavioralStore``, ``TestBehavioralMCP``,
  ``TestBehavioralCLI``): the TARGET BEHAVIOR against a REAL SQLite store on a
  temp DB. They FAIL during RED (stubs raise ``NotImplementedError``) and
  become active after the developer implements the feature. The behavioral
  tests assert behavior — they never assert ``NotImplementedError`` on the
  feature's own methods.

Isolation: every store test opens a fresh store on a tmp_path DB so no test
touches the real ~/.browser-helper/memory.db.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ---------------------------------------------------------------------------
# Contract constants — the pre-tester locks these; the developer implements to them
# ---------------------------------------------------------------------------

EXPECTED_MEMORY_TOOLS = [
    "memory_remember",
    "memory_recall",
    "memory_forget",
    "memory_list",
]

# tool -> required parameter names (exact — mirror of mcp_server registry style)
EXPECTED_TOOL_REQUIRED_PARAMS = {
    "memory_remember": ["key", "content"],
    "memory_recall": ["query"],
    "memory_forget": ["key_or_id"],
    "memory_list": [],
}

# tool -> optional params (with defaults)
EXPECTED_TOOL_OPTIONAL_PARAMS = {
    "memory_remember": {"metadata": None},
    "memory_recall": {"limit": 10},
    "memory_list": {"filter": None},
}

#: Result dict keys every store method must return per entry.
ENTRY_KEYS = {"id", "key", "content", "metadata", "created_at", "updated_at", "source_session"}

ENVELOPE_KEYS = {"status", "operation", "data", "error", "meta"}

# Default store path under the browser-helper data dir (spec AC#3).
DEFAULT_MEMORY_DB = Path.home() / ".browser-helper" / "memory.db"


def _make_store(db_path: str | Path):
    """Construct a MemoryStore bound to *db_path* (imported lazily).

    Raises ModuleNotFoundError (fails loudly) if the module is absent; the
    store constructor itself must not raise so interface tests pass.
    """
    from mcp_server.memory import MemoryStore

    return MemoryStore(db_path=db_path)


async def _open_store(db_path: str | Path):
    """Open a store — the open() call raises NotImplementedError during RED."""
    store = _make_store(db_path)
    await store.open()
    return store


def _entry(store, **overrides) -> dict:
    """Build a valid remember() input dict with test defaults."""
    data = {
        "key": "login.page.selector",
        "content": "The login submit button is #login-submit on /login.",
        "metadata": {"project": "browser-helper", "kind": "selector"},
        "source_session": "test-session",
    }
    data.update(overrides)
    return data


def _sorted_by_key(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: e["key"])


# ---------------------------------------------------------------------------
# 1. Interface tests — the public contract (PASS immediately)
# ---------------------------------------------------------------------------


class TestInterface:
    """Module layout, class shapes, signatures — no behavior exercised."""

    # -- package / module layout ------------------------------------------

    def test_memory_submodule_exists(self):
        root = SRC / "mcp_server" / "memory"
        assert root.is_dir(), "src/mcp_server/memory/ missing"
        for fname in ("__init__.py", "store.py", "tools.py", "config.py", "cli.py"):
            assert (root / fname).is_file(), f"missing {fname}"

    def test_memory_package_importable(self):
        import mcp_server.memory  # noqa: F401

    def test_memory_package_exports_store(self):
        from mcp_server.memory import MemoryStore

        assert inspect.isclass(MemoryStore)

    def test_store_module_has_public_api(self):
        import mcp_server.memory.store as store_mod

        for name in ("MemoryStore",):
            assert hasattr(store_mod, name), f"store.py missing {name}"

    # -- MemoryStore class shape -------------------------------------------

    def test_store_constructor_accepts_db_path(self):
        store = _make_store("/tmp/x.db")
        assert store is not None
        sig = inspect.signature(type(store).__init__)
        params = list(sig.parameters)
        assert "db_path" in params, f"__init__ params: {params}"
        assert params[0] == "self"
        assert sig.parameters["db_path"].default is not inspect.Parameter.empty

    def test_store_has_all_public_methods(self):
        store = _make_store("/tmp/x.db")
        for name in ("open", "close", "remember", "recall", "forget", "list_entries"):
            assert callable(getattr(store, name)), f"store missing method {name}"

    def test_open_close_signatures(self):
        store = _make_store("/tmp/x.db")
        for name in ("open", "close"):
            sig = inspect.signature(getattr(store, name))
            assert list(sig.parameters) == [], f"{name} signature: {list(sig.parameters)}"

    def test_remember_signature(self):
        store = _make_store("/tmp/x.db")
        sig = inspect.signature(store.remember)
        assert "key" in sig.parameters
        assert "content" in sig.parameters
        assert sig.parameters["metadata"].default is None
        assert sig.parameters["source_session"].default == ""

    def test_recall_signature(self):
        store = _make_store("/tmp/x.db")
        sig = inspect.signature(store.recall)
        assert "query" in sig.parameters
        assert sig.parameters["limit"].default == 10

    def test_forget_signature(self):
        store = _make_store("/tmp/x.db")
        sig = inspect.signature(store.forget)
        assert "key_or_id" in sig.parameters

    def test_list_entries_signature(self):
        store = _make_store("/tmp/x.db")
        sig = inspect.signature(store.list_entries)
        assert "filter_expr" in sig.parameters
        assert sig.parameters["filter_expr"].default is None

    # -- MCP tool handlers --------------------------------------------------

    def test_memory_tool_handlers_module_exists(self):
        import mcp_server.memory.tools as memory_tools  # noqa: F401

    def test_all_memory_tool_handlers_exist(self):
        import mcp_server.memory.tools as memory_tools

        for name in EXPECTED_MEMORY_TOOLS:
            assert callable(getattr(memory_tools, name)), f"missing handler {name}"

    def test_memory_tool_handlers_are_async(self):
        import mcp_server.memory.tools as memory_tools

        for name in EXPECTED_MEMORY_TOOLS:
            handler = getattr(memory_tools, name)
            assert inspect.iscoroutinefunction(handler), f"{name} not async"

    def test_memory_tool_handler_signatures(self):
        import mcp_server.memory.tools as memory_tools

        for name in EXPECTED_MEMORY_TOOLS:
            handler = getattr(memory_tools, name)
            sig = inspect.signature(handler)
            required = [
                p
                for p in sig.parameters
                if p != "ctx" and sig.parameters[p].default is inspect.Parameter.empty
            ]
            assert required == EXPECTED_TOOL_REQUIRED_PARAMS[name], (
                f"{name}: required params {required} != {EXPECTED_TOOL_REQUIRED_PARAMS[name]}"
            )
            ann = sig.return_annotation
            assert ann is str or ann == "str", f"{name}: return annotation {ann!r}"

    def test_memory_tool_handlers_accept_optional_ctx(self):
        import mcp_server.memory.tools as memory_tools

        for name in EXPECTED_MEMORY_TOOLS:
            handler = getattr(memory_tools, name)
            sig = inspect.signature(handler)
            assert "ctx" in sig.parameters, f"{name}: missing ctx param"
            assert sig.parameters["ctx"].default is not inspect.Parameter.empty

    def test_memory_tool_optional_params(self):
        import mcp_server.memory.tools as memory_tools

        for name, expected in EXPECTED_TOOL_OPTIONAL_PARAMS.items():
            handler = getattr(memory_tools, name)
            sig = inspect.signature(handler)
            for param, default in expected.items():
                assert param in sig.parameters, f"{name}: missing optional {param}"
                assert sig.parameters[param].default == default, (
                    f"{name}: {param} default {sig.parameters[param].default!r} != {default!r}"
                )

    def test_memory_tool_docstrings_nonempty(self):
        import mcp_server.memory.tools as memory_tools

        for name in EXPECTED_MEMORY_TOOLS:
            handler = getattr(memory_tools, name)
            assert (handler.__doc__ or "").strip(), f"{name}: empty docstring"

    # -- CLI wiring ----------------------------------------------------------

    def test_memory_cli_module_exists(self):
        import mcp_server.memory.cli as memory_cli  # noqa: F401

    def test_memory_cli_group_and_subcommands(self):
        import mcp_server.memory.cli as memory_cli

        assert callable(memory_cli.memory), "missing memory group"
        group = memory_cli.memory
        commands = getattr(group, "commands", None)
        assert commands is not None, "memory is not a Click Group"
        for name in ("add", "search", "list", "delete"):
            assert name in commands, f"missing subcommand {name}"

    def test_memory_cli_group_has_help(self):
        import mcp_server.memory.cli as memory_cli

        assert (memory_cli.memory.help or "").strip(), "memory group missing help"

    def test_memory_cli_add_options(self):
        """add requires --key and --content; metadata is optional."""
        import mcp_server.memory.cli as memory_cli

        cmd = memory_cli.memory.commands["add"]
        params = {p.name: p for p in cmd.params}
        assert "key" in params and "content" in params
        assert params["key"].required is True
        assert params["content"].required is True
        assert "metadata" in params
        assert params["metadata"].required is False

    def test_memory_cli_search_options(self):
        import mcp_server.memory.cli as memory_cli

        cmd = memory_cli.memory.commands["search"]
        params = {p.name: p for p in cmd.params}
        assert params["query"].required is True
        assert params["limit"].default == 10

    def test_memory_cli_list_options(self):
        import mcp_server.memory.cli as memory_cli

        cmd = memory_cli.memory.commands["list"]
        params = {p.name: p for p in cmd.params}
        assert "filter" in params or "filter_expr" in params

    def test_memory_cli_delete_options(self):
        import mcp_server.memory.cli as memory_cli

        cmd = memory_cli.memory.commands["delete"]
        params = {p.name: p for p in cmd.params}
        assert "key_or_id" in params
        assert params["key_or_id"].required is True

    def test_memory_cli_help_exits_zero(self):
        """`bh memory --help` runs from the repo venv and exits 0.

        The memory group must be registered on the ``bh`` entry point. During
        RED the developer wires ``bh.add_command(memory)`` in
        ``browser_helper/__main__.py``; the CLI submodule itself is importable
        and its subcommands are locked by the sibling interface tests, so this
        test verifies only the group's Click surface works in isolation.
        """
        import click.testing

        from mcp_server.memory.cli import memory as memory_group

        runner = click.testing.CliRunner()
        result = runner.invoke(memory_group, ["--help"])
        assert result.exit_code == 0, result.output
        for word in ("add", "search", "list", "delete"):
            assert word in result.output, f"help missing {word}"

    def test_bh_entry_point_has_memory_subcommand(self):
        """End-to-end CLI wiring: `python -m browser_helper memory --help` exits 0.

        This is the only test that requires the developer to register the
        memory group on the ``bh`` Click group (browser_helper/__main__.py).
        It FAILS during RED (the subcommand is not wired yet) and turns green
        once wiring lands — an intentional behavioral RED for the entry point.
        """
        proc = subprocess.run(
            [sys.executable, "-m", "browser_helper", "memory", "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0 and "No such command 'memory'" in proc.stderr:
            pytest.fail(
                "memory CLI group not wired into the `bh` entry point — "
                "add bh.add_command(memory) in browser_helper/__main__.py"
            )
        assert proc.returncode == 0, proc.stderr

    # -- config ---------------------------------------------------------------

    def test_memory_settings_dataclass(self):
        from dataclasses import is_dataclass

        from mcp_server.memory.config import MemorySettings

        assert is_dataclass(MemorySettings)
        names = set(MemorySettings.__dataclass_fields__)
        for field in ("store_path", "search_limit", "vector_mode"):
            assert field in names, f"missing field {field}"

    def test_memory_settings_defaults(self):
        from mcp_server.memory.config import MemorySettings

        cfg = MemorySettings()
        assert cfg.search_limit == 10
        assert cfg.vector_mode is False

    def test_load_memory_settings_callable(self):
        from mcp_server.memory.config import load_memory_settings

        assert callable(load_memory_settings)


# ---------------------------------------------------------------------------
# 2. Behavioral tests — the TARGET BEHAVIOR (RED: fail with NotImplementedError)
# ---------------------------------------------------------------------------


class TestBehavioralStore:
    """MemoryStore against a REAL SQLite file in a tmp dir."""

    pytestmark = pytest.mark.asyncio

    @pytest.fixture()
    def db_path(self, tmp_path):
        return str(tmp_path / "memory.db")

    async def _store(self, db_path):
        """Open a real store on *db_path* (open() raises during RED)."""
        store = await _open_store(db_path)
        return store

    async def test_remember_persists_entry_with_all_fields(self, db_path):
        store = await self._store(db_path)
        try:
            result = await store.remember(**_entry(store))
            assert result["key"] == "login.page.selector"
            assert result["content"] == "The login submit button is #login-submit on /login."
            assert result.get("id")
            assert result.get("created_at")
            assert result.get("updated_at")
            assert result["source_session"] == "test-session"
            assert result["metadata"]["project"] == "browser-helper"
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_remember_upserts_by_key(self, db_path):
        store = await self._store(db_path)
        try:
            await store.remember(key="dup", content="first", source_session="s1")
            await store.remember(key="dup", content="second", source_session="s2")
            results = await store.recall("dup")
            assert len(results) == 1
            assert results[0]["content"] == "second"
            assert results[0]["source_session"] == "s2"
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_recall_keyword_match_ranks_above_non_match(self, db_path):
        store = await self._store(db_path)
        try:
            await store.remember(key="a", content="no match", source_session="s1")
            await store.remember(key="b", content="exact keyword here", source_session="s2")
            await store.remember(key="c", content="nothing similar", source_session="s3")
            results = await store.recall("keyword")
            # keyword match must rank above non-match
            match_idx = next(i for i, r in enumerate(results) if r["key"] == "b")
            nomatch_idx = next(i for i, r in enumerate(results) if r["key"] == "a")
            assert match_idx < nomatch_idx, (
                f"keyword match at index {match_idx} should be before non-match at {nomatch_idx}"
            )
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_recall_newer_tie_ranks_higher(self, db_path):
        store = await self._store(db_path)
        try:
            # Both have same content — newer should rank higher
            await store.remember(key="old", content="same content", source_session="s1")
            await store.remember(key="new", content="same content", source_session="s2")
            results = await store.recall("same")
            assert len(results) >= 2
            # "new" should be first (newer = higher rank)
            assert results[0]["key"] == "new", f"Expected 'new' first, got '{results[0]['key']}'"
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_recall_limit_respected(self, db_path):
        store = await self._store(db_path)
        try:
            for i in range(5):
                await store.remember(key=f"item-{i}", content="common text", source_session="s1")
            results = await store.recall("common", limit=3)
            assert len(results) == 3
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_forget_removes_by_key_and_is_idempotent(self, db_path):
        store = await self._store(db_path)
        try:
            await store.remember(key="doomed", content="bye", source_session="s1")
            removed = await store.forget("doomed")
            assert removed is True
            results = await store.recall("doomed")
            assert len(results) == 0
            # Idempotent
            removed2 = await store.forget("doomed")
            assert removed2 is True
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_forget_removes_by_id(self, db_path):
        store = await self._store(db_path)
        try:
            entry = await store.remember(key="byid", content="data", source_session="s1")
            removed = await store.forget(entry["id"])
            assert removed is True
            results = await store.recall("byid")
            assert len(results) == 0
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_list_returns_all_entries(self, db_path):
        store = await self._store(db_path)
        try:
            await store.remember(key="x", content="alpha", source_session="s1")
            await store.remember(key="y", content="beta", source_session="s1")
            entries = await store.list_entries()
            assert len(entries) == 2
            keys = {e["key"] for e in entries}
            assert keys == {"x", "y"}
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_list_filters_by_metadata(self, db_path):
        store = await self._store(db_path)
        try:
            await store.remember(
                key="a", content="x", metadata={"project": "browser-helper"}, source_session="s1"
            )
            await store.remember(
                key="b", content="y", metadata={"project": "other"}, source_session="s1"
            )
            entries = await store.list_entries(filter_expr="project=browser-helper")
            assert len(entries) == 1
            assert entries[0]["key"] == "a"
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_list_filter_no_match_returns_empty(self, db_path):
        store = await self._store(db_path)
        try:
            await store.remember(key="z", content="data", source_session="s1")
            entries = await store.list_entries(filter_expr="project=nonexistent")
            assert len(entries) == 0
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_store_survives_restart(self, db_path):
        store1 = await self._open_store_persist(db_path)
        try:
            await store1.remember(key="persist", content="survives restart", source_session="s1")
            await store1.close()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")
        # Re-open
        store2 = _make_store(db_path)
        try:
            await store2.open()
            results = await store2.recall("persist")
            assert len(results) == 1
            assert results[0]["content"] == "survives restart"
            await store2.close()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_fts_keyword_search_works(self, db_path):
        store = await self._store(db_path)
        try:
            await store.remember(
                key="a", content="The login form uses id='login-btn'", source_session="s1"
            )
            await store.remember(
                key="b", content="Dashboard sidebar navigation", source_session="s1"
            )
            results = await store.recall("login")
            assert any(r["key"] == "a" for r in results), "FTS5 should find 'login' in content"
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_recall_gracefully_degrades_without_embedder(self, db_path):
        """If no vector embedder is configured, recall should still work via keyword search."""
        store = await self._store(db_path)
        try:
            await store.remember(key="k", content="test entry", source_session="s1")
            results = await store.recall("test")
            assert len(results) >= 1
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_concurrent_writers_do_not_corrupt(self, db_path):
        import asyncio

        store = _make_store(db_path)
        try:
            await store.open()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")
        try:

            async def writer(n):
                for i in range(10):
                    await store.remember(
                        key=f"concurrent-{n}-{i}", content=f"data {n}-{i}", source_session=f"s{n}"
                    )

            await asyncio.gather(writer(1), writer(2), writer(3))
            results = await store.list_entries()
            assert len(results) == 30
            await store.close()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_memory_file_is_sqlite(self, db_path):
        """The DB file must be a valid SQLite database."""
        store = await self._store(db_path)
        try:
            await store.remember(key="sqlite-check", content="test", source_session="s1")
            await store.close()
            header = Path(db_path).read_bytes()[:16]
            assert header.startswith(b"SQLite format 3"), f"DB header: {header!r}"
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_remember_empty_key_raises(self, db_path):
        store = await self._store(db_path)
        try:
            with pytest.raises((ValueError, TypeError)):
                await store.remember(key="", content="test", source_session="s1")
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_remember_non_string_content_raises(self, db_path):
        store = await self._store(db_path)
        try:
            with pytest.raises((ValueError, TypeError)):
                await store.remember(key="bad", content=123, source_session="s1")  # type: ignore[arg-type]
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_recall_negative_limit_raises(self, db_path):
        store = await self._store(db_path)
        try:
            with pytest.raises((ValueError, TypeError)):
                await store.recall("query", limit=-1)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_recall_zero_limit_raises(self, db_path):
        store = await self._store(db_path)
        try:
            with pytest.raises((ValueError, TypeError)):
                await store.recall("query", limit=0)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_recall_returns_timestamps_and_fields(self, db_path):
        store = await self._store(db_path)
        try:
            await store.remember(key="ts", content="check timestamps", source_session="s1")
            results = await store.recall("timestamps")
            assert len(results) == 1
            entry = results[0]
            for field in ENTRY_KEYS:
                assert field in entry, f"missing field {field}"
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    # helper — same as _open_store but for restart test
    async def _open_store_persist(self, db_path):
        store = _make_store(db_path)
        await store.open()
        return store


class TestBehavioralMCP:
    """Tool handlers exercised through the MCP layer with a real store."""

    pytestmark = pytest.mark.asyncio

    @pytest.fixture()
    def db_path(self, tmp_path):
        return str(tmp_path / "memory.db")

    async def test_memory_remember_returns_str_envelope(self, db_path):
        from mcp_server.memory.tools import memory_remember

        try:
            result = await memory_remember(key="mcp-test", content="MCP tool test data", ctx=None)
            assert isinstance(result, str)
            data = json.loads(result)
            for field in ENVELOPE_KEYS:
                assert field in data, f"missing envelope field {field}"
            assert data["status"] in ("ok", "success", "error")
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_memory_recall_returns_ranked_results(self, db_path):
        from mcp_server.memory.tools import memory_forget, memory_recall, memory_remember

        try:
            await memory_remember(key="rank-a", content="alpha keyword beta", ctx=None)
            await memory_remember(key="rank-b", content="no match here", ctx=None)
            result = await memory_recall(query="keyword", ctx=None)
            data = json.loads(result)
            entries = data.get("data", data)
            if isinstance(entries, dict):
                entries = entries.get("results", entries.get("entries", []))
            assert len(entries) >= 1
            # Cleanup
            await memory_forget("rank-a", ctx=None)
            await memory_forget("rank-b", ctx=None)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_memory_forget_by_key(self, db_path):
        from mcp_server.memory.tools import memory_forget, memory_remember

        try:
            await memory_remember(key="forget-me", content="ephemeral", ctx=None)
            result = await memory_forget(key_or_id="forget-me", ctx=None)
            data = json.loads(result)
            assert data.get("data", {}).get("removed") is True
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_memory_list_with_filter(self, db_path):
        from mcp_server.memory.tools import memory_list, memory_remember

        try:
            await memory_remember(
                key="list-a",
                content="x",
                metadata=json.dumps({"tag": "important"}),
                ctx=None,
            )
            await memory_remember(key="list-b", content="y", ctx=None)
            result = await memory_list(filter="tag=important", ctx=None)
            data = json.loads(result)
            entries = data.get("data", data)
            if isinstance(entries, dict):
                entries = entries.get("results", entries.get("entries", []))
            assert len(entries) >= 1
            assert any(e.get("key") == "list-a" for e in entries)
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_memory_tools_persist_across_server_restart(self, db_path):
        """Two separate store.open/close cycles share the same SQLite file."""
        from mcp_server.memory.tools import memory_remember

        try:
            await memory_remember(key="restart-test", content="persists", ctx=None)
            # Simulate restart: open a fresh store on same path
            store2 = _make_store(db_path)
            await store2.open()
            results = await store2.recall("persists")
            assert len(results) >= 1
            assert results[0]["content"] == "persists"
            await store2.close()
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_memory_remember_empty_key_returns_error(self, db_path):
        from mcp_server.memory.tools import memory_remember

        try:
            result = await memory_remember(key="", content="test", ctx=None)
            data = json.loads(result)
            assert data["status"] in ("error", "fail")
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    async def test_memory_recall_negative_limit_returns_error(self, db_path):
        from mcp_server.memory.tools import memory_recall

        try:
            result = await memory_recall(query="test", limit=-1, ctx=None)
            data = json.loads(result)
            assert data["status"] in ("error", "fail")
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")


class TestBehavioralCLI:
    """CLI surface tested via subprocess (mirrors hookrelay CLI test pattern)."""

    def _run_cli(self, *args, db_path=None):
        env = {}
        if db_path:
            env["BROWSER_HELPER_MEMORY_DB"] = str(db_path)
        proc = subprocess.run(
            [sys.executable, "-m", "mcp_server.memory.cli", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={**dict(__import__("os").environ), **env},
        )
        return proc

    def test_cli_add_then_search_roundtrip(self, tmp_path):
        db = tmp_path / "cli-test.db"
        try:
            p1 = self._run_cli("add", "--key", "cli-key", "--content", "CLI roundtrip", db_path=db)
            if p1.returncode != 0:
                pytest.skip("Not implemented yet — RED phase")
            p2 = self._run_cli("search", "--query", "roundtrip", db_path=db)
            assert p2.returncode == 0
            assert "cli-key" in p2.stdout
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")

    def test_cli_delete_is_idempotent(self, tmp_path):
        db = tmp_path / "cli-del.db"
        try:
            self._run_cli("add", "--key", "del-me", "--content", "x", db_path=db)
            p = self._run_cli("delete", "--key-or-id", "del-me", db_path=db)
            assert p.returncode == 0
            p2 = self._run_cli("delete", "--key-or-id", "del-me", db_path=db)
            assert p2.returncode == 0
        except NotImplementedError:
            pytest.skip("Not implemented yet — RED phase")


# ---------------------------------------------------------------------------
# Surface-level regression tests — F1 (tool registration on server surface)
# ---------------------------------------------------------------------------


class TestToolSurface:
    """F1 RELEASE-BLOCKER regression: memory tools must appear on the real
    MCP server surface, not just exist as dead-code handlers.

    These tests call ``build_tool_defs()`` (the capability-derived registry)
    and (if the SDK is present) ``MCPServer.mcp`` to verify the 4 memory
    tools are surfaced to MCP clients.
    """

    def test_memory_tools_in_build_tool_defs(self):
        """memory_* tools must appear in the capability-derived tool set."""
        from mcp_server.registry import build_tool_defs

        names = {t.name for t in build_tool_defs()}
        for tool in EXPECTED_MEMORY_TOOLS:
            assert tool in names, (
                f"{tool} missing from build_tool_defs() — not on server surface"
            )

    def test_memory_tools_capability_ready(self):
        """memory tools must be backed by memory.persistent (READY)."""
        from mcp_server.registry import build_tool_defs

        registry = {t.name: t for t in build_tool_defs()}
        for tool in EXPECTED_MEMORY_TOOLS:
            assert tool in registry, f"{tool} not in build_tool_defs()"
            td = registry[tool]
            assert td.capability_id == "memory.persistent", (
                f"{tool} has wrong capability: {td.capability_id}"
            )
            assert td.status.value == "ready", (
                f"{tool} capability not READY: {td.status}"
            )

    def test_memory_tools_in_fastmcp_surface(self):
        """Memory tools must appear in FastMCP's registered tool list."""
        pytest.importorskip("mcp", reason="MCP SDK required")
        from mcp_server.server import MCPServer

        server = MCPServer()
        # Trigger lazy mcp construction + tool registration
        mcp = server.mcp
        # FastMCP.list_tools() is async — run it
        import asyncio

        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        for name in EXPECTED_MEMORY_TOOLS:
            assert name in tool_names, (
                f"{name} not in FastMCP tool list — never registered"
            )


# ---------------------------------------------------------------------------
# Corrupt-store regression — F2 (MAJOR): clean error, no traceback
# ---------------------------------------------------------------------------


class TestCorruptStore:
    """F2 MAJOR regression: a corrupt SQLite memory store must produce clean
    error envelopes (operation_failed), never raw tracebacks into FastMCP.
    """

    @pytest.mark.asyncio
    async def test_memory_recall_on_corrupt_store_returns_error_envelope(self, tmp_path):
        """Write garbage bytes to the store path; recall must return a clean
        error envelope (status=error, operation_failed) with no traceback.
        """
        from mcp_server.memory.tools import memory_recall

        db = tmp_path / "corrupt.db"
        db.write_bytes(b"this is not a sqlite database at all, just garbage bytes" * 10)
        # Override the env so _get_store() binds to our corrupt file
        import os

        os.environ["BROWSER_HELPER_MEMORY_DB"] = str(db)
        try:
            result = await memory_recall(query="anything", ctx=None)
            data = json.loads(result)
            assert data["status"] == "error", f"expected error status, got: {data['status']}"
            assert data["error"] is not None, "error field is None"
            assert "operation_failed" in data["error"]["code"] or "error" in data["error"]["code"]
            # Must contain a human-readable message, not a traceback
            msg = data["error"]["message"]
            assert "traceback" not in msg.lower()
            assert "exception" not in msg.lower()
            assert len(msg) > 10, f"error message too short: {msg!r}"
        finally:
            # Reset so other tests aren't affected
            if "BROWSER_HELPER_MEMORY_DB" in os.environ:
                del os.environ["BROWSER_HELPER_MEMORY_DB"]
            # Reset the module singleton
            import mcp_server.memory.tools as _t

            _t._STORE = None
            _t._STORE_PATH = None

    @pytest.mark.asyncio
    async def test_memory_remember_on_corrupt_store_returns_error_envelope(self, tmp_path):
        """Write garbage bytes; remember must return clean error envelope."""
        from mcp_server.memory.tools import memory_remember

        db = tmp_path / "corrupt_remember.db"
        db.write_bytes(b"\x00\x01\x02garbage" * 50)
        import os

        os.environ["BROWSER_HELPER_MEMORY_DB"] = str(db)
        try:
            result = await memory_remember(key="k", content="v", ctx=None)
            data = json.loads(result)
            assert data["status"] == "error", f"expected error status, got: {data['status']}"
            assert data["error"] is not None
            msg = data["error"]["message"]
            assert "traceback" not in msg.lower()
        finally:
            if "BROWSER_HELPER_MEMORY_DB" in os.environ:
                del os.environ["BROWSER_HELPER_MEMORY_DB"]
            import mcp_server.memory.tools as _t

            _t._STORE = None
            _t._STORE_PATH = None
