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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


@pytest.fixture(autouse=True)
def _reset_module_fingerprint_db():
    """Restore the API's fingerprint DB to a clean defaults-only state.

    Runs before every test: clears the in-memory store, reseeds the shipped
    defaults, and removes persisted JSON files so ``load()`` on a later
    ``FingerprintDatabase()`` construction cannot resurrect test templates.
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
    yield


@pytest.fixture(autouse=True)
def _no_real_chrome(monkeypatch):
    """Prevent API endpoint tests from launching real Chrome.

    ``run_op`` / ``_resolve_session_client`` mint a per-client session via
    ``chrome_mgr.launch()``. In the test environment there is no Chrome on
    the test port, so those calls return 503. Stub the launcher (no-op
    failure) and mark the global client as connected so ``_ensure_browser``
    short-circuits and the endpoint runs against the mocked client — same
    behaviour as the pre-session tests expected.
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
    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    yield
