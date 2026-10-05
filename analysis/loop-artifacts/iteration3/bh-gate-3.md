# GATE REVIEW — SPEC-003 typing-path engine swap (/home/zoltan/browser-helper)

dispatch: brief "ROLE: reviewer for /home/zoltan/browser-helper … SPEC-003 gate" (claude -p), spec at /tmp/dispatch-log/bh-spec-3.md
agent: reviewer
repo: /home/zoltan/browser-helper @ 8cd91a0 (swap itself: 71abe6d)
brief: sha256:not established — no brief file was supplied, the dispatch text is inline in the process args
verdict: REWORK 3.2/5.0 (previous gate run, on findings F1/F2/F3 in tests/test_behavioral_engine.py) — re-measured below
status: DONE — all 5 numbered items answered with pasted evidence; full suite + ruff re-measured

## FIRST FINDING: THE BRIEF'S PREMISE IS WRONG

The brief says "The change is uncommitted working-tree diff; `git diff` is the artifact."
**That is false.** The working tree is clean and the swap is committed as WIP:

```
$ git status --short          # (no output)
$ git diff --name-only        # (no output)
$ git log --oneline -4
8cd91a0 chore(loop): iteration 3 stopped — gate open, work local at 71abe6d
71abe6d WIP(loop): a gepelesi ut atkotese a BehavioralTyping modulra — gate NYITOTT
50de71d chore(loop): iteration 3 in progress — spec done, keyPress risk measured as NOT real
47a5a5c docs: a README teszt-badge es allapot-sor a MERT szamot mondja (2630 -> 2796)
```

A reviewer who trusted the brief and ran `git diff` would have scored an EMPTY change set.
I reviewed `git diff 50de71d..71abe6d` instead (baseline 50de71d is the orchestrator's stated
baseline commit). **This is a brief defect, not an agent defect** — reported so the next
dispatch brief says which commit is under review.

Scope of the swap commit:
```
$ git diff 50de71d..71abe6d --name-only
src/behavioral_engine.py
tests/test_behavioral_engine.py
```

---

## 1. CORRECTNESS — boundary is exactly as specified. PASS.

Old loop **deleted, no dead fallback** (spec §1 "DELETED, with no fallback"):
```
$ grep -n "keystroke_timing" src/behavioral_engine.py ; echo "exit=$?"
exit=1
```
(`grep` printed nothing; exit 1 = no match. AC-2 PASS.)

The old fire-and-forget sender is deleted too — this is what rules out the double-send:
```
$ grep -n "_send_key_event" src/behavioral_engine.py ; echo "exit=$?"
exit=1
```

Exactly one delegation replaces the loop — `src/behavioral_engine.py:212`:
```python
        # 2. Gépelés a BehavioralTyping modulon keresztül
        await self._typing.type_text(text, mode="human", client=self._client)

        return {"status": "ok", "operation": "behavioral_type", "result": {"chars": len(text)}}
```
`self._typing` (not `self.typing`) is the attribute access; the spec's own §5 line table
specifies `self._typing.type_text(...)`, so this matches the spec, and the `typing` property
exists at `:106-107` for AC-4/AC-6. No other `BehavioralTyping` method is called by the engine
(`grep` shows `_typing` referenced at :93, :99, :107, :212 only).

Kept, intact — disabled-profile early return `:191-192`:
```python
        if not self._profile.enabled:
            return await self._client.type_text(selector, text)
```
Selector/focus `:194-198` (`evaluate` + `click_at`) and the error dict `:207-210` are
byte-identical to baseline — the diff touches neither hunk:
```python
            return {
                "status": "error",
                "error": f"Element not found: {selector}",
            }
```
`self._sim` still constructed `:90` and still used for the mouse `:116`:
```
$ grep -n "_sim\." src/behavioral_engine.py
116:        result: MouseMovementResult = self._sim.wind_mouse_bezier(
```

**Anything the spec said to keep that is gone: NONE.** Signature at `:189` is unchanged, so
`cdp_client.py:1966` keeps working; `:86` adds `typing_config` as keyword-only with default
`None`, so `cdp_client.py:1994`'s existing 2-arg construction stays valid (confirmed by the
2805-test suite, which exercises that call site).

## 2. THE BEHAVIOURS THAT MUST SURVIVE — 4/4 PASS, each measured.

**(a) element-not-found returns a dict, does not raise — PASS.** Ran through the real engine
path, not the test only:
```python
client.evaluate -> {"status":"ok","result":None}
r = await engine.type_text("#missing","ab")
print(r)   # {'status': 'error', 'error': 'Element not found: #missing'}
# key events sent: []
```
Covered by `test_type_text_element_not_found` (asserts `result["status"]=="error"`,
`"#missing" in result["error"]`, and `_key_events(client) == []` — i.e. nothing is typed into
the void).

**(b) uppercase / shifted punctuation reach the page — PASS.** Measured the CDP payloads the
engine emits for `"H!"`:
```
keyDown texts: ['H', '!']      # shifted FACE VALUE, not base char
"modifiers" in any event: False   # no double-shift
```
Asserted by `test_no_modifiers_field` (also checks `len(keys) == 3*2`). Uppercase arrives as
`text="H"`, so a React/controlled input reading `event.key`/`event.data` sees `H` — spec §2
behaviour 1 and 2 satisfied, and the old `modifiers: 2` synthesis is gone as §2 requires.

**(c) named keys `\n`, `\t`, space, `\b` — PASS.** Measured through the ENGINE path
(`type_text("#i", "a\nb\tc d\be")`), keyDown events only:
```
keyDown keys: ['a', 'Enter', 'b', 'Tab', 'c', ' ', 'd', 'Backspace', 'e']
vk codes:     [ 65,     13,     66,     9,    67,   32,  68,            8,   69]
keyUp carries 'text'?  [False, False, False, False, False, False, False, False, False]
```
`\b` is the one the old engine handled by a dedicated branch that is now deleted; it resolves
through `_NAMED_KEYS["\b"] → ("Backspace","Backspace",8)` (`src/behavioral_typing.py:30-38`)
with vk=8 — strictly better than the old `code=""`, no-vk send, exactly as spec §2 predicted.
keyUp carries no `text` (spec §2 behaviour 4). `\x1b`/`\x7f` were not exercised: they are in
the same `_NAMED_KEYS` table and out of the review's named list. `tests/test_behavioral_typing.py:442`
covers `"line1\nline2\tindented  spaces"` at module level.

**(d) typing works with the profile disabled — PASS.** Two independent flags, both checked:
- `profile.enabled=False`: `test_type_text_disabled_profile_delegates` asserts
  `client.type_text.assert_awaited_once_with("#input","ab")` and that **zero** CDP key events
  were sent (no double-path).
- `TypingConfig(enabled=False)` (AC-5 script, verbatim from spec §7.1):
```
disabled-typing key events: 6 expected: 6
OK
```
  — text still reaches the field, no human delays, and the engine returns
  `{"status":"ok",...}` without pre-checking `config.enabled` (spec §4: no second code path).

## 3. THE SPEED TRANSLATION — implemented, applied once, clamped. PASS.

`src/behavioral_engine.py:92-99`, in `__init__` only (no post-hoc multiplier anywhere):
```python
        if typing_config is not None:
            self._typing = BehavioralTyping(typing_config)
        else:
            raw_min = round(self._profile.wpm_range[0] * 5 * self._profile.speed_factor)
            raw_max = round(self._profile.wpm_range[1] * 5 * self._profile.speed_factor)
            cpm_min = max(1, raw_min)
            cpm_max = max(cpm_min, raw_max)
            self._typing = BehavioralTyping(TypingConfig(cpm_min=cpm_min, cpm_max=cpm_max))
```
Injected config short-circuits the translation entirely (correct — spec §3 wants injection, not
global retuning).

Measured numbers:
```
default HumanProfile() (wpm 45-80, sf 1.0) -> cpm_min 225  cpm_max 400
speed_factor 0.7 -> 158 / 280
speed_factor 1.0 -> 225 / 400
speed_factor 1.3 -> 292 / 520
degenerate wpm_range=(0,0) sf=0.0 -> cpm_min 1  cpm_max 1     # clamped, min<=max holds
```
**Direction honoured: YES** — monotone increasing in `speed_factor` (158 < 225 < 292 on
cpm_min), so a faster factor still types faster. **Default produces (225, 400)**, matching spec
§3's prediction. Clamp is `max(1, raw_min)` then `max(cpm_min, raw_max)`, which satisfies
`TypingConfig._validate`'s `cpm_min >= 1 and cpm_min <= cpm_max` for a degenerate profile
instead of raising during `__init__` — spec §3's requirement met.

AC-6 script verbatim: `cpm_min 140 cpm_max 245` / `OK` for `wpm_range=(40,70), sf=0.7`
(= round(40*5*0.7), round(70*5*0.7)).

## 4. THE EVENT COUNT — 3 per character, ONE sender. PASS.

Counted from a **single** instrumented client, wrapping BOTH senders (`_send_command` and
`_ws.send`), for a plain lowercase string `"abc"` through `engine.type_text`:
```
4) lowercase "abc": keyDown+keyPress+keyUp = 9 expected 9 | ws.send key events = 0
   types per char: ['keyDown', 'keyPress', 'keyUp']
   keyPress carries text: 'a' | keyUp text: None
```
**9 events / 3 chars = 3 per character, all 9 via `_send_command`, 0 via `ws.send`** — no
second sender is alive, so no double-send. Independent confirmation from the AC-4 script
(spec §7.1 verbatim), which counts both senders and asserts:
```
key events: 15 expected: 15 (_send_command=15 ws.send=0)
OK
```
Locking this in the test suite too: `test_three_events_per_char_single_sender` asserts
`len(keys) == 3*5` **and** `ws_keys == []` after parsing every `ws.send` payload — a swap that
left the old loop alive would fail that assertion rather than pass it.

I do not contradict the orchestrator's headless-Chrome measurement: keyDown(text)+keyPress(text)+keyUp
yields one character in the field. The event COUNT changed 2/char → 3/char; that is the intended
AC-4 invariant ("exactly 3 per character, dispatched by exactly one sender"), not a regression.

## 5. REGRESSION — 0 failures, ruff clean, allowlist respected.

Full suite (verbatim command from the brief):
```
$ timeout 590 .venv/bin/python -m pytest tests/ -o addopts='' --no-header -q -p no:randomly \
    --ignore=tests/test_parallel_session_isolation.py
2805 passed, 1 skipped, 8 xfailed, 32 xpassed, 35 warnings in 303.67s (0:05:03)
[exited with code 0]
```
Baseline was 2796 passed / 0 failed / 8 xfailed / 32 xpassed / ~307 s. Now **2805 passed,
0 failed**, same 8 xfailed / 32 xpassed, 303.67 s (no wall-clock explosion — the new tests stub
`sleep`; AC-3/4/5 need no real inter-key gaps). 2805 = 2796 + 9 new engine tests
(`tests/test_behavioral_engine.py` 13 → 22). The `1 skipped` is environmental and pre-existing
(`tests/test_core.py:102` `skipif(CHROME_RUNNING)` / `tests/test_mcp_live_e2e.py:62` live-service
marker), not caused by this diff.

ruff (note the brief's typo guard — the real path is `tests/test_behavioral_engine.py`):
```
$ .venv/bin/python -m ruff check src/behavioral_engine.py tests/test_behavioral_engine.py
All checks passed!
```
The previous gate's 2 ruff errors are gone.

Allowlist: **respected.** The swap commit 71abe6d touches exactly `src/behavioral_engine.py`
and `tests/test_behavioral_engine.py`. `git diff 50de71d..HEAD --name-only` lists a third file,
`analysis/next-moves.md`, but that belongs to the orchestrator's own loop-record commit 8cd91a0
("chore(loop): iteration 3 stopped"), not to the developer's swap — naming it so it is not
attributed to the wrong dispatch.

### Previous findings F1/F2/F3 — re-measured, all three genuinely fixed

```
$ timeout 300 .venv/bin/python -m pytest tests/test_behavioral_engine.py -o addopts='' --no-header -q -p no:randomly
22 passed in 2.43s
$ pytest … -k "behavioral_typing or three_events or backspace or speed_factor or raw_mode"
6 passed, 16 deselected in 1.05s        # AC-3: N>=5 required
```

**F1 — CORRECT, not merely passing.** `_dispatch_char_sequence` is decorated
`@staticmethod` (`src/behavioral_typing.py:336-337`) and the production call site is
`await self._dispatch_char_sequence(client, char, delay_before)` (`:189`) — three arguments.
The test now resolves the real function *before* the patch (`orig_seq =
BehavioralTyping._dispatch_char_sequence`, `tests/test_behavioral_engine.py:274`) and re-patches
with `staticmethod(_record_seq)`. That is the correct inverse: on a staticmethod, class
attribute access yields a plain 3-arg function (no implicit `self`/`c` injection), so both
`orig_seq(c, char, 0.0)` and the patched `self._dispatch_char_sequence(client, char,
delay_before)` are arity-correct. The old 4-arg TypeError cannot recur. The test also asserts
`gaps == [0.0, 0.0]`, which is falsifiable (raw mode must emit no inter-key delay).

**F2 — the fix silences the linter, but I DISAGREE with the stated reason.** The comment reads
`import asyncio  # noqa: F401 — patch("asyncio.sleep", ...) resolves it by name`. That reasoning
is factually wrong: `mock.patch`'s target resolution splits `"asyncio.sleep"` and does its own
`importlib.import_module("asyncio")` — it never consults this test module's globals. So the
import is genuinely unused (`grep -n asyncio tests/test_behavioral_engine.py` returns only this
line, the `@pytest.mark.asyncio` decorators, and the `patch("asyncio.sleep", …)` strings), and
the noqa now documents a false cause for a dead import. Correct fix would be to delete the
import. **Minor, non-blocking** — it cannot fail a test or a runtime; it costs one misleading
comment and one dead line. Code-quality ding below, not a rework.

**F3 — fixed.** `tests/test_behavioral_engine.py:222-224` now reads
`vk = next(p for p in downs if p["key"] == "Backspace")["windowsVirtualKeyCode"]`; ruff is
clean, so RUF015 is gone.

**The previously-reported single suite failure — I agree it is not this swap's.**
`tests/test_behavioral_typing.py::TestDelayGenerationBehavioral::test_delays_follow_log_normal_distribution`
is an Anderson-Darling normality test at alpha=0.05 over randomly sampled log-delays, so it is
inherently ~5% flaky per run. I ran it **10 times in isolation: 10 passed, 0 failed**
(2.28–2.82 s each). `src/behavioral_typing.py` is **not in this diff** (allowlist §6 forbids
touching it) and `tests/test_behavioral_typing.py` is not in the diff either, so this swap
cannot have caused it. Bisect to 7cdc515 (`feat(v1.36.12): implementalja a behavioral typing
core-t`, which is the commit that introduced `src/behavioral_typing.py`) is **plausible and
consistent** with everything I measured — though I did not re-run `git bisect` myself, so I
record the bisect as *corroborated, not independently reproduced*. Today's full-suite run is
green, so this is a latent flake, not a live failure. Worth a separate dispatch: an alpha=0.05
statistical assertion in CI will redden the pipeline at ~5% frequency regardless of this swap.

---

## SCORE TABLE

| Dimension | Weight | Score | Evidence |
|---|---|---|---|
| Correctness | 30% | **5** | boundary exactly as spec §1/§5; old loop + `_send_key_event` both absent (grep exit 1); `:191-212` intact; `_sim` still at `:90`/`:116`; 2805 passed / 0 failed |
| Test coverage | 20% | **5** | 9 new engine tests, all falsifiable; 22 passed; AC-3 selector 6 passed (≥5 required); every new assertion can fail (event counts, key lists, gap lists, CPM ints) |
| Spec compliance | 20% | **5** | AC-1 import ✓, AC-2 exit 1 ✓, AC-3 6 passed ✓, AC-4 `15 expected 15 (_send_command=15 ws.send=0)` ✓, AC-5 `6 expected 6` ✓, AC-6 `140 245` ✓; allowlist honoured; no invented UI |
| Code quality | 15% | **4** | typed, single path, no facade, dead sender removed — ding for F2: a dead `import asyncio` kept alive by `# noqa` with an incorrect justification (`patch()` imports the module itself; it does not resolve test-module globals) |
| Evidence | 15% | **4** | commit `71abe6d` + full suite + ruff both re-run by me; **not pushed** (`main` is 2 ahead of `origin/main`) and no CI — correct per method §1 (push is the orchestrator's call, after review), so this is not the developer's omission, but the push is not yet done |

Weighted: 5(.30) + 5(.20) + 5(.20) + 4(.15) + 4(.15) = **4.70 / 5.0**

APPROVE 4.7/5 — the swap is exactly the boundary SPEC-003 specified, all four surviving
behaviours and all six ACs measure green, the full suite is 2805 passed / 0 failed with ruff
clean, and the three findings from the previous REWORK run are genuinely fixed (F1 correctly,
F3 correctly, F2 silenced with a wrong reason — a one-line cosmetic debt, not a gate).

Non-blocking follow-ups for a later dispatch (not rework, and I did not touch them — I am
read-only and wrote no repo file): (1) delete the unused `import asyncio` at
`tests/test_behavioral_engine.py:3`; (2) the alpha=0.05 normality flake in
`tests/test_behavioral_typing.py`, introduced by 7cdc515, will redden CI ~5% of runs; (3) the
CHANGELOG note for the user-visible ~1.5–2x typing speed change and the loss of simulated typos
is still owed (spec §6 flagged it for the orchestrator, correctly not to the implementer);
(4) **the brief's "uncommitted working-tree diff" premise is false and should be corrected in
the next dispatch** — `git diff` on this repo is empty and would have scored an empty change.

REPORT LOCATION / DURABILITY: this report is at `/tmp/dispatch-log/bh-gate-3.md` as the brief
required, which is a `$TMPDIR`-area path and therefore a 72-hour lease, not a durable record.
I cannot remedy that: the reviewer contract makes me write and commit nothing, and my tool grant
has no Write/Edit. **Orchestrator: copy this file into
`/home/zoltan/browser-helper/.agent-pipeline/audit/` and commit it with the gate record**, or
the reasoning behind this score will not survive this week.

SCORE: 4.7/5.0  (SHIP, boundary matches SPEC-003 exactly; 2805 passed / 0 failed, ruff clean, all six ACs green)
