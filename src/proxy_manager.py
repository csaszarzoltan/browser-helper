"""
Proxy rotation manager for browser-helper.

Provides ProxyPool with CRUD, rotation strategies, health checking,
and JSON persistence for anti-detection proxy rotation.
"""

import asyncio
import json
import logging
import os
import random
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("browser-helper.proxy")


class ProxyParseError(ValueError):
    """Raised when a proxy URL cannot be parsed."""


# ── Scheme → type mapping for auto-detection ────────────────
_SCHEME_TO_TYPE = {
    "http": "HTTP",
    "https": "HTTPS",
    "socks5": "SOCKS5",
    "socks4": "SOCKS4",
    "socks": "SOCKS5",
}


def _detect_type(url: str) -> str:
    """Auto-detect proxy type from URL scheme."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    return _SCHEME_TO_TYPE.get(scheme, scheme.upper())


def _validate_url(url: str) -> str:
    """
    Validate a proxy URL.  Must have scheme, host, and port.
    Returns the normalized URL on success; raises ProxyParseError on failure.
    """
    if not url or not isinstance(url, str):
        raise ProxyParseError(f"Empty or invalid proxy URL: {url!r}")
    parsed = urlparse(url)
    if not parsed.scheme:
        raise ProxyParseError(f"Missing scheme in proxy URL: {url!r}")
    if not parsed.hostname:
        raise ProxyParseError(f"Missing hostname in proxy URL: {url!r}")
    if not parsed.port:
        raise ProxyParseError(f"Missing port in proxy URL: {url!r}")
    return url


@dataclass
class ProxyEntry:
    """A single proxy entry in the pool."""

    url: str
    type: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    healthy: bool = True
    last_checked: float = 0.0
    latency_ms: float = 0.0
    success_count: int = 0
    fail_count: int = 0
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        """Validate URL on construction."""
        _validate_url(self.url)


def _default_storage_path() -> str:
    """Return the default proxy pool JSON path."""
    data_dir = os.path.join(Path.home(), ".browser-helper")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "proxy_pool.json")


class ProxyPool:
    """
    Thread-safe proxy pool with rotation strategies, health checking,
    and JSON persistence.

    Strategies:
        round-robin (default) — cycle through healthy proxies sequentially
        random — pick a random healthy proxy
        sticky — pin a session to one proxy
        by-tag — round-robin within a tag group
    """

    # Number of consecutive failures before marking a proxy unhealthy/disabled
    FAILURE_THRESHOLD = 3

    def __init__(self, storage_path: str | None = None, max_size: int = 100):
        self.storage_path = storage_path or _default_storage_path()
        self.max_size = max_size
        self._proxies: dict[str, ProxyEntry] = {}
        self._round_robin_index: int = 0
        self._sticky_map: dict[str, str] = {}  # session_id → proxy_id

    # ── CRUD ─────────────────────────────────────────────────

    def add_proxy(
        self,
        url: str,
        proxy_type: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """
        Add a proxy to the pool.

        Returns the new proxy's UUID string.
        Raises ProxyParseError on bad URL, ValueError if the pool is full.
        """
        # Validate
        _validate_url(url)

        if len(self._proxies) >= self.max_size:
            raise ValueError(
                f"Pool full ({self.max_size}/{self.max_size} proxies)"
            )

        # Auto-detect type if not provided
        if proxy_type is None:
            proxy_type = _detect_type(url)

        entry = ProxyEntry(
            url=url,
            type=proxy_type,
            tags=tags or [],
        )
        self._proxies[entry.id] = entry
        self._save_atomically()
        return entry.id

    def remove_proxy(self, proxy_id: str) -> bool:
        """Remove a proxy by ID.  Returns True if found and removed."""
        if proxy_id in self._proxies:
            del self._proxies[proxy_id]
            # Clean up sticky references
            stale_sessions = [
                sid for sid, pid in self._sticky_map.items() if pid == proxy_id
            ]
            for sid in stale_sessions:
                del self._sticky_map[sid]
            self._save_atomically()
            return True
        return False

    def get_proxy(
        self,
        strategy: str = "round-robin",
        group: str | None = None,
        session_id: str | None = None,
        proxy_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Get a proxy entry as a dict (or by direct ID lookup).

        Args:
            strategy: Rotation strategy name.
            group:  Tag filter for by-tag strategy.
            session_id: Session identifier for sticky strategy.
            proxy_id: Direct ID lookup (takes precedence when provided).

        Returns:
            A dict of proxy fields, or None if not found / no healthy proxies.
        """
        # Direct ID lookup
        if proxy_id is not None:
            entry = self._proxies.get(proxy_id)
            return self._entry_to_dict(entry) if entry else None

        # Strategy-based selection
        available = self._get_healthy_enabled(group=group)

        if not available:
            return None

        if strategy == "round-robin":
            index = self._round_robin_index % len(available)
            self._round_robin_index = index + 1
            entry = available[index]

        elif strategy == "random":
            entry = random.choice(available)

        elif strategy == "sticky":
            if session_id and session_id in self._sticky_map:
                pid = self._sticky_map[session_id]
                entry = self._proxies.get(pid)
                if entry and entry.healthy and entry.enabled:
                    return self._entry_to_dict(entry)
                # Stale sticky entry — remove and reassign
                del self._sticky_map[session_id]

            if session_id:
                index = self._round_robin_index % len(available)
                self._round_robin_index = index + 1
                entry = available[index]
                self._sticky_map[session_id] = entry.id
            else:
                # No session_id — fall back to round-robin
                index = self._round_robin_index % len(available)
                self._round_robin_index = index + 1
                entry = available[index]

        elif strategy == "by-tag":
            if not group:
                # Fall back to round-robin on full pool
                index = self._round_robin_index % len(available)
                self._round_robin_index = index + 1
                entry = available[index]
            else:
                tagged = [e for e in available if group in e.tags]
                if not tagged:
                    return None
                index = self._round_robin_index % len(tagged)
                self._round_robin_index = index + 1
                entry = tagged[index]

        else:
            raise ValueError(f"Unknown rotation strategy: {strategy!r}")

        return self._entry_to_dict(entry)

    def get_pool(self) -> list[dict[str, Any]]:
        """Return all proxy entries as a list of dicts."""
        return [self._entry_to_dict(e) for e in self._proxies.values()]

    def clear(self) -> None:
        """Remove all proxies and reset internal state."""
        self._proxies.clear()
        self._sticky_map.clear()
        self._round_robin_index = 0

    # ── Health checks ─────────────────────────────────────────

    def health_check(self, proxy_id: str) -> dict[str, Any] | None:
        """
        Run a health check on a single proxy.

        Returns the health result dict (with 'healthy', 'latency_ms') or
        None if the proxy_id is not found.
        """
        entry = self._proxies.get(proxy_id)
        if not entry:
            return None

        start = time.time()
        healthy = False
        error = None
        try:
            import httpx
        except ImportError:
            httpx = None

        # Only attempt async health check when not already inside a running
        # event loop (FastAPI / pytest-asyncio context).
        try:
            asyncio.get_running_loop()
            in_running_loop = True
        except RuntimeError:
            in_running_loop = False

        if httpx is None:
            healthy = False
            error = "httpx is not installed — cannot health-check proxy"
        elif in_running_loop:
            # Inside a running event loop we cannot use asyncio.run(); perform
            # the probe with the synchronous httpx client. This blocks the
            # loop briefly but performs a REAL check (review C5) instead of
            # marking the proxy unhealthy without checking.
            try:
                with httpx.Client(proxy=entry.url, timeout=10.0) as client:
                    resp = client.get("https://httpbin.org/ip")
                    healthy = resp.status_code == 200
            except Exception as exc:  # noqa: BLE001 — probe failure means unhealthy
                error = str(exc)
                healthy = False
        else:
            try:
                async def _check() -> bool:
                    try:
                        async with httpx.AsyncClient(
                            proxy=entry.url,
                            timeout=10.0,
                        ) as client:
                            resp = await client.get("https://httpbin.org/ip")
                            return resp.status_code == 200
                    except Exception:
                        return False

                healthy = asyncio.run(_check())
            except Exception as exc:
                error = str(exc)
                healthy = False

        elapsed = (time.time() - start) * 1000
        entry.healthy = healthy
        entry.last_checked = time.time()
        entry.latency_ms = round(elapsed, 1)

        result: dict[str, Any] = {
            "proxy_id": proxy_id,
            "healthy": healthy,
            "latency_ms": entry.latency_ms,
            "last_checked": entry.last_checked,
        }
        if error:
            result["error"] = error
        return result

    def health_check_all(self) -> list[dict[str, Any]]:
        """Run health check on all proxies.  Returns list of result dicts."""
        results = []
        for pid in list(self._proxies.keys()):
            result = self.health_check(pid)
            if result:
                results.append(result)
        return results

    # ── Non-blocking health checks for async callers (review R3) ──────

    async def health_check_async(self, proxy_id: str) -> dict[str, Any] | None:
        """Non-blocking health check using httpx.AsyncClient (R3).

        Safe to call from within a running event loop — never stalls the
        loop.  Returns the same result shape as the sync ``health_check``.
        """
        entry = self._proxies.get(proxy_id)
        if not entry:
            return None

        start = time.time()
        healthy = False
        error = None

        try:
            import httpx as _httpx
        except ImportError:
            _httpx = None

        if _httpx is None:
            healthy = False
            error = "httpx is not installed — cannot health-check proxy"
        else:
            try:
                async with _httpx.AsyncClient(
                    proxy=entry.url,
                    timeout=10.0,
                ) as client:
                    resp = await client.get("https://httpbin.org/ip")
                    healthy = resp.status_code == 200
            except Exception as exc:  # noqa: BLE001 — probe failure = unhealthy
                error = str(exc)
                healthy = False

        return self._finalize_health(entry, healthy, error, start)

    async def health_check_all_async(self) -> list[dict[str, Any]]:
        """Non-blocking health check on all proxies (R3)."""
        results: list[dict[str, Any]] = []
        for pid in list(self._proxies.keys()):
            result = await self.health_check_async(pid)
            if result:
                results.append(result)
        return results

    def _finalize_health(
        self,
        entry: ProxyEntry,
        healthy: bool,
        error: str | None,
        start: float,
    ) -> dict[str, Any]:
        """Update entry state and build the standard result dict."""
        elapsed = (time.time() - start) * 1000
        entry.healthy = healthy
        entry.last_checked = time.time()
        entry.latency_ms = round(elapsed, 1)

        result: dict[str, Any] = {
            "proxy_id": entry.id,
            "healthy": healthy,
            "latency_ms": entry.latency_ms,
            "last_checked": entry.last_checked,
        }
        if error:
            result["error"] = error
        return result

    def report_success(self, proxy_id: str) -> None:
        """Record a successful request for a proxy."""
        entry = self._proxies.get(proxy_id)
        if not entry:
            return
        entry.success_count += 1
        # Restore health if it was unhealthy
        if not entry.healthy:
            entry.healthy = True
        if not entry.enabled:
            entry.enabled = True

    def report_failure(self, proxy_id: str) -> None:
        """Record a failed request for a proxy."""
        entry = self._proxies.get(proxy_id)
        if not entry:
            return
        entry.fail_count += 1
        # Mark unhealthy after threshold
        if entry.fail_count >= self.FAILURE_THRESHOLD:
            entry.healthy = False
            entry.enabled = False

    # ── Stats ──────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return usage statistics for the pool."""
        proxies = list(self._proxies.values())
        total = len(proxies)
        healthy = sum(1 for p in proxies if p.healthy)
        unhealthy = total - healthy
        total_requests = sum(p.success_count + p.fail_count for p in proxies)
        total_success = sum(p.success_count for p in proxies)
        total_failures = sum(p.fail_count for p in proxies)

        # Breakdown by tag
        by_tag: dict[str, int] = {}
        for p in proxies:
            for tag in p.tags:
                by_tag[tag] = by_tag.get(tag, 0) + 1

        return {
            "total": total,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "total_requests": total_requests,
            "total_success": total_success,
            "total_failures": total_failures,
            "by_tag": by_tag,
        }

    # ── Persistence ────────────────────────────────────────────

    def save(self) -> None:
        """Persist the pool to JSON (atomic write)."""
        self._save_atomically()

    def load(self) -> None:
        """Load the pool from JSON.  Missing or corrupt file → empty pool."""
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupted proxy pool file: %s", self.storage_path)
            return

        self._proxies.clear()
        for item in data:
            try:
                entry = ProxyEntry(
                    id=item.get("id", str(uuid.uuid4())),
                    url=item["url"],
                    type=item.get("type", _detect_type(item["url"])),
                    tags=item.get("tags", []),
                    enabled=item.get("enabled", True),
                    healthy=item.get("healthy", True),
                    last_checked=item.get("last_checked", 0.0),
                    latency_ms=item.get("latency_ms", 0.0),
                    success_count=item.get("success_count", 0),
                    fail_count=item.get("fail_count", 0),
                    created_at=item.get("created_at", time.time()),
                )
                self._proxies[entry.id] = entry
            except (KeyError, ProxyParseError, TypeError) as exc:
                logger.warning("Skipping corrupt proxy entry: %s", exc)

    # ── Internal helpers ───────────────────────────────────────

    def _entry_to_dict(self, entry: ProxyEntry) -> dict[str, Any]:
        """Convert a ProxyEntry to a plain dict."""
        return {
            "id": entry.id,
            "url": entry.url,
            "type": entry.type,
            "tags": entry.tags,
            "enabled": entry.enabled,
            "healthy": entry.healthy,
            "last_checked": entry.last_checked,
            "latency_ms": entry.latency_ms,
            "success_count": entry.success_count,
            "fail_count": entry.fail_count,
            "created_at": entry.created_at,
        }

    def _get_healthy_enabled(
        self, group: str | None = None
    ) -> list[ProxyEntry]:
        """Return list of healthy + enabled proxies, optionally filtered by tag."""
        candidates = [
            e for e in self._proxies.values() if e.healthy and e.enabled
        ]
        if group:
            candidates = [e for e in candidates if group in e.tags]
        return candidates

    def _save_atomically(self) -> None:
        """Write pool data to a temp file, then atomically rename."""
        data = []
        for entry in self._proxies.values():
            data.append(self._entry_to_dict(entry))

        dir_path = os.path.dirname(self.storage_path)
        os.makedirs(dir_path, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix="proxy_pool_",
            dir=dir_path,
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.storage_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
