# bh-dev-5 — SPEC-5 deterministic rate-limiter gates

```
dispatch:  inline brief in session (no brief file supplied)
agent:     developer
repo:      /home/zoltan/browser-helper @ 092b00f
brief:     sha256:not attempted — brief arrived inline, nothing to hash
verdict:   none - first pass
status:    DONE — SPEC-5 Items 1-4 applied; all 5 acceptance items answered with measured output
```

Model-alive proof: replaced both KS-oracle bodies in `tests/test_rate_limiter.py`
with the SPEC-5 pinned-draw gates (seed 20260905, three-part oracle for uniform,
two-part for log-normal); measured mutant table below matches SPEC-5's table to
4 decimals (M1 lag-1=+0.9970, M2 mean=1365.42, M3 mean=877.71, M4 KS-D=0.5000).

Scope: ONLY `tests/test_rate_limiter.py` lines 240–268 (both test bodies).
No `src/` change, no other test file, no DEFECT-001 work. The false comment at
old :245 ("Temporarily override randomness for reproducibility") was deleted as
part of replacement 1, as SPEC-5 requires. Tolerances used: SPEC-5's (±150 ms
mean, ±80 ms sd, lag-1 < 0.2, ±0.07/±0.06 log-normal) — NOT tightened to the
retracted 70.15 number.

## Acceptance

### 1. Whole file green

```
$ .venv/bin/python -m pytest tests/test_rate_limiter.py -p no:warnings 2>&1 | tail -n 8
bringing up nodes...
bringing up nodes...

...........................................                              [100%]
43 passed in 6.70s
```
YES — 43 passed, 0 failed, exit 0. (Note: repo pytest runs under xdist, so the
summary line needs `-p no:warnings`/enough tail lines; bare `tail -n 1` shows a
warnings-summary line. The `43 passed` line above is the real result.)

### 2. Same command 5× → identical N passed

```
$ for i in 1 2 3 4 5; do .venv/bin/python -m pytest tests/test_rate_limiter.py -p no:warnings 2>&1 | grep -E 'passed|failed|error'; done
43 passed in 4.66s
43 passed in 4.66s
43 passed in 5.31s
43 passed in 4.94s
43 passed in 4.70s
```
YES — identical `43 passed` all 5 times, no flake.

### 3. Pin byte-identity proof (SPEC-5 item 3A)

```
$ .venv/bin/python -c "...two RateLimiters, seed 20260905, n=1000 each..."
pin byte-identical: True
```
YES.

### 4. Mutation check (SPEC-5 item 3B) — each applied IN PLACE in src/cdp_client.py

Each mutant replaced `_uniform_delay` in the repo file, the new gate was run,
then the file was restored. Script output (rc = pytest exit code):

```
--- M1 (sorted linspace): rc=1
    FAILED tests/test_rate_limiter.py::TestRateLimiterBehavior::test_uniform_distribution_ks_test
--- M2 (uniform delegates to log-normal): rc=1
    FAILED tests/test_rate_limiter.py::TestRateLimiterBehavior::test_uniform_distribution_ks_test
--- M3 (halve the draw): rc=1
    FAILED tests/test_rate_limiter.py::TestRateLimiterBehavior::test_uniform_distribution_ks_test
--- M4 (constant 1750): rc=1
    FAILED tests/test_rate_limiter.py::TestRateLimiterBehavior::test_uniform_distribution_ks_test
restored; diff of src: (clean)
```

Before: 43 passed on correct code (item 1). After each mutant: the uniform gate
FAILED (1 failed). Measured numbers on the pinned draw (seed 20260905, n=1000):

| mutant | mean (Δ) | pop-sd (Δ) | KS-D | lag-1 | caught by |
|---|---|---|---|---|---|
| correct | 1755.43 (+5.43) | 735.60 (+13.91) | 0.0195 | +0.0216 | — (passes, 2.3–10× margins) |
| M1 sorted linspace | 1750.00 (+0.00) | 722.41 (+0.72) | 0.0010 | **+0.9970** | invariant 3 (≥ 0.2) |
| M2 log-normal branch | 1365.42 (−384.58) | 608.32 (−113.37) | 0.2899 | +0.0542 | invariant 2 + shape |
| M3 draw×0.5 | 877.71 (−872.29) | 367.80 (−353.89) | 0.6001 | +0.0216 | invariant 2 + shape |
| M4 constant 1750 | 1750.00 | 0.00 | 0.5000 | nan | shape + sd invariant |

Matches SPEC-5's table (M1 D=0.0010/lag-1=0.9970; M2 1365.42/608.32/0.2899;
M3 877.71/367.80/0.6001; M4 0.5000). After restore:
`git diff --stat -- src/cdp_client.py` → empty (byte-exact restore; the script
rewrote the file from the pre-mutation string each time), and
`git status --short` showed only `M tests/test_rate_limiter.py`.

### 5. Diff touches ONLY tests/test_rate_limiter.py

```
$ git diff --stat
 tests/test_rate_limiter.py | 111 ++++++++++++++++++++++++++++++++++++++-------
 1 file changed, 94 insertions(+), 17 deletions(-)
```
YES — one file, no `src/`, no other test file.

## Stop command (SPEC-5 item 4)

```
$ cd /home/zoltan/browser-helper && .venv/bin/python -m pytest tests/test_rate_limiter.py -q 2>&1 | tail -n 1 && git diff --stat -- tests/test_rate_limiter.py
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
 tests/test_rate_limiter.py | 111 ++++++++++++++++++++++++++++++++++++++-------
 1 file changed, 94 insertions(+), 17 deletions(-)
```
Note: the literal `tail -n 1` line shows the pytest Docs footer because the
xdist run prints warnings after the summary; the pass line for the same command
is `43 passed in 6.70s` (item 1, shown with more tail lines). Exit 0,
zero failed, diff confined to `tests/test_rate_limiter.py`.

## Working-tree state / commit

NOT COMMITTED — the brief forbids committing ("DO NOT: commit, push").
`git status --short` at end of work:
```
 M tests/test_rate_limiter.py
?? analysis/loop-artifacts/iteration5/bh-dev-5.md
```
The `??` file is the durable copy of this report (written, uncommitted per the
brief; the orchestrator commits). Full suite not run (brief forbids it, >5 min).
No other dirty paths; nothing staged.
