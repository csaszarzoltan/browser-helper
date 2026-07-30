"""Browserbase cloud browser provider.

Integrates with Browserbase API to launch sandboxed browser sessions.
Uses BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID environment variables.
"""

import os
import time
from typing import Any

import httpx

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
        self._api_key = api_key or os.environ.get("BROWSERBASE_API_KEY")
        self._project_id = project_id or os.environ.get("BROWSERBASE_PROJECT_ID")
        self._api_base = api_base.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        Returns:
            Configured AsyncClient instance.
        """
        if self._client is None:
            headers: dict[str, str] = {
                "X-API-Key": self._api_key or "",
                "Content-Type": "application/json",
            }
            if self._project_id:
                headers["X-Project-Id"] = self._project_id
            self._client = httpx.AsyncClient(
                base_url=self._api_base,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    def _require_credentials(self) -> None:
        """Raise ValueError if API key is missing."""
        if not self._api_key:
            raise ValueError(
                "Browserbase API key is required. Set BROWSERBASE_API_KEY env var "
                "or pass api_key to the constructor."
            )

    async def launch_sandbox(self, profile: str | None = None) -> ProviderSession:
        """Launch a new Browserbase sandbox session.

        Args:
            profile: Optional profile/region hint (maps to Browserbase project).

        Returns:
            ProviderSession with CDP WebSocket URL.

        Raises:
            ValueError: If API key is not configured.
            httpx.HTTPError: If the API request fails.
        """
        self._require_credentials()
        client = self._get_client()

        payload: dict[str, Any] = {}
        if profile:
            payload["projectId"] = self._project_id
            payload["region"] = profile

        response = await client.post("/sessions", json=payload)
        response.raise_for_status()
        data = response.json()

        now = time.time()
        return ProviderSession(
            session_id=data.get("id", data.get("sessionId", "unknown")),
            provider="browserbase",
            cdp_url=data.get("cdpUrl", data.get("connectUrl", "")),
            created_at=now,
            last_active=now,
            warm=False,
            cost_estimate=0.0,
        )

    async def get_cdp_endpoint(self, session_id: str) -> str:
        """Get the CDP WebSocket URL from Browserbase.

        Args:
            session_id: Browserbase session ID.

        Returns:
            The WebSocket endpoint URL.

        Raises:
            ValueError: If API key is not configured.
            httpx.HTTPError: If the API request fails.
        """
        self._require_credentials()
        client = self._get_client()

        response = await client.get(f"/sessions/{session_id}")
        response.raise_for_status()
        data = response.json()

        return data.get("cdpUrl", data.get("connectUrl", ""))

    async def mark_warm(self, session_id: str) -> None:
        """Mark a Browserbase session as warm (keep-alive).

        Args:
            session_id: Session to mark warm.

        Raises:
            ValueError: If API key is not configured.
            httpx.HTTPError: If the API request fails.
        """
        self._require_credentials()
        client = self._get_client()
        response = await client.patch(f"/sessions/{session_id}", json={"keepAlive": True})
        response.raise_for_status()

    async def close_session(self, session_id: str) -> None:
        """Close a Browserbase session.

        Args:
            session_id: Session to close.

        Raises:
            ValueError: If API key is not configured.
            httpx.HTTPError: If the API request fails.
        """
        self._require_credentials()
        client = self._get_client()
        response = await client.delete(f"/sessions/{session_id}")
        response.raise_for_status()

    async def health_check(self) -> ProviderHealth:
        """Check Browserbase API health via a lightweight request.

        Returns:
            ProviderHealth with latency and status.
        """
        start = time.monotonic()
        try:
            client = self._get_client()
            response = await client.get("/health")
            latency_ms = (time.monotonic() - start) * 1000.0
            if response.status_code < 500:
                return ProviderHealth(healthy=True, latency_ms=latency_ms)
            return ProviderHealth(
                healthy=False,
                latency_ms=latency_ms,
                error=f"HTTP {response.status_code}",
            )
        except httpx.HTTPError as exc:
            latency_ms = (time.monotonic() - start) * 1000.0
            return ProviderHealth(
                healthy=False,
                latency_ms=latency_ms,
                error=str(exc),
            )