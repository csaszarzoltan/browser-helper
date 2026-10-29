"""MCP ``act`` can leave out the observation the REST engine attaches after an action.

The REST ``/agent/act`` defaults to ``observe_after=True`` and attaches a bounded page
snapshot to every reply. The MCP tool had no way to ask for less, so each action
cost the snapshot's tokens even when the agent only needed the verdict.
"""

import asyncio
import json

from mcp_server import tools


def _run_act_with_fake_engine(monkeypatch, **kwargs):
    """Call the MCP act tool and return (reply, the AgentActionRequest the engine received)."""
    import main

    seen = {}

    async def fake_session():
        return object(), None

    async def fake_agent_act(request, model):
        seen["model"] = model
        return {"status": "ok", "operation": "agent_act", "data": {"ok": True}, "error": None, "meta": {}}

    monkeypatch.setattr(tools, "_mcp_session", fake_session)
    monkeypatch.setattr(main, "agent_act", fake_agent_act)
    monkeypatch.setattr(main, "_set_current_session", lambda _sess: None)
    reply = json.loads(asyncio.run(tools.act(action="click", selector="#save", **kwargs)))
    return reply, seen["model"]


def test_act_passes_include_observation_false_to_the_engine(monkeypatch):
    reply, model = _run_act_with_fake_engine(monkeypatch, include_observation=False)

    assert reply["status"] == "ok"
    assert model.include_observation is False


def test_act_without_the_flag_keeps_the_engine_default(monkeypatch):
    _reply, model = _run_act_with_fake_engine(monkeypatch)

    assert model.include_observation is None
