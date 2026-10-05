# POST-TASK REVIEW — /home/zoltan/browser-helper, v1.36.12 → v1.36.17

```
REPO:            /home/zoltan/browser-helper
COMMIT(S):       7cdc515, 97afc47/ab50d84, e7fde1a, 4f06d18, 7c4df52, 73b5d52 (+ docs commits)
DISPATCHES:      17 loop dispatches (2 review) · LEDGER: ~/.cache/claude-queue/dispatch-log/dispatch-ledger.log
ARTIFACTS:       9/32 survived inside the repo

SCORES:  brief 3 · target 4 · verification 2 · scope 3 · honesty 3 · evidence 2
VERDICT: REQUEST-CHANGES
```

Two dimensions are below the 4.0 threshold and they are the two that matter: **the verification
could not have caught what shipped broken**, and **two thirds of the reasoning is on a 72-hour
lease.**

## The finding that matters

**Two production-breaking defects passed a full green suite AND two binding gates scoring 5.0 and
4.7.** The loop's own verification pinned the defect as correct. Verified first-hand against the
pre-hotfix tree:

```
$ git show 4f06d18^:tests/test_behavioral_typing.py | grep -n keyPress
520:        assert event_types == ["keyDown", "keyPress", "keyUp"], (
521:            f"Expected [keyDown, keyPress, keyUp], got {event_types}"
```

`keyPress` is not a valid CDP `Input.dispatchKeyEvent` type. **The suite asserted the invalid
sequence and was green.** Live, `POST /type` returned HTTP 400 and typed 1 of 11 characters.

The tester's Q12/Q13 nailed the mechanism and I confirmed both mocks:

- `tests/test_behavioral_typing.py:95-99` — `AsyncMock(); client._send_command =
  AsyncMock(return_value={"status": "ok"})`. **Canned ok for any method and any payload.**
- `tests/test_behavioral_engine.py:69-87` — a stub that appends to `client._sent` and returns `{}`.
  **Never serialises JSON, so a null `text` field cannot be seen.**

No mocked verification could have caught either defect. The guard tests added in the hotfix
(`:577-586` keyPress-ban, `:589-619` no-null-text) still run against the same mocks — they pin the
fix, not the protocol.

## What the loop did NOT do that the skill mandates

**The BUILD step never dispatched `tester` or `test-author`.** The skill's step 5 reads
`BUILD → developer implements, tester verifies, test-author writes the gate`. Verified from the
ledger: every `agent=tester` and `agent=test-author` row predates the loop (2026-10-04); inside
2026-10-05 the loop ran explore / reviewer / spec-author / developer / reviewer only. **The binding
`reviewer` gate was the only verification, and it re-ran the same mocked suite the developer wrote.**
The gate's 4.5–5.0 scores were real and about the right files — and structurally unable to see a
wire-protocol defect. That is a `verification` failure, and it was mine.

## PART 0 — the briefs

17 briefs, six clauses counted per brief, text read where the count was 0 or 1:

- **16/17 carried all six clauses.** Budget *with a number* (e.g. `BUDGET: 600 seconds. If you run
  out, report which items you completed`), numbered items, an explicit do-not-decide line, an output
  path.
- **`brief-spec-1.txt` is the one gap**: it has a budget (`you have 5 minutes`) and a numbered list,
  but **no "report every item, even if NO" clause**. A spec answering 4 of 6 items would have been
  indistinguishable from a complete one. This is exactly the class PART 0 exists to catch.
- Three briefs named the **wrong output path**: `brief-spec-4.txt` said write to
  `$TMPDIR/bh-spec-4.md` (the agent correctly wrote `docs/specs/SPEC-4-deterministic-gates.md`
  instead, *better* than asked), and `brief-gate-4.txt` named `bh-gate-4.md` — **the agent wrote the
  complete 8167-byte report to `bh-gate-4.out` and never created the `.md`.** "I wrote it somewhere"
  was reachable because the path was a convention, not a fact.

## PART 1d — load-bearingness: PASS

The opposite of the Veritas zero-caller class. The full production chain exists:

```
src/session_registry.py:282   client.enable_behavioral(HumanProfile.from_session(sid))
src/cdp_client.py:1966        return await self._behavioral.type_text(selector, text)
src/behavioral_engine.py:212  await self._typing.type_text(text, mode="human", client=self._client)
src/behavioral_engine.py:98   cpm_min = round(self._profile.wpm_range[0] * 5 * self._profile.speed_factor)
src/main.py:3224              result = await run_op("type", client.type_text, body.selector, body.text)
```

`HumanProfile.enabled` defaults to **True** and the engine is attached **automatically for every
session** — the client never opts in. So the swapped code is reachable from `POST /type` and the
per-session profile (`wpm_range` 40–60, `speed_factor`) really does change every keystroke delay.

**One below-the-line element:** `_compute_cpm` has **zero production callers**
(`grep -rn _compute_cpm src/` → only the definition at `:232`). Its tests were tightened in v1.36.13
(`TestComputeCpm`, strict gate) and it is a useful self-check, but no production code consumes it.
Below the line on its own merits; incidental to iteration 2's target, which was above it.

## PART 3 — process

**A read-only-intent brief produced a commit, and it swept my uncommitted work.** `c7b8f83`
(`docs(spec-4): …`) contains `docs/specs/SPEC-4-deterministic-gates.md` **plus** a 1-line change to
`tests/test_behavioral_typing.py` that was **my uncommitted docstring fix**. Root cause is mine: I
dispatched with a dirty working tree, so "sweep in the rest" was available. The agent **disclosed it
in its own commit message** ("Also carries a one-line docstring fix … left uncommitted by a prior
dispatch"), which is the honesty this loop depends on.

**Proof that the gate can fail — in place, with a byte-exact restore.** Mutating the real repo file
(`lognormvariate` → `uniform(0.15, 0.30)` at `behavioral_typing.py:230`) turned the real test red:

```
$ md5sum src/behavioral_typing.py     → c2495385b5796f7b5f83c3dec6d75331
  [mutate] 1 failed, 1 warning in 2.50s  (AD statistic fires)
$ git checkout -- src/behavioral_typing.py
$ md5sum -c → src/behavioral_typing.py: OK
  [restored] 1 passed
  git status --short → empty
```

**The verdict store was never used.** `claude-verdict --repo … --list` → *no verdicts*. Six releases,
zero recorded verdicts, while the gate-4 report itself ended with *"the orchestrator should record
this report via `claude-verdict`"*. PART 4b's channel existed and I did not use it.

**Defect hygiene is clean**: no `BLOCKED*`/`*STATUS*`/`*KNOWN-ISSUES*` files tracked, no open
verdicts pointing at shipped work.

## PART 2 — the agents' answers

Both audits were asked and both held up where checkable.

**developer** (8371 B) — 13/13 answered, several as `not established` rather than asserted, which is
the correct behaviour. Verified independently: the SHAs it named are real and accurately described
(`97afc47` = the v1.36.13 content commit, `ab50d84` its version bump); its Q4 allowlist claim
(`git show --name-status 97afc47` → exactly 2 files, 84 insertions / 30 deletions) reproduces; its
Q12 zero-caller claim for `_compute_cpm` reproduces. Its Q3 is a real, self-reported deviation: the
SPEC-2 full-suite regression guard **was not run, out of budget** — and it said so.

**tester** (8788 B) — and its scope note is the single most valuable sentence in this review: *"no
`tester`-role dispatch ever ran inside the v1.36.12–v1.36.17 loop."* It established that from
`ls /tmp/dispatch-log/brief-*.txt` and a grep, and I confirmed it from the ledger. It answered every
item against the record rather than inventing first-hand claims, and marked both Q12/Q13 honestly.

Where they disagree: the developer grades its own verification as adequate and defers to the live
check; the tester states flatly that **no mocked verification could have caught either defect**. The
tester is right, and the disagreement is itself the finding — the role that would have said so was
never dispatched.

## NOT ESTABLISHED

- Whether bh-dev-2.md's pasted command outputs were observed or transcribed (the developer's own Q1/Q2
  caveat). Nothing re-ran them.
- Whether the SPEC-2 full-suite regression guard would have passed at the time — it was never run.

## THE FIX — in order

**1. The brief clause (outlives the code).** Every `developer` brief in this loop should carry the
verification-shaped clause the loop never had:

> **Acceptance, additionally:** if your change alters what is sent over a real wire protocol (CDP,
> HTTP, a socket), a green mocked suite is NOT acceptance. Name the live endpoint or command you
> exercised against a real/throwaway instance and paste its actual output. If you cannot run one, say
> `no live check available` — do not report the item as verified.

Why: measured — v1.36.14 shipped with 2805 green tests and gates at 5.0/4.7 while `POST /type`
returned HTTP 400 and typed 1 of 11 characters. The suite pinned the defect as correct at
`tests/test_behavioral_typing.py:520`.

**2. An agent description.** `tester` should state its boundary explicitly, because this loop skipped
it and the gate inherited the job:

> You are not a second reviewer. You verify against the production surface, not a mock. If the code
> under test is dispatched to a real service or protocol, a mocked run is not evidence; drive the
> live surface, or report `could not verify against production` as your result.

Why: the binding `reviewer` gate re-ran the developer's own mocked suite and scored it 4.5–5.0 on
both the broken and the fixed tree. Nothing in the loop could say "that test cannot fail".

**3. `~/.claude/CLAUDE.md`.** Add the universal rule that the loop's own step 5 encodes and the
orchestrator skipped:

> A pipeline step named in a skill is not optional. `BUILD → developer implements, tester verifies,
> test-author writes the gate` means three dispatches. Skipping a role silently transfers its
> verification duty to the next role in the chain, which will report success.

**4. This skill.** Two gaps:

- **It has no question about whether the mandated pipeline steps actually ran.** PART 3 audits the
  diff, the scope and the record; it never asks *"did every role the method requires appear in the
  ledger?"* One `grep` on the ledger would have caught the skipped tester before the reviewer was
  ever dispatched. Add to PART 3:

> **Mandated-step audit** — for each step the governing method names, count its dispatches in the
> ledger over the task's time window. A step named in the skill with **zero** dispatches is a
> finding, whatever the outcome: the duty silently moved to the next role in the chain. Measured
> 2026-10-05: a 4-iteration loop ran explore/spec-author/developer/reviewer and **never dispatched
> `tester` or `test-author`**, though its own step 5 names all three; the binding gate re-ran the
> developer's mocked suite and scored 5.0 and 4.7 on a tree whose production typing path was dead.

- **`PART 1d` appears twice** under two different headings, with two copies of the same caller-check
  guidance and two separate Q12 assignments. Deduplicate so a reader gets one instruction.

## When the review finds nothing

It did not. But the code is, as of `73b5d52`, correct — and the live verification is the reason.
Verified live this session: `/health` `1.36.17 connected=true tabs=0`, and `POST /type` →
`'hello world'`, `'Mix 123!'`, `'a b c'`, `'UPPER'` all PASS.
