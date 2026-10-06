# explore — DEFECT-001: highest-value next item? What is the correct fix?

```
dispatch:  (no brief file — inline brief in dispatch prompt)
agent:     explore
repo:      /home/zoltan/browser-helper @ 3cb1bf2
brief:     n/a — inline brief, no brief file supplied (sha not attempted: no path given)
verdict:   none - first pass (no verdict handed in brief; open verdict
           v20261005134000-741226 observed in analysis/next-moves.md:24, left
           open per its own instruction — not mine to close)
status:    DONE — all five items answered with measured evidence below.
           Report files written but NOT committed (brief says "do not commit";
           role footer says orchestrator commits after the reviewer gate).
```

Alive-proof: I reproduced the collection failure, read both diffs hunk-by-hunk,
and traced the guard fix to its commit (`38e9def`) — details in items 1–3.

## 1. Is DEFECT-001 the highest-value next item, or does something outrank it?

**YES — DEFECT-001 part (a) (duplicate basenames) is the highest-value next item.
Nothing outranks it. But part (b) (Chrome guard) is already fixed, so the defect
file overstates the remaining work by half.**

What I checked:

- `.agent-pipeline/04_defects/` contains exactly ONE file: `DEFECT-001-...md`.
  No competing defect is filed anywhere (`grep -rn -i 'OPEN\|TODO' .agent-pipeline/`
  returns only DEFECT-001's own Status line). So there is no other named rival.
- Reproduced the failure read-only (this run, HEAD `3cb1bf2`):
  `timeout 120 .venv/bin/python -m pytest --collect-only -q -p no:randomly -o addopts=''` →
  `2849 tests collected, 2 errors`, `Interrupted: 2 errors during collection`,
  `ERROR tests/test_proxy_pool_enhanced.py`, `ERROR tests/test_rate_limiter.py`.
  A bare-root run is still broken at collection. Confirmed YES.
- Part (b) is already closed by someone else: `tests/test_parallel_session_isolation.py:112-123`
  now asserts `st.get("browser_available")` ("service has no Chrome available") inside the
  try, so service-up-but-no-Chrome raises AssertionError → caught by `except` → `pytest.skip`.
  Commit `38e9def test: use browser_available not connected for parallel isolation gate`
  (`git log -S 'browser_available'` proves it). The DEFECT-001 text quotes the OLD
  service-only guard — that paragraph is STALE. Do not re-fix the guard.
- Other candidates from `analysis/next-moves.md` are lower value: artifact defects
  (CHANGELOG/docstring mismatches, `:59`) are cosmetic; the open verdict on the mocked
  suite (`:24`) is explicitly deferred by its own instruction ("Ne zarja le, aki ezt
  olvassa"). The previous iteration's "ranked second / ABOVE the line" positions are
  consistent with this: above the line, and now effectively first since (b) is done.
- Answer: ship DEFECT-001(a) next. Cost is two deletions + one config line; risk ~zero
  (items 2–3); payoff is every future bare-root invocation collects.

## 2. The three candidate shapes — correctness, cost, and what each does NOT fix

**(a) Delete the two stale root duplicate files — CORRECT, and the core of the fix.**
`git ls-files | grep -E '^(test_.*\.py|tests/__init__)'` shows both root files tracked,
no `tests/__init__.py`. Nothing imports them (grep for
`from test_rate_limiter|import test_rate_limiter|from test_proxy_pool|import test_proxy_pool`
across `*.py` returns zero hits outside the files themselves). Deletion removes the
`import file mismatch` collision at its root. Cost: two `git rm`s; must first confirm no
unique wanted content is lost — done in item 3 (nothing is). Does NOT fix: recurrence —
nothing stops a future `test_*.py` landing in root again; and the default-run scope stays
implicit (bare `pytest` still means "collect the world").

**(b) Add `testpaths = ["tests"]` to `[tool.pytest.ini_options]` (`pyproject.toml:32-39`,
currently `markers/addopts/asyncio_mode`, no `testpaths`) — CORRECT, and the durable half.**
Makes bare `pytest` collect only `tests/` regardless of stray root files. Cost: one config
line; semantic change is nil in practice (the only root-level test files are the duplicates
(a) deletes). Does NOT fix: the stale-copy trap — with (b) alone, the root files still sit
there, still tracked, still stale, and anyone running an explicit path (`pytest
test_rate_limiter.py tests/`) still collides; also (b) alone leaves the wrong copy editable.

**(c) Add `tests/__init__.py` — NOT RECOMMENDED. Technically works, wrong trade.**
It would disambiguate module names (`tests.test_x` vs `test_x`), but it flips the import
regime of all ~2800 tests (rootdir-inserted vs dirname-inserted `sys.path`), interacting
with the hand-rolled path setup in BOTH `conftest.py:32` and `tests/conftest.py:26`
(`sys.path.insert(0, ...src...)`). Widest blast radius of the three for zero residual
benefit once (a) is done. Worse, (c) ALONE (without (a)) keeps both copies collectible as
distinct modules — the suite would run the stale root copy's OLD probabilistic KS gates
(`assert p > 0.05` on unpinned draws, item 3) a second time, REINTRODUCING the flake the
v1.36.18 loop just pinned. Does NOT fix: staleness, double-collection, or default scope.

**Ship (a)+(b), skip (c).** (a) removes the collision and the stale trap; (b) pins the
default collection root so the "green suite" claim holds without caller flags. Either alone
leaves a hole (recurrence trap / stale trap); together they close both, and (c) adds only risk.

## 3. Is the root `test_rate_limiter.py` safe to delete, given it DIFFERS?

**YES. The root copy is strictly older and strictly worse; it contains nothing wanted
that the maintained copy lacks.**

Measured: `wc -l` → root 431 lines vs `tests/` 512; `diff` → root lacks two hunks the
`tests/` copy has, and every differing hunk goes the same direction (old gate → new gate):

- `:241` hunk: root has the old uniform gate (`scaled.sort()` then
  `_, p = kstest(scaled, "uniform"); assert p > 0.05`) with comment "Temporarily override
  randomness for reproducibility". `tests/` copy has the pinned deterministic gate
  (seed 20260905, KS-D vs critical `1.36/sqrt(1000)`, mean/sd calibration, lag-1 order
  invariant) — the v1.36.18 SPEC-5 work (`docs/specs/SPEC-5-deterministic-rate-limiter-gates.md`,
  `CHANGELOG.md:10,27`, commit `507fd61` touching only the `tests/` copy).
- `:255` hunk: root has the old log-normal gate (`np.log`, mean/std ESTIMATED FROM the
  sample — Lilliefors-invalid — plus unpinned draw). `tests/` copy tests against the
  THEORETICAL `(mu, sigma)` derived at `src/cdp_client.py:100-101` with calibration bounds.
- `:403` hunk (the `:404` defaults-reset from the brief): `tests/` copy has
  `from cdp_client import RateLimitConfig` + `main.client.rate_limiter.config =
  RateLimitConfig()`; root copy lacks it.
- Same 43 `def test_` names in both (`diff` of the `grep 'def test_'` lists: identical).
- `test_proxy_pool_enhanced.py`: `cmp` → BYTE-IDENTICAL (917 lines each), trivially safe.

So "what the root copy contains that the maintained copy does not" = only the two
superseded probabilistic gates and their numpy import. Nothing unique is still wanted.
Maintenance direction is unambiguous (all iteration-5 artifacts and CHANGELOG reference the
`tests/` path). `git rm test_rate_limiter.py test_proxy_pool_enhanced.py` loses nothing.

## 4. After the fix, what EXACTLY must be true (commands + expected output)?

1. Duplicates gone: `git ls-files | grep -E '^test_.*\.py'` → empty output (exit 1 from grep).
2. Config pinned: `grep -n 'testpaths' pyproject.toml` → `testpaths = ["tests"]`
   under `[tool.pytest.ini_options]`.
3. Bare-root collect (the command that fails today):
   `.venv/bin/python -m pytest --collect-only -q -p no:randomly -o addopts=''` →
   exit 0, NO `ERROR` lines, NO `Interrupted: ... errors`, and `2849 collected`
   (today: `2849 tests collected, 2 errors` — after the fix the same collection minus the
   2 errors; exact count may shift by duplicate-removal, key assertions are zero errors
   and exit 0).
4. Scoped gate stays green (verbatim from DEFECT-001):
   `timeout 590 .venv/bin/python -m pytest tests/ -o addopts='' --no-header -q -p no:randomly --ignore=tests/test_parallel_session_isolation.py` →
   `0 failed, 0 errors` (reference: `2805 passed, 1 skipped, 8 xfailed, 32 xpassed`;
   counts quoted from the defect file — I did NOT re-run the 5-minute suite in this
   400 s budget, so re-measure; the load-bearing assertions are `failed=0, error=0`).
5. Full bare `pytest -q` collects with no import-mismatch errors. NOTE: with `testpaths`
   set, bare `pytest` will now INCLUDE `tests/test_parallel_session_isolation.py`
   (live-Chrome, previously `--ignore`d) — it skips when the service is down
   (`pytest.skip`) and needs a browser when up. A bare-run failure THERE is
   environment, not collection; do not confuse the two.

## 5. What would the reader get wrong from this report alone? Signals.

- **DEFECT-001(b) reads open but is fixed.** If you only read the defect file you will
  "fix" the guard that `38e9def` already fixed. Signal: `git log -S 'browser_available'
  --oneline -- tests/test_parallel_session_isolation.py` → `38e9def`. The defect file
  needs a correction line, not a second guard patch.
- **Suite counts are quoted, not re-measured by me.** `2805 passed` / `2849 collected`
  come from the orchestrator's measurement and my `--collect-only` run respectively;
  I did not run the full suite (budget). Signal: re-run item-4 commands post-fix.
- **Brief SHA / verdict bookkeeping is thin by construction.** No brief file was
  supplied (inline brief → `brief: n/a`, sha not attempted, no path to hash) and no
  verdict was handed to me. The open verdict `v20261005134000-741226` is real but
  out of my scope — signal: `analysis/next-moves.md:19-24`.
- **Diff direction was established by content, not per-hunk blame.** I judged the
  `tests/` copy newer because its gates match SPEC-5/CHANGELOG/commit `507fd61` and the
  root copy's gates are the probabilistically-flaky ones v1.36.18 replaced. If disputed,
  run `git log --follow` on both paths — I did not.
- **This report is written, not committed.** `analysis/loop-artifacts/iteration6/bh-explore-6.md`
  exists in the working tree uncommitted per the brief's "do not commit" and the role
  footer (orchestrator commits after the reviewer gate). Signal: `git status --short`
  should show exactly one untracked path from me and nothing else staged.
