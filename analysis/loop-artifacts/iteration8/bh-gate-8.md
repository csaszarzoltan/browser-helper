# bh-gate-8 — binding gate, iteration 8 (live typing integration)

dispatch: inline prompt (binding GATE iteration 8, /home/zoltan/browser-helper)
agent: reviewer
repo: /home/zoltan/browser-helper @ cb3fdce
brief: inline - sha256 not provided by the dispatcher
verdict: none - first pass (binding gate)
status: DONE — all six items measured; verdict APPROVE

## 0. Base state
- `git log --oneline -1` seen: `cb3fdce docs(loop): iteration 7 next-moves — gate APPROVE 4.8/5 landed`
- `git status --short` seen: `?? analysis/loop-artifacts/iteration8/` + `?? tests/test_typing_live_integration.py` (nothing else; `git diff --stat` empty, `git diff -- src/ | wc -c` = 0)
- `git log --all --oneline -- tests/test_typing_live_integration.py` = empty (gate file never committed; untracked new file)
- Model-alive proof: read `src/behavioral_typing.py:340-374` dispatch pair and `src/main.py:3215-3234` POST /type handler (quoted below); not inferred.
- Note: `git pull --rebase` not attempted (single-node loop, clean tree on cb3fdce, live service running; pull would not change the untracked gate file). Brief budget 900s: all 6 items completed, no timeout.

## 1. Live file meets spec — YES
- Exists: `tests/test_typing_live_integration.py` (brief says 179 lines; measured `wc -l` = 244 lines — expanded, not a violation).
- Marker: `tests/test_typing_live_integration.py:31` `pytestmark = pytest.mark.integration` (precedent `tests/test_cookie_export.py:20` verified present).
- Skip when no service: `:44-50` `_live_service_available()` GET /health; `:211-212` `pytest.skip("live Chrome required")`.
- Strings: `:200` `PROBE_TEXTS = ["a b", "Hello", "Mix 123!"]` — "a b" (space = text=null killer), "Hello" (uppercase), "Mix 123!" (special/punct). Matches spec §Strings.
- Readback via /eval input.value: `:159-160` `_eval` → `_http_post("/eval",...)`; `:163-182` `_read_input_value()` parses `document.querySelector('#probe').value`; `:243-244` `assert value == text`. No `Runtime.evaluate`-by-name (uses POST /eval wrapper) — equivalent live CDP path, accepted.
- No real AsyncMock usage: `grep -c 'AsyncMock' tests/test_typing_live_integration.py` = 0 (zero literals, not even in docstring); `grep -n 'Mock\|mock\.'` executable = empty; no `unittest.mock` import. Spec guard `AsyncMock count = 0` satisfied. `pyproject.toml:35` integration marker already present, so no edit — as spec expected.

## 2. Fails on broken tree / passes on current — YES (RED by mechanism + GREEN live)
- GREEN (measured this gate): `.venv/bin/python -m pytest tests/test_typing_live_integration.py -p no:randomly -o addopts='' -v` → `3 passed in 9.39s` (`[a b]`, `[Hello]`, `[Mix 123!]` each PASSED).
- RED (historical v1.36.14, described per spec allowance — live keyPress injection NOT attempted this gate):
  - `src/behavioral_typing.py:352-355` — `keyPress` is NOT a valid CDP `Input.dispatchKeyEvent` type; Chrome answers `-32602 Unexpected event type 'keyPress'`.
  - `src/behavioral_typing.py:340-342` — `text` popped when None / keyUp; broken tree sent `text=null` (space killer) so nothing inserted.
  - `src/behavioral_typing.py:257-312` — `_key_identifier()` is the `text` source (`"text": char`); space `"a b"` exercises it.
  - `src/behavioral_typing.py:373-374` (current) — `keyDown`+`text` inserts, `keyUp` completes; broken order/type raced the error.
  - `tests/test_typing_live_integration.py:235-236` `assert type_status == 200` would see 400 on broken; `:238-240` envelope `status == "ok"` would fail; `:244` `assert value == text` would see `1/11 chars` mismatch.
  - `src/main.py:3215-3234` POST /type via `run_op("type", ...)` propagates the failure (404 only for not-found; other errors surface in envelope/4xx).
  - Why mocks missed it: `tests/test_behavioral_typing.py:93-99` `mock_client` = `AsyncMock(return_value={"status":"ok"})` answers ok to anything; `:577-584` pins `event_types == ["keyDown","keyUp"]` + `keyPress not in` — pins the mock, cannot prove Chrome accepts the payload.

## 3. No leak + BH_STRICT_SESSIONS=1 — YES (with adoption note)
- Fixture: `tests/test_typing_live_integration.py:185-195` `@pytest.fixture(scope="module", autouse=True) _session_lifecycle` → `_ensure_session()` / yield / `_close_session()`.
- Budget logic: `:71-79` docstring (3-tab budget, 429 tab_budget_exhausted / 400 Missing session if one session per case); `:84-91` adopt existing via GET /sessions; `:95-104` else mint exactly ONE via POST /session/new.
- Strict-session dance: `:100` `sid = resp.headers.get("X-Session-ID")`; `:137` `headers["X-Session-ID"] = _SESSION_ID` on every POST; `:36-41` module comment states BH_STRICT_SESSIONS=1.
- Live proof: service env pid 222642 carries `BH_STRICT_SESSIONS=1` (+`BH_MAX_SESSIONS=30`, `BH_SESSION_AUTO=1`); service v1.36.19.
- Tabs: before run `/sessions` → `tabs_in_use: 1 count: 1 sid 629a796e... age 627.8s`; after live 3-passed → `tabs_in_use: 1 count: 1` same sid age 654.0s. Minted 0, leaked 0 — module ADOPTED the pre-existing session (`_SESSION_OWNED=False`) so `_close_session()` (`:119-128` only-if-owned) correctly left it open. Brief's "tabs 0 after close" is not literally met because a foreign session pre-existed; no-growth + same-sid is the correct no-leak signal here.

## 4. Normal suite unaffected; collect adds only 3 — YES
- Collect without: `.venv/bin/python -m pytest tests/ -o addopts='' -p no:randomly --ignore=tests/test_typing_live_integration.py --co -q` → `2855 tests collected`.
- Collect with: same without `--ignore` → `2858 tests collected`. Delta exactly +3 (the parametrized gate). File-only collect lists `test_live_typing_round_trip[a b|Hello|Mix 123!]`.
- Normal suite (new file ignored): `.venv/bin/python -m pytest tests/ -o addopts='' -q -p no:randomly --ignore=tests/test_typing_live_integration.py -p no:cacheprovider` → `2846 passed, 1 skipped, 8 xfailed, 35 warnings in 319.05s`. No new failures/skips beyond known 8 xfailed. (Counts differ from brief's 2844p/197p by tree growth since iteration estimate; isolation holds.) Default `pyproject.toml:38` `addopts = "-n auto -q"` noted; spec acceptance commands used `-o addopts=''` as written.

## 5. Allowlist respected — YES
- `git diff --name-only` empty; `git diff --stat` empty; `git diff -- src/ | wc -c` = 0. No `src/` change (spec: production path `behavioral_typing.py:328,352-370` + `behavioral_engine.py:212` + `main.py:3216/6430` correct as-is — verified `behavioral_engine.py:189 type_text`, `main.py:3215 @app.post("/type")`).
- Only `tests/test_typing_live_integration.py` (untracked new file) + `analysis/loop-artifacts/iteration8/` (this gate's durable report copy) are dirty. `pyproject.toml` untouched (marker `:35` already present). `scripts/release-validate.sh` untouched (no pytest/integration hook found — not required by spec).

## 6. Score + verdict

| Dimension | Weight | Score | Basis |
|---|---|---|---|
| Correctness | 30% | 5 | All ACs met, proven live: 3 passed 9.39s, readback == sent, session adoption with 0 growth |
| Test coverage | 20% | 5 | New behavior has new test + green; delta exactly +3 collected; normal suite 2846p green |
| Spec compliance | 20% | 5 | File+marker+skip+strings+readback+AsyncMock-0+allowlist all per bh-spec-8.md |
| Code quality | 15% | 5 | Clean, typed (`tuple[int, dict\|None]`), stdlib urllib only, module fixture, no facade/stub |
| Evidence | 15% | 4 | Live + suite logs pasted with commands/counts; base SHA seen; −1: gate file never committed, no push SHA (untracked) |
| **Weighted total** | 100% | **4.85** | 5*.3+5*.2+5*.2+5*.15+4*.15 = 4.85 |

APPROVE 4.9/5 — live gate is green (3 passed), isolated (+3 only), and leak-free on the fixed tree.

- `git log --oneline -1` seen: `cb3fdce docs(loop): iteration 7 next-moves — gate APPROVE 4.8/5 landed`
- Test commands run: file collect (3 collected); live `tests/test_typing_live_integration.py` (3 passed in 9.39s); suite-collect without/with (2855 vs 2858); full normal suite ignored-new-file (2846 passed, 1 skipped, 8 xfailed in 319.05s); `/sessions` before/after (1/1 same sid).
- Report at BOTH paths: `$TMPDIR/dispatch-log/bh-gate-8.md` (=`/home/zoltan/.hermes/cache/scratch/dispatch-log/bh-gate-8.md`) and durable `/home/zoltan/browser-helper/analysis/loop-artifacts/iteration8/bh-gate-8.md` (same bytes; orchestrator to `git add` explicit paths and commit after gate — reviewer commits nothing).
- Do not tag per brief; orchestrator releases.
