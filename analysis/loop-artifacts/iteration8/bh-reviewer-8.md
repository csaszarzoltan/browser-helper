```
dispatch:  inline prompt (reviewer, iteration 8 — six numbered items)
agent:     reviewer
repo:      /home/zoltan/browser-helper @ cb3fdce
brief:     sha256:38a9e99e55b4
verdict:   v20261005134000-741226 REQUEST-CHANGES (verification 2/5 on 73b5d52, v1.36.17 mock boundary — older, not about RateLimiter; still OPEN per claude-verdict --list this session)
status:    DONE — all six items answered, each with a file:line or command output; report at both paths below
```

# bh-reviewer-8 — what the last changes got WRONG or left INCOMPLETE

Model-alive proof: read `src/cdp_client.py:78` (`self._rng = random.Random()`),
`:513` (the only "warnings" hit — a code comment), `:660-670` (pacing consumer),
`tests/test_rate_limiter.py:240-250` (docstring prose, not a WARN),
`tests/test_behavioral_typing.py:93-99` (AsyncMock client) + `:577-586` (keyPress
regression guard), `pyproject.toml:40-46` (`testpaths` + `xfail_strict`), and ran
two pytest slices plus four greps this session (outputs pasted under each item).

Scope note: there is NO unshipped code diff. HEAD `cb3fdce` is three docs commits
past tag `v1.36.20` (`git describe` → `v1.36.20-3-gcb3fdce`; tag points at the
release commit `01da0e1`). The last shipped code is v1.36.20 (pacing consumer gate
`76c07dc` + xfail revival `d28c3cd`), gated APPROVE 4.8/5 in
`analysis/loop-artifacts/iteration7/bh-gate-7.md:64`. This review scores that
state; per the brief I do NOT issue a ship decision (scores in §7, no
APPROVE/REQUEST-CHANGES on a release — there is nothing pending to gate).

## 1. The single most important gap the last changes left

**The pacing gap is CLOSED. The remaining gap is the live wire-protocol check for
the typing path — mocked suite, live Chrome never driven.**

- Pacing consumer, `src/cdp_client.py:665-667`, is present and correct:
  ```
  delay_ms = self.rate_limiter.get_delay()
  if delay_ms > 0:
      await asyncio.sleep(delay_ms / 1000.0)
  ```
  Constructor seed `src/cdp_client.py:78` is `self._rng = random.Random()`
  (unpinned). Gate-7 killed all three mutants in place with byte-exact restore
  (M1 `:78`→`Random(12345)` 1 failed; M2 `:665`→`delay_ms=0.0` 4 failed; M3
  `:667`→`/1.0` 3 failed — cited from
  `analysis/loop-artifacts/iteration7/bh-gate-7.md`, NOT re-run here). My own
  slice this session:
  ```
  $ .venv/bin/python -m pytest tests/test_rate_limiter.py tests/test_pacing_consumption.py -o addopts='' -q
  49 passed, 1 warning in 3.04s
  ```
  (43 sampler + 6 consumer; the 1 warning is the pre-existing
  `StarletteDeprecationWarning` from `from fastapi.testclient import TestClient`
  at `tests/test_rate_limiter.py:18`, unrelated.)
- The open gap is exactly what explore-8 §1 proposes and what open verdict
  `v20261005134000-741226` still names: the typing path is green on mocks only.
  `tests/test_behavioral_typing.py:93-99` builds the client as
  `client = AsyncMock(); client._send_command = AsyncMock(return_value={"status": "ok"})`
  — a mock that answers `ok` to any payload, including the invalid `keyPress`
  that broke production in v1.36.14 (HTTP 400, 1/11 chars, 2805 tests green).
  The file's own comments admit it (`:577-586` "Mocked tests cannot see that, so
  pin it here"; `:589-619` no-null-text guard "A mock cannot see an invalid CDP
  payload"). Production callers are live: `src/behavioral_engine.py:212`
  (`await self._typing.type_text(...)`), `src/main.py:3216` (`POST /type`),
  `src/main.py:6430` (`flow_type`). No integration-marked typing test exists that
  drives a real Chrome (precedent marker style exists, e.g.
  `tests/test_cookie_export.py:20` `pytestmark = pytest.mark.integration`).
- Any other gap? Only the two near-empty items below (§3, §5). Nothing else:
  DEFECT-001 closed, 8 xfails honest, version strings agree, no stray artifacts.

## 2. The spurious WARN at pyproject.toml:44 / test_rate_limiter.py:245

**NOT real. Zero executable WARN content in any named file. Removing the words
would not change the suite — they are docstring/comment prose.**

Commands run this session (verbatim):
```
$ grep -n "WARN\|warnings\|filterwarnings\|pytest.warns" pyproject.toml tests/test_rate_limiter.py tests/test_pacing_consumption.py src/cdp_client.py
src/cdp_client.py:513:            return None  # only keep warnings/errors (keep buffer small)
```
That is the ONLY hit across all four files — a buffer-trimming code comment at
`src/cdp_client.py:513`, not a warning filter, not a `pytest.warns`, not
executable test behaviour. Explore-8's wider `grep -n "WARN"` (case-sensitive)
correctly returned empty; the case-insensitive form above finds only `:513`.

- `pyproject.toml:44` is `xfail_strict = true` (plus a 4-line comment,
  `pyproject.toml:40-46` verified by `sed -n '40,46p'`). No WARN.
- `tests/test_rate_limiter.py:245` (current numbering) sits inside the
  `test_uniform_distribution_ks_test` docstring (`:241-256`): the words
  "unpinned"/"reproducibility" there describe the OLD deleted gate; the only two
  "unpinned" hits in the file (`:243`, `:303`) are docstring prose inside `"""`
  bodies — verified by `sed -n '240,250p'` showing docstring text, and the file
  has no `warnings` import.
- Would deletion change behaviour? NO — docstring-only edit; the file's 43 tests
  pass with or without that prose (43 of the 49 in my slice above). The `:245`
  false-pinning comment from iteration 5 was already deleted then
  (`analysis/loop-artifacts/iteration5/bh-dev-5.md:19`).
- Conclusion: explore-8's "NOT real (0 WARN hits, docstring strings only)" is
  CONFIRMED with one qualification — case-insensitive search finds the `:513`
  comment, which is equally behaviour-neutral.

## 3. What must happen BEFORE a next release can ship

**Nothing code-blocking. Four entries, none a release blocker:**

1. Version bump — NOT NEEDED now, but NOTE the shape: all five strings read
   `1.36.20` (`pyproject.toml:3`, `src/main.py:308`, `Dockerfile:17`,
   `README.md:3`, `CHANGELOG.md:7` — all verified this session). The next
   release bumps all five + tag; `scripts/release-validate.sh:14-31` enforces
   exactly these five (`check_version` × 5). No drift exists to fix first.
2. CHANGELOG — `CHANGELOG.md:5` has an empty `## [Unreleased]` section; next
   release writes its entry there. Nothing missing, just the normal step.
3. Health drift (`/health` 1.36.19 claim) — NOT REPRODUCIBLE as a repo defect
   and NOT a release precondition: this session `curl -sv
   http://localhost:8931/health` → `Connection refused` on both ::1 and
   127.0.0.1, and `ss -ltnp` shows NOTHING listening on 8931. There is no stale
   process to restart — the service is simply down. The code path is correct
   (`src/main.py:308` `version="1.36.20"` feeds the app version; explore-8
   verified `app.version` → health payload). Action: start the service at deploy
   time; no diff required.
4. Full-suite xfail audit — formally still open (CHANGELOG says "file-local"),
   but de facto near-empty (see §5): `grep -rln "mark.xfail" tests/` returns
   exactly ONE file. Not a blocker; a 2-minute sweep, not a release gate.
5. Tag — `v1.36.20` exists; HEAD is 3 docs commits past it
   (`v1.36.20-3-gcb3fdce`). Next release tags normally. None of the three
   post-tag commits touches code (`992c32b`, `cb3fdce` docs; `02e9ed9` shipped-block).

Net: **none** — no version bump, no CHANGELOG repair, no tag fix, no health fix
blocks the next release. The only candidate work item is the §1 live typing test.

## 4. Stale OPEN defects or misplaced artifacts

**Neither. Checked both, both clean.**

- Defect store: `.agent-pipeline/04_defects/` contains exactly ONE file,
  `DEFECT-001-repo-root-pytest-cannot-collect.md`, whose `:6` reads
  `**Status:** fixed (SPEC-6, v1.36.19)`. `grep -rln -i "OPEN\|open"` over the
  directory returns empty. No BLOCKED files anywhere (`find -maxdepth 3
  -iname "*BLOCKED*"` → nothing; brief's "No BLOCKED files" confirmed).
- Open verdict `v20261005134000-741226` (v1.36.17 mock boundary) is still OPEN
  by design — it names the same live-wire gap as §1, so leaving it open is
  CORRECT, not stale. The PTR `04a3be8` (v1.36.18+19) is closed by the v1.36.20
  consumer gate per `analysis/next-moves.md` Iteration 7.
- Artifacts: `analysis/loop-artifacts/` holds `iteration3,4,5,6,7,8` — no gaps,
  no duplicates. `iteration7/` has exactly the three expected files
  (`bh-explore-7.md`, `bh-spec-7.md`, `bh-gate-7.md`); `iteration8/` has only
  `bh-explore-8.md` (this report joins it). No artifact sits in a wrong
  iteration directory. `git ls-files | grep -c "^test_"` → `0` (exit 1, no
  matches): no repo-root duplicate tests. `testpaths = ["tests"]` pinned at
  `pyproject.toml:45`.
- One hygiene note (not a defect): `analysis/loop-artifacts/iteration8/` is
  currently UNTRACKED (`git status --short` → `?? .../iteration8/`); the
  orchestrator commits it after the gate per method §reviewer. My report adds
  one more file to that untracked dir — named explicitly so nothing is swept
  silently (global §3e).

## 5. Are the 8 remaining xfails honest, and is the full-suite audit complete?

**The 8 are honest (all fail unmarked — re-measured this session). The audit is
file-local by record but suite-complete by measurement; one sweep remains to
close the paperwork.**

- Honesty, measured (not cited):
  ```
  $ .venv/bin/python -m pytest tests/test_fingerprint_database.py -o addopts='' -q --runxfail
  8 failed, 81 passed in 1.78s
  ```
  All 8 fail when forced to run → none is stale. Locations:
  `tests/test_fingerprint_database.py:441,498,511,527,566,588,600,758`
  (duplicate-add-raises, generate chrome/firefox/edge, save/load, delete,
  update, empty-name). `xfail_strict = true` at `pyproject.toml:44` makes any
  future stale mark fail loudly instead of XPASS-silently.
- Scope: `grep -rln "mark.xfail" tests/ --include="*.py"` → ONLY
  `tests/test_fingerprint_database.py`. Qualified counts:
  `tests/test_behavioral_typing.py:0`, `tests/test_pacing_consumption.py:0`,
  `tests/test_rate_limiter.py:0` real markers. (The 2 "xfail" hits in
  `tests/test_behavioral_typing.py:234,696` are docstrings — "xfail until
  endpoints are wired" — while `src/main.py:2808,2820` show the routes ARE
  wired; that is STALE PROSE in two docstrings, zero test-behaviour effect, and
  a legitimate micro-cleanup candidate.)
- So the "file-local" caveat in the v1.36.20 CHANGELOG is technically still
  accurate (the `d28c3cd` audit touched one file) but the remaining sweep is
  trivially small: one `grep -rln` already shows there is nowhere else for a
  stale mark to hide. What would close it: re-run the strip-and-run audit
  (remove marks → clean-tree run → keep genuine failures) across `tests/` and
  record the command + result. Two minutes, not a release gate.

## 6. What the reader would get wrong from this report alone

- **Mutant kills are CITED, not re-measured.** M1/M2/M3 (1f/4f/3f), the
  `130 passed, 8 xfailed` three-file gate cut, `2844 passed` scoped suite,
  `2855 collected` bare-root, and `release-validate MINDEN ZÖLD` all come from
  `analysis/loop-artifacts/iteration7/bh-gate-7.md` + `analysis/next-moves.md`
  Iteration 7. I ran only: the 49-test slice (43 rate_limiter + 6 pacing,
  `49 passed`) and the `--runxfail` cut (`8 failed, 81 passed`). Do not read my
  "pacing gap CLOSED" as a fresh full-suite green — it is a fresh slice green
  plus a cited gate.
- **`/health` was NOT measured against a running service** — connection refused,
  nothing listening. "No drift in the repo" is measured (five strings agree);
  "service not restarted" from the brief context could not be confirmed or
  refuted because there is no service. Assumption: deploy restarts it.
- **No live Chrome was launched here.** The §1 proposal's feasibility (headed /
  disposable Chrome, integration-mark mechanics) is inferred from precedent
  (`pytestmark = pytest.mark.integration` in 8+ files) and explore-8, not from a
  local Chrome run.
- **The `:513` qualification on §2.** A case-sensitive `WARN` grep is clean; a
  case-insensitive one finds a behaviour-neutral comment. Anyone re-checking
  with `-i` and stopping at the hit count would wrongly conclude explore-8
  missed something — the hit is prose, not logic.
- **Unmeasured number:** the "600s budget" — this review used a fraction of it;
  no item was deferred. All six items COMPLETED (none partial).
- **Scores below are state scores for the shipped v1.36.20 tree, not a gate on
  a pending diff** — there is no pending diff. Per the brief I score; the
  orchestrator decides.

## 7. Scores (shipped v1.36.20 tree as it stands at cb3fdce)

| Dimension      | Weight | Score | Basis |
|---|---|---|---|
| Correctness    | 30% | 5 | Pacing consumer present `:665-667`, seed unpinned `:78`; gate-7 killed M1/M2/M3; my slice 49 passed |
| Test coverage  | 20% | 5 | 6-test consumer gate (205 lines) + 32 revived; `--runxfail` 8f81p re-measured; live typing test is a gap, not a regression |
| Spec compliance| 20% | 4 | Tree matches specs; 2 stale docstrings (`behavioral_typing` `:234,696` "until wired" — routes ARE wired at `main.py:2808,2820`) |
| Code quality   | 15% | 5 | No stubs introduced; only version-string `src/` delta; WARN claim refuted, no dead code |
| Evidence       | 15% | 4 | Full suite + mutants cited from gate-7, not re-run; health endpoint dead (no service); slices re-measured |
| **Weighted total** | | **4.75/5** | 5·.3 + 5·.2 + 4·.2 + 5·.15 + 4·.15 = 1.5+1.0+0.8+0.75+0.6 |

No ship verdict per brief ("DO NOT DECIDE whether to ship — you score, the
orchestrator decides"). If this were a release gate, 4.75 ≥ 4.0 would be APPROVE
territory; the call is the orchestrator's.

---
`git log --oneline -1`: `cb3fdce docs(loop): iteration 7 next-moves — gate APPROVE 4.8/5 landed`
Test commands run this session:
- `.venv/bin/python -m pytest tests/test_rate_limiter.py tests/test_pacing_consumption.py -o addopts='' -q` → **49 passed, 1 warning** (pre-existing StarletteDeprecationWarning)
- `.venv/bin/python -m pytest tests/test_fingerprint_database.py -o addopts='' -q --runxfail` → **8 failed, 81 passed**
- `grep -rln "mark.xfail" tests/ --include="*.py"` → only `tests/test_fingerprint_database.py`
- `curl -sv http://localhost:8931/health` → connection refused (no listener; `ss -ltnp` confirms)
