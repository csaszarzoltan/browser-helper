# Capability readiness and execution context

Browser Helper 1.9 adds a truthful readiness model to the Overview workspace. The goal is to help operators decide what they can safely use before starting a browser task.

## Status vocabulary

- **Ready**: supported for normal daily use and included in the production path.
- **Experimental**: present for evaluation, but the supplied implementation still has incomplete or pre-development paths.
- **Unavailable**: intentionally excluded from production use because its implementation or dependency is absent.

`GET /api/v1/capabilities` returns a versioned, privacy-safe registry. It does not expose credentials, URLs, cookie values, page content, or provider secrets. The dashboard refreshes the registry on load and on demand.

## Expanded execution context

The persistent context bar now shows:

- CDP connection state
- current tab count
- current CDP target, truncated visually with the full value available as an accessible title
- most recent operation

Browser-dependent controls continue to be disabled while disconnected. Context changes use the existing state update bridge and remain available to keyboard and assistive-technology users.

## Operator guidance

Review Product readiness on Overview before using advanced domains. Experimental areas remain available to developers through their existing interfaces but should not be treated as production-ready until their stubs and RED-phase tests are resolved. Unavailable providers should not be offered in production selection lists.

## Testing

`tests/test_capability_readiness_v20.py` covers registry ordering and safety, maturity classification, API contract, dashboard structure, accessible rendering, failure telemetry, and execution-context bridging.
