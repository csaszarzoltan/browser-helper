# Daily work launchpad

**Since:** v1.18.0

## Purpose

The Overview workspace provides a single privacy-safe starting point for repeated operator work. It reduces the need to inspect connection, environment, workflow, and diagnostics panels separately before deciding what to do next.

## User behavior supported

The launchpad is designed for operators who commonly reconnect to Chrome, reuse an environment, review a saved workflow, and inspect recent failed or incomplete runs. It does not execute an action automatically. The operator always reviews the destination workspace before running browser automation.

## Recommendation order

The server chooses one deterministic next action:

1. Connect a browser when Chrome is disconnected.
2. Review recent error, incomplete, or explicitly failed-verification runs.
3. Choose an environment when no recipe is active.
4. Open saved workflows when a reusable workflow exists.
5. Start a Live Browser task otherwise.

## API

`GET /api/v1/launchpad`

The versioned response includes connection state, tab count, a bounded active-environment summary, aggregate counts, at most five workflow summaries, at most five runs needing attention, and explicit privacy metadata.

The endpoint excludes page content, URLs, workflow step values, parameters, run detail strings, cookies, browser storage, credentials, tokens, and secrets.

## Accessibility and resilience

- The card is labeled by its visible heading.
- Loading uses `aria-busy` and a polite status region.
- Empty states explain where to create a workflow or confirm that no run requires attention.
- Actions use native buttons and preserve the existing workspace navigation behavior.
- The layout changes from three columns to two and then one without hiding content.
- A failed launchpad request does not disable existing workspaces.

## Telemetry

The browser emits local `browser-helper:telemetry` events for launchpad load, load failure, and action selection. Event details contain only bounded reason text, aggregate counts, an action identifier, and a workspace identifier. They are not sent anywhere unless a host application explicitly subscribes and forwards them.

## Testing

Run:

```bash
PYTHONPATH=src uv run pytest -q tests/test_daily_launchpad_v218.py
node --check static/dashboard_ux.js
uv run ruff check src/daily_launchpad.py tests/test_daily_launchpad_v218.py
```
