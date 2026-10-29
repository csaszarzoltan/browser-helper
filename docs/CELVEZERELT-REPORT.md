# Celvezérelt cycle report

Date: 2026-10-29. Branch: `mcp-token-efficiency`. Base commit: `300f531`.

## Goals

The README had no `## Goals` section, so the goals were derived from the README, the CHANGELOG and the code, then written at the top of `README.md`. Status is the state before and after this cycle.

| # | Goal | Before | After | Evidence |
|---|------|--------|-------|----------|
| 1 | Small answers for agents: one REST envelope, bounded MCP replies | partially met | partially met | Envelope: `src/main.py:1532-1537` (`api_error`), `src/mcp_server/serialization.py:65`. Bounded observation: `src/main.py:6060-6062`. MCP could not skip it before: `src/mcp_server/tools.py:660` (signature). Open: 19 call sites of the legacy `_api_error` shape (`src/main.py:7884-7889`, bare string under `error`). |
| 2 | Works in the user's real Chrome, survives a service restart | met | met | `src/chrome_manager.py:559` (`start_new_session=True`); `tests/test_chrome_survives_restart.py` |
| 3 | Isolated sessions, budgets enforced | met | met | `src/session_registry.py:91`; `src/main.py:451` (`BH_MAX_TABS`); `tests/test_agent_isolation.py`, `tests/test_parallel_session_isolation.py` |
| 4 | No silent success | met | met | `src/main.py:6008` (`effect: "none"`); `src/main.py:5991` (dialog policy); `src/mcp_server/registry.py:248` (`expect`); `tests/test_act_click_effect.py`, `tests/test_dialog_policy.py` |
| 5 | Safe by default: loopback bind, token for non-loopback | met | met (one open finding) | `run.py:24,31`; `src/main.py:1279-1310`; `src/mcp_server/server.py:154-158`. Open: fingerprint import reads any server-side path (see review findings). |
| 6 | Failures explain themselves; `bh doctor` | met | met | `src/browser_helper/doctor.py:197`; `src/main.py:2603-2607` (holders in `tab_budget_exhausted`); `tests/test_doctor.py` |

Goal 1 stays `partially met` because of the 19 legacy error sites. Changing them changes the public error shape of many endpoints, so I did not do it in this cycle. This is a decision for the owner.

## Competitor findings

Sources were searched on 2026-10-29. Most results were third-party mirrors, not the official repositories, so treat these as secondhand.

- **chrome-devtools-mcp** (Google, npm `chrome-devtools-mcp`): CDP-based, traces and performance insights, one-command install with `@latest`. A third-party listing reports 26 tools, unverified. Mirror changelog ends at 0.18.1 (2026-02-25). Sources: https://glama.ai/mcp/servers/@ChromeDevTools/chrome-devtools-mcp ; https://glama.ai/mcp/servers/@ChromeDevTools/chrome-devtools-mcp/blob/505089c2884428ef7d040a36dd0b50ee30f0e623/CHANGELOG.md
- **Playwright MCP** (Microsoft): accessibility-tree snapshots instead of screenshots; `browser_snapshot` plus element refs. Snapshot can be turned off after actions (snapshot mode `none`) and called explicitly; a tree depth limit and file output exist. Tool counts differ by source. Relevance: this confirms our goal 1 gap, where `act` could not omit the observation. Sources: https://www.mintlify.com/microsoft/playwright-mcp/concepts/accessibility-snapshots ; https://itnext.io/why-does-playwright-mcp-use-so-many-tokens-da56b6dbd2db
- **Browserbase Stagehand** (v3 docs): `observe` finds candidate actions, which are checked before `act` runs them, and can narrow `extract` to one element to save tokens. Our `observe` (`src/mcp_server/registry.py:222`) and `act` `expect` already cover this pattern. Source: https://docs.stagehand.dev/v3/basics/observe
- **Browser Use** (cloud docs): persistent profiles hold cookies and storage across sessions. Our session save and restore (`src/main.py:4710`, `4720`) and profile manager cover this. Source: https://docs.cloud.browser-use.com/guides/sessions

Conclusion: Playwright MCP's snapshot-off option is the one idea that fit our goals and was missing. Stagehand's observe-then-act and Browser Use's profiles are already present, so I did not copy them.

## Features implemented

Only one feature passed the evidence check. The minimum of three was **not met**. The other candidates had no gap in the code: `observe` already has paging, filters and a diff; session save and restore exist; the stub modules (`src/session_manager.py`, `src/behavioral_scroll.py`, `src/browser_providers/camofox.py`) are documented as experimental and are not in the goals.

1. **MCP `act` takes `include_observation`** (goal 1, cost S, risk low). The REST engine already had the flag. The MCP tool did not pass it, so every reply carried the snapshot. `false` now drops it, and unset keeps the old behaviour. Commit `019b9ee`. Tests: `tests/test_mcp_act_observation.py` (2 tests).

## Review findings

Code review, round 1 (goals-driven, with the touched areas read in full):

| Finding | Status | Reason |
|---------|--------|--------|
| `/api/v1/fingerprints/import` returned 500 for invalid JSON or a JSON list | fixed, `dfa6577`, `d79db42` | Now 422 with `error: {code, message}`. Tests in `tests/test_fingerprint_import_api.py`. |
| Import endpoint errors used a bare-string `error` (not the envelope) | fixed, `d79db42` | Changed for this endpoint only. Noted in CHANGELOG. |
| `tests/test_anti_detect_api.py::test_fingerprints_import` read `/tmp/test.json`, which no test creates. It failed once under `-n auto` (404) and passed on reruns. | fixed, `efcd8cf` | Test writes its own file. Stale "RED phase" text removed. |
| Dashboard screenshot `<img>` had no `alt` (`static/index.html:598`) | fixed, `bf68038` | Static test added for all dashboard images. |
| 19 call sites of legacy `_api_error` (`src/main.py:7884`) return `error` as a string, not the envelope | open | Changes the public error shape of many endpoints. Needs an owner decision and a migration note. Goal 1 stays partial. |
| Fingerprint import takes any server-readable path from the request body (`src/main.py:8071`, `src/anti_detection/fingerprint_database.py:414`) and saves it into the template store | open | Only reachable with `API_TOKEN` (or on loopback without it). Restricting paths to a directory is a design choice. The 404 also echoes the path back. |
| Dashboard screenshot image opens its viewer on `onclick` only (`static/index.html:598`), so it cannot be reached by keyboard | open | Needs a real button or `tabindex` plus key handling. Not done in this cycle. |
| `scripts/release-validate.sh` tool-count check for README uses a loose pattern (`(15|19|78) tools?`) | open | It would pass on any "15 tools" text. Minor. |
| `scripts/release-validate.sh` reports `main` 56 commits behind `origin/main` | open, environmental | Local `main` is at `0e25674`; `origin/main` is at `300f531`, which is the base of this branch. This branch does not depend on local `main`. The owner needs to sync `main`. |

## Iterations

- Code review: 1 round. Limit (5) not reached.
- UI review: 1 round. **Static only.** No live browser walk: no run of the dashboard against Chrome was done in this cycle. Checked: `alt` on images (fixed), button labels (visible text, fine), existing `tests/test_dashboard_a11y_static.py` and `tests/test_dashboard_ux_v19.py` (pass).
- Limit not reached. No open loop.

## Git

- Branch: `mcp-token-efficiency` (not `main`). Per the workflow, work stayed on the current branch. No new branch was created.
- Commits (on top of `300f531`):
  - `6641614` docs: add Goals section with checkable evidence per goal
  - `019b9ee` feat(mcp): act takes include_observation to skip the reply snapshot
  - `dfa6577` fix(api): fingerprint import answers 422 for invalid or non-object JSON
  - `efcd8cf` test(api): the fingerprint import test writes the file it reads
  - `bf68038` fix(dashboard): screenshot image has alt text
  - `eb23736` docs: MCP act include_observation, and the changelog for this round
  - `d79db42` fix(api): fingerprint import errors use the standard error envelope
  - plus this report commit
- Push: see the final chat message for the outcome. The push target is the current branch's upstream, `origin/mcp-token-efficiency`, as a fast-forward. The workflow names `main`, but local `main` is not in sync with `origin/main`, so `main` was not touched.
- No force push, no reset, no history rewrite. `.serena/` (untracked, not mine to commit) was left out.

## Tests

Commands run on the final state:

- `.venv/bin/ruff check src/`: exit 0, "All checks passed!"
- `.venv/bin/python -m pytest -o addopts="" -q -n auto -p no:cacheprovider`: exit 0, **3011 passed, 6 skipped, 8 xfailed**, 49 warnings, 80.5 s.
- Baseline before the cycle, same command: 3004 passed, 6 skipped, 8 xfailed, exit 0. One earlier full run, without `-o addopts=""`, failed `test_fingerprints_import` (see review findings). That is the flake I fixed.
- Targeted runs during the cycle: MCP test files 100 passed; fingerprint and API files 222 passed; import and API files 118 passed; dashboard static files 11 passed.
- `scripts/release-validate.sh`: exit 1. Version, badge, changelog, Dockerfile and tool count (78) all pass. The one failure is the `main` vs `origin/main` divergence in the environment (see review findings).
- Build: no separate build step in this project. `pip install -e ".[dev,mcp]"` was not re-run.

## Open items

1. Decide on the 19 legacy `_api_error` sites (goal 1). Needs an API-change note.
2. Restrict or document the fingerprint import path (security).
3. Keyboard access for the dashboard screenshot.
4. Live dashboard walk at 1280 px and 390 px, which this cycle did not run.
5. Fewer than three features were implemented (minimum not met). The evidence did not support more without inventing gaps.
6. Push: see the final chat message.

## Changes to goals

- Added a `## Goals` section to `README.md`, because the file had none. Six goals, each with file and test references.
- No goal was rewritten or dropped.
