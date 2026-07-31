import base64
from unittest.mock import AsyncMock

import pytest

# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from fastapi.testclient import TestClient

import main
from agent_runtime import SnapshotStore, StaleSnapshotError, diff_snapshots, paginate_snapshot
from artifact_store import ArtifactStore
from headless_manager import HeadlessManager, SessionHandle


def sample_page(text="A" * 1000, extra=False):
    buttons = [{"text": "Save", "selector": "#save"}]
    if extra:
        buttons.append({"text": "Cancel", "selector": "#cancel"})
    return {"page": {"url": "https://example.test", "title": "Demo", "text_preview": text, "buttons": buttons,
                     "form_fields": [{"label": "Email", "selector": "#email", "type": "email"}]}}


def test_snapshot_stable_refs_and_pagination():
    store = SnapshotStore()
    snap = store.add(sample_page())
    assert snap.snapshot_id.startswith("snap_")
    assert snap.elements[0]["element_id"] == "e1"
    assert store.resolve(snap.snapshot_id, "e1")["name"] == "Save"
    page1 = paginate_snapshot(snap, 256, 1)
    assert page1["truncated"] is True
    page2 = paginate_snapshot(snap, 256, 1, page1["next_cursor"])
    assert page2["text"] != page1["text"] or len(page2["text"]) == 256


def test_snapshot_diff():
    store = SnapshotStore()
    old = store.add(sample_page("old"))
    new = store.add(sample_page("new", extra=True))
    diff = diff_snapshots(old, new)
    assert diff["changed"] is True
    assert diff["text_changed"] is True
    assert any(x["name"] == "Cancel" for x in diff["elements_added"])


def test_expired_snapshot():
    store = SnapshotStore(ttl_seconds=-1)
    snap = store.add(sample_page())
    with pytest.raises(StaleSnapshotError):
        store.get(snap.snapshot_id)


def test_artifact_store_round_trip(tmp_path):
    store = ArtifactStore(str(tmp_path), ttl_seconds=10)
    record = store.put(b"jpeg-data", "image/jpeg", ".jpg", {"width": 10})
    path, loaded = store.get(record["artifact_id"])
    assert path.read_bytes() == b"jpeg-data"
    assert loaded["sha256"] == record["sha256"]
    assert loaded["metadata"]["width"] == 10


@pytest.mark.asyncio
async def test_headless_evaluate_real_cdp_result(monkeypatch):
    mgr = HeadlessManager(chrome_path="chrome")
    handle = SessionHandle("s1", 1, "http://127.0.0.1:1", 1, 0, 0, "active")
    mgr.pool.add(handle)
    mgr._cdp_command = AsyncMock(return_value={"result": {"type": "number", "value": 4}})
    result = await mgr.evaluate("s1", "2+2")
    assert result["status"] == "ok"
    assert result["value"] == 4
    mgr._cdp_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_headless_screenshot_creates_artifact(tmp_path):
    mgr = HeadlessManager(chrome_path="chrome")
    mgr.artifacts = ArtifactStore(str(tmp_path))
    handle = SessionHandle("s1", 1, "http://127.0.0.1:1", 1, 0, 0, "active")
    mgr.pool.add(handle)
    mgr._cdp_command = AsyncMock(return_value={"data": base64.b64encode(b"image").decode()})
    result = await mgr.screenshot("s1")
    assert result["status"] == "ok"
    assert result["artifact"]["mime_type"] == "image/jpeg"
    assert mgr.artifacts.get(result["artifact"]["artifact_id"])[0].read_bytes() == b"image"


def client_with_connected_state(monkeypatch):
    monkeypatch.setattr(main.client, "_connected", True, raising=False)
    monkeypatch.setattr(type(main.client), "is_connected", property(lambda self: True))
    return TestClient(main.app)


def test_capabilities_endpoint(monkeypatch):
    client = client_with_connected_state(monkeypatch)
    response = client.get("/agent/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["observation"]["stable_element_refs"] is True


def test_agent_observe_and_diff(monkeypatch):
    client = client_with_connected_state(monkeypatch)
    main.client.analyze_page_condensed = AsyncMock(side_effect=[sample_page("one"), sample_page("two", extra=True)])
    first = client.post("/agent/observe", json={"max_chars": 256, "max_elements": 1}).json()["data"]
    second_response = client.post("/agent/observe", json={"since_snapshot_id": first["snapshot_id"]})
    assert second_response.status_code == 200
    assert second_response.json()["data"]["diff"]["changed"] is True


def test_agent_invalid_action_is_422(monkeypatch):
    client = client_with_connected_state(monkeypatch)
    response = client.post("/agent/act", json={"action": "does-not-exist", "observe_after": False})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_action"


def test_headless_missing_session_is_not_http_200(monkeypatch):
    client = client_with_connected_state(monkeypatch)
    response = client.post("/headless/eval", json={"session_id": "missing", "expression": "1"})
    assert response.status_code == 404
    assert response.json()["status"] == "error"
