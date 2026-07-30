"""Camoufox cloud browser provider.

P0: stub implementation only. Camoufox is a Firefox-based managed browser
that runs as a local subprocess. Full integration deferred to P2.
"""

from browser_providers.base import BaseProvider, ProviderHealth, ProviderSession


class CamofoxProvider(BaseProvider):
    """Provider implementation for Camoufox managed browsers.

    P0: Stub — all methods raise NotImplementedError.
    P2: Full binary management with subprocess lifecycle.
    """

    def __init__(self, binary_path: str | None = None) -> None:
        """Initialize Camoufox provider.

        Args:
            binary_path: Optional path to Camoufox binary.
                         Falls back to CAMOFOX_BINARY_PATH env var.
        """
        self._binary_path = binary_path

    async def launch_sandbox(self, profile: str | None = None) -> ProviderSession:
        """Launch a new Camoufox sandbox session.

        P0 stub — raises NotImplementedError.
        """
        raise NotImplementedError

    async def get_cdp_endpoint(self, session_id: str) -> str:
        """Get the CDP endpoint for a Camoufox session.

        P0 stub — raises NotImplementedError.
        """
        raise NotImplementedError

    async def mark_warm(self, session_id: str) -> None:
        """Mark a Camoufox session as warm.

        P0 stub — raises NotImplementedError.
        """
        raise NotImplementedError

    async def close_session(self, session_id: str) -> None:
        """Close a Camoufox session.

        P0 stub — raises NotImplementedError.
        """
        raise NotImplementedError

    async def health_check(self) -> ProviderHealth:
        """Check Camoufox availability.

        P0 stub — raises NotImplementedError.
        """
        raise NotImplementedError
