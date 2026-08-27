"""Domain-level navigation throttle.

Protects external sites (Google, GitHub, ...) from hammering when multiple
systems share one browser-helper instance: no more than one navigation per
domain within ``min_interval`` seconds.

Design:
- Thread-safe (asyncio tasks share the service's event loop; the REST
  endpoints and MCP tool tasks all funnel through ``run_op``).
- Per-domain timestamps keep different sites independent.
- The interval is read from the SettingsManager at call time, so a settings
  change takes effect immediately without a restart.
- ``force`` bypasses the wait (used by tests and by watchdog/health checks
  that must never be delayed).

The throttle is *domain-wide*, not per-session: multiple sessions or clients
hitting the same domain are throttled together, which is exactly the
hammering protection requested.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Default minimum gap between two navigations to the same domain (seconds).
# Overridable via settings.json ``domain_min_interval_sec``.
DEFAULT_MIN_INTERVAL_SEC = 4.0


class DomainThrottle:
    """Rate-limits navigations per domain (netloc), configurable interval."""

    def __init__(self) -> None:
        self._last: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    @staticmethod
    def _domain_of(url: str) -> str:
        """Extract the domain (netloc, lowercased, port stripped) from a URL.

        ``https://google.com:8080`` and ``https://google.com`` are the same
        site for throttling purposes, so the port is stripped.
        """
        try:
            netloc = urlsplit(url).netloc.lower()
        except (ValueError, AttributeError):
            return ""
        if not netloc:
            return ""
        # Strip the port (IPv4 + bracket IPv6 forms).
        if netloc.startswith("["):
            end = netloc.find("]")
            return netloc[1:end] if end > 0 else netloc
        return netloc.split(":", 1)[0]

    async def wait(self, url: str, min_interval: float | None = None, *, force: bool = False) -> float:
        """Wait until a navigation to *url*'s domain is allowed.

        Returns the number of seconds actually waited (0 if immediate).
        ``min_interval`` overrides the default; ``None`` uses
        ``DEFAULT_MIN_INTERVAL_SEC``. ``force=True`` skips the wait entirely
        (tests / internal checks).
        """
        if force:
            return 0.0
        interval = DEFAULT_MIN_INTERVAL_SEC if min_interval is None else min_interval
        if interval <= 0:
            return 0.0
        domain = self._domain_of(url)
        if not domain:
            return 0.0  # no domain (data:, about:, ...) — nothing to protect
        async with self._lock:
            now = time.monotonic()
            wait = interval - (now - self._last[domain])
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._last[domain] = now
            return max(0.0, wait)

    def last_hit(self, domain: str) -> float:
        """Monotonic timestamp of the last navigation to *domain* (0.0 if never)."""
        return self._last.get(domain.lower(), 0.0)

    def snapshot(self) -> dict:
        """Return a JSON-serializable snapshot of throttle state."""
        return {"per_domain": dict(self._last), "default_min_interval": DEFAULT_MIN_INTERVAL_SEC}

    def reset(self) -> None:
        """Clear all history (tests, settings change)."""
        self._last.clear()


# Singleton used by the service (and imported by tests).
domain_throttle = DomainThrottle()
