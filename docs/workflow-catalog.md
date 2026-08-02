# Durable parameterized workflow catalog

Browser Helper 1.16 adds durable, versioned workflows on top of the existing local Script Runner.

## User value

Operators commonly copy a JSON workflow, change one URL or value, and run it again. The catalog lets them save the workflow once, declare typed parameters, supply values at use time, and load resolved steps into the existing editor for review before execution.

## Safety model

- Catalog resolution never executes browser actions.
- Resolved steps are loaded into the Script Runner and remain reviewable before the user chooses **Run**.
- Secret parameter values are accepted only at resolution time.
- Secret values are returned in resolved steps because the existing runner needs them, but `recorded_parameters` always contains `[REDACTED]`.
- Secret defaults are not persisted.
- Workflows are bounded to 100 steps and 50 parameters.
- Placeholder references must match declared parameters.

## Parameter types

- `string`
- `number`
- `boolean`
- `url`, limited to HTTP and HTTPS
- `enum`, with configured choices
- `secret`

Use `{{parameter_name}}` inside strings. A value consisting only of one placeholder preserves its resolved JSON type.

## API

- `GET /api/v1/workflows`
- `POST /api/v1/workflows`
- `GET /api/v1/workflows/{workflow_id}?version=2`
- `POST /api/v1/workflows/{workflow_id}/versions`
- `POST /api/v1/workflows/{workflow_id}/resolve`
- `POST /api/v1/workflows/{workflow_id}/archive`

Example:

```json
{
  "name": "Open target",
  "description": "Navigate and capture evidence",
  "parameters": [
    {"name": "target_url", "type": "url", "required": true}
  ],
  "steps": [
    {"action": "navigate", "url": "{{target_url}}"},
    {"action": "screenshot", "quality": 80}
  ]
}
```

Resolve it with:

```json
{
  "parameters": {
    "target_url": "https://example.com"
  }
}
```

## Persistence

The catalog uses schema version 1 and atomic JSON replacement at `~/.browser-helper/workflows.json`. Every update creates an immutable new version. Archiving hides the latest version from the default catalog view without removing historical data.
