"""API key authentication and rate limiting for browser-helper.

Provides ``verify_api_key()`` middleware and an in-memory rate limiter
for per-IP request throttling (P0-B).
"""

import os
import time
from collections import defaultdict

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Read from environment, fall back to a default (not secret — overridable).
API_KEY = os.environ.get("BROWSER_HELPER_API_KEY", "dev-key-please-change")

RATE_LIMIT_REQUESTS = 100  # max requests per window
RATE_LIMIT_WINDOW = 60     # window in seconds


# ---------------------------------------------------------------------------
# IP-address-based rate limiter (sliding window)
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple in-memory sliding-window rate limiter keyed by IP address."""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, ip: str) -> bool:
        """Check whether *ip* is within the rate limit.

        Returns ``True`` if the request is allowed, ``False`` if rate-limited.
        """
        now = time.monotonic()
        # Prune stale entries
        cutoff = now - self.window_seconds
        self._buckets[ip] = [t for t in self._buckets[ip] if t > cutoff]

        bucket = self._buckets[ip]
        if len(bucket) >= self.max_requests:
            return False

        bucket.append(now)
        return True


# Singleton — importable by middleware
rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# API key verification
# ---------------------------------------------------------------------------


def verify_api_key(header_value: str | None) -> str | None:
    """Verify the ``X-API-Key`` header value.

    Args:
        header_value: The value of the ``X-API-Key`` header, or ``None``
            if the header was not sent.

    Returns:
        ``None`` if the key is valid, or an error message string describing
        why the request was rejected.
    """
    if not header_value or header_value != API_KEY:
        return "Missing or invalid API key"
    return None
