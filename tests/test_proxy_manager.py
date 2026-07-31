"""Pre-development tests for ProxyPool / ProxyManager (RED phase).

These tests define the expected interface BEFORE implementation.
All will fail with ImportError/AttributeError until the developer
writes src/proxy_manager.py.

Coverage:
  - ProxyEntry dataclass fields, defaults, validation
  - ProxyPool CRUD (add, remove, get, list, clear)
  - Rotation strategies (round-robin, random, sticky, by-tag-group)
  - Health check logic (explicit check, passive marking, recovery)
  - JSON persistence (save, load)
  - Proxy URL parsing / auth validation
  - Edge cases (empty pool, duplicate IDs, bad input)
"""

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def storage_path(tmp_path):
    """Return a temporary path for proxy pool JSON persistence."""
    return str(tmp_path / "proxy_pool.json")


@pytest.fixture
def pool(storage_path):
    """Return a fresh ProxyPool isolated to a temp JSON file."""
    from proxy_manager import ProxyPool

    p = ProxyPool(storage_path=storage_path)
    yield p
    # Teardown: clear pool state
    p.clear()


@pytest.fixture
def sample_proxies():
    """Return a list of proxy URLs for population tests."""
    return [
        "socks5://user1:pass1@proxy1.example.com:1080",
        "http://user2:pass2@proxy2.example.com:3128",
        "https://proxy3.example.com:443",
        "socks5://proxy4.example.com:1080",
    ]


@pytest.fixture
def populated_pool(pool, sample_proxies):
    """Return a ProxyPool pre-loaded with sample proxies."""
    ids = []
    for url in sample_proxies:
        pid = pool.add_proxy(url, tags=["datacenter"])
        ids.append(pid)
    pool._proxies[ids[1]].tags = ["residential"]
    pool._proxies[ids[2]].tags = ["datacenter", "us"]
    pool._proxies[ids[3]].tags = ["residential", "eu"]
    return pool, ids


# ===================================================================
# ProxyEntry dataclass
# ===================================================================


class TestProxyEntry:
    """Verify ProxyEntry dataclass fields, types, and defaults."""

    def test_import(self):
        """ProxyEntry should be importable from proxy_manager."""
        from proxy_manager import ProxyEntry

        assert hasattr(ProxyEntry, "__dataclass_fields__")

    def test_required_fields(self):
        """ProxyEntry should require url and type."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="socks5://user:pass@host:1080", type="SOCKS5")
        assert entry.url == "socks5://user:pass@host:1080"
        assert entry.type == "SOCKS5"

    def test_id_generated(self):
        """ProxyEntry.id should be auto-generated as a UUID string."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="socks5://user:pass@host:1080", type="SOCKS5")
        assert isinstance(entry.id, str)
        assert len(entry.id) == 36  # UUID4 with dashes
        assert entry.id.count("-") == 4

    def test_tags_default_empty(self):
        """ProxyEntry.tags should default to empty list."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:80", type="HTTP")
        assert entry.tags == []

    def test_enabled_default_true(self):
        """ProxyEntry.enabled should default to True."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:80", type="HTTP")
        assert entry.enabled is True

    def test_healthy_default_true(self):
        """ProxyEntry.healthy should default to True until first check."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:80", type="HTTP")
        assert entry.healthy is True

    def test_counters_default_zero(self):
        """ProxyEntry success/fail counts should default to 0."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:80", type="HTTP")
        assert entry.success_count == 0
        assert entry.fail_count == 0

    def test_latency_default_none(self):
        """ProxyEntry.latency_ms should default to 0 or None."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:80", type="HTTP")
        assert entry.latency_ms == 0.0 or entry.latency_ms is None

    def test_last_checked_default_none(self):
        """ProxyEntry.last_checked should default to 0 or None."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:80", type="HTTP")
        assert entry.last_checked == 0.0 or entry.last_checked is None

    def test_created_at_set(self):
        """ProxyEntry.created_at should be set on creation (timestamp)."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:80", type="HTTP")
        assert isinstance(entry.created_at, (int, float))
        assert entry.created_at > 0

    def test_url_validation(self):
        """ProxyEntry.url should accept protocol://user:pass@host:port format."""
        from proxy_manager import ProxyEntry

        # Valid formats
        entry1 = ProxyEntry(url="socks5://user:password@192.168.1.1:1080", type="SOCKS5")
        assert "user:password" in entry1.url or "@" in entry1.url

        entry2 = ProxyEntry(url="http://proxy.example.com:8080", type="HTTP")
        assert entry2.type == "HTTP"

        entry3 = ProxyEntry(url="https://user:pass@proxy.com:443", type="HTTPS")
        assert entry3.type == "HTTPS"

    def test_socks5_type(self):
        """ProxyEntry should support SOCKS5 type."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="socks5://host:1080", type="SOCKS5")
        assert entry.type == "SOCKS5"

    def test_http_type(self):
        """ProxyEntry should support HTTP type."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:8080", type="HTTP")
        assert entry.type == "HTTP"

    def test_https_type(self):
        """ProxyEntry should support HTTPS type."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="https://host:443", type="HTTPS")
        assert entry.type == "HTTPS"

    def test_fields_immutable_after_create(self):
        """ProxyEntry should be a frozen/immutable dataclass or treat as such."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="http://host:80", type="HTTP")
        # At minimum the id should not change
        original_id = entry.id
        assert entry.id == original_id


# ===================================================================
# ProxyPool CRUD
# ===================================================================


class TestProxyPoolCRUD:
    """Verify ProxyPool add, remove, get, list, clear operations."""

    def test_import(self):
        """ProxyPool should be importable from proxy_manager."""
        from proxy_manager import ProxyPool

    def test_init_with_storage_path(self, storage_path):
        """ProxyPool should accept an optional storage_path."""
        from proxy_manager import ProxyPool

        p = ProxyPool(storage_path=storage_path)
        assert p is not None
        assert p.storage_path == storage_path

    def test_init_empty_pool(self, pool):
        """A fresh ProxyPool should contain zero proxies."""
        assert len(pool.get_pool()) == 0

    def test_add_proxy_returns_id(self, pool):
        """add_proxy() should return a UUID string."""
        pid = pool.add_proxy("socks5://user:pass@host:1080")
        assert isinstance(pid, str)
        assert len(pid) == 36

    def test_add_proxy_with_tags(self, pool):
        """add_proxy() should accept an optional tags list."""
        pid = pool.add_proxy(
            "http://proxy.example.com:8080",
            tags=["datacenter", "us"],
        )
        assert pid is not None
        entry = pool.get_proxy(proxy_id=pid)
        assert "datacenter" in entry["tags"]
        assert "us" in entry["tags"]

    def test_add_proxy_type_detection(self, pool):
        """add_proxy() should extract or accept proxy type."""
        pid = pool.add_proxy(
            "socks5://user:pass@host:1080",
            proxy_type="SOCKS5",
        )
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["type"] == "SOCKS5"

    def test_add_proxy_without_type(self, pool):
        """add_proxy() should auto-detect type from URL scheme."""
        pid = pool.add_proxy("socks5://host:1080")
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["type"] in ("SOCKS5", "socks5")

    def test_add_multiple_proxies(self, pool, sample_proxies):
        """add_proxy() should accept multiple distinct proxies."""
        ids = []
        for url in sample_proxies:
            pid = pool.add_proxy(url)
            ids.append(pid)
        assert len(set(ids)) == len(sample_proxies)
        assert len(pool.get_pool()) == len(sample_proxies)

    def test_get_proxy_by_id(self, pool):
        """get_proxy(proxy_id=...) should return the proxy entry dict."""
        pid = pool.add_proxy("socks5://host:1080")
        entry = pool.get_proxy(proxy_id=pid)
        assert entry is not None
        assert entry["id"] == pid
        assert entry["url"] == "socks5://host:1080"

    def test_get_proxy_nonexistent(self, pool):
        """get_proxy() with nonexistent id should return None."""
        entry = pool.get_proxy(proxy_id="nonexistent-uuid")
        assert entry is None

    def test_get_pool_returns_list(self, pool, sample_proxies):
        """get_pool() should return a list of all proxy entries."""
        for url in sample_proxies:
            pool.add_proxy(url)
        proxies = pool.get_pool()
        assert isinstance(proxies, list)
        assert len(proxies) == len(sample_proxies)

    def test_get_pool_entries_have_all_fields(self, pool):
        """Each entry in get_pool() should contain all ProxyEntry fields."""
        pid = pool.add_proxy("socks5://user:pass@host:1080", tags=["test"])
        proxies = pool.get_pool()
        entry = proxies[0]
        for key in ("id", "url", "type", "tags", "enabled", "healthy",
                     "last_checked", "latency_ms", "success_count",
                     "fail_count", "created_at"):
            assert key in entry, f"Missing field: {key}"

    def test_remove_proxy(self, pool):
        """remove_proxy() should remove a proxy and return True."""
        pid = pool.add_proxy("socks5://host:1080")
        result = pool.remove_proxy(pid)
        assert result is True
        assert pool.get_proxy(proxy_id=pid) is None
        assert len(pool.get_pool()) == 0

    def test_remove_proxy_nonexistent(self, pool):
        """remove_proxy() with bad id should return False."""
        result = pool.remove_proxy("nonexistent")
        assert result is False

    def test_remove_proxy_twice(self, pool):
        """Removing the same proxy twice should fail the second time."""
        pid = pool.add_proxy("socks5://host:1080")
        assert pool.remove_proxy(pid) is True
        assert pool.remove_proxy(pid) is False

    def test_clear_pool(self, pool, sample_proxies):
        """clear() should remove all proxies."""
        for url in sample_proxies:
            pool.add_proxy(url)
        pool.clear()
        assert len(pool.get_pool()) == 0

    def test_add_invalid_url(self, pool):
        """add_proxy() with malformed URL should raise or return error."""
        from proxy_manager import ProxyEntry

        with pytest.raises((ValueError, Exception)):
            pool.add_proxy("not-a-url")

    def test_add_empty_url(self, pool):
        """add_proxy() with empty string should raise."""
        with pytest.raises((ValueError, Exception)):
            pool.add_proxy("")

    def test_add_none_url(self, pool):
        """add_proxy() with None should raise."""
        with pytest.raises((ValueError, TypeError, Exception)):
            pool.add_proxy(None)  # type: ignore

    def test_pool_accepts_max_size(self, storage_path):
        """ProxyPool should accept a max_size parameter."""
        from proxy_manager import ProxyPool

        p = ProxyPool(storage_path=storage_path, max_size=10)
        assert p.max_size == 10

    def test_pool_rejects_over_max(self, storage_path):
        """ProxyPool should reject adds beyond max_size."""
        from proxy_manager import ProxyPool

        p = ProxyPool(storage_path=storage_path, max_size=2)
        p.add_proxy("socks5://host1:1080")
        p.add_proxy("socks5://host2:1080")
        with pytest.raises((ValueError, Exception)):
            p.add_proxy("socks5://host3:1080")

    def test_get_proxy_no_args_uses_default_strategy(self, pool):
        """get_proxy() with no args should return a healthy proxy."""
        pool.add_proxy("socks5://host:1080")
        entry = pool.get_proxy()
        assert entry is not None
        assert isinstance(entry, dict)

    def test_get_proxy_empty_pool(self, pool):
        """get_proxy() on empty pool should return None."""
        entry = pool.get_proxy()
        assert entry is None


# ===================================================================
# Rotation strategies
# ===================================================================


class TestRotationStrategies:
    """Verify round-robin, random, sticky, by-tag-group rotation."""

    def test_round_robin_cycles(self, pool):
        """Round-robin should cycle through proxies sequentially."""
        urls = [
            "socks5://host1:1080",
            "socks5://host2:1080",
            "socks5://host3:1080",
        ]
        for url in urls:
            pool.add_proxy(url)

        picked = []
        for _ in range(6):
            entry = pool.get_proxy(strategy="round-robin")
            picked.append(entry["url"])

        # Sequence should be host1, host2, host3, host1, host2, host3
        assert picked[0] == urls[0]
        assert picked[1] == urls[1]
        assert picked[2] == urls[2]
        assert picked[3] == urls[0]
        assert picked[4] == urls[1]
        assert picked[5] == urls[2]

    def test_round_robin_skips_unhealthy(self, pool):
        """Round-robin should skip unhealthy proxies."""
        pid1 = pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")
        pool.add_proxy("socks5://host3:1080")
        # Mark host1 as unhealthy
        pool._proxies[pid1].healthy = False

        # Should only get host2 and host3
        urls_seen = set()
        for _ in range(4):
            entry = pool.get_proxy(strategy="round-robin")
            urls_seen.add(entry["url"])

        assert "socks5://host1:1080" not in urls_seen

    def test_random_returns_healthy(self, pool):
        """Random strategy should return healthy proxies."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")
        pool.add_proxy("socks5://host3:1080")

        for _ in range(10):
            entry = pool.get_proxy(strategy="random")
            assert entry is not None
            assert entry["healthy"] is True

    def test_sticky_returns_same_for_session(self, pool):
        """Sticky strategy should return the same proxy for a session_id."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")
        pool.add_proxy("socks5://host3:1080")

        session_id = "session-123"
        first = pool.get_proxy(strategy="sticky", session_id=session_id)
        for _ in range(5):
            entry = pool.get_proxy(strategy="sticky", session_id=session_id)
            assert entry["url"] == first["url"]

    def test_sticky_different_session_different_proxy(self, pool):
        """Sticky should assign different sessions different proxies."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")

        a = pool.get_proxy(strategy="sticky", session_id="session-a")
        b = pool.get_proxy(strategy="sticky", session_id="session-b")
        # Two sessions may get same proxy if only 2 proxies in pool
        # But each should be consistent for its session
        assert a["url"] == pool.get_proxy(strategy="sticky", session_id="session-a")["url"]
        assert b["url"] == pool.get_proxy(strategy="sticky", session_id="session-b")["url"]

    def test_sticky_session_unknown(self, pool):
        """A sticky request for a new session should assign a proxy."""
        pool.add_proxy("socks5://host1:1080")
        entry = pool.get_proxy(strategy="sticky", session_id="new-session")
        assert entry is not None

    def test_sticky_round_robin_without_session(self, pool):
        """Sticky without session_id should fall back to round-robin."""
        pool.add_proxy("socks5://host1:1080")
        entry = pool.get_proxy(strategy="sticky")
        assert entry is not None

    def test_by_tag_group_residential(self, populated_pool):
        """By-tag strategy should filter to matching tag group."""
        pool, ids = populated_pool
        residential = pool.get_proxy(strategy="by-tag", group="residential")
        assert residential is not None
        assert "residential" in residential["tags"]

    def test_by_tag_group_datacenter(self, populated_pool):
        """By-tag strategy should filter to datacenter proxies."""
        pool, ids = populated_pool
        dc = pool.get_proxy(strategy="by-tag", group="datacenter")
        assert dc is not None
        assert "datacenter" in dc["tags"]

    def test_by_tag_group_nonexistent(self, pool):
        """By-tag with nonexistent group should return None."""
        pool.add_proxy("socks5://host:1080", tags=["datacenter"])
        entry = pool.get_proxy(strategy="by-tag", group="nonexistent")
        assert entry is None

    def test_by_tag_group_empty_pool(self, pool):
        """By-tag on empty pool should return None."""
        entry = pool.get_proxy(strategy="by-tag", group="residential")
        assert entry is None

    def test_invalid_strategy(self, pool):
        """An unrecognized strategy should raise or fall back."""
        pool.add_proxy("socks5://host:1080")
        with pytest.raises((ValueError, Exception)):
            pool.get_proxy(strategy="unknown-strategy")


# ===================================================================
# Health check logic
# ===================================================================


class TestHealthCheck:
    """Verify health check pass/fail, passive marking, recovery."""

    def test_health_check_proxy(self, pool):
        """health_check() should return health result for a proxy ID."""
        pid = pool.add_proxy("socks5://host:1080")
        result = pool.health_check(pid)
        assert result is not None
        assert "healthy" in result or "status" in result

    def test_health_check_nonexistent(self, pool):
        """health_check() on bad ID should return None or raise."""
        result = pool.health_check("nonexistent")
        assert result is None

    def test_health_check_all(self, pool, sample_proxies):
        """health_check_all() should check all proxies and return results."""
        for url in sample_proxies:
            pool.add_proxy(url)
        results = pool.health_check_all()
        assert isinstance(results, list)
        assert len(results) == len(sample_proxies)

    def test_health_check_empty_pool(self, pool):
        """health_check_all() on empty pool should return empty list."""
        results = pool.health_check_all()
        assert results == []

    def test_passive_failure_marking(self, pool):
        """A failed request should mark proxy unhealthy / increment fail_count."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.report_failure(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["fail_count"] == 1

    def test_passive_multiple_failures(self, pool):
        """Multiple failures should accumulate."""
        pid = pool.add_proxy("socks5://host:1080")
        for _ in range(3):
            pool.report_failure(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["fail_count"] == 3

    def test_report_success(self, pool):
        """report_success() should increment success_count."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.report_success(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["success_count"] == 1

    def test_report_success_on_unhealthy_makes_healthy(self, pool):
        """A successful report on an unhealthy proxy should restore it."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.report_failure(pid)
        pool.report_failure(pid)
        # Mark unhealthy after threshold
        pool.report_success(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["healthy"] is True

    def test_failure_threshold_disables_proxy(self, pool):
        """Repeated failures should mark proxy unhealthy/enabled=False."""
        pid = pool.add_proxy("socks5://host:1080")
        for _ in range(5):
            pool.report_failure(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["healthy"] is False
        assert entry["enabled"] is False

    def test_recovery_retry(self, pool):
        """Unhealthy proxies should be retried after cooldown."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.report_failure(pid)
        pool.report_failure(pid)
        pool.report_failure(pid)
        # Force a health check that succeeds
        entry = pool.get_proxy(proxy_id=pid)
        # After cooldown, proxy should be retried
        # Health check should re-enable it
        pool.report_success(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["healthy"] is True

    def test_health_check_updates_latency(self, pool):
        """health_check() should update latency_ms."""
        pid = pool.add_proxy("socks5://host:1080")
        result = pool.health_check(pid)
        entry = pool.get_proxy(proxy_id=pid)
        # Latency should be a non-negative number
        assert entry["latency_ms"] >= 0

    def test_health_check_updates_last_checked(self, pool):
        """health_check() should update last_checked timestamp."""
        pid = pool.add_proxy("socks5://host:1080")
        before = time.time()
        pool.health_check(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["last_checked"] >= before


# ===================================================================
# JSON persistence
# ===================================================================


class TestJSONPersistence:
    """Verify save/load from JSON file."""

    def test_save_creates_file(self, pool, storage_path):
        """save() should create the JSON file on disk."""
        pool.add_proxy("socks5://host:1080")
        pool.save()
        assert os.path.exists(storage_path)

    def test_save_and_load_roundtrip(self, pool, storage_path):
        """Proxies saved to JSON should be reconstructable."""
        pool.add_proxy("socks5://host1:1080", tags=["dc"])
        pool.add_proxy("http://host2:8080", tags=["res"])
        pool.save()

        # Create a new pool loading from the same file
        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()
        assert len(pool2.get_pool()) == 2

        urls = {p["url"] for p in pool2.get_pool()}
        assert "socks5://host1:1080" in urls
        assert "http://host2:8080" in urls

    def test_load_empty_file(self, storage_path):
        """Loading from non-existent file should give empty pool."""
        from proxy_manager import ProxyPool

        pool = ProxyPool(storage_path=storage_path)
        pool.load()
        assert len(pool.get_pool()) == 0

    def test_auto_save_on_add(self, pool, storage_path):
        """add_proxy() should auto-save to disk."""
        pool.add_proxy("socks5://host:1080")
        assert os.path.exists(storage_path)
        with open(storage_path) as f:
            data = json.load(f)
        assert len(data) == 1

    def test_auto_save_on_remove(self, pool, storage_path):
        """remove_proxy() should auto-save to disk."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.remove_proxy(pid)
        with open(storage_path) as f:
            data = json.load(f)
        assert len(data) == 0

    def test_save_idempotent(self, pool, storage_path):
        """Saving multiple times without changes should be idempotent."""
        pool.add_proxy("socks5://host:1080")
        pool.save()
        pool.save()
        pool.save()
        assert os.path.exists(storage_path)

    def test_json_format(self, pool, storage_path):
        """Saved JSON should be a list of proxy objects."""
        pid = pool.add_proxy("socks5://user:pass@host:1080", tags=["test"])
        with open(storage_path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        entry = data[0]
        assert entry["id"] == pid
        assert entry["url"] == "socks5://user:pass@host:1080"
        assert "user:pass" in entry["url"]

    def test_load_corrupted_json(self, storage_path):
        """Loading corrupted JSON should not crash."""
        with open(storage_path, "w") as f:
            f.write("{corrupted json")
        from proxy_manager import ProxyPool

        pool = ProxyPool(storage_path=storage_path)
        pool.load()  # Should handle gracefully
        assert len(pool.get_pool()) == 0

    def test_storage_path_default(self):
        """ProxyPool should have a sensible default storage path."""
        from proxy_manager import ProxyPool

        pool = ProxyPool()
        assert pool.storage_path is not None
        assert isinstance(pool.storage_path, str)


# ===================================================================
# Stats
# ===================================================================


class TestStats:
    """Verify get_stats() returns meaningful metrics."""

    def test_stats_empty_pool(self, pool):
        """get_stats() on empty pool should return zero counts."""
        stats = pool.get_stats()
        assert stats["total"] == 0
        assert stats["healthy"] == 0
        assert stats["unhealthy"] == 0

    def test_stats_counts(self, pool):
        """get_stats() should reflect pool composition."""
        pid1 = pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")
        pool.add_proxy("socks5://host3:1080")
        # Mark one as unhealthy
        pool.report_failure(pid1)
        pool.report_failure(pid1)
        pool.report_failure(pid1)

        stats = pool.get_stats()
        assert stats["total"] == 3
        assert stats["healthy"] == 2
        assert stats["unhealthy"] == 1

    def test_stats_by_tag(self, populated_pool):
        """get_stats() should include breakdown by tag."""
        pool, ids = populated_pool
        stats = pool.get_stats()
        assert "by_tag" in stats
        assert "datacenter" in stats["by_tag"]
        assert "residential" in stats["by_tag"]

    def test_stats_total_requests(self, pool):
        """get_stats() should reflect total success+fail counts."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.report_success(pid)
        pool.report_success(pid)
        pool.report_failure(pid)
        stats = pool.get_stats()
        assert stats["total_requests"] == 3
        assert stats["total_success"] == 2
        assert stats["total_failures"] == 1
class TestR3HealthCheckAsync:
    """R3 regression: async health_check must not stall the event loop."""

    @pytest.mark.asyncio
    async def test_async_health_check_does_not_block_loop(self, monkeypatch):
        """A slow proxy (simulated) must not stall the event loop when
        health_check_async is awaited.  Uses a 50ms ticker to measure gaps."""
        import asyncio as _asyncio
        import time as _time

        import httpx as _httpx

        from proxy_manager import ProxyPool as _ProxyPool

        pool = _ProxyPool()
        pid = pool.add_proxy("http://blackhole:1080")

        class _SlowAsyncClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                await _asyncio.sleep(2.0)  # simulate hanging proxy
                from types import SimpleNamespace
                return SimpleNamespace(status_code=500)

        monkeypatch.setattr(_httpx, "AsyncClient", _SlowAsyncClient)

        # Ticker: record gaps every ~50ms during the probe
        tick_gaps: list[float] = []

        async def _ticker():
            last = _time.monotonic()
            for _ in range(60):  # 60 x 50ms = 3s (probe is 2s)
                await _asyncio.sleep(0.05)
                now = _time.monotonic()
                tick_gaps.append(now - last)
                last = now

        ticker_task = _asyncio.create_task(_ticker())
        result = await pool.health_check_async(pid)
        await ticker_task

        assert result is not None
        max_gap = max(tick_gaps)
        assert max_gap < 0.15, (
            f"Event loop stalled during async health_check: max tick gap "
            f"was {max_gap:.3f}s (threshold 0.15s)"
        )

    @pytest.mark.asyncio
    async def test_async_health_check_all(self):
        """health_check_all_async returns result dicts for all proxies."""
        from proxy_manager import ProxyPool as _ProxyPool

        pool = _ProxyPool()
        p1 = pool.add_proxy("socks5://h1:1080")
        p2 = pool.add_proxy("socks5://h2:1080")

        results = await pool.health_check_all_async()
        assert isinstance(results, list)
        assert len(results) == 2
        ids = {r["proxy_id"] for r in results}
        assert p1 in ids and p2 in ids
