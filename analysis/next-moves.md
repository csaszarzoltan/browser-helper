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

# Iteration 3 — IN PROGRESS (2026-10-05)
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
