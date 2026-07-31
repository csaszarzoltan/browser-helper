"""
AntiDetectCompositor — facade that composes complete anti-detection profiles (P1.2).

Stub — all behavioral methods raise NotImplementedError.
Interface definitions (dataclasses, types) are available for import.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("browser-helper.compositor")


# ── Data types ──────────────────────────────────────────────────────────


@dataclass
class AntiDetectProfileBundle:
    """Complete anti-detection profile specification."""

    name: str
    fingerprint_template: str
    fingerprint_config: dict[str, Any] = field(default_factory=dict)
    proxy_strategy: str = "round-robin"
    proxy_group: str | None = None
    stealth_level: str = "medium"
    session_ttl: float = 3600.0
    version: int = 1
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "name": self.name,
            "fingerprint_template": self.fingerprint_template,
            "fingerprint_config": dict(self.fingerprint_config),
            "proxy_strategy": self.proxy_strategy,
            "proxy_group": self.proxy_group,
            "stealth_level": self.stealth_level,
            "session_ttl": self.session_ttl,
            "version": self.version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AntiDetectProfileBundle:
        """Deserialize from a dict loaded from JSON."""
        return cls(
            name=data["name"],
            fingerprint_template=data.get("fingerprint_template", ""),
            fingerprint_config=data.get("fingerprint_config", {}),
            proxy_strategy=data.get("proxy_strategy", "round-robin"),
            proxy_group=data.get("proxy_group"),
            stealth_level=data.get("stealth_level", "medium"),
            session_ttl=data.get("session_ttl", 3600.0),
            version=data.get("version", 1),
            created_at=data.get("created_at", time.time()),
        )


# ── Compositor ──────────────────────────────────────────────────────────


class AntiDetectCompositor:
    """Facade that composes a complete anti-detection profile bundle.

    Aggregates FingerprintDatabase, ProxyRotationManager, StealthInjector,
    and optionally SessionManager into a single unified profile.
    """

    def __init__(
        self,
        fingerprint_db: Any,
        proxy_mgr: Any,
        stealth: Any,
        session_mgr: Any | None = None,
    ):
        self._fingerprint_db = fingerprint_db
        self._proxy_mgr = proxy_mgr
        self._stealth = stealth
        self._session_mgr = session_mgr

    # ── Composition ──────────────────────────────────────────────────

    def compose(self, bundle: AntiDetectProfileBundle) -> dict[str, Any]:
        """Compose a full anti-detection profile.

        Returns a dict with:
          - fingerprint: FingerprintConfig dict + JS patches
          - proxy: ProxyEntry dict or strategy
          - stealth: Level name + patch list
          - session: Session config
          - combined: All JS scripts concatenated for single-shot injection
        """
        fingerprint = self.resolve_fingerprint(bundle.fingerprint_template, bundle.fingerprint_config)
        stealth_patches = self.resolve_stealth_patches(bundle.stealth_level)
        proxy = self._proxy_mgr.get_proxy(strategy=bundle.proxy_strategy) or {
            "strategy": bundle.proxy_strategy,
        }

        combined_js: list[str] = []
        # Add fingerprint JS patches
        combined_js.extend(fingerprint.get("js_patches", []))
        # Add stealth JS patches
        combined_js.extend(stealth_patches.get("patches", {}).values())

        return {
            "fingerprint": fingerprint,
            "proxy": proxy,
            "stealth": stealth_patches,
            "session": {"ttl": bundle.session_ttl},
            "combined_js": combined_js,
        }

    async def test(self, bundle: AntiDetectProfileBundle, cdp_client) -> dict[str, Any]:
        """Launch a quick detection test using the composed profile.

        Returns test results with pass/fail per site.
        """
        from detection_tester import DetectionTester

        tester = DetectionTester()
        results = await tester.run_all(cdp_client, timeout_per_site=30)
        return {"results": [{"site": r.site, "passed": r.passed, "details": r.details} for r in results]}

    # ── Serialization ────────────────────────────────────────────────

    def export_bundle(self, bundle: AntiDetectProfileBundle, path: str) -> None:
        """Serialize bundle to JSON file."""
        data = bundle.to_dict()
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def import_bundle(self, path: str) -> AntiDetectProfileBundle:
        """Deserialize bundle from JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Bundle file not found: {path}")
        raw = file_path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in bundle file: {exc}") from exc
        return AntiDetectProfileBundle.from_dict(data)

    # ── Profile resolution ───────────────────────────────────────────

    def resolve_fingerprint(
        self, template_name: str, overrides: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Load a FingerprintTemplate and produce fingerprint config + JS patches.

        Returns:
            {"config": {...}, "js_patches": [...], "gpu": {"vendor": ..., "renderer": ...}}
        """
        from anti_detection.fingerprint_database import FingerprintTemplate

        raw = self._fingerprint_db.get_template(template_name)
        if raw is None:
            # Fall back to DEFAULT_TEMPLATES — this handles the case where a
            # template was deleted from the in-memory store (e.g. via the API
            # DELETE endpoint) but the shipped default should still be usable.
            defaults = getattr(self._fingerprint_db, "DEFAULT_TEMPLATES", {})
            default_data = defaults.get(template_name)
            if default_data is None:
                raise KeyError(f"Fingerprint template not found: {template_name}")
            # Re-seed the database so subsequent lookups on the same instance work
            try:
                self._fingerprint_db.add_template(FingerprintTemplate(**default_data))
            except Exception:  # noqa: BLE001, S110 — best-effort re-seed, fall back to defaults
                pass
            raw = default_data

        # Handle FingerprintTemplate dataclass vs dict (from mock)
        if isinstance(raw, FingerprintTemplate):
            signals = dict(raw.signals) if raw.signals else {}
            config_data = dict(raw.config) if raw.config else {}
            tpl_name = raw.name
        elif isinstance(raw, dict):
            signals = raw.get("signals", {}) if isinstance(raw.get("signals"), dict) else {}
            config_data = raw.get("config", {}) if isinstance(raw.get("config"), dict) else {}
            tpl_name = raw.get("name", "")
        else:
            signals = {}
            config_data = {}
            tpl_name = ""

        # Verify template name matches (important for mock tests where
        # the mock returns the same template for any name)
        if tpl_name and tpl_name != template_name:
            raise KeyError(f"Fingerprint template not found: {template_name}")

        # Apply overrides
        config = dict(config_data)
        if overrides:
            config.update(overrides)

        # Build JS patches from signals
        js_patches: list[str] = []
        canvas = signals.get("canvas", {})
        webgl = signals.get("webgl", {})

        if canvas.get("noise_enabled", False):
            seed = canvas.get("noise_seed", 0)
            js_patches.append(
                f"(function(){{"
                f"const _origGetImageData=HTMLCanvasElement.prototype.getImageData;"
                f"HTMLCanvasElement.prototype.getImageData=function(x,y,w,h){{"
                f"const img=_origGetImageData.call(this,x,y,w,h);"
                f"for(let i=0;i<img.data.length;i+=4){{img.data[i]^={seed};}}"
                f"return img;}})();"
            )

        gpu_info = {
            "vendor": webgl.get("vendor", "Unknown"),
            "renderer": webgl.get("renderer", "Unknown"),
        }

        return {
            "config": config,
            "js_patches": js_patches,
            "gpu": gpu_info,
        }

    def resolve_stealth_patches(self, level: str) -> dict[str, Any]:
        """Resolve StealthInjector patches for the given level.

        Returns:
            {"level": str, "patches": {name: js_source}, "count": int}
        """
        from stealth_injector import LEVEL_PATCHES, _make_patches

        if level not in LEVEL_PATCHES:
            raise ValueError(f"Unknown stealth level: {level!r}")

        patch_names = LEVEL_PATCHES[level]
        # Use _make_patches to get all real patch sources (works with mocks too)
        all_patches = _make_patches()
        patches = {}
        for name in patch_names:
            js = all_patches.get(name)
            if js:
                patches[name] = js

        return {
            "level": level,
            "patches": patches,
            "count": len(patches),
        }


__all__ = [
    "AntiDetectCompositor",
    "AntiDetectProfileBundle",
]
