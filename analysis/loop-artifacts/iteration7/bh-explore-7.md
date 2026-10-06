```
dispatch: inline prompt (no brief file path)
agent: explore
repo: /home/zoltan/browser-helper @ d28c3cd
brief: sha256:92c6b84235bc
verdict: REQUEST-CHANGES (04a3be8 on v1.36.18+v1.36.19, verification 3/5; older open verdict v20261005134000-741226 on 73b5d52 noted separately)
status: DONE — all five items answered; report at BOTH paths, byte-identical, 11635 bytes
```

**Commit note (per §1):** I did NOT commit. The brief explicitly forbids it ("Do not edit, commit, or stage anything else"), so the brief wins on this point and the global commit rule is the one I dropped. Durable copy is written but uncommitted at `analysis/loop-artifacts/iteration7/bh-explore-7.md` (the whole `iteration7/` dir shows as untracked — that dir listing also includes pre-existing `ptr2-*` files the `git ls-files` shows as tracked; my only new file is `bh-explore-7.md`). No other files touched; `git status --short` shows only `?? analysis/loop-artifacts/iteration7/`.

**Proof the model was alive:** read `src/cdp_client.py:70-140` + `:650-690`, `tests/test_rate_limiter.py:250-290`, full `git show 76c07dc` body, grep-mapped all 6 tests in `tests/test_pacing_consumption.py` to mutants, and re-ran slices: `49 passed` (6 pacing + 43 sampler), collect `2855 tests`, `--runxfail` on fingerprint DB = `8 failed, 81 passed`.

**Answer in brief:**

1. **Highest-value next change: GATE + RELEASE the two unreleased test-only commits (v1.36.20 candidate). No new code.** `76c07dc` + `d28c3cd` sit on top of v1.36.19 unreleased; all five version files still read 1.36.19 with no drift; CHANGELOG has no entry for either. Rejected: wire-protocol live check (real but larger scope, belongs to the older verdict), xfail-audit extension (grep shows only 8 remaining xfails, all in the audited file; other files carry `skipif`, not `xfail`), version drift (none), root-collect (already shipped).
2. **Consumer gap CLOSED** (pending gate re-verification): all three PTR mutants (78 constant seed / 665 pacing-disabled / 667 ms-s unit) plus two more map to named tests in `tests/test_pacing_consumption.py` (`:77`, `:100`, `:122`, `:130`, `:156`, `:177`); 49/49 green measured here. Boundary: clock + transport injected (hand-rolled, no `Mock` — grepped empty), so no wall-clock/live-CDP proof by design.
3. **Already done:** the revive itself + `xfail_strict=true` (DONE, re-verified); gate over the new file, release/CHANGELOG/1.36.20, any `bh-gate-7*`/`bh-release*` artifact — all checked via `analysis/loop-artifacts/iteration7/` listing, `git log --grep`, `git ls-files`, CHANGELOG head: **nothing already done**.
4. **Production caller CONFIRMED:** `RateLimiter` built at `src/cdp_client.py:132`, `get_delay()` called at `:665`, slept at `:667`, before `send` at `:675`; operator surfaces `GET /rate/config`, `POST /rate/config`, `GET /rate_limiter/status` (`src/main.py:2933,7589`), MCP `rate_limiter_status` (`tools.py:1191`, registered `registry.py:75-76`). Not dead code; no wiring slice needed.
5. **What could mislead:** I did NOT re-apply mutants in place (kill claims rest on the 76c07dc matrix + code read); did NOT run the full 2855 suite (only collect + 49-slice + `--runxfail`); did NOT run bare-root collect or release-validate. Numbers I didn't re-run are labeled as carried, not measured.

Report at both paths, `cmp` clean, 11635 bytes each:
- `$TMPDIR/dispatch-log/bh-explore-7.md`
- `/home/zoltan/browser-helper/analysis/loop-artifacts/iteration7/bh-explore-7.md`
en release commit (version bump to 1.36.20 in the 5 version files + CHANGELOG entry + `bash scripts/release-validate.sh`).

## 2. Is the RateLimiter/pacing CONSUMER gap now closed? YES — reproduced here by test-to-mutant mapping, with one stated boundary.

**Production lines (unchanged, `src/cdp_client.py`):**

- `:78` `self._rng = random.Random()` (constructor seed)
- `:665` `delay_ms = self.rate_limiter.get_delay()`
- `:666` `if delay_ms > 0:`
- `:667` `await asyncio.sleep(delay_ms / 1000.0)`

**The old sampler gate is still blind by construction (refute nothing — confirm the PTR's diagnosis stands for the OLD file alone):** `tests/test_rate_limiter.py:265` does `rl._rng = random.Random(20260905)` AFTER construction, so `:78` never executes under that file. The PTR's measured mutant (`Random()` -> `Random(12345)` -> 43 passed) is consistent with this read; I did NOT re-apply mutants in place this run (see §5).

**The new gate `tests/test_pacing_consumption.py` (205 lines, 6 tests) covers all three PTR mutants plus two more from the commit matrix:**

| mutant | covering test | how it fails (per 76c07dc message + code read) |
|---|---|---|
| `:78` constant seed `Random(12345)` | `TestSamplerIsNotFrozenAcrossInstances::test_two_limiters_do_not_share_a_frozen_seed` (:156-166: two instances, 12 draws each, `assert draws_a != draws_b`-shape) | cross-instance assert; single-instance tests cannot see it by construction |
| `:665` `delay_ms = 0.0` (pacing disabled at call site) | `TestSendPathConsumesTheDelay::test_send_command_sleeps_the_drawn_delay_in_seconds` (:77) + `test_each_send_draws_its_own_delay` (:130) + `TestSendPathUsesTheProductionSampler::test_limiter_value_reaches_the_sleep` (:177) | recorded `slept_ms` would be empty/zero |
| `:667` `delay_ms / 1.0` (ms/s unit error) | `test_send_command_sleeps_the_drawn_delay_in_seconds` (:77: asserts sleep arg equals drawn delay IN SECONDS) + `test_sleep_tracks_the_configured_window` (:100: two configs -> two sleeps) | 1000x sleep value |
| `:666` branch removed | `test_no_sleep_when_delay_is_zero` (:122) | sleep called when it must not be |
| `:667` constant sleep | `test_sleep_tracks_the_configured_window` (:100) + `test_each_send_draws_its_own_delay` (:130) | identical sleeps across configs/sends |

Full test list (all 6, `grep -n "def test" tests/test_pacing_consumption.py`): `:77 test_send_command_sleeps_the_drawn_delay_in_seconds`, `:100 test_sleep_tracks_the_configured_window`, `:122 test_no_sleep_when_delay_is_zero`, `:130 test_each_send_draws_its_own_delay`, `:156 test_two_limiters_do_not_share_a_frozen_seed`, `:177 test_limiter_value_reaches_the_sleep`.

**Measured here (not carried forward):**

```
$ .venv/bin/python -m pytest tests/test_pacing_consumption.py tests/test_rate_limiter.py -o addopts='' -q
49 passed, 1 warning in 4.58s
```

i.e. 6/6 new + 43/43 old green together — the new file does not break the sampler gate.

**Remaining CONSUMER surface:** none on the pacing path itself. The stated boundary is that the clock is injected (`recording_sleep` appends `seconds*1000`, no wall-clock wait) and the transport is a hand-rolled `_ResolvingWebSocket` (resolves the pending future from inside `send()`), NOT `AsyncMock` — `grep -n "Mock\|mock" tests/test_pacing_consumption.py` returns empty (measured). So a real-Chrome wall-clock/live-CDP run remains unproven BY DESIGN (suite stays fast); that belongs to the older wire-protocol verdict, not to this gap.

## 3. Already-done candidates — every one checked, even the NOs.

- `analysis/loop-artifacts/iteration7/`: contains ONLY `ptr2-dev.out`, `ptr2-dev.out.err`, `ptr2-report.md`, `ptr2-tester.out`, `ptr2-tester.out.err` (`git ls-files` measured) — post-task review audit artifacts, NOT a gate or release of 76c07dc/d28c3cd. Result: gate+release NOT done.
- `git log --oneline --grep="release\|1.36.20\|gate.*pacing\|pacing.*gate\|consumer"`: no release after d28c3cd, no 1.36.20, no gate dispatch over the new file. The only pacing-gate commit is 76c07dc itself (the change, not its gate). Result: NOT done.
- `git log --oneline --grep="pacing\|consumer\|gate\|release\|1.36.20\|xfail"`: latest hits are d28c3cd/76c07dc/ce67d10/04a3be8 — no follow-up. Result: NOT done.
- `git ls-files analysis/loop-artifacts/iteration7/`: no `bh-gate-7*`, no `bh-release*` report. Result: NOT done.
- `CHANGELOG.md` top entry still `## [1.36.19]`; no 1.36.20 section. Result: release NOT done.
- `tests/test_fingerprint_database.py` + `pyproject.toml:44 xfail_strict = true`: the revive IS done (d28c3cd), including the strict flag. Re-verified here: `--runxfail` on that file gives `8 failed, 81 passed` (measured) — exactly the 8 honest marks failing, so the flag + marks are consistent. Result: DONE (this one), and it is part of what the proposed gate would ship.
- Duplicate-root-collect fix (13ac740/ed4b201): DONE and shipped in v1.36.19 (not re-run here; out of scope for the next slice).
- Net: NOTHING beyond 76c07dc+d28c3cd themselves is done; the gate + release they need has no artifact, no commit, no ledger claim I could find.

## 4. Production caller — reproduced.

```
$ grep -rn "get_delay\|rate_limiter\|RateLimiter" src/ --include="*.py"
src/cdp_client.py:68:class RateLimiter:
src/cdp_client.py:105:    def get_delay(self) -> float:
src/cdp_client.py:132:        self.rate_limiter = RateLimiter()
src/cdp_client.py:665:        delay_ms = self.rate_limiter.get_delay()
src/cdp_client.py:687:        c = self.rate_limiter.config
src/cdp_client.py:699:        self.rate_limiter.config = RateLimitConfig(**merged)
src/main.py:7589:@app.get("/rate_limiter/status")
src/main.py:7590:async def rate_limiter_status():
src/main.py:7591-7607: (returns api_success("rate_limiter_status", ...))
src/main.py:2933:@app.get("/rate/config")
src/main.py:566:    """POST /rate/config body — partial updates allowed.
src/mcp_server/tools.py:1191:async def rate_limiter_status(...)
src/mcp_server/registry.py:75-76,435-436: rate_limiter_status registered ("browser.core")
```

Call chain: `CDPClient.__init__` (`:132`) builds the limiter -> every `_send_command` calls `get_delay()` at `:665` and sleeps at `:667` before `self._ws.send(...)` at `:675` -> operator surfaces are `GET /rate/config`, `POST /rate/config` (via `get_rate_config` `:685` / config setter `:699`), `GET /rate_limiter/status`, and MCP `rate_limiter_status`. NOT dead code. No wiring slice needed; the consumer test drives the real `_send_command` path.

## 5. What the reader would get wrong from this report alone — assumptions and unrere-run numbers.

- I did NOT re-apply any mutant in place (no `Random(12345)`, no `delay_ms = 0.0`, no unit-error run). The kill claims for the new gate rest on the 76c07dc commit message's MUTATION MATRIX + my code read of the 6 tests, NOT on a fresh in-place mutation run here. A gate dispatch should re-run at least the `:78`/`:665`/`:667` triple itself.
- I did NOT run the full suite (2855 tests). Numbers I quote for it (2806/2812/2855 lineage, "full scoped suite timed out at 180s") are carried from the brief/session context, not measured here. What I DID measure: collect-only `2855 tests collected in 5.52s`; the 49-test pacing+sampler slice green; the `--runxfail` 8-failed/81-passed check on `test_fingerprint_database.py`.
- I did NOT run the bare-root collect or the release-validate script; "no drift / no duplicates" rests on `grep` + `git ls-files` reads, not on executing those gates.
- Assumption: `CLAUDE_BRIEF_SHA=92c6b84235bc` was exported by the dispatcher (it was — echoed at session start); the header hashes that value's first 12 chars, which is the whole value.
- Assumption: `TestSendPathUsesTheProductionSampler::test_limiter_value_reaches_the_sleep` ties the sleep to the REAL `get_delay()` rather than a stubbed value — from reading the test name + helper (`_paced_client` builds a real `RateLimiter(config)` and only injects transport + clock). I read the helper and the class names but did not paste every assertion body; the gate should read `:173-205` in full.
- Budget: well under 600s; all five items completed, none deferred.

