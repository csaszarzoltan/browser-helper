# SPEC-8 — Live typing integration gate (iteration 8)

## Item
Add one `@pytest.mark.integration` test file that drives the real Chrome typing path
(`POST /type` → `behavioral_engine.py:212` `BehavioralTyping.type_text` → CDP)
and asserts the typed text lands via `input.value`. Skipped by default, runnable
with the live service. Closes open verdict v20261005134000-741226 (verification 2/5).

This is the class that shipped BROKEN in v1.36.14 (keyPress invalid, text=null,
HTTP 400 1/11 chars, 2805 green mocks). Current guards at
`tests/test_behavioral_typing.py:93-99` (AsyncMock) and `:577-619` (mock-can't-see)
cannot prove Chrome accepts the payload.

## Target Files allowlist
- `tests/test_typing_live_integration.py` (new file only)
- `pyproject.toml` MAY gain an `integration` marker description if missing (already present at :35, so no edit expected)
No `src/` change — production path `behavioral_typing.py:328,352-370` + `behavioral_engine.py:212` + `src/main.py:3216/6430` is correct.

## File + marker + skip condition
- File: `tests/test_typing_live_integration.py`
- Marker: `pytestmark = pytest.mark.integration` (iter3-collector pattern, precedent `tests/test_cookie_export.py:20`)
- Skip: if Chrome/CDP not reachable or service not running — `pytest.skip("live Chrome required")`
- Normal suite: `pytest tests/ -o addopts='' -q` → skipped (no count change)
- With `--run-integration` or `--chrome`: collected and green when live

## Strings + readback
- Must type: `"a b"` (space — the `text=null` killer), plus one uppercase and one special char string (e.g. `"Mix 123!"` or re-use iteration-3 precedent vectors)
- Readback: navigate to a page with `<input>` (or inject one), call the typing endpoint, then `Runtime.evaluate` / `DOM.getProperty` for `input.value` and assert `== sent`.

## How spec prevents passing on mocks
- The test MUST NOT use `AsyncMock`; it must call the live HTTP endpoint or a real `CDPCient`/websocket. The module comment must state this explicitly (greppable guard `AsyncMock` count = 0).
- On the v1.36.14 broken tree (keyPress in dispatch, text=null) the test FAILS; on the current tree it passes — this is the mutant.

## Acceptance (runnable)
```bash
.venv/bin/python -m pytest tests/test_typing_live_integration.py --collect-only -q -p no:randomly -o addopts=''   # must list tests
.venv/bin/python -m pytest tests/ -o addopts='' -q -p no:randomly --ignore=tests/test_typing_live_integration.py  # must be unchanged (no new failures/skips except the known 8 xfailed)
```

## Not in scope
- No product-code change (src/ correct; the gate proves it)
- No version bump (this is a test-only addition; release after gate if desired)
- Performance gate: not this iteration

## Checks before accepting
- Both ASK agents (explore 11194B, reviewer 14431B) independently propose this item (agreement HIGH)
- Spurious WARN/pyproject:44/:245 verified as 0 hits — not real (explore §2, reviewer §2)
- Production callers exist (behavioral_engine.py:212, main.py:3216/6430) — no wiring slice
