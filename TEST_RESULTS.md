# Test Results

## 2026-07-29 - Snapshot, modal and workflow reliability 1.4.0

Environment: Python 3.12.9; isolated `uv` environment; project installed from `.[dev]`.

### Baseline

```bash
PYTHONPATH=.:src .test-venv/bin/pytest -q
```

Result before modifications: **735 passed, 0 failed, 33 warnings**.

### Targeted regression

```bash
PYTHONPATH=.:src .test-venv/bin/pytest -q \
  tests/test_agent_navigation.py tests/test_agent_api.py tests/test_v11_features.py
```

Result: **39 passed, 0 failed, 1 third-party deprecation warning**.

### Full regression after final changes

```bash
PYTHONPATH=.:src .test-venv/bin/pytest -q
```

Result: **742 passed, 0 failed, 33 warnings** in 116.96 seconds. Warnings are one Starlette/httpx compatibility notice and 32 existing Pillow `getdata()` deprecation notices from screenshot tests.

### Static and packaging checks

- `python -m compileall -q src tests run.py examples`: passed.
- `ruff check src/agent_runtime.py src/agent_navigation.py tests/test_agent_navigation.py`: passed after formatting/import cleanup.
- `ruff format --check src/agent_runtime.py src/agent_navigation.py tests/test_agent_navigation.py`: passed.
- `uv build`: passed for version 1.4.0; generated build outputs were removed before delivery.
- Repository-wide `ruff check .`: still fails on existing legacy broad-exception, import-order, unused-variable and style findings. No lint rule was disabled and no existing debt was hidden.
