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

## 2026-08-01 - Task-oriented dashboard UX improvement

Environment: Python 3.12 isolated with `uv sync --extra dev`.

### TDD acceptance test

The seven new tests in `tests/test_dashboard_ux_v19.py` were executed before implementation and failed as expected. After implementation:

```bash
PYTHONPATH=src uv run pytest -q tests/test_dashboard_ux_v19.py
```

Result: **7 passed, 0 failed**.

### Targeted regression

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_dashboard_ux_v19.py tests/test_core.py \
  tests/test_agent_api.py tests/test_enterprise_workspace.py
```

Result: **137 passed, 0 failed, 1 third-party deprecation warning**.

### Full regression and baseline comparison

Modified project result: **1,950 passed, 222 failed, 3 skipped, 8 xfailed, 32 xpassed**.  
Unmodified supplied archive in the same environment: **1,944 passed, 221 failed, 3 skipped, 8 xfailed, 32 xpassed**.

The modified project adds seven passing tests. Failure-set comparison found a single additional randomized failure in `TestKeystrokeTimingRED::test_occasional_typo_backspace`; the test also failed when rerun alone and is unrelated to the dashboard change. All other failures match the supplied baseline and are existing RED-phase or incomplete-feature tests.

### Static checks

- `python -m compileall -q src tests run.py examples`: passed.
- `ruff check tests/test_dashboard_ux_v19.py`: passed.
- `node --check static/dashboard_ux.js`: passed.

## 2026-08-01 - Guided browser flow continuation

Five additional acceptance tests were written first and confirmed RED. The implementation adds validated navigation, screenshot and observation shortcuts, recent URL reuse, accessible busy/error/success feedback, and Enter-to-navigate behavior.

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_guided_browser_flow_v19.py tests/test_dashboard_ux_v19.py
```

Result: **12 passed, 0 failed**.

## 2026-08-01 - Correlated guided run history continuation

Five acceptance tests were added first and confirmed RED. The implementation adds bounded, tab-session-scoped run correlation, duration and outcome tracking, retry, confirmed clear, and redacted JSON export.

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_guided_run_history_v19.py \
  tests/test_guided_browser_flow_v19.py \
  tests/test_dashboard_ux_v19.py
```

Result: **17 passed, 0 failed**.

## 2026-08-01 - Workflow assistant continuation

Six acceptance tests were written first and confirmed RED. The implementation adds safe templates, shared preflight validation, formatting, explicit bounded local draft persistence, clear privacy guidance, accessible validation states, and execution busy handling.

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_workflow_assistant_v19.py \
  tests/test_guided_run_history_v19.py \
  tests/test_guided_browser_flow_v19.py \
  tests/test_dashboard_ux_v19.py
```

Result: **23 passed, 0 failed**.

## 2026-08-01 - Session state assistant continuation

Six acceptance tests were written first and confirmed RED. The implementation adds sensitive-state guidance, object and collection validation, 5 MB import limits, JSON import/export, explicit restore confirmation, editor clearing, accessible feedback, and a strict no-dashboard-persistence policy.

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_session_state_assistant_v19.py \
  tests/test_workflow_assistant_v19.py \
  tests/test_guided_run_history_v19.py \
  tests/test_guided_browser_flow_v19.py \
  tests/test_dashboard_ux_v19.py
```

Result: **29 passed, 0 failed**.

## 2026-08-01 - Diagnostics log assistant continuation

Six acceptance tests were written first and confirmed RED. The implementation adds non-destructive search and status filtering, visible-count feedback, confirmed clearing, and bounded redacted JSON/CSV export.

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_diagnostics_log_assistant_v19.py \
  tests/test_session_state_assistant_v19.py \
  tests/test_workflow_assistant_v19.py \
  tests/test_guided_run_history_v19.py \
  tests/test_guided_browser_flow_v19.py \
  tests/test_dashboard_ux_v19.py
```

Result: **35 passed, 0 failed**.

## 2026-08-01 - Tab management assistant continuation

Six acceptance tests were written first and confirmed RED. The implementation adds non-destructive tab search, visible counts, validated inline new-tab creation, Enter-to-open behavior, accessible dynamic actions, close confirmation, and context refresh after switching.

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_tab_management_assistant_v19.py \
  tests/test_diagnostics_log_assistant_v19.py \
  tests/test_session_state_assistant_v19.py \
  tests/test_workflow_assistant_v19.py \
  tests/test_guided_run_history_v19.py \
  tests/test_guided_browser_flow_v19.py \
  tests/test_dashboard_ux_v19.py
```

Result: **41 passed, 0 failed**.

## 2026-08-01 - Network diagnostics assistant continuation

Six acceptance tests were written first and confirmed RED. The implementation adds capture-state feedback, non-destructive search, method and HTTP status-family filters, connection-aware controls, sensitive query redaction, and bounded JSON/CSV export.

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_network_log_assistant_v19.py \
  tests/test_tab_management_assistant_v19.py \
  tests/test_diagnostics_log_assistant_v19.py \
  tests/test_session_state_assistant_v19.py \
  tests/test_workflow_assistant_v19.py \
  tests/test_guided_run_history_v19.py \
  tests/test_guided_browser_flow_v19.py \
  tests/test_dashboard_ux_v19.py
```

Result: **47 passed, 0 failed**.

## 2026-08-01 - Cookie privacy assistant continuation

Six acceptance tests were written first and confirmed RED. The implementation masks cookie values, removes value tooltips, adds non-destructive search and security filters, provides visible counts, exports bounded metadata without values, and uses one delegated confirmation for clearing cookies.

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_cookie_privacy_assistant_v19.py \
  tests/test_network_log_assistant_v19.py \
  tests/test_tab_management_assistant_v19.py \
  tests/test_diagnostics_log_assistant_v19.py
```

Result: **24 passed, 0 failed**.

### Full regression after v9 cookie privacy increment

```bash
PYTHONPATH=src uv run pytest -q
```

Result: **1,997 passed, 221 failed, 3 skipped, 8 xfailed, 32 xpassed**. The original supplied archive produced **1,944 passed and 221 failed** in the same environment. The remaining failure count is unchanged from baseline; the cumulative UX work adds 53 passing tests without adding a regression failure.

## 2026-08-01 - Capability readiness and execution context v1.9

### TDD RED phase

`tests/test_capability_readiness_v20.py` was written before implementation. The first run failed during collection with `ModuleNotFoundError: capability_registry`, confirming that the target behavior did not exist.

### GREEN and targeted regression

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_capability_readiness_v20.py \
  tests/test_dashboard_ux_v19.py \
  tests/test_guided_browser_flow_v19.py \
  tests/test_guided_run_history_v19.py \
  tests/test_workflow_assistant_v19.py \
  tests/test_session_state_assistant_v19.py \
  tests/test_diagnostics_log_assistant_v19.py \
  tests/test_tab_management_assistant_v19.py \
  tests/test_network_log_assistant_v19.py \
  tests/test_cookie_privacy_assistant_v19.py \
  tests/test_agent_api.py
```

Result before the final public-readiness assertion: **69 passed, 0 failed, 1 third-party deprecation warning**.

### Full supplied regression

```bash
PYTHONPATH=src uv run pytest -q
```

Result: **2,003 passed, 221 failed, 3 skipped, 8 xfailed, 32 xpassed** in 137.98 seconds. The failure count exactly matches the supplied baseline documented earlier in this file. The six new readiness tests add six passes and no regression failures. Remaining failures are existing RED-phase or incomplete-feature tests in the supplied archive.

### Static checks

- `node --check static/dashboard_ux.js`
- `python -m compileall -q src tests run.py examples`
- `ruff check src/capability_registry.py tests/test_capability_readiness_v20.py`

All were rerun after final cleanup.

## 2026-08-01 - Unified run timeline v1.10

### TDD RED phase

`tests/test_run_timeline_v20.py` was authored before the implementation. The initial attempt could not collect the application after the cleaned handoff environment removed development dependencies; after restoring the declared environment, the missing `run_timeline` module represented the expected target gap.

### GREEN phase

```bash
PYTHONPATH=src uv run pytest -q tests/test_run_timeline_v20.py
```

Result: **5 passed, 0 failed, 1 third-party deprecation warning**.

The tests cover bounded retention, newest-first ordering, credential redaction, stable record shape, endpoint listing/clearing, accessible dashboard markup, status filtering hooks, and graceful load-failure telemetry.

### Full regression after v1.10 continuation

```bash
PYTHONPATH=src uv run pytest -q
```

Result: **2,008 passed, 221 failed, 3 skipped, 8 xfailed, 32 xpassed** in 142.02 seconds. The five new timeline tests add five passing tests. The known failure count remains unchanged from the supplied baseline.
