"""Cookie export service — retrieves a session's cookies via CDP.

Exposes one async function, :func:`export_cookies`, that resolves a session
from the :class:`session_registry.SessionRegistry` and pulls its cookie jar
through the session's own CDP connection (``Network.getAllCookies``).

The returned payload is deliberately flat and JSON-safe: every cookie is
mapped to the stable keys ``name``, ``value``, ``domain``, ``path``,
``expires``, ``httpOnly``, ``secure``, ``sameSite`` so downstream consumers
(REST clients, MCP tool callers) never see CDP's raw ``Network.Cookie``
shape.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("browser-helper.cookie_service")


def _normalise_cookie(raw: dict) -> dict:
    """Map one CDP ``Network.Cookie`` dict onto the stable export shape."""
    return {
        "name": raw.get("name", ""),
        "value": raw.get("value", ""),
        "domain": raw.get("domain", ""),
        "path": raw.get("path", "/"),
        "expires": raw.get("expires", -1),
        "httpOnly": bool(raw.get("httpOnly", False)),
        "secure": bool(raw.get("secure", False)),
        "sameSite": raw.get("sameSite", ""),
    }


class SessionNotFoundError(LookupError):
    """Raised when the requested session id does not exist in the registry."""


async def export_cookies(session_id: str) -> dict:
    """Export every cookie for *session_id* as ``{"cookies": [...]}``.

    Resolves the session through the shared registry and asks its own CDP
    client for the full cookie jar. Raises :class:`SessionNotFoundError`
    when no such session exists; CDP/connection failures propagate to the
    caller (the REST layer maps them to an error response).
    """
    from main import session_registry  # lazy import — avoids engine import at module load

    sess = session_registry.get(session_id)
    if sess is None:
        raise SessionNotFoundError(f"Session {session_id} not found")

    raw = await sess.client.get_cookies()
    cookies = raw.get("cookies", []) if isinstance(raw, dict) else []
    return {"cookies": [_normalise_cookie(c) for c in cookies]}
