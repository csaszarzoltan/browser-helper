# DEFECT-001 — a repo-root `pytest` cannot collect this suite

**Found by:** orchestrator, while independently re-measuring the v1.36.12→17 review's "2805 passed"
claim. **Not** introduced by that loop — see provenance below.

**Status:** fixed (SPEC-6, v1.36.19) — root duplicates deleted, `testpaths = ["tests"]` pinned.

## Impact

Any verification command that starts pytest at the repository root fails **before** meaning anything:

```
$ cd /home/zoltan/browser-helper && .venv/bin/python -m pytest -q
FAILED tests/test_parallel_session_isolation.py::test_parallel_sessions_get_separate_tabs
FAILED tests/test_parallel_session_isolation.py::test_parallel_search_overwrites_no_one
ERROR  tests/test_proxy_pool_enhanced.py - import file mismatch:
ERROR  tests/test_rate_limiter.py - import file mismatch:
exit=1
```

Two consequences, both real:

1. **The import errors abort collection**, so a root-level run does not even reach the tests it could
   have run. `2 errors during collection` is reported as the headline, not the state of the suite.
2. **The two live-Chrome tests skip, not fail.** Fixed in `38e9def`: the guard in
   `tests/test_parallel_session_isolation.py:112-123` asserts `st.get("browser_available")`
   inside the `try`, so "service up but no Chrome attached" now `pytest.skip`s instead of failing.

## Root cause

Two independent problems share one symptom.

**a) Duplicate test basenames across two roots.** `tests/__init__.py` does not exist, so pytest imports
`tests/test_proxy_pool_enhanced.py` and `test_proxy_pool_enhanced.py` as the *same* module name:

```
34135 B  test_proxy_pool_enhanced.py            # (deleted by SPEC-6)
34135 B  tests/test_proxy_pool_enhanced.py      # byte-identical to the deleted root copy
18961 B  test_rate_limiter.py                   # (deleted by SPEC-6 — older copy, 431 lines)
23028 B  tests/test_rate_limiter.py             # newer copy, 512 lines; differs since 507fd61
```

Only the `test_proxy_pool_enhanced` pair was byte-identical (`md5 a2dc186a...`); the
`test_rate_limiter` pair differed (`cmp`: byte 10871, line 241) since `507fd61` replaced the
flaky `kstest(p > 0.05)` oracle in the `tests/` copy. Tracked since **2026-08-14** (`29da9ee`).

**b) A module-scoped skip guard that checked the wrong thing — already fixed in `38e9def`.**
It asked "is the HTTP service up?" when the test needed "is a Chrome attached?". The guard now
asserts `browser_available`, so a green service with no browser skips instead of failing.

`.worktrees/` is gitignored and is **not** the cause; `--ignore=.worktrees` does not fix collection.

## Why the loop's claim was still accurate

The gate ran a **scoped** command, verbatim from its brief:

```
$ timeout 590 .venv/bin/python -m pytest tests/ -o addopts='' --no-header -q -p no:randomly \
    --ignore=tests/test_parallel_session_isolation.py
2805 passed, 1 skipped, 8 xfailed, 32 xpassed in 303.67s (0:05:03)
```

`tests/` as the target excludes the root duplicates; the explicit `--ignore` excludes the live-Chrome
module. So `2805 passed` is **true of that command** and **false of the repository**. Neither party was
wrong; the claim was narrower than it read.

## Fix applied (SPEC-6)

1. Deleted the root-level duplicates `test_proxy_pool_enhanced.py` and `test_rate_limiter.py`
   via `git rm`. (`tests/__init__.py` deliberately NOT added — it would leave both copies
   collectable and resurrect the flaky root oracle.)
2. Chrome-reachability guard already in place via `38e9def` — not re-fixed here.
3. Added `testpaths = ["tests"]` to `[tool.pytest.ini_options]` so a bare `pytest` cannot wander
   into the repo root at all. **This is the durable fix**: it makes the "green suite" claim true
   without the caller having to remember a flag.

## Provenance

- The duplicates predate the v1.36.12→17 loop by ~7 weeks (`29da9ee`, 2026-08-14).
- The loop never touched `tests/test_parallel_session_isolation.py` (0 commits in its window).
- The review that scored this loop cited the scoped command, and its own artifacts do not claim the
  root-level run was clean.
