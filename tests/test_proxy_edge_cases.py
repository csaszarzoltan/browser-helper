"""Edge case tests for ProxyPool / ProxyManager.

Covers scenarios not tested by the main proxy test files:
  - All proxies unhealthy → rotation returns None
  - Duplicate proxy URLs → handles gracefully (dedupe or reject)
  - Sticky session stale entry cleanup
  - report_success on nonexistent proxy (no-op)
  - report_failure on nonexistent proxy (no-op)
  - Concurrent health check calls (thread safety)
  - Atomic save failure cleanup
"""

import os
import sys
import threading
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
    p.clear()


# ===================================================================
# Edge: All proxies unhealthy
# ===================================================================


class TestAllUnhealthy:
    """When ALL proxies are unhealthy, rotation must return None."""

    def test_get_proxy_all_unhealthy_returns_none(self, pool):
        """get_proxy() when all proxies unhealthy should return None."""
        pid1 = pool.add_proxy("socks5://host1:1080")
        pid2 = pool.add_proxy("socks5://host2:1080")
        pid3 = pool.add_proxy("socks5://host3:1080")

        for pid in [pid1, pid2, pid3]:
            for _ in range(5):
                pool.report_failure(pid)

        entry = pool.get_proxy()
        assert entry is None, "Should return None when all proxies unhealthy"

    def test_get_proxy_all_unhealthy_strategies(self, pool):
        """All unhealthy should return None across all strategies."""
        pid = pool.add_proxy("socks5://host1:1080")
        for _ in range(5):
            pool.report_failure(pid)

        assert pool.get_proxy(strategy="round-robin") is None
        assert pool.get_proxy(strategy="random") is None
        assert pool.get_proxy(strategy="sticky", session_id="s1") is None
        assert pool.get_proxy(strategy="by-tag", group="datacenter") is None

    def test_health_check_all_on_all_unhealthy(self, pool):
        """health_check_all() should still return results even if all unhealthy."""
        pool.add_proxy("socks5://host1:1080")
        pool.add_proxy("socks5://host2:1080")
        results = pool.health_check_all()
        assert isinstance(results, list)

    def test_stats_all_unhealthy(self, pool):
        """get_stats() should correctly reflect all-unhealthy state."""
        pid1 = pool.add_proxy("socks5://host1:1080")
        pid2 = pool.add_proxy("socks5://host2:1080")
        for pid in [pid1, pid2]:
            for _ in range(5):
                pool.report_failure(pid)

        stats = pool.get_stats()
        assert stats["total"] == 2
        assert stats["healthy"] == 0
        assert stats["unhealthy"] == 2


# ===================================================================
# Edge: Duplicate proxy URLs
# ===================================================================


class TestDuplicateURLs:
    """Duplicate proxy URLs should be handled gracefully."""

    def test_add_same_url_twice(self, pool):
        """Adding the same URL twice should succeed (each gets a unique ID)."""
        url = "socks5://user:pass@proxy.example.com:1080"
        id1 = pool.add_proxy(url)
        id2 = pool.add_proxy(url)
        assert id1 != id2, "Each addition should have a unique ID"

        proxies = pool.get_pool()
        assert len(proxies) == 2
        assert all(p["url"] == url for p in proxies)

    def test_add_same_url_different_tags(self, pool):
        """Adding same URL with different tags should be fine."""
        url = "socks5://host:1080"
        id1 = pool.add_proxy(url, tags=["datacenter"])
        id2 = pool.add_proxy(url, tags=["residential"])
        assert id1 != id2

        entry1 = pool.get_proxy(proxy_id=id1)
        entry2 = pool.get_proxy(proxy_id=id2)
        assert entry1["tags"] == ["datacenter"]
        assert entry2["tags"] == ["residential"]


# ===================================================================
# Edge: Sticky session stale entry
# ===================================================================


class TestStickyStaleEntry:
    """When a sticky proxy is removed, sessions should get a new proxy."""

    def test_sticky_removed_proxy_reassigns(self, pool):
        """Sticky session should be reassigned after its proxy is removed."""
        pool.add_proxy("socks5://host1:1080")
        pid2 = pool.add_proxy("socks5://host2:1080")

        # Assign session to proxy 2 via sticky
        pool.get_proxy(strategy="sticky", session_id="session-a")

        # Remove the assigned proxy
        pool.remove_proxy(pid2)

        # Next request should get a new proxy (host1)
        second = pool.get_proxy(strategy="sticky", session_id="session-a")
        assert second is not None, "Should reassign to available proxy"
        assert second["url"] == "socks5://host1:1080", "Should fall back to remaining proxy"

    def test_sticky_removed_all_proxies_returns_none(self, pool):
        """Sticky session should return None when all proxies removed."""
        pid = pool.add_proxy("socks5://host1:1080")
        pool.get_proxy(strategy="sticky", session_id="s1")
        pool.remove_proxy(pid)
        assert pool.get_proxy(strategy="sticky", session_id="s1") is None


# ===================================================================
# Edge: report_success / report_failure on nonexistent proxy
# ===================================================================


class TestNoopOperations:
    """report_success / report_failure on nonexistent proxy should be no-ops."""

    def test_report_success_nonexistent(self, pool):
        """report_success() on nonexistent id should not crash."""
        pool.report_success("nonexistent-id")

    def test_report_failure_nonexistent(self, pool):
        """report_failure() on nonexistent id should not crash."""
        pool.report_failure("nonexistent-id")

    def test_remove_then_report(self, pool):
        """Operations on a proxy after removal should be no-ops."""
        pid = pool.add_proxy("socks5://host:1080")
        pool.remove_proxy(pid)
        pool.report_success(pid)
        pool.report_failure(pid)
        assert pool.get_proxy(proxy_id=pid) is None


# ===================================================================
# Edge: Concurrent health check calls
# ===================================================================


class TestConcurrentHealthChecks:
    """Concurrent health_check calls should not race or crash."""

    def test_concurrent_health_check_all(self, pool):
        """Calling health_check_all from multiple threads should not crash."""
        for i in range(10):
            pool.add_proxy(f"socks5://host{i}:1080")

        errors: list[BaseException] = []
        lock = threading.Lock()

        def _check() -> None:
            try:
                pool.health_check_all()
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=_check) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent health checks raised: {errors}"

    def test_concurrent_add_and_health_check(self, pool):
        """Adding proxies concurrently with health checks should not crash."""
        errors: list[BaseException] = []
        lock = threading.Lock()

        def _adder() -> None:
            try:
                for i in range(20):
                    pool.add_proxy(f"socks5://host-adder{i}:1080")
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(e)

        def _checker() -> None:
            try:
                for _ in range(10):
                    pool.health_check_all()
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(e)

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=_adder))
            threads.append(threading.Thread(target=_checker))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent access raised: {errors}"

    def test_concurrent_get_proxy(self, pool):
        """Calling get_proxy from multiple threads should not crash."""
        for i in range(10):
            pool.add_proxy(f"socks5://host{i}:1080")

        errors: list[BaseException] = []
        lock = threading.Lock()

        def _get() -> None:
            try:
                for _ in range(20):
                    pool.get_proxy(strategy="random")
                    pool.get_proxy(strategy="round-robin")
                    pool.get_proxy(strategy="sticky", session_id="shared-session")
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=_get) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent get_proxy raised: {errors}"


# ===================================================================
# Edge: Atomic save failure cleanup
# ===================================================================


class TestAtomicSave:
    """Verify atomic save cleans up temp files on failure."""

    def test_save_to_readonly_dir(self, pool, tmp_path):
        """Save failure should clean up temp files."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir(parents=True, exist_ok=True)

        # Add a proxy first while directory is writable
        pool.add_proxy("socks5://host:1080")
        pool.storage_path = str(readonly_dir / "proxy_pool.json")

        # Now make the directory read-only
        os.chmod(str(readonly_dir), 0o444)

        # Save should fail (readonly dir) but not crash
        with pytest.raises((PermissionError, OSError)):
            pool.save()

        # Temp file should be cleaned up
        temp_files = list(readonly_dir.glob("proxy_pool_*.tmp"))
        assert len(temp_files) == 0, f"Temp files not cleaned: {temp_files}"

        # Restore permissions for cleanup
        os.chmod(str(readonly_dir), 0o755)

    def test_save_to_nonexistent_dir_creates_it(self, pool, tmp_path):
        """Save should create parent directory if missing."""
        deep_dir = tmp_path / "a" / "b" / "c"
        pool.storage_path = str(deep_dir / "proxy_pool.json")
        assert not deep_dir.exists()

        pool.add_proxy("socks5://host:1080")
        pool.save()
        assert deep_dir.exists()
        assert os.path.exists(pool.storage_path)


# ===================================================================
# Edge: Missing port in URL
# ===================================================================


class TestURLValidationEdgeCases:
    """Edge cases for proxy URL validation."""

    def test_url_without_port_rejected(self, pool):
        """URL without explicit port should be rejected."""
        with pytest.raises((ValueError, Exception)):
            pool.add_proxy("http://proxy.example.com")

    def test_url_without_scheme_rejected(self, pool):
        """URL without scheme should be rejected."""
        with pytest.raises((ValueError, Exception)):
            pool.add_proxy("proxy.example.com:1080")

    def test_url_invalid_port_rejected(self, pool):
        """Non-numeric port should be rejected or parsed gracefully."""
        with pytest.raises((ValueError, Exception)):
            pool.add_proxy("socks5://host:notaport")

    def test_url_with_auth_special_chars(self, pool):
        """URL with special characters in auth should be accepted."""
        pid = pool.add_proxy("socks5://user_name:pass-word@host:1080")
        assert pid is not None
        entry = pool.get_proxy(proxy_id=pid)
        assert entry is not None


# ===================================================================
# Edge: Full pool edge cases
# ===================================================================


class TestPoolBoundaries:
    """Boundary tests for pool size limits."""

    def test_pool_at_max_then_remove_then_add(self, storage_path):
        """After removing from full pool, should be able to add again."""
        from proxy_manager import ProxyPool

        p = ProxyPool(storage_path=storage_path, max_size=2)
        p.add_proxy("socks5://host1:1080")
        pid2 = p.add_proxy("socks5://host2:1080")
        with pytest.raises((ValueError, Exception)):
            p.add_proxy("socks5://host3:1080")

        p.remove_proxy(pid2)
        pid3 = p.add_proxy("socks5://host3:1080")
        assert pid3 is not None
        assert len(p.get_pool()) == 2

    def test_clear_then_add(self, pool):
        """After clear(), adding should work fresh."""
        for i in range(5):
            pool.add_proxy(f"socks5://host{i}:1080")
        pool.clear()
        assert len(pool.get_pool()) == 0
        pid = pool.add_proxy("socks5://newhost:1080")
        assert pid is not None
        assert len(pool.get_pool()) == 1
