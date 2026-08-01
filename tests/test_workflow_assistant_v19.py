"""TDD acceptance tests for the reusable workflow assistant."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard_ux.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "dashboard_ux.css").read_text(encoding="utf-8")


def test_script_runner_has_assistant_controls_and_status():
    for element_id in (
        "workflow-template", "workflow-apply-template", "workflow-validate",
        "workflow-format", "workflow-save-draft", "workflow-clear-draft",
        "workflow-validation-status",
    ):
        assert f'id="{element_id}"' in HTML


def test_assistant_has_safe_builtin_templates():
    assert "WORKFLOW_TEMPLATES" in JS
    assert "Navigate and capture" in JS
    assert "Observe page" in JS
    assert "Form workflow starter" in JS
    assert "eval" not in JS.split("const WORKFLOW_TEMPLATES", 1)[1].split("};", 1)[0]


def test_workflow_validation_checks_shape_supported_actions_and_required_fields():
    assert "validateWorkflowSteps" in JS
    assert "SUPPORTED_WORKFLOW_ACTIONS" in JS
    assert "must be a non-empty JSON array" in JS
    assert "requires a URL" in JS
    assert "requires a selector" in JS


def test_draft_storage_is_explicit_bounded_and_private():
    assert "browser-helper.workflow-draft" in JS
    assert "MAX_DRAFT_BYTES" in JS
    assert "saveWorkflowDraft" in JS
    assert "clearWorkflowDraft" in JS
    assert "Drafts may contain sensitive data" in HTML
    assert "localStorage.setItem(WORKFLOW_DRAFT_KEY" in JS


def test_run_script_uses_shared_validation_before_execution():
    inline_start = HTML.index("async function runScript()")
    inline_end = HTML.index("//  SESSION MANAGER", inline_start)
    run_script_source = HTML[inline_start:inline_end]
    assert "window.BrowserHelperWorkflow.validate" in run_script_source
    assert "window.BrowserHelperWorkflow.setBusy" in run_script_source


def test_assistant_has_accessible_validation_states():
    assert 'role="status"' in HTML
    assert 'aria-live="polite"' in HTML
    assert '.workflow-validation.success' in CSS
    assert '.workflow-validation.error' in CSS
