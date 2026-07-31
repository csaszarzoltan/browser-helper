"""
ProxyRotationManager — thin wrapper around ProxyPool with env-var auto-load
and health-check rotation strategy (P0.3).

Interface:
  __init__(pool=None)      — create or wrap a ProxyPool
  load_from_env() -> int   — read PROXY_LIST / PROPROXY_FILE env vars (stub)
  get_proxy(strategy, ...) — delegate with added "health-check" strategy (stub)
  add_proxy / remove_proxy / get_pool / clear / get_stats
  health_check / health_check_all
"""

import logging
import os
from typing import Any

from proxy_manager import ProxyPool

logger = logging.getLogger("browser-helper.proxy-rotation")


class ProxyRotationManager:
    """Thin wrapper around ProxyPool with env-var auto-load and health-check strategy."""

    def __init__(self, pool: ProxyPool | None = None):
        if pool is None:
            self._pool = ProxyPool()
        elif isinstance(pool, ProxyPool):
            self._pool = pool
        else:
            raise TypeError(
                f"Expected ProxyPool or None, got {type(pool).__name__}"
            )

    @property
    def pool(self) -> ProxyPool:
        """Expose wrapped ProxyPool for direct access."""
        return self._pool

    # ── New behaviour ──────────────────────────────────────────

    def load_from_env(self) -> int:
        """Read PROXY_LIST and/or PROXY_FILE env vars, add proxies, return count added.

        PROXY_LIST: comma-separated proxy URLs.
        PROXY_FILE: path to a file with one proxy URL per line (# comments and blank lines ignored).

        Returns the total number of proxies added.
        """
        added = 0

        # Load from PROXY_LIST env var (comma-separated URLs)
        proxy_list = os.environ.get("PROXY_LIST", "").strip()
        if proxy_list:
            for url in proxy_list.split(","):
                url = url.strip()
                if not url:
                    continue
                try:
                    self._pool.add_proxy(url)
                    added += 1
                except Exception as exc:  # noqa: BLE001 — one bad URL must not abort env loading
                    logger.warning("Bad proxy URL in PROXY_LIST: %s — %s", url, exc)

        # Load from PROXY_FILE env var (one URL per line)
        proxy_file = os.environ.get("PROXY_FILE", "").strip()
        if proxy_file:
            try:
                with open(proxy_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        try:
                            self._pool.add_proxy(line)
                            added += 1
                        except Exception as exc:  # noqa: BLE001 — one bad line must not abort env loading
                            logger.warning("Bad proxy URL in PROXY_FILE: %s — %s", line, exc)
            except FileNotFoundError:
                logger.warning("PROXY_FILE not found: %s", proxy_file)
            except OSError as exc:
                logger.warning("Cannot read PROXY_FILE %s: %s", proxy_file, exc)

        return added

    def get_proxy(self, strategy: str = "round-robin", **kwargs: Any) -> dict[str, Any] | None:
        """Get a healthy proxy.

        Supports all ProxyPool strategies plus:
          "health-check" — picks the proxy with the lowest latency_ms
                          (falls back to round-robin if no latencies recorded yet).
        """
        if strategy == "health-check":
            return self._health_check_strategy(**kwargs)
        return self._pool.get_proxy(strategy=strategy, **kwargs)

    def _health_check_strategy(self, **kwargs: Any) -> dict[str, Any] | None:
        """Pick the proxy with the lowest latency_ms among healthy, enabled proxies.

        Falls back to round-robin if no proxy has been checked yet.
        """
        pool_entries = self._pool.get_pool()
        # Filter to healthy, enabled proxies that have been checked (latency_ms > 0)
        checked = [
            p for p in pool_entries
            if p.get("healthy", True) and p.get("enabled", True) and p.get("latency_ms", 0) > 0
        ]
        if checked:
            # Pick the one with lowest latency_ms
            checked.sort(key=lambda p: p.get("latency_ms", float("inf")))
            best_id = checked[0].get("id")
            # Get the proxy from the pool by its id
            available = self._pool.get_pool()
            for entry in available:
                if entry.get("id") == best_id:
                    return entry
        # Fall back to round-robin if no checked proxies available
        return self._pool.get_proxy(strategy="round-robin", **kwargs)

    # ── Delegated methods (work via wrapped ProxyPool) ─────────────

    def add_proxy(self, url: str, **kwargs: Any) -> str:
        """Add a proxy to the pool. Returns the new proxy's UUID."""
        return self._pool.add_proxy(url, **kwargs)

    def remove_proxy(self, proxy_id: str) -> bool:
        """Remove a proxy by ID. Returns True if found and removed."""
        return self._pool.remove_proxy(proxy_id)

    def get_pool(self) -> list[dict[str, Any]]:
        """Return all proxy entries as a list of dicts."""
        return self._pool.get_pool()

    def clear(self) -> None:
        """Remove all proxies and reset internal state."""
        self._pool.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return usage statistics for the pool."""
        return self._pool.get_stats()

    def health_check(self, proxy_id: str) -> dict[str, Any] | None:
        """Run a health check on a single proxy. Returns result dict or None."""
        return self._pool.health_check(proxy_id)

    def health_check_all(self) -> list[dict[str, Any]]:
        """Run health check on all proxies. Returns list of result dicts."""
        return self._pool.health_check_all()
