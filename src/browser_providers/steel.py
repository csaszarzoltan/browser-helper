"""Steel cloud browser provider.

Integrates with Steel API to launch sandboxed browser sessions.
Uses STEEL_API_KEY environment variable.
"""

from browser_providers.base import BaseProvider, ProviderHealth, ProviderSession


class SteelProvider(BaseProvider):
    """Provider implementation for Steel managed browsers.

    API Base URL: https://api.steel.dev/v2/sessions
    Requires env: STEEL_API_KEY
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str = "https://api.steel.dev/v2/sessions",
    ) -> None:
        """Initialize Steel provider.

        Args:
            api_key: Steel API key. Falls back to STEEL_API_KEY env var.
            api_base: API base URL override.
        """
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    async def launch_sandbox(self, profile: str | None = None) -> ProviderSession:
        """Launch a new Steel sandbox session.

        Args:
            profile: Optional profile/region hint.

        Returns:
            ProviderSession with CDP WebSocket URL.
        """
        raise NotImplementedError

    async def get_cdp_endpoint(self, session_id: str) -> str:
        """Get the CDP WebSocket URL from Steel.

        Args:
            session_id: Steel session ID.

        Returns:
            The WebSocket endpoint URL.
        """
        raise NotImplementedError

    async def mark_warm(self, session_id: str) -> None:
        """Mark a Steel session as warm.

        Args:
            session_id: Session to mark warm.
        """
        raise NotImplementedError

    async def close_session(self, session_id: str) -> None:
        """Close a Steel session.

        Args:
            session_id: Session to close.
        """
        raise NotImplementedError

    async def health_check(self) -> ProviderHealth:
        """Check Steel API health."""
        raise NotImplementedError
