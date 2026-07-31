"""
FingerprintDatabase — JSON-backed browser fingerprint template database (P0.1).

Provides persistent storage for named ``FingerprintTemplate`` objects plus
generation of randomized templates per browser family. Templates are loaded
from JSON files in a storage directory at construction, are exposed through
CRUD accessors (list/get/add/update/delete), and can be exported/imported as
JSON files. Built-in defaults are seeded on first load.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger("browser-helper.fingerprint-database")


# ── Data types ──────────────────────────────────────────────────────────


@dataclass(init=False)
class FingerprintTemplate:
    """A single browser fingerprint template."""

    name: str
    browser: str
    signals: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        name: str,
        browser: str,
        signals: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Construct a fingerprint template.

        ``signals`` and ``config`` default to empty dicts. ``metadata``
        defaults to an empty dict for minimal constructions (name + browser
        only); when ``signals`` or ``config`` are provided, sensible metadata
        defaults (version, created_at, description) are generated instead.
        """
        self.name = name
        self.browser = browser
        self.signals = dict(signals) if signals is not None else {}
        self.config = dict(config) if config is not None else {}
        if metadata is not None:
            self.metadata = dict(metadata)
        elif signals is not None or config is not None:
            self.metadata = {
                "version": 1,
                "created_at": time.time(),
                "description": "",
            }
        else:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "name": self.name,
            "browser": self.browser,
            "signals": dict(self.signals),
            "config": dict(self.config),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FingerprintTemplate:
        """Deserialize from a dict loaded from JSON."""
        return cls(
            name=data.get("name", ""),
            browser=data.get("browser", "unknown"),
            signals=data.get("signals", {}),
            config=data.get("config", {}),
            metadata=data.get("metadata", {
                "version": 1,
                "created_at": time.time(),
                "description": "",
            }),
        )


# ── Database ────────────────────────────────────────────────────────────


class FingerprintDatabase:
    """JSON-backed database of browser fingerprint templates.

    Provides CRUD for templates (Chrome, Firefox, Safari, Edge),
    random generation, persistence to JSON files, and import/export.
    """

    DEFAULT_TEMPLATES: ClassVar[dict[str, dict[str, Any]]] = {
        "chrome-120": {
            "name": "chrome-120",
            "browser": "chrome",
            "metadata": {"version": 1, "created_at": 0.0, "description": "Chrome 120 on Windows 10"},
            "signals": {
                "canvas": {"noise_enabled": True, "noise_seed": 42},
                "webgl": {"vendor": "Google Inc. (NVIDIA)", "renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)"},
                "audio": {"sample_rate": 48000, "noise_enabled": True},
                "navigator": {"platform": "Win32", "hardwareConcurrency": 8, "deviceMemory": 8},
                "screen": {"width": 1920, "height": 1080, "colorDepth": 24},
                "timezone": "America/New_York",
                "locale": "en-US,en;q=0.9",
            },
            "config": {
                "canvas_noise_seed": 42,
                "webgl_vendor": "Google Inc. (NVIDIA)",
                "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
                "audio_noise_enabled": True,
                "geolocation": {"lat": 40.7128, "lng": -74.0060},
                "timezone": "America/New_York",
                "locale": "en-US",
            },
        },
        "firefox-linux": {
            "name": "firefox-linux",
            "browser": "firefox",
            "metadata": {"version": 1, "created_at": 0.0, "description": "Firefox 121 on Ubuntu 22.04"},
            "signals": {
                "canvas": {"noise_enabled": True, "noise_seed": 7},
                "webgl": {"vendor": "Mozilla Inc.", "renderer": "Mesa/X.org Gallium 0.4 on AMD Radeon"},
                "audio": {"sample_rate": 44100, "noise_enabled": True},
                "navigator": {"platform": "Linux x86_64", "hardwareConcurrency": 4, "deviceMemory": 4},
                "screen": {"width": 1920, "height": 1080, "colorDepth": 24},
                "timezone": "Europe/London",
                "locale": "en-GB,en;q=0.5",
            },
            "config": {
                "canvas_noise_seed": 7,
                "webgl_vendor": "Mozilla Inc.",
                "webgl_renderer": "Mesa/X.org Gallium 0.4 on AMD Radeon",
                "audio_noise_enabled": True,
                "geolocation": {"lat": 51.5074, "lng": -0.1278},
                "timezone": "Europe/London",
                "locale": "en-GB",
            },
        },
        "safari-ios": {
            "name": "safari-ios",
            "browser": "safari",
            "metadata": {"version": 1, "created_at": 0.0, "description": "Safari 17.2 on iOS 17.2"},
            "signals": {
                "canvas": {"noise_enabled": False, "noise_seed": 0},
                "webgl": {"vendor": "Apple Inc.", "renderer": "Apple GPU"},
                "audio": {"sample_rate": 48000, "noise_enabled": False},
                "navigator": {"platform": "iPhone", "hardwareConcurrency": 6, "deviceMemory": 6},
                "screen": {"width": 390, "height": 844, "colorDepth": 24},
                "timezone": "America/Los_Angeles",
                "locale": "en-US",
            },
            "config": {
                "canvas_noise_seed": 0,
                "webgl_vendor": "Apple Inc.",
                "webgl_renderer": "Apple GPU",
                "audio_noise_enabled": False,
                "geolocation": {"lat": 37.7749, "lng": -122.4194},
                "timezone": "America/Los_Angeles",
                "locale": "en-US",
            },
        },
        "edge-windows": {
            "name": "edge-windows",
            "browser": "edge",
            "metadata": {"version": 1, "created_at": 0.0, "description": "Edge 120 on Windows 11"},
            "signals": {
                "canvas": {"noise_enabled": True, "noise_seed": 99},
                "webgl": {"vendor": "Google Inc. (Microsoft)", "renderer": "ANGLE (Microsoft, Microsoft Basic Render Driver)"},
                "audio": {"sample_rate": 48000, "noise_enabled": True},
                "navigator": {"platform": "Win32", "hardwareConcurrency": 16, "deviceMemory": 16},
                "screen": {"width": 2560, "height": 1440, "colorDepth": 24},
                "timezone": "America/Chicago",
                "locale": "en-US,en;q=0.9",
            },
            "config": {
                "canvas_noise_seed": 99,
                "webgl_vendor": "Google Inc. (Microsoft)",
                "webgl_renderer": "ANGLE (Microsoft, Microsoft Basic Render Driver)",
                "audio_noise_enabled": True,
                "geolocation": {"lat": 41.8781, "lng": -87.6298},
                "timezone": "America/Chicago",
                "locale": "en-US",
            },
        },
    }

    def __init__(self, storage_dir: str | None = None):
        self._storage_dir = Path(storage_dir) if storage_dir else Path.home() / ".browser-helper" / "fingerprints"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._templates: dict[str, FingerprintTemplate] = {}
        # Load persisted templates first — both explicit and default-dir
        # instances must persist across restarts (review R1).  Test isolation
        # belongs in tests (tmp dirs / HOME), NOT in production behaviour.
        self.load()
        # Seed per-name defaults for any names still missing from disk.
        # Per-name seeding is safe after a load() — it only fills gaps.
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Seed default templates for names not already present.

        Seeding is per-name (not gated on the storage dir being empty) so a
        default-dir instance keeps its shipped defaults even when stale JSON
        files exist from earlier API runs (review H1).
        """
        for name, data in self.DEFAULT_TEMPLATES.items():
            if name not in self._templates:
                self._templates[name] = FingerprintTemplate(**data)

    # ── CRUD ─────────────────────────────────────────────────────────

    def list_templates(self) -> list[dict[str, Any]]:
        """Return [{name, browser, metadata}, ...] for all templates."""
        return [
            {"name": t.name, "browser": t.browser, "metadata": t.metadata}
            for t in self._templates.values()
        ]

    def get_template(self, name: str) -> FingerprintTemplate | None:
        """Return template by name, or None if not found."""
        return self._templates.get(name)

    def add_template(self, template: FingerprintTemplate) -> None:
        """Add a template to the in-memory store."""
        self._templates[template.name] = template

    def update_template(self, name: str, updates: dict[str, Any]) -> bool:
        """Update a template's fields in place. Returns True if updated."""
        if name not in self._templates:
            return False
        tpl = self._templates[name]
        for key, value in updates.items():
            if hasattr(tpl, key):
                setattr(tpl, key, value)
        return True

    def delete_template(self, name: str) -> bool:
        """Remove a template. Returns True if deleted."""
        if name not in self._templates:
            return False
        del self._templates[name]
        return True

    # ── Generation ─────────────────────────────────────────────────

    def generate_template(self, browser: str) -> FingerprintTemplate:
        """Generate a plausible random template for the given browser.

        Uses the GPU pool from fingerprint_engine and creates randomized
        but realistic signal values for the given browser type.
        """
        import random as _random

        from fingerprint_engine import _pick_gpu

        rng = _random.Random()
        gpu_vendor, gpu_renderer = _pick_gpu(rng)

        # Browser-specific defaults
        browser_lower = browser.lower().strip()
        if browser_lower in ("chrome", "chromium"):
            platform = "Win32"
            hw_concurrency = rng.choice([4, 8, 16])
            device_memory = rng.choice([4, 8])
            screen_w, screen_h = rng.choice([(1920, 1080), (2560, 1440), (1366, 768)])
            timezone = "America/New_York"
            locale = "en-US,en;q=0.9"
            audio_rate = 48000
            browser_name = browser
        elif browser_lower == "firefox":
            platform = "Linux x86_64"
            hw_concurrency = rng.choice([4, 8])
            device_memory = 4
            screen_w, screen_h = rng.choice([(1920, 1080), (1440, 900)])
            timezone = "Europe/London"
            locale = "en-GB,en;q=0.5"
            audio_rate = 44100
            browser_name = "firefox"
        elif browser_lower == "safari":
            platform = "iPhone"
            hw_concurrency = rng.choice([4, 6])
            device_memory = rng.choice([4, 6])
            screen_w, screen_h = rng.choice([(390, 844), (430, 932)])
            timezone = "America/Los_Angeles"
            locale = "en-US"
            audio_rate = 48000
            browser_name = "safari"
        elif browser_lower == "edge":
            platform = "Win32"
            hw_concurrency = rng.choice([8, 16])
            device_memory = rng.choice([8, 16])
            screen_w, screen_h = rng.choice([(1920, 1080), (2560, 1440)])
            timezone = "America/Chicago"
            locale = "en-US,en;q=0.9"
            audio_rate = 48000
            browser_name = "edge"
        else:
            raise ValueError(f"Unknown browser type: {browser}")

        now = time.time()
        # Unique suffix guards against two generations within the same second
        # overwriting each other in the store (review M1).
        name = f"{browser_name}-{int(now)}-{uuid.uuid4().hex[:6]}"

        return FingerprintTemplate(
            name=name,
            browser=browser_name,
            metadata={
                "version": 1,
                "created_at": now,
                "description": f"Generated {browser_name} template",
            },
            signals={
                "canvas": {"noise_enabled": True, "noise_seed": rng.randint(1, 999)},
                "webgl": {"vendor": gpu_vendor, "renderer": gpu_renderer},
                "audio": {"sample_rate": audio_rate, "noise_enabled": True},
                "navigator": {
                    "platform": platform,
                    "hardwareConcurrency": hw_concurrency,
                    "deviceMemory": device_memory,
                },
                "screen": {"width": screen_w, "height": screen_h, "colorDepth": 24},
                "timezone": timezone,
                "locale": locale,
            },
            config={
                "canvas_noise_seed": rng.randint(1, 999),
                "webgl_vendor": gpu_vendor,
                "webgl_renderer": gpu_renderer,
                "audio_noise_enabled": True,
                "geolocation": {"lat": 0.0, "lng": 0.0},
                "timezone": timezone,
                "locale": locale.split(",")[0] if "," in locale else locale,
            },
        )

    # ── Persistence ─────────────────────────────────────────────────

    def save(self) -> None:
        """Persist all templates to JSON files (one per template)."""
        for name, tpl in self._templates.items():
            file_path = self._storage_dir / f"{name}.json"
            data = {
                "name": tpl.name,
                "browser": tpl.browser,
                "metadata": tpl.metadata,
                "signals": tpl.signals,
                "config": tpl.config,
            }
            file_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def load(self) -> None:
        """Load templates from JSON files in storage_dir."""
        if not self._storage_dir.exists():
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            return
        loaded = 0
        for file_path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                tpl = FingerprintTemplate(
                    name=data.get("name", file_path.stem),
                    browser=data.get("browser", "unknown"),
                    signals=data.get("signals", {}),
                    config=data.get("config", {}),
                    metadata=data.get("metadata", {
                        "version": 1,
                        "created_at": time.time(),
                        "description": "",
                    }),
                )
                self._templates[tpl.name] = tpl
                loaded += 1
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Corrupted fingerprint file %s: %s", file_path, exc)
        # If nothing was loaded from disk, seed defaults
        if loaded == 0 and not self._templates:
            self._load_defaults()

    # ── Import/Export ───────────────────────────────────────────────

    def export_template(self, name: str, path: str) -> None:
        """Export a single template to a JSON file."""
        # Check in-memory templates first, then fall back to DEFAULT_TEMPLATES
        tpl = self._templates.get(name)
        if tpl is None and name in self.DEFAULT_TEMPLATES:
            # Re-create from defaults if deleted from in-memory state
            data = self.DEFAULT_TEMPLATES[name]
            tpl = FingerprintTemplate(
                name=data["name"],
                browser=data["browser"],
                signals=data.get("signals", {}),
                config=data.get("config", {}),
                metadata=data.get("metadata", {"version": 1, "created_at": 0.0, "description": ""}),
            )
        if tpl is None:
            raise KeyError(f"Template not found: {name}")
        data = {
            "name": tpl.name,
            "browser": tpl.browser,
            "metadata": tpl.metadata,
            "signals": tpl.signals,
            "config": tpl.config,
        }
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def import_template(self, path: str) -> str:
        """Import a template from a JSON file and add to database.

        Returns the template name.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Import file not found: {path}")
        raw = file_path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in import file: {exc}") from exc
        tpl = FingerprintTemplate(
            name=data.get("name", file_path.stem),
            browser=data.get("browser", "unknown"),
            signals=data.get("signals", {}),
            config=data.get("config", {}),
            metadata=data.get("metadata", {
                "version": 1,
                "created_at": time.time(),
                "description": "",
            }),
        )
        self._templates[tpl.name] = tpl
        return tpl.name


# Module-level alias for the default template table.
# The test suite imports DEFAULT_TEMPLATES directly from this module.
DEFAULT_TEMPLATES: dict[str, dict[str, Any]] = FingerprintDatabase.DEFAULT_TEMPLATES

__all__ = [
    "DEFAULT_TEMPLATES",
    "FingerprintDatabase",
    "FingerprintTemplate",
]
