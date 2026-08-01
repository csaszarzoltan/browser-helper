# Run support bundles

Browser Helper 1.11 lets an operator download a small, redacted JSON document for one entry in the unified run timeline.

## Why this exists

Previously, an operator needed to copy status, timing, capability maturity, and environment details manually when reporting an issue. A support bundle packages the minimum safe context needed to begin troubleshooting without exporting browser data.

## Included data

- Support schema version and generation time
- Selected redacted run record
- Connection state and tab count
- Last operation name and timestamp
- Capability-readiness summary
- Explicit privacy flags

## Excluded data

- Page content and observations
- Cookie names and values
- Local or session storage
- Authorization headers and credentials
- Proxy secrets and provider keys
- CDP target URL
- Screenshots and network bodies

## API

```http
GET /api/v1/runs/{run_id}/support
```

A missing or expired run returns HTTP 404 with `run_not_found`. The endpoint follows the existing API-token middleware policy.

## Dashboard

Open **Diagnostics**, find the desired run, and choose **Support JSON**. The file is downloaded as `<run_id>-support.json`. The action announces success or failure to assistive technology and emits only a local telemetry event containing the generated run ID.
