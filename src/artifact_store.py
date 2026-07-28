"""Content-addressed artifact storage for large binary browser outputs."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: str = "~/.browser-helper/artifacts", ttl_seconds: int = 86400):
        self.root = Path(os.path.expanduser(root)).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def put(self, data: bytes, mime_type: str, suffix: str | None = None, metadata: dict | None = None) -> dict:
        suffix = suffix or mimetypes.guess_extension(mime_type) or ".bin"
        artifact_id = f"art_{uuid.uuid4().hex[:16]}"
        path = self.root / f"{artifact_id}{suffix}"
        path.write_bytes(data)
        sha256 = hashlib.sha256(data).hexdigest()
        created_at = time.time()
        record = {
            "artifact_id": artifact_id,
            "mime_type": mime_type,
            "size_bytes": len(data),
            "sha256": sha256,
            "created_at": created_at,
            "expires_at": created_at + self.ttl_seconds,
            "download_path": f"/artifacts/{artifact_id}",
            "metadata": metadata or {},
        }
        (self.root / f"{artifact_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    def get(self, artifact_id: str) -> tuple[Path, dict] | None:
        if not artifact_id.startswith("art_") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in artifact_id):
            return None
        meta_path = self.root / f"{artifact_id}.json"
        if not meta_path.is_file():
            return None
        record = json.loads(meta_path.read_text(encoding="utf-8"))
        matches = [p for p in self.root.glob(f"{artifact_id}.*") if p.suffix != ".json"]
        if not matches:
            return None
        return matches[0], record

    def cleanup(self) -> int:
        now = time.time()
        removed = 0
        for meta_path in self.root.glob("art_*.json"):
            try:
                record = json.loads(meta_path.read_text(encoding="utf-8"))
                if record.get("expires_at", 0) < now:
                    found = self.get(record["artifact_id"])
                    if found:
                        found[0].unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    removed += 1
            except (OSError, ValueError, KeyError):
                continue
        return removed
