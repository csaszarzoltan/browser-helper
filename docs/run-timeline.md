# Unified run timeline

Browser Helper 1.10 adds a process-local, bounded timeline for browser operations recorded through the shared operation logger.

## User value

The timeline gives operators one newest-first view of recent action outcomes instead of requiring them to reconstruct basic execution order from individual panels. It is deliberately incremental: it creates a safe foundation for future cross-step correlation without changing existing endpoint contracts.

## Data contract

Each run contains:

- `schema_version`
- generated `run_id`
- UTC timestamp
- operation name
- `success`, `error`, or `incomplete` status
- duration in milliseconds
- `verified`, `unverified`, or `failed` verification state
- bounded, redacted detail

The current integration marks ordinary operations as `unverified`. This avoids implying that command completion proves the intended page outcome.

## Privacy and retention

- The store is in memory and is removed when the process stops.
- Retention is bounded to 100 entries.
- Common authorization, token, API key, password, session, and secret patterns are redacted before storage.
- Detail strings are capped at 500 characters.
- Clearing the timeline does not affect Chrome, tabs, cookies, or session state.

## API

- `GET /api/v1/runs?status=error&limit=50`
- `DELETE /api/v1/runs`

The endpoint remains protected by the existing API-token middleware when `API_TOKEN` is configured.

## Dashboard

Open **Diagnostics** and use **Unified run timeline**. The view supports refresh, status filtering, accessible status updates, an empty state, and confirmed clearing.
