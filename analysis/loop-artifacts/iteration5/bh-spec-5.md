# SPEC-5 — Replace two single-draw KS oracles with pinned-draw deterministic gates

```
dispatch:  inline brief in session (no brief file supplied)
agent:     spec-author
repo:      /home/zoltan/browser-helper @ 0f4c4a8
brief:     sha256:not attempted — no brief file was supplied; brief arrived inline, nothing to hash
verdict:   none - first pass
status:    DONE — items 1-6 answered; every number traced to a command in Evidence
```

Scope: test-only change. No production code changes. No alpha raised, no
threshold raised. Every constant below is either pinned from a measurement in
this document or derived from the implementation's own calibration formula.
Shape follows v1.36.17 (`73b5d52`), the same defect class already fixed in
`tests/test_behavioral_typing.py:279-332` and
`tests/test_behavioral_simulation.py:547-594` (both read in full before writing
this spec; pinning idiom and three-part oracle structure mirror SPEC-4).

---

## Item 1 — Target Files allowlist

1. `tests/test_rate_limiter.py`, lines 240–252
   (`test_uniform_distribution_ks_test`) — REPLACE body.
2. `tests/test_rate_limiter.py`, lines 254–268
   (`test_log_normal_distribution_ks_test`) — REPLACE body.

Checked and explicitly excluded:

- There is NO `src/rate_limiter.py`. The symbol lives in `src/cdp_client.py`
  (`RateLimiter`, line 68; per-instance RNG `self._rng = random.Random()`,
  line 78 — read, confirmed).
- NO `src/` file changes. Production code and the RNG are CORRECT; both
  defects are in the oracles, same as v1.36.17. If the `developer` believes any
  `src/` file must change, that belief is wrong — report back, do not edit.
- The misleading comment on line 245 (`# Temporarily override randomness for
  reproducibility`) is deleted as part of replacement 1. It describes a pinning
  that does not exist (no seed is set anywhere in the file — checked with
  `grep -n seed tests/test_rate_limiter.py`, zero hits).

## Item 2 — Exact replacement code

Pin mechanism (both tests): `rl._rng = random.Random(20260905)` on the
instance. A module-level `random.seed()` cannot reach the draw because
`RateLimiter._rng` is a per-instance `random.Random()`
(`src/cdp_client.py:78`, read). This is the instance-assignment analogue of
the SPEC-4 module-patch (`bt_mod.random.Random = ...`), required by the same
reason: the draw site owns its RNG.

### Test 1 — `test_uniform_distribution_ks_test`

```python
    def test_uniform_distribution_ks_test(self):
        """Uniform delays match the calibrated [500, 3000] draw, deterministically.

        The old gate ran ``kstest`` on ONE unpinned 1000-draw and asserted
        p > 0.05: a hypothesis test that rejects 5% of CORRECT draws by
        construction (10/200 = 5.0% red on correct code, per brief), and the
        comment claiming reproducibility pinned nothing. This pins the
        instance RNG and asserts three deterministic invariants on the pinned
        draw (seed 20260905, n=1000):
          1. shape: KS-D against Uniform[500,3000] under the α=0.05 critical value
          2. calibration: mean/sd of the draw match the interval's moments
          3. order: lag-1 autocorrelation near zero (the draw is iid, not sorted)
        Invariant 3 is mandatory, not decoration: a sorted-linear mutant
        scores KS-D=0.0010 with exact mean/sd and passes 1+2 — only the order
        invariant catches it (lag-1 r=+0.9970).
        """
        import math
        import random
        import statistics

        from cdp_client import RateLimitConfig, RateLimiter
        from scipy.stats import kstest

        cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=3000, distribution="uniform")
        rl = RateLimiter(config=cfg)
        rl._rng = random.Random(20260905)
        delays = [rl.get_delay() for _ in range(1000)]
        assert all(500.0 <= d <= 3000.0 for d in delays), "pinned draw left [500, 3000]"

        # --- 1. Shape ------------------------------------------------------
        scaled = sorted((d - 500.0) / 2500.0 for d in delays)
        stat, _ = kstest(scaled, "uniform")
        critical = 1.36 / math.sqrt(1000)  # ~= 0.0430, KS α=0.05 asymptote
        assert stat <= critical, (
            f"KS-D {stat:.4f} exceeds critical {critical:.4f} on the pinned draw — "
            "not uniform over [500, 3000]"
        )

        # --- 2. Calibration: moments of Uniform[500, 3000] ------------------
        # mean = (500+3000)/2 = 1750.0; pop-sd = 2500/sqrt(12) ~= 721.69.
        mean = statistics.fmean(delays)
        pop_sd = statistics.pstdev(delays)
        assert abs(mean - 1750.0) <= 150.0, (
            f"pinned mean {mean:.2f} departs from 1750.0 by more than 150 ms — "
            "draw is not centred on [500, 3000]"
        )
        assert abs(pop_sd - 721.69) <= 80.0, (
            f"pinned pop-sd {pop_sd:.2f} departs from 721.69 by more than 80 ms — "
            "draw has the wrong spread (this is the case KS-D alone cannot see)"
        )

        # --- 3. Order: the draw is iid, not sorted --------------------------
        denom = sum((x - mean) ** 2 for x in delays)
        lag1 = sum((a - mean) * (b - mean) for a, b in zip(delays, delays[1:])) / denom
        assert abs(lag1) < 0.2, (
            f"lag-1 autocorrelation {lag1:+.4f} on the pinned draw — "
            "delays are ordered (e.g. sorted), not independent draws"
        )
```

Measured on the UNMODIFIED implementation, seed 20260905: KS-D=0.0195
(critical 0.0430), p=0.8333, mean=1755.43 (Δ=+5.43), pop-sd=735.60
(Δ=+13.91), lag-1=+0.0216. Every margin is ~2.3–10x its bound.

Tolerance justification (all measured this run, Evidence E3): worst
|mean−1750| over 2000 correct seeds = 91.79 ms, so ±150 clears with ~63%
headroom; worst |pop-sd−721.69| = 34.26 ms, so ±80 clears with ~2.3x margin;
worst |lag-1| over 2000 correct seeds = 0.1132, so 0.2 clears with ~77%
headroom while the sorted-linear mutant scores 0.9970 (5x the bound).

### Test 2 — `test_log_normal_distribution_ks_test`

```python
    def test_log_normal_distribution_ks_test(self):
        """Log-normal delays match the documented (mu, sigma) calibration, deterministically.

        The old gate estimated mean/std FROM the sample it tested (Lilliefors
        problem: the p-value is invalid, not merely flaky) on an unpinned draw
        (1/200 = 0.5% red on correct code, per brief). This pins the instance
        RNG (same mechanism as the uniform twin) and tests against the
        THEORETICAL parameters the implementation derives — a valid KS test —
        plus deterministic calibration bounds.
        """
        import math
        import random
        import statistics

        from cdp_client import RateLimitConfig, RateLimiter
        from scipy.stats import kstest

        cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=3000, distribution="log-normal")
        rl = RateLimiter(config=cfg)
        rl._rng = random.Random(20260905)
        delays = [rl.get_delay() for _ in range(1000)]
        assert all(500.0 <= d <= 3000.0 for d in delays), "pinned draw left [500, 3000]"

        # Theoretical parameters: same derivation as src/cdp_client.py:100-101.
        mu = (math.log(500.0) + math.log(3000.0)) / 2      # 7.11049
        sigma = (math.log(3000.0) - math.log(500.0)) / 4   # 0.44794

        # --- 1. Shape: KS against the theoretical normal in log space -------
        log_delays = [math.log(d) for d in delays]
        stat, _ = kstest(log_delays, "norm", args=(mu, sigma))
        critical = 1.36 / math.sqrt(1000)  # ~= 0.0430
        assert stat <= critical, (
            f"KS-D {stat:.4f} exceeds critical {critical:.4f} on the pinned draw — "
            "log(delays) is not normal with the documented (mu, sigma)"
        )

        # --- 2. Calibration ---------------------------------------------------
        log_mean = statistics.fmean(log_delays)
        log_sd = statistics.pstdev(log_delays)
        assert abs(log_mean - mu) <= 0.07, (
            f"log-mean {log_mean:.5f} deviates from mu {mu:.5f} by more than 0.07 — "
            "delays are drawn with the wrong centre"
        )
        assert abs(log_sd - sigma) <= 0.06, (
            f"log-sd {log_sd:.5f} deviates from sigma {sigma:.5f} by more than 0.06 — "
            "delays are log-normal but with the wrong spread"
        )
```

Measured on the UNMODIFIED implementation, seed 20260905: log-mean Δ=+0.01466,
log-sd Δ=−0.01425, KS-D vs theoretical=0.0228 (p=0.6700). Tolerance
justification (Evidence E3): worst |log-mean−mu| over 2000 correct seeds =
0.05205, so ±0.07 clears with ~35% headroom; worst |log-sd−sigma| = 0.04592,
so ±0.06 clears with ~30% headroom.

## Item 3 — Acceptance criteria as RUNNABLE commands

All commands run from `/home/zoltan/browser-helper` with the project venv
(`.venv/bin/python` — the system python has no scipy/numpy/pytest; checked).

**A. Deterministic run (both tests), repeated to show determinism:**

```bash
cd /home/zoltan/browser-helper
.venv/bin/python -m pytest tests/test_rate_limiter.py -q 2>&1 | tail -n 2
for i in 1 2 3 4 5; do .venv/bin/python -m pytest tests/test_rate_limiter.py -q 2>&1 | grep -E 'passed|failed'; done
```

Expected: `N passed` (whole file green — the two gates were the only red
test), identical across all 5 repeats. Plus the byte-identity proof that the
pin is real (two pinned draws, same seed, must be equal):

```bash
.venv/bin/python -c "
import random, sys; sys.path.insert(0,'src')
from cdp_client import RateLimitConfig, RateLimiter
cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=3000, distribution='uniform')
a = RateLimiter(config=cfg); a._rng = random.Random(20260905)
b = RateLimiter(config=cfg); b._rng = random.Random(20260905)
da = [a.get_delay() for _ in range(1000)]; db = [b.get_delay() for _ in range(1000)]
assert da == db, 'pin is not deterministic'; print('pin byte-identical:', da == db)"
```

Expected: `pin byte-identical: True`.

**B. Mutation check — each mutant MUST make the new gate fail:**

| # | Mutation (apply temporarily, revert after) | New gate must show |
|---|---|---|
| M1 | `_uniform_delay` returns sorted linspace over [500,3000] | invariants 1+2 PASS (D=0.0010, meanΔ=0.00, sdΔ=0.72), invariant 3 FAILS (lag-1=+0.9970 ≥ 0.2) |
| M2 | `_uniform_delay` returns the log-normal draw instead | invariant 2 FAILS (mean≈1365, Δ≈−385; sd≈608, Δ≈−113 — both far outside ±150/±80); shape FAILS too (KS-D≈0.29) |
| M3 | halve the draw (`d*0.5`) | invariant 2 FAILS (mean≈878, Δ≈−872; sd≈368, Δ≈−354); shape FAILS (KS-D≈0.60) |
| M4 | constant `[1750.0]*1000` | shape FAILS (KS-D=0.5000); sd invariant FAILS (sd=0) |

Measured this run (Evidence E2/E4): M1 D=0.0010/p=1.0000/lag-1=+0.9970;
M2 mean=1365.42/sd=608.32/KS-D=0.2899; M3(d*0.5) mean=877.71/sd=367.80/
KS-D=0.6001; M4 KS-D=0.5000. All four are CAUGHT; no mutant passes all three
invariants. (M2/M3 absolute values differ slightly from the brief's — see
item 6. The verdict is identical: caught by invariant 2 with 2–10x margin.)

**C. Log-normal twin rides the same commit: YES.** Same defect class
(single-draw KS oracle on an unpinned draw), same file, adjacent lines
(240–268), same pin mechanism. Splitting it would leave a known-flaky,
known-invalid (Lilliefors) gate in the tree. Precedent: v1.36.17 fixed both
of its gates in one commit.

**NOT required:** the full suite (takes >5 minutes; brief forbids it).
Targeted `pytest tests/test_rate_limiter.py -q` is the gate.

## Item 4 — The stop command

```bash
cd /home/zoltan/browser-helper && .venv/bin/python -m pytest tests/test_rate_limiter.py -q 2>&1 | tail -n 1 && git diff --stat -- tests/test_rate_limiter.py
```

Done means: exit 0, `N passed` (zero failed), and the diff touches ONLY
`tests/test_rate_limiter.py` (no `src/` file, no other test file).

## Item 5 — DEFECT-001 (repo-root pytest collection)

NOT DECIDED here, by instruction. DEFECT-001 (repo-root pytest cannot collect
this suite) is a separate item; the orchestrator decides its ordering. This
spec neither fixes it nor depends on it — all commands above run from the
repo root with `tests/` path arg, which is the collection mode that works
today. `developer` MUST NOT fold a DEFECT-001 fix into this commit.

## Item 6 — Interpretations (brief defects, not hidden)

1. Brief sentence: "`_rng` is a per-instance `random.Random()`
   (`src/cdp_client.py:78`)". Confirmed by reading lines 68–78. Assumption:
   NONE needed — verified, not interpreted.
2. Brief sentence: "Over 2000 seeds on correct code: worst |mean−1750| =
   70.15 ms, worst |pop_sd−721.69| = 34.10 ms, worst KS-D = 0.0678."
   My 2000-seed sweep (E3, seeds 20260905–20262904 consecutive) measured
   91.79 / 34.26 / 0.0685. Assumption: the brief used a different seed window;
   the discrepancy changes nothing because the tolerances (±150/±80) clear
   BOTH sets with margin. Named so the next reader does not re-litigate it.
3. Brief sentence: "uniform-path-returns-log-normal: mean=1349.78,
   pop_sd=571.55" and "half-scale: mean=853.93, pop_sd=363.23". My
   reproductions (E2/E4) measured 1365.42/608.32 and 877.71/367.80
   (d*0.5; the 500+d/2 variant gives 1377.71/367.80). Assumption: "half-scale"
   means a halving of the draw; "uniform-path-returns-log-normal" means the
   uniform branch delegates to the log-normal sampler. Exact mutant mechanics
   were under-specified, so I measured the natural readings — every reading
   is caught by invariant 2 with ≥2x margin, which is the property the spec
   guarantees, not the decimals.
4. Brief budget "500 seconds": interpreted as wall-clock for this dispatch.
   Flake rates (10/200, 1/200) were NOT re-measured (not attempted — a 200-run
   loop exceeds the budget alongside the 2000-seed sweeps); they are taken
   from the brief as given. The sweeps I did run are pasted in Evidence.
5. "the deterministic run of the two tests, repeated enough to show it is
   deterministic": interpreted as 5 consecutive green runs PLUS the
   byte-identity pin proof (criterion A), because repeats alone cannot
   distinguish "deterministic" from "lucky".

---

## Evidence (commands actually run, output pasted)

- E1 — pinned uniform draw (seed 20260905, n=1000):
  `D=0.0195 p=0.8333 mean=1755.43 dmean=+5.43 popsd=735.60 dsd=+13.91 lag1=+0.0216`, critical `0.0430`. Matches brief exactly.
- E1b — pinned log-normal draw: `mu=7.11049 sigma=0.44794`,
  `logmean=7.12515 logsd=0.43369 dmean=+0.01466 dsd=-0.01425 KSD=0.0228 p=0.6700`. Matches brief exactly.
- E2 — mutants M2/M3/M4 (proper sampler-backed reproductions, `.venv/bin/python`):
  M2 `mean=1365.42 popsd=608.32 KS_D=0.2899 p=0.0000`;
  M3(d*0.5) `mean=877.71 popsd=367.80 KS_D=0.6001`;
  M3(500+d/2) `mean=1377.71 popsd=367.80 KS_D=0.4001`;
  M4(constant) `D=0.5000`. Sorted-linear M1: `D=0.0010 p=1.0000 meanD=+0.00 sdD=+0.72 lag1=+0.9970`.
- E3 — 2000-seed sweep (seeds 20260905–20262904, n=1000 each, `.venv/bin/python`):
  uniform `worst|dmean|=91.79 worst|dsd|=34.26 worst_KSD=0.0685 worst|lag1|=0.1132`;
  log-normal `worst|dlogmean|=0.05205 worst|dlogsd|=0.04592`.
- E4 — reference gates read: `tests/test_behavioral_typing.py:279-360`,
  `tests/test_behavioral_simulation.py:547-594`; impl read:
  `src/cdp_client.py:60-115`; SPEC-4 read (`docs/specs/SPEC-4-deterministic-gates.md`, 370 lines).
- Toolchain note: system `python` has no scipy/numpy/pytest
  (`No module named pytest/scipy`); all measurements used
  `/home/zoltan/browser-helper/.venv/bin/python` (pytest+scipy+numpy present).
