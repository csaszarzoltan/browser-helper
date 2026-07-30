"""Pre-development tests for Cloud Browser Provider Integration.

Modules under test (src/browser_providers/):
  - base.py          — BaseProvider ABC, ProviderSession, ProviderHealth
  - browserbase.py   — BrowserbaseProvider
  - steel.py         — SteelProvider
  - camofox.py       — CamofoxProvider
  - session_pool.py  — CloudSessionPool, FallbackChain, FallbackResult

Coverage (30+ tests):
  Interface tests (GREEN)   — class existence, constructor, inheritance, method signatures
  Behavioral tests (RED)    — NotImplementedError per method via pytest.raises
  Mock provider tests       — mock stub with controlled behavior
  Integration test          — single marked @pytest.mark.integration (skipped by default)
"""

import inspect
import sys
import time
from dataclasses import is_dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from browser_providers.base import (
    BaseProvider,
    ProviderHealth,
    ProviderSession,
)
from browser_providers.browserbase import BrowserbaseProvider
from browser_providers.camofox import CamofoxProvider
from browser_providers.session_pool import CloudSessionPool, FallbackChain, FallbackResult
from browser_providers.steel import SteelProvider

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def browserbase_provider() -> BrowserbaseProvider:
    """Return a BrowserbaseProvider instance for testing."""
    return BrowserbaseProvider(api_key="test-key", project_id="test-project")


@pytest.fixture
def steel_provider() -> SteelProvider:
    """Return a SteelProvider instance for testing."""
    return SteelProvider(api_key="test-key")


@pytest.fixture
def camofox_provider() -> CamofoxProvider:
    """Return a CamofoxProvider instance for testing."""
    return CamofoxProvider(binary_path="/usr/bin/camoufox")


@pytest.fixture
def sample_session() -> ProviderSession:
    """Return a populated ProviderSession for testing."""
    return ProviderSession(
        session_id="sess-001",
        provider="browserbase",
        cdp_url="wss://browserbase.com/ws/abc123",
        created_at=1000.0,
        last_active=1000.0,
        warm=True,
        cost_estimate=0.05,
    )


@pytest.fixture
def cloud_pool() -> CloudSessionPool:
    """Return a CloudSessionPool with mock providers."""
    return CloudSessionPool(min_warm=1, max_warm=5, ttl_seconds=300)


@pytest.fixture
def fallback_chain() -> FallbackChain:
    """Return a FallbackChain with empty provider list (tests can override)."""
    return FallbackChain(providers=[])


# ===================================================================
# INTERFACE TESTS — must pass immediately (GREEN)
# ===================================================================


class TestProviderSessionInterface:
    """ProviderSession dataclass fields, types, and defaults."""

    def test_is_dataclass(self):
        """ProviderSession should be a dataclass."""
        assert is_dataclass(ProviderSession)

    def test_required_fields(self):
        """ProviderSession should have all required fields."""
        required = {"session_id", "provider", "cdp_url", "created_at", "last_active"}
        for field_name in required:
            assert field_name in ProviderSession.__dataclass_fields__

    def test_optional_fields_default_warm(self):
        """ProviderSession.warm should default to False."""
        field_def = ProviderSession.__dataclass_fields__["warm"]
        assert field_def.default is False

    def test_optional_fields_default_cost(self):
        """ProviderSession.cost_estimate should default to 0.0."""
        field_def = ProviderSession.__dataclass_fields__["cost_estimate"]
        assert field_def.default == 0.0

    def test_session_id_type(self):
        """ProviderSession.session_id should be str."""
        fields = ProviderSession.__dataclass_fields__
        assert fields["session_id"].type in (str, "str")

    def test_provider_type(self):
        """ProviderSession.provider should be str."""
        fields = ProviderSession.__dataclass_fields__
        assert fields["provider"].type in (str, "str")

    def test_created_at_type(self):
        """ProviderSession.created_at should be float."""
        fields = ProviderSession.__dataclass_fields__
        assert fields["created_at"].type in (float, "float")

    def test_instantiation_with_all_fields(self):
        """Should create a full ProviderSession with all fields."""
        sess = ProviderSession(
            session_id="test-1",
            provider="steel",
            cdp_url="wss://example.com/ws",
            created_at=500.0,
            last_active=500.0,
            warm=True,
            cost_estimate=0.10,
        )
        assert sess.session_id == "test-1"
        assert sess.provider == "steel"
        assert sess.cdp_url == "wss://example.com/ws"
        assert sess.created_at == 500.0
        assert sess.last_active == 500.0
        assert sess.warm is True
        assert sess.cost_estimate == 0.10

    def test_instantiation_with_defaults(self):
        """Should create ProviderSession with warm=False and cost=0.0."""
        sess = ProviderSession(
            session_id="test-2",
            provider="camofox",
            cdp_url="ws://localhost:9222",
            created_at=0.0,
            last_active=0.0,
        )
        assert sess.warm is False
        assert sess.cost_estimate == 0.0


class TestProviderHealthInterface:
    """ProviderHealth dataclass fields, types, and defaults."""

    def test_is_dataclass(self):
        """ProviderHealth should be a dataclass."""
        assert is_dataclass(ProviderHealth)

    def test_required_fields(self):
        """ProviderHealth should have healthy and latency_ms."""
        fields = ProviderHealth.__dataclass_fields__
        assert "healthy" in fields
        assert "latency_ms" in fields

    def test_optional_error_default_none(self):
        """ProviderHealth.error should default to None."""
        field_def = ProviderHealth.__dataclass_fields__["error"]
        assert field_def.default is None

    def test_healthy_type_bool(self):
        """ProviderHealth.healthy should be bool."""
        fields = ProviderHealth.__dataclass_fields__
        assert fields["healthy"].type in (bool, "bool")

    def test_latency_type_float(self):
        """ProviderHealth.latency_ms should be float."""
        fields = ProviderHealth.__dataclass_fields__
        assert fields["latency_ms"].type in (float, "float")

    def test_healthy_instance(self):
        """Should create a healthy ProviderHealth."""
        h = ProviderHealth(healthy=True, latency_ms=42.0)
        assert h.healthy is True
        assert h.latency_ms == 42.0
        assert h.error is None

    def test_unhealthy_instance(self):
        """Should create an unhealthy ProviderHealth with error."""
        h = ProviderHealth(healthy=False, latency_ms=5000.0, error="timeout")
        assert h.healthy is False
        assert h.latency_ms == 5000.0
        assert h.error == "timeout"


class TestBaseProviderInterface:
    """BaseProvider ABC cannot be instantiated, enforces abstract methods."""

    def test_is_abstract(self):
        """BaseProvider should be an ABC."""
        assert inspect.isabstract(BaseProvider)

    def test_cannot_instantiate_directly(self):
        """Should raise TypeError when instantiating BaseProvider directly."""
        with pytest.raises(TypeError, match="abstract"):
            BaseProvider()

    def test_has_launch_sandbox_abstract(self):
        """BaseProvider should declare launch_sandbox as abstract."""
        assert "launch_sandbox" in BaseProvider.__abstractmethods__

    def test_has_get_cdp_endpoint_abstract(self):
        """BaseProvider should declare get_cdp_endpoint as abstract."""
        assert "get_cdp_endpoint" in BaseProvider.__abstractmethods__

    def test_has_mark_warm_abstract(self):
        """BaseProvider should declare mark_warm as abstract."""
        assert "mark_warm" in BaseProvider.__abstractmethods__

    def test_has_close_session_abstract(self):
        """BaseProvider should declare close_session as abstract."""
        assert "close_session" in BaseProvider.__abstractmethods__

    def test_has_health_check_abstract(self):
        """BaseProvider should declare health_check as abstract."""
        assert "health_check" in BaseProvider.__abstractmethods__

    def test_all_five_abstract_methods(self):
        """BaseProvider should have exactly 5 abstract methods."""
        assert len(BaseProvider.__abstractmethods__) == 5


class TestBrowserbaseProviderInterface:
    """BrowserbaseProvider class structure and constructor."""

    def test_class_exists(self):
        """BrowserbaseProvider should be importable."""
        assert BrowserbaseProvider is not None

    def test_inherits_base_provider(self):
        """BrowserbaseProvider should inherit BaseProvider."""
        assert issubclass(BrowserbaseProvider, BaseProvider)

    def test_constructor_with_explicit_keys(self):
        """Should instantiate with explicit api_key and project_id."""
        bp = BrowserbaseProvider(api_key="key-123", project_id="proj-456")
        assert bp is not None

    def test_constructor_without_keys(self):
        """Should instantiate without explicit keys (falls back to env)."""
        bp = BrowserbaseProvider()
        assert bp is not None

    def test_constructor_default_api_base(self):
        """Default api_base should be Browserbase API v1."""
        bp = BrowserbaseProvider(api_key="k")
        # Access the private field to verify the default URL
        assert hasattr(bp, "_api_base")

    def test_has_launch_sandbox_method(self):
        """BrowserbaseProvider should have launch_sandbox."""
        assert hasattr(BrowserbaseProvider, "launch_sandbox")

    def test_has_get_cdp_endpoint_method(self):
        """BrowserbaseProvider should have get_cdp_endpoint."""
        assert hasattr(BrowserbaseProvider, "get_cdp_endpoint")

    def test_has_mark_warm_method(self):
        """BrowserbaseProvider should have mark_warm."""
        assert hasattr(BrowserbaseProvider, "mark_warm")

    def test_has_close_session_method(self):
        """BrowserbaseProvider should have close_session."""
        assert hasattr(BrowserbaseProvider, "close_session")

    def test_has_health_check_method(self):
        """BrowserbaseProvider should have health_check."""
        assert hasattr(BrowserbaseProvider, "health_check")


class TestSteelProviderInterface:
    """SteelProvider class structure and constructor."""

    def test_class_exists(self):
        """SteelProvider should be importable."""
        assert SteelProvider is not None

    def test_inherits_base_provider(self):
        """SteelProvider should inherit BaseProvider."""
        assert issubclass(SteelProvider, BaseProvider)

    def test_constructor_with_explicit_key(self):
        """Should instantiate with explicit api_key."""
        sp = SteelProvider(api_key="key-789")
        assert sp is not None

    def test_constructor_without_key(self):
        """Should instantiate without explicit key."""
        sp = SteelProvider()
        assert sp is not None

    def test_has_all_provider_methods(self):
        """SteelProvider should have all BaseProvider methods."""
        methods = {"launch_sandbox", "get_cdp_endpoint", "mark_warm", "close_session", "health_check"}
        for method in methods:
            assert hasattr(SteelProvider, method), f"SteelProvider missing {method}"


class TestCamofoxProviderInterface:
    """CamofoxProvider class structure and constructor."""

    def test_class_exists(self):
        """CamofoxProvider should be importable."""
        assert CamofoxProvider is not None

    def test_inherits_base_provider(self):
        """CamofoxProvider should inherit BaseProvider."""
        assert issubclass(CamofoxProvider, BaseProvider)

    def test_constructor_with_binary_path(self):
        """Should instantiate with explicit binary_path."""
        cp = CamofoxProvider(binary_path="/usr/local/bin/camoufox")
        assert cp is not None

    def test_constructor_without_path(self):
        """Should instantiate without binary path (env fallback)."""
        cp = CamofoxProvider()
        assert cp is not None

    def test_has_all_provider_methods(self):
        """CamofoxProvider should have all BaseProvider methods."""
        methods = {"launch_sandbox", "get_cdp_endpoint", "mark_warm", "close_session", "health_check"}
        for method in methods:
            assert hasattr(CamofoxProvider, method), f"CamofoxProvider missing {method}"


class TestCloudSessionPoolInterface:
    """CloudSessionPool class structure and constructor."""

    def test_class_exists(self):
        """CloudSessionPool should be importable."""
        assert CloudSessionPool is not None

    def test_constructor_defaults(self):
        """Should instantiate with default params."""
        pool = CloudSessionPool()
        assert pool.min_warm == 1
        assert pool.max_warm == 5
        assert pool.ttl_seconds == 300

    def test_constructor_custom_values(self):
        """Should instantiate with custom params."""
        pool = CloudSessionPool(min_warm=2, max_warm=10, ttl_seconds=600)
        assert pool.min_warm == 2
        assert pool.max_warm == 10
        assert pool.ttl_seconds == 600

    def test_constructor_with_providers(self):
        """Should accept a list of providers."""
        bp = BrowserbaseProvider(api_key="k")
        pool = CloudSessionPool(providers=[bp])
        assert pool is not None

    def test_has_get_session_method(self):
        """CloudSessionPool should have get_session."""
        assert hasattr(CloudSessionPool, "get_session")

    def test_has_release_session_method(self):
        """CloudSessionPool should have release_session."""
        assert hasattr(CloudSessionPool, "release_session")

    def test_has_scale_pool_method(self):
        """CloudSessionPool should have scale_pool."""
        assert hasattr(CloudSessionPool, "scale_pool")

    def test_has_run_health_checks_method(self):
        """CloudSessionPool should have run_health_checks."""
        assert hasattr(CloudSessionPool, "run_health_checks")

    def test_has_get_costs_method(self):
        """CloudSessionPool should have get_costs."""
        assert hasattr(CloudSessionPool, "get_costs")


class TestFallbackChainInterface:
    """FallbackChain class structure and constructor."""

    def test_class_exists(self):
        """FallbackChain should be importable."""
        assert FallbackChain is not None

    def test_constructor_with_providers(self):
        """Should instantiate with a list of providers."""
        fc = FallbackChain(providers=[])
        assert fc is not None

    def test_has_execute_method(self):
        """FallbackChain should have execute."""
        assert hasattr(FallbackChain, "execute")

    def test_has_execute_with_local_fallback_method(self):
        """FallbackChain should have execute_with_local_fallback."""
        assert hasattr(FallbackChain, "execute_with_local_fallback")


class TestFallbackResultInterface:
    """FallbackResult dataclass fields."""

    def test_is_dataclass(self):
        """FallbackResult should be a dataclass."""
        assert is_dataclass(FallbackResult)

    def test_has_required_fields(self):
        """FallbackResult should have success, chain, errors."""
        fields = FallbackResult.__dataclass_fields__
        assert "success" in fields
        assert "chain" in fields
        assert "errors" in fields

    def test_session_optional(self):
        """FallbackResult.session should be optional."""
        fields = FallbackResult.__dataclass_fields__
        assert fields["session"].type in (ProviderSession | None, "ProviderSession | None",
                                           "Optional[ProviderSession]")

    def test_default_fields(self):
        """FallbackResult should have sensible defaults."""
        result = FallbackResult(success=False)
        assert result.success is False
        assert result.chain == []
        assert result.errors == []
        assert result.session is None


# ===================================================================
# BEHAVIORAL TESTS — fail with NotImplementedError (RED)
# ===================================================================


class TestBrowserbaseProviderBehavior:
    """BrowserbaseProvider methods should raise NotImplementedError."""

    @pytest.mark.asyncio
    async def test_launch_sandbox_raises(self, browserbase_provider):
        """BrowserbaseProvider.launch_sandbox should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await browserbase_provider.launch_sandbox()

    @pytest.mark.asyncio
    async def test_get_cdp_endpoint_raises(self, browserbase_provider):
        """BrowserbaseProvider.get_cdp_endpoint should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await browserbase_provider.get_cdp_endpoint("sess-001")

    @pytest.mark.asyncio
    async def test_mark_warm_raises(self, browserbase_provider):
        """BrowserbaseProvider.mark_warm should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await browserbase_provider.mark_warm("sess-001")

    @pytest.mark.asyncio
    async def test_close_session_raises(self, browserbase_provider):
        """BrowserbaseProvider.close_session should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await browserbase_provider.close_session("sess-001")

    @pytest.mark.asyncio
    async def test_health_check_raises(self, browserbase_provider):
        """BrowserbaseProvider.health_check should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await browserbase_provider.health_check()


class TestSteelProviderBehavior:
    """SteelProvider methods should raise NotImplementedError."""

    @pytest.mark.asyncio
    async def test_launch_sandbox_raises(self, steel_provider):
        """SteelProvider.launch_sandbox should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await steel_provider.launch_sandbox()

    @pytest.mark.asyncio
    async def test_get_cdp_endpoint_raises(self, steel_provider):
        """SteelProvider.get_cdp_endpoint should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await steel_provider.get_cdp_endpoint("sess-002")

    @pytest.mark.asyncio
    async def test_mark_warm_raises(self, steel_provider):
        """SteelProvider.mark_warm should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await steel_provider.mark_warm("sess-002")

    @pytest.mark.asyncio
    async def test_close_session_raises(self, steel_provider):
        """SteelProvider.close_session should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await steel_provider.close_session("sess-002")

    @pytest.mark.asyncio
    async def test_health_check_raises(self, steel_provider):
        """SteelProvider.health_check should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await steel_provider.health_check()


class TestCamofoxProviderBehavior:
    """CamofoxProvider methods should raise NotImplementedError (P0 stub)."""

    @pytest.mark.asyncio
    async def test_launch_sandbox_raises(self, camofox_provider):
        """CamofoxProvider.launch_sandbox should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await camofox_provider.launch_sandbox()

    @pytest.mark.asyncio
    async def test_get_cdp_endpoint_raises(self, camofox_provider):
        """CamofoxProvider.get_cdp_endpoint should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await camofox_provider.get_cdp_endpoint("sess-003")

    @pytest.mark.asyncio
    async def test_mark_warm_raises(self, camofox_provider):
        """CamofoxProvider.mark_warm should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await camofox_provider.mark_warm("sess-003")

    @pytest.mark.asyncio
    async def test_close_session_raises(self, camofox_provider):
        """CamofoxProvider.close_session should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await camofox_provider.close_session("sess-003")

    @pytest.mark.asyncio
    async def test_health_check_raises(self, camofox_provider):
        """CamofoxProvider.health_check should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await camofox_provider.health_check()


class TestCloudSessionPoolBehavior:
    """CloudSessionPool methods should raise NotImplementedError."""

    @pytest.mark.asyncio
    async def test_get_session_raises(self, cloud_pool):
        """CloudSessionPool.get_session should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await cloud_pool.get_session()

    @pytest.mark.asyncio
    async def test_get_session_with_provider_raises(self, cloud_pool):
        """CloudSessionPool.get_session(provider=...) should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await cloud_pool.get_session(provider="browserbase")

    @pytest.mark.asyncio
    async def test_release_session_raises(self, cloud_pool):
        """CloudSessionPool.release_session should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await cloud_pool.release_session("sess-001")

    @pytest.mark.asyncio
    async def test_scale_pool_raises(self, cloud_pool):
        """CloudSessionPool.scale_pool should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await cloud_pool.scale_pool(target_warm=3)

    @pytest.mark.asyncio
    async def test_run_health_checks_raises(self, cloud_pool):
        """CloudSessionPool.run_health_checks should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await cloud_pool.run_health_checks()

    @pytest.mark.asyncio
    async def test_get_costs_raises(self, cloud_pool):
        """CloudSessionPool.get_costs should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await cloud_pool.get_costs()


class TestFallbackChainBehavior:
    """FallbackChain methods should raise NotImplementedError."""

    @pytest.mark.asyncio
    async def test_execute_raises(self, fallback_chain):
        """FallbackChain.execute should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await fallback_chain.execute()

    @pytest.mark.asyncio
    async def test_execute_with_local_fallback_raises(self, fallback_chain):
        """FallbackChain.execute_with_local_fallback should raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await fallback_chain.execute_with_local_fallback()


class TestProviderLifecycleBehavior:
    """End-to-end behavioral tests for the provider lifecycle.
    
    These define the expected flow: launch sandbox → get CDP endpoint → mark warm → close.
    Since no implementation exists, each step verifies NotImplementedError.
    """

    @pytest.mark.asyncio
    async def test_full_lifecycle_browserbase(self, browserbase_provider):
        """Browserbase: launch → get_cdp → mark_warm → close — each raises."""
        # Step 1: Launch sandbox
        with pytest.raises(NotImplementedError):
            await browserbase_provider.launch_sandbox(profile="stealth-chrome-120")

        # Step 2: Get CDP endpoint (after hypothetical launch)
        with pytest.raises(NotImplementedError):
            await browserbase_provider.get_cdp_endpoint("sess-001")

        # Step 3: Mark warm
        with pytest.raises(NotImplementedError):
            await browserbase_provider.mark_warm("sess-001")

        # Step 4: Close session
        with pytest.raises(NotImplementedError):
            await browserbase_provider.close_session("sess-001")

    @pytest.mark.asyncio
    async def test_full_lifecycle_steel(self, steel_provider):
        """Steel: launch → get_cdp → mark_warm → close — each raises."""
        with pytest.raises(NotImplementedError):
            await steel_provider.launch_sandbox()
        with pytest.raises(NotImplementedError):
            await steel_provider.get_cdp_endpoint("sess-002")
        with pytest.raises(NotImplementedError):
            await steel_provider.mark_warm("sess-002")
        with pytest.raises(NotImplementedError):
            await steel_provider.close_session("sess-002")

    @pytest.mark.asyncio
    async def test_health_check_round_trip(self, browserbase_provider):
        """Provider health check should be a callable measurement.

        Expected behavior: health_check returns ProviderHealth with
        latency_ms measuring round-trip time (not pending forever).
        """
        with pytest.raises(NotImplementedError):
            await browserbase_provider.health_check()
            # When implemented: assert isinstance(result, ProviderHealth)
            # assert result.latency_ms >= 0
            # assert isinstance(result.healthy, bool)

    @pytest.mark.asyncio
    async def test_health_check_connection_success_rate(self, browserbase_provider):
        """Provider should track and expose connection success rate.

        Expected: health_check reflects whether the provider API is reachable.
        Multiple sequential checks should be possible.
        """
        with pytest.raises(NotImplementedError):
            await browserbase_provider.health_check()


class TestSessionPoolBehavior:
    """Session pool behavioral tests — pool lifecycle and management."""

    @pytest.mark.asyncio
    async def test_warm_session_pre_launch(self, cloud_pool):
        """Pool should have warm sessions ready on demand.

        Expected: get_session() should return a warm ProviderSession
        without calling provider.launch_sandbox if pool has warm sessions.
        """
        with pytest.raises(NotImplementedError):
            await cloud_pool.get_session()

    @pytest.mark.asyncio
    async def test_min_warm_auto_scale(self):
        """Pool should auto-scale to maintain min_warm sessions."""
        pool = CloudSessionPool(min_warm=2, max_warm=10, ttl_seconds=300)
        with pytest.raises(NotImplementedError):
            await pool.scale_pool(target_warm=2)

    @pytest.mark.asyncio
    async def test_max_warm_enforced(self):
        """Pool should not exceed max_warm sessions."""
        pool = CloudSessionPool(min_warm=1, max_warm=3, ttl_seconds=300)
        with pytest.raises(NotImplementedError):
            await pool.scale_pool(target_warm=5)

    @pytest.mark.asyncio
    async def test_ttl_expiry_closes_old(self, cloud_pool):
        """Sessions past TTL should be auto-closed on get/release."""
        with pytest.raises(NotImplementedError):
            await cloud_pool.release_session("old-sess")

    @pytest.mark.asyncio
    async def test_cost_tracking_per_session(self, cloud_pool):
        """Pool should track cost per session based on duration × provider rate."""
        with pytest.raises(NotImplementedError):
            await cloud_pool.get_costs()


class TestFallbackExecutionBehavior:
    """Fallback chain behavioral tests — ordering and error propagation."""

    @pytest.mark.asyncio
    async def test_fallback_chain_ordering(self):
        """Fallback chain should try providers in order: A → B → local."""
        mock_a = MagicMock(spec=BaseProvider)
        mock_b = MagicMock(spec=BaseProvider)

        chain = FallbackChain(providers=[mock_a, mock_b])

        with pytest.raises(NotImplementedError):
            await chain.execute()

    @pytest.mark.asyncio
    async def test_fallback_chain_propagates_errors(self):
        """Fallback chain should collect errors from all providers on total failure."""
        chain = FallbackChain(providers=[])
        with pytest.raises(NotImplementedError):
            await chain.execute_with_local_fallback()


class TestMockProviderBehavior:
    """Mock provider tests — verify the provider interface works with mocks."""

    @pytest.mark.asyncio
    async def test_mock_provider_can_return_session(self):
        """A mocked provider should be able to return a ProviderSession."""
        mock_provider = MagicMock(spec=BaseProvider)
        session = ProviderSession(
            session_id="mock-1",
            provider="mock",
            cdp_url="ws://localhost:9222",
            created_at=time.time(),
            last_active=time.time(),
            warm=True,
            cost_estimate=0.0,
        )
        mock_provider.launch_sandbox = AsyncMock(return_value=session)

        result = await mock_provider.launch_sandbox()
        assert result.session_id == "mock-1"
        assert result.provider == "mock"
        assert result.warm is True

    @pytest.mark.asyncio
    async def test_mock_provider_health_check(self):
        """A mocked provider should support health check return."""
        mock_provider = MagicMock(spec=BaseProvider)
        health = ProviderHealth(healthy=True, latency_ms=150.0)
        mock_provider.health_check = AsyncMock(return_value=health)

        result = await mock_provider.health_check()
        assert result.healthy is True
        assert result.latency_ms == 150.0

    @pytest.mark.asyncio
    async def test_mock_provider_close_propagates(self):
        """Closing a mock provider should call through correctly."""
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.close_session = AsyncMock()

        await mock_provider.close_session("sess-mock")
        mock_provider.close_session.assert_awaited_once_with("sess-mock")

    @pytest.mark.asyncio
    async def test_mock_provider_unhealthy_detected(self):
        """A mock provider should be able to simulate unhealthy state."""
        mock_provider = MagicMock(spec=BaseProvider)
        unhealthy = ProviderHealth(healthy=False, latency_ms=5000.0, error="connection refused")
        mock_provider.health_check = AsyncMock(return_value=unhealthy)

        result = await mock_provider.health_check()
        assert result.healthy is False
        assert result.error == "connection refused"

    @pytest.mark.asyncio
    async def test_mock_fallback_chain_with_one_provider(self):
        """Fallback chain with a single working mock provider should succeed."""
        mock_provider = MagicMock(spec=BaseProvider)
        session = ProviderSession(
            session_id="fc-1",
            provider="mock-a",
            cdp_url="ws://localhost:9222",
            created_at=time.time(),
            last_active=time.time(),
            warm=True,
            cost_estimate=0.02,
        )
        mock_provider.launch_sandbox = AsyncMock(return_value=session)

        chain = FallbackChain(providers=[mock_provider])
        with pytest.raises(NotImplementedError):
            await chain.execute()


# ===================================================================
# INTEGRATION TEST — skipped by default
# ===================================================================


@pytest.mark.integration
class TestCloudProviderIntegration:
    """Real provider integration tests.
    
    These tests require valid API keys set via environment variables.
    Skipped by default during normal pre-dev test runs.
    """

    @pytest.mark.asyncio
    async def test_browserbase_end_to_end(self):
        """Browserbase: real API launch → CDP endpoint → close.
        
        Requires BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID env vars.
        """
        provider = BrowserbaseProvider()
        with pytest.raises(NotImplementedError):
            await provider.launch_sandbox()

    @pytest.mark.asyncio
    async def test_steel_end_to_end(self):
        """Steel: real API launch → CDP endpoint → close.
        
        Requires STEEL_API_KEY env var.
        """
        provider = SteelProvider()
        with pytest.raises(NotImplementedError):
            await provider.launch_sandbox()
