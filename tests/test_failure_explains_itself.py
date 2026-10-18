"""The 429 names who holds the sessions, and the access log names the error code.

Runtime log, 14 days to 2026-10-18: 33 x 429 on /session/new and 105 x 400 on
/agent/act, with no way to tell from the log or the body what held the slots.
"""

import json
import logging
import sys
from unittest.mock import MagicMock

sys.path.insert(0, "src")
sys.path.insert(0, ".")


def _registry_with(sessions):
    import session_registry as sr

    reg = sr.SessionRegistry(ttl=1800.0, max_sessions=30)
    for sid, idle, url in sessions:
        s = MagicMock()
        s.session_id = sid
        s.last_seen = sr.time.monotonic() - idle
        s.created = sr.time.monotonic() - idle - 5
        s.target_url = url
        reg._sessions[sid] = s
    return reg


def test_holders_cut_ids_strip_query_and_sort_idlest_first():
    reg = _registry_with([
        ("a" * 32, 10, "https://x.test/p?token=secret#frag"),
        ("b" * 32, 600, "about:blank"),
    ])
    rows = reg.holders()
    assert [r["session_id"] for r in rows] == ["bbbbbbbb", "aaaaaaaa"]
    assert rows[1]["url"] == "https://x.test/p"
    assert "secret" not in json.dumps(rows)
    assert rows[0]["idle_s"] >= 600


def test_api_error_sets_error_code_header():
    from main import api_error

    resp = api_error("session_new", "tab_budget_exhausted", "boom", 429)
    assert resp.headers["X-Error-Code"] == "tab_budget_exhausted"


def test_access_log_line_has_code_and_no_body(caplog):
    from fastapi.testclient import TestClient

    import main

    with caplog.at_level(logging.WARNING, logger="browser-helper"):
        r = TestClient(main.app).post("/agent/act", json={"action": "click", "target": {}})
    assert r.status_code >= 400
    lines = [m for m in caplog.messages if "/agent/act" in m and "->" in m]
    assert lines, caplog.messages
    assert f"-> {r.status_code}" in lines[0]
    assert "trace=" in lines[0]
    assert "click" not in lines[0]
