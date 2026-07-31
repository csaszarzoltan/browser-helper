"""
Pre-development tests for FingerprintDatabase (RED phase — P0.1).

╔══════════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                               ║
║                                                                        ║
║  Interface tests (green checkmark) → assert pass immediately with stub  ║
║  Behavioral tests (red X)          → assert fail until implementation   ║
║                                                                        ║
║  Class under test: FingerprintDatabase                                  ║
║  Dataclass:         FingerprintTemplate                                  ║
║                                                                        ║
║  Acceptance Criteria (from analysis brief Section 7, P0.1):             ║
║    1. DEFAULT_TEMPLATES contains 4 templates                            ║
║    2. list_templates() returns names for all default templates          ║
║    3. get_template("chrome-120") returns complete template              ║
║    4. get_template("nonexistent") returns None                          ║
║    5. add_template(template) persists and appears in list               ║
║    6. update_template(name, updates) modifies fields                    ║
║    7. delete_template(name) removes template                            ║
║    8. generate_template("chrome") creates plausible random template     ║
║    9. generate_template("firefox") creates plausible random template    ║
║   10. Templates persist to disk and survive re-init                     ║
║   11. export_template(name, path) writes valid JSON                     ║
║   12. import_template(path) reads JSON and loads into DB                ║
║   13. Empty storage dir → database initializes with defaults            ║
║   14. Corrupted JSON file → database initializes with defaults          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from typing import get_type_hints

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from anti_detection.fingerprint_database import (
    DEFAULT_TEMPLATES,
    FingerprintDatabase,
    FingerprintTemplate,
)

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Interface Tests (PASSING — green checkmark)
# ═══════════════════════════════════════════════════════════════════════════


class TestFingerprintTemplateInterface:
    """FingerprintTemplate dataclass contract tests."""

    def test_class_exists(self):
        """FingerprintTemplate is importable and is a class."""
        assert isinstance(FingerprintTemplate, type)

    def test_is_dataclass(self):
        """FingerprintTemplate should be a dataclass."""
        assert hasattr(FingerprintTemplate, "__dataclass_fields__")

    def test_has_name_field(self):
        """FingerprintTemplate has a 'name' field."""
        assert "name" in FingerprintTemplate.__dataclass_fields__

    def test_name_is_string(self):
        """FingerprintTemplate.name has type str."""
        hints = get_type_hints(FingerprintTemplate)
        assert hints.get("name") is str, f"name should be str, got {hints.get('name')}"

    def test_has_browser_field(self):
        """FingerprintTemplate has a 'browser' field."""
        assert "browser" in FingerprintTemplate.__dataclass_fields__

    def test_browser_is_string(self):
        """FingerprintTemplate.browser has type str."""
        hints = get_type_hints(FingerprintTemplate)
        assert hints.get("browser") is str, (
            f"browser should be str, got {hints.get('browser')}"
        )

    def test_has_metadata_field(self):
        """FingerprintTemplate has a 'metadata' field."""
        assert "metadata" in FingerprintTemplate.__dataclass_fields__

    def test_has_signals_field(self):
        """FingerprintTemplate has a 'signals' field."""
        assert "signals" in FingerprintTemplate.__dataclass_fields__

    def test_has_config_field(self):
        """FingerprintTemplate has a 'config' field."""
        assert "config" in FingerprintTemplate.__dataclass_fields__

    def test_to_dict_method(self):
        """FingerprintTemplate has a to_dict() method."""
        assert hasattr(FingerprintTemplate, "to_dict")
        assert callable(FingerprintTemplate.to_dict)

    def test_to_dict_signature(self):
        """to_dict() takes only self."""
        # to_dict() should return dict
        _sig = inspect.signature(FingerprintTemplate.to_dict)
        hints = get_type_hints(FingerprintTemplate.to_dict)
        return_ann = hints.get("return")
        # Accept dict or dict[str, Any]
        hints_str = str(return_ann) if return_ann else ""
        assert "dict" in hints_str.lower() or return_ann is dict, (
            f"to_dict should return dict, got {return_ann}"
        )

    def test_from_dict_classmethod(self):
        """FingerprintTemplate has a from_dict classmethod."""
        assert hasattr(FingerprintTemplate, "from_dict")
        assert callable(FingerprintTemplate.from_dict)

    def test_from_dict_signature(self):
        """from_dict accepts (data: dict) -> FingerprintTemplate."""
        sig = inspect.signature(FingerprintTemplate.from_dict)
        params = list(sig.parameters.values())
        # Skip cls — so we expect 1 param after cls
        non_self = [p for p in params if p.name not in ("cls", "self")]
        assert len(non_self) >= 1, "from_dict should accept at least 1 argument"
        assert non_self[0].name == "data"

    def test_can_instantiate(self):
        """Can create a FingerprintTemplate with minimal args."""
        tmpl = FingerprintTemplate(name="test", browser="chrome")
        assert tmpl.name == "test"
        assert tmpl.browser == "chrome"

    def test_fields_default_to_empty_dict(self):
        """metadata, signals, config default to empty dict."""
        tmpl = FingerprintTemplate(name="test", browser="chrome")
        assert tmpl.metadata == {}
        assert tmpl.signals == {}
        assert tmpl.config == {}


class TestDEFAULT_TEMPLATESInterface:
    """DEFAULT_TEMPLATES dict contract tests."""

    def test_default_templates_exists(self):
        """DEFAULT_TEMPLATES is accessible from the module."""
        assert isinstance(DEFAULT_TEMPLATES, dict)

    def test_has_four_templates(self):
        """DEFAULT_TEMPLATES contains exactly 4 templates."""
        assert len(DEFAULT_TEMPLATES) == 4, (
            f"Expected 4 templates, got {len(DEFAULT_TEMPLATES)}"
        )

    def test_contains_chrome_120(self):
        """'chrome-120' is in DEFAULT_TEMPLATES."""
        assert "chrome-120" in DEFAULT_TEMPLATES

    def test_contains_firefox_linux(self):
        """'firefox-linux' is in DEFAULT_TEMPLATES."""
        assert "firefox-linux" in DEFAULT_TEMPLATES

    def test_contains_safari_ios(self):
        """'safari-ios' is in DEFAULT_TEMPLATES."""
        assert "safari-ios" in DEFAULT_TEMPLATES

    def test_contains_edge_windows(self):
        """'edge-windows' is in DEFAULT_TEMPLATES."""
        assert "edge-windows" in DEFAULT_TEMPLATES

    def test_each_template_has_browser_key(self):
        """Each default template dict has a 'browser' key."""
        for name, data in DEFAULT_TEMPLATES.items():
            assert "browser" in data, f"{name} missing 'browser'"

    def test_each_template_has_signals_key(self):
        """Each default template dict has a 'signals' key."""
        for name, data in DEFAULT_TEMPLATES.items():
            assert "signals" in data, f"{name} missing 'signals'"

    def test_each_template_has_config_key(self):
        """Each default template dict has a 'config' key."""
        for name, data in DEFAULT_TEMPLATES.items():
            assert "config" in data, f"{name} missing 'config'"

    def test_each_template_has_metadata_key(self):
        """Each default template dict has a 'metadata' key."""
        for name, data in DEFAULT_TEMPLATES.items():
            assert "metadata" in data, f"{name} missing 'metadata'"


class TestFingerprintDatabaseInterface:
    """FingerprintDatabase class contract tests."""

    def test_class_exists(self):
        """FingerprintDatabase is importable and is a class."""
        assert isinstance(FingerprintDatabase, type)

    def test_has_DEFAULT_TEMPLATES_classvar(self):
        """FingerprintDatabase.DEFAULT_TEMPLATES is a ClassVar dict."""
        assert isinstance(FingerprintDatabase.DEFAULT_TEMPLATES, dict)
        assert len(FingerprintDatabase.DEFAULT_TEMPLATES) == 4

    def test_init_accepts_optional_storage_dir(self):
        """FingerprintDatabase.__init__ accepts (storage_dir: str | None)."""
        sig = inspect.signature(FingerprintDatabase.__init__)
        params = list(sig.parameters.values())
        params_no_self = [p for p in params if p.name != "self"]
        assert len(params_no_self) >= 1
        assert params_no_self[0].name == "storage_dir"
        # Check it has a default (None)
        assert params_no_self[0].default is None, (
            "storage_dir should default to None"
        )

    def test_can_instantiate_with_no_args(self):
        """FingerprintDatabase() should not raise."""
        db = FingerprintDatabase(storage_dir="/tmp/test_fp_db_init")
        assert isinstance(db, FingerprintDatabase)

    def test_has_list_templates_method(self):
        """FingerprintDatabase has list_templates()."""
        assert hasattr(FingerprintDatabase, "list_templates")
        assert callable(FingerprintDatabase.list_templates)

    def test_list_templates_signature(self):
        """list_templates() -> list[dict]."""
        sig = inspect.signature(FingerprintDatabase.list_templates)
        params_no_self = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params_no_self) == 0, "list_templates should take only self"

    def test_has_get_template_method(self):
        """FingerprintDatabase has get_template()."""
        assert hasattr(FingerprintDatabase, "get_template")
        assert callable(FingerprintDatabase.get_template)

    def test_get_template_signature(self):
        """get_template(name) -> FingerprintTemplate | None."""
        sig = inspect.signature(FingerprintDatabase.get_template)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 1
        assert params[0].name == "name"

    def test_has_add_template_method(self):
        """FingerprintDatabase has add_template()."""
        assert hasattr(FingerprintDatabase, "add_template")
        assert callable(FingerprintDatabase.add_template)

    def test_add_template_signature(self):
        """add_template(template) -> None."""
        sig = inspect.signature(FingerprintDatabase.add_template)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 1
        assert params[0].name == "template"

    def test_has_update_template_method(self):
        """FingerprintDatabase has update_template()."""
        assert hasattr(FingerprintDatabase, "update_template")
        assert callable(FingerprintDatabase.update_template)

    def test_update_template_signature(self):
        """update_template(name, updates) -> bool."""
        sig = inspect.signature(FingerprintDatabase.update_template)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 2
        assert params[0].name == "name"
        assert params[1].name == "updates"

    def test_has_delete_template_method(self):
        """FingerprintDatabase has delete_template()."""
        assert hasattr(FingerprintDatabase, "delete_template")
        assert callable(FingerprintDatabase.delete_template)

    def test_delete_template_signature(self):
        """delete_template(name) -> bool."""
        sig = inspect.signature(FingerprintDatabase.delete_template)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 1
        assert params[0].name == "name"

    def test_has_generate_template_method(self):
        """FingerprintDatabase has generate_template()."""
        assert hasattr(FingerprintDatabase, "generate_template")
        assert callable(FingerprintDatabase.generate_template)

    def test_generate_template_signature(self):
        """generate_template(browser) -> FingerprintTemplate."""
        sig = inspect.signature(FingerprintDatabase.generate_template)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 1
        assert params[0].name == "browser"

    def test_has_save_method(self):
        """FingerprintDatabase has save()."""
        assert hasattr(FingerprintDatabase, "save")
        assert callable(FingerprintDatabase.save)

    def test_has_load_method(self):
        """FingerprintDatabase has load()."""
        assert hasattr(FingerprintDatabase, "load")
        assert callable(FingerprintDatabase.load)

    def test_has_export_template_method(self):
        """FingerprintDatabase has export_template()."""
        assert hasattr(FingerprintDatabase, "export_template")
        assert callable(FingerprintDatabase.export_template)

    def test_export_template_signature(self):
        """export_template(name, path) -> None."""
        sig = inspect.signature(FingerprintDatabase.export_template)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 2
        assert params[0].name == "name"
        assert params[1].name == "path"

    def test_has_import_template_method(self):
        """FingerprintDatabase has import_template()."""
        assert hasattr(FingerprintDatabase, "import_template")
        assert callable(FingerprintDatabase.import_template)

    def test_import_template_signature(self):
        """import_template(path) -> str."""
        sig = inspect.signature(FingerprintDatabase.import_template)
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 1
        assert params[0].name == "path"


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def storage_dir(tmp_path):
    """Return a temporary storage directory."""
    return str(tmp_path / "fingerprints")


@pytest.fixture
def db(storage_dir):
    """Return a FingerprintDatabase instance isolated to a temp directory."""
    return FingerprintDatabase(storage_dir=storage_dir)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — Behavioral Tests (RED — XFAIL until implementation)
# ═══════════════════════════════════════════════════════════════════════════


class TestDefaultTemplatesBehavior:
    """Acceptance criteria 1-2: DEFAULT_TEMPLATES and list_templates."""

    @pytest.mark.xfail(reason="P0.1 not implemented: list_templates() returns defaults")
    def test_list_templates_returns_four_defaults(self, db):
        """AC-2: list_templates() returns all 4 default templates on first call."""
        templates = db.list_templates()
        assert len(templates) == 4
        names = [t["name"] for t in templates]
        assert "chrome-120" in names
        assert "firefox-linux" in names
        assert "safari-ios" in names
        assert "edge-windows" in names

    @pytest.mark.xfail(
        reason="P0.1 not implemented: list includes browser metadata"
    )
    def test_list_includes_browser_field(self, db):
        """Each list entry has 'name', 'browser', 'metadata' keys."""
        templates = db.list_templates()
        for t in templates:
            assert "name" in t, f"Entry missing 'name': {t}"
            assert "browser" in t, f"Entry missing 'browser': {t}"
            assert "metadata" in t, f"Entry missing 'metadata': {t}"


class TestGetTemplateBehavior:
    """Acceptance criteria 3-4: get_template."""

    @pytest.mark.xfail(
        reason="P0.1 not implemented: get_template returns FingerprintTemplate"
    )
    def test_get_chrome_120_returns_complete_template(self, db):
        """AC-3: get_template('chrome-120') returns a complete FingerprintTemplate."""
        tmpl = db.get_template("chrome-120")
        assert isinstance(tmpl, FingerprintTemplate)
        assert tmpl.name == "chrome-120"
        assert tmpl.browser == "chrome"
        assert tmpl.signals, "signals dict should be non-empty"
        assert "navigator" in tmpl.signals, "signals should contain navigator"
        assert "webgl" in tmpl.signals, "signals should contain webgl"
        assert tmpl.config, "config dict should be non-empty"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: get_template returns None for missing"
    )
    def test_get_nonexistent_returns_none(self, db):
        """AC-4: get_template('nonexistent') returns None."""
        result = db.get_template("nonexistent")
        assert result is None

    @pytest.mark.xfail(
        reason="P0.1 not implemented: get_template for other defaults"
    )
    def test_get_firefox_linux(self, db):
        """get_template('firefox-linux') returns a valid template."""
        tmpl = db.get_template("firefox-linux")
        assert isinstance(tmpl, FingerprintTemplate)
        assert tmpl.name == "firefox-linux"
        assert tmpl.browser == "firefox"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: get_template for safari"
    )
    def test_get_safari_ios(self, db):
        """get_template('safari-ios') returns a valid template."""
        tmpl = db.get_template("safari-ios")
        assert isinstance(tmpl, FingerprintTemplate)
        assert tmpl.name == "safari-ios"
        assert tmpl.browser == "safari"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: get_template for edge"
    )
    def test_get_edge_windows(self, db):
        """get_template('edge-windows') returns a valid template."""
        tmpl = db.get_template("edge-windows")
        assert isinstance(tmpl, FingerprintTemplate)
        assert tmpl.name == "edge-windows"
        assert tmpl.browser == "edge"


class TestCRUDBehavior:
    """Acceptance criteria 5-7: add/update/delete CRUD."""

    @pytest.mark.xfail(reason="P0.1 not implemented: add_template")
    def test_add_template_persists_and_appears_in_list(self, db):
        """AC-5: add_template persists and appears in list."""
        tmpl = FingerprintTemplate(
            name="custom-chrome",
            browser="chrome",
            metadata={"version": "120", "description": "Custom profile"},
            signals={"navigator": {"user_agent": "Custom UA"}},
            config={"canvas_noise_seed": 42},
        )
        db.add_template(tmpl)
        templates = db.list_templates()
        names = [t["name"] for t in templates]
        assert "custom-chrome" in names

    @pytest.mark.xfail(reason="P0.1 not implemented: get after add")
    def test_added_template_is_retrievable(self, db):
        """An added template is retrievable via get_template."""
        tmpl = FingerprintTemplate(name="custom-edge", browser="edge")
        db.add_template(tmpl)
        retrieved = db.get_template("custom-edge")
        assert retrieved is not None
        assert retrieved.name == "custom-edge"
        assert retrieved.browser == "edge"

    @pytest.mark.xfail(reason="P0.1 not implemented: duplicate add raises")
    def test_add_duplicate_raises_value_error(self, db):
        """Adding a template with an existing name raises ValueError."""
        tmpl1 = FingerprintTemplate(name="duplicate", browser="chrome")
        tmpl2 = FingerprintTemplate(name="duplicate", browser="firefox")
        db.add_template(tmpl1)
        with pytest.raises(ValueError, match=r"(?i)already exists|duplicate"):
            db.add_template(tmpl2)

    @pytest.mark.xfail(reason="P0.1 not implemented: update_template")
    def test_update_template_modifies_fields(self, db):
        """AC-6: update_template modifies fields as specified."""
        db.add_template(
            FingerprintTemplate(
                name="updatable",
                browser="chrome",
                metadata={"description": "Original"},
                signals={"navigator": {"user_agent": "Original UA"}},
            )
        )
        result = db.update_template(
            "updatable",
            {"metadata": {"description": "Updated"}},
        )
        assert result is True
        updated = db.get_template("updatable")
        assert updated is not None
        assert updated.metadata.get("description") == "Updated"

    @pytest.mark.xfail(reason="P0.1 not implemented: update nonexistent")
    def test_update_nonexistent_returns_false(self, db):
        """update_template on a nonexistent name returns False."""
        result = db.update_template("nonexistent", {"metadata": {}})
        assert result is False

    @pytest.mark.xfail(reason="P0.1 not implemented: delete_template")
    def test_delete_template_removes_from_list(self, db):
        """AC-7: delete_template removes template and it no longer appears in list."""
        db.add_template(FingerprintTemplate(name="deletable", browser="chrome"))
        result = db.delete_template("deletable")
        assert result is True
        templates = db.list_templates()
        names = [t["name"] for t in templates]
        assert "deletable" not in names

    @pytest.mark.xfail(reason="P0.1 not implemented: get after delete")
    def test_delete_makes_get_return_none(self, db):
        """After deletion, get_template returns None."""
        db.add_template(FingerprintTemplate(name="disappear", browser="chrome"))
        db.delete_template("disappear")
        assert db.get_template("disappear") is None

    @pytest.mark.xfail(reason="P0.1 not implemented: delete nonexistent")
    def test_delete_nonexistent_returns_false(self, db):
        """delete_template on a nonexistent name returns False."""
        result = db.delete_template("nonexistent")
        assert result is False


class TestGenerateTemplateBehavior:
    """Acceptance criteria 8-9: generate_template."""

    @pytest.mark.xfail(
        reason="P0.1 not implemented: generate_template chrome"
    )
    def test_generate_chrome_returns_valid_template(self, db):
        """AC-8: generate_template('chrome') creates a plausible random template."""
        tmpl = db.generate_template("chrome")
        assert isinstance(tmpl, FingerprintTemplate)
        assert tmpl.browser == "chrome"
        assert tmpl.signals, "signals should be populated"
        assert "navigator" in tmpl.signals
        assert "Chrome" in tmpl.signals["navigator"].get("user_agent", "")
        assert tmpl.config, "config should be populated"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: generate_template firefox"
    )
    def test_generate_firefox_returns_valid_template(self, db):
        """AC-9: generate_template('firefox') creates a plausible random template."""
        tmpl = db.generate_template("firefox")
        assert isinstance(tmpl, FingerprintTemplate)
        assert tmpl.browser == "firefox"
        assert "Firefox" in tmpl.signals["navigator"].get("user_agent", "")

    @pytest.mark.xfail(
        reason="P0.1 not implemented: generate_template safari"
    )
    def test_generate_safari_returns_valid_template(self, db):
        """generate_template('safari') returns a Safari template."""
        tmpl = db.generate_template("safari")
        assert isinstance(tmpl, FingerprintTemplate)
        assert tmpl.browser == "safari"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: generate_template edge"
    )
    def test_generate_edge_returns_valid_template(self, db):
        """generate_template('edge') returns an Edge template."""
        tmpl = db.generate_template("edge")
        assert isinstance(tmpl, FingerprintTemplate)
        assert tmpl.browser == "edge"
        assert "Edg/" in tmpl.signals["navigator"].get("user_agent", "")

    @pytest.mark.xfail(
        reason="P0.1 not implemented: generate for unknown browser raises"
    )
    def test_generate_invalid_browser_raises(self, db):
        """generate_template with unknown browser raises ValueError."""
        with pytest.raises(ValueError, match=r"(?i)unknown|unsupported|invalid"):
            db.generate_template("opera")

    @pytest.mark.xfail(
        reason="P0.1 not implemented: generate is non-deterministic"
    )
    def test_generate_is_non_deterministic(self, db):
        """Two calls to generate_template('chrome') produce different results."""
        tmpl1 = db.generate_template("chrome")
        tmpl2 = db.generate_template("chrome")
        # Different hardware GPU selection should make them differ
        assert tmpl1.config != tmpl2.config or tmpl1.signals != tmpl2.signals, (
            "generate_template should produce different results on each call"
        )

    @pytest.mark.xfail(
        reason="P0.1 not implemented: generated has signals with all groups"
    )
    def test_generated_template_has_all_signal_groups(self, db):
        """Generated template contains navigator, screen, webgl, canvas, audio."""
        tmpl = db.generate_template("chrome")
        assert "navigator" in tmpl.signals
        assert "screen" in tmpl.signals
        assert "webgl" in tmpl.signals
        assert "canvas" in tmpl.signals
        assert "audio" in tmpl.signals
        assert "timezone" in tmpl.signals
        assert "locale" in tmpl.signals


class TestPersistenceBehavior:
    """Acceptance criteria 10: persistence round-trip."""

    @pytest.mark.xfail(
        reason="P0.1 not implemented: save/load persistence"
    )
    def test_templates_survive_re_init(self, storage_dir):
        """AC-10: Templates persist to disk and survive a re-init."""
        db1 = FingerprintDatabase(storage_dir=storage_dir)
        db1.add_template(
            FingerprintTemplate(name="persist-test", browser="chrome")
        )

        db2 = FingerprintDatabase(storage_dir=storage_dir)
        tmpl = db2.get_template("persist-test")
        assert tmpl is not None
        assert tmpl.name == "persist-test"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: added defaults persist"
    )
    def test_defaults_survive_re_init(self, storage_dir):
        """Default templates are still available after re-init."""
        FingerprintDatabase(storage_dir=storage_dir)  # db1 — init then discard
        db2 = FingerprintDatabase(storage_dir=storage_dir)
        templates = db2.list_templates()
        assert len(templates) == 4

    @pytest.mark.xfail(
        reason="P0.1 not implemented: delete persists"
    )
    def test_deletion_survives_re_init(self, storage_dir):
        """Deleted default does not reappear after re-init."""
        db1 = FingerprintDatabase(storage_dir=storage_dir)
        db1.delete_template("chrome-120")

        db2 = FingerprintDatabase(storage_dir=storage_dir)
        tmpl = db2.get_template("chrome-120")
        assert tmpl is None

    @pytest.mark.xfail(
        reason="P0.1 not implemented: update persists"
    )
    def test_update_survives_re_init(self, storage_dir):
        """Updated template metadata persists across re-init."""
        db1 = FingerprintDatabase(storage_dir=storage_dir)
        db1.update_template(
            "chrome-120",
            {"metadata": {"description": "Persist update test"}},
        )

        db2 = FingerprintDatabase(storage_dir=storage_dir)
        tmpl = db2.get_template("chrome-120")
        assert tmpl is not None
        assert tmpl.metadata.get("description") == "Persist update test"


class TestExportImportBehavior:
    """Acceptance criteria 11-12: export/import round-trip."""

    @pytest.mark.xfail(
        reason="P0.1 not implemented: export_template"
    )
    def test_export_writes_valid_json(self, db, tmp_path):
        """AC-11: export_template(name, path) writes a valid JSON file."""
        export_path = str(tmp_path / "chrome-120.json")
        db.export_template("chrome-120", export_path)
        assert os.path.isfile(export_path)
        with open(export_path) as f:
            data = json.load(f)
        assert "name" in data
        assert data["name"] == "chrome-120"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: export nonexistent raises"
    )
    def test_export_nonexistent_raises(self, db, tmp_path):
        """export_template on nonexistent name raises KeyError."""
        export_path = str(tmp_path / "nope.json")
        with pytest.raises(KeyError):
            db.export_template("nonexistent", export_path)

    @pytest.mark.xfail(
        reason="P0.1 not implemented: import_template"
    )
    def test_import_loads_json_into_db(self, db, tmp_path):
        """AC-12: import_template(path) reads JSON and loads into DB."""
        # First export a template
        export_path = str(tmp_path / "for-import.json")
        db.export_template("chrome-120", export_path)

        # Create a fresh DB and import
        db2 = FingerprintDatabase(storage_dir=str(tmp_path / "import-test"))
        name = db2.import_template(export_path)
        assert name == "chrome-120"
        tmpl = db2.get_template("chrome-120")
        assert tmpl is not None
        assert tmpl.browser == "chrome"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: import returns name"
    )
    def test_import_returns_template_name(self, db, tmp_path):
        """import_template returns the name of the imported template."""
        export_path = str(tmp_path / "export-for-return.json")
        db.export_template("firefox-linux", export_path)

        db2 = FingerprintDatabase(storage_dir=str(tmp_path / "import-return"))
        name = db2.import_template(export_path)
        assert name == "firefox-linux"

    @pytest.mark.xfail(
        reason="P0.1 not implemented: import invalid JSON raises"
    )
    def test_import_invalid_json_raises(self, db, tmp_path):
        """import_template with invalid JSON raises ValueError."""
        bad_path = str(tmp_path / "bad.json")
        with open(bad_path, "w") as f:
            f.write("not json")
        with pytest.raises(ValueError, match=r"(?i)invalid|not a valid|parse"):
            db.import_template(bad_path)

    @pytest.mark.xfail(
        reason="P0.1 not implemented: export/import round-trip"
    )
    def test_export_import_round_trip(self, db, tmp_path):
        """Export → import → get_template produces identical data."""
        # Add a custom template
        original = FingerprintTemplate(
            name="round-trip",
            browser="edge",
            metadata={"version": "120", "description": "Round trip test"},
            signals={
                "navigator": {
                    "user_agent": "Round Trip UA",
                    "platform": "Win64",
                },
                "webgl": {
                    "vendor": "Intel",
                    "renderer": "Intel UHD",
                },
            },
            config={"canvas_noise_seed": 99, "screen_width": 1920},
        )
        db.add_template(original)

        export_path = str(tmp_path / "round-trip.json")
        db.export_template("round-trip", export_path)

        db2 = FingerprintDatabase(storage_dir=str(tmp_path / "round-trip-db"))
        db2.import_template(export_path)
        loaded = db2.get_template("round-trip")

        assert loaded is not None
        assert loaded.name == original.name
        assert loaded.browser == original.browser
        assert loaded.signals["navigator"]["user_agent"] == "Round Trip UA"
        assert loaded.config["canvas_noise_seed"] == 99


class TestGracefulFallbackBehavior:
    """Acceptance criteria 13-14: graceful initialization."""

    @pytest.mark.xfail(
        reason="P0.1 not implemented: empty storage dir loads defaults"
    )
    def test_empty_storage_dir_loads_defaults(self, tmp_path):
        """AC-13: Empty storage dir → database initializes with defaults."""
        empty_dir = str(tmp_path / "empty-storage")
        db = FingerprintDatabase(storage_dir=empty_dir)
        templates = db.list_templates()
        assert len(templates) == 4, (
            f"Expected 4 defaults from empty dir, got {len(templates)}"
        )

    @pytest.mark.xfail(
        reason="P0.1 not implemented: corrupted JSON fallback"
    )
    def test_corrupted_json_loads_defaults(self, tmp_path):
        """AC-14: Corrupted JSON file → database initializes with defaults."""
        storage_dir = str(tmp_path / "corrupted-storage")
        os.makedirs(storage_dir, exist_ok=True)
        # Write a corrupted JSON file
        with open(os.path.join(storage_dir, "chrome-120.json"), "w") as f:
            f.write("{corrupted json!!!}")

        db = FingerprintDatabase(storage_dir=storage_dir)
        templates = db.list_templates()
        assert len(templates) >= 1, (
            "DB should still work with corrupt fallback"
        )

    @pytest.mark.xfail(
        reason="P0.1 not implemented: non-existent storage dir"
    )
    def test_nonexistent_storage_dir_creates_and_loads_defaults(self, tmp_path):
        """Storage dir that doesn't exist is created and defaults loaded."""
        non_existent = str(tmp_path / "brand-new" / "nested")
        db = FingerprintDatabase(storage_dir=non_existent)
        assert os.path.isdir(non_existent), "Storage dir should have been created"
        templates = db.list_templates()
        assert len(templates) == 4

    @pytest.mark.xfail(
        reason="P0.1 not implemented: mixed good/bad files"
    )
    def test_mixed_valid_and_corrupted_files(self, tmp_path):
        """Valid templates are loaded even when some files are corrupted."""
        storage_dir = str(tmp_path / "mixed-storage")
        os.makedirs(storage_dir, exist_ok=True)
        # Write one corrupt file
        with open(os.path.join(storage_dir, "corrupt.json"), "w") as f:
            f.write("bad data")
        # Write one valid file
        valid = FingerprintTemplate(
            name="valid-template", browser="chrome"
        ).to_dict()
        with open(os.path.join(storage_dir, "valid.json"), "w") as f:
            json.dump(valid, f)

        db = FingerprintDatabase(storage_dir=storage_dir)
        tmpl = db.get_template("valid-template")
        assert tmpl is not None, "Valid file should be loaded despite corruption"


class TestEdgeCasesBehavior:
    """Additional edge-case behavioral tests."""

    @pytest.mark.xfail(
        reason="P0.1 not implemented: empty name"
    )
    def test_add_template_empty_name(self, db):
        """Adding a template with empty name is handled gracefully."""
        tmpl = FingerprintTemplate(name="", browser="chrome")
        with pytest.raises(ValueError):
            db.add_template(tmpl)

    @pytest.mark.xfail(
        reason="P0.1 not implemented: update empty dict"
    )
    def test_update_with_empty_dict(self, db):
        """Updating with empty dict does not error."""
        result = db.update_template("chrome-120", {})
        # Should succeed (no-op) or return True
        assert result is True

    @pytest.mark.xfail(
        reason="P0.1 not implemented: list returns fresh copy"
    )
    def test_list_templates_returns_separate_objects(self, db):
        """list_templates returns independent copies, not internal references."""
        templates1 = db.list_templates()
        templates2 = db.list_templates()
        # Modifying one shouldn't affect the other
        if templates1:
            templates1[0] = {"name": "hacked", "browser": "hacked"}
            t2_names = [t["name"] for t in templates2]
            assert "hacked" not in t2_names

    @pytest.mark.xfail(
        reason="P0.1 not implemented: concurrent add and get"
    )
    def test_add_then_immediate_get(self, db):
        """get_template immediately after add_template returns the new template."""
        tmpl = FingerprintTemplate(
            name="immediate",
            browser="chrome",
            signals={"navigator": {"user_agent": "Immediate UA"}},
        )
        db.add_template(tmpl)
        retrieved = db.get_template("immediate")
        assert retrieved is not None
        assert retrieved.signals["navigator"]["user_agent"] == "Immediate UA"
class TestR1DefaultInstanceLoadsPersisted:
    """R1 regression: default-constructed FingerprintDatabase loads persisted files."""

    def test_default_constructor_loads_from_disk(self, tmp_path, monkeypatch):
        """Default FingerprintDatabase() must load templates persisted by a
        previous instance (review R1).  Uses monkeypatched HOME so tests
        don't touch the real user directory."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        # First instance: add a custom template and save to default path
        db1 = FingerprintDatabase()
        tpl = FingerprintTemplate(name="r1-persist-test", browser="chrome")
        db1.add_template(tpl)
        db1.save()

        # Second default-constructed instance must find the persisted template
        db2 = FingerprintDatabase()
        found = db2.get_template("r1-persist-test")
        assert found is not None, (
            "Default-constructed FingerprintDatabase must load persisted files"
        )
        assert found.name == "r1-persist-test"
        assert found.browser == "chrome"

    def test_default_constructor_also_has_defaults(self, tmp_path, monkeypatch):
        """Default-constructed FingerprintDatabase still has the 4 built-in
        defaults even when the storage dir was empty."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        db = FingerprintDatabase()
        names = [t["name"] for t in db.list_templates()]
        for default_name in ("chrome-120", "firefox-linux", "safari-ios", "edge-windows"):
            assert default_name in names, f"Default template {default_name} missing"
