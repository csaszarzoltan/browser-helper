"""Example: Cloud browser provider integration.

Demonstrates using the BrowserbaseProvider, SteelProvider, and
CloudSessionPool for launching cloud-hosted browser sessions.

This example does NOT require a running Browser Helper server —
it accesses the provider classes directly.

Requires one of: BROWSERBASE_API_KEY, STEEL_API_KEY env vars.

Usage:
    # With Browserbase
    BROWSERBASE_API_KEY=bb_... python examples/cloud_browser.py

    # With Steel
    STEEL_API_KEY=steel_... python examples/cloud_browser.py

The demo launches a sandbox, retrieves the CDP endpoint URL,
checks health, and cleans up.
"""

from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    """Run the cloud provider demo."""
    available_providers: list[str] = []

    if os.environ.get("BROWSERBASE_API_KEY"):
        available_providers.append("browserbase")
    if os.environ.get("STEEL_API_KEY"):
        available_providers.append("steel")

    if not available_providers:
        print(
            "No cloud provider credentials found.\n"
            "Set BROWSERBASE_API_KEY or STEEL_API_KEY to run this demo.\n"
            "Falling back to showing the abstract class hierarchy."
        )
        _show_class_hierarchy()
        return 0

    print(f"Available providers: {', '.join(available_providers)}")
    print()

    # We import here so the demo works even without the env vars
    from browser_providers.base import BaseProvider, ProviderHealth, ProviderSession

    providers: list[BaseProvider] = []

    if "browserbase" in available_providers:
        from browser_providers.browserbase import BrowserbaseProvider

        bb = BrowserbaseProvider()
        providers.append(bb)
        print("✓ BrowserbaseProvider initialised")
    if "steel" in available_providers:
        from browser_providers.steel import SteelProvider

        steel = SteelProvider()
        providers.append(steel)
        print("✓ SteelProvider initialised")

    from browser_providers.session_pool import CloudSessionPool

    pool = CloudSessionPool(
        providers=providers,
        min_warm=1,
        max_warm=3,
        ttl_seconds=300,
    )

    # Check provider health
    for provider in providers:
        try:
            health: ProviderHealth = await provider.health_check()
            print(
                f"  {provider.__class__.__name__}: "
                f"healthy={health.healthy}, "
                f"latency={health.latency_ms:.0f}ms"
                + (f", error={health.error}" if health.error else "")
            )
        except (ConnectionError, TimeoutError, ValueError) as exc:
            print(f"  {provider.__class__.__name__}: health check failed — {exc}")

    # Launch a sandbox session
    try:
        session: ProviderSession = await pool.get_session()
        print("\n✓ Session launched:")
        print(f"  session_id: {session.session_id}")
        print(f"  provider:   {session.provider}")
        print(f"  cdp_url:    {session.cdp_url}")
        print(f"  cost:       ${session.cost_estimate:.4f}")
        print(f"  warm:       {session.warm}")
    except (ConnectionError, TimeoutError, ValueError) as exc:
        print(f"\n✗ Session launch failed — {exc}")
        return 1

    # Close the session
    try:
        await pool.get_session().close_session(session.session_id)  # type: ignore[union-attr]
        print(f"✓ Session {session.session_id} closed")
    except (ConnectionError, TimeoutError, ValueError) as exc:
        # Expected if the provider requires real credentials
        print(f"  Session close: {exc}")

    return 0


def _show_class_hierarchy() -> None:
    """Show the abstract class hierarchy when no credentials are available."""
    print("  BaseProvider (ABC)")
    print("    ├── BrowserbaseProvider  — requires BROWSERBASE_API_KEY")
    print("    ├── SteelProvider        — requires STEEL_API_KEY")
    print("    └── CamofoxProvider      — P0 stub (raises NotImplementedError)")
    print()
    print("  CloudSessionPool")
    print("    ├── get_session()        — prefer warm, fallback to new")
    print("    ├── min_warm / max_warm  — pool scaling config")
    print("    └── ttl_seconds          — idle session expiry")
    print()
    print("  ProviderSession")
    print("    ├── session_id           — provider-scoped identifier")
    print("    ├── provider             — 'browserbase' | 'steel' | 'camofox'")
    print("    ├── cdp_url              — WebSocket CDP endpoint")
    print("    ├── warm                 — pooled for reuse?")
    print("    └── cost_estimate        — estimated session cost")
    print()
    print("  FallbackResult")
    print("    ├── success              — session obtained?")
    print("    ├── session              — ProviderSession or None")
    print("    ├── chain                — providers attempted in order")
    print("    └── errors               — per-step error messages")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
