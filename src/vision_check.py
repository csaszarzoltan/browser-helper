"""Vision-model assessment of screenshots (VLM feedback loop).

The browser-helper can ask a vision-capable LLM to *look at* a screenshot and
answer a prompt (e.g. "is this a login page?").  The model is reached through
the configured OpenAI-compatible endpoint (``VLM_BASE_URL`` /
``VLM_API_KEY`` / ``VLM_MODEL``), which in this setup is the llm-budget-gateway
proxy so the call is budgeted and routed like any other LLM traffic.

Fully optional: if no endpoint is configured, :func:`assess_screenshot`
returns a graceful ``skipped`` result instead of failing the flow.
"""

from __future__ import annotations

import base64
import json
import logging
import os

import httpx

logger = logging.getLogger("browser-helper.vision_check")


def _config() -> dict:
    return {
        "base_url": os.environ.get("VLM_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("VLM_API_KEY", ""),
        "model": os.environ.get("VLM_MODEL", ""),
        "timeout": float(os.environ.get("VLM_TIMEOUT", "60")),
    }


async def assess_screenshot(image_b64: str, prompt: str) -> dict:
    """Send *image_b64* (JPEG base64) to the vision model with *prompt*.

    Returns ``{"status": "ok", "assessment": ...}`` on success, or a
    ``skipped`` / ``error`` payload when the VLM is not configured or fails —
    the caller should treat those as non-fatal.
    """
    cfg = _config()
    if not cfg["base_url"] or not cfg["api_key"] or not cfg["model"]:
        logger.info("VLM not configured (VLM_BASE_URL/VLM_API_KEY/VLM_MODEL) — skipping")
        return {"status": "skipped", "reason": "vision model not configured"}

    data_url = f"data:image/jpeg;base64,{image_b64}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 300,
    }
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=cfg["timeout"]) as http:
            resp = await http.post(
                f"{cfg['base_url']}/chat/completions",
                json=payload,
                headers=headers,
            )
            if resp.status_code in (401, 403, 429):
                # Auth/rate-limit failures are environmental, not flow failures.
                logger.warning("VLM rejected (%s) — treating as skipped", resp.status_code)
                return {
                    "status": "skipped",
                    "reason": f"vision provider rejected request (HTTP {resp.status_code})",
                }
            resp.raise_for_status()
            data = resp.json()
        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return {"status": "ok", "assessment": text}
    except Exception as exc:  # noqa: BLE001 — non-fatal by contract
        logger.warning("VLM assessment failed: %s", exc)
        return {"status": "error", "error": str(exc)}
