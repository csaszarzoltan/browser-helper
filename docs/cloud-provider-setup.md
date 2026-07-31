# Cloud Browser Provider Setup

**Since:** v1.7.0

Browser Helper can launch sandboxed browser sessions through cloud providers, providing managed browser environments with CDP access — no local Chrome instance required.

## Architecture

```
Your App → Browser Helper REST API
               ↓
        CloudSessionPool
         ↙    ↓    ↘
  Browserbase  Steel  Camofox*
  Provider    Provider  Provider
```

`*` Camofox is a P0 stub — full integration deferred to P2.

The `CloudSessionPool` manages a pool of warm sessions across all configured providers, with automatic fallback if one provider fails.

## Supported Providers

### Browserbase

Connects to the Browserbase API (`https://www.browserbase.com/api/v1`) to launch sandboxed browser sessions.

**Prerequisites:**
- Browserbase account with API access
- `BROWSERBASE_API_KEY` environment variable set
- `BROWSERBASE_PROJECT_ID` environment variable set (optional, for project scoping)

```bash
export BROWSERBASE_API_KEY="your-api-key"
export BROWSERBASE_PROJECT_ID="your-project-id"
```

### Steel Browser

Connects to the Steel Browser API (`https://api.steelbrowser.com/v1`).

**Prerequisites:**
- Steel Browser account
- `STEEL_API_KEY` environment variable set

```bash
export STEEL_API_KEY="your-steel-api-key"
```

### Camofox (stub — P2)

A Firefox-based managed browser that runs as a local subprocess. The `CamofoxProvider` class exists with the full `BaseProvider` interface but all methods currently raise `NotImplementedError`. Full integration planned for a future release.

## Getting Started

### 1. Set up credentials

```bash
# At least one of these:
export BROWSERBASE_API_KEY="bb_..."
export BROWSERBASE_PROJECT_ID="proj_..."
export STEEL_API_KEY="steel_..."
```

### 2. Start Browser Helper

```bash
python run.py
```

The cloud providers are auto-detected from environment variables. If no credentials are set, the session pool runs empty and local headless mode is used.

### 3. Launch a cloud browser session

Browser Helper's internal API (`CloudSessionPool.get_session()`) handles provider selection automatically. For direct provider usage:

```python
import asyncio
from browser_providers.browserbase import BrowserbaseProvider
from browser_providers.session_pool import CloudSessionPool

async def demo():
    # Create a provider
    bb = BrowserbaseProvider()
    
    # Create a session pool with this provider
    pool = CloudSessionPool(providers=[bb], min_warm=1, max_warm=3)
    
    # Get a session (prefers warm, falls back to new launch)
    session = await pool.get_session()
    print(f"Session: {session.session_id}")
    print(f"Provider: {session.provider}")
    print(f"CDP URL: {session.cdp_url}")
    
    # Mark as warm for reuse
    await bb.mark_warm(session.session_id)
    
    # Close when done
    await bb.close_session(session.session_id)

asyncio.run(demo())
```

## Session Pool Configuration

The `CloudSessionPool` is configurable on construction:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `providers` | `[]` | List of `BaseProvider` instances to use |
| `min_warm` | `1` | Minimum number of warm sessions to maintain |
| `max_warm` | `5` | Maximum warm sessions allowed |
| `ttl_seconds` | `300` | Idle session TTL in seconds (expired sessions are evicted) |

```python
# Production-like configuration
pool = CloudSessionPool(
    providers=[BrowserbaseProvider(), SteelProvider()],
    min_warm=2,
    max_warm=10,
    ttl_seconds=600,
)
```

## Provider Fallback

When a provider fails to launch a session, the pool falls through the provider list:

```python
pool = CloudSessionPool(
    providers=[
        BrowserbaseProvider(),  # Tried first
        SteelProvider(),        # Fallback if Browserbase fails
    ]
)

result: FallbackResult = await pool.get_session_with_fallback()
print(f"Success: {result.success}")
print(f"Chain attempted: {result.chain}")   # ["browserbase", "steel"]
print(f"Errors: {result.errors}")           # ["HTTP 429", None]
```

Each provider's `health_check()` method can be used proactively:

```python
for provider in [BrowserbaseProvider(), SteelProvider()]:
    health = await provider.health_check()
    print(f"{health}: healthy={health.healthy}, latency={health.latency_ms}ms")
```

## Cost Tracking

The pool tracks per-provider costs. Each `ProviderSession` carries a `cost_estimate` field:

```python
session = await pool.get_session()
print(f"Estimated cost: ${session.cost_estimate:.4f}")
```

Cost estimates are provider-specific and reset when the pool is recreated.

## ProviderSession Data

A `ProviderSession` contains:

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Provider-scoped session identifier |
| `provider` | `str` | Provider name: `"browserbase"`, `"steel"`, or `"camofox"` |
| `cdp_url` | `str` | WebSocket CDP endpoint URL |
| `created_at` | `float` | Unix timestamp of creation |
| `last_active` | `float` | Unix timestamp of last use |
| `warm` | `bool` | Whether the session is warm (pooled for reuse) |
| `cost_estimate` | `float` | Estimated cost for this session |

## Provider Interface

All cloud providers implement `BaseProvider`:

```python
from browser_providers.base import BaseProvider, ProviderSession, ProviderHealth

class MyCustomProvider(BaseProvider):
    async def launch_sandbox(self, profile: str | None = None) -> ProviderSession:
        ...
    
    async def get_cdp_endpoint(self, session_id: str) -> str:
        ...
    
    async def mark_warm(self, session_id: str) -> None:
        ...
    
    async def close_session(self, session_id: str) -> None:
        ...
    
    async def health_check(self) -> ProviderHealth:
        ...
```

Adding a custom provider is a matter of implementing these 5 methods and passing the instance to `CloudSessionPool`.

## Provider Health Data

`ProviderHealth` contains:

| Field | Type | Description |
|-------|------|-------------|
| `healthy` | `bool` | Whether the provider is responsive |
| `latency_ms` | `float` | Response time in milliseconds |
| `error` | `str\|None` | Error message if unhealthy |
