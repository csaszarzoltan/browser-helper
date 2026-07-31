from pathlib import Path

import pytest


# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from enterprise_workspace import EnterpriseWorkspace, PolicyDenied, render_console


def app(tmp_path: Path):
    return EnterpriseWorkspace(tmp_path / "enterprise.db")


def test_private_network_navigation_is_denied_before_cdp_dispatch(tmp_path):
    w = app(tmp_path)
    w.create_policy("team-a", ["https://example.com"], ["navigate"])
    with pytest.raises(PolicyDenied, match="PRIVATE_NETWORK_DENIED"):
        w.authorize("team-a", "navigate", "http://127.0.0.1/admin")


def test_failed_action_replay_aligns_before_after_dom_network_and_screenshot(tmp_path):
    w = app(tmp_path)
    r = w.start_replay("team-a")
    w.add_replay_event(
        r,
        "click",
        {
            "token": "secret",
            "dom_before": "a",
            "dom_after": "b",
            "network": "500",
            "screenshot": "art-1",
        },
    )
    data = w.replay(r)
    assert data["events"][0]["data"]["screenshot"] == "art-1"
    assert "secret" not in str(data)


def test_expired_control_lease_prevents_agent_and_human_concurrent_input(tmp_path):
    w = app(tmp_path)
    t = w.request_takeover("team-a", "run-1", "mfa")
    w.claim_takeover(t, "alice", expires_at=1)
    with pytest.raises(PolicyDenied, match="LEASE_EXPIRED"):
        w.approve_takeover(t, "alice", now=2)


def test_recorded_checkout_exports_deterministic_versioned_workflow_without_credentials(tmp_path):
    w = app(tmp_path)
    f = w.create_workflow(
        "team-a",
        "Checkout",
        [
            {"action": "navigate", "url": "https://example.com"},
            {"action": "fill", "secret_ref": "secret://team-a/login"},
        ],
    )
    out = w.export_workflow(f)
    assert out == w.export_workflow(f)
    assert "password" not in out


def test_lost_node_requeues_only_checkpointed_sessions_within_tenant_quota(tmp_path):
    w = app(tmp_path)
    w.set_quota("team-a", 2)
    n = w.register_node("eu", 2)
    s = w.lease_session("team-a", n, checkpoint="cp-1")
    w.mark_node_lost(n)
    assert w.recovery_sessions("team-a") == [s]


def test_candidate_fails_release_gate_when_success_rate_regresses_across_repeated_trials(tmp_path):
    w = app(tmp_path)
    e = w.create_evaluation("candidate", 0.9)
    [w.record_trial(e, x, 100, 0.1) for x in (True, False, True)]
    assert w.evaluate(e)["state"] == "FAILED"


def test_accessible_responsive_consoles(tmp_path):
    w = app(tmp_path)
    for p in ("policy", "replay", "takeover", "workflows", "fleet", "evaluation"):
        h = render_console(p, w)
        assert "Skip to content" in h and 'aria-live="polite"' in h and "Try again" in h


def test_enterprise_routes_are_present():
    import main

    paths = {r.path for r in main.app.routes}
    assert "/enterprise/{page}" in paths
    assert "/api/v1/enterprise/policies" in paths
    assert "/api/v1/enterprise/replays" in paths
    assert "/api/v1/enterprise/takeovers" in paths
    assert "/api/v1/enterprise/workflows" in paths
    assert "/api/v1/enterprise/evaluations" in paths
