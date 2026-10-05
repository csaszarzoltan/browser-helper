# next-moves — browser-helper

# Iteration 1 — 2026-10-05 — SHIPPED v1.36.12
- what: Close the `behavioral_typing` gap (P1-3) — 6× NotImplementedError in src/behavioral_typing.py, suite 29 passed +33 xfailed certified absence, POST/GET /typing/config missing
- who: explore → spec-author → developer → reviewer (gate)
- dispatch-ids: explore ticket 109 (548s, 2483B, OK), spec-author ticket 111 (1202s, 3130B, OK), developer ticket (timeout exit 2, code in tree), gate ticket 118 (1294s, 1497B, verdict APPROVE 4.5/5.0 SHIP)
- depends-on: nothing (only TODOs in src/)
- shipped: v1.36.12 @ 7cdc515 — 2788 passed 0 failed (seq 317s, measured), 68 tools, gate 4.5/5.0
- learned: version-string drift (v1.36.11 tag existed but pyproject/src/main/Dockerfile/README still 1.36.10), CHANGELOG claimed 2758 without measurement (actual 2759), behavioral_engine.py already sleeps (213/216) — brief premise "no delay" was false

# Iteration 2 — PENDING
- what: Behavioral engine swap — route behavioral_engine.py:176 through BehavioralTyping (currently uses behavioral_sim.keystroke_timing, alive). Spec splits this as SECOND commit because swapping working timer for previously-dead makes speed regression indistinguishable from new bug.
- who: not yet dispatched
- depends-on: iteration 1 (must be green first)
- status: queued, not started

# Iteration 3 — CANDIDATE (needs ASK verification)
- what: (awaiting next ASK — explore+reviewer disagreement is output)
- status: not yet proposed
