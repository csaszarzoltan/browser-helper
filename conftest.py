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

import os
import sys
from pathlib import Path

# Repo gyökér = a tests/ mappa szülője (a root conftest a repo gyökerében van,
# a tests/conftest.py a tests/ alatt — itt a __file__ a repo gyökere).
_REPO = Path(__file__).resolve().parent
_SRC = str(_REPO / "src")
sys.path.insert(0, _SRC)

import pytest


@pytest.fixture(autouse=True, scope="session")
def _subprocess_pythonpath():
    """Make ``src/`` importable for subprocess-based CLI tests.

    Tests like ``test_fleet_v115.py::TestCLI`` and ``test_memory.py`` spawn
    ``python -m fleet.cli`` / ``python -m mcp_server.memory.cli`` in a
    subprocess with ``env={**os.environ}``.  Without ``src/`` on
    ``PYTHONPATH`` those modules are not found (``No module named ...``) and
    the CLI tests fail even though the package is healthy.  Seed the env
    once per session so every spawned CLI sees the same import path the
    in-process tests use.
    """
    env_key = "PYTHONPATH"
    old = os.environ.get(env_key)
    parts = [p for p in (old or "").split(os.pathsep) if p]
    if _SRC not in parts:
        os.environ[env_key] = os.pathsep.join([_SRC, *parts])
        print(f"[conftest] PYTHONPATH={os.environ[env_key]}", flush=True)
    yield
    if old is None:
        os.environ.pop(env_key, None)
    else:
        os.environ[env_key] = old


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
    except Exception:
        pass

    # Rate limiter: reset to defaults so /rate/config default assertions
    # hold regardless of test order (other tests toggle the config).
    try:
        from cdp_client import RateLimitConfig

        main.client.rate_limiter.config = RateLimitConfig()
    except Exception:
        pass
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
