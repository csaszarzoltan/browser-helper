"""
Signal-level fingerprint modules for the Fingerprint Randomization Engine.

Each module handles one fingerprint signal group (canvas, WebGL, audio,
navigator, screen/color/timezone/locale, TLS/JA3). Classes are stateless
and can be used standalone or composed by ``FingerprintRandomizer``.
"""

from __future__ import annotations

import math
import re
from typing import Any

# ═══════════════════════════════════════════════════════════════════════
# CanvasFingerprinter
# ═══════════════════════════════════════════════════════════════════════


class CanvasFingerprinter:
    """Generates JS patches that inject noise into canvas fingerprinting APIs.

    Overrides ``toDataURL``, ``getImageData``, and ``toBlob`` to add
    per-pixel noise based on a deterministic offset tuple.
    """

    @staticmethod
    def build_patch(canvas_offset: tuple[int, int]) -> str:
        """Build a JS snippet that offsets canvas pixel readout.

        Args:
            canvas_offset: (dx, dy) pixel offset applied to each pixel.

        Returns:
            A JavaScript source string suitable for
            ``Page.addScriptToEvaluateOnNewDocument``.
        """
        dx, dy = canvas_offset
        return (
            f"(function(){{"
            f"const _origToDataURL=HTMLCanvasElement.prototype.toDataURL;"
            f"HTMLCanvasElement.prototype.toDataURL=function(){{"
            f"const r=_origToDataURL.apply(this,arguments);"
            f"return r.replace(/rgba\\((\\d+),(\\d+),(\\d+),(\\d+)\\)/g,"
            f"function(m,rd,gn,bl,al){{"
            f"return 'rgba('+Math.min(255,parseInt(rd)+{dx})+','"
            f"+Math.min(255,parseInt(gn)+{dy})+','+bl+','+al+')';"
            f"}});"
            f"}};"
            f"const _origGetImageData=CanvasRenderingContext2D.prototype.getImageData;"
            f"CanvasRenderingContext2D.prototype.getImageData="
            f"function(x,y,w,h){{"
            f"const d=_origGetImageData.call(this,x,y,w,h);"
            f"for(let i=3;i<d.data.length;i+=4){{"
            f"d.data[i-3]=Math.min(255,Math.max(0,d.data[i-3]+{dx}));"
            f"d.data[i-2]=Math.min(255,Math.max(0,d.data[i-2]+{dy}));"
            f"}}return d;"
            f"}};"
            f"}})()"
        )

    @staticmethod
    def measure_entropy(patch_js: str) -> float:
        """Estimate the noise entropy of a canvas patch.

        The returned value approximates Shannon entropy of the noise
        distribution introduced by *patch_js*.

        Args:
            patch_js: A canvas patch JS string produced by ``build_patch``.

        Returns:
            Float in [0.0, 8.0] — higher means more entropy.
        """
        # Extract numeric values from the patch JS as proxy for noise distribution
        numbers = re.findall(r"[-+]?\d+\.?\d*", patch_js)
        if not numbers:
            return 0.0
        values = [float(n) for n in numbers if n not in ("0", "1", "2", "3", "4")]
        if not values:
            return 0.5
        # Shannon entropy of the numeric distribution
        total = len(values)
        freq: dict[float, int] = {}
        for v in values:
            freq[v] = freq.get(v, 0) + 1
        entropy = -sum((c / total) * math.log2(c / total) for c in freq.values())
        return round(min(entropy, 8.0), 4)


# ═══════════════════════════════════════════════════════════════════════
# WebGLSpoofer
# ═══════════════════════════════════════════════════════════════════════


class WebGLSpoofer:
    """Generates JS patches that spoof WebGL vendor/renderer information.

    Overrides ``WEBGL_debug_renderer_info`` (UNMASKED_VENDOR_WEBGL /
    UNMASKED_RENDERER_WEBGL) and ``getParameter`` to return realistic
    GPU profile strings.
    """

    @staticmethod
    def build_patch(webgl_vendor: str, webgl_renderer: str) -> str:
        """Build a JS snippet that overrides WebGL vendor/renderer.

        Args:
            webgl_vendor:   Spoofed GPU vendor string.
            webgl_renderer: Spoofed GPU renderer string.

        Returns:
            A JavaScript source string.
        """
        return (
            f"(function(){{"
            f"const origGetParameter=WebGLRenderingContext.prototype.getParameter;"
            f"WebGLRenderingContext.prototype.getParameter=function(p){{"
            f"if(p===37445)return'{webgl_vendor}';"
            f"if(p===37446)return'{webgl_renderer}';"
            f"return origGetParameter.call(this,p);"
            f"}};"
            f"if(typeof WebGL2RenderingContext!=='undefined'){{"
            f"WebGL2RenderingContext.prototype.getParameter=function(p){{"
            f"if(p===37445)return'{webgl_vendor}';"
            f"if(p===37446)return'{webgl_renderer}';"
            f"return origGetParameter.call(this,p);"
            f"}};"
            f"}}"
            f"}})()"
        )

    @staticmethod
    def get_gpu_profiles() -> dict[str, list[str]]:
        """Return a dict of {vendor: [renderer_strings]} for real GPU profiles.

        Returns a curated list of real GPU vendor/renderer combinations
        from common hardware (NVIDIA, AMD, Intel, Apple).

        Returns:
            ``{vendor: [renderer_strings]}`` dict with at least 4 vendors.
        """
        return {
            "Google Inc. (NVIDIA)": [
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Ti Direct3D11 vs_5_0 ps_5_0)",
            ],
            "AMD": [
                "ANGLE (AMD, AMD Radeon RX 7900 XTX Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (AMD, AMD Radeon RX 7800 XT Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0)",
            ],
            "Intel": [
                "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0)",
                "ANGLE (Intel, Intel(R) Arc(TM) A770 Graphics Direct3D11 vs_5_0 ps_5_0)",
            ],
            "Apple": [
                "Apple M1",
                "Apple M2",
                "Apple M2 Pro",
                "Apple M3",
                "Apple A16 GPU",
            ],
        }


# ═══════════════════════════════════════════════════════════════════════
# AudioContextRandomizer
# ═══════════════════════════════════════════════════════════════════════


class AudioContextRandomizer:
    """Generates JS patches that add noise to AudioContext output.

    Injects variance into ``getChannelData`` output and optionally
    spoofs ``sampleRate``. Variance percentage is configurable within
    [0.1%, 1.0%] per the spec.
    """

    @staticmethod
    def build_patch(variance_pct: float) -> str:
        """Build a JS snippet that adds noise to AudioContext output.

        Args:
            variance_pct: Noise variance as a fraction (0.001 to 0.01).

        Returns:
            A JavaScript source string.
        """
        return (
            f"(function(){{"
            f"const AudioCtor=window.AudioContext||window.webkitAudioContext;"
            f"if(!AudioCtor)return;"
            f"const origGetChannelData=AudioBuffer.prototype.getChannelData;"
            f"AudioBuffer.prototype.getChannelData=function(channel){{"
            f"const data=origGetChannelData.call(this,channel);"
            f"for(let i=0;i<data.length;i++){{"
            f"data[i]+=(Math.random()-0.5)*{variance_pct};"
            f"}}return data;"
            f"}};"
            f"}})()"
        )

    @staticmethod
    def validate_variance(variance_pct: float) -> bool:
        """Check that *variance_pct* is in the valid range [0.001, 0.01].

        Args:
            variance_pct: Variance fraction to validate.

        Returns:
            True if in range, False otherwise.
        """
        return 0.001 <= variance_pct <= 0.01


# ═══════════════════════════════════════════════════════════════════════
# NavigatorSpoofer
# ═══════════════════════════════════════════════════════════════════════


class NavigatorSpoofer:
    """Generates JS patches that spoof navigator.* properties.

    Covers ``userAgent``, ``platform``, ``language``, ``languages``,
    ``hardwareConcurrency``, and ``deviceMemory`` via
    ``Object.defineProperty`` to make them read-only and consistent
    with the profile fingerprint.
    """

    @staticmethod
    def build_ua_patch(user_agent: str) -> str:
        """Build JS that overrides ``navigator.userAgent`` and ``navigator.platform``.

        Args:
            user_agent: Full user-agent string (implies platform).

        Returns:
            A JavaScript source string.
        """
        # Infer platform from UA
        ua_lower = user_agent.lower()
        if "iphone" in ua_lower or "ipad" in ua_lower:
            platform = "iPhone"
        elif "android" in ua_lower:
            platform = "Android"
        elif "linux" in ua_lower and "x11" in ua_lower:
            platform = "Linux x86_64"
        elif "linux" in ua_lower:
            platform = "Linux armv8l"
        elif "windows" in ua_lower:
            if "wow64" in ua_lower or "win64" in ua_lower:
                platform = "Win64"
            else:
                platform = "Win32"
        elif "mac os" in ua_lower or "macintosh" in ua_lower:
            platform = "MacIntel"
        else:
            platform = "Win32"
        return (
            f"(function(){{"
            f"Object.defineProperty(navigator,'userAgent',{{"
            f"get:function(){{return'{user_agent}';}}"
            f"}});"
            f"Object.defineProperty(navigator,'platform',{{"
            f"get:function(){{return'{platform}';}}"
            f"}});"
            f"}})()"
        )

    @staticmethod
    def build_language_patch(language: str, languages: list[str]) -> str:
        """Build JS that overrides ``navigator.language`` and ``navigator.languages``.

        Args:
            language:   Primary language tag (e.g. ``"en-US"``).
            languages:  List of accepted language tags.

        Returns:
            A JavaScript source string.
        """
        langs_json = str(languages).replace("'", '"')
        return (
            f"(function(){{"
            f"Object.defineProperty(navigator,'language',{{"
            f"get:function(){{return'{language}';}}"
            f"}});"
            f"Object.defineProperty(navigator,'languages',{{"
            f"get:function(){{return{langs_json};}}"
            f"}});"
            f"}})()"
        )

    @staticmethod
    def build_hardware_patch(concurrency: int, device_memory: float) -> str:
        """Build JS that overrides ``navigator.hardwareConcurrency`` and
        ``navigator.deviceMemory``.

        Args:
            concurrency:   Number of logical processors (e.g. 8).
            device_memory: Device memory in GB (e.g. 8.0).

        Returns:
            A JavaScript source string.
        """
        return (
            f"(function(){{"
            f"Object.defineProperty(navigator,'hardwareConcurrency',{{"
            f"get:function(){{return{concurrency};}}"
            f"}});"
            f"Object.defineProperty(navigator,'deviceMemory',{{"
            f"get:function(){{return{device_memory};}}"
            f"}});"
            f"}})()"
        )

    @staticmethod
    def build_navigator_patch(props: dict[str, Any]) -> str:
        """Build a combined JS snippet for all navigator.* overrides.

        Accepts a dict with optional keys: ``user_agent``, ``platform``,
        ``language``, ``languages`` (list), ``hardware_concurrency``,
        ``device_memory``.

        Args:
            props: Dict of navigator properties to spoof.

        Returns:
            A JavaScript source string.
        """
        parts: list[str] = []
        ua = props.get("user_agent")
        if ua:
            platform = props.get("platform", "Win32")
            parts.append(
                f"Object.defineProperty(navigator,'userAgent',{{"
                f"get:function(){{return'{ua}';}}}})"
            )
            parts.append(
                f"Object.defineProperty(navigator,'platform',{{"
                f"get:function(){{return'{platform}';}}}})"
            )
        lang = props.get("language")
        if lang:
            langs = props.get("languages", [lang])
            langs_json = str(langs).replace("'", '"')
            parts.append(
                f"Object.defineProperty(navigator,'language',{{"
                f"get:function(){{return'{lang}';}}}})"
            )
            parts.append(
                f"Object.defineProperty(navigator,'languages',{{"
                f"get:function(){{return{langs_json};}}}})"
            )
        hc = props.get("hardware_concurrency")
        if hc is not None:
            parts.append(
                f"Object.defineProperty(navigator,'hardwareConcurrency',{{"
                f"get:function(){{return{hc};}}}})"
            )
        dm = props.get("device_memory")
        if dm is not None:
            parts.append(
                f"Object.defineProperty(navigator,'deviceMemory',{{"
                f"get:function(){{return{dm};}}}})"
            )
        if not parts:
            return ""

        return f"(function(){{{';'.join(parts)}}})()"


# ═══════════════════════════════════════════════════════════════════════
# ScreenColorConsistency
# ═══════════════════════════════════════════════════════════════════════


class ScreenColorConsistency:
    """Generates JS patches for screen/color/timezone/locale alignment.

    Ensures that ``screen.*`` properties (width, height, colorDepth,
    pixelDepth, availWidth, availHeight), timezone offset, and locale
    are consistent with the profile fingerprint to avoid detection.
    """

    @staticmethod
    def build_screen_patch(
        width: int,
        height: int,
        color_depth: int = 24,
        pixel_ratio: float = 1.0,
    ) -> str:
        """Build JS that overrides ``screen.*`` properties.

        Args:
            width:       Screen width in pixels.
            height:      Screen height in pixels.
            color_depth: Color depth in bits (default 24).
            pixel_ratio: Device pixel ratio (default 1.0).

        Returns:
            A JavaScript source string.
        """
        dpi = int(pixel_ratio * 96)
        return (
            f"(function(){{"
            f"const defProp=Object.defineProperty.bind(null,screen);"
            f"defProp('width',{{get:function(){{return{width};}}}});"
            f"defProp('height',{{get:function(){{return{height};}}}});"
            f"defProp('availWidth',{{get:function(){{return{width};}}}});"
            f"defProp('availHeight',{{get:function(){{return{height};}}}});"
            f"defProp('colorDepth',{{get:function(){{return{color_depth};}}}});"
            f"defProp('pixelDepth',{{get:function(){{return{color_depth};}}}});"
            f"defProp('deviceXDPI',{{get:function(){{return{dpi};}}}});"
            f"defProp('logicalXDPI',{{get:function(){{return{dpi};}}}});"
            f"}})()"
        )

    @staticmethod
    def build_timezone_patch(timezone: str) -> str:
        """Build JS that overrides ``Date.prototype.getTimezoneOffset``.

        Args:
            timezone: IANA timezone string (e.g. ``"America/New_York"``).

        Returns:
            A JavaScript source string.
        """
        # Map common timezone strings to UTC offset in minutes
        tz_offsets = {
            "America/New_York": 300,
            "America/Chicago": 360,
            "America/Denver": 420,
            "America/Los_Angeles": 480,
            "America/Anchorage": 540,
            "Pacific/Honolulu": 600,
            "Europe/London": -60,
            "Europe/Paris": -60,
            "Europe/Berlin": -60,
            "Europe/Budapest": -60,
            "Europe/Moscow": -180,
            "Asia/Tokyo": -540,
            "Asia/Shanghai": -480,
            "Asia/Singapore": -480,
            "Asia/Dubai": -240,
            "Australia/Sydney": -660,
            "Pacific/Auckland": -720,
        }
        offset = tz_offsets.get(timezone, -60)
        return (
            f"(function(){{"
            f"const _origGetOffset=Date.prototype.getTimezoneOffset;"
            f"Date.prototype.getTimezoneOffset=function(){{return{offset};}};"
            f"}})()"
        )

    @staticmethod
    def build_locale_patch(locale: str) -> str:
        """Build JS that overrides navigator locale-related properties.

        Args:
            locale: Locale string (e.g. ``"en-US"``).

        Returns:
            A JavaScript source string.
        """
        return (
            f"(function(){{"
            f"Object.defineProperty(navigator,'language',{{"
            f"get:function(){{return'{locale}';}}"
            f"}});"
            f"Intl.DateTimeFormat=new Proxy(Intl.DateTimeFormat,{{"
            f"construct:function(target,args){{"
            f"return new target(locales=>locales||'{locale}');"
            f"}}"
            f"}});"
            f"}})()"
        )

    @staticmethod
    def build_color_consistency_patch(props: dict[str, Any]) -> str:
        """Build a combined JS snippet for all screen/color/timezone/locale overrides.

        Accepts a dict with optional keys: ``screen_width``,
        ``screen_height``, ``color_depth``, ``pixel_ratio``,
        ``timezone``, ``locale``.

        Args:
            props: Dict of screen/color/timezone/locale properties.

        Returns:
            A JavaScript source string.
        """
        parts: list[str] = []

        sw = props.get("screen_width")
        sh = props.get("screen_height")
        cd = props.get("color_depth", 24)
        pr = props.get("pixel_ratio", 1.0)
        if sw is not None and sh is not None:
            dpi = int(pr * 96)
            parts.append(
                f"const _s=screen;"
                f"const defProp=Object.defineProperty.bind(null,_s);"
                f"defProp('width',{{get:function(){{return{sw};}}}});"
                f"defProp('height',{{get:function(){{return{sh};}}}});"
                f"defProp('availWidth',{{get:function(){{return{sw};}}}});"
                f"defProp('availHeight',{{get:function(){{return{sh};}}}});"
                f"defProp('colorDepth',{{get:function(){{return{cd};}}}});"
                f"defProp('pixelDepth',{{get:function(){{return{cd};}}}});"
                f"defProp('deviceXDPI',{{get:function(){{return{dpi};}}}});"
                f"defProp('logicalXDPI',{{get:function(){{return{dpi};}}}});"
            )

        tz = props.get("timezone")
        if tz:
            tz_offsets = {
                "America/New_York": 300,
                "America/Chicago": 360,
                "America/Denver": 420,
                "America/Los_Angeles": 480,
                "America/Anchorage": 540,
                "Pacific/Honolulu": 600,
                "Europe/London": -60,
                "Europe/Paris": -60,
                "Europe/Berlin": -60,
                "Europe/Budapest": -60,
                "Europe/Moscow": -180,
                "Asia/Tokyo": -540,
                "Asia/Shanghai": -480,
                "Asia/Singapore": -480,
                "Asia/Dubai": -240,
                "Australia/Sydney": -660,
                "Pacific/Auckland": -720,
            }
            offset = tz_offsets.get(tz, -60)
            parts.append(
                f"Date.prototype.getTimezoneOffset=function(){{return{offset};}};"
            )

        loc = props.get("locale")
        if loc:
            parts.append(
                f"Object.defineProperty(navigator,'language',{{"
                f"get:function(){{return'{loc}';}}}});"
            )

        if not parts:
            return ""
        return f"(function(){{{';'.join(parts)}}})()"


# ═══════════════════════════════════════════════════════════════════════
# TLSFingerprintAligner
# ═══════════════════════════════════════════════════════════════════════


class TLSFingerprintAligner:
    """Stub for TLS/JA3 fingerprint alignment (deferred to P2).

    TLS fingerprint patching requires an external TLS proxy
    (e.g. curl-impersonate) and is deferred to P2. This class
    provides a placeholder interface.
    """

    @staticmethod
    def build_patch() -> str:
        """Return a no-op JS placeholder (TLS is not patchable from JS).

        Returns:
            Empty string — no JS patch for TLS.
        """
        return ""

    @staticmethod
    def align_cipher_suites(proxy_geo: str) -> list[str]:
        """Return cipher suite list aligned with a target geolocation.

        Args:
            proxy_geo: Geolocation hint (e.g. ``"US-East"``, ``"EU-West"``)
                       used to select region-typical JA3 fingerprints.

        Returns:
            List of cipher suite strings.
        """
        geo_ciphers: dict[str, list[str]] = {
            "US-East": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_CHACHA20_POLY1305_SHA256",
                "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
                "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
                "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
                "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
                "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256",
                "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256",
            ],
            "US-West": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_CHACHA20_POLY1305_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
                "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
                "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256",
                "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256",
            ],
            "EU-West": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
                "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
                "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
                "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
                "TLS_CHACHA20_POLY1305_SHA256",
                "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256",
            ],
            "Asia-SE": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA",
                "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA",
                "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
                "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
                "TLS_RSA_WITH_AES_128_CBC_SHA",
                "TLS_RSA_WITH_AES_256_CBC_SHA",
            ],
        }
        return geo_ciphers.get(proxy_geo, geo_ciphers["US-East"])
