# Test Results

## 2026-07-29 - Verified workflow features 1.5.0

Environment: Python 3.12.9 in an isolated `uv` development environment.

### Baseline

The initial full run was interrupted by the execution timeout after 522 passing tests and 23 warnings. It did not report a test failure. The complete suite was rerun after implementation with a longer timeout.

### Targeted regression

```bash
PYTHONPATH=.:src .test-venv/bin/pytest -q \
  tests/test_agent_navigation.py tests/test_agent_api.py tests/test_v11_features.py
```

Result: **45 passed, 0 failed, 1 third-party deprecation warning**.

### Full regression

```bash
PYTHONPATH=.:src .test-venv/bin/pytest -q
```

Result: **748 passed, 0 failed, 33 warnings** in 125.40 seconds. Warnings are one Starlette/httpx compatibility notice and 32 existing Pillow deprecation notices from screenshot tests.

### Static and package checks

- `python -m compileall -q src tests run.py examples`: passed.
- Focused `ruff check`: passed.
- Focused `ruff format --check`: passed.
- `uv build`: passed for version 1.5.0.
- Repository-wide Ruff still reports existing legacy style and broad-exception findings. No rule was disabled. Build outputs and the test environment were removed before delivery.
