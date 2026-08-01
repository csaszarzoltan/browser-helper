# Truthful verified outcomes

Browser Helper 1.13 separates command execution from proof that the intended user-visible outcome occurred.

## State definitions

- **verified**: explicit evidence confirms the outcome.
- **unverified**: the operation completed, but no supported proof was present.
- **failed**: the operation executed, but explicit verification evidence says the expected state did not occur.

A transport-level error remains an operation `error`; it is not confused with verification failure.

## Recognized evidence

The shared operation path recognizes only explicit evidence:

- top-level boolean `verified`;
- nested `verification.verified` boolean;
- `confirmation.state_change.changed` boolean.

A generic `status: ok`, truthy result, or successful CDP response never becomes verified automatically.

## API behavior

The inferred value is returned in response metadata and stored on the correlated run:

```json
{
  "meta": {
    "run_id": "run_0123456789abcdef",
    "verification": "verified"
  }
}
```

An explicit verification failure can coexist with `status: ok` because the command itself executed successfully. This distinction helps operators understand whether they need transport recovery or task-level recovery.

## Dashboard

Diagnostics can filter by all verification states. Guidance above the timeline explains the difference between verified and unverified outcomes so users do not equate successful execution with completed intent.
