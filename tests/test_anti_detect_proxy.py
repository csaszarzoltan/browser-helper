"""
Tests for ProxyRotationManager (P0.3).

Interface tests: verify imports, constructor, delegation to ProxyPool.
Behavioral tests: verify load_from_env env-var parsing and the
health-check rotation strategy (implementation exists; the stale
RED-phase NotImplementedError assertions were removed — see a7952e5).

Coverage:
  - ProxyRotationManager class existence and constructor
  - Delegated methods (add_proxy, remove_proxy, get_pool, clear, get_stats, health_check, health_check_all)
  - load_from_env() with PROXY_LIST / PROXY_FILE env vars
  - get_proxy(strategy="health-check")
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from proxy_manager import ProxyPool
from proxy_rotation_manager import ProxyRotationManager

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def mgr() -> ProxyRotationManager:
    """Return a fresh ProxyRotationManager with an isolated ProxyPool."""
    return ProxyRotationManager()


@pytest.fixture
def mgr_with_pool() -> tuple[ProxyRotationManager, ProxyPool]:
    """Return a manager wrapping an explicit ProxyPool."""
    pool = ProxyPool()
    return ProxyRotationManager(pool=pool), pool


# ===================================================================
# Interface tests — pass immediately against the stub
# ===================================================================


class TestProxyRotationManagerInterface:
    """Verify the ProxyRotationManager class exists and can be constructed."""

    def test_import(self):
        """ProxyRotationManager is importable from proxy_rotation_manager."""
        assert ProxyRotationManager is not None

    def test_constructor_no_args(self, mgr):
        """__init__() creates an instance without an existing pool."""
        assert isinstance(mgr, ProxyRotationManager)

    def test_constructor_with_pool(self, mgr_with_pool):
        """__init__(pool=pool) wraps the provided pool."""
        mgr, pool = mgr_with_pool
        assert mgr.pool is pool

    def test_pool_property(self, mgr):
        """pool property exposes a ProxyPool instance."""
        assert isinstance(mgr.pool, ProxyPool)

    def test_add_proxy_delegates(self, mgr):
        """add_proxy delegates to ProxyPool and returns a UUID string."""
        proxy_id = mgr.add_proxy("socks5://u:p@h:1080")
        assert isinstance(proxy_id, str) and len(proxy_id) > 0

    def test_get_pool_returns_list(self, mgr):
        """get_pool returns a list of proxy dicts."""
        pool = mgr.get_pool()
        assert isinstance(pool, list)

    def test_remove_proxy_delegates(self, mgr):
        """remove_proxy delegates to ProxyPool and returns a bool."""
        proxy_id = mgr.add_proxy("http://test:1080")
        result = mgr.remove_proxy(proxy_id)
        assert result is True

    def test_remove_proxy_nonexistent(self, mgr):
        """remove_proxy on nonexistent id returns False."""
        assert mgr.remove_proxy("nonexistent") is False

    def test_clear_works(self, mgr):
        """clear empties the pool without error."""
        mgr.add_proxy("http://test:1080")
        mgr.clear()
        assert len(mgr.get_pool()) == 0

    def test_get_stats_returns_dict(self, mgr):
        """get_stats returns a stats dict."""
        stats = mgr.get_stats()
        assert isinstance(stats, dict)

    def test_health_check_nonexistent(self, mgr):
        """health_check on a nonexistent proxy returns None."""
        result = mgr.health_check("nonexistent")
        assert result is None

    def test_health_check_all_returns_list(self, mgr):
        """health_check_all returns a list (empty for empty pool)."""
        results = mgr.health_check_all()
        assert isinstance(results, list)


# ===================================================================
# Behavioral tests — RED phase, must raise NotImplementedError
# ===================================================================


class TestProxyRotationManagerLoadFromEnvRED:
    """load_from_env() — behavioral tests (implementation exists)."""

    def test_load_from_env_with_proxy_list_returns_int(self, mgr):
        """load_from_env() with PROXY_LIST set should return the count of proxies added."""
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setenv("PROXY_LIST", "socks5://a:1080,http://b:3128")
                count = mgr.load_from_env()
                assert isinstance(count, int)
        except NotImplementedError:
            pytest.fail(
                "load_from_env must be implemented to test PROXY_LIST parsing. "
                "See test_load_from_env_raises_not_implemented."
            )

    def test_load_from_env_with_proxy_file_returns_int(self, mgr, tmp_path):
        """load_from_env() with PROXY_FILE set should read proxies from file."""
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("socks5://a:1080\nhttp://b:3128\n# comment\n\nhttp://c:443\n")
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setenv("PROXY_FILE", str(proxy_file))
                count = mgr.load_from_env()
                assert isinstance(count, int)
                assert count == 3  # 3 non-empty non-comment lines
        except NotImplementedError:
            pytest.fail(
                "load_from_env must be implemented to test PROXY_FILE parsing. "
                "See test_load_from_env_raises_not_implemented."
            )

    def test_load_from_env_no_env_vars(self, mgr):
        """load_from_env() with neither PROXY_LIST nor PROXY_FILE adds 0 proxies."""
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.delenv("PROXY_LIST", raising=False)
                mp.delenv("PROXY_FILE", raising=False)
                count = mgr.load_from_env()
                assert count == 0
        except NotImplementedError:
            pytest.fail(
                "load_from_env must be implemented to test empty-env case. "
                "See test_load_from_env_raises_not_implemented."
            )

    def test_load_from_env_bad_urls_logged_not_fatal(self, mgr):
        """Bad proxy URLs in PROXY_LIST are logged as warnings, not raised as errors."""
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setenv("PROXY_LIST", "invalid-url,,socks5://good:1080")
                count = mgr.load_from_env()
                # Should not crash; valid proxy should be added
                assert isinstance(count, int)
        except NotImplementedError:
            pytest.fail(
                "load_from_env must be implemented to test graceful error handling. "
                "See test_load_from_env_raises_not_implemented."
            )


class TestProxyRotationManagerHealthCheckStrategyRED:
    """get_proxy(strategy='health-check') — behavioral tests (implementation exists)."""

    def test_health_check_other_strategies_work(self, mgr):
        """Non-health-check strategies delegate to ProxyPool without error."""
        mgr.add_proxy("socks5://test:1080")
        proxy = mgr.get_proxy(strategy="round-robin")
        assert proxy is not None
        assert isinstance(proxy, dict)

    def test_health_check_returns_lowest_latency(self, mgr):
        """health-check strategy should return the proxy with the lowest latency_ms."""
        mgr.add_proxy("http://slow:1080")
        mgr.add_proxy("http://fast:1080")
        # Access ProxyPool directly to set latencies for testing
        pool_entries = mgr.pool.get_pool()
        if len(pool_entries) >= 2:
            # ProxyPool returns dicts; set latency via the internal _proxies dict
            ids = list(mgr.pool._proxies.keys())[:2]
            mgr.pool._proxies[ids[0]].latency_ms = 200.0
            mgr.pool._proxies[ids[1]].latency_ms = 10.0
        try:
            proxy = mgr.get_proxy(strategy="health-check")
            assert proxy is not None
            assert proxy.get("latency_ms", proxy.get("health", {}).get("latency_ms", 999)) < 100
        except NotImplementedError:
            pytest.fail(
                "health-check strategy must be implemented to verify lowest-latency selection. "
                "See test_health_check_strategy_raises_not_implemented."
            )

    def test_health_check_fallback_to_round_robin(self, mgr):
        """When no latencies recorded, health-check falls back to round-robin."""
        mgr.add_proxy("http://unchecked:1080")
        try:
            proxy = mgr.get_proxy(strategy="health-check")
            assert proxy is not None
        except NotImplementedError:
            pytest.fail(
                "health-check must implement fallback to round-robin when no latencies exist. "
                "See test_health_check_strategy_raises_not_implemented."
            )
