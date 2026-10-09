# bh-tester-8 — iteration 8 shipped-slice verification

```
dispatch:  inline prompt
agent:     tester
repo:      /home/zoltan/browser-helper @ b379d36  (tested code SHA e59e289 = v1.36.21; b379d36 is docs-only on top)
brief:     sha256:5993369427f8
verdict:   none - first pass
status:    DONE — all 4 items measured; item 4 count differs from brief (73 vs 76), see below
```

Slice: live typing integration gate (`tests/test_typing_live_integration.py`) + no-regression check on normal suite + behavioral_typing/pacing slice.

## Item 1 — live file collects as 3 tests and passes live; skipped when service down?
STATUS: YES (collects 3; passes live; service was up, so skip-when-down path not exercised here)

```
$ .venv/bin/python -m pytest tests/test_typing_live_integration.py --collect-only -q -p no:randomly
tests/test_typing_live_integration.py: 3
$ curl -s -m 3 -o /dev/null -w '%{http_code}\n' http://localhost:8000/health
200
$ .venv/bin/python -m pytest tests/test_typing_live_integration.py -o addopts='' -p no:randomly -v
test_live_typing_round_trip[a b] PASSED [ 33%]
test_live_typing_round_trip[Hello] PASSED [ 66%]
test_live_typing_round_trip[Mix 123!] PASSED [100%]
3 passed in 8.27s
```

Skip-when-service-down was not tested (service was up); marked not established.

## Item 2 — normal suite still passes without live file; including it only adds skips/passes?
STATUS: YES (2846 passed, 1 skipped, 8 xfailed with live file excluded)

```
$ .venv/bin/python -m pytest tests/ --ignore=tests/test_typing_live_integration.py -q -p no:randomly -o addopts='' --ignore=tests/parallel_session_isolation.py
2846 passed, 1 skipped, 8 xfailed, 35 warnings in 299.16s (0:04:59)
```

Caveat: the `--ignore=tests/parallel_session_isolation.py` path was a guess; the prior note used `--ignore parallel_session_isolation`. Whether it matched a file was not verified. Live-file contribution to the bare count (2855 → 2858) is from the orchestrator's G1 measurement, not re-measured here.

## Item 3 — no real mock usage (AsyncMock count 0) + integration marker present?
STATUS: YES

```
$ grep -c 'AsyncMock(' tests/test_typing_live_integration.py
0
$ grep -n 'pytestmark' tests/test_typing_live_integration.py
31:pytestmark = pytest.mark.integration
```

## Item 4 — behavioral_typing + pacing slice still green (76 passed)?
STATUS: PARTIAL-MATCH — green, but 73 passed, not 76

```
$ .venv/bin/python -m pytest tests/ -k "behavioral_typing or pacing" -q -p no:randomly -o addopts=''
73 passed, 2785 deselected, 3 warnings in 13.12s
```

The brief's expected 76 is not reproduced by this selector. Cause not established: the brief may have used a different selector or count. The 3 difference was not investigated further.
