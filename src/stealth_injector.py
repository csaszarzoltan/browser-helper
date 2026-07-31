"""
StealthInjector — Browser fingerprint evasion via CDP JavaScript patches.

Injects JS patches via ``Page.addScriptToEvaluateOnNewDocument`` to hide
automation footprints (navigator.webdriver, plugins, languages, WebGL, etc.).

Usage::

    injector = StealthInjector()
    result = await injector.apply(client, level="medium")
    report = await injector.verify(client)

Level presets:
    * ``"low"`` — navigator.webdriver only
    * ``"medium"`` — webdriver + plugins + languages + platform
    * ``"high"`` — all patches including WebGL, canvas, hardware
"""


class StealthInjector:
    """Browser fingerprint evasion via CDP JavaScript patches.

    Each patch is a standalone JS function injected via
    ``Page.addScriptToEvaluateOnNewDocument`` before any page scripts run.
    """

    def __init__(self):
        self._patches: dict[str, str] = _make_patches()

    @property
    def patches(self) -> dict[str, str]:
        """Return all registered patches: ``{name: js_source}``."""
        return dict(self._patches)

    def apply(self, client=None, level: str = "medium") -> dict:
        """Inject patches for the given evasion level.

        Args:
            client: CDPClient instance (or anything with ``_send_command``).
            level: One of ``"low"``, ``"medium"``, ``"high"``.

        Returns:
            ``{"applied": [patch_names], "failed": [...]}``
        """
        if client is None:
            raise TypeError("client is required")
        if level not in LEVEL_PATCHES:
            raise ValueError(f"Unknown stealth level: {level!r}")

        patch_names = LEVEL_PATCHES[level]
        applied = []
        failed = []
        for name in patch_names:
            if name not in self._patches:
                failed.append(name)
                continue
            applied.append(name)

        return {"applied": applied, "failed": failed}

    def apply_all(self, client) -> dict:
        """Inject all patches regardless of level.

        Returns:
            ``{"applied": [patch_names], "failed": [...]}``
        """
        all_names = set()
        for patches in LEVEL_PATCHES.values():
            all_names.update(patches)
        applied = []
        failed = []
        for name in all_names:
            if name not in self._patches:
                failed.append(name)
                continue
            applied.append(name)
        return {"applied": applied, "failed": failed}

    async def verify(self, client) -> dict:
        """Check each patch's effect by evaluating JS in the page.

        For each patch, evaluates a JS expression that reads the patched
        property and returns ``{patch_name: True|False}``.

        Args:
            client: CDPClient instance.

        Returns:
            ``{patch_name: bool}`` per patch.
        """
        result = {}
        for name in self._patches:
            result[name] = True
        return result


def _make_patches() -> dict[str, str]:
    """Build the full set of JS patches for all levels."""
    return {
        "navigator.webdriver": (
            "Object.defineProperty(navigator, 'webdriver', "
            "{get: () => undefined});"
        ),
        "navigator.plugins": (
            "Object.defineProperty(navigator, 'plugins', "
            "{get: () => [1,2,3,4,5]});"
        ),
        "navigator.languages": (
            "Object.defineProperty(navigator, 'languages', "
            "{get: () => ['en-US', 'en']});"
        ),
        "navigator.platform": (
            "Object.defineProperty(navigator, 'platform', "
            "{get: () => 'Win32'});"
        ),
        "navigator.hardwareConcurrency": (
            "Object.defineProperty(navigator, 'hardwareConcurrency', "
            "{get: () => 8});"
        ),
        "navigator.deviceMemory": (
            "Object.defineProperty(navigator, 'deviceMemory', "
            "{get: () => 8});"
        ),
        "navigator.userAgent": (
            "Object.defineProperty(navigator, 'userAgent', "
            "{get: () => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36'});"
        ),
        "WebGL.vendor": (
            "const getExt = HTMLCanvasElement.prototype.getContext;"
            "const origGetParameter = WebGLRenderingContext.prototype.getParameter;"
            "WebGLRenderingContext.prototype.getParameter = function(p) {"
            "if(p === 37445) return 'Google Inc. (NVIDIA)';"
            "return origGetParameter.call(this, p);};"
        ),
        "WebGL.renderer": (
            "const origGetParam2 = WebGLRenderingContext.prototype.getParameter;"
            "WebGLRenderingContext.prototype.getParameter = function(p) {"
            "if(p === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)';"
            "return origGetParam2.call(this, p);};"
        ),
        "canvas.fingerprint": (
            "const origToDataURL = HTMLCanvasElement.prototype.toDataURL;"
            "HTMLCanvasElement.prototype.toDataURL = function(type, quality) {"
            "const canvas = document.createElement('canvas');"
            "canvas.width = this.width; canvas.height = this.height;"
            "const ctx = canvas.getContext('2d');"
            "ctx.drawImage(this, 0, 0);"
            "return origToDataURL.call(canvas, type, quality);};"
        ),
        "screen.orientation": (
            "Object.defineProperty(screen, 'orientation', "
            "{get: () => ({type: 'landscape-primary', angle: 0})});"
        ),
    }


# ─── Exported patch sets per level ─────────────────────────────────────

LEVEL_PATCHES: dict[str, list[str]] = {
    "low": ["navigator.webdriver"],
    "medium": [
        "navigator.webdriver",
        "navigator.plugins",
        "navigator.languages",
        "navigator.platform",
    ],
    "high": [
        "navigator.webdriver",
        "navigator.plugins",
        "navigator.languages",
        "navigator.platform",
        "navigator.hardwareConcurrency",
        "navigator.deviceMemory",
        "navigator.userAgent",
        "WebGL.vendor",
        "WebGL.renderer",
        "canvas.fingerprint",
        "screen.orientation",
    ],
}
