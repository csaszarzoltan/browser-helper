# End-to-end run correlation

Browser Helper 1.12 carries one generated run ID from the shared operation logger into API response metadata, the operation stream, the unified timeline, and support exports.

## Response metadata

Successful operations using the shared `run_op` path now include:

```json
{
  "meta": {
    "run_id": "run_0123456789abcdef",
    "verification": "unverified"
  }
}
```

The `verification` field is intentionally explicit. Successful command execution does not automatically prove that the intended page outcome occurred.

## API

Retrieve one retained redacted run:

```http
GET /api/v1/runs/{run_id}
```

A deleted, expired, or unknown run returns HTTP 404 with `run_not_found`.

## Dashboard

The Diagnostics timeline displays each run ID and provides **Copy run ID**. Copying announces the result to assistive technology and emits the local-only `run_id_copied` telemetry event. The copied ID can be included in bug reports or used with the single-run and support-bundle endpoints.

## Compatibility

The change is additive. Existing response data and the deprecated `result` alias remain unchanged. Clients that ignore `meta` continue to work.
