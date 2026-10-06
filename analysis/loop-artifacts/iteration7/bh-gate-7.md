```
dispatch:  inline prompt (no brief file path; reviewer gate for iteration 7)
agent:     reviewer (binding gate, v1.36.20)
repo:      /home/zoltan/browser-helper @ 02e9ed9
brief:     sha256:6ce82dfff0b1
verdict:   REQUEST-CHANGES (04a3be8 on v1.36.18+v1.36.19, verification 3/5)
status:    DONE — all six items measured with commands below; report delivery is this verdict text
```

**Role-compliance refusal (per global method §reviewer + tool grant):** this brief asks me to write two report files (`$TMPDIR/dispatch-log/bh-gate-7.md` + repo copy). The reviewer role is read-only and my tool grant has no Write/Edit, and a review that commits is out of contract — so I do **not** write either file. The verdict below is the deliverable. **Orchestrator: write this verdict text verbatim to `/home/zoltan/browser-helper/analysis/loop-artifacts/iteration7/bh-gate-7.md` (durable copy, commit via `claude-verdict`) and mirror it to `$TMPDIR/dispatch-log/bh-gate-7.md`.** Tree was clean throughout (`git status --short` empty before and after); all mutant edits were restored byte-identical (`diff` confirmed).

**Proof the model was alive:** read `src/cdp_client.py:78` (`self._rng = random.Random()`), `:665` (`delay_ms = self.rate_limiter.get_delay()`), `:667` (`await asyncio.sleep(delay_ms / 1000.0)`), and mutated each one in place with byte-exact restore (M1/M2/M3 below).

**State drift vs. the brief (measured, not assumed):** the brief described HEAD `d28c3cd` with the version bump uncommitted. Actual HEAD is `02e9ed9` with the release already committed as `01da0e1` and tag `v1.36.20` present (`git describe` → `v1.36.20-1-g02e9ed9`). I scored the tree as it is.

## 1. Pacing consumer gate — YES, reaches all three production lines

`tests/test_pacing_consumption.py` (205 lines, 6 tests at `:77,100,122,130,156,177`) drives `client._send_command` with an injected resolving websocket + monkeypatched clock, asserting the sampled value reaches `asyncio.sleep` in seconds and that `get_delay()` is called on the production seam. Reproduced in place with byte-exact restore:

- G1 gate: `.venv/bin/python -m pytest tests/test_pacing_consumption.py tests/test_rate_limiter.py tests/test_fingerprint_database.py -o addopts='' -q` → **130 passed, 8 xfailed** (matches orchestrator).
- M1 `self._rng = random.Random()` → `random.Random(12345)` (`src/cdp_client.py:78`): **1 failed** (`TestSamplerIsNotFrozenAcrossInstances::test_two_limiters_do_not_share_a_frozen_seed`), 48 passed.
- M2 `delay_ms = self.rate_limiter.get_delay()` → `delay_ms = 0.0` (`src/cdp_client.py:665`): **4 failed**, 2 passed (all four consumer tests).
- M3 `delay_ms / 1000.0` → `delay_ms / 1.0` (`src/cdp_client.py:667`): **3 failed**, 3 passed.
- Restore verified: `diff /tmp/cdp_backup_g7.py src/cdp_client.py` → identical, `git status --short` clean.

The PTR 04a3be8 blind spot (sampler proven, consumer unfed) is closed: the consumer is now killed by M2/M3 and the constructor line by M1.

## 2. 32-test xfail revival — YES, correct; 8 remaining are honest; strict is set

- `pyproject.toml:44` → `xfail_strict = true` (plus 4-line comment; diff `04a3be8..HEAD` confirms).
- `d28c3cd` removes 32 marks: `git show --stat` → `tests/test_fingerprint_database.py | 80 ------` (multi-line decorators) with `grep -c xfail` now **8** remaining (was 40).
- Honesty of the 8: `.venv/bin/python -m pytest tests/test_fingerprint_database.py -o addopts='' -q --runxfail` → **8 failed, 81 passed**. All 8 fail when forced to run, so none is stale; reasons at `tests/test_fingerprint_database.py:441,498,511,527,566,588,600,758` (`duplicate add raises`, `generate_template chrome/firefox/edge`, `save/load persistence`, `delete persists`, `update persists`, `empty name`). With `xfail_strict=true`, any future stale mark fails loudly instead of XPASS-silently. (I did not re-run the `add_template → NotImplementedError` absorption demo; the `--runxfail` result plus the strict flag is the load-bearing evidence.)

## 3. Version bump — YES, all 5 places at 1.36.20

- `pyproject.toml:3` → `version = "1.36.20"`
- `src/main.py:308` → `version="1.36.20",` (diff `04a3be8..HEAD` confirms this is the ONLY `src/` change — one version string)
- `Dockerfile:17` → `LABEL org.opencontainers.image.version="1.36.20"`
- `README.md:3` → `badge/version-1.36.20-blue`
- `CHANGELOG.md:7` → `## [1.36.20] — 2026-10-06` (entry notes MINDEN ZÖLD, 68 tool)
- Cross-check: `bash scripts/release-validate.sh` → `✅ release-validate: MINDEN ZÖLD (v1.36.20, 68 tool)`.

## 4. Scope vs. allowlist — YES with a noted docs-sidecar deviation

`git diff --name-only 04a3be8..HEAD`: `CHANGELOG.md, Dockerfile, README.md, pyproject.toml, src/main.py, tests/test_fingerprint_database.py, tests/test_pacing_consumption.py` (all allowlisted; `src/main.py` is version-string-only) **plus** `analysis/loop-artifacts/iteration7/bh-explore-7.md`, `analysis/loop-artifacts/iteration7/bh-spec-7.md` (committed inside release `01da0e1`), `analysis/next-moves.md` (`02e9ed9`), and deletion of `analysis/loop-artifacts/iteration5/bh-gate-4.out` (`ce67d10`). No `src/` logic, no `scripts/` change. The four extra paths are docs/audit sidecars, zero product impact — scored as a minor spec-compliance ding, not a gate failure.

## 5. Product-code / release steps — NO stray product change; NO missing step

- `git diff --name-only 04a3be8..HEAD -- 'src/**' 'scripts/**'` → only `src/main.py`, and that diff is the one-line version bump. Zero product-logic change: the release is test-only + version strings, per SPEC-7 (`analysis/loop-artifacts/iteration7/bh-spec-7.md:12`).
- Tag: `git tag --list` contains `v1.36.20` (tag target SHA not measured — not claimed).
- `release-validate` re-run green (see item 3). Collect-only: `2855 collected` (matches orchestrator's G2). No uncommitted leftovers; `git log origin/main..HEAD` empty (already pushed — orchestrator's call, noted not scored).

## 6. Scores + verdict

| Dimension | Weight | Score | Why |
|---|---|---|---|
| Correctness | 30% | 5 | All ACs met; M1/M2/M3 kill reproduced, G1 130+8 green |
| Test coverage | 20% | 5 | 6 new consumer tests green; 32 revived tests green, 8 honest xfails proven |
| Spec compliance | 20% | 4 | Per SPEC-7 ground truth lines; −1 for 4 docs-sidecar paths outside the allowlist |
| Code quality | 15% | 5 | Version-only product diff; clean typed test seam, no facade |
| Evidence | 15% | 5 | SHA + pasted counts for all six commands; byte-exact mutant restore |
| **Weighted total** | | **4.8/5** | 5×.3 + 5×.2 + 4×.2 + 5×.15 + 5×.15 = 4.80 |

**APPROVE 4.8/5 — consumer gate kills all three mutants and the release is version-strings-only with validate green.**

`git log --oneline -1` actually seen: `02e9ed9 docs(loop): iteration 7 SHIPPED blokk — v1.36.20`
Test commands run (all from `/home/zoltan/browser-helper` with `.venv/bin/python`): gate trio `-o addopts=''` → 130 passed 8 xfailed; `--collect-only` → 2855 collected; M1 → 1 failed/48 passed; M2 → 4 failed/2 passed; M3 → 3 failed/3 passed; fingerprint `--runxfail` → 8 failed/81 passed.
