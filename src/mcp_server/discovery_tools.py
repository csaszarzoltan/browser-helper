"""Browser MCP discovery + recorder bulk batch + locale visual diff + hybrid wait tools.

P1-2/P1-3/P2-1/P2-2: thin MCP wrappers over the existing REST primitives.
"""
from __future__ import annotations

import os
import glob as _glob

from mcp.server.fastmcp import Context

from .serialization import tool_error, tool_result


async def browser_discover_tests(
    pattern: str = "e2e/us_*.spec.ts",
    root: str | None = None,
    ctx: Context | None = None,
) -> str:
    """P1-2: discover test files by glob — maps to e2e/us_*.spec.ts + BDD gate US-007 (capability ``agent.testing``, READY).

    Returns {files:[{path, us_id, display_name}], count} — the US gate map is
    derived from the path (us_007 → US-007).
    """
    if ctx is not None:
        ctx.info(f"browser_discover_tests pattern={pattern}")
    try:
        base = root or os.getcwd()
        glob_expr = os.path.join(base, pattern)
        raw = _glob.glob(glob_expr, recursive=True)
        files = []
        for p in sorted(raw):
            stem = os.path.basename(p)
            # derive US-007 from us_007.spec.ts stem
            us = ""
            lower = stem.lower()
            if "us_" in lower:
                import re
                m = re.search(r"us_(\d+)", lower)
                if m:
                    us = f"US-{m.group(1).zfill(3)}"
            files.append({"path": p, "us_id": us, "display_name": stem})
        return tool_result("browser_discover_tests", {"count": len(files), "pattern": pattern, "files": files})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_discover_tests", "discovery_failed", str(exc))


async def browser_export_batch_spec(
    recordings: list[dict] | None = None,
    suite_name: str | None = None,
    ctx: Context | None = None,
) -> str:
    """P1-3: recorder bulk batch output — merge N recordings into one combined .spec.ts (capability ``agent.flow``, READY).

    Each entry in *recordings* is a {name, steps:[{selector, action, value}], ac} dict
    or a recording_id string. Delegates to browser_export_playwright_spec's renderer
    and merges via artifact_store.
    """
    if ctx is not None:
        ctx.info(f"browser_export_batch_spec recordings={len(recordings or [])}")
    try:
        import main as _m
        from main import artifact_store
        from .tools import _render_playwright_spec, _RECORD_AC

        bundle: list[dict] = []
        for item in (recordings or []):
            if isinstance(item, str):
                rec = _m.agent_recordings.get(item)
                if rec:
                    bundle.append(rec)
            elif isinstance(item, dict):
                # explicit steps dict → treat as a recording-like dict
                bundle.append(item)
        if not bundle:
            return tool_error("browser_export_batch_spec", "no_recordings", "no recordings found — pass recording ids or step dicts")
        # Merge steps into one pseudo-recording
        merged: dict = {"name": suite_name or f"Batch of {len(bundle)} recordings", "recording_id": f"batch_{bundle[0].get('recording_id','batch')}", "steps": []}
        for rec in bundle:
            merged["steps"].extend(rec.get("steps", []))
        # Harvest AC from any constituent
        for rec in bundle:
            for st in rec.get("steps", []):
                ac = st.get("ac")
                if ac:
                    _RECORD_AC[merged["recording_id"]] = ac
                    break
            if merged["recording_id"] in _RECORD_AC:
                break
        spec = _render_playwright_spec(merged, suite_name)
        art = artifact_store.put(spec.encode("utf-8"), "text/x.typescript", ".ts", metadata={"kind": "batch-spec", "count": len(bundle)})
        return tool_result("browser_export_batch_spec", {"suite_name": suite_name or merged["name"], "count": len(bundle), "artifact": art, "spec": spec})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_export_batch_spec", "export_failed", str(exc))


async def browser_visual_diff_locale(
    url: str,
    locales: list[str] | None = None,
    storage_key: str = "receiptlens.locale",
    h1_selector: str = "h1",
    threshold: float = 0.001,
    ctx: Context | None = None,
) -> str:
    """P2-1: visual diff per locale — h1 Scan vs Numerisez pixel-diff (capability ``agent.testing``, READY).

    Navigates to *url* once per locale value (via storageState origins
    injection before navigate), extracts h1 text, takes a screenshot,
    and pixel-diffs locale pairs. Returns {locales:[{locale,h1}], diffs:[{pair,pixel_delta,passed}]}.
    """
    if ctx is not None:
        ctx.info(f"browser_visual_diff_locale url={url} locales={locales}")
    try:
        from main import _get_current_session, _local_cdp_http, chrome_mgr, session_registry
        import base64, tempfile, os as _os
        from screenshot_diff import ScreenshotDiffEngine

        locales = locales or ["en", "fr"]
        storage_key = storage_key or "receiptlens.locale"
        locale_snaps: list[dict] = []
        img_paths: list[str] = []
        tmpdir = tempfile.mkdtemp(prefix="bh-locale-diff-")
        for loc in locales:
            # Fresh session per locale with injected locale
            await chrome_mgr.launch()
            sess = await session_registry.create(_local_cdp_http(), url="about:blank")
            try:
                # Inject locale via addScript+storageState idiom (navigate does it, but we are explicit)
                try:
                    await sess.client.add_script_to_evaluate_on_new_document(
                        f"try{{localStorage.setItem({repr(storage_key)},{repr(loc)});}}catch(e){{}}"
                    )
                except Exception:
                    pass
                await sess.client.navigate(url)
                await sess.client.wait_for_ready(timeout=8)
                # h1 text
                h1_r = await sess.client.evaluate(f"document.querySelector({repr(h1_selector)})?.innerText || ''")
                h1 = (h1_r.get("result") if isinstance(h1_r, dict) else "") or ""
                h1 = h1.strip() if isinstance(h1, str) else ""
                shot = await sess.client.screenshot()
                data = shot.get("data") or shot.get("image") or ""
                img_path = _os.path.join(tmpdir, f"locale-{loc}.jpg")
                if data:
                    raw = base64.b64decode(data) if isinstance(data, str) and len(data) > 100 else b""
                    if raw:
                        with open(img_path, "wb") as f:
                            f.write(raw)
                locale_snaps.append({"locale": loc, "h1": h1, "img_path": img_path})
                img_paths.append(img_path)
            finally:
                try:
                    await session_registry.destroy(sess.session_id)
                except Exception:
                    pass
        diffs: list[dict] = []
        for i in range(1, len(locale_snaps)):
            a, b = locale_snaps[i - 1], locale_snaps[i]
            out_path = _os.path.join(tmpdir, f"diff-{a['locale']}-{b['locale']}.png")
            try:
                res = ScreenshotDiffEngine.diff(a["img_path"], b["img_path"], out_path, threshold=threshold)
                diffs.append({"pair": f"{a['locale']}→{b['locale']}", "h1_a": a["h1"], "h1_b": b["h1"], "pixel_delta": round(res.pixel_delta, 6), "passed": res.passed, "dimensions_match": res.dimensions_match})
            except Exception as exc:
                diffs.append({"pair": f"{a['locale']}→{b['locale']}", "h1_a": a["h1"], "h1_b": b["h1"], "error": str(exc)[:300]})
        # Cleanup temp images
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
        return tool_result("browser_visual_diff_locale", {"url": url, "locales": locale_snaps, "diffs": diffs, "storage_key": storage_key})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_visual_diff_locale", "locale_diff_failed", str(exc))


async def browser_rate_hybrid_idle(
    url: str | None = None,
    timeout: int = 10,
    quiet_ms: int = 500,
    ctx: Context | None = None,
) -> str:
    """P2-2: hybrid wait_network_idle integrated into navigate flow (capability ``browser.core``, READY).

    If *url* is given, navigates first then waits for network idle (rate-limiter
    aware); otherwise just waits for idle on the current page. Returns idle wait
    result + rate_limiter state.
    """
    if ctx is not None:
        ctx.info(f"browser_rate_hybrid_idle url={url}")
    try:
        from main import _get_current_session, client, run_op
        from domain_throttle import domain_throttle
        sess = _get_current_session()
        target = sess.client if sess is not None else client
        # Optional navigate with hybrid wait
        nav_res = None
        if url:
            nav_res = await run_op("navigate", target.navigate, url)
            target = (sess.client if sess is not None else client)
        try:
            idle = await target.wait_for_network_idle(timeout=int(timeout), quiet_ms=int(quiet_ms))
        except Exception as exc:
            idle = {"status": "timeout", "error": str(exc)[:200]}
        # rate limiter snapshot
        rate = domain_throttle.snapshot() if hasattr(domain_throttle, "snapshot") else {}
        return tool_result("browser_rate_hybrid_idle", {"nav": nav_res, "idle": idle, "rate": rate})
    except Exception as exc:  # noqa: BLE001
        return tool_error("browser_rate_hybrid_idle", "hybrid_idle_failed", str(exc))
