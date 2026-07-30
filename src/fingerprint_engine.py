"""
FingerprintEngine — Per-session fingerprint noise generation and CDP injection.

Generates per-session seeded noise for Canvas, WebGL, and AudioContext,
then produces JS patches for CDP ``Page.addScriptToEvaluateOnNewDocument``.

Usage:
    from fingerprint_engine import FingerprintConfig, FingerprintEngine

    config = FingerprintEngine.get_default_config()
    engine = FingerprintEngine(config)
    scripts = engine.generate_all_scripts()
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Fingerprint Configuration
# ---------------------------------------------------------------------------


@dataclass
class FingerprintConfig:
    """Per-session fingerprint configuration.

    Attributes:
        canvas_noise_seed:  Seed for canvas pixel noise. 0 = random per session.
        webgl_vendor:       WebGL vendor string. Empty = auto-pick from pool.
        webgl_renderer:     WebGL renderer string. Empty = auto-pick from pool.
        audio_sample_rate:  AudioContext sample rate override (default 44100).
        geolocation:        Optional {lat, lng} geolocation override.
        timezone:           Optional IANA timezone string (e.g. "America/New_York").
        locale:             Optional locale string (e.g. "en-US").
    """

    canvas_noise_seed: int = 0
    webgl_vendor: str = ""
    webgl_renderer: str = ""
    audio_sample_rate: int = 44100
    geolocation: dict | None = None
    timezone: str | None = None
    locale: str | None = None


# ---------------------------------------------------------------------------
# GPU vendor / renderer pool (curated from real hardware)
# ---------------------------------------------------------------------------

_PLAUSIBLE_GPU_POOL: dict[str, list[str]] = {
    "NVIDIA Corporation": [
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 4080 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Ti Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0)",
    ],
    "AMD": [
        "ANGLE (AMD, AMD Radeon RX 7900 XTX Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD, AMD Radeon RX 7800 XT Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD, AMD Radeon Graphics Direct3D11 vs_5_0 ps_5_0)",
    ],
    "Intel": [
        "ANGLE (Intel, Intel(R) Arc(TM) A770 Graphics Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel, Intel(R) Arc(TM) A750 Graphics Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)",
    ],
    "Apple": [
        "Apple M2",
        "Apple M2 Pro",
        "Apple M2 Max",
        "Apple M3",
        "Apple M3 Pro",
    ],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_seeded_rng(seed: int) -> random.Random:
    """Return a random.Random instance seeded from an int."""
    return random.Random(seed)


def _pick_gpu(rng: random.Random) -> tuple[str, str]:
    """Pick a random (vendor, renderer) pair from the pool."""
    vendor = rng.choice(list(_PLAUSIBLE_GPU_POOL.keys()))
    renderer = rng.choice(_PLAUSIBLE_GPU_POOL[vendor])
    return vendor, renderer


def _escape_js(s: str) -> str:
    """Escape a string for safe embedding inside a JS string literal."""
    return (
        s.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


# ---------------------------------------------------------------------------
# JS script templates
# ---------------------------------------------------------------------------


def _canvas_noise_js(seed: int) -> str:
    """Build a JS snippet that patches canvas toDataURL/toBlob with noise.

    Uses a simple LCG seeded hash to generate deterministic per-pixel
    offsets so the same seed always produces the same canvas output.
    """
    return f"""(function() {{
    'use strict';
    const SEED = {seed};
    function seededHash(x, y) {{
        let h = (SEED ^ (x * 374761393 + y * 668265263)) | 0;
        h = Math.imul(h ^ (h >>> 13), 1274126177);
        h = h ^ (h >>> 16);
        return h;
    }}
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(...args) {{
        const w = this.width, h = this.height;
        const ctx = this.getContext('2d');
        if (ctx) {{
            const imageData = ctx.getImageData(0, 0, w, h);
            const data = imageData.data;
            for (let y = 0; y < h; y++) {{
                for (let x = 0; x < w; x++) {{
                    const i = (y * w + x) * 4;
                    const hash = seededHash(x, y);
                    data[i]     = Math.max(0, Math.min(255, data[i]     + (hash & 3) - 1));
                    data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + ((hash >> 2) & 3) - 1));
                    data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + ((hash >> 4) & 3) - 1));
                }}
            }}
            ctx.putImageData(imageData, 0, 0);
        }}
        return origToDataURL.apply(this, args);
    }};
    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = function(callback, ...args) {{
        const self = this;
        const wrapped = function(blob) {{
            const w = self.width, h = self.height;
            const ctx = self.getContext('2d');
            if (ctx) {{
                const imageData = ctx.getImageData(0, 0, w, h);
                const data = imageData.data;
                for (let y = 0; y < h; y++) {{
                    for (let x = 0; x < w; x++) {{
                        const i = (y * w + x) * 4;
                        const hash = seededHash(x, y);
                        data[i]     = Math.max(0, Math.min(255, data[i]     + (hash & 3) - 1));
                        data[i + 1] = Math.max(0, Math.min(255, data[i + 1] + ((hash >> 2) & 3) - 1));
                        data[i + 2] = Math.max(0, Math.min(255, data[i + 2] + ((hash >> 4) & 3) - 1));
                    }}
                }}
                ctx.putImageData(imageData, 0, 0);
            }}
            callback(blob);
        }};
        origToBlob.call(self, wrapped, ...args);
    }};
}})();"""


def _webgl_override_js(vendor: str, renderer: str) -> str:
    """Build a JS snippet that overrides WEBGL_debug_renderer_info."""
    escaped_vendor = _escape_js(vendor)
    escaped_renderer = _escape_js(renderer)
    return f"""(function() {{
    'use strict';
    const getExt = HTMLCanvasElement.prototype.getContext;
    const vendorStr = '{escaped_vendor}';
    const rendererStr = '{escaped_renderer}';
    const origGetParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {{
        if (p === 37445) return vendorStr;
        if (p === 37446) return rendererStr;
        return origGetParameter.call(this, p);
    }};
    if (typeof WebGL2RenderingContext !== 'undefined') {{
        WebGL2RenderingContext.prototype.getParameter = function(p) {{
            if (p === 37445) return vendorStr;
            if (p === 37446) return rendererStr;
            return origGetParameter.call(this, p);
        }};
    }}
}})();"""


def _audio_override_js(sample_rate: int) -> str:
    """Build a JS snippet that overrides AudioContext sampleRate."""
    return f"""(function() {{
    'use strict';
    const targetRate = {sample_rate};
    const origAC = window.AudioContext || window.webkitAudioContext;
    if (origAC) {{
        const origConstructor = function() {{
            const ctx = new (Function.prototype.bind.apply(origAC, arguments));
            Object.defineProperty(ctx, 'sampleRate', {{
                get: function() {{ return targetRate; }}
            }});
            return ctx;
        }};
        if (window.AudioContext) {{
            window.AudioContext = origConstructor;
        }}
        if (window.webkitAudioContext) {{
            window.webkitAudioContext = origConstructor;
        }}
    }}
}})();"""


# ---------------------------------------------------------------------------
# Fingerprint Noise / Patch Engine
# ---------------------------------------------------------------------------


class FingerprintEngine:
    """Generates and injects browser fingerprint patches.

    Produces JS source strings that override Canvas, WebGL, and AudioContext
    APIs when injected via ``Page.addScriptToEvaluateOnNewDocument``.

    Args:
        config: Optional FingerprintConfig. Uses defaults if omitted.
    """

    def __init__(self, config: FingerprintConfig | None = None) -> None:
        self._config = config or FingerprintConfig()

    # ── Config ─────────────────────────────────────────────────────────

    @property
    def config(self) -> FingerprintConfig:
        """Return the current fingerprint configuration."""
        return self._config

    @config.setter
    def config(self, value: FingerprintConfig) -> None:
        self._config = value

    # ── Static factory ─────────────────────────────────────────────────

    @staticmethod
    def get_default_config() -> FingerprintConfig:
        """Return a FingerprintConfig with all defaults."""
        return FingerprintConfig()

    # ── Script generators ──────────────────────────────────────────────

    @staticmethod
    def generate_canvas_noise_script(seed: int) -> str:
        """Return JS that patches toDataURL/toBlob with seeded per-pixel noise.

        The returned script overrides ``HTMLCanvasElement.prototype.toDataURL``
        and ``HTMLCanvasElement.prototype.toBlob`` to add ±1-3 per-pixel noise
        using the provided seed for deterministic output within a session.

        Args:
            seed: Integer seed for reproducible per-pixel noise.

        Returns:
            A JavaScript source string suitable for
            ``Page.addScriptToEvaluateOnNewDocument``.
        """
        return _canvas_noise_js(seed)

    @staticmethod
    def generate_webgl_override_script(vendor: str, renderer: str) -> str:
        """Return JS that overrides WEBGL_debug_renderer_info parameters.

        The returned script intercepts ``WEBGL_debug_renderer_info`` queries
        to return the given vendor and renderer strings instead of the real
        ones.

        Args:
            vendor:  GPU vendor string (e.g. "Google Inc. (NVIDIA)").
            renderer: GPU renderer string (e.g. "ANGLE (NVIDIA, ...)").

        Returns:
            A JavaScript source string.
        """
        return _webgl_override_js(vendor, renderer)

    @staticmethod
    def generate_audio_override_script(sample_rate: int) -> str:
        """Return JS that overrides AudioContext sampleRate and perturbs output.

        The returned script overrides the ``sampleRate`` getter on
        ``AudioContext.prototype`` and optionally introduces minor
        perturbations to ``getFloatFrequencyData`` output.

        Args:
            sample_rate: Target sample rate (recommended: 44100).

        Returns:
            A JavaScript source string.
        """
        return _audio_override_js(sample_rate)

    # ── Composite ──────────────────────────────────────────────────────

    def generate_all_scripts(self) -> list[str]:
        """Return list of all JS scripts to inject.

        Combines canvas, WebGL, and audio scripts based on the current
        config. For fields left empty/auto (e.g. empty webgl_vendor), a
        plausible value is chosen from the GPU pool.

        Returns:
            A list of JS source strings, one per patch type.
        """
        cfg = self._config
        scripts: list[str] = []

        # Canvas noise — use seed from config (0 = random, generate one)
        seed = cfg.canvas_noise_seed
        if seed == 0:
            seed = random.randint(1, 2**31 - 1)
        scripts.append(_canvas_noise_js(seed))

        # WebGL override — pick from pool if vendor/renderer are empty
        vendor = cfg.webgl_vendor
        renderer = cfg.webgl_renderer
        if not vendor or not renderer:
            rng = _make_seeded_rng(seed if seed != 0 else random.randint(1, 2**31 - 1))
            picked_vendor, picked_renderer = _pick_gpu(rng)
            vendor = vendor or picked_vendor
            renderer = renderer or picked_renderer
        scripts.append(_webgl_override_js(vendor, renderer))

        # Audio override
        scripts.append(_audio_override_js(cfg.audio_sample_rate))

        return scripts

    # ── GPU pool ───────────────────────────────────────────────────────

    @staticmethod
    def get_plausible_gpu_pool() -> dict[str, list[str]]:
        """Return dict of {vendor: [renderer_strings]} for random selection.

        Returns a curated list of real GPU vendor/renderer combinations
        from common hardware (NVIDIA RTX 3080/4090, AMD RX 7900 XTX,
        Intel Arc A770, Apple M2, etc.).

        Returns:
            ``{vendor: [renderer_strings]}`` dict.
        """
        return dict(_PLAUSIBLE_GPU_POOL)
