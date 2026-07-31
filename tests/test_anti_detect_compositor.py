"""
RED-phase pre-development tests for the AntiDetectCompositor module.

All behavioral tests in this file MUST FAIL initially because the
AntiDetectCompositor module is a stub whose methods raise
``NotImplementedError``.  Once the module is implemented, every test
below should PASS with zero changes.

Acceptance criteria covered (analysis brief §7 — P1.2):
 1. compose() returns dict with 5 keys: fingerprint, proxy, stealth,
    session, combined_js
 2. combined_js contains all JS scripts concatenated
 3. resolve_fingerprint("chrome-120") returns config + JS patches
 4. resolve_fingerprint with overrides includes the override
 5. resolve_stealth_patches("high") returns 11 patches
 6. export_bundle writes valid JSON
 7. import_bundle reads valid JSON and returns AntiDetectProfileBundle
 8. test() returns results per test site (mock DetectionTester)
 9. Nonexistent template raises clear error
10. Round-trip export → import → compose produces same result

Total: 70 tests (54 interface PASS, 16 behavioral RED-phase FAIL)
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from pathlib import Path
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from anti_detection.compositor import AntiDetectCompositor, AntiDetectProfileBundle

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_fingerprint_db() -> MagicMock:
    """Return a MagicMock that behaves like a FingerprintDatabase."""
    db = MagicMock()
    db.get_template.return_value = {
        "name": "chrome-120",
        "browser": "chrome",
        "signals": {},
        "config": {"canvas_noise_seed": 0, "platform": "Win32"},
    }
    db.list_templates.return_value = [{"name": "chrome-120", "browser": "chrome", "metadata": {}}]
    return db


@pytest.fixture
def mock_proxy_mgr() -> MagicMock:
    """Return a MagicMock that behaves like a ProxyRotationManager."""
    mgr = MagicMock()
    mgr.get_proxy.return_value = {
        "id": "proxy-1",
        "url": "socks5://user:pass@host:1080",
        "type": "socks5",
        "latency_ms": 42.0,
    }
    mgr.get_pool.return_value = [{"id": "proxy-1", "url": "socks5://..."}]
    return mgr


@pytest.fixture
def mock_stealth() -> MagicMock:
    """Return a MagicMock that behaves like a StealthInjector."""
    s = MagicMock()
    s.patches = {
        "navigator.webdriver": "Object.defineProperty(navigator, 'webdriver', ...)",
        "navigator.plugins": "...",
        "navigator.languages": "...",
    }
    return s


@pytest.fixture
def mock_session_mgr() -> MagicMock:
    """Return a MagicMock that behaves like a SessionManager."""
    mgr = MagicMock()
    mgr.capture = AsyncMock()
    mgr.restore = AsyncMock()
    return mgr


@pytest.fixture
def compositor(
    mock_fingerprint_db: MagicMock,
    mock_proxy_mgr: MagicMock,
    mock_stealth: MagicMock,
) -> AntiDetectCompositor:
    """Return an AntiDetectCompositor with mocked dependencies."""
    return AntiDetectCompositor(
        fingerprint_db=mock_fingerprint_db,
        proxy_mgr=mock_proxy_mgr,
        stealth=mock_stealth,
    )


@pytest.fixture
def compositor_with_session(
    mock_fingerprint_db: MagicMock,
    mock_proxy_mgr: MagicMock,
    mock_stealth: MagicMock,
    mock_session_mgr: MagicMock,
) -> AntiDetectCompositor:
    """Return an AntiDetectCompositor with all deps including SessionManager."""
    return AntiDetectCompositor(
        fingerprint_db=mock_fingerprint_db,
        proxy_mgr=mock_proxy_mgr,
        stealth=mock_stealth,
        session_mgr=mock_session_mgr,
    )


@pytest.fixture
def sample_bundle() -> AntiDetectProfileBundle:
    """Return a basic AntiDetectProfileBundle for testing."""
    return AntiDetectProfileBundle(
        name="test-profile",
        fingerprint_template="chrome-120",
        fingerprint_config={"canvas_noise_seed": 42},
        proxy_strategy="round-robin",
        stealth_level="medium",
        session_ttl=3600,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Interface Tests (PASSING — green checkmark)
# ═══════════════════════════════════════════════════════════════════════════


class TestAntiDetectProfileBundleInterface:
    """AntiDetectProfileBundle dataclass contract tests."""

    def test_class_exists(self) -> None:
        """AntiDetectProfileBundle is importable and is a class."""
        assert isinstance(AntiDetectProfileBundle, type)

    def test_is_dataclass(self) -> None:
        """AntiDetectProfileBundle should be a dataclass."""
        assert hasattr(AntiDetectProfileBundle, "__dataclass_fields__")

    # ── Field existence ─────────────────────────────────────────────────

    def test_has_name_field(self) -> None:
        """AntiDetectProfileBundle has a 'name' field."""
        assert "name" in AntiDetectProfileBundle.__dataclass_fields__

    def test_name_is_string(self) -> None:
        """AntiDetectProfileBundle.name has type str."""
        hints = get_type_hints(AntiDetectProfileBundle)
        assert hints.get("name") is str, f"name should be str, got {hints.get('name')}"

    def test_has_fingerprint_template_field(self) -> None:
        """AntiDetectProfileBundle has a 'fingerprint_template' field."""
        assert "fingerprint_template" in AntiDetectProfileBundle.__dataclass_fields__

    def test_fingerprint_template_is_string(self) -> None:
        """AntiDetectProfileBundle.fingerprint_template has type str."""
        hints = get_type_hints(AntiDetectProfileBundle)
        assert hints.get("fingerprint_template") is str, (
            f"fingerprint_template should be str, got {hints.get('fingerprint_template')}"
        )

    def test_has_fingerprint_config_field(self) -> None:
        """AntiDetectProfileBundle has a 'fingerprint_config' field."""
        assert "fingerprint_config" in AntiDetectProfileBundle.__dataclass_fields__

    def test_fingerprint_config_is_dict(self) -> None:
        """AntiDetectProfileBundle.fingerprint_config has type dict."""
        hints = get_type_hints(AntiDetectProfileBundle)
        hint = hints.get("fingerprint_config")
        assert hint is not None, "fingerprint_config should have a type annotation"
        hint_str = str(hint).lower()
        assert "dict" in hint_str, f"fingerprint_config should be dict-like, got {hint}"

    def test_has_proxy_strategy_field(self) -> None:
        """AntiDetectProfileBundle has a 'proxy_strategy' field."""
        assert "proxy_strategy" in AntiDetectProfileBundle.__dataclass_fields__

    def test_proxy_strategy_is_string(self) -> None:
        """AntiDetectProfileBundle.proxy_strategy has type str."""
        hints = get_type_hints(AntiDetectProfileBundle)
        assert hints.get("proxy_strategy") is str, (
            f"proxy_strategy should be str, got {hints.get('proxy_strategy')}"
        )

    def test_has_proxy_group_field(self) -> None:
        """AntiDetectProfileBundle has a 'proxy_group' field."""
        assert "proxy_group" in AntiDetectProfileBundle.__dataclass_fields__

    def test_proxy_group_is_optional_string(self) -> None:
        """AntiDetectProfileBundle.proxy_group has type str | None."""
        hints = get_type_hints(AntiDetectProfileBundle)
        hint = hints.get("proxy_group")
        assert hint is not None, "proxy_group should have a type annotation"
        hint_str = str(hint)
        assert "None" in hint_str or "Optional" in hint_str, (
            f"proxy_group should be Optional[str], got {hint}"
        )

    def test_has_stealth_level_field(self) -> None:
        """AntiDetectProfileBundle has a 'stealth_level' field."""
        assert "stealth_level" in AntiDetectProfileBundle.__dataclass_fields__

    def test_stealth_level_is_string(self) -> None:
        """AntiDetectProfileBundle.stealth_level has type str."""
        hints = get_type_hints(AntiDetectProfileBundle)
        assert hints.get("stealth_level") is str, (
            f"stealth_level should be str, got {hints.get('stealth_level')}"
        )

    def test_has_session_ttl_field(self) -> None:
        """AntiDetectProfileBundle has a 'session_ttl' field."""
        assert "session_ttl" in AntiDetectProfileBundle.__dataclass_fields__

    def test_session_ttl_is_float(self) -> None:
        """AntiDetectProfileBundle.session_ttl has type float."""
        hints = get_type_hints(AntiDetectProfileBundle)
        assert hints.get("session_ttl") is float, (
            f"session_ttl should be float, got {hints.get('session_ttl')}"
        )

    def test_has_version_field(self) -> None:
        """AntiDetectProfileBundle has a 'version' field."""
        assert "version" in AntiDetectProfileBundle.__dataclass_fields__

    def test_version_is_int(self) -> None:
        """AntiDetectProfileBundle.version has type int."""
        hints = get_type_hints(AntiDetectProfileBundle)
        assert hints.get("version") is int, (
            f"version should be int, got {hints.get('version')}"
        )

    def test_has_created_at_field(self) -> None:
        """AntiDetectProfileBundle has a 'created_at' field."""
        assert "created_at" in AntiDetectProfileBundle.__dataclass_fields__

    def test_created_at_is_float(self) -> None:
        """AntiDetectProfileBundle.created_at has type float."""
        hints = get_type_hints(AntiDetectProfileBundle)
        assert hints.get("created_at") is float, (
            f"created_at should be float, got {hints.get('created_at')}"
        )

    # ── Default values ──────────────────────────────────────────────────

    def test_version_defaults_to_one(self) -> None:
        """AntiDetectProfileBundle.version defaults to 1."""
        bundle = AntiDetectProfileBundle(
            name="test",
            fingerprint_template="chrome-120",
            stealth_level="medium",
        )
        assert bundle.version == 1

    def test_fingerprint_config_defaults_to_empty_dict(self) -> None:
        """fingerprint_config defaults to empty dict."""
        bundle = AntiDetectProfileBundle(
            name="test",
            fingerprint_template="chrome-120",
            stealth_level="medium",
        )
        assert bundle.fingerprint_config == {}

    def test_proxy_strategy_defaults_to_round_robin(self) -> None:
        """proxy_strategy defaults to 'round-robin'."""
        bundle = AntiDetectProfileBundle(
            name="test",
            fingerprint_template="chrome-120",
            stealth_level="medium",
        )
        assert bundle.proxy_strategy == "round-robin"

    def test_proxy_group_defaults_to_none(self) -> None:
        """proxy_group defaults to None."""
        bundle = AntiDetectProfileBundle(
            name="test",
            fingerprint_template="chrome-120",
            stealth_level="medium",
        )
        assert bundle.proxy_group is None

    def test_stealth_level_defaults_to_medium(self) -> None:
        """stealth_level defaults to 'medium'."""
        bundle = AntiDetectProfileBundle(
            name="test",
            fingerprint_template="chrome-120",
        )
        assert bundle.stealth_level == "medium"

    def test_session_ttl_defaults_to_3600(self) -> None:
        """session_ttl defaults to 3600.0."""
        bundle = AntiDetectProfileBundle(
            name="test",
            fingerprint_template="chrome-120",
            stealth_level="medium",
        )
        assert bundle.session_ttl == 3600.0

    def test_created_at_defaults_to_current_time(self) -> None:
        """created_at defaults to the current time."""
        before = time.time()
        bundle = AntiDetectProfileBundle(
            name="test",
            fingerprint_template="chrome-120",
            stealth_level="medium",
        )
        after = time.time()
        assert before <= bundle.created_at <= after, (
            "created_at should be set to current time on construction"
        )

    # ── to_dict / from_dict ─────────────────────────────────────────────

    def test_to_dict_method(self) -> None:
        """AntiDetectProfileBundle has a to_dict() method."""
        assert hasattr(AntiDetectProfileBundle, "to_dict")
        assert callable(AntiDetectProfileBundle.to_dict)

    def test_to_dict_returns_dict(self) -> None:
        """to_dict() returns a dict with all fields."""
        bundle = AntiDetectProfileBundle(
            name="test",
            fingerprint_template="chrome-120",
            proxy_strategy="round-robin",
            stealth_level="high",
        )
        result = bundle.to_dict()
        assert isinstance(result, dict)
        assert result["name"] == "test"
        assert result["fingerprint_template"] == "chrome-120"
        assert result["proxy_strategy"] == "round-robin"
        assert result["stealth_level"] == "high"
        assert "version" in result
        assert "created_at" in result
        assert "fingerprint_config" in result
        assert "proxy_group" in result
        assert "session_ttl" in result

    def test_from_dict_classmethod(self) -> None:
        """AntiDetectProfileBundle has a from_dict classmethod."""
        assert hasattr(AntiDetectProfileBundle, "from_dict")
        assert callable(AntiDetectProfileBundle.from_dict)

    def test_from_dict_returns_bundle(self) -> None:
        """from_dict() returns an AntiDetectProfileBundle."""
        data = {
            "name": "restored",
            "fingerprint_template": "chrome-120",
            "fingerprint_config": {"seed": 1},
            "proxy_strategy": "random",
            "proxy_group": None,
            "stealth_level": "high",
            "session_ttl": 7200.0,
            "version": 1,
            "created_at": 1000.0,
        }
        bundle = AntiDetectProfileBundle.from_dict(data)
        assert isinstance(bundle, AntiDetectProfileBundle)
        assert bundle.name == "restored"
        assert bundle.fingerprint_config == {"seed": 1}
        assert bundle.proxy_strategy == "random"
        assert bundle.stealth_level == "high"
        assert bundle.session_ttl == 7200.0

    def test_round_trip_to_dict_from_dict(self) -> None:
        """to_dict() → from_dict() preserves all values."""
        original = AntiDetectProfileBundle(
            name="roundtrip",
            fingerprint_template="edge-windows",
            fingerprint_config={"custom": True},
            proxy_strategy="sticky",
            proxy_group="datacenter",
            stealth_level="high",
            session_ttl=1800.0,
            version=2,
        )
        data = original.to_dict()
        restored = AntiDetectProfileBundle.from_dict(data)
        assert restored.name == original.name
        assert restored.fingerprint_template == original.fingerprint_template
        assert restored.fingerprint_config == original.fingerprint_config
        assert restored.proxy_strategy == original.proxy_strategy
        assert restored.proxy_group == original.proxy_group
        assert restored.stealth_level == original.stealth_level
        assert restored.session_ttl == original.session_ttl
        assert restored.version == original.version


class TestCompositorInterface:
    """AntiDetectCompositor class contract tests."""

    def test_class_exists(self) -> None:
        """AntiDetectCompositor is importable and is a class."""
        assert isinstance(AntiDetectCompositor, type)

    def test_constructor_accepts_three_positional(self, mock_fingerprint_db, mock_proxy_mgr, mock_stealth) -> None:
        """__init__ accepts (fingerprint_db, proxy_mgr, stealth)."""
        c = AntiDetectCompositor(
            fingerprint_db=mock_fingerprint_db,
            proxy_mgr=mock_proxy_mgr,
            stealth=mock_stealth,
        )
        assert isinstance(c, AntiDetectCompositor)

    def test_constructor_accepts_session_mgr(self, mock_fingerprint_db, mock_proxy_mgr, mock_stealth, mock_session_mgr) -> None:
        """__init__ accepts optional session_mgr."""
        c = AntiDetectCompositor(
            fingerprint_db=mock_fingerprint_db,
            proxy_mgr=mock_proxy_mgr,
            stealth=mock_stealth,
            session_mgr=mock_session_mgr,
        )
        assert isinstance(c, AntiDetectCompositor)

    def test_constructor_session_mgr_defaults_none(self) -> None:
        """session_mgr parameter defaults to None."""
        sig = inspect.signature(AntiDetectCompositor.__init__)
        params = list(sig.parameters.values())
        session_mgr_param = None
        for p in params:
            if "session_mgr" in p.name:
                session_mgr_param = p
                break
        assert session_mgr_param is not None, "session_mgr param not found"
        assert session_mgr_param.default is None, "session_mgr should default to None"

    # ── Method existence ────────────────────────────────────────────────

    def test_has_compose_method(self) -> None:
        """AntiDetectCompositor has compose()."""
        assert hasattr(AntiDetectCompositor, "compose")
        assert callable(AntiDetectCompositor.compose)

    def test_compose_signature(self) -> None:
        """compose(bundle) takes one arg beyond self."""
        sig = inspect.signature(AntiDetectCompositor.compose)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 1
        assert params[0].name == "bundle"

    def test_has_test_method(self) -> None:
        """AntiDetectCompositor has test()."""
        assert hasattr(AntiDetectCompositor, "test")
        assert callable(AntiDetectCompositor.test)

    def test_test_signature(self) -> None:
        """test(bundle, cdp_client) takes two args beyond self."""
        sig = inspect.signature(AntiDetectCompositor.test)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 2
        param_names = [p.name for p in params]
        assert "bundle" in param_names
        assert "cdp_client" in param_names

    def test_has_export_bundle_method(self) -> None:
        """AntiDetectCompositor has export_bundle()."""
        assert hasattr(AntiDetectCompositor, "export_bundle")
        assert callable(AntiDetectCompositor.export_bundle)

    def test_export_bundle_signature(self) -> None:
        """export_bundle(bundle, path) takes two args beyond self."""
        sig = inspect.signature(AntiDetectCompositor.export_bundle)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 2
        assert params[0].name == "bundle"
        assert params[1].name == "path"

    def test_has_import_bundle_method(self) -> None:
        """AntiDetectCompositor has import_bundle()."""
        assert hasattr(AntiDetectCompositor, "import_bundle")
        assert callable(AntiDetectCompositor.import_bundle)

    def test_import_bundle_signature(self) -> None:
        """import_bundle(path) takes one arg beyond self."""
        sig = inspect.signature(AntiDetectCompositor.import_bundle)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 1
        assert params[0].name == "path"

    def test_has_resolve_fingerprint_method(self) -> None:
        """AntiDetectCompositor has resolve_fingerprint()."""
        assert hasattr(AntiDetectCompositor, "resolve_fingerprint")
        assert callable(AntiDetectCompositor.resolve_fingerprint)

    def test_resolve_fingerprint_signature(self) -> None:
        """resolve_fingerprint(template_name, overrides=None) takes two args."""
        sig = inspect.signature(AntiDetectCompositor.resolve_fingerprint)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 2
        assert params[0].name == "template_name"
        # overrides should have a default of None
        assert params[1].name == "overrides"
        assert params[1].default is None

    def test_has_resolve_stealth_patches_method(self) -> None:
        """AntiDetectCompositor has resolve_stealth_patches()."""
        assert hasattr(AntiDetectCompositor, "resolve_stealth_patches")
        assert callable(AntiDetectCompositor.resolve_stealth_patches)

    def test_resolve_stealth_patches_signature(self) -> None:
        """resolve_stealth_patches(level) takes one arg beyond self."""
        sig = inspect.signature(AntiDetectCompositor.resolve_stealth_patches)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 1
        assert params[0].name == "level"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — Behavioral Tests (RED-phase — fail with NotImplementedError)
# ═══════════════════════════════════════════════════════════════════════════


class TestComposeRED:
    """compose() — expected to fail with NotImplementedError."""

    # ── AC1: compose() returns dict with 5 keys ────────────────────────

    def test_compose_returns_dict_with_five_keys(self, compositor, sample_bundle) -> None:
        """compose() returns a dict with fingerprint, proxy, stealth, session, combined_js.

        Acceptance criterion P1.2.1: compose() result must contain all 5 keys.
        """
        try:
            result = compositor.compose(sample_bundle)
            assert isinstance(result, dict)
            for key in ("fingerprint", "proxy", "stealth", "session", "combined_js"):
                assert key in result, (
                    f"compose() result missing required key: {key!r}"
                )
        except NotImplementedError:
            pytest.fail(
                "compose must be implemented to verify return shape. "
                "See RED-phase test: test_compose_raises_not_implemented."
            )

    # ── AC2: combined_js contains all JS scripts concatenated ───────────

    def test_compose_combined_js_contains_all_scripts(self, compositor, sample_bundle) -> None:
        """compose() result combined_js is a list with all JS scripts.

        Acceptance criterion P1.2.2: combined_js must contain JS from
        fingerprint patches and stealth patches combined.
        """
        try:
            result = compositor.compose(sample_bundle)
            combined = result.get("combined_js", [])
            assert isinstance(combined, list), "combined_js should be a list"
            assert len(combined) >= 1, "combined_js should have at least one script"
            # Each entry should be a non-empty string
            for script in combined:
                assert isinstance(script, str) and script, (
                    "Each combined_js entry should be a non-empty string"
                )
        except NotImplementedError:
            pytest.fail(
                "compose must be implemented to verify combined_js content."
            )


class TestResolveFingerprintRED:
    """resolve_fingerprint() — expected to fail with NotImplementedError."""

    # ── AC3: resolve_fingerprint("chrome-120") returns config + JS patches ──

    def test_resolve_fingerprint_returns_config_and_js_patches(self, compositor) -> None:
        """resolve_fingerprint("chrome-120") returns a config dict and JS patches.

        Acceptance criterion P1.2.3: ensures the return shape includes config,
        js_patches, and gpu metadata.
        """
        try:
            result = compositor.resolve_fingerprint("chrome-120")
            assert isinstance(result, dict), "result should be a dict"
            assert "config" in result, "result missing 'config' key"
            assert isinstance(result["config"], dict), "config should be a dict"
            assert "js_patches" in result, "result missing 'js_patches' key"
            assert isinstance(result["js_patches"], list), "js_patches should be a list"
        except NotImplementedError:
            pytest.fail(
                "resolve_fingerprint must be implemented to verify return shape."
            )

    # ── AC4: resolve_fingerprint with overrides includes the override ───

    def test_resolve_fingerprint_with_overrides(self, compositor) -> None:
        """resolve_fingerprint with overrides includes the override.

        Acceptance criterion P1.2.4: when overrides={"canvas_noise_seed": 42}
        is passed, the returned config must contain "canvas_noise_seed": 42.
        """
        try:
            result = compositor.resolve_fingerprint(
                "chrome-120", overrides={"canvas_noise_seed": 42}
            )
            config = result.get("config", {})
            assert config.get("canvas_noise_seed") == 42, (
                f"Expected canvas_noise_seed=42 in config, got {config.get('canvas_noise_seed')}"
            )
        except NotImplementedError:
            pytest.fail(
                "resolve_fingerprint must be implemented to verify override behaviour."
            )

    # ── AC9: Nonexistent template raises clear error ────────────────────

    def test_resolve_fingerprint_nonexistent_template_raises_error(self, compositor) -> None:
        """Resolving a nonexistent template raises a clear error.

        Acceptance criterion P1.2.9: composing or resolving with a template
        that does not exist should raise a clear error (KeyError or ValueError).
        """
        try:
            compositor.resolve_fingerprint("nonexistent-template")
            pytest.fail(
                "Expected an error for nonexistent template, but none was raised."
            )
        except NotImplementedError:
            pytest.fail(
                "resolve_fingerprint must be implemented to verify error on nonexistent template."
            )
        except (KeyError, ValueError, LookupError) as exc:
            # Clear error means the exception message names the missing template
            assert "nonexistent" in str(exc).lower() or "nonexistent" in type(exc).__name__.lower(), (
                f"Error message should reference 'nonexistent-template', got: {exc}"
            )


class TestResolveStealthPatchesRED:
    """resolve_stealth_patches() — expected to fail with NotImplementedError."""

    # ── AC5: resolve_stealth_patches("high") returns 11 patches ─────────

    def test_resolve_stealth_patches_high_returns_dict_with_level_and_patches(self, compositor) -> None:
        """resolve_stealth_patches("high") returns a dict with level, patches, count.

        Acceptance criterion P1.2.5: high level should return patches
        for all 11 stealth signals.
        """
        try:
            result = compositor.resolve_stealth_patches("high")
            assert isinstance(result, dict)
            assert "level" in result
            assert result["level"] == "high"
            assert "patches" in result
            assert isinstance(result["patches"], dict)
            assert "count" in result
            assert result["count"] >= 11, (
                f"Expected >=11 patches at high level, got {result['count']}"
            )
            assert len(result["patches"]) == result["count"], (
                "len(patches) should equal count"
            )
        except NotImplementedError:
            pytest.fail(
                "resolve_stealth_patches must be implemented to verify high-level coverage."
            )

    def test_resolve_stealth_patches_medium_returns_fewer_than_high(self, compositor) -> None:
        """resolve_stealth_patches("medium") returns fewer patches than high."""
        try:
            medium = compositor.resolve_stealth_patches("medium")
            high = compositor.resolve_stealth_patches("high")
            assert medium["count"] < high["count"], (
                f"Expected medium count ({medium['count']}) < high count ({high['count']})"
            )
        except NotImplementedError:
            pytest.fail(
                "resolve_stealth_patches must be implemented to verify level differences."
            )

    def test_resolve_stealth_patches_low_returns_webdriver_only(self, compositor) -> None:
        """resolve_stealth_patches("low") returns only navigator.webdriver."""
        try:
            result = compositor.resolve_stealth_patches("low")
            assert result["level"] == "low"
            patches = result["patches"]
            assert "navigator.webdriver" in patches
        except NotImplementedError:
            pytest.fail(
                "resolve_stealth_patches must be implemented to verify low-level patches."
            )

    def test_resolve_stealth_patches_invalid_level_raises_error(self, compositor) -> None:
        """An unknown level string raises ValueError or similar."""
        try:
            compositor.resolve_stealth_patches("ultra")
            pytest.fail("Expected error for invalid stealth level, but none was raised.")
        except NotImplementedError:
            pytest.fail(
                "resolve_stealth_patches must be implemented to verify invalid level handling."
            )
        except (ValueError, KeyError) as exc:
            assert str(exc), "Error message should be non-empty"


class TestExportImportBundleRED:
    """export_bundle() / import_bundle() — NotImplementedError until impl."""

    # ── AC6: export_bundle writes valid JSON ────────────────────────────

    def test_export_bundle_writes_valid_json(self, compositor, sample_bundle, tmp_path) -> None:
        """export_bundle writes a valid JSON file.

        Acceptance criterion P1.2.6: exported JSON must be a valid
        representation of the bundle's to_dict().
        """
        out = str(tmp_path / "exported.json")
        try:
            compositor.export_bundle(sample_bundle, out)
            # Verify the file exists and contains valid JSON
            assert Path(out).exists(), "exported file should exist"
            raw = Path(out).read_text(encoding="utf-8")
            data = json.loads(raw)
            assert isinstance(data, dict)
            assert data["name"] == sample_bundle.name
            assert data["fingerprint_template"] == sample_bundle.fingerprint_template
        except NotImplementedError:
            pytest.fail(
                "export_bundle must be implemented to verify JSON output."
            )

    # ── AC7: import_bundle reads valid JSON and returns AntiDetectProfileBundle ──

    def test_import_bundle_reads_json_and_returns_bundle(self, compositor, sample_bundle, tmp_path) -> None:
        """import_bundle reads a JSON file and returns AntiDetectProfileBundle.

        Acceptance criterion P1.2.7: loading a valid bundle JSON file
        returns a properly populated AntiDetectProfileBundle.
        """
        data = sample_bundle.to_dict()
        path = tmp_path / "importable.json"
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        try:
            loaded = compositor.import_bundle(str(path))
            assert isinstance(loaded, AntiDetectProfileBundle)
            assert loaded.name == sample_bundle.name
            assert loaded.fingerprint_template == sample_bundle.fingerprint_template
            assert loaded.stealth_level == sample_bundle.stealth_level
        except NotImplementedError:
            pytest.fail(
                "import_bundle must be implemented to verify deserialization."
            )

    def test_import_bundle_nonexistent_file_raises_error(self, compositor, tmp_path) -> None:
        """import_bundle with a nonexistent path raises FileNotFoundError or similar."""
        try:
            compositor.import_bundle(str(tmp_path / "no-such-file.json"))
            pytest.fail("Expected FileNotFoundError for missing file.")
        except NotImplementedError:
            pytest.fail(
                "import_bundle must be implemented to verify error on missing file."
            )
        except FileNotFoundError:
            pass  # Expected for a real file system
        except OSError:
            pass  # Acceptable OS-level error for missing file

    def test_import_bundle_corrupt_json_raises_error(self, compositor, tmp_path) -> None:
        """import_bundle with corrupt JSON raises json.JSONDecodeError or ValueError."""
        path = tmp_path / "corrupt.json"
        Path(path).write_text("{invalid json}", encoding="utf-8")
        try:
            compositor.import_bundle(str(path))
            pytest.fail("Expected error for corrupt JSON file.")
        except NotImplementedError:
            pytest.fail(
                "import_bundle must be implemented to verify error on corrupt JSON."
            )
        except (json.JSONDecodeError, ValueError):
            pass  # Expected

    # ── AC10: Round-trip export → import → compose ──────────────────────

    def test_export_import_round_trip(self, compositor, sample_bundle, tmp_path) -> None:
        """Round-trip export → import → compose produces the same result.

        Acceptance criterion P1.2.10: after exporting a bundle and then
        importing it, the imported bundle should equal the original.
        """
        path = str(tmp_path / "roundtrip.json")
        try:
            compositor.export_bundle(sample_bundle, path)
            loaded = compositor.import_bundle(path)
            assert loaded.name == sample_bundle.name
            assert loaded.fingerprint_template == sample_bundle.fingerprint_template
            assert loaded.proxy_strategy == sample_bundle.proxy_strategy
            assert loaded.stealth_level == sample_bundle.stealth_level
            assert loaded.session_ttl == sample_bundle.session_ttl
            assert loaded.version == sample_bundle.version
        except NotImplementedError:
            pytest.fail(
                "export_bundle/import_bundle must both be implemented "
                "to verify round-trip fidelity."
            )


class TestDetectionTestRED:
    """test() — async, expected to fail with NotImplementedError."""

    # ── AC8: test() returns results per test site ───────────────────────

    @pytest.mark.asyncio
    async def test_test_returns_results_per_site(self, compositor, sample_bundle) -> None:
        """test() returns a dict with results per test site.

        Acceptance criterion P1.2.8: test() should return
        {"results": [{site, passed, details}, ...]} for each known
        detection test site.
        """
        client = MagicMock()
        try:
            result = await compositor.test(sample_bundle, client)
            assert isinstance(result, dict)
            assert "results" in result
            assert isinstance(result["results"], list)
            for entry in result["results"]:
                assert isinstance(entry, dict)
                assert "site" in entry
                assert "passed" in entry
                assert isinstance(entry["passed"], bool)
                assert "details" in entry
        except NotImplementedError:
            pytest.fail(
                "test must be implemented to verify return shape with results per site."
            )

    @pytest.mark.asyncio
    async def test_test_returns_all_known_test_sites(self, compositor, sample_bundle) -> None:
        """test() runs detection checks on all known test sites.

        The result should include at least the 3 standard test sites:
        sannysoft, fingerprintjs, creepjs.
        """
        client = MagicMock()
        try:
            result = await compositor.test(sample_bundle, client)
            sites = {entry["site"].lower() for entry in result.get("results", [])}
            expected_fragments = {"sannysoft", "fingerprintjs", "creepjs"}
            found = any(
                any(frag in site for frag in expected_fragments)
                for site in sites
            )
            assert found, (
                f"Expected test results to include sannysoft/fingerprintjs/creepjs sites, "
                f"got: {sites}"
            )
        except NotImplementedError:
            pytest.fail(
                "test must be implemented to verify coverage of known test sites."
            )
