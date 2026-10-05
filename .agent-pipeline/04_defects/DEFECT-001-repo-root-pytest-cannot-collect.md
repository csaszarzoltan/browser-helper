# DEFECT-001 — a repo-root `pytest` cannot collect this suite

**Found by:** orchestrator, while independently re-measuring the v1.36.12→17 review's "2805 passed"
claim. **Not** introduced by that loop — see provenance below.

**Status:** open, repo-side, pre-existing (three months old).

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
2. **The two failing tests need a live Chrome.** They fail with empty tab titles (`''`), which is what
   an absent browser looks like. Their module-level guard skips only when the *service* is unreachable:

   ```python
   # tests/test_parallel_session_isolation.py:112-123
   """Verify the live service is up; skip the module if not."""
   except Exception as exc:
       pytest.skip(f"browser-helper service not reachable: {exc}")
   ```

   The service can be up while no Chrome is attached, and then the module does not skip — it fails.

## Root cause

Two independent problems share one symptom.

**a) Duplicate test basenames across two roots.** `tests/__init__.py` does not exist, so pytest imports
`tests/test_proxy_pool_enhanced.py` and `test_proxy_pool_enhanced.py` as the *same* module name:

```
34135 B  test_proxy_pool_enhanced.py
34135 B  tests/test_proxy_pool_enhanced.py     # byte-identical duplicates
```

Both are tracked. `test_rate_limiter.py` has the same pair. Tracked since **2026-08-14** (`29da9ee`).

**b) A module-scoped skip guard that checks the wrong thing.** It asks "is the HTTP service up?" when
the test needs "is a Chrome attached?". A green service with no browser is the failing configuration.

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

## Suggested fix (not applied — outside this review's scope)

1. Delete the root-level duplicates `test_proxy_pool_enhanced.py` and `test_rate_limiter.py`, **or**
   add `tests/__init__.py` so the two roots cannot collide on module names.
2. Replace the service-only guard with a Chrome-reachability guard, or mark the module
   `@pytest.mark.integration` and exclude it from the default run.
3. Add `testpaths = ["tests"]` to `[tool.pytest.ini_options]` so a bare `pytest` cannot wander into the
   repo root at all. **This is the durable fix**: it makes the "green suite" claim true without the
   caller having to remember a flag.

## Provenance

- The duplicates predate the v1.36.12→17 loop by ~7 weeks (`29da9ee`, 2026-08-14).
- The loop never touched `tests/test_parallel_session_isolation.py` (0 commits in its window).
- The review that scored this loop cited the scoped command, and its own artifacts do not claim the
  root-level run was clean.
