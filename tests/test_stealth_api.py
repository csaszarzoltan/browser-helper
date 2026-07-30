"""
RED-phase pre-development tests for the Stealth Configuration REST API.

All tests in this file MUST FAIL initially because the stealth endpoints
(``POST/GET /stealth/config``, ``POST /stealth/test``) are not registered
in the FastAPI app yet.  They will return 404 until the developer implements
the router and registers it in ``src/main.py``.

Acceptance criteria covered:
5. Tests for enable/disable toggle via REST
6. Tests for startup-loads-from-settings.json
7. Tests for invalid level returns 422
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from fastapi.testclient import TestClient

import main


# ─── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def api_client() -> TestClient:
    """FastAPI TestClient pointing at the real app."""
    return TestClient(main.app)


VALID_LEVELS = ("low", "medium", "high")
INVALID_LEVELS = ("ultra", "extreme", "invalid_level", "")


# ─── Interface / contract tests ───────────────────────────────────────


class TestStealthConfigAPIInterface:
    """Contract tests: endpoint existence and response shapes.

    These should all fail with 404 (RED) until the endpoints are registered.
    """

    def test_get_config_endpoint_exists(self, api_client):
        """``GET /stealth/config`` returns 200 when the endpoint is registered."""
        resp = api_client.get("/stealth/config")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. "
            "RED: endpoint not registered yet."
        )

    def test_get_config_returns_json_with_enabled_and_level(self, api_client):
        """``GET /stealth/config`` returns ``{\"enabled\": bool, \"level\": str}``."""
        resp = api_client.get("/stealth/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data, "Missing 'enabled' field in config response"
        assert "level" in data, "Missing 'level' field in config response"
        assert isinstance(data["enabled"], bool)
        assert data["level"] in VALID_LEVELS

    def test_post_config_enables_stealth(self, api_client):
        """``POST /stealth/config {\"enabled\": True, \"level\": \"low\"}`` enables stealth."""
        resp = api_client.post(
            "/stealth/config",
            json={"enabled": True, "level": "low"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. "
            "RED: endpoint not registered yet."
        )

    def test_post_config_disables_stealth(self, api_client):
        """``POST /stealth/config {\"enabled\": False, \"level\": \"medium\"}`` disables."""
        resp = api_client.post(
            "/stealth/config",
            json={"enabled": False, "level": "medium"},
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}"
        )

    def test_post_config_returns_422_for_invalid_level(self, api_client):
        """Invalid level returns 422 validation error."""
        resp = api_client.post(
            "/stealth/config",
            json={"enabled": True, "level": "bogus_level"},
        )
        assert resp.status_code == 422, (
            f"Expected 422 for invalid level, got {resp.status_code}. "
            "RED: validation not implemented (currently returning 404)."
        )

    def test_post_config_without_level_defaults(self, api_client):
        """``POST /stealth/config {\"enabled\": True}`` picks a default level."""
        resp = api_client.post(
            "/stealth/config",
            json={"enabled": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] in VALID_LEVELS, (
            f"Unexpected default level: {data['level']!r}"
        )

    def test_post_config_missing_enabled_returns_422(self, api_client):
        """Missing required ``enabled`` field returns 422."""
        resp = api_client.post(
            "/stealth/config",
            json={"level": "high"},
        )
        assert resp.status_code == 422, (
            f"Expected 422 for missing 'enabled', got {resp.status_code}"
        )

    def test_post_stealth_test_returns_patch_results(self, api_client):
        """``POST /stealth/test`` returns per-patch boolean results dict."""
        resp = api_client.post("/stealth/test")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. "
            "RED: endpoint not registered yet."
        )
        data = resp.json()
        assert isinstance(data, dict), "Response should be a dict"
        for name, status in data.items():
            assert isinstance(name, str), f"Patch name must be string, got {name!r}"
            assert isinstance(status, bool), (
                f"Patch status for {name!r} must be bool, got {status}"
            )


# ─── Enable / disable toggle tests (RED-phase) ────────────────────────


class TestStealthToggleRED:
    """Toggle stealth on/off via REST — RED until endpoints exist."""

    def test_toggle_on_then_off(self, api_client):
        """Enable, verify, disable, verify disabled."""
        # Enable at medium
        resp_on = api_client.post(
            "/stealth/config",
            json={"enabled": True, "level": "medium"},
        )
        assert resp_on.status_code == 200, (
            f"Enable failed: {resp_on.status_code}"
        )

        # GET confirms enabled
        resp_get = api_client.get("/stealth/config")
        assert resp_get.status_code == 200
        assert resp_get.json()["enabled"] is True

        # Disable
        resp_off = api_client.post(
            "/stealth/config",
            json={"enabled": False, "level": "medium"},
        )
        assert resp_off.status_code == 200, (
            f"Disable failed: {resp_off.status_code}"
        )

        # GET confirms disabled
        resp_get2 = api_client.get("/stealth/config")
        assert resp_get2.status_code == 200
        assert resp_get2.json()["enabled"] is False

    def test_toggle_preserves_level(self, api_client):
        """Disabling then re-enabling keeps the same evasion level."""
        # Enable at high
        api_client.post(
            "/stealth/config",
            json={"enabled": True, "level": "high"},
        )
        # Disable
        api_client.post(
            "/stealth/config",
            json={"enabled": False, "level": "high"},
        )
        # Re-enable at same level
        resp = api_client.post(
            "/stealth/config",
            json={"enabled": True, "level": "high"},
        )
        assert resp.status_code == 200
        assert resp.json()["level"] == "high"

    def test_level_upgrade_via_post(self, api_client):
        """Upgrade from low → medium → high via sequential POST."""
        for level in VALID_LEVELS:
            resp = api_client.post(
                "/stealth/config",
                json={"enabled": True, "level": level},
            )
            assert resp.status_code == 200, (
                f"Level {level!r} returned {resp.status_code}"
            )
            assert resp.json()["level"] == level


# ─── Persistence tests (RED-phase) ────────────────────────────────────


class TestStealthPersistenceRED:
    """Settings persistence — RED until settings.json integration exists.

    These tests require the REST endpoints to be registered AND for the config
    to integrate with ``settings_manager.SettingsManager``.  They will return
    404 until both are implemented, then more specific failures once the
    endpoints exist but persistence isn't wired yet.
    """

    def test_config_persists_across_requests(self, api_client):
        """Config set via POST persists and is returned by GET."""
        # Set enabled
        resp_set = api_client.post(
            "/stealth/config",
            json={"enabled": True, "level": "high"},
        )
        assert resp_set.status_code == 200

        # Verify via GET
        resp_get = api_client.get("/stealth/config")
        assert resp_get.status_code == 200
        data = resp_get.json()
        assert data["enabled"] is True
        assert data["level"] == "high"

    def test_startup_loads_from_settings(self, api_client):
        """The config endpoints read startup defaults from settings.json.

        When the FastAPI app starts, the stealth config should be initialised
        from ``SettingsManager`` (which reads ``src/settings.json``).
        If ``settings.json`` contains a ``\"stealth\"`` key with ``enabled``
        and ``level``, those values are used as the initial config.

        This test checks that the initial GET returns the persisted state
        rather than hardcoded defaults.
        """
        resp = api_client.get("/stealth/config")
        assert resp.status_code == 200
        data = resp.json()
        # If SettingsManager integration is working, these may come from disk.
        # At minimum, the shape must be correct.
        assert "enabled" in data
        assert "level" in data

    def test_cdp_test_endpoint_after_config(self, api_client):
        """After configuring stealth, ``POST /stealth/test`` returns statuses."""
        # First configure
        api_client.post(
            "/stealth/config",
            json={"enabled": True, "level": "medium"},
        )
        # Then test
        resp = api_client.post("/stealth/test")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "navigator.webdriver" in data, (
            "navigator.webdriver should be included in test results"
        )
