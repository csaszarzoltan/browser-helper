"""Fleet failover manager — save session state, re-allocate, restore.

``FailoverManager`` implements the node-failure path from
``analysis/architecture-brief.md`` §3.6.  When the health checker (or an
operator's ``POST /fleet/failover``) reports a dead node:

1. mark the node unhealthy so it leaves the scheduling pool;
2. for every active session on that node (or the one requested ``session_id``),
   snapshot its state — via the injected :class:`~session_manager.SessionManager`
   (the coordinator's ``_session_mgr`` singleton, ``capture()``/``restore()``)
   when available, else the persisted ``fleet_sessions.saved_state`` — and
   persist the snapshot into ``fleet_sessions.saved_state`` (JSON);
3. re-allocate the session on a healthy node through
   :class:`~fleet.session_pool.FleetSessionPool` (the dead node excluded, the
   coordinator-local fallback as last resort) and move the session row +
   capacity counters;
4. replay the saved state on the destination node via ``restore()``.

State transfer is best-effort by design (risk table §11: "Failover state
transfer fails → log error, mark session as failed"): if capture or restore
fails the session is still re-allocated and resumed without state — the
"retry on healthy node" guarantee must hold even when CDP is unreachable.
Every transfer returns a record the API layer can surface:

``{"session_id", "from_node_id", "to_node_id", "cdp_url", "status",
  "method": "save_restore", "state_transferred": bool}``
"""

from __future__ import annotations

import logging
from typing import Any

from fleet.session_pool import FleetSessionPool

logger = logging.getLogger("browser-helper.fleet.failover")

#: Session statuses that count as "active" for failover purposes.
_ACTIVE_STATUSES = ("active", "allocated", "idle")


class FailoverManager:
    """Re-allocate sessions away from a failed fleet node."""

    def __init__(
        self,
        pool: FleetSessionPool | None = None,
        db_path: str | None = None,
        session_manager: Any = None,
    ) -> None:
        """Wrap a session pool (or open one at ``db_path``) and a state manager.

        ``session_manager`` is the coordinator's existing
        :class:`~session_manager.SessionManager` singleton — the design's
        integration point so failover reuses ``capture``/``restore`` instead of
        re-instantiating CDP machinery.  ``None`` degrades to the persisted
        ``saved_state`` column only.
        """
        self.pool = pool or FleetSessionPool(db_path=db_path)
        self.session_manager = session_manager

    # -- public entry point -----------------------------------------------

    async def failover(
        self, node_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        """Fail over a node's sessions; returns a transfer report.

        ``session_id`` limits the operation to one session (the API's
        ``POST /fleet/failover`` accepts it); otherwise every active session
        hosted by ``node_id`` is transferred.  The report always carries
        ``transferred`` (list of transfer records) and ``failed`` (list of
        session ids whose re-allocation errored), plus a ``save_restore``
        marker the API contract asserts on.
        """
        await self.pool.registry.update_health(
            node_id,
            healthy=False,
            last_error="failover triggered",
        )

        if session_id is not None:
            target_ids = [session_id]
        else:
            sessions = await self.pool.registry.storage.sessions_on_node(
                node_id, status=None
            )
            target_ids = [
                s["session_id"]
                for s in sessions
                if s.get("status") in _ACTIVE_STATUSES
            ]

        transferred: list[dict[str, Any]] = []
        failed: list[str] = []
        for sid in target_ids:
            try:
                record = await self._transfer_session(sid, from_node_id=node_id)
            except Exception:
                logger.exception("failover failed for session %s", sid)
                failed.append(sid)
                continue
            if record.get("status") == "failed":
                failed.append(sid)
            else:
                transferred.append(record)

        return {
            "transferred": transferred,
            "failed": failed,
            "save_restore": True,
            "state_transferred": sum(
                1 for r in transferred if r.get("state_transferred")
            ),
        }

    # -- per-session transfer ---------------------------------------------

    async def _transfer_session(
        self, session_id: str, from_node_id: str
    ) -> dict[str, Any]:
        """Save → re-allocate → restore one session; return its record."""
        existing = await self.pool.registry.storage.get_session(session_id)
        from_url = existing["node_url"] if existing else ""

        # 1. Save state (best-effort).
        state = await self._save_state(session_id, from_url)

        # 2. Re-allocate on a healthy node (dead node excluded).  The pool's
        #    relocate mode moves the existing fleet_sessions row (or creates it
        #    when the original allocation never landed) and transfers the
        #    capacity counters atomically.
        result = await self.pool.allocate(
            session_id=session_id,
            node_id=None,
            exclude={from_node_id},
            local_fallback=True,
            relocate=True,
        )
        decision = result["decision"]
        if decision not in ("allocated", "local", "relocated"):
            logger.error(
                "failover re-allocation failed for %s (decision=%s)",
                session_id,
                decision,
            )
            return {
                "session_id": session_id,
                "from_node_id": from_node_id,
                "to_node_id": None,
                "status": "failed",
                "method": "save_restore",
                "state_transferred": state is not None,
            }

        session = result["session"]
        to_node_id = session["node_id"]
        to_url = session["node_url"]
        cdp_url = session.get("cdp_url")

        # 3. Restore state on the destination (best-effort).
        restored = await self._restore_state(session_id, state)

        return {
            "session_id": session_id,
            "from_node_id": from_node_id,
            "to_node_id": to_node_id,
            "node_url": to_url,
            "cdp_url": cdp_url,
            "status": "active",
            "method": "save_restore",
            "state_transferred": restored,
        }

    # -- state save / restore ---------------------------------------------

    async def _save_state(
        self, session_id: str, url: str
    ) -> dict[str, Any] | None:
        """Capture session state and persist it into ``saved_state``.

        Prefers the injected :class:`SessionManager` (``capture``); falls back
        to any previously persisted ``saved_state``.  Returns the state dict,
        or None when nothing could be captured (session had no state).
        """
        state: dict[str, Any] | None = None
        if self.session_manager is not None:
            try:
                captured = await self.session_manager.capture(
                    cdp_client=None, session_id=session_id, url=url
                )
                state = _state_to_dict(captured)
            except Exception as exc:  # noqa: BLE001 — capture is best-effort
                logger.warning("state capture failed for %s: %s", session_id, exc)
        if state is None:
            row = await self.pool.registry.storage.get_session(session_id)
            if row and row.get("saved_state"):
                state = row["saved_state"]
        if state is not None:
            await self.pool.registry.storage.save_session_state(session_id, state)
        return state

    async def _restore_state(
        self, session_id: str, state: dict[str, Any] | None
    ) -> bool:
        """Replay captured state on the destination node; True when applied."""
        if state is None or self.session_manager is None:
            return state is not None
        try:
            from session_manager import SessionState

            restored = await self.session_manager.restore(
                cdp_client=None,
                state=_state_to_session_state(state, SessionState),
            )
            return bool(restored)
        except Exception as exc:  # noqa: BLE001 — restore is best-effort
            logger.warning("state restore failed for %s: %s", session_id, exc)
            return False


def _state_to_dict(state: Any) -> dict[str, Any] | None:
    """Convert a SessionManager state object into a JSON-serialisable dict."""
    if state is None:
        return None
    if isinstance(state, dict):
        return state
    attrs = (
        "session_id",
        "cookies",
        "local_storage",
        "session_storage",
        "url",
        "created_at",
        "last_active",
    )
    data = {name: getattr(state, name, None) for name in attrs}
    return {k: v for k, v in data.items() if v is not None}


def _state_to_session_state(state: dict[str, Any], cls: type) -> Any:
    """Rebuild a SessionManager state object from a plain dict."""
    kwargs = {
        name: state.get(name)
        for name in (
            "session_id",
            "cookies",
            "local_storage",
            "session_storage",
            "url",
            "created_at",
            "last_active",
        )
    }
    kwargs["session_id"] = kwargs.get("session_id") or state.get("id") or "unknown"
    kwargs.setdefault("cookies", [])
    kwargs.setdefault("local_storage", {})
    kwargs.setdefault("session_storage", {})
    kwargs.setdefault("url", "about:blank")
    kwargs.setdefault("created_at", 0.0)
    kwargs.setdefault("last_active", 0.0)
    return cls(**kwargs)
