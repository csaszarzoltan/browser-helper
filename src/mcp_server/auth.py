"""MCP server auth — JWT-based API key verification + tier enforcement.

Supports BH_AUTH_DISABLED=1 bypass for development.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from enum import StrEnum
from typing import Any

import jwt


class AuthLevel(StrEnum):
    """Access tiers for API key authentication."""

    ANONYMOUS = "anonymous"
    FREE = "free"
    PREMIUM = "premium"
    ADMIN = "admin"


# Tier hierarchy — higher index = more access
_TIER_ORDER: dict[AuthLevel, int] = {
    AuthLevel.ANONYMOUS: 0,
    AuthLevel.FREE: 1,
    AuthLevel.PREMIUM: 2,
    AuthLevel.ADMIN: 3,
}


@dataclass(frozen=True)
class AuthContext:
    """Result of successful API key verification."""

    level: AuthLevel
    key_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def generate_api_key(
    level: AuthLevel,
    secret: str,
    key_id: str = "",
    expires_in_days: int = 365,
) -> str:
    """Generate a JWT API key for the given auth level.

    Args:
        level: The access tier this key grants.
        secret: HMAC signing secret.
        key_id: Optional key identifier (kid claim).
        expires_in_days: Expiry in days from now. Use -1 for immediate expiry.

    Returns:
        A signed JWT string.
    """
    from datetime import datetime, timedelta

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "level": level.value,
        "iat": now,
        "exp": now + timedelta(days=expires_in_days),
    }
    if key_id:
        payload["kid"] = key_id
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_api_key(api_key: str, secret: str) -> AuthContext:
    """Verify a JWT API key and return an AuthContext.

    Raises:
        ValueError: If the token is expired, malformed, or invalid.
    """
    try:
        payload = jwt.decode(api_key, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("invalid") from exc

    level_str = payload.get("level", "anonymous")
    try:
        level = AuthLevel(level_str)
    except ValueError:
        level = AuthLevel.ANONYMOUS

    return AuthContext(
        level=level,
        key_id=payload.get("kid", ""),
        metadata={k: v for k, v in payload.items() if k not in ("level", "kid", "iat", "exp")},
    )


def require_auth(min_level: AuthLevel = AuthLevel.FREE) -> Callable[[AuthContext], None]:
    """Return a guard that raises PermissionError if context.level < min_level.

    When BH_AUTH_DISABLED=1 is set in the environment, all checks are bypassed.
    """

    def _guard(ctx: AuthContext) -> None:
        if os.environ.get("BH_AUTH_DISABLED", "") == "1":
            return
        if _TIER_ORDER.get(ctx.level, 0) < _TIER_ORDER.get(min_level, 0):
            raise PermissionError(
                f"insufficient access: {ctx.level.value} < {min_level.value}"
            )

    return _guard
