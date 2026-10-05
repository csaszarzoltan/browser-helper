# bh-review-3 — what the last two changes got wrong / left incomplete

- repo: /home/zoltan/browser-helper @ 039001b
- shipped commits reviewed: `7cdc515` (v1.36.12 feat) + `97afc47` (v1.36.13 fix) + `ab50d84` (v1.36.13 version bump)
- `ab50d84` is version-only (5 files, no product code); the substantive fix lives in `97afc47`.
- method: `git show <sha> --stat`, `git show <sha>` diff, `grep -rn` for callers, targeted `pytest -k TestComputeCpmBehavioral`.
- verdict on the question: the N-1/`_compute_cpm` fix is real and gated, but it leaves one dead-code inconsistency, one untested no-client path, and a stale badge in the version-bump commit itself.

## 1. Single most concrete weakness in `ab50d84`

`ab50d84` touches zero product code — `git show ab50d84 --stat` lists only
`CHANGELOG.md`, `Dockerfile`, `README.md`, `pyproject.toml`, `src/main.py`
(version string). Its most concrete self-contained defect is a stale test-count
badge left in the same diff that claims the new count:

- `README.md:5` still reads `![Tests](.../tests-2630%20passed-brightgreen)` (and
  `README.md:482` still says "Current state: **2630 tests passing** historically").
- `CHANGELOG.md:24` (added by this same commit) claims "**2796 passed, 0 failed**
  (szekvenciális, 307s, mérve), xfailed 12 → 8".
- `src/main.py:308` bumps `version="1.36.13"` but no badge/count line is updated.

Evidence (pasted output):

```
README.md:5:![Tests](https://img.shields.io/badge/tests-2630%20passed-brightgreen)
README.md:482:Current state: **2630 tests passing** historically; the fast gate used per release is
CHANGELOG.md:24:  **2796 passed, 0 failed** (szekvenciális, 307s, mérve), xfailed 12 → 8.
```

So the commit that announces "2796 passed" keeps advertising "2630 passed" two
files away. Weakness class: stale gate badge in the release commit itself.

A second, process-level weakness in `ab50d84` (cited, not counted as the "single"
one): anyone running `git show ab50d84` sees no fix at all — the real product
change is the sibling commit `97afc47` (`src/behavioral_typing.py` + tests). A
review scoped to the tag commit alone reviews nothing.

## 2. Is zero-sleep for `type_text("a")` correct? (N-1 convention)

YES, zero sleeps / `total_delay_ms == 0` for a 1-char string is the documented
N-1 convention, and NO — I found no caller and no test that expects a wait
proportional to one character.

What I checked:

- `src/behavioral_typing.py:217-218`: `if char_count <= 1: return []` — 1 char
  yields zero gaps by construction.
- `src/behavioral_typing.py:184-190`: the dispatch loop does
  `delay_before = 0.0 if index == 0 else delays[index - 1]` and
  `total_delay += delay_before`, so a single char contributes exactly `0.0`.
- `src/behavioral_typing.py:349-350`: `_dispatch_char_sequence` skips sleep when
  `delay_before <= 0`, so zero gaps = zero `asyncio.sleep` calls.
- Test expectation agrees: `tests/test_behavioral_typing.py:546-547`
  (`test_generate_delays_one_char_returns_empty`) asserts
  `typing._generate_delays(1) == []`.
- Caller grep for production use of `BehavioralTyping.type_text`:
  `grep -rn "type_text" src/` returns only `src/cdp_client.py:1966`
  (`return await self._behavioral.type_text(selector, text)`),
  `src/behavioral_engine.py:176` (a *different* `type_text(selector, text)`),
  `src/main.py:3224,6430` and `src/mcp_server/tools.py:148,1501` (all
  `client.type_text(selector, text)` on `CDPClient`, not `BehavioralTyping`).
  **Zero production call sites** invoke `BehavioralTyping.type_text`.
- The sibling engine (`src/behavioral_engine.py:199-220`) *does* sleep per
  keystroke including the first (`await asyncio.sleep(dwell ...)` +
  `await asyncio.sleep(flight ...)` inside the per-char loop), but it is a
  different class with a different signature (`type_text(selector, text)` via
  dwell/flight, not inter-key gaps), so it is not a caller expectation on
  `BehavioralTyping` — it is a noted divergence between the two parallel
  implementations (the engine swap is explicitly deferred per `CHANGELOG.md`
  "Nem ebben a commitban: a behavioral_engine.py:199 swap").

Answer: **NO — no caller or test expects a one-char wait; single-char zero is
consistent.**

## 3. `_compute_cpm` empty→0.0 vs all-zero→ZeroDivisionError: reachable?

**NO — the inconsistency is not reachable from any real (production) caller.**
It is reachable only by hand-calling `_compute_cpm` with a fabricated all-zero
list, which today means only the test suite.

Trace (pasted command output):

```
$ grep -rn "_compute_cpm" --include="*.py" src/ tests/
src/behavioral_typing.py:232:    def _compute_cpm(self, delays: list[float]) -> float:
tests/test_behavioral_typing.py:212-215,304,313,528-...  (tests only)
```

- Definition: `src/behavioral_typing.py:232-252` — `if not delays: return 0.0`
  (`:247-248`), `if total == 0: raise ZeroDivisionError` (`:250-251`).
- `src/behavioral_typing.py:178-182` (`type_text`) builds `delays` but **never
  calls `_compute_cpm`**; the computed `total_delay_ms` comes from the dispatch
  loop sum, not from `_compute_cpm`.
- `_generate_delays` (`src/behavioral_typing.py:217-230`) returns `[]` for
  `char_count <= 1` and `rng.lognormvariate(mu, sigma)` draws otherwise —
  lognormal draws are strictly `> 0`, so the generator cannot produce an
  all-zero non-empty list.
- The only non-empty all-zero list constructed anywhere is
  `src/behavioral_typing.py:181`
  (`[0.0] * (char_count - 1)` for raw mode), and that list is consumed only by
  the dispatch loop (`:188-190`), never passed to `_compute_cpm`.
- Hence the path `type_text → _compute_cpm([0.0]*N) → ZeroDivisionError` does
  not exist; the `ZeroDivisionError` branch fires only for
  `typing._compute_cpm([0.0]*10)` written literally in
  `tests/test_behavioral_typing.py:541-544`.

So: real inconsistency in contract, dead in production. Fix belongs to a
follow-up (either return `inf` for instant typing or keep the raise and document
it), not a ship-blocker.

## 4. The four removed strict-xfail markers — genuine gates?

The four removed markers (from `git show 97afc47 -- tests/... | grep "^-.*xfail"`):

1. `test_cpm_bounds_enforced` (`tests/test_behavioral_typing.py:301`)
2. `test_custom_cpm_bounds_enforced` (`:309`)
3. `test_compute_cpm_known_delays` (`:534`)
4. `test_compute_cpm_instant` (`:541`)

Plus a fifth changed test that was *not* an xfail removal but a rewrite:
`test_compute_cpm_not_implemented` (old, asserted `NotImplementedError`) →
`test_compute_cpm_returns_float` (`:528`, asserts a value). Pasted assertions:

```python
# :528-531 test_compute_cpm_returns_float (NEW, replaces the NotImplementedError test)
cpm = typing._compute_cpm([0.1, 0.2, 0.15])
assert isinstance(cpm, float)
assert cpm == pytest.approx(60 * 4 / 0.45, rel=0.02)

# :301-306 test_cpm_bounds_enforced (xfail removed, body unchanged)
delays = typing._generate_delays(100)
cpm = typing._compute_cpm(delays)
assert typing.config.cpm_min <= cpm <= typing.config.cpm_max, (...)

# :309-316 test_custom_cpm_bounds_enforced (xfail removed, body unchanged)
bt = BehavioralTyping(config=custom_config)
delays = bt._generate_delays(100)
cpm = bt._compute_cpm(delays)
assert custom_config.cpm_min <= cpm <= custom_config.cpm_max, (...)

# :534-538 test_compute_cpm_known_delays (xfail removed AND gate tightened)
uniform_300ms = [0.3] * 10  # 10 gaps = 11 chars in 3.0 s
cpm = typing._compute_cpm(uniform_300ms)
assert cpm == pytest.approx(220, rel=0.02)  # 11 chars in 3.0 s = 220 CPM

# :541-544 test_compute_cpm_instant (xfail removed, body unchanged)
with pytest.raises(ZeroDivisionError):
    typing._compute_cpm([0.0] * 10)  # Zero total time
```

Would each still pass under the OLD behaviour?

- (a) `test_compute_cpm_returns_float`: NO — old code raised
  `NotImplementedError` (`git show 7cdc515:...: _compute_cpm` body was
  `raise NotImplementedError`), so it errored under the old behaviour and passes
  only now. Genuine gate for "stub implemented". (Strong: `60*4/0.45 ≈ 533.3`
  pins the `(len+1)` formula, not just "returns a float".)
- (b) `test_cpm_bounds_enforced` / (c) `test_custom_cpm_bounds_enforced`:
  PARTLY — they genuinely gate "stub implemented" (old code raised, so they
  xfailed/errored before and pass now), but they do **NOT** gate the N-1 vs N
  convention: with 100 chars the N vs N-1 difference is `100/99 ≈ 1%`, far
  inside the `[cpm_min, cpm_max]` band either way, so both conventions pass.
  A test that passes both before and after *the convention change* is not a
  gate for that change (it gates only the stub removal).
- (d) `test_compute_cpm_known_delays`: YES, genuine gate for the formula —
  old stub raised (fail), and a naive N-formula `60*len/sum = 60*10/3.0 = 200`
  would FAIL the new `approx(220, rel=0.02)` gate (old assertion was
  `approx(200, rel=1.0)`, i.e. `[100,400]`, which would have accepted both 200
  and 220 — the tightening to `rel=0.02` is what makes it a gate).
- (e) `test_compute_cpm_instant`: PARTLY — genuine gate for stub removal (old
  code raised `NotImplementedError`, not `ZeroDivisionError`, so `pytest.raises
  (ZeroDivisionError)` failed before), but NOT a gate for N-1 (any
  zero-total-raising implementation passes regardless of list length
  convention).

Targeted run evidencing the new tests actually pass:

```
$ python -m pytest tests/test_behavioral_typing.py -k "TestComputeCpmBehavioral" -p no:xdist -o addopts="" -q
7 passed, 59 deselected in 3.54s
```

## 5. Still stubbed or dead in `src/behavioral_typing.py` after ab50d84?

Pasted command output:

```
$ grep -n "NotImplementedError\|TODO\|FIXME" src/behavioral_typing.py
grep-exit=1   (no hits)
```

Answer: **NO `NotImplementedError` / `TODO` / `FIXME` markers remain** in
`src/behavioral_typing.py` — the last stub (`_compute_cpm`,
formerly `:252 `raise NotImplementedError ...  # TODO: P1-3``) is implemented.

What is still dead (no marker, but unreached code — named so it is not silently
passed over):

- `_compute_cpm` (`src/behavioral_typing.py:232-252`) has **zero production
  callers** (see item 3 grep). It is tested but never wired into `type_text` or
  any endpoint.
- `type_text` with `client=None` (`src/behavioral_typing.py:184-196`):
  delays are generated (`:178-182`) but the accumulation loop is guarded by
  `if client is not None`, so the no-client return always carries
  `total_delay_ms == 0.0` while the delays are discarded. `test_type_text_default_mode`
  (`tests/test_behavioral_typing.py:345-349`, `type_text("Hello")` with no
  client) asserts `status/mode/chars` but not `total_delay_ms`, so the path is
  unasserted.
- The `BehavioralEngine ↔ BehavioralTyping` duplication noted in item 2
  (`src/behavioral_engine.py:176-220` dwell/flight vs
  `src/behavioral_typing.py:133-197` gap-based) is still unresolved by design
  (deferred swap, `CHANGELOG.md:27`).

BUDGET: finished inside the 10-minute budget; all 5 items checked. No item marked NOT CHECKED.
