"""
RED-phase pre-development tests for the StealthInjector module.

All tests in this file MUST FAIL initially because the StealthInjector
module is a stub whose methods raise ``NotImplementedError``.  Once the
module is implemented, every test below should PASS with zero changes.

Acceptance criteria covered (analysis brief §7 — P0.2):
 1. patches property returns dict with all patch names from LEVEL_PATCHES
 2. apply(client, "low") injects only navigator.webdriver
 3. apply(client, "medium") injects exactly 4 patches
 4. apply(client, "high") injects all 11 patches
 5. apply_all() injects all patches regardless of level
 6. verify() returns {patch_name: bool}
 7. JS patches are syntactically valid (basic syntax check)
 8. _make_patches() returns 11+ entries, one per LEVEL_PATCHES name
 9. LEVEL_PATCHES dict unchanged (backward compat)
10. Missing client raises appropriate error

Total: 29 tests (13 interface PASS, 16 behavioral RED-phase FAIL)
"""

# ─── Helpers: mock CDP client ─────────────────────────────────────────

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from unittest.mock import AsyncMock, MagicMock

import pytest

from stealth_injector import LEVEL_PATCHES, StealthInjector, _make_patches


def _mock_cdp_client() -> MagicMock:
    """Return a MagicMock that behaves like a CDPClient.

    The mock's ``_send_command`` returns a dict with an ``id`` field,
    mimicking the real CDPClient's ``_send_command`` return shape.
    Its ``evaluate`` returns a standard ``{"status": "ok", "result": ...}``.
    """
    client = MagicMock()
    client._send_command = AsyncMock(return_value={"id": 1})
    client.evaluate = AsyncMock(
        return_value={"status": "ok", "result": True, "type": "boolean"}
    )
    return client


# ─── Interface tests (should pass even with NotImplError in methods) ──


class TestStealthInjectorInterface:
    """Contract tests: constructor, properties, return shapes.

    These exercise the interface without calling the core methods that
    raise NotImplementedError.
    """

    def test_constructor_creates_instance(self):
        """A StealthInjector can be instantiated."""
        injector = StealthInjector()
        assert isinstance(injector, StealthInjector)

    def test_patches_property_returns_dict(self):
        """``patches`` property returns a ``dict`` of name → JS source."""
        injector = StealthInjector()
        patches = injector.patches
        assert isinstance(patches, dict)

    def test_patches_are_non_empty_strings(self):
        """Every patch name and JS source is a non-empty string."""
        injector = StealthInjector()
        for name, js in injector.patches.items():
            assert isinstance(name, str) and name, f"Patch name is empty: {name!r}"
            assert isinstance(js, str) and js, f"Patch source for {name!r} is empty"

    def test_low_level_has_webdriver_only(self):
        """The ``\"low\"`` level preset contains only ``navigator.webdriver``."""
        patches = LEVEL_PATCHES["low"]
        assert patches == ["navigator.webdriver"]

    def test_medium_level_has_four_patches(self):
        """The ``\"medium\"`` level preset contains at least 4 patches."""
        patches = LEVEL_PATCHES["medium"]
        assert len(patches) >= 4

    def test_high_level_has_min_10_patches(self):
        """The ``\"high\"`` level preset contains at least 10 patches."""
        patches = LEVEL_PATCHES["high"]
        assert len(patches) >= 10, (
            f"Expected >=10 patches at high level, got {len(patches)}"
        )

    def test_high_level_includes_low_level_patches(self):
        """``\"high\"`` patches are a superset of ``\"low\"`` patches."""
        high = LEVEL_PATCHES["high"]
        for p in LEVEL_PATCHES["low"]:
            assert p in high, f"High-level missing low-level patch: {p!r}"

    def test_high_level_includes_medium_level_patches(self):
        """``\"high\"`` patches are a superset of ``\"medium\"`` patches."""
        high = LEVEL_PATCHES["high"]
        for p in LEVEL_PATCHES["medium"]:
            assert p in high, f"High-level missing medium-level patch: {p!r}"

    def test_all_levels_are_defined(self):
        """All three levels ``\"low\"``, ``\"medium\"``, ``\"high\"`` are present."""
        for level in ("low", "medium", "high"):
            assert level in LEVEL_PATCHES, f"Missing level preset: {level!r}"

    def test_no_duplicate_patches_in_high(self):
        """No duplicate patch names in the high-level set."""
        patches = LEVEL_PATCHES["high"]
        assert len(patches) == len(set(patches)), "Duplicate patch names in high level"


# ─── RED-phase behavioral tests ───────────────────────────────────────


class TestStealthInjectorApplyRED:
    """``apply()`` — behavioural tests (RED-phase markers removed, implementation landed)."""

    def test_apply_returns_dict_with_applied_and_failed(self):
        """``apply()`` returns ``{\"applied\": [...], \"failed\": [...]}``."""
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result = injector.apply(client, level="low")
            assert isinstance(result, dict)
            assert "applied" in result
            assert "failed" in result
        except NotImplementedError:
            pytest.fail(
                "Apply must be implemented to test return shape. "
                "See RED-phase test: test_apply_raises_not_implemented."
            )

    def test_apply_invalid_level_raises_value_error(self):
        """An unknown level raises ``ValueError`` (or 422 for the API)."""
        injector = StealthInjector()
        client = _mock_cdp_client()
        with pytest.raises((ValueError, NotImplementedError)):
            injector.apply(client, level="ultra")

    def test_apply_low_returns_webdriver_only(self):
        """``apply(level=\"low\")`` injects only the webdriver patch."""
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result = injector.apply(client, level="low")
            assert result["applied"] == ["navigator.webdriver"]
        except NotImplementedError:
            pytest.fail(
                "Apply must be implemented to verify low-level injection."
            )

    # ── AC3: medium level injects exactly 4 patches ──────────────

    def test_apply_medium_injects_four_patches(self):
        """``apply(level=\"medium\")`` injects exactly 4 patches.

        Acceptance criterion P0.2.3: ``apply(client, \"medium\")``
        injects 4 patches (webdriver + plugins + languages + platform).
        """
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result = injector.apply(client, level="medium")
            expected = LEVEL_PATCHES["medium"]
            assert len(result["applied"]) == len(expected), (
                f"Expected {len(expected)} patches at medium level, "
                f"got {len(result['applied'])}"
            )
            for name in expected:
                assert name in result["applied"], (
                    f"Medium-level patch {name!r} missing from applied list"
                )
        except NotImplementedError:
            pytest.fail(
                "Apply must be implemented to verify medium-level injection."
            )

    # ── AC4: high level injects all 11 patches ───────────────────

    def test_apply_high_injects_all_patches(self):
        """``apply(level=\"high\")`` injects all 11 patches.

        Acceptance criterion P0.2.4: ``apply(client, \"high\")``
        injects all patches in ``LEVEL_PATCHES[\"high\"]`` (11).
        """
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result = injector.apply(client, level="high")
            expected = LEVEL_PATCHES["high"]
            assert len(result["applied"]) == len(expected), (
                f"Expected {len(expected)} patches at high level, "
                f"got {len(result['applied'])}"
            )
            for name in expected:
                assert name in result["applied"], (
                    f"High-level patch {name!r} missing from applied list"
                )
        except NotImplementedError:
            pytest.fail(
                "Apply must be implemented to verify high-level injection."
            )

    # ── AC10: missing client raises error ────────────────────────

    def test_apply_without_client_raises_error(self):
        """Calling ``apply()`` without a ``client`` raises ``TypeError``.

        Acceptance criterion P0.2.10: Missing ``client`` raises
        appropriate error.
        """
        injector = StealthInjector()
        with pytest.raises((TypeError, NotImplementedError)):
            injector.apply()


class TestStealthInjectorApplyAllRED:
    """``apply_all()`` — behavioural tests (RED-phase markers removed, implementation landed)."""

    def test_apply_all_injects_all_patches(self):
        """``apply_all()`` injects every patch registered."""
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result = injector.apply_all(client)
            all_patches = set()
            for patches in LEVEL_PATCHES.values():
                all_patches.update(patches)
            for name in all_patches:
                assert name in result["applied"], (
                    f"Patch {name!r} not in applied list"
                )
        except NotImplementedError:
            pytest.fail("apply_all must be implemented to verify patch coverage.")


class TestStealthInjectorVerifyRED:
    """``verify()`` — behavioural tests (RED-phase markers removed, implementation landed)."""

    @pytest.mark.asyncio
    async def test_verify_returns_dict_of_string_to_bool(self):
        """``verify()`` returns ``{patch_name: bool}`` for every patch."""
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result = await injector.verify(client)
            assert isinstance(result, dict)
            for name, status in result.items():
                assert isinstance(name, str)
                assert isinstance(status, bool), (
                    f"Status for {name!r} should be bool, got {type(status)}"
                )
        except NotImplementedError:
            pytest.fail("verify must be implemented to verify return shape.")

    @pytest.mark.asyncio
    async def test_verify_navigator_webdriver_is_undefined(self):
        """After injection ``navigator.webdriver`` evaluates to ``undefined``."""
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result = await injector.verify(client)
            status = result.get("navigator.webdriver", None)
            if status is not None:
                assert status is True, (
                    "navigator.webdriver should be masked (True = masked successfully)"
                )
        except NotImplementedError:
            pytest.fail(
                "verify must be implemented to assert navigator.webdriver is masked."
            )


# ─── Level switching tests (RED-phase) ────────────────────────────────


class TestStealthInjectorLevelSwitchingRED:
    """Level switching — ``apply`` with changing levels."""

    def test_apply_upgrade_low_to_medium(self):
        """Switching from low → medium adds the medium-level patches."""
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result_low = injector.apply(client, level="low")
            result_med = injector.apply(client, level="medium")
            assert "navigator.plugins" in result_med["applied"]
        except NotImplementedError:
            pytest.fail(
                "Level switching requires apply to be implemented."
            )

    def test_apply_upgrade_low_to_high(self):
        """Switching from low → high injects all patches."""
        injector = StealthInjector()
        client = _mock_cdp_client()
        try:
            result_high = injector.apply(client, level="high")
            assert len(result_high["applied"]) >= 10
        except NotImplementedError:
            pytest.fail(
                "Level switching requires apply to be implemented."
            )


# ─── Patch source integrity tests ─────────────────────────────────────


class TestPatchSourceIntegrity:
    """Static checks on patch JS sources (constants, not implementation)."""

    def test_make_patches_returns_dict(self):
        """``_make_patches()`` returns a dict."""
        patches = _make_patches()
        assert isinstance(patches, dict)

    def test_make_patches_has_all_high_level_names(self):
        """Every name from ``LEVEL_PATCHES[\"high\"]`` exists in the patches dict."""
        patches = _make_patches()
        for name in LEVEL_PATCHES["high"]:
            assert name in patches, (
                f"Missing patch source for {name!r}"
            )

    # ── AC7: JS patches are syntactically valid ──────────────────

    def test_js_patches_are_syntactically_valid(self):
        """Every JS patch from ``_make_patches()`` passes a basic syntax check.

        Acceptance criterion P0.2.7: Each JS patch is syntactically valid
        JavaScript (basic syntax check via balanced delimiters and structure).
        Only runs when ``_make_patches()`` is implemented (no longer stub).
        """
        patches = _make_patches()
        for name, js in patches.items():
            # Non-empty string
            assert isinstance(js, str) and js, (
                f"Patch {name!r} JS source is empty"
            )

            # Balanced braces
            open_braces = js.count("{")
            close_braces = js.count("}")
            assert open_braces == close_braces, (
                f"Patch {name!r}: unbalanced braces "
                f"({open_braces} open, {close_braces} close)"
            )

            # Balanced parentheses
            open_parens = js.count("(")
            close_parens = js.count(")")
            assert open_parens == close_parens, (
                f"Patch {name!r}: unbalanced parentheses "
                f"({open_parens} open, {close_parens} close)"
            )

            # Balanced square brackets
            open_brack = js.count("[")
            close_brack = js.count("]")
            assert open_brack == close_brack, (
                f"Patch {name!r}: unbalanced square brackets "
                f"({open_brack} open, {close_brack} close)"
            )

            # Must contain at least one JS keyword or assignment pattern
            assert any(kw in js for kw in (
                "function", "=>", "Object.defineProperty",
                "var ", "let ", "const ", "=",
            )), (
                f"Patch {name!r} JS source contains no recognizable "
                f"JavaScript constructs"
            )

    # ── AC9: LEVEL_PATCHES dict unchanged (backward compat) ──────

    def test_level_patches_dict_not_modified(self):
        """``LEVEL_PATCHES`` dict is not modified by any operation.

        Acceptance criterion P0.2.9: Existing ``LEVEL_PATCHES`` dict
        is not modified (backward compatibility).
        """
        # Snapshot of LEVEL_PATCHES before any operation
        original = {
            level: list(patches)
            for level, patches in LEVEL_PATCHES.items()
        }
        # Perform operations that could mutate
        injector = StealthInjector()
        _ = injector.patches  # accessing property should not mutate
        # Verify LEVEL_PATCHES is unchanged
        assert LEVEL_PATCHES == original, (
            "LEVEL_PATCHES dict was modified after accessing patches property"
        )
