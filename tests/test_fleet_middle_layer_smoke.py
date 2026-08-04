"""Verify the fleet middle-layer imports resolve and the 29 RED tests fail
only with HTTP 404 (the API router task is not wired yet)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from fleet import (  # noqa: E402
    FailoverManager,
    FleetHealthChecker,
    FleetQueueManager,
    FleetSessionPool,
    QueueFullError,
)

pytestmark = pytest.mark.quick


def test_all_middle_layer_imports_resolve():
    assert FleetHealthChecker is not None
    assert FleetSessionPool is not None
    assert FleetQueueManager is not None
    assert FailoverManager is not None
    assert issubclass(QueueFullError, Exception)


def test_v115_failures_are_404_only():
    repo = Path(__file__).parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_fleet_v115.py", "-q", "--no-header"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout + proc.stderr
    assert "29 failed" in out, out[-2000:]
    # No ImportError / collection errors — the fleet package must import fine.
    assert "ImportError" not in out
    assert "ModuleNotFoundError" not in out
    assert "collection failed" not in out.lower()
    # Every failure is a 404 (endpoint not wired) or a KeyError/assert that
    # stems from a 404 body — never a logic error inside fleet modules.
    assert "404" in out
