"""Browserbase cloud browser provider.

Integrates with Browserbase API to launch sandboxed browser sessions.
Uses BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID environment variables.
"""

from browser_providers.base import BaseProvider, ProviderHealth, ProviderSession


class BrowserbaseProvider(BaseProvider):
    """Provider implementation for Browserbase managed browsers.

    API Base URL: https://www.browserbase.com/api/v1
    Requires env: BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID
    """

    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
        api_base: str = "https://www.browserbase.com/api/v1",
    ) -> None:
        """Initialize Browserbase provider.

        Args:
            api_key: Browserbase API key. Falls back to BROWSERBASE_API_KEY env var.
            project_id: Browserbase project ID. Falls back to BROWSERBASE_PROJECT_ID env var.
            api_base: API base URL override.
        """
        self._api_key = api_key
        self._project_id = project_id
        self._api_base = api_base.rstrip("/")

    async def launch_sandbox(self, profile: str | None = None) -> ProviderSession:
        """Launch a new Browserbase sandbox session.

        Args:
            profile: Optional profile/region hint.

        Returns:
            ProviderSession with CDP WebSocket URL.
        """
        raise NotImplementedError

    async def get_cdp_endpoint(self, session_id: str) -> str:
        """Get the CDP WebSocket URL from Browserbase.

        Args:
            session_id: Browserbase session ID.

        Returns:
            The WebSocket endpoint URL.
        """
        raise NotImplementedError

    async def mark_warm(self, session_id: str) -> None:
        """Mark a Browserbase session as warm.

        Args:
            session_id: Session to mark warm.
        """
        raise NotImplementedError

    async def close_session(self, session_id: str) -> None:
        """Close a Browserbase session.

        Args:
            session_id: Session to close.
        """
        raise NotImplementedError

    async def health_check(self) -> ProviderHealth:
        """Check Browserbase API health."""
        raise NotImplementedError
