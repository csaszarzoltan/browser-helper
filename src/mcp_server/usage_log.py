"""MCP usage log: one JSON line per tool call, plus the summary behind ``bh usage``.

Entry functions: ``record()`` (called by ``server._as_tool_result``), ``summarize()``.
Only the operation, outcome, duration and, for ``eval``, the length and a short
SHA-1 of the script are written: never arguments, URLs, selectors or values.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

MAX_BYTES = 5 * 1024 * 1024


def log_path() -> Path:
    """Log file: ``BH_USAGE_LOG`` or ``~/.browser-helper/usage.jsonl``."""
    env = os.environ.get("BH_USAGE_LOG", "").strip()
    return Path(env) if env else Path.home() / ".browser-helper" / "usage.jsonl"


def record(
    op: str,
    status: str,
    error_code: str | None,
    ms: int,
    js: str | None = None,
    path: Path | None = None,
) -> None:
    """Append one line; rotate to ``<log>.1`` past 5 MB.

    Never raises: a broken log (read-only disk, bad path) must not fail a tool
    call, so every error is swallowed. A single ``.1`` generation is kept; older
    history is dropped rather than growing without bound.
    """
    try:
        entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "op": op,
            "status": status,
            "error_code": error_code,
            "ms": ms,
        }
        if js is not None:
            entry["js_len"] = len(js)
            entry["js_sha1_8"] = hashlib.sha1(js.encode("utf-8", "replace")).hexdigest()[:8]
        target = path or log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size >= MAX_BYTES:
            os.replace(target, target.with_name(target.name + ".1"))
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001, S110 — logging is best effort
        pass


def summarize(path: Path, days: int) -> dict[str, Any]:
    """Per-op counts, per-error-code counts and top eval hashes of the last *days* days."""
    cutoff = time.time() - days * 86400
    ops: dict[str, dict[str, int]] = {}
    codes: Counter[str] = Counter()
    evals: dict[str, dict[str, int]] = {}
    total = 0
    for file in (path.with_name(path.name + ".1"), path):
        try:
            lines = file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                e = json.loads(line)
                ts = time.mktime(time.strptime(e["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, KeyError, TypeError):
                continue
            if ts < cutoff:
                continue
            total += 1
            o = ops.setdefault(e["op"], {"calls": 0, "errors": 0, "ms": 0})
            o["calls"] += 1
            o["ms"] += int(e.get("ms") or 0)
            if e.get("status") == "error":
                o["errors"] += 1
                codes[e.get("error_code") or "unknown"] += 1
            if e["op"] == "eval" and e.get("js_sha1_8"):
                h = evals.setdefault(e["js_sha1_8"], {"count": 0, "js_len": e.get("js_len", 0)})
                h["count"] += 1
    return {"total": total, "ops": ops, "error_codes": dict(codes), "evals": evals}
