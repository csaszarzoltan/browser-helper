"""A test that reaches /headless/launch must not start a browser that outlives the test.

Found 2026-10-12: tests/test_headless_api.py and tests/test_proxy_api.py POST /headless/launch
without a stub. On a host with Chrome the launcher started a real headless browser each run
(about 1-2 GB with its renderers), and nothing stopped it. About three per suite run piled up
until the machine ran out of memory. The endpoint tests accept an error status, so the fix is
to point the launcher under test at a binary that does not exist.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_the_headless_launcher_under_test_points_at_no_real_chrome():
    import main

    path = main.headless_mgr._chrome_path
    assert not os.path.exists(path), f"a test that reaches /headless/launch would start {path}"
