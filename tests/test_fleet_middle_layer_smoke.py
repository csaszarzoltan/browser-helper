"""Verify the fleet imports resolve and the 29 integration tests pass.

Originally a RED-phase smoke test (asserted the v115 suite failed only with
HTTP 404 before the API router was wired).  Once ``src/fleet/api.py`` is
wired into ``main.py`` the same checks flip to GREEN: the suite must pass
end-to-end with no ImportError or collection errors.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from fleet import (
    FailoverManager,
    FleetCoordinator,
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
    assert FleetCoordinator is not None
    assert issubclass(QueueFullError, Exception)


def test_v115_suite_passes_after_wiring():
    repo = Path(__file__).parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_fleet_v115.py", "-q", "--no-header"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    out = proc.stdout + proc.stderr
    assert "29 passed" in out, out[-3000:]
    # The fleet package must import cleanly — no ImportError / collection errors.
    assert "ImportError" not in out
    assert "ModuleNotFoundError" not in out
    assert "collection failed" not in out.lower()
