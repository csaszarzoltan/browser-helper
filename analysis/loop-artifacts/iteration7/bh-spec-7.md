# SPEC-7 — GATE + RELEASE the two unreleased test-only commits as v1.36.20

```
dispatch:  inline prompt (no brief file path)
agent:     spec-author
repo:      /home/zoltan/browser-helper @ d28c3cd
brief:     sha256:55d18c919f3b
verdict:   REQUEST-CHANGES (04a3be8 on v1.36.18+v1.36.19, verification 3/5)
status:    DONE — all six items answered, each with a file:line or command
```

Scope: TEST-ONLY + RELEASE. No `src/` change. This spec ships two commits
already on HEAD as v1.36.20:

- `76c07dc` — `tests/test_pacing_consumption.py` (205 lines, 6 tests), the
  CONSUMER gate for the pacing delay (`src/cdp_client.py:665,667`).
- `d28c3cd` — `pyproject.toml` (`xfail_strict = true`, `:44`) + revival of
  32 stale `xfail` marks in `tests/test_fingerprint_database.py`.

Ground truth (read, not assumed): `src/cdp_client.py:78`
(`self._rng = random.Random()`), `:665`
(`delay_ms = self.rate_limiter.get_delay()`), `:667`
(`await asyncio.sleep(delay_ms / 1000.0)`); `pyproject.toml:3`
(`version = "1.36.19"`), `:44` (`xfail_strict = true`), `:45`
(`testpaths = ["tests"]`); `src/main.py:308` (`version="1.36.19"`);
`Dockerfile:17` (`image.version="1.36.19"`); `README.md:3-5` (version +
tests badges); `CHANGELOG.md:7` (`## [Unreleased]`), `:8`
(`## [1.36.19]`); `scripts/release-validate.sh` (4 checks + MINDEN ZÖLD).
Prior spec: `analysis/loop-artifacts/iteration5/bh-spec-5.md`. Prior
explore: `analysis/loop-artifacts/iteration7/bh-explore-7.md` (11635 B).
Commit-message convention (measured `git log --format=%s -15`): `type(scope):`
prefixes dominate (`test(...)`, `release(...)`, `spec(...)`, `docs(...)`,
`fix(...)`, `chore(...)`). Use `test(...)` / `release(v1.36.20): ...`.

Two-phase execution. A different agent implements; a gate scores. DO NOT
decide whether to ship.

---

## 1. GATE half — exact commands and expected outputs

Run all commands from `/home/zoltan/browser-helper` with the project venv
(`.venv/bin/python` — system python has no pytest/scipy; per SPEC-5 Evidence).

### G1. Scoped suite (the release gate)

```bash
cd /home/zoltan/browser-helper
.venv/bin/python -m pytest tests/test_pacing_consumption.py tests/test_rate_limiter.py tests/test_fingerprint_database.py -o addopts='' -q 2>&1 | tail -n 3
```

- Collect-only proof first:
  `... --collect-only -q -o addopts=''` must print `138 tests collected`
  (measured this spec run: 138 = 6 pacing + 43 sampler + 89 fingerprint).
- Expected: `130 passed, 8 xfailed` (6/6 new + 43/43 sampler + 81 passed /
  8 xfailed fingerprint), exit 0, zero failed, zero XPASS.
- Before/after counts: BEFORE (v1.36.19, without the two commits) the same
  three files would collect 132 (43 + 89 with 32 of the 89 XPASS-silenced);
  AFTER they collect 138 with `8 xfailed` and no XPASS. The `+6` is
  `tests/test_pacing_consumption.py:77,100,122,130,156,177` (6 tests,
  `grep -n "def test"` measured). The `32` revived marks are the
  `d28c3cd` delta (`pyproject.toml:44` makes the remaining 8 honest marks
  in `tests/test_fingerprint_database.py:441,498,511,527,566,588,600,758`
  strict).

### G2. Bare-root collect (DEFECT-001 stays fixed)

```bash
cd /home/zoltan/browser-helper
.venv/bin/python -m pytest --collect-only -q -o addopts='' 2>&1 | tail -n 2
```

- Expected: `2855 tests collected` (explore-7 measured), `0 error`, exit 0.
- Proves `pyproject.toml:45` (`testpaths = ["tests"]`) still holds and no
  root-duplicate regressed the `import file mismatch`.

### G3. Mutant in-place checks (the gate must FAIL on each)

Apply each mutant with `sed -i`, run the G1 scoped slice (must be RED),
then revert with `git checkout -- src/cdp_client.py` is FORBIDDEN by the
global rule for paths you did not write — instead revert with the inverse
`sed -i` (exact strings below) and prove clean with
`git diff --stat -- src/cdp_client.py` (must be empty). Never leave a mutant
in the tree.

| # | Mutant (exact edit, `src/cdp_client.py`) | Gate command | Must show |
|---|---|---|---|
| M1 | `:78` `self._rng = random.Random()` → `self._rng = random.Random(12345)` | G1 slice | OLD file alone: `43 passed` (blind, proves nothing); WITH pacing file: `1 failed` (`TestSamplerIsNotFrozenAcrossInstances::test_two_limiters_do_not_share_a_frozen_seed`, `tests/test_pacing_consumption.py:156`) |
| M2 | `:665` `delay_ms = self.rate_limiter.get_delay()` → `delay_ms = 0.0` | G1 slice | `4 failed` (the `:77`, `:100`/`:130`-family, `:177` send-path tests see empty/zero `slept_ms`) |
| M3 | `:667` `await asyncio.sleep(delay_ms / 1000.0)` → `await asyncio.sleep(delay_ms / 1.0)` | G1 slice | `3 failed` (1000x sleep value; `:77` seconds-assertion + `:100` window test) |

Reference numbers (orchestrator-measured in place, carried not re-run here):
M1-alone 43 passed / M1-with-pacing 1 failed / M2 4 failed / M3 3 failed.
The implementer MUST reproduce the RED runs live; a gate that stays green
on any of M1–M3 is rejected. Revert proof after each:
`git diff --stat -- src/cdp_client.py` prints nothing.

### G4. Fingerprint strictness proof

```bash
cd /home/zoltan/browser-helper
.venv/bin/python -m pytest tests/test_fingerprint_database.py -o addopts='' -q --runxfail 2>&1 | tail -n 2
```

- Expected: `8 failed, 81 passed` (explore-7 measured) — exactly the 8
  honest marks failing, proving `pyproject.toml:44` (`xfail_strict = true`)
  and the revived marks are consistent.

---

## 2. RELEASE half — every file that must change (1.36.19 → 1.36.20)

Exactly six paths. No other file may change (see §4).

| # | File | Edit | Prove command (must be GREEN after) |
|---|---|---|---|
| R1 | `pyproject.toml:3` | `version = "1.36.19"` → `version = "1.36.20"` | `grep -m1 '^version = ' pyproject.toml` prints `version = "1.36.20"` |
| R2 | `src/main.py:308` | `version="1.36.19"` → `version="1.36.20"` | `grep -n 'version="1.36.20"' src/main.py` hits `:308` |
| R3 | `Dockerfile:17` | `image.version="1.36.19"` → `image.version="1.36.20"` | `grep -n 'image.version="1.36.20"' Dockerfile` hits `:17` |
| R4a | `README.md:3` | version badge `version-1.36.19-blue` → `version-1.36.20-blue` | `grep -n 'version-1.36.20-blue' README.md` hits `:3` |
| R4b | `README.md:5` | tests badge `tests-2806%20passed` → `tests-<N>%20passed` where `<N>` = measured `passed` count from the full scoped suite run (do NOT hardcode; measure, then set) | `grep -n 'tests-.*passed' README.md` matches the run's number |
| R5 | `CHANGELOG.md:7` | new `## [1.36.20] — 2026-10-06` section under `## [Unreleased]` (`:7`), above `## [1.36.19]` (`:8`), naming both commits (`76c07dc` pacing-consumer gate, `d28c3cd` xfail revive + strict) with before/after counts | `grep -n '\[1.36.20\]' CHANGELOG.md` hits the new section |
| R6 | (no edit) tag + validate | `git tag v1.36.20` after the version commit; `bash scripts/release-validate.sh` | script prints `✅ release-validate: MINDEN ZÖLD (v1.36.20, ...)` and exits 0 |

Tool-count note: `scripts/release-validate.sh` §2 checks `docs/mcp-server.md`
and `README.md` against live `build_tool_defs()` (measured 68 this run via
`.venv/bin/python -c "from mcp_server.registry import build_tool_defs; ..."`).
If the script flags a tool-count line, update ONLY the stale count token on
that line (still within the 6-path allowlist only if the path is already
listed — `docs/mcp-server.md` is NOT in scope; report it instead of editing).

---

## 3. Acceptance criterion as RUNNABLE commands

```bash
cd /home/zoltan/browser-helper
.venv/bin/python -m pytest tests/test_pacing_consumption.py tests/test_rate_limiter.py tests/test_fingerprint_database.py -o addopts='' -q 2>&1 | tail -n 2
# expect: 130 passed, 8 xfailed, exit 0
.venv/bin/python -m pytest --collect-only -q -o addopts='' 2>&1 | tail -n 2
# expect: 2855 collected, 0 error, exit 0
bash scripts/release-validate.sh
# expect: MINDEN ZÖLD, exit 0
grep -m1 '^version = ' pyproject.toml && grep -n 'version="1.36.20"' src/main.py && grep -n 'image.version="1.36.20"' Dockerfile && grep -n 'version-1.36.20-blue' README.md && grep -n '\[1.36.20\]' CHANGELOG.md
# expect: all five greps hit
```

ACCEPT = all four blocks green. Any RED block = NOT accepted, no tag.

---

## 4. Target Files allowlist per phase

- **GATE phase: READ-ONLY.** May read `src/cdp_client.py:68-140,650-700`,
  `tests/test_pacing_consumption.py`, `tests/test_rate_limiter.py`,
  `tests/test_fingerprint_database.py`, `pyproject.toml`,
  `scripts/release-validate.sh`. May write NOTHING except `/tmp` scratch.
  Mutant `sed -i` edits MUST be reverted by inverse `sed -i` in the same
  run (never `git checkout`/`restore`/`reset` — global rule §4.2).
- **RELEASE phase: writes ONLY** `pyproject.toml` (R1), `src/main.py` (R2,
  version string only), `Dockerfile` (R3, label only), `README.md` (R4a+R4b
  badge tokens only), `CHANGELOG.md` (R5 new section only), plus the
  `v1.36.20` tag (R6). NO `src/` logic change, NO `tests/` change, NO other
  doc change. Anything else dirty (`git status --short`) is out of scope:
  name it in the report and leave it alone (global §3e — the staged
  `analysis/loop-artifacts/iteration7/bh-explore-7.md` is NOT yours to
  commit).

---

## 5. Product-code change in scope? NO

NO. The pacing production lines are already correct and are the thing the
new gate proves: `src/cdp_client.py:665` draws the delay,
`:666-667` sleeps `delay_ms / 1000.0` only when positive, `:78` seeds a
fresh `random.Random()` per instance. The "fix" that closed the consumer
gap IS the test file `tests/test_pacing_consumption.py` (`76c07dc`) — it
drives the real `_send_command` with an injected transport
(`_ResolvingWebSocket`, hand-rolled, zero `Mock` — explore-7 grepped empty)
and a recording clock, killing the M1/M2/M3 mutants the 43-test sampler
gate passed. Changing `src/` here would invalidate the very mutants the
gate is built to kill. If the implementer believes any `src/` file must
change, that belief is wrong — report back, do not edit.

---

## 6. What the reader would get wrong from this report alone

1. Mutant kill numbers (M1 1 failed / M2 4 failed / M3 3 failed; M1-alone
   43 passed) are CARRIED from the orchestrator's in-place runs noted in the
   brief, NOT re-run in this spec dispatch (spec-author reads code/config,
   does not mutate). The gate implementer must reproduce them live (§1-G3).
2. `130 passed, 8 xfailed` / `138 collected` / `2855 collected` / `--runxfail
   8 failed, 81 passed` combine one live measurement (138 + 89 collect-only
   this run) with explore-7/brief carried numbers — re-run §3 to confirm.
3. Full scoped-suite count for the README tests badge (`README.md:5`,
   currently `2806`) is NOT pinned here: `<N>` must be measured from the
   full run at release time, because 2855-collected vs 2806-passed lineage
   spans skipped/slow markers. Do not copy 2806 or 2855 into the badge.
4. Live tool count 68 was measured this run but the README/docs tool-count
   tokens were NOT re-grepped; `release-validate.sh` §2 is the authority.
5. Wall-clock: spec completed well under the 600 s budget; all six items
   DONE, none deferred. Commit convention above is measured from
   `git log --format=%s -15`; `METHODOLOGY.md` was not consulted (pointer
   is not evidence it exists).
6. This spec was NOT committed: the brief forbids commit/stage
   ("Do not edit, commit, or stage anything else"), so the brief wins on
   this point and the global commit rule is the one dropped (same as
   explore-7's disclosed non-commit). Durable copy lives at both paths
   below, uncommitted.
