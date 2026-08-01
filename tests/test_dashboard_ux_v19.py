"""Acceptance and contract tests for the v1.9 day-to-day dashboard UX."""
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from main import app

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = ROOT / "static" / "dashboard_ux.css"
JS = ROOT / "static" / "dashboard_ux.js"


def test_dashboard_has_skip_link_landmarks_and_live_region():
    assert 'class="skip-link"' in HTML
    assert 'aria-label="Primary workspace navigation"' in HTML
    assert '<main id="workspace-main"' in HTML
    assert 'id="a11y-announcer"' in HTML
    assert 'aria-live="polite"' in HTML


def test_dashboard_exposes_task_based_workspaces_and_context():
    for workspace in ("overview", "browser", "automation", "diagnostics", "agent"):
        assert f'data-workspace="{workspace}"' in HTML
    assert 'id="workspace-nav"' in HTML
    assert 'id="active-context"' in HTML
    assert 'id="context-connection"' in HTML
    assert 'id="context-tab"' in HTML


def test_dashboard_has_command_palette_and_shortcut_help():
    assert 'id="command-palette"' in HTML
    assert 'id="command-search"' in HTML
    assert 'aria-modal="true"' in HTML
    assert 'Ctrl+K' in HTML


def test_dashboard_loads_local_ux_assets_without_cdn_dependency():
    assert '/static/dashboard_ux.css' in HTML
    assert '/static/dashboard_ux.js' in HTML
    assert CSS.exists()
    assert JS.exists()


def test_ux_script_persists_workspace_and_protects_dangerous_actions():
    source = JS.read_text(encoding="utf-8")
    assert 'browser-helper.workspace' in source
    assert 'localStorage.setItem' in source
    assert 'data-confirm' in source
    assert 'window.confirm' in source
    assert "document.addEventListener('keydown'" in source


def test_ux_script_has_connection_aware_controls_and_telemetry_hook():
    source = JS.read_text(encoding="utf-8")
    assert 'data-requires-connection' in source
    assert 'browser-helper:telemetry' in source
    assert 'setConnectedState' in source


@pytest.mark.asyncio
async def test_dashboard_and_ux_assets_are_served():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        dashboard = await client.get("/")
        css = await client.get("/static/dashboard_ux.css")
        js = await client.get("/static/dashboard_ux.js")
    assert dashboard.status_code == 200
    assert css.status_code == 200
    assert js.status_code == 200
    assert "Primary workspace navigation" in dashboard.text
    assert "browser-helper.workspace" in js.text
