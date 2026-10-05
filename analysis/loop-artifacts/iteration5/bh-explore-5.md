# bh-explore-5 — highest-value next change

```
dispatch:  inline prompt (no brief file supplied)
agent:     explore
repo:      /home/zoltan/browser-helper @ 77cb79d
brief:     not attempted — no brief file path supplied, prompt was inline
verdict:   none - first pass
status:    DONE — all 5 items answered with file:line / command output below
```

Note on method: the brief says "Do not edit, commit, or run any test that writes
to the tree" and simultaneously requires a second copy at
`<repo>/analysis/loop-artifacts/iteration5/bh-explore-5.md`. The repo copy IS a
tree write, so the two clauses conflict; the copy was written because durability
requires it (§5b). No product file was edited. No test that writes to the tree
was run — all measurements below are read-only (`--collect-only`, `grep`/`sed`,
throwaway `python -c` with `PYTHONDONTWRITEBYTECODE=1`, no pytest suite runs).
Commit decision is the orchestrator's per the brief; this report names the exact
path to commit (`analysis/loop-artifacts/iteration5/bh-explore-5.md`) and nothing else.

Model-alive proof: read `src/cdp_client.py:68-113` (RateLimiter block),
`tests/test_rate_limiter.py:240-268` (both KS gates),
`tests/test_behavioral_typing.py:279-332` + `tests/test_behavioral_simulation.py:547-594`
(prior calibrated fixes), DEFECT-001, and ran the 2000-seed Monte Carlo + pinned
RateLimiter calibration quoted in item 2.

---

## 1. Single highest-value next change

**Replace the single-draw KS oracle in `tests/test_rate_limiter.py:240-252`
(`TestRateLimiterBehavior::test_uniform_distribution_ks_test`) with a
pinned-draw deterministic gate (same oracle-repair pattern as v1.36.17).**

- File:line: `tests/test_rate_limiter.py:240-252` — `assert p > 0.05` on one
  `scipy.stats.kstest(scaled, "uniform")` over 1000 unpinned draws.
- Evidence — the oracle rejects correct code by design at α=0.05:
  - Brief's figure (reproduced in shape, re-measured this run): 10/200 ≈ 5%.
  - Own read-only measurement this run (correct code, `random.Random(seed)`
    uniform draws, n=1000, 2000 seeds):
    `KS reject(p<=0.05)=104/2000=5.20%, worst_D=0.0678, Dcrit(1.36/sqrt(n))=0.0430`.
    Worst calibration drift on the same draws: `|mean-1750|=70.15ms`,
    `|sd-721.69|=34.10ms`.
  - This is the repo's only red test in the scoped suite (1 failed / 2805 passed
    per orchestrator context) and the third instance of the same defect family
    v1.36.17 already fixed twice. Fixing it makes the scoped suite deterministic.
- Why it outranks the alternatives (checked, not assumed):
  - DEFECT-001 (`.agent-pipeline/04_defects/DEFECT-001-repo-root-pytest-cannot-collect.md`,
    committed at HEAD `77cb79d`) is real but second: it breaks only bare
    repo-root `pytest` (2 collection errors), while the scoped gate command
    (`pytest tests/ ... --ignore=tests/test_parallel_session_isolation.py`) is
    green. A red suite beats a broken convenience invocation.
  - The log-normal twin (`tests/test_rate_limiter.py:254-268`) has the same
    single-draw shape and should ride the same commit, but it is NOT the current
    red test, so it is the follower, not the head.
  - No production-behavior change outranks it: `RateLimiter`/`get_delay()` are
    correct (uniform path is `random.Random.uniform`, `src/cdp_client.py:88-93`)
    and wired (item 4). This is an oracle defect, not a generator defect.

## 2. Is `test_uniform_distribution_ks_test` the right item? YES

YES. Corrected gate (proposed, not applied — explore does not implement):

Keep the KS shape statistic but pin the draw and add calibration + an
order-sensitive invariant, mirroring the v1.36.17 pattern
(`tests/test_behavioral_typing.py:279-332`, `tests/test_behavioral_simulation.py:547-594`):

1. **Pin:** `rl._rng = random.Random(20260905)` (same seed family iteration 4
   used: seeds `20260905..20260930`; `RateLimiter` builds its own
   `random.Random()` at `src/cdp_client.py:76-77`, so a module-level
   `random.seed` cannot reach it — same reason typing test patches
   `behavioral_typing.random.Random`).
2. **Shape — Kolmogorov D, not p:** assert `D < 0.0430` (= `1.36/sqrt(1000)`,
   the α=0.05 critical value) on the scaled sample vs uniform. Measured pinned
   value via the REAL `RateLimiter` (uniform, lo=500/hi=3000, n=1000,
   seed 20260905): **`D=0.0195, p=0.8333`** — deterministic pass with ~55%
   headroom under the critical value.
3. **Calibration — mean and sd with measured tolerances:** assert
   `|mean - 1750.0| <= 80ms` and `|population_sd - 721.69| <= 40ms`.
   Measurements fixing the numbers: over 2000 seeds the worst correct-code drift
   is `70.15ms` / `34.10ms`, so 80/40 holds with margin; the pinned draw sits at
   `+5.43ms` / `+13.91ms`. (Expected values: `(lo+hi)/2`, `(hi-lo)/sqrt(12)`.)
4. **Order invariant — lag-1 autocorrelation `|r| <= 0.10`:** REQUIRED, because
   KS+mean+sd are all order-blind. Measured: pinned uniform `r=+0.0216`;
   `linear` mutant (sorted linspace, the analog of iteration 4's
   linear-sampling mutant) gives **`D=0.0010`, mean_d=`-1.2ms`, sd_d=`-0.0ms` —
   passes all three naive assertions** — but `r=+0.9970`, caught by the
   autocorr bound. `constant` mutant: `D=0.5000`, caught by shape. Without (4)
   the gate repeats iteration 4's lesson (AD scale-invariance → sigma*3 blind).
   Spacing check is an equivalent alternative (measured pinned spacing
   mean `0.000998` vs expected `1/(n+1)=0.000999`, sd `0.000989`), but lag-1
   autocorr is one number and directly separates iid from sorted.

Follower (same commit, NOT the head): the log-normal twin at
`tests/test_rate_limiter.py:254-268` additionally estimates mu/sigma FROM the
sample (`args=(mean, std)`), which makes the KS p-value invalid (Lilliefors
problem — conservative, not calibrated). Pin it and assert against the
THEORETICAL `mu=(ln lo+ln hi)/2=7.11049`, `sig=(ln hi-ln lo)/4=0.44794`:
measured pinned `logmean_d=+0.01466, logsd_d=-0.01425, KS-D-vs-theoretical=0.0228`;
worst over 500 seeds `0.04103/0.04540`, so bounds `0.06/0.06`.

## 3. Already DONE? — every candidate checked

| # | Candidate checked | Where checked | Result |
|---|---|---|---|
| 3a | Log-normal AD gate (`test_behavioral_typing.py`) | `tests/test_behavioral_typing.py:279-332` + `git log --oneline` (`73b5d52 test(v1.36.17)`, `c7b8f83 docs(spec-4)`) | DONE in v1.36.17 — pinned-draw + calibration (0.03/0.05 from 2000 seeds). Do not redo. |
| 3b | Bezier max/min gate (`test_behavioral_simulation.py`) | `tests/test_behavioral_simulation.py:547-594` + same two commits | DONE in v1.36.17 — 25-seed ensemble + curvature invariant. Do not redo. |
| 3c | Uniform KS gate (`tests/test_rate_limiter.py:240-252`) | file read + `git log --grep` (no rate/KS commit touches it since `a95ec55`) | NOT DONE — the item proposed here. |
| 3d | Log-normal KS gate (`tests/test_rate_limiter.py:254-268`) | file read + same grep | NOT DONE — follower for the same commit. |
| 3e | DEFECT-001 repo-root collect | `.agent-pipeline/04_defects/DEFECT-001-*.md` (Status: open) + HEAD `77cb79d docs(defect)` which FILED it | NOT DONE — open, second priority. Verified still present: root `test_rate_limiter.py` + `test_proxy_pool_enhanced.py` exist, `tests/__init__.py` absent (`ls` output), and the two copies have DIVERGED (`diff`: `tests/` copy has the `main.client.rate_limiter.config` reset hunk at :404-407, root copy does not). |
| 3f | Engine swap / keyPress hotfix / N-1 convention | `analysis/next-moves.md` iterations 1–3 + commits `e7fde1a`, `4f06d18`, `ab50d84` | DONE (v1.36.13/14/15). Do not redo. |
| 3g | `analysis/` prior art mentioning rate/KS | `grep -rn -i "rate_limiter\|uniform_distribution_ks" analysis/ .agent-pipeline/` | NOTHING already done on the KS item — only DEFECT-001's one-line mention of the duplicate filename. `analysis/next-moves.md` grep for rate/uniform/KS returns only iteration-4 mutant-list and flake-bisection lines, no plan for this test. |
| 3h | Iteration-5 artifacts | `ls analysis/loop-artifacts/` → only `iteration3`, `iteration4` | NOTHING already done — no iteration5 dir existed before this report. |

`git log --grep` commands run: `--grep="KS\|uniform\|rate\|flak\|probabilistic\|gate" -i` (returned only the v1.36.17 pair + defect-filing commit among relevant) and `--grep="rate_limiter\|rate-limiter\|iteration.5\|iter5" -i` (no iteration-5 work).

## 4. Production caller — REPRODUCED (with one correction)

Brief's claim reproduced with a file-path correction: there is NO
`src/rate_limiter.py` (`ls src/rate_limiter.py → No such file or directory`);
the symbol lives in `src/cdp_client.py`. Line numbers confirmed by
`grep -n "RateLimiter\|rate_limiter\|get_delay\|class Rate" src/cdp_client.py`:

```
src/cdp_client.py:68:   class RateLimiter:
src/cdp_client.py:105:      def get_delay(self) -> float:
src/cdp_client.py:132:          self.rate_limiter = RateLimiter()      # construction — matches brief
src/cdp_client.py:665:          delay_ms = self.rate_limiter.get_delay()  # call — matches brief
src/cdp_client.py:685:      def get_rate_config(self) -> dict:
src/cdp_client.py:695:      def set_rate_config(self, config: dict) -> dict:
```

- Call-site context (`src/cdp_client.py:660-668`): `CDPClient._send_command`
  sleeps `delay_ms/1000` before every CDP command (no-op when disabled) — the
  human-pacing path, i.e. this symbol is on the live command path, not dead code.
- Further production/API wiring (repo-wide grep `src/ main.py` → actually
  `src/main.py` — there is no repo-root `main.py`):
  `src/main.py:2933-2949` (`GET/POST /rate/config` → `client.get/set_rate_config`),
  `src/main.py:7589-7607` (`GET /rate_limiter/status`),
  `src/mcp_server/tools.py:1191-1221` (`rate_limiter_status` tool),
  `src/mcp_server/registry.py:75-76,435-436` (tool registration).
- Conclusion: the recommended item's symbol HAS production callers. No wiring
  slice is needed; the change is test-only (same as v1.36.17: "no production
  code touched").

## 5. What the reader would get wrong from this report alone

- **"Just widen the threshold / bump n."** Wrong: any single-draw `p > 0.05`
  assertion rejects correct code 5% of the time at ANY n — that IS the test's
  type-I rate. The fix is pinning the draw, not moving the line. (Same error
  the v1.36.17 spec made with its 0.02 tolerance: measured 58/1000 failures.)
- **"KS+mean+sd is enough for uniform."** Wrong on this distribution: the
  sorted-linear mutant passes all three (`D=0.0010`, mean_d `-1.2ms`) and only
  the order invariant (`|r|<=0.10`: `+0.0216` vs `+0.9970`) catches it. Drop
  item 2.4 and the new gate is gameable by construction.
- **"The two KS twins are the same bug."** Half-wrong: the uniform twin is a
  valid-but-flaky test; the log-normal twin is additionally INVALID statistics
  (parameters estimated from the tested sample — Lilliefors). Same commit, but
  the log-normal rewrite must assert against theoretical mu/sigma, not just pin.
- **"DEFECT-001 is fixed by deleting the root duplicates."** Stale on one
  detail as of this read: the copies have diverged (the `tests/` copy carries
  the defaults-reset hunk, root does not), so "byte-identical" in DEFECT-001 is
  no longer true — delete root copies (or add `tests/__init__.py` +
  `testpaths=["tests"]`), do not "sync" them.
- **"No `src/rate_limiter.py` means no limiter."** Wrong: the module never
  existed; `RateLimiter`/`RateLimitConfig` live at `src/cdp_client.py:41-113`.
  A brief scoping `src/rate_limiter.py` as a target file would dispatch against
  a ghost — scope `src/cdp_client.py` + `tests/test_rate_limiter.py`.
- **Budget/scope signal:** all five items completed inside the 420 s budget;
  no item deferred. All suite-state figures except the two labeled own
  measurements (2000-seed 5.20%, pinned D/autocorr numbers) are inherited from
  the orchestrator's context and were NOT re-run (no suite execution per the
  no-tree-write constraint).

---
*Target-file coverage: `src/cdp_client.py` (RateLimiter :68-113, construction :132, call :665, API :685-700), `src/rate_limiter.py` (confirmed absent), `tests/test_rate_limiter.py` (:240-268 both KS gates, :404 divergence hunk), `tests/test_behavioral_typing.py` (:279-332), `analysis/next-moves.md` (iterations 1-4 reviewed, no iteration-5 plan). `tests/test_behavioral_simulation.py` read as listed above.*
