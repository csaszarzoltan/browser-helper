"""Cloud session pool and fallback chain.

Manages warm cloud browser sessions with auto-scaling, TTL expiry,
cost tracking, and fallback chain for provider failures.
"""

from dataclasses import dataclass, field

from browser_providers.base import BaseProvider, ProviderSession


@dataclass
class FallbackResult:
    """Result of a fallback chain attempt."""

    success: bool
    session: ProviderSession | None = None
    chain: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CloudSessionPool:
    """Manages a pool of warm cloud browser sessions.

    Maintains a configurable number of warm (pre-launched) sessions,
    automatically scales up/down, expires idle sessions past TTL,
    and tracks per-provider costs.
    """

    def __init__(
        self,
        providers: list[BaseProvider] | None = None,
        min_warm: int = 1,
        max_warm: int = 5,
        ttl_seconds: int = 300,
    ) -> None:
        """Initialize the cloud session pool.

        Args:
            providers: List of available provider instances.
            min_warm: Minimum number of warm sessions to maintain.
            max_warm: Maximum number of warm sessions allowed.
            ttl_seconds: Idle session TTL in seconds.
        """
        self._providers = providers or []
        self._sessions: dict[str, ProviderSession] = {}
        self.min_warm = min_warm
        self.max_warm = max_warm
        self.ttl_seconds = ttl_seconds
        self._costs: dict[str, float] = {}

    async def get_session(self, provider: str | None = None) -> ProviderSession:
        """Get a session, optionally filtered by provider name.

        Args:
            provider: Optional provider name to filter by.

        Returns:
            A ProviderSession from the pool (warm) or newly launched.
        """
        raise NotImplementedError

    async def release_session(self, session_id: str) -> None:
        """Release a session back to the warm pool.

        Args:
            session_id: Session to release.
        """
        raise NotImplementedError

    async def scale_pool(self, target_warm: int) -> None:
        """Scale the warm pool to a target size.

        Args:
            target_warm: Desired number of warm sessions.
        """
        raise NotImplementedError

    async def run_health_checks(self) -> dict:
        """Run health checks against all registered providers.

        Returns:
            Dict mapping provider name to ProviderHealth result.
        """
        raise NotImplementedError

    async def get_costs(self) -> dict:
        """Get cumulative cost breakdown per provider.

        Returns:
            Dict with per-provider costs.
        """
        raise NotImplementedError


class FallbackChain:
    """Ordered fallback chain for cloud browser providers.

    Falls back through providers in order, then to local headless Chrome,
    returning the first successful result or a diagnostic error.
    """

    def __init__(self, providers: list[BaseProvider]) -> None:
        """Initialize the fallback chain.

        Args:
            providers: Ordered list of providers to try.
                       Last entry should be a local headless fallback.
        """
        self._providers = providers

    async def execute(self, profile: str | None = None) -> FallbackResult:
        """Execute the fallback chain.

        Tries each provider in order. Returns the first successful session.

        Args:
            profile: Optional profile for session configuration.

        Returns:
            FallbackResult with the successful session or error diagnostics.
        """
        raise NotImplementedError

    async def execute_with_local_fallback(
        self, profile: str | None = None,
    ) -> FallbackResult:
        """Execute fallback chain with local headless Chrome as last resort.

        Args:
            profile: Optional profile for session configuration.

        Returns:
            FallbackResult with session or diagnostics.
        """
        raise NotImplementedError
