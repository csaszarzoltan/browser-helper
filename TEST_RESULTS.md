# Test Results

## 2026-07-29 - Agent Navigation Engine 1.3.0

Environment: Python 3.12.9, isolated development environment created with `uv`, project installed from `.[dev]`.

### Targeted regression

Command:

```bash
PYTHONPATH=.:src .test-venv/bin/pytest -q tests/test_v11_features.py tests/test_agent_navigation.py
```

Result: **22 passed, 0 failed, 1 third-party deprecation warning**.

### Full regression

Command:

```bash
PYTHONPATH=.:src .test-venv/bin/pytest -q
```

Result: **735 passed, 0 failed, 33 warnings** in 115.27 seconds. Warnings are one Starlette/httpx compatibility warning and 32 Pillow `getdata` deprecation warnings in existing screenshot tests.

### Syntax, focused lint and formatting

- `python -m compileall -q src tests run.py examples`: success.
- `ruff check src/agent_navigation.py tests/test_agent_navigation.py`: success.
- `ruff format --check src/agent_navigation.py tests/test_agent_navigation.py`: success.

A repository-wide `ruff check .` still fails on pre-existing broad-exception, import-order, unused-variable and style findings in legacy modules. The new isolated navigation module and test module are clean. No existing lint debt was hidden or disabled.

### Package build

Command:

```bash
uv build
```

Result: success; source distribution and wheel built for version 1.3.0. Build outputs were removed before delivery.
