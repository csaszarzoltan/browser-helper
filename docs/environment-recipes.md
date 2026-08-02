# Reusable environment recipes

Browser Helper 1.15 adds a privacy-safe environment catalog for repeated daily setup. An environment recipe combines non-secret runtime choices such as visible or headless execution, profile, proxy strategy, fingerprint template, and provider reference.

## Why it exists

Profiles, proxies, fingerprints, providers, and runtime choices previously lived in separate API areas. Operators had to remember the intended combination before each run. Environment recipes create a named, reviewable context without storing credentials.

## Dashboard

Open **Environments** to:

- create a named recipe;
- choose visible Chrome, local headless, Browserbase, or Steel;
- reference an existing profile;
- select a proxy strategy;
- activate one recipe as the current execution context;
- safely delete recipes that are not active.

The active environment appears in the persistent context bar. Activation selects context only. It does not silently launch, reconnect, or mutate a browser.

## API

- `GET /api/v1/environments`
- `POST /api/v1/environments`
- `GET /api/v1/environments/{environment_id}`
- `POST /api/v1/environments/{environment_id}/activate`
- `DELETE /api/v1/environments/{environment_id}`

Example:

```json
{
  "name": "Daily QA",
  "runtime": "visible",
  "profile": "qa-profile",
  "proxy_strategy": "round-robin",
  "tags": ["qa", "daily"]
}
```

## Privacy and persistence

Recipes are stored in `~/.browser-helper/environments.json` using schema version 1 and atomic file replacement. Secret-like fields including passwords, tokens, API keys, authorization values, cookies, and credentials are rejected. Provider credentials continue to come from protected server configuration or environment variables.

## Safety behavior

- Names are unique, case-insensitively.
- Object references use a bounded safe identifier format.
- The active recipe cannot be deleted until another recipe is activated.
- Browser launch remains an explicit action.
- UI telemetry contains only recipe ID, runtime, count, and bounded failure reason.
