"""Feedback from a peer agent session: dialog scope, verification evidence, screenshots as files, tidy."""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _ax(*nodes):
    return {"nodes": [dict(n) for n in nodes]}


def _node(node_id, role, name="", children=(), backend=None):
    return {"nodeId": node_id, "role": {"value": role}, "name": {"value": name},
            "childIds": list(children), "backendDOMNodeId": backend or int(node_id) + 100}


def _page():
    return _ax(
        _node("1", "main", "Page", ["2", "3"]),
        _node("2", "button", "Edit availability", backend=7),
        _node("3", "dialog", "Availability", ["4", "5"], backend=9),
        _node("4", "statictext", "Set your hours"),
        _node("5", "button", "Save"),
    )


def _build(raw, scope="page"):
    from agent_navigation import AccessibilityTreeBuilder

    return AccessibilityTreeBuilder().build(raw, page={"url": "https://a.test/", "title": "t"}, scope=scope)


def test_dialog_scope_returns_only_the_dialog_subtree():
    snap = _build(_page(), "dialog")
    assert [n.name for n in snap.nodes] == ["Availability", "Set your hours", "Save"]


def test_dialog_scope_without_a_dialog_is_empty_not_the_whole_page():
    raw = _ax(_node("1", "main", "Page", ["2"]), _node("2", "button", "Edit"))
    assert _build(raw, "dialog").nodes == []


def test_a_dialog_that_was_already_open_does_not_satisfy_dialog_opened():
    from agent_navigation import validate_expectations

    before, after = _build(_page()), _build(_page())
    assert not validate_expectations(before, after, {"dialog_opened": True})["satisfied"]
    no_dialog = _build(_ax(_node("1", "main", "Page", ["2"]), _node("2", "button", "Edit")))
    assert validate_expectations(no_dialog, after, {"dialog_opened": True})["satisfied"]
    other = _page()
    other["nodes"][2]["name"]["value"] = "Different"
    other["nodes"][2]["backendDOMNodeId"] = 11
    assert validate_expectations(before, _build(other), {"dialog_opened": True})["satisfied"]


def test_failed_verification_evidence_shows_dialog_text_and_target_state():
    from agent_navigation import verification_evidence

    ev = verification_evidence(_build(_page()), _build(_page()), target_backend_id=7)
    assert ev["page_changed"] is False
    assert ev["dialogs_after"][0]["name"] == "Availability"
    assert "statictext: Set your hours" in ev["dialogs_after"][0]["contents"]
    assert ev["target"]["name"] == "Edit availability"
    gone = verification_evidence(_build(_page()), _build(_page()), target_backend_id=12345)
    assert gone["target"] == {"present": False}


def test_evidence_stays_small():
    from agent_navigation import verification_evidence

    kids = [str(i) for i in range(10, 200)]
    raw = _ax(_node("1", "dialog", "Big", kids),
              *[_node(k, "statictext", "long text " * 20) for k in kids])
    ev = verification_evidence(_build(raw), _build(raw), max_chars=1500)
    assert len(json.dumps(ev)) <= 1500 and ev["dialogs_after"][0]["truncated"] is True


def test_cap_node_text_drops_trailing_nodes_and_says_so():
    from mcp_server.tools import _cap_node_text

    data = {"nodes": [{"name": "a" * 300}, {"name": "b" * 100}, {"name": "c" * 100}], "omitted_nodes": 0}
    _cap_node_text(data, 250)
    assert data["truncated"] is True and data["omitted_nodes"] == 2 and len(data["nodes"]) == 1
    assert len(data["nodes"][0]["name"]) == 201


def test_screenshot_is_saved_to_a_file_and_base64_is_left_out(tmp_path, monkeypatch):
    import base64

    import main
    from artifact_store import ArtifactStore
    from mcp_server.tools import _screenshot_to_file

    monkeypatch.setattr(main, "artifact_store", ArtifactStore(str(tmp_path)))
    shot = {"status": "ok", "data": base64.b64encode(b"\xff\xd8jpegbytes").decode(), "format": "jpeg"}
    out = _screenshot_to_file(shot)
    assert "data" not in out and Path(out["path"]).read_bytes() == b"\xff\xd8jpegbytes"
    assert "data" in _screenshot_to_file(shot, inline=True)


class _Mgr:
    def __init__(self):
        self.removed = False

    def list_sessions(self):
        return [{"session_id": "old", "expired": True}, {"session_id": "live", "expired": False}]

    def remove_expired(self):
        self.removed = True
        return ["old"]


class _Tabs:
    def __init__(self):
        self.closed = []

    async def get_tabs(self):
        return [
            {"id": "own", "title": "", "url": "about:blank", "active": False},
            {"id": "blank1", "title": "about:blank", "url": "about:blank", "active": False},
            {"id": "active", "title": "", "url": "about:blank", "active": True},
            {"id": "page", "title": "Local", "url": "http://127.0.0.1:8080/", "active": False},
        ]

    async def close_tab(self, tab_id):
        self.closed.append(tab_id)


def test_tidy_previews_by_default_and_only_closes_stray_blank_tabs(monkeypatch):
    import main
    from mcp_server import tools

    mgr, tabs = _Mgr(), _Tabs()
    monkeypatch.setattr(main, "_session_mgr", mgr)

    async def fake_target():
        return tabs, None

    class _Own:
        tab_id = "own"

    monkeypatch.setattr(tools, "_target", fake_target)
    monkeypatch.setitem(tools._MCP_SESSION, "session", _Own())
    preview = asyncio.run(tools._tidy({"sessions", "tabs"}, apply=False))
    assert preview["tabs"] == {"blank": ["blank1"], "closed": []} and tabs.closed == [] and not mgr.removed
    done = asyncio.run(tools._tidy({"sessions", "tabs"}, apply=True))
    assert done["tabs"]["closed"] == ["blank1"] and tabs.closed == ["blank1"]
    assert done["sessions"] == {"expired": ["old"], "removed": ["old"]} and mgr.removed
