dispatch: inline prompt (no brief file supplied; CLAUDE_BRIEF_SHA not provided by dispatcher)
agent: tester (audit of a loop this role was absent from)
repo: /home/zoltan/browser-helper @ 518cab6
brief: inline - sha256 not provided by the dispatcher
verdict: none - first pass (reviewer gates APPROVE 4.8 and 5.0 cited inline)
status: DONE — all six items answered; no commands that write were run, nothing committed

Method note: this audit ran ZERO test commands (role instruction: do not run
anything that writes — pytest creates .pytest_cache/coverage artifacts). Every
claim below is sourced to a file:line I read or a command output quoted in a
loop artifact. Where I could not measure, I wrote `not established`.

HEAD at audit time: 518cab6 (docs(loop): iteration 6 SHIPPED blokk — v1.36.19).

---

1. Would a `tester` dispatch have added verification the `reviewer` gate could not?
(Two changes; one answer each.)

v1.36.18 (`507fd61`, pinned-draw gates in `tests/test_rate_limiter.py:240-268`):
Almost none. The reviewer gate for this change (bh-gate-4, verdict line 100 of
`analysis/loop-artifacts/iteration5/bh-gate-4.out`: "REQUEST-CHANGES 3.9/5 →
corrected to APPROVE 4.5/5") did the strongest tester-like work available: it
verified the rewrite against constructed mutants IN PLACE with byte-exact
restore (mutants caught 200/200 incl. the two classes the old gate was
structurally blind to; old bare-AD rejected sigma*3 at only 7/200). The one
check I would have run that no artifact records: a repeat-run determinism
proof — `pytest tests/test_rate_limiter.py` N consecutive times asserting 0
failures — because the entire point of the change is "expected flake 0/185 =
0.00%" (bh-gate-4.out:70), and a single green run does not prove a flake rate
of zero. That is process redundancy (independent re-run), not a new
verification class.

v1.36.19 (`13ac740`, two deletions + `testpaths = ["tests"]`):
None. The gate (`analysis/loop-artifacts/iteration6/bh-gate-6.md`, APPROVE
5.0) independently re-ran exactly the tester checks: bare-root
`pytest --collect-only` ("2849 tests collected in 5.05s, no ERROR, EXIT=0")
and the full scoped suite ("2806 passed, 1 skipped, 8 xfailed, 32 xpassed,
EXIT=0"). There is no new behavior for a tester to gate beyond re-running the
suite, and the suite was re-run twice independently of the developer. The
gate-6 report says this itself (item 5: "the missing `tester` dispatch is
process debt at most, not a correctness gap"). I concur.

2. Do either of these changes touch a wire protocol?
NO to both. The skill's mocked-suite rule triggers on HTTP/CDP/WebSocket/socket
surfaces; neither change speaks one:
- v1.36.18 touches only `tests/test_rate_limiter.py:240-268`. The test
  instantiates the real `RateLimiter` with a pinned stdlib RNG
  (`rl._rng = random.Random(20260905)`, tests/test_rate_limiter.py:265) and
  asserts on sampled floats. No mock exists in the file at all (`grep -c
  AsyncMock|Mock` on tests/test_rate_limiter.py returns nothing — verified this
  audit), and no client, socket, or endpoint is imported.
- v1.36.19 touches `pyproject.toml:40` (one config line) and deletes two root
  files (`git show --name-status --format='' 13ac740` = exactly `M
  .agent-pipeline/04_defects/...`, `M pyproject.toml`, `D
  test_proxy_pool_enhanced.py`, `D test_rate_limiter.py`; quoted in
  bh-gate-6.md claim 1). Deletion + config is not a protocol surface.
Deciding lines: tests/test_rate_limiter.py:265 (pinned RNG, no transport) and
the 4-file namestatus above. The production call site `src/cdp_client.py:665`
(`delay_ms = self.rate_limiter.get_delay()`) is unchanged by both commits.

3. Is the pinned-draw gate end-to-end (get_delay IS called in production)?
Still a UNIT verification. It constructs `RateLimiter` directly, pins
`rl._rng`, draws 1000 samples in-process, and asserts distribution invariants
(shape/calibration/order) — see tests/test_rate_limiter.py:240-298. It never
imports `cdp_client`, never opens a WebSocket, never sends a command. What it
proves: the sampler draws from the calibrated distribution. What it does NOT
prove: that the sampled delay is actually applied on the send path
(`src/cdp_client.py:665-668` — `get_delay()`, then `await
asyncio.sleep(delay_ms / 1000.0)` only `if delay_ms > 0`). A unit-conversion
bug (ms vs s), a `delay_ms > 0` short-circuit, or pacing silently disabled by
config would all pass this gate while production sends unpaced.
What a `tester` would do differently: drive the live send path — instantiate
the real client against a real (or loopback-WebSocket) transport with rate
limiting enabled, issue N commands, and assert measured inter-command gaps ≥
min_delay. That is the e2e counterpart; the pinned-draw gate is its necessary
but insufficient unit half.

4. Check before accepting the deletion of two tracked test files; does loop evidence cover it?
The check: prove NO unique wanted content was deleted — (a) every test name in
each deleted file exists in its surviving twin, and (b) byte-identity (or a
diff showing only stale content) for the pairs. Commands:
`git show 13ac740^:test_rate_limiter.py | grep -c 'def test_'` (= 43, matches
the 43 in tests/test_rate_limiter.py — both counted this audit) and md5
comparison of the proxy pair (`a2dc186a7a3c7d5039fa7ede096bf5c0` on both
pre-images, per the DEFECT-001 doc and gate-6 claim 2).
YES, the loop's evidence already covers it: bh-gate-6.md claim 2 records
exactly this ("all 43 names present in tests/test_rate_limiter.py (loop over
del_names → zero MISSING). Proxy pair byte-identical"), and the commit message
of 13ac740 documents WHY the rate_limiter pair differed (root copy still held
the old flaky kstest oracle that v1.36.18 replaced — the claim outlived the
code). A tester re-running the same two commands would add redundancy only.

5. Is a gate score a substitute for the tester role?
NO. Measurement, from `analysis/reviews/post-task-review-v1.36.12-17.md:19`:
"Two production-breaking defects passed a full green suite AND two binding
gates scoring 5.0 and [4.7]" while (lines 151-155) "`POST /type`" was broken in
production. Mechanism (lines 46-50): "`BUILD → developer implements, tester
verifies, test-author writes the gate`... the loop ran none of the last two,
so the binding `reviewer` gate re-ran the developer's own mocked suite and
scored the broken tree" — 4.5–5.0 scores that "were real and about the right
files — and structurally unable to see" the defect (line 50). A gate that
re-runs the developer's own suite inherits that suite's blindness (here:
`AsyncMock(return_value={"status": "ok"})` answering `ok` to an invalid CDP
`keyPress` payload). A score grades the work it could see; the tester role
exists to look where the suite cannot — the live surface. Applied to THIS
loop: both gates are trustworthy anyway, but for the reason in items 1–2 (no
wire surface, independent re-runs) — not because 4.8 and 5.0 are high numbers.

6. The ONE test I would add in 10 minutes:
A send-path pacing integration test: enable rate limiting (e.g.
min_delay_ms=500), drive the REAL `cdp_client` send path over a loopback
WebSocket (real client + real RateLimiter + real `asyncio.sleep`, only the
socket peer faked at the frame level — no `AsyncMock` on the client), issue 3+
commands, assert every measured inter-command gap ≥ min_delay minus a small
scheduling tolerance. Defect class guarded: "correctly-sampled delay silently
not applied" — wrong time unit, `if delay_ms > 0` short-circuit, config flag
bypassing the sleep, or a refactor that moves sampling off the send path. This
is exactly the hole item 3 names: the pinned-draw gate proves the sampler, and
NOTHING in the repo proves the sleep. (Caveat, honestly held: with only the
socket peer faked this is integration, not full e2e against Chrome; full e2e
needs the live-Chrome harness that `tests/test_parallel_session_isolation.py:112-123`
guards. The proposed test is the strongest 10-minute step toward it.)

BUDGET: used a fraction of 400 s; all six items completed. `not established`:
nothing — every answer above carries a file:line or quoted command output.

Files written (deliverables only; no product code edited, no tests run, no
commit — committing is the orchestrator's decision):
- /tmp/dispatch-log/ptr2-tester.out (queue copy)
- analysis/reviews/ptr2-v1.36.18-19/ptr2-tester.md (durable repo copy, UNCOMMITTED — see note)
Note: at audit time the repo tree already contains uncommitted work I did not
write; per method §1 I staged nothing and am naming that instead of sweeping
it in. The repo copy above is left uncommitted for the orchestrator to stage by
explicit path.
