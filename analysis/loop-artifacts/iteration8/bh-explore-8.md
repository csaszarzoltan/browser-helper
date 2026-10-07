```
dispatch:  inline prompt
agent:     explore
repo:      /home/zoltan/browser-helper @ cb3fdce
brief:     sha256:961c9a511c88
verdict:   v20261005134000-741226 REQUEST-CHANGES (verification 2/5 on 73b5d52, v1.36.17 mock boundary)
status:    DONE — all five items answered with file:line or command output; report at both paths
```

# bh-explore-8 — highest-value next change (read-only)

Commit note: per brief ("Do not edit, commit, or stage anything else") this report is
written but NOT committed. The durable copy is staged at
`analysis/loop-artifacts/iteration8/bh-explore-8.md` for the orchestrator to commit.
Global §1 would require a commit; the brief prohibition wins here by §1b (an instruction
the agent cannot satisfy both ways) — dropped commit, named explicitly.

Model-alive proof: read `src/cdp_client.py:660-672` (pacing consumer) and
`tests/test_behavioral_typing.py:525-625` (mock assertion depth) during this run.

## 1. Single highest-value next change

**Add one live wire-protocol check for the typing path (integration-marked, skipped by
default), driving `POST /type` or `BehavioralTyping.type_text` against a real
(disposable/headed) Chrome and asserting the typed text lands.**

- Why this and nothing else: the suite is green on mocks but the one open verdict
  (`v20261005134000-741226`, verification 2/5 on `73b5d52`) is exactly "mocked suite
  scored 5.0/4.7 on a dead production tree". The defect class already bit once
  (v1.36.14 shipped BROKEN: `keyPress` invalid + `text=null` rejected; live `/type`
  returned HTTP 400 with 1/11 chars while 2805 tests were green).
- The current guard tests pin payload shapes but still run against a mock that
  accepts anything, so they cannot prove Chrome accepts the payload:
  - `tests/test_behavioral_typing.py:95-99` — `client = AsyncMock(); client._send_command = AsyncMock(return_value={"status": "ok"})`
  - `tests/test_behavioral_typing.py:577-586` — keyPress-ban comment itself admits "Mocked tests cannot see that, so pin it here"
  - `tests/test_behavioral_typing.py:589-619` — no-null-text comment: "A mock cannot see an invalid CDP payload, so assert the shapes here"
- Production surface to drive (all live, all real):
  - `src/behavioral_engine.py:212` — `await self._typing.type_text(text, mode="human", client=self._client)`
  - `src/main.py:3216` — `POST /type` route (`result = await run_op("type", client.type_text, ...)`); also `src/main.py:6430` flow_type caller
  - Valid wire alphabet documented in code: `src/behavioral_typing.py:328,352-355,370` (`keyPress` invalid, `-32602`)
- What "done" looks like (proposal only, not a decision): one test file or one test,
  `@pytest.mark.integration`, skipped without Chrome, that types a string containing
  a space (the `text=null` killer: `"a b"`) plus one uppercase/special char and reads
  back `input.value` via CDP; FAILS on `keyPress` or null-text regressions where the
  mock suite passes. Precedent: iteration-3 live re-verification strings
  ('hello world' / 'a b c' / 'UPPER' / 'a!b' / 'x1y2' / 'Mix 123!' ALL PASS, per
  `analysis/next-moves.md` Iteration 3).
- Considered and rejected (higher-value test applied):
  - "/health version drift fix": NO code change — `src/main.py:308` `version="1.36.20"` feeds `/health` (`return {"status": "ok", "version": app.version, ...}`); orchestrator's "1.36.19" is a stale running process, fixed by restart, not a diff.
  - "xfail audit extension to full suite": near-zero — real markers exist in exactly ONE file (item 3); the rest is stale header prose, not coverage.
  - "spurious WARN deletion": NO-OP (item 2).
  - "missing test-author gate for pacing": ALREADY DONE (item 3, `76c07dc` + `d28c3cd`).

## 2. Is the spurious WARN real?

**NO. There is no WARN statement, warning filter, or executable logic matching the
triage description in any of the three named files.**

Commands run (verbatim):
```
$ grep -n "WARN" tests/test_rate_limiter.py tests/test_pacing_consumption.py src/cdp_client.py
(no output, exit 1)
$ grep -n "warn\|WARN\|filterwarnings\|pytest.warns\|warnings\." tests/test_rate_limiter.py
(EXIT:1 — no hits)
$ grep -rn "pyproject.toml:44\|:245" tests/ analysis/
analysis/loop-artifacts/iteration5/bh-dev-5.md:19:old :245 ("Temporarily override randomness for reproducibility") was deleted ...
analysis/loop-artifacts/iteration5/brief-spec-5.txt:15:- `tests/test_rate_limiter.py:245` — the comment `# Temporarily override randomness ...`
(plus 6 more hits, ALL in analysis/ docs, NONE in current test code)
```
- The only two "unpinned" hits in `tests/test_rate_limiter.py` are prose inside
  docstrings, not code:
  - `tests/test_rate_limiter.py:243` — `The old gate ran kstest on ONE unpinned 1000-draw and asserted`
  - `tests/test_rate_limiter.py:303` — `problem: the p-value is invalid, not merely flaky) on an unpinned draw`
  (verified with `sed -n '230,260p' ... | cat -A` and `sed -n '295,320p' ... | cat -A`:
  both lines end with `$` inside a `"""` docstring body, no `warnings` import in file)
- `pyproject.toml:44` is `xfail_strict = true` (plus 4-line comment), not a WARN.
  The `:245` number is the iteration-5 false comment, deleted then
  (`analysis/loop-artifacts/iteration5/bh-dev-5.md:19`), not a live line.
- Would deleting the docstring words change test behaviour? NO — docstring-only edit;
  all 43 tests in the file pass with or without that prose (spot re-run this session:
  `.venv/bin/python -m pytest tests/test_rate_limiter.py -o addopts='' -q` →
  `43 passed, 1 warning in 2.96s`; the 1 warning is the pre-existing
  `StarletteDeprecationWarning` from `from fastapi.testclient import TestClient`
  at `tests/test_rate_limiter.py:18`, unrelated).

## 3. Candidates ALREADY DONE (each checked, even the NOs)

| candidate | check | result |
|---|---|---|
| pacing consumer gate (`:665-668` sleep) | `git log --oneline` shows `76c07dc test(pacing)`; file `tests/test_pacing_consumption.py` exists (205 lines); consumer at `src/cdp_client.py:665-667` present | DONE |
| xfail revival + `xfail_strict=true` | `git log` shows `d28c3cd`; `pyproject.toml:44` `xfail_strict = true`; `grep -c xfail` → fingerprint 8, behavioral 0 markers | DONE (file-local; full-suite sweep still open but near-empty, see §1) |
| `:245` false pinning comment | `analysis/loop-artifacts/iteration5/bh-dev-5.md:19` "was deleted"; current file has no such comment (`grep -n 245` empty in tests/) | DONE |
| `/typing/config` routes wired | `src/main.py:2808` GET + `:2820` POST exist; `route_paths()` tests pass (`-k route_registered` → `2 passed`) | DONE — the `tests/test_behavioral_typing.py:234,696` docstrings "xfail until endpoints are wired" are STALE PROSE (0 `@pytest.mark.xfail` in that file) |
| version strings agree | `pyproject.toml:3` 1.36.20, `src/main.py:308` 1.36.20, `Dockerfile:17` 1.36.20, `README.md:3` badge 1.36.20 | DONE (code); `/health` runtime value is deploy state, not a repo defect |
| DEFECT-001 repo-root collect | `git log --grep` shows `13ac740`+`ed4b201`; `testpaths = ["tests"]` at `pyproject.toml:40`; `git ls-files \| grep '^test_.*py$'` → empty per next-moves | DONE |
| KS-gate determinism (v1.36.17/18) | `507fd61`, `4b29204`, SPEC-5; `43 passed` re-measured this session | DONE |
| keyPress docstring cleanup | `7c4df52`; remaining `keyPress` hits in `src/behavioral_typing.py:328,352-355,370` are CORRECT regression docs, not stale | DONE (nothing to delete) |
| stale `bh-gate-4.out` | `ce67d10` removed it | DONE |
| open verdict `v20261005134000-741226` | still OPEN by design (mock boundary, item 1's proposal would address it); PTR `04a3be8` closed by v1.36.20 consumer gate per `analysis/next-moves.md` Iteration 7 | NOT done — this is the live item §1 proposes |

"Nothing already done" answer: NO — eight of the ten checked candidates are DONE;
only the live wire check (§1) and the trivial stale-docstring prose are open.

## 4. Production caller for the candidate

YES — the candidate symbol is live code with production callers (paste of real grep):

```
$ grep -n "BehavioralTyping\|type_text\|_typing\b" src/behavioral_engine.py
23:from behavioral_typing import BehavioralTyping, TypingConfig
93:            self._typing = BehavioralTyping(typing_config)
99:            self._typing = BehavioralTyping(TypingConfig(cpm_min=cpm_min, cpm_max=cpm_max))
106:    def typing(self) -> BehavioralTyping:
189:    async def type_text(self, selector: str, text: str) -> dict:
212:        await self._typing.type_text(text, mode="human", client=self._client)
$ grep -n "BehavioralTyping\|type_text\|typing_config" src/main.py | head
2809:async def get_typing_config():
2821:async def post_typing_config(body: TypingConfigRequest | None = None):
3216:async def type_text(body: TypeRequest):
3224:    result = await run_op("type", client.type_text, body.selector, body.text)
6430:                r = await run_op("flow_type", client.type_text, step.selector or "", step.value or "")
$ sed -n '660,672p' src/cdp_client.py
        # Human pacing: sleep the configured random delay before sending
        delay_ms = self.rate_limiter.get_delay()
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
```
- Wiring slice NOT needed: `BehavioralTyping.type_text` has 3+ production callers
  (engine + two `main.py` routes). Zero-caller rule does not trigger.
- For non-code sub-candidates caller check is N/A: `/health` drift is ops-restart
  (no caller question), docstring/WARN deletion touches no symbol (no caller question).

## 5. What the reader would get wrong from this report alone

- Signals that look stronger than they are: "suite green" (2844p/8x/409s) is
  ORCHESTRATOR-measured at release, NOT re-run here — I ran only the
  `test_rate_limiter.py` slice (43 passed) and `-k route_registered` (2 passed) plus
  full `test_behavioral_typing.py` (67 passed). Do not read my DONE as a fresh
  full-suite green.
- Numbers I did NOT re-measure (taken from `analysis/next-moves.md` Iteration 7 /
  `analysis/loop-artifacts/iteration7/bh-gate-7.md`): 2855 collected, G3-M1/M2/M3
  mutant kills (1f/4f/3f), fingerprint `--runxfail` 8f81p, release-validate 68 tools.
  Signal: every such number above without a `$` prompt is cited, not measured.
- Assumption without measuring: no live Chrome exists in this environment, so the §1
  proposal's feasibility (headed/disposable Chrome, integration-mark mechanics) is
  inferred from `pytestmark = pytest.mark.integration` precedent in 8+ files
  (e.g. `tests/test_cookie_export.py:20`) and `test_chrome_diagnostics.py` live-pid
  tests — NOT from launching Chrome here.
- `/health 1.36.19` claim: NOT re-measured (no running service queried); code path
  (`app.version` → health payload) verified at `src/main.py:306-320` only.
- `grep -c xfail` asymmetry (8 vs 0): the behavioral file's 2 "xfail" hits are
  docstring prose at `:234`/`:696`, not markers — a substring count without the
  `mark.xfail` qualifier overstates it. I used the qualified form
  (`grep -rn "mark.xfail\|xfail(" ... | uniq -c` → 8 in fingerprint only).
- Budget: all 5 items completed inside the 600s budget; no item deferred.
