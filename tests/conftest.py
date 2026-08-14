"""Shared test fixtures.

Resets the module-level ``FingerprintDatabase`` singleton (the one the API
endpoints use) before every test. The DB now persists to
``~/.browser-helper/fingerprints`` (H1 fix), so a previous run's leftover
templates would otherwise leak into the next run and break tests that use
fixed template names (e.g. ``test_fingerprints_add``). This fixture keeps
the suite repeatable without touching any existing test's assertions.

Also: since v1.21 the ``run_op`` path mints a per-client session
(``session_registry.create``) which launches REAL Chrome — that makes
API tests that hit browser endpoints (``/click/*``, ``/form/fill``,
``/dropdown/select``, ``/wait/visible``, ...) return 503 instead of the
expected 200/400/422/500. The autouse ``_no_real_chrome`` fixture below
stubs the Chrome launcher so endpoint tests run against the mocked/global
client exactly like they did before per-client sessions existed.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def _reset_module_fingerprint_db(tmp_path, monkeypatch):
    """Restore the API's fingerprint DB to a clean defaults-only state.

    Runs before every test: clears the in-memory store, reseeds the shipped
    defaults, and removes persisted JSON files so ``load()`` on a later
    ``FingerprintDatabase()`` construction cannot resurrect test templates.
    Also redirects the baseline manager to a temp dir so screenshot/baseline
    tests start from an empty state instead of seeing real recorded
    baselines from the live service.
    """
    import main

    db = main._fingerprint_db
    db._templates.clear()
    db._load_defaults()
    storage = db._storage_dir
    if storage.exists():
        for json_file in storage.glob("*.json"):
            try:
                json_file.unlink()
            except OSError:
                pass

    # Baseline manager: point at a fresh temp dir so /screenshot/baselines
    # starts empty (real baselines were recorded during e2e runs).
    try:
        from baseline_manager import BaselineManager

        fresh = tmp_path / "baselines"
        fresh.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            main, "baseline_mgr", BaselineManager(base_dir=str(fresh))
        )
    except Exception as exc:  # noqa: BLE001 - optional baseline manager, tests pass without it
        logger.debug("baseline_manager setup failed (optional): %s", exc)
    yield


@pytest.fixture(autouse=True)
def _no_real_chrome(monkeypatch, request):
    """Prevent API endpoint tests from launching real Chrome.

    ``run_op`` / ``_resolve_session_client`` mint a per-client session via
    ``chrome_mgr.launch()``. In the test environment there is no Chrome on
    the test port, so those calls return 503. Stub the launcher (no-op
    failure) and mark the global client as connected so ``_ensure_browser``
    short-circuits and the endpoint runs against the mocked client — same
    behaviour as the pre-session tests expected.

    The MCP integration tests (``test_mcp_integration.py``) deliberately
    exercise the NOT-connected gate ("CDP" error) — the connected mock
    would make those tools return success. Skip the connected override
    for them.
    """
    import main

    async def _noop_launch(**kwargs):
        return {"status": "error", "error": "test stub: no real Chrome"}

    async def _no_session(*args, **kwargs):
        raise RuntimeError("test stub: no real Chrome session")

    async def _noop_ensure_browser(*args, **kwargs):
        return None

    async def _resolve_no_session_client():
        # Tests run without cookies → session-less fallback to the global client,
        # matching the pre-session behaviour endpoint tests were written against.
        await _noop_ensure_browser()
        return main.client, None

    monkeypatch.setattr(main.chrome_mgr, "launch", _noop_launch)
    monkeypatch.setattr(main.session_registry, "create", _no_session)
    monkeypatch.setattr(main, "_ensure_browser", _noop_ensure_browser)
    monkeypatch.setattr(main, "_resolve_session_client", _resolve_no_session_client)
    # MCP e2e tests assert the deterministic "not connected to CDP" error;
    # leave the global client disconnected for them.
    is_mcp = "mcp_integration" in str(request.node.fspath or "")
    if not is_mcp:
        monkeypatch.setattr(main.client, "_connected", True, raising=False)
    yield


@pytest.fixture(autouse=True)
def _isolate_memory_db(tmp_path, monkeypatch, request):
    """Point the MCP memory tools at a per-test temp DB (hermetic).

    The memory tool handlers resolve their store path via
    ``load_memory_settings`` (``BROWSER_HELPER_MEMORY_DB`` env override,
    default ``~/.browser-helper/memory.db``). Without a redirect the
    behavioral MCP tests in ``test_memory.py`` would write to — and pollute
    — the real user store. Redirecting to ``<tmp_path>/memory.db`` keeps the
    suite hermetic: the test's own ``db_path`` fixture resolves to the same
    file, which is what ``test_memory_tools_persist_across_server_restart``
    relies on (the tool layer and a fresh ``MemoryStore`` on ``db_path``
    must share one SQLite file). Gated to the memory test module so no
    other test's environment changes.
    """
    fspath = getattr(request.node, "fspath", None)
    if fspath is None or Path(fspath).name != "test_memory.py":
        return
    monkeypatch.setenv("BROWSER_HELPER_MEMORY_DB", str(tmp_path / "memory.db"))
