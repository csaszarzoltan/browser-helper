# Agent Navigation Engine

## Purpose

The Agent Navigation Engine minimizes LLM tool calls and brittle selectors by exposing the browser in user-facing concepts. Chrome's accessibility tree is normalized into a compact semantic graph. CDP transport stays in `cdp_client.py`; deterministic modeling lives in `agent_navigation.py`; FastAPI adapters live in `main.py`.

## Observation contract

`POST /agent/observe` retains the legacy default. Set `mode` to `accessibility` to receive:

- stable snapshot fingerprint and snapshot-scoped semantic refs;
- role, accessible name, description, value, hierarchy and path;
- required, invalid, expanded, selected, checked, disabled and readonly states;
- available high-level actions;
- backend DOM node IDs used internally for selector-free interaction;
- scope, inclusion categories, interactive-only mode and node budgets;
- differential observations with `since_snapshot_id` and `changed_only`.

Accessibility refs are snapshot scoped. Re-observe after page mutation. Acting on a stale ref returns HTTP 409.

## Form endpoints

### `POST /agent/forms/discover`

Returns forms, semantic field types, required/disabled/invalid state, current values and supported actions.

### `POST /agent/forms/fill`

Request fields:

- `form_ref`: a ref returned by discovery;
- `data`: semantic keys such as `full_name`, `postal_code`, `country`, or a normalized field label;
- `validate`: whether to capture a new form state after filling.

The response distinguishes attempted, confirmed, invalid and uncertain fields. Native text fields use backend-node filling and verify their final value. Comboboxes reuse the existing label-aware selection implementation.

## Extraction endpoint

`POST /agent/extract` accepts `schema`, optional `scope`, `snapshot_id`, and `include_evidence`. The deterministic extractor matches schema property names to accessible names, descriptions and semantic paths. It returns missing required fields rather than inventing data. Evidence contains the source ref, role and source text.

## Page-aware actions

`POST /agent/available-actions` reports the active region/dialog, discovered forms, required missing fields, clickable controls, enablement and blocking reasons.

## Verified actions

Add an `expect.any_of` array to `/agent/act`. Supported checks are:

- `url_changed`;
- `dialog_opened`;
- `text_visible`;
- `element_visible` with role and/or accessible name.

A failed expectation returns `needs_attention`. `recovery.retry` permits one bounded retry for accessibility-ref clicks.

## Task execution

`POST /agent/execute-task` performs a bounded deterministic micro-workflow:

1. accessibility observation;
2. semantic form discovery;
3. form fill and value confirmation;
4. refreshed observation;
5. optional Continue/Next/Proceed action;
6. post-action change verification;
7. final compact observation or candidate actions.

It does not contain an LLM and does not claim success for unsupported goals. Use `constraints.max_steps` and `constraints.stop_before` to bound behavior.

## Extension points

The next adapters should implement shadow DOM, iframe aggregation, ARIA autocomplete, date pickers, virtual lists, pagination, overlay dismissal, and screenshot fallback. They should depend on `AccessibilitySnapshot` and remain independent from FastAPI.

## Complex UI helpers and visual fallback

`POST /agent/act` also supports `dismiss_overlay`, `open_menu`, `expand_section`, `load_all_items`, `extract_table`, and `switch_context`. These are bounded helpers for common web UI patterns. When verified interaction remains uncertain, pass a strategy containing `element_screenshot` or `viewport_screenshot`; the response then contains a short-lived artifact for LLM visual grounding instead of embedding base64 image data.

## Snapshot reliability and accessibility fallback

The semantic store retains up to 200 snapshots and supports reference-counted pinning. `/agent/act` pins a referenced snapshot for the call duration and always releases it in a `finally` block. Target resolution no longer creates a competing snapshot before using the supplied ref.

For stale refs, `auto_recover` performs at most one accessibility refresh and resolves the target by its accessible name. Recovery fails explicitly when no name is supplied or no unique candidate is found.

Legacy observations accept `search_text` and `fallback: accessibility`. This is intended for SPA portals, Angular CDK overlays, menus and dialogs that condensed DOM extraction misses. When a dialog is open, accessibility page scope automatically narrows to the dialog subtree, including modal form fields and dropdown actions.

## Workflow recording

- `POST /agent/record` starts a process-local recording.
- `POST /agent/record/stop` finalizes and returns it.
- `POST /agent/replay` replays recorded act requests and can stop at the first HTTP error.

Observe operations are included as trace context but are not replayed. Replayed actions use stale-ref recovery and do not pin obsolete snapshot IDs.

## Verification, autocomplete, waits and SPA history

Actions can carry `verify_after` with `text_visible` or `element_visible`. Verification is independent from CDP command success and reports observed text and elapsed time. `wait_for_element` exposes the same deterministic polling primitives as a standalone action.

Autocomplete form values use `{value, resolver: autocomplete}`. The browser helper fills the semantic field, sends input/change events, waits for the popup, and selects the first visible matching option.

Accessibility observations exclude ignored nodes by default. `include_hidden` opts into them for unusual tab/portal implementations. `select_tab` searches DOM roles and common tab controls directly.

History-aware form discovery uses bounded scrolling with a stable-height stop condition. Workflow replay accepts recursive overrides keyed by recorded request field names; the older `recording_id` remains accepted alongside `recorded_id`.
