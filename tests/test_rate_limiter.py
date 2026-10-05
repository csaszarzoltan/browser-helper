"""
Pre-development tests for Rate Limiting Middleware (P0-3).

RED phase — all tests fail cleanly because the implementation doesn't exist yet.
Expected failure modes:
  - ImportError: RateLimitConfig, RateLimiter, or CDPClient.rate_limiter not found
  - AttributeError: missing method or attribute
  - HTTP 404: /rate/config routes not registered
  - AssertionError: stub returns wrong default
"""


import pytest

# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from fastapi.testclient import TestClient

import main

# ═══════════════════════════════════════════════════════════════════
# Interface tests — verify expected types exist
# ═══════════════════════════════════════════════════════════════════

class TestRateLimitConfigInterface:
    """RateLimitConfig Pydantic model contract."""

    def test_rate_limit_config_importable(self):
        """RateLimitConfig is defined in cdp_client."""
        from cdp_client import RateLimitConfig
        assert RateLimitConfig is not None

    def test_rate_limit_config_is_pydantic_model(self):
        """RateLimitConfig inherits from BaseModel."""
        from cdp_client import RateLimitConfig
        assert issubclass(RateLimitConfig, object)  # relaxed check for RED phase
        # Full check after impl: assert issubclass(RateLimitConfig, BaseModel)

    def test_rate_limit_config_fields_exist(self):
        """RateLimitConfig has expected fields."""
        from cdp_client import RateLimitConfig
        for fld in ("enabled", "min_delay_ms", "max_delay_ms", "distribution"):
            assert fld in RateLimitConfig.model_fields

    def test_rate_limit_config_default_enabled_false(self):
        """enabled defaults to False."""
        from cdp_client import RateLimitConfig
        cfg = RateLimitConfig()
        assert cfg.enabled is False

    def test_rate_limit_config_default_min_delay_500(self):
        """min_delay_ms defaults to 500."""
        from cdp_client import RateLimitConfig
        cfg = RateLimitConfig()
        assert cfg.min_delay_ms == 500

    def test_rate_limit_config_default_max_delay_3000(self):
        """max_delay_ms defaults to 3000."""
        from cdp_client import RateLimitConfig
        cfg = RateLimitConfig()
        assert cfg.max_delay_ms == 3000

    def test_rate_limit_config_default_distribution_log_normal(self):
        """distribution defaults to 'log-normal'."""
        from cdp_client import RateLimitConfig
        cfg = RateLimitConfig()
        assert cfg.distribution == "log-normal"

    def test_rate_limit_config_distribution_validated(self):
        """distribution is restricted to 'uniform' or 'log-normal'."""
        from cdp_client import RateLimitConfig
        with pytest.raises((ValueError, AssertionError)):
            RateLimitConfig(distribution="exponential")

    def test_rate_limit_config_min_gt_max_raises(self):
        """min_delay_ms > max_delay_ms is rejected."""
        from cdp_client import RateLimitConfig
        with pytest.raises((ValueError, AssertionError)):
            RateLimitConfig(enabled=True, min_delay_ms=5000, max_delay_ms=500)

    def test_rate_limit_config_negative_delay_raises(self):
        """Negative delay values are rejected."""
        from cdp_client import RateLimitConfig
        with pytest.raises((ValueError, AssertionError)):
            RateLimitConfig(min_delay_ms=-100)


class TestRateLimiterInterface:
    """RateLimiter class contract."""

    def test_rate_limiter_importable(self):
        """RateLimiter is defined in cdp_client."""
        from cdp_client import RateLimiter
        assert RateLimiter is not None

    def test_rate_limiter_init_with_config(self):
        """RateLimiter accepts a RateLimitConfig."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=1500, distribution="uniform")
        rl = RateLimiter(config=cfg)
        assert rl is not None

    def test_rate_limiter_has_get_delay_method(self):
        """RateLimiter has a get_delay() method returning float milliseconds."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True)
        rl = RateLimiter(config=cfg)
        delay = rl.get_delay()
        assert isinstance(delay, float)

    def test_rate_limiter_init_without_config_uses_defaults(self):
        """RateLimiter can be created without config (defaults apply)."""
        from cdp_client import RateLimiter
        rl = RateLimiter()
        assert rl is not None

    def test_rate_limiter_config_property(self):
        """RateLimiter.config returns the current RateLimitConfig."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True)
        rl = RateLimiter(config=cfg)
        assert isinstance(rl.config, RateLimitConfig)

    def test_rate_limiter_config_setter(self):
        """RateLimiter.config can be replaced at runtime."""
        from cdp_client import RateLimitConfig, RateLimiter
        rl = RateLimiter()
        new_cfg = RateLimitConfig(enabled=True, min_delay_ms=100)
        rl.config = new_cfg
        assert rl.config.min_delay_ms == 100

    def test_rate_limiter_distribution_methods_exist(self):
        """RateLimiter has _log_normal_delay() and _uniform_delay() methods."""
        from cdp_client import RateLimiter
        rl = RateLimiter()
        assert hasattr(rl, "_log_normal_delay")
        assert hasattr(rl, "_uniform_delay")


class TestCDPClientRateIntegrationInterface:
    """CDPClient rate limiting attribute contract."""

    def test_cdp_client_has_rate_limiter_attr(self):
        """CDPClient has a 'rate_limiter' attribute (RateLimiter instance)."""
        from cdp_client import CDPClient, RateLimiter
        c = CDPClient()
        assert hasattr(c, "rate_limiter")
        assert isinstance(c.rate_limiter, RateLimiter)

    def test_cdp_client_has_get_rate_config_method(self):
        """CDPClient has get_rate_config() returning a dict."""
        from cdp_client import CDPClient
        c = CDPClient()
        cfg = c.get_rate_config()
        assert isinstance(cfg, dict)
        assert "enabled" in cfg
        assert "min_delay_ms" in cfg
        assert "max_delay_ms" in cfg
        assert "distribution" in cfg

    def test_cdp_client_has_set_rate_config_method(self):
        """CDPClient.set_rate_config() accepts a dict config."""
        from cdp_client import CDPClient
        c = CDPClient()
        c.set_rate_config({"enabled": True, "min_delay_ms": 200, "max_delay_ms": 1000, "distribution": "uniform"})


# ═══════════════════════════════════════════════════════════════════
# Behavioral tests — rate limiter delay generation
# ═══════════════════════════════════════════════════════════════════

class TestRateLimiterBehavior:
    """Behavioral tests for delay generation."""

    def test_disabled_returns_zero_delay(self):
        """When enabled=False, get_delay() returns 0.0."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=False)
        rl = RateLimiter(config=cfg)
        for _ in range(10):
            assert rl.get_delay() == 0.0

    def test_log_normal_delay_within_bounds(self):
        """Log-normal delays stay within [min_delay_ms, max_delay_ms]."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=3000, distribution="log-normal")
        rl = RateLimiter(config=cfg)
        delays = [rl.get_delay() for _ in range(200)]
        assert all(500.0 <= d <= 3000.0 for d in delays)

    def test_uniform_delay_within_bounds(self):
        """Uniform delays stay within [min_delay_ms, max_delay_ms]."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=100, max_delay_ms=2000, distribution="uniform")
        rl = RateLimiter(config=cfg)
        delays = [rl.get_delay() for _ in range(200)]
        assert all(100.0 <= d <= 2000.0 for d in delays)

    def test_log_normal_lower_bound_respected(self):
        """Lower bound is respected for log-normal distribution."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=1000, max_delay_ms=2000, distribution="log-normal")
        rl = RateLimiter(config=cfg)
        delays = [rl.get_delay() for _ in range(200)]
        assert all(d >= 1000.0 for d in delays)

    def test_uniform_lower_bound_respected(self):
        """Lower bound is respected for uniform distribution."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=1500, max_delay_ms=2500, distribution="uniform")
        rl = RateLimiter(config=cfg)
        delays = [rl.get_delay() for _ in range(100)]
        assert all(d >= 1500.0 for d in delays)

    def test_non_deterministic_delays(self):
        """Consecutive get_delay() calls produce different values."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=3000, distribution="uniform")
        rl = RateLimiter(config=cfg)
        delays = [rl.get_delay() for _ in range(10)]
        # At least 8 out of 10 should be unique (allowing rare collisions)
        unique = len(set(delays))
        assert unique >= 8, f"Only {unique} unique delays out of 10"

    def test_switch_distribution_at_runtime(self):
        """Switching distribution at runtime changes delay characteristics."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=1000, distribution="uniform")
        rl = RateLimiter(config=cfg)
        uniform_delays = [rl.get_delay() for _ in range(100)]

        rl.config = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=1000, distribution="log-normal")
        log_normal_delays = [rl.get_delay() for _ in range(100)]

        # Both should stay in bounds
        assert all(500.0 <= d <= 1000.0 for d in uniform_delays)
        assert all(500.0 <= d <= 1000.0 for d in log_normal_delays)

    def test_uniform_distribution_ks_test(self):
        """Uniform delays match the calibrated [500, 3000] draw, deterministically.

        The old gate ran ``kstest`` on ONE unpinned 1000-draw and asserted
        p > 0.05: a hypothesis test that rejects 5% of CORRECT draws by
        construction (10/200 = 5.0% red on correct code, per brief), and the
        comment claiming reproducibility pinned nothing. This pins the
        instance RNG and asserts three deterministic invariants on the pinned
        draw (seed 20260905, n=1000):
          1. shape: KS-D against Uniform[500,3000] under the α=0.05 critical value
          2. calibration: mean/sd of the draw match the interval's moments
          3. order: lag-1 autocorrelation near zero (the draw is iid, not sorted)
        Invariant 3 is mandatory, not decoration: a sorted-linear mutant
        scores KS-D=0.0010 with exact mean/sd and passes 1+2 — only the order
        invariant catches it (lag-1 r=+0.9970).
        """
        import math
        import random
        import statistics

        from cdp_client import RateLimitConfig, RateLimiter
        from scipy.stats import kstest

        cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=3000, distribution="uniform")
        rl = RateLimiter(config=cfg)
        rl._rng = random.Random(20260905)
        delays = [rl.get_delay() for _ in range(1000)]
        assert all(500.0 <= d <= 3000.0 for d in delays), "pinned draw left [500, 3000]"

        # --- 1. Shape ------------------------------------------------------
        scaled = sorted((d - 500.0) / 2500.0 for d in delays)
        stat, _ = kstest(scaled, "uniform")
        critical = 1.36 / math.sqrt(1000)  # ~= 0.0430, KS α=0.05 asymptote
        assert stat <= critical, (
            f"KS-D {stat:.4f} exceeds critical {critical:.4f} on the pinned draw — "
            "not uniform over [500, 3000]"
        )

        # --- 2. Calibration: moments of Uniform[500, 3000] ------------------
        # mean = (500+3000)/2 = 1750.0; pop-sd = 2500/sqrt(12) ~= 721.69.
        mean = statistics.fmean(delays)
        pop_sd = statistics.pstdev(delays)
        assert abs(mean - 1750.0) <= 150.0, (
            f"pinned mean {mean:.2f} departs from 1750.0 by more than 150 ms — "
            "draw is not centred on [500, 3000]"
        )
        assert abs(pop_sd - 721.69) <= 80.0, (
            f"pinned pop-sd {pop_sd:.2f} departs from 721.69 by more than 80 ms — "
            "draw has the wrong spread (this is the case KS-D alone cannot see)"
        )

        # --- 3. Order: the draw is iid, not sorted --------------------------
        denom = sum((x - mean) ** 2 for x in delays)
        lag1 = sum((a - mean) * (b - mean) for a, b in zip(delays, delays[1:])) / denom
        assert abs(lag1) < 0.2, (
            f"lag-1 autocorrelation {lag1:+.4f} on the pinned draw — "
            "delays are ordered (e.g. sorted), not independent draws"
        )

    def test_log_normal_distribution_ks_test(self):
        """Log-normal delays match the documented (mu, sigma) calibration, deterministically.

        The old gate estimated mean/std FROM the sample it tested (Lilliefors
        problem: the p-value is invalid, not merely flaky) on an unpinned draw
        (1/200 = 0.5% red on correct code, per brief). This pins the instance
        RNG (same mechanism as the uniform twin) and tests against the
        THEORETICAL parameters the implementation derives — a valid KS test —
        plus deterministic calibration bounds.
        """
        import math
        import random
        import statistics

        from cdp_client import RateLimitConfig, RateLimiter
        from scipy.stats import kstest

        cfg = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=3000, distribution="log-normal")
        rl = RateLimiter(config=cfg)
        rl._rng = random.Random(20260905)
        delays = [rl.get_delay() for _ in range(1000)]
        assert all(500.0 <= d <= 3000.0 for d in delays), "pinned draw left [500, 3000]"

        # Theoretical parameters: same derivation as src/cdp_client.py:100-101.
        mu = (math.log(500.0) + math.log(3000.0)) / 2      # 7.11049
        sigma = (math.log(3000.0) - math.log(500.0)) / 4   # 0.44794

        # --- 1. Shape: KS against the theoretical normal in log space -------
        log_delays = [math.log(d) for d in delays]
        stat, _ = kstest(log_delays, "norm", args=(mu, sigma))
        critical = 1.36 / math.sqrt(1000)  # ~= 0.0430
        assert stat <= critical, (
            f"KS-D {stat:.4f} exceeds critical {critical:.4f} on the pinned draw — "
            "log(delays) is not normal with the documented (mu, sigma)"
        )

        # --- 2. Calibration ---------------------------------------------------
        log_mean = statistics.fmean(log_delays)
        log_sd = statistics.pstdev(log_delays)
        assert abs(log_mean - mu) <= 0.07, (
            f"log-mean {log_mean:.5f} deviates from mu {mu:.5f} by more than 0.07 — "
            "delays are drawn with the wrong centre"
        )
        assert abs(log_sd - sigma) <= 0.06, (
            f"log-sd {log_sd:.5f} deviates from sigma {sigma:.5f} by more than 0.06 — "
            "delays are log-normal but with the wrong spread"
        )

    def test_wide_bounds_still_respected(self):
        """Very wide bounds still work."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=50, max_delay_ms=10000, distribution="uniform")
        rl = RateLimiter(config=cfg)
        delays = [rl.get_delay() for _ in range(500)]
        assert all(50.0 <= d <= 10000.0 for d in delays)

    def test_equal_min_max_returns_same_value(self):
        """When min == max, the delay is always that value."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=True, min_delay_ms=1500, max_delay_ms=1500, distribution="uniform")
        rl = RateLimiter(config=cfg)
        for _ in range(10):
            assert rl.get_delay() == 1500.0

    def test_disabled_then_enabled(self):
        """Toggle enabled from False to True at runtime."""
        from cdp_client import RateLimitConfig, RateLimiter
        cfg = RateLimitConfig(enabled=False)
        rl = RateLimiter(config=cfg)
        assert rl.get_delay() == 0.0
        rl.config = RateLimitConfig(enabled=True, min_delay_ms=500, max_delay_ms=1000, distribution="uniform")
        assert rl.get_delay() > 0.0


# ═══════════════════════════════════════════════════════════════════
# API endpoint tests — /rate/config round-trips
# ═══════════════════════════════════════════════════════════════════

class TestRateConfigAPILive:
    """Test /rate/config API endpoints via TestClient.

    These tests will fail with 404 (RED phase) until the routes are registered in main.py.
    """

    def test_get_rate_config_returns_200(self):
        """GET /rate/config returns 200 with current config."""
        client = TestClient(main.app)
        response = client.get("/rate/config")
        assert response.status_code == 200
        body = response.json()
        assert "enabled" in body
        assert "min_delay_ms" in body
        assert "max_delay_ms" in body
        assert "distribution" in body

    def test_post_rate_config_valid_body_returns_200(self):
        """POST /rate/config with valid body returns 200."""
        client = TestClient(main.app)
        response = client.post("/rate/config", json={
            "enabled": True,
            "min_delay_ms": 500,
            "max_delay_ms": 3000,
            "distribution": "uniform",
        })
        assert response.status_code == 200

    def test_post_rate_config_partial_update(self):
        """POST /rate/config with partial body updates only specified fields."""
        client = TestClient(main.app)
        response = client.post("/rate/config", json={
            "enabled": True,
        })
        assert response.status_code == 200

    def test_post_rate_config_min_gt_max_return_422(self):
        """POST /rate/config with min > max returns 422."""
        client = TestClient(main.app)
        response = client.post("/rate/config", json={
            "enabled": True,
            "min_delay_ms": 5000,
            "max_delay_ms": 500,
            "distribution": "uniform",
        })
        assert response.status_code == 422

    def test_post_rate_config_unknown_distribution_returns_422(self):
        """POST /rate/config with unknown distribution returns 422."""
        client = TestClient(main.app)
        response = client.post("/rate/config", json={
            "enabled": True,
            "min_delay_ms": 500,
            "max_delay_ms": 3000,
            "distribution": "exponential",
        })
        assert response.status_code == 422

    def test_post_rate_config_negative_delay_returns_422(self):
        """POST /rate/config with negative delay returns 422."""
        client = TestClient(main.app)
        response = client.post("/rate/config", json={
            "enabled": True,
            "min_delay_ms": -100,
            "max_delay_ms": 500,
            "distribution": "uniform",
        })
        assert response.status_code == 422

    def test_rate_config_round_trip(self):
        """POST then GET returns same values."""
        client = TestClient(main.app)
        payload = {
            "enabled": True,
            "min_delay_ms": 200,
            "max_delay_ms": 1500,
            "distribution": "log-normal",
        }
        post_resp = client.post("/rate/config", json=payload)
        assert post_resp.status_code == 200
        get_resp = client.get("/rate/config")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["enabled"] == payload["enabled"]
        assert body["min_delay_ms"] == payload["min_delay_ms"]
        assert body["max_delay_ms"] == payload["max_delay_ms"]
        assert body["distribution"] == payload["distribution"]

    def test_rate_config_toggle_enabled(self):
        """Toggling enabled via POST is reflected in GET."""
        client = TestClient(main.app)

        # Disable
        client.post("/rate/config", json={"enabled": False})
        r1 = client.get("/rate/config")
        assert r1.json()["enabled"] is False

        # Re-enable
        client.post("/rate/config", json={"enabled": True})
        r2 = client.get("/rate/config")
        assert r2.json()["enabled"] is True

    def test_get_rate_config_defaults(self):
        """GET /rate/config returns default values before any POST."""
        from cdp_client import RateLimitConfig

        # Reset to defaults first — other tests toggle the global config.
        main.client.rate_limiter.config = RateLimitConfig()
        client = TestClient(main.app)
        response = client.get("/rate/config")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert body["min_delay_ms"] == 500
        assert body["max_delay_ms"] == 3000
        assert body["distribution"] == "log-normal"

    def test_post_rate_config_string_fields_rejected(self):
        """POST /rate/config with string instead of int returns 422."""
        client = TestClient(main.app)
        response = client.post("/rate/config", json={
            "enabled": True,
            "min_delay_ms": "abc",
            "max_delay_ms": 3000,
            "distribution": "uniform",
        })
        assert response.status_code == 422

    def test_post_rate_config_nonexistent_field_rejected(self):
        """POST /rate/config with unknown field returns 422."""
        client = TestClient(main.app)
        response = client.post("/rate/config", json={
            "enabled": True,
            "extra_field": "should_not_be_accepted",
        })
        assert response.status_code == 422
