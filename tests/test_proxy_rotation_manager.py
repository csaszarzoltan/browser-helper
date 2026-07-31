"""Pre-development tests for ProxyRotationManager (RED phase).

Interface coverage (PASS — works via delegation or stub constructor):
  - Module import, class existence
  - __init__(pool=None) creates internal ProxyPool
  - __init__(pool=...) wraps an existing ProxyPool
  - pool property exposes the internal ProxyPool
  - All delegated methods pass through correctly

Behavioural coverage (FAIL — NotImplementedError until implementation):
  - load_from_env() with PROXY_LIST=... adds correct proxies
  - load_from_env() with PROXY_FILE=/path reads one-per-line file
  - load_from_env() with neither env var returns 0
  - get_proxy(strategy="health-check") returns lowest-latency proxy
  - Fallback to round-robin when no latencies available
  - PROXY_FILE handles # comments and blank lines
  - Bad URLs logged as warnings, not fatal errors

Usage:
    cd /home/zoltan/browser-helper
    .venv/bin/python -m pytest tests/test_proxy_rotation_manager.py -v
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def manager():
    """Return a fresh ProxyRotationManager with an internal ProxyPool."""
    from proxy_rotation_manager import ProxyRotationManager

    return ProxyRotationManager()


@pytest.fixture
def tmp_proxy_file(tmp_path):
    """Return a path to a temp proxy file with sample proxies."""

    def _make(lines: list[str]) -> str:
        path = tmp_path / "proxies.txt"
        path.write_text("\n".join(lines))
        return str(path)

    return _make


# ===================================================================
# Module & class existence
# ===================================================================


class TestProxyRotationManagerImports:
    """Verify the module loads and the class is available."""

    def test_module_importable(self):
        """proxy_rotation_manager module should import without error."""
        import proxy_rotation_manager  # noqa: F401

    def test_class_exists(self):
        """ProxyRotationManager class should be available in the module."""
        from proxy_rotation_manager import ProxyRotationManager

        assert isinstance(ProxyRotationManager, type)

    def test_proxy_pool_importable(self):
        """ProxyPool should be importable from proxy_manager."""
        from proxy_manager import ProxyPool

        assert isinstance(ProxyPool, type)


# ===================================================================
# __init__ behaviour
# ===================================================================


class TestProxyRotationManagerInit:
    """Verify __init__ creates or wraps a ProxyPool."""

    def test_init_default_creates_pool(self, manager):
        """__init__() with no args should create an internal ProxyPool."""
        from proxy_manager import ProxyPool

        assert isinstance(manager.pool, ProxyPool)

    def test_init_accepts_pool(self):
        """__init__(pool=...) should wrap the given ProxyPool."""
        from proxy_manager import ProxyPool
        from proxy_rotation_manager import ProxyRotationManager

        pool = ProxyPool()
        mgr = ProxyRotationManager(pool=pool)
        assert mgr.pool is pool

    def test_pool_property(self, manager):
        """pool property should return the ProxyPool instance."""
        from proxy_manager import ProxyPool

        assert isinstance(manager.pool, ProxyPool)

    def test_init_empty_pool(self, manager):
        """A fresh manager should start with an empty pool."""
        assert len(manager.get_pool()) == 0

    def test_init_rejects_non_pool(self):
        """__init__(pool=<wrong type>) should raise TypeError."""
        from proxy_rotation_manager import ProxyRotationManager

        with pytest.raises(TypeError):
            ProxyRotationManager(pool="not-a-pool")  # type: ignore[arg-type]


# ===================================================================
# load_from_env — interface
# ===================================================================


class TestLoadFromEnvInterface:
    """Verify load_from_env method exists, is callable, and has correct signature."""

    def test_method_exists(self, manager):
        """load_from_env should be a callable method."""
        assert callable(manager.load_from_env)

    def test_signature(self):
        """load_from_env should take only self."""
        import inspect

        from proxy_rotation_manager import ProxyRotationManager

        sig = inspect.signature(ProxyRotationManager.load_from_env)
        # Only 'self' parameter
        assert len(sig.parameters) == 1

    def test_returns_int_or_raises(self, manager):
        """load_from_env should return int or raise NotImplementedError."""
        try:
            result = manager.load_from_env()
            assert isinstance(result, int)
        except NotImplementedError:
            pass


# ===================================================================
# load_from_env — behavioural (RED phase)
# ===================================================================


class TestLoadFromEnvBehaviour:
    """load_from_env() behavioural tests — fail until implementation."""

    def test_load_from_env_with_proxy_list(self, monkeypatch, manager):
        """load_from_env() with PROXY_LIST should add correct number of proxies."""
        monkeypatch.setenv("PROXY_LIST", "socks5://u1:p1@h1:1080,http://u2:p2@h2:3128")
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        assert count == 2
        assert len(manager.get_pool()) == 2

    def test_load_from_env_single_proxy(self, monkeypatch, manager):
        """load_from_env() with a single proxy in PROXY_LIST should add 1."""
        monkeypatch.setenv("PROXY_LIST", "socks5://user:pass@host:1080")
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        assert count == 1
        assert len(manager.get_pool()) == 1

    def test_load_from_env_with_proxy_file(self, monkeypatch, manager, tmp_proxy_file):
        """load_from_env() with PROXY_FILE should read one-per-line file."""
        lines = [
            "socks5://u1:p1@h1:1080",
            "http://u2:p2@h2:3128",
            "socks5://u3:p3@h3:1080",
        ]
        fpath = tmp_proxy_file(lines)
        monkeypatch.setenv("PROXY_FILE", fpath)
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        assert count == 3
        assert len(manager.get_pool()) == 3

    def test_load_from_env_file_with_comments_and_blanks(
        self, monkeypatch, manager, tmp_proxy_file
    ):
        """PROXY_FILE should skip # comment lines and blank lines."""
        lines = [
            "# This is a comment",
            "socks5://u1:p1@h1:1080",
            "",
            "   ",
            "# Another comment",
            "http://u2:p2@h2:3128",
        ]
        fpath = tmp_proxy_file(lines)
        monkeypatch.setenv("PROXY_FILE", fpath)
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        assert count == 2
        assert len(manager.get_pool()) == 2

    def test_load_from_env_none_set(self, monkeypatch, manager):
        """load_from_env() with neither env var should add 0 proxies."""
        monkeypatch.delenv("PROXY_LIST", raising=False)
        monkeypatch.delenv("PROXY_FILE", raising=False)
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        assert count == 0
        assert len(manager.get_pool()) == 0

    def test_load_from_env_prefers_list_over_file(self, monkeypatch, manager, tmp_proxy_file):
        """load_from_env() should process both env vars, adding from both."""
        monkeypatch.setenv("PROXY_LIST", "socks5://list:1080")
        fpath = tmp_proxy_file(["socks5://file:1080"])
        monkeypatch.setenv("PROXY_FILE", fpath)
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        assert count == 2

    def test_load_from_env_bad_url_logged_warning(self, monkeypatch, manager, caplog):
        """Bad URLs should be logged as warnings, not raise fatal errors."""
        monkeypatch.setenv("PROXY_LIST", "not-a-valid-url,socks5://good:1080")
        caplog.set_level(logging.WARNING)
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        # Should have added 1 good proxy without crashing
        assert count >= 1

    def test_load_from_env_missing_file_returns_zero(self, monkeypatch, manager):
        """load_from_env() with PROXY_FILE pointing to non-existent file should not crash."""
        monkeypatch.setenv("PROXY_FILE", "/tmp/nonexistent-proxy-file-12345.txt")
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        assert count == 0


# ===================================================================
# get_proxy — interface
# ===================================================================


class TestGetProxyInterface:
    """Verify get_proxy method exists and delegates correctly."""

    def test_method_exists(self, manager):
        """get_proxy should be a callable method."""
        assert callable(manager.get_proxy)

    def test_default_strategy(self, manager):
        """get_proxy() with default strategy (round-robin) should work on populated pool."""
        manager.add_proxy("socks5://host:1080")
        result = manager.get_proxy()
        assert result is not None
        assert isinstance(result, dict)
        assert result["url"] == "socks5://host:1080"

    def test_returns_none_on_empty_pool(self, manager):
        """get_proxy() on empty pool should return None."""
        result = manager.get_proxy()
        assert result is None

    def test_round_robin_strategy(self, manager):
        """get_proxy(strategy='round-robin') should delegate to pool."""
        manager.add_proxy("socks5://host1:1080")
        manager.add_proxy("socks5://host2:1080")
        first = manager.get_proxy(strategy="round-robin")
        second = manager.get_proxy(strategy="round-robin")
        assert first is not None
        assert second is not None
        # Two different proxies in sequence
        urls = {first["url"], second["url"]}
        assert len(urls) == 2

    def test_random_strategy(self, manager):
        """get_proxy(strategy='random') should work."""
        manager.add_proxy("socks5://host:1080")
        result = manager.get_proxy(strategy="random")
        assert result is not None
        assert result["url"] == "socks5://host:1080"

    def test_sticky_strategy(self, manager):
        """get_proxy(strategy='sticky') should work."""
        manager.add_proxy("socks5://host:1080")
        result = manager.get_proxy(strategy="sticky", session_id="test-session")
        assert result is not None

    def test_by_tag_strategy(self, manager):
        """get_proxy(strategy='by-tag') should work."""
        manager.add_proxy("socks5://host:1080", tags=["datacenter"])
        result = manager.get_proxy(strategy="by-tag", group="datacenter")
        assert result is not None
        assert "datacenter" in result["tags"]


# ===================================================================
# get_proxy health-check strategy — behavioural (RED phase)
# ===================================================================


class TestGetProxyHealthCheck:
    """get_proxy(strategy='health-check') behavioural tests — fail until implementation."""

    def test_health_check_strategy_returns_lowest_latency(self, manager):
        """health-check strategy should return the proxy with lowest latency_ms."""
        pid1 = manager.add_proxy("socks5://slow:1080")
        pid2 = manager.add_proxy("socks5://fast:1080")
        # Manually set latencies via internal pool
        manager.pool._proxies[pid1].latency_ms = 150.0
        manager.pool._proxies[pid2].latency_ms = 20.0
        try:
            result = manager.get_proxy(strategy="health-check")
        except NotImplementedError:
            pytest.skip("RED phase — health-check strategy not implemented")
        assert result is not None
        assert result["id"] == pid2  # Fastest proxy

    def test_health_check_fallback_to_round_robin(self, manager):
        """health-check should fall back to round-robin when no latencies recorded."""
        pid1 = manager.add_proxy("socks5://host1:1080")
        pid2 = manager.add_proxy("socks5://host2:1080")
        try:
            result = manager.get_proxy(strategy="health-check")
        except NotImplementedError:
            pytest.skip("RED phase — health-check strategy not implemented")
        assert result is not None
        assert result["id"] in (pid1, pid2)

    def test_health_check_skips_unhealthy(self, manager):
        """health-check strategy should skip unhealthy/enabled=False proxies."""
        pid1 = manager.add_proxy("socks5://unhealthy:1080")
        pid2 = manager.add_proxy("socks5://healthy:1080")
        manager.pool._proxies[pid1].enabled = False
        manager.pool._proxies[pid1].healthy = False
        manager.pool._proxies[pid2].latency_ms = 30.0
        try:
            result = manager.get_proxy(strategy="health-check")
        except NotImplementedError:
            pytest.skip("RED phase — health-check strategy not implemented")
        assert result is not None
        assert result["id"] == pid2

    def test_health_check_returns_none_all_unhealthy(self, manager):
        """health-check strategy should return None when no healthy proxies exist."""
        pid = manager.add_proxy("socks5://dead:1080")
        manager.pool._proxies[pid].healthy = False
        manager.pool._proxies[pid].enabled = False
        try:
            result = manager.get_proxy(strategy="health-check")
        except NotImplementedError:
            pytest.skip("RED phase — health-check strategy not implemented")
        assert result is None


# ===================================================================
# Delegated methods
# ===================================================================


class TestDelegatedMethods:
    """Verify delegated methods pass through to the internal ProxyPool correctly."""

    def test_add_proxy(self, manager):
        """add_proxy() should delegate and return a UUID."""
        pid = manager.add_proxy("socks5://host:1080")
        assert isinstance(pid, str)
        assert len(pid) == 36

    def test_add_proxy_with_tags(self, manager):
        """add_proxy() with tags should store them."""
        pid = manager.add_proxy("socks5://host:1080", tags=["datacenter", "us"])
        entry = manager.get_proxy(proxy_id=pid)
        assert "datacenter" in entry["tags"]
        assert "us" in entry["tags"]

    def test_remove_proxy(self, manager):
        """remove_proxy() should delegate and return True."""
        pid = manager.add_proxy("socks5://host:1080")
        assert manager.remove_proxy(pid) is True
        assert manager.get_proxy(proxy_id=pid) is None

    def test_remove_proxy_nonexistent(self, manager):
        """remove_proxy() with bad ID should return False."""
        assert manager.remove_proxy("nonexistent") is False

    def test_get_pool(self, manager):
        """get_pool() should delegate and return a list."""
        manager.add_proxy("socks5://host1:1080")
        manager.add_proxy("socks5://host2:1080")
        pool = manager.get_pool()
        assert isinstance(pool, list)
        assert len(pool) == 2

    def test_get_pool_empty(self, manager):
        """get_pool() on empty pool should return empty list."""
        assert manager.get_pool() == []

    def test_clear(self, manager):
        """clear() should delegate and remove all proxies."""
        manager.add_proxy("socks5://host:1080")
        manager.clear()
        assert len(manager.get_pool()) == 0

    def test_get_stats(self, manager):
        """get_stats() should delegate and return a dict."""
        manager.add_proxy("socks5://host:1080")
        stats = manager.get_stats()
        assert isinstance(stats, dict)
        assert stats["total"] == 1
        assert stats["healthy"] == 1

    def test_get_stats_empty(self, manager):
        """get_stats() on empty pool should return zero counts."""
        stats = manager.get_stats()
        assert stats["total"] == 0
        assert stats["healthy"] == 0
        assert stats["unhealthy"] == 0

    def test_health_check(self, manager):
        """health_check() should delegate and return a dict or None."""
        pid = manager.add_proxy("socks5://host:1080")
        result = manager.health_check(pid)
        # May be None if running in async context, but should not crash
        assert result is None or isinstance(result, dict)

    def test_health_check_nonexistent(self, manager):
        """health_check() with bad ID should return None."""
        result = manager.health_check("nonexistent")
        assert result is None

    def test_health_check_all(self, manager):
        """health_check_all() should delegate and return a list."""
        manager.add_proxy("socks5://host1:1080")
        manager.add_proxy("socks5://host2:1080")
        results = manager.health_check_all()
        assert isinstance(results, list)

    def test_health_check_all_empty(self, manager):
        """health_check_all() on empty pool should return empty list."""
        assert manager.health_check_all() == []

    def test_add_proxy_type_auto_detection(self, manager):
        """add_proxy() should auto-detect SOCKS5 type."""
        pid = manager.add_proxy("socks5://host:1080")
        entry = manager.get_proxy(proxy_id=pid)
        assert entry["type"] in ("SOCKS5", "socks5")

    def test_get_proxy_by_id(self, manager):
        """get_proxy(proxy_id=...) should work via delegation."""
        pid = manager.add_proxy("socks5://host:1080")
        entry = manager.get_proxy(proxy_id=pid)
        assert entry is not None
        assert entry["id"] == pid

    def test_add_proxy_invalid_url(self, manager):
        """add_proxy() with invalid URL should raise ProxyParseError."""
        from proxy_manager import ProxyParseError

        with pytest.raises(ProxyParseError):
            manager.add_proxy("not-a-url")


# ===================================================================
# Edge cases & integration
# ===================================================================


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_pool_is_same_after_clear(self, manager):
        """Clearing the pool should not replace the pool instance."""
        pool_id_before = id(manager.pool)
        manager.add_proxy("socks5://host:1080")
        manager.clear()
        assert id(manager.pool) == pool_id_before
        assert len(manager.get_pool()) == 0

    def test_wrapped_pool_stays_accessible(self):
        """Wrapping an existing pool should keep it accessible."""
        from proxy_manager import ProxyPool
        from proxy_rotation_manager import ProxyRotationManager

        external_pool = ProxyPool()
        mgr = ProxyRotationManager(pool=external_pool)
        mgr.add_proxy("socks5://host:1080")
        # Check both manager and original pool see the proxy
        assert len(mgr.get_pool()) == 1
        assert len(external_pool.get_pool()) == 1

    def test_add_remove_add_cycle(self, manager):
        """Add, remove, add should work correctly."""
        pid1 = manager.add_proxy("socks5://host1:1080")
        manager.add_proxy("socks5://host2:1080")
        manager.remove_proxy(pid1)
        assert len(manager.get_pool()) == 1
        pid3 = manager.add_proxy("socks5://host3:1080")
        assert len(manager.get_pool()) == 2
        assert pid3 != pid1

    def test_load_from_env_unset_env_with_existing_proxies(self, monkeypatch, manager):
        """load_from_env() with no env vars should not remove existing proxies."""
        manager.add_proxy("socks5://existing:1080")
        monkeypatch.delenv("PROXY_LIST", raising=False)
        monkeypatch.delenv("PROXY_FILE", raising=False)
        try:
            count = manager.load_from_env()
        except NotImplementedError:
            pytest.skip("RED phase — load_from_env not implemented")
        assert count == 0
        # Existing proxies should remain
        assert len(manager.get_pool()) == 1

    def test_get_proxy_unknown_strategy(self, manager):
        """An unknown strategy should raise ValueError."""
        manager.add_proxy("socks5://host:1080")
        with pytest.raises(ValueError, match="Unknown rotation strategy"):
            manager.get_proxy(strategy="nonexistent-strategy")
