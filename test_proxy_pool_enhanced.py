"""
Pre-development tests for Enhanced Proxy Pool features (P1-6).

RED PHASE — All tests will fail until the developer implements:
  - Concurrent async health checks in health_check_all()
  - Geo-tagging (set_geo / get_geo)
  - Proxy type filtering on get_proxy() and get_pool()
  - Circuit breaker (consecutive_failures → cooling_until)
  - Stats extension with circuit breaker info

Coverage (10 acceptance criteria):
   1. health_check_all() runs concurrently
   2. Geo-tagging stores and retrieves country/city/ISP
   3. GET /proxy/pool?type=SOCKS5 returns only SOCKS5 proxies
   4. Circuit breaker marks proxy cooling_down after N consecutive failures
   5. Cooling-down proxy is excluded from selection for M seconds
   6. Cooling-down proxy recovers after M seconds
   7. Backward compat: existing proxy entries without geo/circuit fields work
   8. report_success() resets consecutive_failure counter
   9. Edge case: cooling-down + health check completes successfully
  10. Geo tags persist across save/load
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


# ===================================================================
# Fixtures
# ===================================================================



# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

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
    p.clear()


@pytest.fixture
def sample_proxies():
    """Return a list of proxy URLs for population tests."""
    return [
        "socks5://user1:pass1@proxy1.example.com:1080",
        "http://user2:pass2@proxy2.example.com:3128",
        "https://proxy3.example.com:443",
        "socks4://proxy4.example.com:1080",
    ]


@pytest.fixture
def populated_pool(pool, sample_proxies):
    """Return a ProxyPool pre-loaded with sample proxies of various types."""
    ids = []
    for url in sample_proxies:
        pid = pool.add_proxy(url)
        ids.append(pid)
    return pool, ids


# ===================================================================
# 1. ProxyEntry enhanced fields
# ===================================================================


class TestProxyEntryEnhanced:
    """Verify new fields on ProxyEntry: geo, consecutive_failures, cooling_until."""

    def test_geo_field_exists(self):
        """ProxyEntry should have a 'geo' field defaulting to None."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="socks5://host:1080", type="SOCKS5")
        assert hasattr(entry, "geo"), "geo field missing from ProxyEntry"
        assert entry.geo is None, "geo should default to None"

    def test_consecutive_failures_field_exists(self):
        """ProxyEntry should have a 'consecutive_failures' field defaulting to 0."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="socks5://host:1080", type="SOCKS5")
        assert hasattr(entry, "consecutive_failures"), "consecutive_failures field missing"
        assert entry.consecutive_failures == 0, "consecutive_failures should default to 0"

    def test_cooling_until_field_exists(self):
        """ProxyEntry should have a 'cooling_until' field defaulting to 0.0."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(url="socks5://host:1080", type="SOCKS5")
        assert hasattr(entry, "cooling_until"), "cooling_until field missing"
        assert entry.cooling_until == 0.0, "cooling_until should default to 0.0"

    def test_geo_accepts_dict(self):
        """ProxyEntry.geo should accept a dict with country/city/isp."""
        from proxy_manager import ProxyEntry

        entry = ProxyEntry(
            url="socks5://host:1080",
            type="SOCKS5",
            geo={"country": "US", "city": "New York", "isp": "DigitalOcean"},
        )
        assert entry.geo["country"] == "US"
        assert entry.geo["city"] == "New York"
        assert entry.geo["isp"] == "DigitalOcean"

    def test_entry_to_dict_includes_new_fields(self, pool):
        """get_proxy() dict output should include geo, consecutive_failures, cooling_until."""
        pid = pool.add_proxy("socks5://host:1080")
        entry = pool.get_proxy(proxy_id=pid)
        assert "geo" in entry, "geo missing from serialized entry"
        assert "consecutive_failures" in entry, (
            "consecutive_failures missing from serialized entry"
        )
        assert "cooling_until" in entry, "cooling_until missing from serialized entry"


# ===================================================================
# 2. Geo-tagging
# ===================================================================


class TestGeoTaggng:
    """Verify set_geo stores and get_geo retrieves country/city/ISP."""

    def test_set_geo_method_exists(self, pool):
        """ProxyPool should have a set_geo(proxy_id, country, city, isp) method."""
        from proxy_manager import ProxyPool

        assert hasattr(ProxyPool, "set_geo"), "set_geo method missing"

    def test_get_geo_method_exists(self, pool):
        """ProxyPool should have a get_geo(proxy_id) method."""
        from proxy_manager import ProxyPool

        assert hasattr(ProxyPool, "get_geo"), "get_geo method missing"

    def test_set_geo_stores_fields(self, pool):
        """set_geo should store country, city, isp on the proxy entry."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.set_geo(pid, country="US", city="New York", isp="DigitalOcean")
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["geo"] == {"country": "US", "city": "New York", "isp": "DigitalOcean"}

    def test_set_geo_nonexistent(self, pool):
        """set_geo on nonexistent proxy_id should raise or return False."""
        with pytest.raises((KeyError, ValueError)):
            pool.set_geo("nonexistent", country="US", city="NY", isp="ISP")

    def test_get_geo_returns_dict(self, pool):
        """get_geo should return the geo dict for a proxy."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.set_geo(pid, country="DE", city="Berlin", isp="Hetzner")
        geo = pool.get_geo(pid)
        assert geo == {"country": "DE", "city": "Berlin", "isp": "Hetzner"}

    def test_get_geo_nonexistent(self, pool):
        """get_geo on nonexistent proxy_id should return None."""
        result = pool.get_geo("nonexistent")
        assert result is None

    def test_get_geo_no_geo_set(self, pool):
        """get_geo on a proxy without geo should return None."""
        pid = pool.add_proxy("socks5://host:1080")
        geo = pool.get_geo(pid)
        assert geo is None

    def test_set_geo_partial(self, pool):
        """set_geo should accept partial geo info (only country, no city/isp)."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.set_geo(pid, country="GB")
        geo = pool.get_geo(pid)
        assert geo["country"] == "GB"

    def test_geo_clear(self, pool):
        """set_geo with all None should clear geo field."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.set_geo(pid, country="US", city="NY", isp="ISP")
        pool.set_geo(pid, country=None, city=None, isp=None)
        geo = pool.get_geo(pid)
        assert geo is None, "geo should be cleared when all fields are None"


# ===================================================================
# 3. Proxy type filtering
# ===================================================================


class TestTypeFilter:
    """Verify get_proxy(type=...) and get_pool(type=...) filter by proxy type."""

    def test_get_proxy_type_filter_socks5(self, pool):
        """get_proxy(type='SOCKS5') should return a SOCKS5 proxy."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("http://host2:8080")
        pool.add_proxy("socks4://host3:1080")

        result = pool.get_proxy(type="SOCKS5")
        assert result is not None
        assert result["type"] == "SOCKS5"

    def test_get_proxy_type_http(self, pool):
        """get_proxy(type='HTTP') should return an HTTP proxy."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("http://host2:8080")

        http_proxy = pool.get_proxy(type="HTTP")
        assert http_proxy is not None
        assert http_proxy["type"] == "HTTP"

    def test_get_proxy_type_no_match(self, pool):
        """get_proxy(type='HTTPS') with only SOCKS5 proxies should return None."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")

        result = pool.get_proxy(type="HTTPS")
        assert result is None

    def test_get_pool_type_filter(self, pool):
        """get_pool(type='SOCKS5') should return only SOCKS5 proxies."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("http://host2:8080")
        pool.add_proxy("socks4://host3:1080")

        proxies = pool.get_pool(type="SOCKS5")
        assert all(p["type"] == "SOCKS5" for p in proxies)

    def test_get_pool_type_empty(self, pool):
        """get_pool(type='SOCKS5') on empty pool should return empty list."""
        proxies = pool.get_pool(type="SOCKS5")
        assert proxies == []

    def test_get_pool_type_count(self, pool):
        """get_pool(type='SOCKS5') should return correct count."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("http://host2:8080")
        pool.add_proxy("socks5://host3:1080")

        proxies = pool.get_proxy(type="SOCKS5")
        # get_proxy returns one entry; get_pool should return filtered list.
        proxies = pool.get_pool(type="SOCKS5")
        assert len(proxies) == 2

    def test_get_proxy_type_with_strategy(self, pool):
        """get_proxy(type=..., strategy=...) should combine type + rotation strategy."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")
        pool.add_proxy("http://host3:8080")

        for _ in range(5):
            entry = pool.get_proxy(type="SOCKS5", strategy="random")
            assert entry is not None
            assert entry["type"] == "SOCKS5"

    def test_type_filter_with_tag_group(self, pool):
        """get_proxy(type=..., group=...) should combine type + tag filter."""
        pool.add_proxy("socks5://host1:1080", tags=["residential"])
        pool.add_proxy("socks5://host2:1080", tags=["datacenter"])
        pool.add_proxy("http://host3:8080", tags=["residential"])

        entry = pool.get_proxy(type="SOCKS5", group="datacenter")
        assert entry is not None
        assert entry["type"] == "SOCKS5"
        assert "datacenter" in entry["tags"]

    def test_type_filter_no_match_returns_none(self, pool):
        """get_proxy with type filter on empty matching pool should return None."""
        pool.add_proxy("http://host:8080")
        result = pool.get_proxy(type="SOCKS5")
        assert result is None


# ===================================================================
# 4. Concurrent health checks
# ===================================================================


class TestConcurrentHealthCheck:
    """Verify health_check_all() runs concurrently (not sequentially)."""

    def test_concurrent_execution_faster_than_sequential(self, pool):
        """health_check_all() should complete faster than sequential execution.

        If each health_check takes ~0.15s, 3 sequential checks take ~0.45s.
        Concurrent checks should complete in ~0.15-0.20s (near the max of individual).
        """
        pid1 = pool.add_proxy("socks5://host1:1080")
        pid2 = pool.add_proxy("socks5://host2:1080")
        pid3 = pool.add_proxy("socks5://host3:1080")

        # Patch health_check to simulate a slow check (0.15s each)
        original_check = pool.health_check

        def _slow_check(proxy_id):
            time.sleep(0.15)
            return original_check(proxy_id)

        pool.health_check = _slow_check

        start = time.time()
        results = pool.health_check_all()
        elapsed = time.time() - start

        # Sequential: 3 * 0.15 = 0.45s; concurrent: ~0.15-0.18s
        assert elapsed < 0.40, (
            f"health_check_all took {elapsed:.3f}s (expected < 0.40s for concurrency, "
            f">= 0.45s indicates sequential execution)"
        )
        assert len(results) == 3

    def test_concurrent_with_many_proxies(self, pool):
        """health_check_all() should scale with many proxies (not O(n) sequential)."""
        # Add 10 proxies
        for i in range(10):
            pool.add_proxy(f"socks5://host{i}:1080")

        original_check = pool.health_check

        def _slow_check(proxy_id):
            time.sleep(0.1)
            return original_check(proxy_id)

        pool.health_check = _slow_check

        start = time.time()
        results = pool.health_check_all()
        elapsed = time.time() - start

        # Sequential 10 * 0.1 = 1.0s; concurrent ~0.1-0.15s
        assert elapsed < 0.8, (
            f"health_check_all with 10 proxies took {elapsed:.3f}s "
            f"(expected < 0.8s for concurrent execution)"
        )
        assert len(results) == 10

    def test_concurrent_empty_pool(self, pool):
        """health_check_all() on empty pool should return quickly."""
        start = time.time()
        results = pool.health_check_all()
        elapsed = time.time() - start
        assert results == []
        assert elapsed < 1.0, "empty pool check should be nearly instant"


# ===================================================================
# 5. Circuit Breaker — failure threshold
# ===================================================================


class TestCircuitBreaker:
    """Verify circuit breaker: N consecutive failures -> cooling_down state."""

    def test_consecutive_failures_tracks_separately(self, pool):
        """report_failure should increment consecutive_failures."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.report_failure(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["consecutive_failures"] == 1

    def test_consecutive_failures_resets_on_success(self, pool):
        """report_success should reset consecutive_failures to 0."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.report_failure(pid)
        pool.report_failure(pid)
        pool.report_success(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["consecutive_failures"] == 0, (
            "consecutive_failures should reset to 0 on report_success"
        )

    def test_cooling_after_N_failures(self, pool):
        """After FAILURE_THRESHOLD consecutive failures, proxy enters cooling_down."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")
        threshold = ProxyPool.FAILURE_THRESHOLD  # typically 3

        # Hit the threshold
        for _ in range(threshold):
            pool.report_failure(pid)

        entry = pool.get_proxy(proxy_id=pid)
        assert entry["cooling_until"] > 0, (
            f"proxy should be in cooling-down state after {threshold} consecutive failures"
        )
        assert entry["cooling_until"] > time.time(), (
            "cooling_until should be a future timestamp"
        )

    def test_cooling_below_threshold(self, pool):
        """Below FAILURE_THRESHOLD, proxy should NOT enter cooling_down."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")
        threshold = ProxyPool.FAILURE_THRESHOLD

        for _ in range(threshold - 1):
            pool.report_failure(pid)

        entry = pool.get_proxy(proxy_id=pid)
        assert entry["cooling_until"] == 0.0, (
            f"proxy should NOT be cooling_down after {threshold - 1} failures "
            f"(threshold is {threshold})"
        )

    def test_cooling_makes_proxy_unavailable(self, pool):
        """A cooling-down proxy should not be returned by get_proxy()."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")
        pool.add_proxy("socks5://host2:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid)

        entry = pool.get_proxy()
        assert entry is not None
        assert entry["id"] != pid, "cooling-down proxy should not be selected"

    def test_cooling_healthy_still_available(self, pool):
        """Healthy proxies should still be selectable when another is cooling."""
        from proxy_manager import ProxyPool

        pid1 = pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid1)

        entry = pool.get_proxy()
        assert entry is not None
        assert entry["id"] != pid1

    def test_cooling_with_interleaved_success(self, pool):
        """A success between failures should reset consecutive_failures."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")

        pool.report_failure(pid)  # consecutive=1
        pool.report_failure(pid)  # consecutive=2
        pool.report_success(pid)  # consecutive=0 (reset)
        pool.report_failure(pid)  # consecutive=1
        pool.report_failure(pid)  # consecutive=2
        pool.report_failure(pid)  # consecutive=3 = threshold

        entry = pool.get_proxy(proxy_id=pid)
        assert entry["consecutive_failures"] == 3
        assert entry["cooling_until"] > time.time()


# ===================================================================
# 6. Cooling-down recovery
# ===================================================================


class TestCoolingDownRecovery:
    """Verify cooling-down proxy recovers after M seconds."""

    def test_cooling_down_recovery_after_timeout(self, pool):
        """After cooling_down period expires, proxy should return to normal."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")
        pool.add_proxy("socks5://host2:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid)

        # Manually set cooling_until to 1 second in the past (expired)
        pool._proxies[pid].cooling_until = time.time() - 1

        # Should now be selectable again
        entry = pool.get_proxy()
        assert entry is not None

    def test_cooling_down_still_excluded_during_cooldown(self, pool):
        """During cooling_down period, proxy should remain excluded."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid)

        # Set cooling_until well in the future
        pool._proxies[pid].cooling_until = time.time() + 60

        # There are no other healthy proxies, so get_proxy should return None
        entry = pool.get_proxy()
        assert entry is None, "should return None when only proxy is cooling down"

    def test_consecutive_failures_resets_on_recovery(self, pool):
        """After cooling_down period expires, consecutive_failures should reset to 0."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid)

        # Simulate cooldown expiry
        pool._proxies[pid].cooling_until = time.time() - 1

        entry = pool.get_proxy(proxy_id=pid)
        if entry["cooling_until"] == 0.0:
            assert entry["consecutive_failures"] == 0, (
                "consecutive_failures should reset on recovery"
            )

    def test_cooldown_timer_default(self, pool):
        """The cooling_down duration should default to a reasonable value (e.g. 30s)."""
        from proxy_manager import ProxyPool

        assert hasattr(ProxyPool, "COOLDOWN_SECONDS"), "COOLDOWN_SECONDS constant missing"
        assert ProxyPool.COOLDOWN_SECONDS >= 10, "COOLDOWN_SECONDS should be at least 10s"
        assert ProxyPool.COOLDOWN_SECONDS <= 300, (
            "COOLDOWN_SECONDS should be at most 300s (5 min)"
        )

    def test_get_stats_includes_circuit_breaker(self, pool):
        """get_stats() should include circuit breaker information."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")
        pool.add_proxy("socks5://host2:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid)

        stats = pool.get_stats()
        assert "cooling_down" in stats, "get_stats should include cooling_down count"
        assert stats["cooling_down"] == 1


# ===================================================================
# 7. report_success resets consecutive_failures
# ===================================================================


class TestReportSuccessResets:
    """Specific tests for report_success resetting the failure counter."""

    def test_report_success_after_single_failure(self, pool):
        """report_success after 1 failure should reset consecutive_failures to 0."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.report_failure(pid)
        pool.report_success(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["consecutive_failures"] == 0
        # total fail_count should remain (only consecutive resets)
        assert entry["fail_count"] == 1

    def test_report_success_during_cooldown(self, pool):
        """report_success during cooling_down should exit cooling state early."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid)

        # Proxy is now cooling_down
        entry_before = pool.get_proxy(proxy_id=pid)
        assert entry_before["cooling_until"] > time.time()

        # report_success should reset and exit cooling state
        pool.report_success(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["consecutive_failures"] == 0
        assert entry["cooling_until"] == 0.0, (
            "cooling_until should be reset on report_success"
        )

    def test_report_success_multiple_times(self, pool):
        """Multiple report_success calls should keep consecutive_failures at 0."""
        pid = pool.add_proxy("socks5://host:1080")
        for _ in range(5):
            pool.report_success(pid)
        entry = pool.get_proxy(proxy_id=pid)
        assert entry["consecutive_failures"] == 0

    def test_report_success_nonexistent(self, pool):
        """report_success on nonexistent proxy should not raise."""
        pool.report_success("nonexistent")


# ===================================================================
# 8. Cooling-down + health check edge cases
# ===================================================================


class TestCoolingDownHealthCheck:
    """Verify edge cases: cooling-down proxy with health check completing."""

    def test_health_check_on_cooling_proxy(self, pool):
        """A health check on a cooling-down proxy should still update its status."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid)

        result = pool.health_check(pid)
        assert result is not None

    def test_health_check_clears_cooling_on_success(self, pool):
        """If health_check succeeds on a cooling-down proxy, it should recover."""
        from proxy_manager import ProxyPool

        pid = pool.add_proxy("socks5://host:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid)

        result = pool.health_check(pid)
        entry = pool.get_proxy(proxy_id=pid)

        if result and result.get("healthy"):
            assert entry["cooling_until"] == 0.0, (
                "cooling_until should reset when health check succeeds"
            )
            assert entry["consecutive_failures"] == 0, (
                "consecutive_failures should reset when health check succeeds"
            )

    def test_cooling_proxy_not_selected_even_if_healthy(self, pool):
        """A cooling-down proxy should not be selected even if marked healthy."""
        from proxy_manager import ProxyPool

        pid1 = pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")

        threshold = ProxyPool.FAILURE_THRESHOLD
        for _ in range(threshold):
            pool.report_failure(pid1)

        # Mark pid1 as healthy but keep it cooling
        pool._proxies[pid1].healthy = True
        pool._proxies[pid1].cooling_until = time.time() + 60

        entry = pool.get_proxy()
        assert entry is not None
        assert entry["id"] != pid1, (
            "cooling-down proxy should NOT be selected even if healthy"
        )


# ===================================================================
# 9. Geo persistence across save/load
# ===================================================================


class TestGeoPersistence:
    """Verify geo tags persist across save() / load()."""

    def test_geo_saved_to_json(self, pool, storage_path):
        """Geo data should be included in the JSON file on save."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.set_geo(pid, country="US", city="New York", isp="DigitalOcean")
        pool.save()

        with open(storage_path) as f:
            data = json.load(f)

        assert "geo" in data[0]
        assert data[0]["geo"] == {"country": "US", "city": "New York", "isp": "DigitalOcean"}

    def test_geo_loaded_from_json(self, pool, storage_path):
        """Geo data should be restored when loading from JSON."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.set_geo(pid, country="DE", city="Berlin", isp="Hetzner")
        pool.save()

        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()
        geo = pool2.get_geo(pid)
        assert geo == {"country": "DE", "city": "Berlin", "isp": "Hetzner"}

    def test_geo_roundtrip_multiple(self, pool, storage_path):
        """Multiple geo-tagged proxies should survive save/load roundtrip."""
        pid1 = pool.add_proxy("socks5://host1:1080")
        pid2 = pool.add_proxy("socks5://host2:1080")
        pool.set_geo(pid1, country="US", city="NY", isp="DC")
        pool.set_geo(pid2, country="GB", city="London", isp="Fastly")
        pool.save()

        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()

        assert pool2.get_geo(pid1) == {"country": "US", "city": "NY", "isp": "DC"}
        assert pool2.get_geo(pid2) == {"country": "GB", "city": "London", "isp": "Fastly"}

    def test_geo_clear_survives_save(self, pool, storage_path):
        """Clearing geo should be reflected after save/load."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.set_geo(pid, country="US", city="NY", isp="ISP")
        pool.set_geo(pid, country=None, city=None, isp=None)
        pool.save()

        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()
        assert pool2.get_geo(pid) is None


# ===================================================================
# 10. Backward compatibility
# ===================================================================


class TestBackwardCompatibility:
    """Verify existing proxy entries without geo/circuit fields still work."""

    def _write_legacy(self, storage_path, entries):
        """Write legacy-format proxy entries to the JSON file."""
        with open(storage_path, "w") as f:
            json.dump(entries, f)

    def test_old_format_load(self, pool, storage_path):
        """Legacy proxy entries (no geo, no cooling fields) should load fine."""
        legacy = [
            {
                "id": "legacy-001",
                "url": "socks5://host:1080",
                "type": "SOCKS5",
                "tags": [],
                "enabled": True,
                "healthy": True,
                "last_checked": 0.0,
                "latency_ms": 0.0,
                "success_count": 0,
                "fail_count": 0,
                "created_at": 1000.0,
            }
        ]
        self._write_legacy(storage_path, legacy)

        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()
        assert len(pool2.get_pool()) == 1
        entry = pool2.get_proxy(proxy_id="legacy-001")
        assert entry is not None
        assert entry["url"] == "socks5://host:1080"

    def test_old_format_gets_default_geo(self, pool, storage_path):
        """Legacy proxy entries should have geo=None after loading."""
        legacy = [
            {
                "id": "legacy-002",
                "url": "socks5://host:1080",
                "type": "SOCKS5",
                "tags": [],
                "enabled": True,
                "healthy": True,
                "last_checked": 0.0,
                "latency_ms": 0.0,
                "success_count": 0,
                "fail_count": 0,
                "created_at": 1000.0,
            }
        ]
        self._write_legacy(storage_path, legacy)

        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()
        entry = pool2.get_proxy(proxy_id="legacy-002")
        assert entry["geo"] is None, "legacy entry should have geo=None"
        assert entry["consecutive_failures"] == 0
        assert entry["cooling_until"] == 0.0

    def test_old_format_can_be_selected(self, pool, storage_path):
        """Legacy proxy entries should be selectable via get_proxy()."""
        legacy = [
            {
                "id": "legacy-003",
                "url": "socks5://host:1080",
                "type": "SOCKS5",
                "tags": [],
                "enabled": True,
                "healthy": True,
                "last_checked": 0.0,
                "latency_ms": 0.0,
                "success_count": 0,
                "fail_count": 0,
                "created_at": 1000.0,
            }
        ]
        self._write_legacy(storage_path, legacy)

        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()
        entry = pool2.get_proxy()
        assert entry is not None
        assert entry["id"] == "legacy-003"

    def test_old_format_with_tag_strategy(self, pool, storage_path):
        """Legacy entries should work with by-tag rotation strategy."""
        legacy = [
            {
                "id": "legacy-004",
                "url": "socks5://host:1080",
                "type": "SOCKS5",
                "tags": ["residential", "us"],
                "enabled": True,
                "healthy": True,
                "last_checked": 0.0,
                "latency_ms": 0.0,
                "success_count": 0,
                "fail_count": 0,
                "created_at": 1000.0,
            }
        ]
        self._write_legacy(storage_path, legacy)

        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()
        entry = pool2.get_proxy(strategy="by-tag", group="residential")
        assert entry is not None
        assert "residential" in entry["tags"]

    def test_mixed_format_load(self, pool, storage_path):
        """Pool with both new and legacy entries should work."""
        pid = pool.add_proxy("socks5://host1:1080")
        pool.set_geo(pid, country="US", city="NY", isp="ISP")
        pool.save()

        # Append a legacy entry manually
        with open(storage_path) as f:
            data = json.load(f)
        data.append(
            {
                "id": "legacy-mixed",
                "url": "socks5://host2:1080",
                "type": "SOCKS5",
                "tags": [],
                "enabled": True,
                "healthy": True,
                "last_checked": 0.0,
                "latency_ms": 0.0,
                "success_count": 0,
                "fail_count": 0,
                "created_at": 2000.0,
            }
        )
        self._write_legacy(storage_path, data)

        from proxy_manager import ProxyPool

        pool2 = ProxyPool(storage_path=storage_path)
        pool2.load()
        assert len(pool2.get_pool()) == 2
        assert pool2.get_geo(pid) == {"country": "US", "city": "NY", "isp": "ISP"}
        assert pool2.get_geo("legacy-mixed") is None


# ===================================================================
# 11. ProxyPool constant and config validation
# ===================================================================


class TestProxyPoolConstants:
    """Verify constants used for circuit breaker and recovery."""

    def test_failure_threshold_constant(self, pool):
        """FAILURE_THRESHOLD should be a positive integer."""
        from proxy_manager import ProxyPool

        assert isinstance(ProxyPool.FAILURE_THRESHOLD, int)
        assert ProxyPool.FAILURE_THRESHOLD >= 1

    def test_cooldown_seconds_constant(self, pool):
        """COOLDOWN_SECONDS should be a positive number."""
        from proxy_manager import ProxyPool

        assert hasattr(ProxyPool, "COOLDOWN_SECONDS")
        assert isinstance(ProxyPool.COOLDOWN_SECONDS, (int, float))
        assert ProxyPool.COOLDOWN_SECONDS > 0
