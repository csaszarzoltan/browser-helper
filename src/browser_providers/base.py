"""Base provider abstraction for cloud browser services.

Defines the abstract base class that all cloud browser providers
must implement, along with shared data types.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProviderHealth:
    """Result of a provider health check."""

    healthy: bool
    latency_ms: float
    error: str | None = None


@dataclass
class ProviderSession:
    """Represents a sandboxed browser session from a cloud provider."""

    session_id: str
    provider: str  # "browserbase" | "steel" | "camofox"
    cdp_url: str
    created_at: float
    last_active: float
    warm: bool = False
    cost_estimate: float = 0.0


class BaseProvider(ABC):
    """Abstract base class for cloud browser providers.

    Every provider must implement the full lifecycle:
    launch sandbox → get CDP endpoint → (use) → mark warm → close.
    """

    @abstractmethod
    async def launch_sandbox(self, profile: str | None = None) -> ProviderSession:
        """Launch a new sandboxed browser instance.

        Args:
            profile: Optional profile name to configure the sandbox.

        Returns:
            A ProviderSession with connection details.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_cdp_endpoint(self, session_id: str) -> str:
        """Get the CDP WebSocket URL for an active session.

        Args:
            session_id: The session identifier.

        Returns:
            The CDP WebSocket URL string.
        """
        raise NotImplementedError

    @abstractmethod
    async def mark_warm(self, session_id: str) -> None:
        """Mark a session as warm (reusable without re-launch).

        Args:
            session_id: The session identifier.
        """
        raise NotImplementedError

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        """Close and clean up a sandboxed browser session.

        Args:
            session_id: The session identifier.
        """
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Run a health check against this provider.

        Returns:
            ProviderHealth with latency and status.
        """
        raise NotImplementedError
