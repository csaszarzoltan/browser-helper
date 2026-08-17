"""P0-2: API key auth middleware — interface + behavioral tests.

Written by the pre-tester against analysis-brief.md spec P0-2 *before*
the developer implements the auth module.

Phase semantics
---------------
- **Interface tests** (class ``TestInterface``) verify that the auth
  module can be imported and its public API has the expected signatures.
  These will FAIL on import until ``src/mcp_server/auth.py`` exists.
- **Behavioral tests** (class ``TestBehavioral``) exercise roundtrip
  JWT generation/verification, tier enforcement, expiry, and the
  auth-disabled bypass. They fail cleanly while the module is missing.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Interface tests — FAIL until src/mcp_server/auth.py exists
# ---------------------------------------------------------------------------


class TestInterface:
    """Verify imports, classes, and function signatures of the auth module."""

    def test_import_auth_module(self):
        """src/mcp_server/auth.py must be importable."""
        import mcp_server.auth  # noqa: F401

    def test_auth_level_enum_exists(self):
        """AuthLevel enum must exist with ANONYMOUS, FREE, PREMIUM, ADMIN."""
        from mcp_server.auth import AuthLevel
        assert AuthLevel.ANONYMOUS.value == "anonymous"
        assert AuthLevel.FREE.value == "free"
        assert AuthLevel.PREMIUM.value == "premium"
        assert AuthLevel.ADMIN.value == "admin"

    def test_auth_context_dataclass_exists(self):
        """AuthContext must be a dataclass with level, key_id, metadata."""
        from dataclasses import is_dataclass

        from mcp_server.auth import AuthContext
        assert is_dataclass(AuthContext)

    def test_auth_context_fields(self):
        """AuthContext must have level, key_id, and metadata fields."""
        from dataclasses import fields

        from mcp_server.auth import AuthContext
        names = {f.name for f in fields(AuthContext)}
        assert "level" in names
        assert "key_id" in names
        assert "metadata" in names

    def test_verify_api_key_exists_and_callable(self):
        """verify_api_key must be a callable function."""
        from mcp_server.auth import verify_api_key
        assert callable(verify_api_key)

    def test_verify_api_key_signature(self):
        """verify_api_key(api_key: str, secret: str) -> AuthContext."""
        from mcp_server.auth import verify_api_key
        sig = inspect.signature(verify_api_key)
        params = list(sig.parameters.keys())
        assert "api_key" in params
        assert "secret" in params

    def test_generate_api_key_exists_and_callable(self):
        """generate_api_key must be a callable function."""
        from mcp_server.auth import generate_api_key
        assert callable(generate_api_key)

    def test_generate_api_key_signature(self):
        """generate_api_key must accept level, secret, key_id, expires_in_days."""
        from mcp_server.auth import generate_api_key
        sig = inspect.signature(generate_api_key)
        params = list(sig.parameters.keys())
        assert "level" in params
        assert "secret" in params
        assert "key_id" in params
        assert "expires_in_days" in params

    def test_require_auth_exists_and_callable(self):
        """require_auth must be a callable decorator factory."""
        from mcp_server.auth import require_auth
        assert callable(require_auth)

    def test_mcp_settings_has_auth_fields(self):
        """MCPSettings must have auth_secret and auth_enabled fields."""
        from dataclasses import fields

        from mcp_server.config import MCPSettings
        names = {f.name for f in fields(MCPSettings)}
        assert "auth_secret" in names
        assert "auth_enabled" in names


# ---------------------------------------------------------------------------
# Behavioral tests — FAIL cleanly while the module is missing
# ---------------------------------------------------------------------------


class TestBehavioral:
    """Exercise the auth module end-to-end.

    Tests import from ``mcp_server.auth`` inside the method body so that
    each test fails with a clear ImportError until the module exists.
    """

    TEST_SECRET = "test-hmac-secret-key-for-unit-tests"

    def test_generate_and_verify_roundtrip(self):
        """generate -> verify returns the same auth level."""
        from mcp_server.auth import (
            AuthLevel,
            generate_api_key,
            verify_api_key,
        )
        token = generate_api_key(
            level=AuthLevel.PREMIUM, secret=self.TEST_SECRET
        )
        ctx = verify_api_key(token, self.TEST_SECRET)
        assert ctx.level == AuthLevel.PREMIUM

    def test_expired_key_rejected(self):
        """An expired JWT must raise ValueError on verify."""
        from mcp_server.auth import (
            AuthLevel,
            generate_api_key,
            verify_api_key,
        )
        token = generate_api_key(
            level=AuthLevel.FREE,
            secret=self.TEST_SECRET,
            expires_in_days=-1,  # expired immediately
        )
        with pytest.raises(ValueError, match="expired|invalid"):
            verify_api_key(token, self.TEST_SECRET)

    def test_invalid_key_rejected(self):
        """A garbage string must raise ValueError on verify."""
        from mcp_server.auth import verify_api_key
        with pytest.raises(ValueError, match="invalid|malformed"):
            verify_api_key("not-a-jwt-token", self.TEST_SECRET)

    def test_free_key_cannot_access_premium(self):
        """require_auth(PREMIUM) must reject a FREE key."""
        from mcp_server.auth import (
            AuthLevel,
            generate_api_key,
            require_auth,
            verify_api_key,
        )
        token = generate_api_key(
            level=AuthLevel.FREE, secret=self.TEST_SECRET
        )
        ctx = verify_api_key(token, self.TEST_SECRET)
        guard = require_auth(min_level=AuthLevel.PREMIUM)
        with pytest.raises(PermissionError, match="insufficient|denied|premium"):
            guard(ctx)

    def test_premium_key_accesses_free_tools(self):
        """require_auth(FREE) must accept a PREMIUM key."""
        from mcp_server.auth import (
            AuthLevel,
            generate_api_key,
            require_auth,
            verify_api_key,
        )
        token = generate_api_key(
            level=AuthLevel.PREMIUM, secret=self.TEST_SECRET
        )
        ctx = verify_api_key(token, self.TEST_SECRET)
        guard = require_auth(min_level=AuthLevel.FREE)
        # Should NOT raise
        guard(ctx)

    def test_anonymous_accesses_free_tools(self):
        """An anonymous context (no key) must work when min_level=ANONYMOUS."""
        from mcp_server.auth import AuthContext, AuthLevel, require_auth
        ctx = AuthContext(level=AuthLevel.ANONYMOUS)
        guard = require_auth(min_level=AuthLevel.ANONYMOUS)
        guard(ctx)  # should not raise

    def test_auth_disabled_bypasses_check(self, monkeypatch):
        """BH_AUTH_DISABLED=1 must skip all auth checks."""
        from mcp_server.auth import AuthContext, AuthLevel, require_auth
        monkeypatch.setenv("BH_AUTH_DISABLED", "1")
        ctx = AuthContext(level=AuthLevel.ANONYMOUS)
        guard = require_auth(min_level=AuthLevel.PREMIUM)
        guard(ctx)  # should not raise when auth is disabled

    def test_key_id_in_context(self):
        """AuthContext.key_id must match the kid claim in the JWT."""
        from mcp_server.auth import (
            AuthLevel,
            generate_api_key,
            verify_api_key,
        )
        kid = "test-key-42"
        token = generate_api_key(
            level=AuthLevel.FREE,
            secret=self.TEST_SECRET,
            key_id=kid,
        )
        ctx = verify_api_key(token, self.TEST_SECRET)
        assert ctx.key_id == kid
