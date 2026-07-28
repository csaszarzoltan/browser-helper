# Test results

Validated on 2026-07-28 with Python 3.12.9.

## Targeted agent and documentation suite

```text
42 passed, 1 warning
```

## Full regression suite

```text
590 passed, 33 warnings in 53.53s
```

Warnings are one Starlette/httpx deprecation warning and existing Pillow `getdata()` deprecation warnings. There were no test failures.

## New-code lint

```text
ruff check src/agent_runtime.py src/artifact_store.py src/headless_manager.py tests/test_agent_api.py --ignore BLE001,S110
All checks passed!
```

The repository-wide Ruff run still reports pre-existing broad-exception and style findings in legacy modules and tests.
