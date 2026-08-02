# Privacy-safe run detail and comparison

Browser Helper 1.17 lets operators inspect safe run metadata and compare two retained runs directly in Diagnostics.

## Why it exists

The unified timeline, run IDs, verification states, support bundles, and recovery guidance made individual outcomes traceable. Operators still had to compare a passing and failing run manually. The comparison endpoint provides a deterministic answer without replaying detail text, page content, cookies, credentials, or target URLs.

## Dashboard

Each timeline entry now has a **Details** action showing:

- run ID;
- operation;
- status;
- verification state;
- duration;
- timestamp.

The comparison panel lets users choose two retained runs. It reports operation, status, and verification changes plus the duration delta. Differences are textual and do not rely on color.

## API

`GET /api/v1/runs/compare?left={run_id}&right={run_id}`

The response contains two bounded summaries, field-level change flags, the duration delta, and explicit privacy metadata. If either run is missing or expired, the endpoint returns HTTP 404 with `run_not_found`.

## Privacy

Comparison excludes the run detail string even though the timeline store already redacts it. It also excludes page content, credentials, cookies, storage, screenshots, target URLs, and network bodies. The browser UI renders only the bounded comparison contract.
