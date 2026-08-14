"""
Tests for FingerprintDatabase (P0.1).

Interface tests: verify FingerprintTemplate dataclass, FingerprintDatabase class,
DEFAULT_TEMPLATES, and CRUD operations.
Behavioral tests: verify generate_template, save/load round-trip, and
export/import (implementation exists; the stale RED-phase
NotImplementedError assertions were removed — see a7952e5).

Coverage:
  - FingerprintTemplate dataclass fields
  - FingerprintDatabase class exists, constructor, DEFAULT_TEMPLATES
  - list_templates, get_template (found + not found)
  - add_template, update_template, delete_template
  - generate_template
  - save / load
  - export_template / import_template
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

from anti_detection.fingerprint_database import FingerprintDatabase, FingerprintTemplate

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def db(tmp_path) -> FingerprintDatabase:
    """Return a FingerprintDatabase with a temp storage directory."""
    storage = str(tmp_path / "fingerprints")
    return FingerprintDatabase(storage_dir=storage)


@pytest.fixture
def sample_template() -> FingerprintTemplate:
    """Return a minimal valid FingerprintTemplate."""
    return FingerprintTemplate(
        name="test-chrome",
        browser="chrome",
        signals={"canvas": {"noise_enabled": True}},
        config={"canvas_noise_seed": 42},
    )


# ===================================================================
# Interface tests — pass immediately against the stub
# ===================================================================


class TestFingerprintTemplateInterface:
    """Verify FingerprintTemplate dataclass fields."""

    def test_import(self):
        """FingerprintTemplate is importable."""
        assert FingerprintTemplate is not None

    def test_is_dataclass(self):
        """FingerprintTemplate is a dataclass."""
        from dataclasses import is_dataclass

        assert is_dataclass(FingerprintTemplate)

    def test_required_fields(self):
        """FingerprintTemplate has the required fields."""
        tpl = FingerprintTemplate(
            name="test",
            browser="chrome",
            signals={},
            config={},
        )
        assert tpl.name == "test"
        assert tpl.browser == "chrome"
        assert tpl.signals == {}
        assert tpl.config == {}
        assert isinstance(tpl.metadata, dict)

    def test_metadata_defaults(self):
        """FingerprintTemplate.metadata has sensible defaults."""
        tpl = FingerprintTemplate(
            name="test",
            browser="chrome",
            signals={},
            config={},
        )
        assert "version" in tpl.metadata
        assert "created_at" in tpl.metadata
        assert "description" in tpl.metadata


class TestFingerprintDatabaseInterface:
    """Verify FingerprintDatabase class and constructor."""

    def test_import(self):
        """FingerprintDatabase is importable."""
        assert FingerprintDatabase is not None

    def test_constructor(self, db):
        """FingerprintDatabase can be instantiated with a storage dir."""
        assert isinstance(db, FingerprintDatabase)

    def test_constructor_default_dir(self):
        """FingerprintDatabase() uses default ~/.browser-helper/fingerprints/."""
        db_default = FingerprintDatabase()
        assert isinstance(db_default, FingerprintDatabase)

    def test_default_templates_exist(self):
        """DEFAULT_TEMPLATES is a class variable with 4 entries."""
        templates = FingerprintDatabase.DEFAULT_TEMPLATES
        assert isinstance(templates, dict)
        assert len(templates) == 4
        for name in ("chrome-120", "firefox-linux", "safari-ios", "edge-windows"):
            assert name in templates, f"Missing default template: {name}"

    def test_default_templates_have_required_keys(self):
        """Each DEFAULT_TEMPLATES entry has name, browser, metadata, signals, config."""
        for name, data in FingerprintDatabase.DEFAULT_TEMPLATES.items():
            assert "name" in data, f"{name} missing 'name'"
            assert "browser" in data, f"{name} missing 'browser'"
            assert "signals" in data, f"{name} missing 'signals'"
            assert "config" in data, f"{name} missing 'config'"

    def test_list_templates_returns_list(self, db):
        """list_templates returns a list of template summaries."""
        result = db.list_templates()
        assert isinstance(result, list)
        if result:
            for item in result:
                assert "name" in item
                assert "browser" in item

    def test_get_template_found(self, db):
        """get_template('chrome-120') returns a FingerprintTemplate."""
        tpl = db.get_template("chrome-120")
        assert tpl is not None
        assert isinstance(tpl, FingerprintTemplate)
        assert tpl.name == "chrome-120"

    def test_get_template_not_found(self, db):
        """get_template('nonexistent') returns None."""
        tpl = db.get_template("nonexistent")
        assert tpl is None

    def test_add_template(self, db, sample_template):
        """add_template persists template and it appears in list."""
        db.add_template(sample_template)
        tpl = db.get_template("test-chrome")
        assert tpl is not None
        assert tpl.name == "test-chrome"
        assert tpl.browser == "chrome"

    def test_update_template(self, db):
        """update_template modifies fields as specified."""
        db.update_template("chrome-120", {"browser": "chrome-updated"})
        tpl = db.get_template("chrome-120")
        assert tpl is not None
        assert tpl.browser == "chrome-updated"

    def test_update_template_not_found(self, db):
        """update_template on nonexistent name returns False."""
        result = db.update_template("nonexistent", {})
        assert result is False

    def test_delete_template(self, db):
        """delete_template removes template from the database."""
        db.delete_template("chrome-120")
        assert db.get_template("chrome-120") is None

    def test_delete_template_not_found(self, db):
        """delete_template on nonexistent name returns False."""
        result = db.delete_template("nonexistent")
        assert result is False


# ===================================================================
# Behavioral tests — RED phase, must raise NotImplementedError
# ===================================================================


class TestFingerprintDatabaseGenerateRED:
    """generate_template() — behavioral tests (implementation exists)."""

    def test_generate_chrome_returns_template(self, db):
        """generate_template('chrome') should return a valid FingerprintTemplate."""
        try:
            tpl = db.generate_template("chrome")
            assert isinstance(tpl, FingerprintTemplate)
            assert tpl.browser == "chrome"
            assert len(tpl.signals) > 0
        except NotImplementedError:
            pytest.fail(
                "generate_template must be implemented to verify Chrome generation. "
                "See test_generate_raises_not_implemented."
            )

    def test_generate_firefox_returns_different_profile(self, db):
        """Generated profiles differ per browser type."""
        try:
            chrome_tpl = db.generate_template("chrome")
            firefox_tpl = db.generate_template("firefox")
            assert chrome_tpl.name != firefox_tpl.name
        except NotImplementedError:
            pytest.fail(
                "generate_template must be implemented to verify browser-specific generation. "
                "See test_generate_raises_not_implemented."
            )


class TestFingerprintDatabasePersistenceRED:
    """save()/load() — behavioral tests (implementation exists)."""

    def test_save_and_reload_preserves_templates(self, db, sample_template):
        """Saved templates should survive a new FingerprintDatabase() init."""
        db.add_template(sample_template)
        try:
            db.save()
            db2 = FingerprintDatabase(storage_dir=db._storage_dir)
            db2.load()
            assert db2.get_template("test-chrome") is not None
        except NotImplementedError:
            pytest.fail(
                "save/load must be implemented to verify persistence round-trip. "
                "See test_save_raises_not_implemented."
            )


class TestFingerprintDatabaseImportExportRED:
    """export_template()/import_template() — behavioral tests (implementation exists)."""

    def test_export_writes_valid_json(self, db, tmp_path):
        """export_template('chrome-120', path) should write a valid JSON file."""
        export_path = str(tmp_path / "chrome-120.json")
        try:
            db.export_template("chrome-120", export_path)
            with open(export_path) as f:
                data = json.load(f)
            assert data["name"] == "chrome-120"
        except NotImplementedError:
            pytest.fail(
                "export_template must be implemented to verify JSON output. "
                "See test_export_raises_not_implemented."
            )

    def test_import_reads_valid_json(self, db, tmp_path):
        """import_template(path) should read a JSON file and add the template."""
        import_path = tmp_path / "import.json"
        import_data = {
            "name": "imported-chrome",
            "browser": "chrome",
            "signals": {},
            "config": {},
            "metadata": {"version": 1, "created_at": 0.0, "description": "imported"},
        }
        with open(import_path, "w") as f:
            json.dump(import_data, f)
        try:
            name = db.import_template(str(import_path))
            assert name == "imported-chrome"
            assert db.get_template("imported-chrome") is not None
        except NotImplementedError:
            pytest.fail(
                "import_template must be implemented to verify JSON input. "
                "See test_import_raises_not_implemented."
            )
