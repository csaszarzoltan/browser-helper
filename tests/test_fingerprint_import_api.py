"""POST /api/v1/fingerprints/import reads the file the caller names.

The import test used to read ``/tmp/test.json``, a file no test creates, so it passed only on
machines where something else had left that file behind. These tests write their own files.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_import_adds_the_template_from_the_file(client, tmp_path):
    path = tmp_path / "chrome-win.json"
    path.write_text(json.dumps({"name": "chrome-win", "browser": "chrome", "signals": {}, "config": {}}))

    resp = await client.post("/api/v1/fingerprints/import", json={"path": str(path)})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "name": "chrome-win"}


@pytest.mark.asyncio
async def test_import_of_a_missing_file_is_404(client, tmp_path):
    resp = await client.post("/api/v1/fingerprints/import", json={"path": str(tmp_path / "nope.json")})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_of_invalid_json_is_a_client_error_not_a_crash(client, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json")

    resp = await client.post("/api/v1/fingerprints/import", json={"path": str(path)})

    assert resp.status_code == 422
    body = resp.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "invalid_request"
    assert "Invalid JSON" in body["error"]["message"]


@pytest.mark.asyncio
async def test_import_of_a_json_list_is_a_client_error_not_a_crash(client, tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]")

    resp = await client.post("/api/v1/fingerprints/import", json={"path": str(path)})

    assert resp.status_code == 422
