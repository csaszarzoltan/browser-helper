# next-moves — browser-helper

# Iteration 1 — 2026-10-05 — SHIPPED v1.36.12
- what: Close the `behavioral_typing` gap (P1-3) — 6× NotImplementedError in src/behavioral_typing.py, suite 29 passed +33 xfailed certified absence, POST/GET /typing/config missing
- who: explore → spec-author → developer → reviewer (gate)
- dispatch-ids: explore ticket 109 (548s, 2483B, OK), spec-author ticket 111 (1202s, 3130B, OK), developer ticket (timeout exit 2, code in tree), gate ticket 118 (1294s, 1497B, verdict APPROVE 4.5/5.0 SHIP)
- depends-on: nothing (only TODOs in src/)
- shipped: v1.36.12 @ 7cdc515 — 2788 passed 0 failed (seq 317s, measured), 68 tools, gate 4.5/5.0
- learned: version-string drift (v1.36.11 tag existed but pyproject/src/main/Dockerfile/README still 1.36.10), CHANGELOG claimed 2758 without measurement (actual 2759), behavioral_engine.py already sleeps (213/216) — brief premise "no delay" was false

# Iteration 2 — SHIPPED v1.36.13 (2026-10-05)
- what: a gepelesi kesleltetes konvencioja N-1 + valodi _compute_cpm. A reviewer talalta a v1.36.12-ben: a kod es a sajat kommentje ellentmondott, az ELSO karakter vart, N delay volt N karakterre, a _compute_cpm stub volt.
- who: reviewer (a finding) -> spec-author -> developer -> reviewer (gate)
- dispatch-ids: reviewer ticket 127, spec-author ticket 128 (5578B brief OK, wall 194s), developer ticket 131, gate ticket 132 (5.0/5.0 SHIP)
- depends-on: iteration 1
- shipped: v1.36.13 @ ab50d84 — 2796 passed 0 failed (seq 307s, measured), xfailed 12 -> 8
- learned: a binding gate a KODOT merte, a commit uzenetet senki -> a v1.36.12 uzenetem 3 NEM LETEZO metodust nevezett meg (`_randomize_cpm`, `validate_settings`, `reset`, mind 0 talalat), es a gate 4.5/5.0 SHIP-et adott mellette. Ezt a skillbe irtam.
- note: az engine swap EZERT nem lehetett eloszor — a konvencio rendezetlen volt es a _compute_cpm NotImplementedError-t dobott. Ez ELofeltetel volt, nem alternativa.

# Iteration 2 (eredeti szoveg) — SUPERSEDED a fenti item altal
- what: Behavioral engine swap — route behavioral_engine.py:176 through BehavioralTyping
- what: Behavioral engine swap — route behavioral_engine.py:176 through BehavioralTyping (currently uses behavioral_sim.keystroke_timing, alive). Spec splits this as SECOND commit because swapping working timer for previously-dead makes speed regression indistinguishable from new bug.
- who: not yet dispatched
- depends-on: iteration 1 (must be green first)
- status: queued, not started

# Iteration 3 — SHIPPED v1.36.14 + v1.36.15 + v1.36.16 (2026-10-05)
- SHIPPED: v1.36.14 @ e7fde1a (engine swap, gate 4.7/5.0 SHIP) + v1.36.15 @ 7ed30f3 (hotfix) + v1.36.16 @ 7c4df52 (docs)
- ARTIFACT-CLASS DEFECTS THIS LOOP (4, all same shape — code right, claim wrong): v1.36.11 tag vs 1.36.10 code; v1.36.12 commit msg naming 3 nonexistent methods; README badge 2630 vs 2796; docstrings still asserting keyDown+keyPress+keyUp after the dispatch was removed. Countermeasure is a grep, not a stricter gate — no reviewer scoring src/ reads a CHANGELOG line or a docstring param list.
- THE HOTFIX WAS MANDATORY: v1.36.14 was BROKEN IN PRODUCTION. Live /type -> HTTP 400, input.value 'h' (1 of 11 chars).
  Two real CDP defects, both invisible to the mocked tests and to the 4.7/5.0 gate:
    (a) `keyPress` is NOT a valid Input.dispatchKeyEvent type (valid: keyDown/keyUp/rawKeyDown/char) -> Chrome -32602, result discarded so the error was SILENT.
    (b) `text=null` is "Invalid parameters" (CDP types text as string, not nullable) -> EVERY SPACE aborted the call.
  Fixed both. Live re-verification: 'hello world' / 'a b c' / 'UPPER' / 'a!b' / 'x1y2' / 'Mix 123!' ALL PASS.
- LESSON (goes in the skill): a mocked CDP client accepts ANY payload. 2805 green tests + a 4.7/5.0 binding gate coexisted with a dead production typing path. Any change that speaks a real wire protocol needs a LIVE end-to-end check.
- MY OWN ERROR: an earlier in-iteration "measurement" that keyPress does not double the character was CONTAMINATED — taken while Chrome was already rejecting keyPress, the rejection swallowed the event. Re-measured clean: char+text genuinely doubles ('aa'); keyPress is simply invalid. A measurement taken on a broken system measures the breakage.
- NEW GUARD TESTS: 2-event sequence pinned, `keyPress` banned, text never null. 89 passed on the two touched files.

# Iteration 3 (korabbi allapot) — STOPPED, GATE OPEN @ local 71abe6d
- what: engine swap — a produkcios ut a `self._typing.type_text`-et hivja (`src/behavioral_engine.py:212`)
- who: explore + reviewer (both named it) -> spec-author (bh-spec-3.md) -> developer (ticket 146) -> reviewer gate (ticket 155, 3.2/5.0 REWORK)
- GATE HISTORY: 3.2/5.0 REQUEST-CHANGES named 3 test-only defects (all in the developer's OWN new test file): F1 :274 staticmethod monkeypatch -> TypeError; F2 :3 F401; F3 :222 RUF015. The gate's own words: "Production src/behavioral_engine.py is correct ... failures are test-only."
- FIXED in this iteration: all 3. Measured after: tests/test_behavioral_engine.py 22 passed, ruff clean, test_behavioral_engine+typing 88 passed, full suite 2804 passed / 1 failed (flaky AD test, bisected to 7cdc515)
- STALL: the re-gate (ticket 158) NEVER STARTED — 2055s in the global queue, no ledger row, 3 consecutive gateway stalls this item (151, 3b, 158). Per skill 6b step 4: stopped, did not re-ask.
- NOT SHIPPED: no >=4.0 verdict exists for the shipping tree, and a failing gate returns the item to BUILD rather than authorising my own score. Work kept LOCAL at 71abe6d; main untouched.
- NEXT SESSION: re-dispatch the gate on 71abe6d (brief /tmp/dispatch-log/brief-gate-3.txt, already updated with the 3 fixes named). If it returns >=4.0 SHIP: bump to v1.36.14, CHANGELOG, tag, release, restart, verify /health. Do NOT re-derive the item.
- MEASURED EARLIER THIS ITEM (do not re-test): keyPress with text does NOT double the character — live throwaway Chrome on 9558, keyDown(text)+keyPress(text)+keyUp -> 'a' len=1.
- STILL OPEN, separate items: TWO flaky tests (same RNG family), both bisected to pre-existing and 10/10 green in isolation: tests/test_behavioral_typing.py::test_delays_follow_log_normal_distribution (Anderson-Darling alpha=0.05) and tests/test_behavioral_simulation.py::test_bezier_non_linear_velocity (file byte-identical at HEAD, md5 e057bd8f145071101558335a1fce8536). REPLACE THE FLAKY GATES, do not widen tolerances blindly. (Anderson-Darling alpha=0.05 over 500 samples; 10/10 isolated pass, fails in full-suite runs depending on RNG order).

# Iteration 3 (eredeti fejlec) — IN PROGRESS
- what: `src/behavioral_engine.py:199` swap — a produkcios gepelesi ut atkotese a BehavioralTyping modulra
- who: explore (CONFIRMS) + reviewer (3rd artifact defect) -> spec-author DONE (bh-spec-3.md, 4173B, wall 1316s)
- spec decisions: boundary = lines 198-216 deleted, no fallback; shift/Backspace owner = BehavioralTyping; speed = TRANSLATED (cpm = wpm*5*speed_factor); disabled = MODE_RAW 3-event sequence
- allowlist: src/behavioral_engine.py + tests/test_behavioral_engine.py
- ORCHESTRATOR MEASUREMENT (live Chrome, throwaway instance on 9558): a keyPress TEXT-tel NEM duplikal — keyDown(text)+keyPress(text)+keyUp -> len=1; keyDown(text)+keyUp (regi ut) -> len=1. A dupla-bevitel kockazata NEM valos.
  MERESI MODSZER: headless Chrome kulon porton + nyers websockets a page targetre, Input.dispatchKeyEvent, majd Runtime.evaluate az input.value-ra.
- NEXT: developer (build), then binding gate

# Iteration 3 (eredeti kerdes) — ANSWERED by both agents: yes, the engine swap
- what: `src/behavioral_engine.py:199` swap — a produkcios gepelesi ut atkotese a BehavioralTyping modulra. MOST MAR BLOKKOLATLAN: a N-1 konvencio rendezve, a _compute_cpm implementalva, tehat a swap nem fut a 4 strict xfail-ba es nem kell ujra donteni a konvenciot.
- who: not yet dispatched — ASK-on kell atmennie, nem orokolheto
- depends-on: iteration 2
- status: candidate, awaiting the step-2 agents' independent answers
