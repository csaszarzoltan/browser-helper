# Safe run recovery guidance

Browser Helper 1.14 provides deterministic guidance for one retained operation run. Guidance is advisory only. It never executes or retries an action.

## Recovery categories

- `execution_failure`: the operation did not complete.
- `verification_failure`: the command executed, but explicit evidence did not confirm the expected result.
- `evidence_missing`: the command completed without supported proof.
- `none`: the run already contains explicit successful evidence.

## Retry safety

Read-only operations such as screenshots, observations, status checks, and page analysis can be marked `safe` to retry after checking context. Mutating operations are marked `review`, because repeating a click, navigation, form submission, or other action may duplicate side effects.

The advisor never uses or returns the run detail text. This prevents credential-like values from being repeated in guidance.

## API

```http
GET /api/v1/runs/{run_id}/recovery
```

The response includes a version, category, retry-safety classification, recommended action, summary, bounded steps, and `automatic_retry: false`. Missing runs return HTTP 404 with `run_not_found`.

## Dashboard

Choose **Recovery guidance** on a Diagnostics timeline row. The advice appears inline in the same workspace and is announced through a live region. No retry button is generated.
