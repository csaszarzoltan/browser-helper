"""Acceptance contracts for the accessible visual workflow builder."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_builder_has_accessible_visual_and_json_modes():
    assert 'id="workflow-editor-mode"' in HTML
    assert 'aria-label="Workflow editor mode"' in HTML
    assert 'id="workflow-visual-builder"' in HTML
    assert 'id="workflow-step-list"' in HTML
    assert 'id="workflow-add-step"' in HTML
    assert 'id="workflow-sync-json"' in HTML
    assert 'aria-live="polite"' in HTML


def test_builder_supports_repeated_daily_actions_and_schema_fields():
    for action in ("navigate", "click", "type", "wait_for_element", "screenshot", "analyze_page", "get_text"):
        assert f"{action}:" in JS
    for field in ("url", "selector", "text", "timeout"):
        assert f"name: '{field}'" in JS
    assert "WORKFLOW_STEP_DEFINITIONS" in JS


def test_builder_can_add_duplicate_reorder_remove_and_sync_steps():
    for behavior in (
        "addVisualWorkflowStep",
        "duplicateVisualWorkflowStep",
        "moveVisualWorkflowStep",
        "removeVisualWorkflowStep",
        "syncVisualBuilderToJson",
        "syncJsonToVisualBuilder",
    ):
        assert behavior in JS
    assert "workflow_builder_step_added" in JS
    assert "workflow_builder_synced" in JS


def test_builder_preserves_validation_and_safe_review_before_run():
    assert "validateWorkflowSteps" in JS
    assert "Review the generated JSON before running" in JS
    assert "does not run automatically" in HTML
    assert "data-requires-connection" in HTML


def test_builder_is_responsive_and_has_focus_visible_states():
    assert ".workflow-builder" in CSS
    assert ".workflow-step-card" in CSS
    assert ".workflow-step-card:focus-within" in CSS
    assert "@media (max-width: 700px)" in CSS


def test_documentation_mentions_visual_builder():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "visual-workflow-builder.md").read_text(encoding="utf-8")
    assert "Visual workflow builder" in readme
    assert "JSON remains available" in docs
    assert "does not execute" in docs
