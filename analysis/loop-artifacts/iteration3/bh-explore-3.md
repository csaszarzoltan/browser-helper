dispatch:  inline scout brief (engine-swap verification, no brief file supplied)
agent:     explore
repo:      /home/zoltan/browser-helper @ 039001b
brief:     not attempted - no brief file path was supplied, dispatch text was inline
verdict:   none - first pass
status:    DONE - all 7 items answered with measured evidence below

ONE QUESTION: single highest-value next change + concrete evidence.

1. Highest-value next change (one item)
CONFIRM the queued candidate: route `BehavioralEngine.type_text` through the
now-implemented `BehavioralTyping` module instead of the legacy
`BehavioralSimulator.keystroke_timing`. This independently confirms the queue
(`analysis/next-moves.md` Iteration 3 CANDIDATE). It is the right next change
because v1.36.12 built the module, v1.36.13 fixed its delay convention (N-1)
and `_compute_cpm`, and the production typing path still calls the old timer —
so the two shipped commits deliver zero production effect until this swap lands.
No higher-value competing item was found (see item 4/7 for what was ruled out).

2. Exact file and line range it touches
`src/behavioral_engine.py`:
- lines 22-23 (imports: `from behavioral_sim import BehavioralSimulator...`;
  `BehavioralTyping` is not imported at all)
- lines 176-229 (`async def type_text`), specifically line 199:
`keystrokes = self._sim.keystroke_timing(text, wpm_range=self._profile.wpm_range)`
Likely also the per-keystroke loop that follows (dwell/flight sleeps,
shift handling, keyUp pairing, `speed_factor` scaling), which overlaps the
new module's dispatch logic and must be reconciled, not duplicated.
New module API for reference: `src/behavioral_typing.py:101`
(`class BehavioralTyping`), `type_text(text, mode="human", client=None)`.

3. Evidence the problem is REAL TODAY (commands I ran + pasted output)
Command A (introspection, PYTHONPATH=src):
```
$ PYTHONPATH=src python3 -c "
import inspect
from behavioral_engine import BehavioralEngine
src = inspect.getsource(BehavioralEngine.type_text)
print('calls keystroke_timing:', 'keystroke_timing' in src)
print('mentions BehavioralTyping:', 'BehavioralTyping' in src)
import behavioral_engine as m
print('BehavioralTyping attr in module:', hasattr(m, 'BehavioralTyping'))
from behavioral_typing import BehavioralTyping
print('BehavioralTyping.type_text sig:', inspect.signature(BehavioralTyping.type_text))
"
calls keystroke_timing: True
mentions BehavioralTyping: False
BehavioralTyping attr in module: False
BehavioralTyping.type_text sig: (self, text: 'str', mode: 'str' = 'human', client: 'Any' = None) -> 'dict[str, Any]'
EXIT:0
```
Command B (grep, engine + routes):
```
$ grep -n "BehavioralTyping\|behavioral_typing\|TypingConfig\|type_text_human\|human_type" src/behavioral_engine.py src/main.py
src/main.py:652:class TypingConfigRequest(BaseModel):
src/main.py:2811:    from behavioral_typing import TypingConfig
... (all hits are the /typing/config REST endpoints in main.py; zero hits in behavioral_engine.py)
$ grep -rn "keystroke_timing" src/ tests/
src/behavioral_engine.py:199:        keystrokes = self._sim.keystroke_timing(
src/behavioral_sim.py:13:    keys = BehavioralSimulator.keystroke_timing("Hello, world!")
src/behavioral_sim.py:254:    def keystroke_timing(
tests/test_behavioral_sim.py: ... (13 hits, old-timer tests)
```
Command C (item-5 failing proof, exits non-zero — see item 5).
Supporting: `tests/test_behavioral_engine.py` contains 13 tests, all passing,
and zero references to BehavioralTyping (grep exit 1) — the old path is
tested, the swap is untested.

4. Is it already done? NO. Checked three ways:
(a) `git log --grep` over history:
```
$ git log --format='%h %s' --grep='typing' -i -50 | head
97afc47 fix(v1.36.13): a gepelesi kesleltetes konvencioja legyen N-1, es a cpm formula valos
7cdc515 feat(v1.36.12): implementalja a behavioral typing core-t (P1-3)
00f704f release: v1.27.2 — /type 404, behavioral no-blind-typing, MCP unwrap ...
$ git log --format='%h %s' --grep='engine swap' -i -50 | head
039001b chore(loop): iteration 2 record — v1.36.13 shipped, engine swap unblocked
(only the loop-record mention; no implementation commit)
$ git log --format='%h %s' --grep='keystroke' -i -50 | head
(empty)
```
(b) CHANGELOG.md explicitly defers it:
```
26:- **Nem ebben a commitban:** a `behavioral_engine.py:199` swap (következő item).
42:  A `behavioral_engine.py` swap a KÖVETKEZŐ commit ...
```
(c) `analysis/next-moves.md` Iteration 3 status: "candidate, awaiting the
step-2 agents' independent answers", "who: not yet dispatched". No other
analysis/*.md file mentions an engine swap (grep over analysis-brief.md,
architecture-brief.md, mcp-reference-analysis.md, research-brief.md: no hits).
Ruled out as competing next-changes: remaining `NotImplementedError` hits are
abstract base methods (`browser_providers/base.py:50-89`), stale docstrings
on already-implemented modules (`behavioral_scroll.py` — verified
`scroll raises NIE: False`, methods `_smooth_scroll/_jagged_scroll/_auto_mode`
all present), and legacy stub docstrings (`session_manager.py:4`,
`anti_detection/compositor.py:4` docstring-only, not verified line-by-line —
see item 7). No TODO/FIXME/XXX/HACK hits in src/ (grep exit 1).

5. What test or command would fail today because of it
No existing test covers the swap (established by grep: `BehavioralTyping`
appears 0 times in `tests/test_behavioral_engine.py`, grep EXIT:1), so no
checked-in test fails — the gap is UNTESTED, not test-guarded. The exact
command that exits non-zero today:
```
$ PYTHONPATH=src python3 -c "
import inspect
from behavioral_engine import BehavioralEngine
src = inspect.getsource(BehavioralEngine.type_text)
assert 'BehavioralTyping' in src, 'FAIL: BehavioralEngine.type_text does not route through BehavioralTyping (still uses BehavioralSimulator.keystroke_timing)'
"
Traceback (most recent call last):
  File "<string>", line 5, in <module>
AssertionError: FAIL: BehavioralEngine.type_text does not route through BehavioralTyping (still uses BehavioralSimulator.keystroke_timing)
EXIT:1
```
Adjacent passing baseline (proves old path is green, so a swap regression
would be distinguishable):
```
$ python3 -m pytest tests/test_behavioral_engine.py -p no:xdist -q -o addopts=''
.............                                                            [100%]
13 passed in 3.36s
EXIT:0
```
(note: `-o addopts=''` override needed because pyproject sets `-n auto` and
this host lacks the xdist plugin for direct `-p no:xdist` runs; the repo's own
runner uses `-n auto`.)

6. If the change is the engine swap, what could go WRONG that v1.36.12/v1.36.13 did not face
Concretely, five reconciliation risks (all from reading both sides, none faced
by the last two commits because those touched only the standalone module):
(a) Typo/backspace model silently dropped. Old path (`behavioral_sim.py:254+`)
injects `"\b"` corrections at ~5% probability (crc32-seeded); new module
(`behavioral_typing.py`) maps `"\b"` only as a named key (`_NAMED_KEYS`, line
35) and generates zero typos (grep for typo/backspace in behavioral_typing.py:
1 hit, the key table). A naive swap deletes typo simulation from production
typing with no test noticing.
(b) Timing-model discontinuity. Old: dwell/flight distributions scaled from
WPM 40-80; new: log-normal inter-key delays calibrated to CPM 200-400.
`HumanProfile.wpm_range` has no defined mapping to `TypingConfig.cpm_min/max`
— shipping the swap changes real typing speed with no calibration.
(c) Double-delay / dropped concerns in the loop. The engine's loop does
click-to-focus, per-char shift detection, explicit keyDown/keyUp pairing, and
`speed_factor` scaling. `BehavioralTyping.type_text` dispatches its own
keyDown/keyPress/keyUp sequence with its own delays. Wiring one inside the
other without deleting one side double-sleeps every keystroke; deleting the
wrong side drops focus-click, shift modifiers, or `speed_factor`.
(d) Two config sources with no precedence. `HumanProfile` (wpm_range,
typo_rate, speed_factor, enabled) vs `TypingConfig` (enabled, cpm_min,
cpm_max, owned by `/typing/config` state in main.py:2808-2848). Both have an
`enabled` flag; a disabled state in one but not the other is undefined.
(e) `BehavioralTyping.type_text(..., client=None)` generates delays but
dispatches nothing — if the swap passes no client (or the wrong client
handle vs the engine's `self._client` + `_send_key_event`), production typing
becomes a timed no-op that still returns `{"status": "ok"}`.

7. What I did NOT get to examine (budget: used ~8 of 10 min, no timeout hit)
- NOT CHECKED (out of scope for the one question): full test suite
(ran only `tests/test_behavioral_engine.py`, 13 passed; typing/sim suites not
executed), MCP-server wiring for typing beyond main.py routes, live-CDP
dispatch behavior of the new module, performance effect of log-normal delays.
- NOT CHECKED (seen but not classified): whether `session_manager.py` and
`anti_detection/compositor.py` stub docstrings ("all ... methods raise
NotImplementedError") are stale like `behavioral_scroll.py`'s was, or live
gaps — each needs its own import-and-inspect run.
- NOT CHECKED: `capability_registry.py:84` still advertises
"explicit NotImplementedError paths" for scroll/typing — stale after v1.36.12?
One grep + one import would settle it; not run.
- NOT CHECKED: exact `type_text` line-range end (cited 176-229 from the
150-260 window read; the scroll section starts after `_send_key_event`, so the
range is approximately right but not re-verified to the closing line).
