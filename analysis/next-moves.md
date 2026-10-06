# Iteration 6 — SHIPPED v1.36.19 (2026-10-05): DEFECT-001 repo-root pytest collection

- what: a repo-gyokerben futtatott `pytest` collectaljon. Elotte: `2849 collected, 2 errors,
  Interrupted` — harom honapja (29da9ee, 2026-08-14). Ok: nincs `tests/__init__.py`, a ket
  gyoker-duplikatum ugyanazon a modulneven importalodik (`import file mismatch`).
- SHIPPED: v1.36.19 @ ed4b201, tartalom 13ac740.
- FIX: (a) `git rm test_rate_limiter.py test_proxy_pool_enhanced.py` (gyoker), (b)
  `testpaths = ["tests"]` a `pyproject.toml:40`-be. **(c) `tests/__init__.py` SZANDEKOSAN NEM:**
  ~2800 teszt import-rezsimjet billentené, es egyedul hagyva MINDKET peldanyt collectalhatova
  teszi -> visszahozna a flaky `kstest` orakulumot. A reviewer fuggetlenul ugyanerre jutott.
- **A claim tulelte a kodot, FAJL-SZINTEN:** a torolt gyoker-`test_rate_limiter.py` (431 sor) meg
  MINDIG a regi, flaky `kstest(p > 0.05)` orakulumot tartalmazta (`:240-252`), amit a v1.36.18
  epp lecserelt a `tests/` peldanyban (512 sor). Semmi egyedi, meg kivant tartalom nem veszett el
  (a proxy-par byte-identikus volt, `md5 a2dc186a...`; a rate_limiter 43/43 tesztneve megvan).
- MERVE: A1 `git ls-files | grep '^test_.*py$'` -> ures; A2 `testpaths = ["tests"]`; A3 bare-root
  collect `2849 collected, 0 error, exit 0`; A4 scoped kapu `2806 passed, 0 failed`; BONUS a teljes
  bare-root futas `2808 passed, exit 0` (elotte el sem indult).
- A `DEFECT-001` fajl HAROM elavult allitasa javitva (a reviewer merte): (1) a "byte-identical"
  mar csak az egyik parra igaz; (2) a Chrome-guard **MAR javitva `38e9def`-ben** — nem javitottuk
  ujra; (3) a "two failing tests" valojaban skip. Status: fixed.
- GATE-6: **APPROVE 5.0/5.0** (5·5·5·5·5). A gate fuggetlenul igazolta a scope-ot (4 fajl, +23/-1373),
  a tartalmat (43/43 tesztnev) es hogy a `tests/__init__.py` kihagyasa helyes.
- A developer artifactja 58B reszleges riport volt ("All four edits are in. Now running the
  acceptance checks.") — a diff dontott, az orchestrator futtatta ujra es vette at. Ez a skill
  "a short artifact is not a stall — diff the target files" szabalyanak a gyakorlata.
- OPEN VERDICT: `v20261005134000-741226` MARAD NYITVA (a v1.36.17 mockolt-suite hibat nevezi; a
  live-check klauzula egy modszertani item, nem ez az iteracio).
- status: CLOSED. Kovetkezo jelolt: nincs (lasd lent).
- MEGJEGYZES a stop-feltetelrol: az ASK-ot a DEFECT-001 JAVITASA UTAN meg NEM futtattuk ujra,
  tehat a loop nem mondhatja ki, hogy "nincs tovabb munka" — az csak egy uj ASK-korbol derulne ki.

## Iteration 5 — SHIPPED v1.36.18 (2026-10-05): a harmadik es negyedik probabilisztikus gate

- what: `tests/test_rate_limiter.py:240-268` — a ket single-draw KS-orakulum cserelje pinnelt-huzas
  determinisztikus kapura (`test_uniform_distribution_ks_test`, `test_log_normal_distribution_ks_test`).
- SHIPPED: v1.36.18 @ 4b29204, tartalom 507fd61. Test-only, egyetlen fajl.
- MERES (orchestrator, HELYES kodon): uniform 10/200 = 5.0% elutasitas = a kstest sajat alpha-ja;
  log-normal 1/200, plusz Lilliefors-hibas (a parametereket a tesztelt mintabol becsli) -> a p-erteke
  ERVENYTELEN, nem csak flaky. A `:245` komment olyan pinninget irt le, ami nem letezett.
- A REGI orakulum VAKSAGA bizonyitva: a rendezett-linear sorozaton `KS p=1.0000` — ATENGEDTE volna.
- RateLimiter ELESBEN terhelt: `src/cdp_client.py:132` epit, `:665` hiv a `_send_command`
  human-pacing utjan, API `/rate/config` + MCP `rate_limiter_status` -> nem dead code.
- ASK: explore + reviewer FUGGETLENUL ugyanezt nevezte meg -> magas konfidencia.
- SPEC-5: `docs/specs/SPEC-5-deterministic-rate-limiter-gates.md` (15689B). 5 interpretaciot nevesit.
- GATE-5: **APPROVE 4.8/5** (5·5·5·5·4). A gate MAGA alkalmazta az M1 mutanst in-place, `1 failed`
  a lag-1 assertion-nel, es a restore md5-je (`100d90b4...`) FUGGETLENUL egyezett az enyemmel.
  A teljes suite-ot is ujrafuttatta: 2806 passed. Az egyetlen levonas a `tester` kimaradasa, amit
  LEGITIMNEK itelt (test-only valtozas, nincs wire-protokol felulet).
- TELJES SUITE A CSERE UTAN: `2806 passed, 0 failed` — a loop egyetlen piros teszje megszunt.
- BRIEF-DEFECT (a spec kapta el es az orchestrator visszavonta): a briefbe "orchestrator merte"-kent
  irt 2000-seed szam (70.15) VALOJABAN az `explore` szama volt. Sajat sweep + a spec fuggetlenul:
  91.79/34.26. A 70.15-ot VISSZAVONTAM; a +-150/+-80 tolerancia igy is tart (58ms margin).
- DEFECT-001 (repo-root pytest collection): meg NYITOTT, a kovetkezo jelolt. A `explore` egy elavult
  reszletet is talalt benne: a ket duplikatum mar NEM byte-identical (a `tests/` peldany visz egy
  defaults-reset hunket `:404`-nel), tehat "torold a root duplikatumot" elott `cmp` kell.
- OPEN VERDICT: `v20261005134000-741226` (a v1.36.17 mockolt-suite hibat nevezi) MARAD NYITVA — ez az
  iteracio mas hibat javitott. Ne zarja le, aki ezt olvassa, amig a live-check klauzula nincs bent.
- CLOSED.



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
- STALL: KORRIGALT — a re-gate (ticket 158) IDOKOZBEN LEFUTOTT. A "soha nem indult el" feljegyzesem teves volt: ~40 percen at 0 B-t lattam minden pollnal (a queue-vara, nem halott dispatch), de az artefakt befejezodott. A korrigalt verdikt-sorozat lentebb: 3.2 -> 5.0 -> 4.7. A pollozott 0 B NEM bizonyitek; a ledger sor az.
- SHIPPED (KORRIGALT): v1.36.14 @ e7fde1a + v1.36.15 @ 7ed30f3 + v1.36.16 @ 7c4df52. A korabbi "NOT SHIPPED" feljegyzes teves volt — a gate 5.0/5.0-t (ticket 158, gate-3b) es 4.7/5.0-t (gate-3c) adott a szallitando fara. A 71abe6d lokalis WIP-commit elveszett/kiveult a force-reset-ig; a tartalma a fenti commitokban el.
- NEXT SESSION: NE csinald ujra. A gate lefutott es a release megtortent (v1.36.14..v1.36.16). Aki ezt olvassa: a fenti "NEXT SESSION: re-dispatch" utasitas ELAVULT, ne hajtsd vegre.
- MEASURED EARLIER — KORRIGALT, a meres KONTAMINALT volt: azt "mertem", hogy a keyPress nem duplazza a karaktert. A Chrome mar elutasította a keyPress-t (-32602), az elutasitas elnyelte az esemenyt, igy len=1 lett ROSSZ okbol. Tiszta eldobhato Chrome-on ujramer ve: a keyPress ERVENYTELEN CDP-tipus, es a keyDown(text)+char(text) VALOBAN duplaz ('aa'). A helyes sorozat keyDown+keyUp. Egy torott rendszeren vett meres a torest meri.
# Iteration 4 — SHIPPED v1.36.17 (2026-10-05): the two flaky gates replaced
- SHIPPED: v1.36.17 @ 73b5d52. Both probabilistic gates replaced, no production code touched.
- MEASURED BEFORE: log-normal gate 5/200 (2.5%) rejections and bezier gate 13/500 (2.6%) failures, BOTH ON CORRECT CODE. Oracle defects, not generator defects -> the fix is pinning the draw and asserting calibration, not widening a threshold.
- MEASURED AFTER: 20/20 deterministic; all 6 mutants caught (uniform/constant/exponential/sigma*3/straight-line/linear-sampling); correct code passes; 3 consecutive full suites all 2806 passed.
- NET GAIN: AD is scale-invariant, so the OLD test was blind to sigma*3 (statistic=0.2215 < 0.7510). The new calibration assertions catch it. Tolerances derived from 2000 seeds (0.02575 / 0.02204 -> 0.03 / 0.05); the spec's proposed 0.02 failed 58/1000 and would have made it worse.
- FALSE AGENT CLAIMS REFUTED BY OWN MEASUREMENT: the spec's acceptance command had a SyntaxError; its second command printed failures:24 not 0; the gate claimed bare `pytest` cannot run (measured: xdist 3.8.0 installed, 67 passed). Recorded as refuted, not "fixed".
- [CORRECTED 2026-10-05: NOT closed. The rate-limiter KS gates (`tests/test_rate_limiter.py:240-268`)
  are the same defect family and SURVIVED — measured 10/200 (5.0%) flake on correct code, the repo's
  only red test. The claim below was false; iteration 5 owns it.]
- CLOSED. This was the loop's only real remaining item; the other bisected flaky family is covered by the same fix.
- GATE-4: APPROVE 4.5/5.0 (reviewer independently reproduced 40/40 deterministic + all 6 mutants). NOTE: the agent wrote its report to bh-gate-4.out; the bh-gate-4.md the brief named was NEVER created. The whole 8167B report (all 6 items, score table, mutant table) is in analysis/loop-artifacts/iteration4/bh-gate-4.out. Durability came from the copy into the repo, not from the brief's path.
- ARTIFACT DEFECTS THIS LOOP: now SEVEN, all one shape (instruction vs delivered artifact disagree, only the artifact is real): (1) v1.36.11 tag vs 1.36.10 code; (2) v1.36.12 commit msg naming 3 nonexistent methods; (3) README badge 2630 vs 2796; (4) 3 docstrings + test header still asserting the removed keyPress; (5) spec's 0.02 tolerance claimed 0 failures, measured 58/1000; (6) gate note claiming bare pytest cannot run, measured 67 passed; (7) gate-4 report path never written. Countermeasure is a grep/sweep, not a stricter gate. (Anderson-Darling alpha=0.05 over 500 samples; 10/10 isolated pass, fails in full-suite runs depending on RNG order).

# Iteration 3 (eredeti fejlec) — SUPERSEDED, ne hajtsd vegre (a szoveg tortenelmi)
- [SUPERSEDED 2026-10-05: ez a blok IN PROGRESS-kent maradt, de az iteracio HAROM release-t szallitott
  (v1.36.14 e7fde1a / v1.36.15 7ed30f3 / v1.36.16 7c4df52). Az alabbi "NEXT: developer" utasitas ELAVULT.]
- what: `src/behavioral_engine.py:199` swap — a produkcios gepelesi ut atkotese a BehavioralTyping modulra
- who: explore (CONFIRMS) + reviewer (3rd artifact defect) -> spec-author DONE (bh-spec-3.md, 4173B, wall 1316s)
- spec decisions: boundary = lines 198-216 deleted, no fallback; shift/Backspace owner = BehavioralTyping; speed = TRANSLATED (cpm = wpm*5*speed_factor); disabled = MODE_RAW 3-event sequence
- allowlist: src/behavioral_engine.py + tests/test_behavioral_engine.py
- [REFUTED 2026-10-05: ez a meres KONTAMINALT volt — lasd a fenti KORRIGALT sort. A keyPress ERVENYTELEN
  CDP-tipus, a keyDown(text)+char(text) VALOBAN duplaz. Helyes sorozat: keyDown+keyUp. NE hasznald.]

# Iteration 3 (eredeti kerdes) — SUPERSEDED, ne hajtsd vegre (a szoveg tortenelmi)
- [SUPERSEDED 2026-10-05: a kerdes meg valaszolva, megtervezve, megbuildelve es lezarva. A "candidate,
  awaiting the step-2 agents" statusz ELAVULT — az agentek valaszoltak, a swap leszallt v1.36.14-ben.]
- what: `src/behavioral_engine.py:199` swap — a produkcios gepelesi ut atkotese a BehavioralTyping modulra.
- who: not yet dispatched — ASK-on kell atmennie, nem orokolheto
- depends-on: iteration 2
- status: candidate, awaiting the step-2 agents' independent answers
