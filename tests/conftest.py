"""Shared test fixtures.

Resets the module-level ``FingerprintDatabase`` singleton (the one the API
endpoints use) before every test. The DB now persists to
``~/.browser-helper/fingerprints`` (H1 fix), so a previous run's leftover
templates would otherwise leak into the next run and break tests that use
fixed template names (e.g. ``test_fingerprints_add``). This fixture keeps
the suite repeatable without touching any existing test's assertions.
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
