"""
Fingerprint randomizer for anti-detection profiles.

Generates JavaScript patches for canvas, WebGL, audio, and other
fingerprint signals that can be injected into browser contexts.
"""

from typing import Any


class FingerprintRandomizer:
    """Applies a profile fingerprint to generate injection-ready patches.

    Usage::

        randomizer = FingerprintRandomizer(profile_fingerprint=fp_dict)
        canvas_patch = FingerprintRandomizer.build_canvas_patch(
            fingerprint[\"canvas_offset\"]
        )
    """

    def __init__(self, profile_fingerprint: dict[str, Any]) -> None:
        self.profile_fingerprint = profile_fingerprint

    @staticmethod
    def build_canvas_patch(canvas_offset: tuple[int, int]) -> str:
        """Build a JavaScript snippet that offsets canvas readout.

        Returns a JS string that overrides ``toDataURL`` and
        ``getImageData`` to introduce the given pixel offset,
        making fingerprint correlation harder.
        """
        dx, dy = canvas_offset
        return (
            f"(function(){{"
            f"const _origToDataURL=HTMLCanvasElement.prototype.toDataURL;"
            f"HTMLCanvasElement.prototype.toDataURL=function(){{"
            f"const r=_origToDataURL.apply(this,arguments);"
            f"return r.replace(/rgba\\(\\d+,\\d+,\\d+,\\d+\\)/g,"
            f"'rgba({dx},{dy},0,1)');"
            f"}};"
            f"const _origGetImageData=CanvasRenderingContext2D.prototype.getImageData;"
            f"CanvasRenderingContext2D.prototype.getImageData="
            f"function(x,y,w,h){{"
            f"const d=_origGetImageData.call(this,x,y,w,h);"
            f"for(let i=3;i<d.data.length;i+=4){{"
            f"d.data[i-3]+={dx};d.data[i-2]+={dy};"
            f"}}return d;"
            f"}};"
            f"}})()"
        )

    @staticmethod
    def build_webgl_patch(webgl_vendor: str, webgl_renderer: str) -> str:
        """Build a JS snippet that overrides WebGL vendor/renderer."""
        return (
            f"Object.defineProperty(HTMLCanvasElement.prototype,"
            f"'getContext',{{value:function(){{"
            f"const ctx=HTMLCanvasElement.prototype.getContext"
            f".apply(this,arguments);"
            f"if(ctx&&ctx.getParameter){{"
            f"const orig=ctx.getParameter.bind(ctx);"
            f"ctx.getParameter=function(p){{"
            f"if(p===37445)return'{webgl_vendor}';"
            f"if(p===37446)return'{webgl_renderer}';"
            f"return orig(p);}};"
            f"}}return ctx;"
            f"}}}})"
        )

    @staticmethod
    def build_audio_patch(audio_variance_pct: float) -> str:
        """Build a JS snippet that adds noise to AudioContext output."""
        return (
            f"(function(){{"
            f"const AudioCtor=window.AudioContext||window.webkitAudioContext;"
            f"if(!AudioCtor)return;"
            f"const origCreateBuffer=AudioCtor.prototype.createBuffer;"
            f"AudioCtor.prototype.createBuffer=function(n,f,sr){{"
            f"const buf=origCreateBuffer.call(this,n,f,sr);"
            f"for(let c=0;c<n;c++){{"
            f"const data=buf.getChannelData(c);"
            f"for(let i=0;i<data.length;i++){{"
            f"data[i]+=(Math.random()-0.5)*{audio_variance_pct};"
            f"}}"
            f"}}return buf;"
            f"}};"
            f"}})()"
        )
