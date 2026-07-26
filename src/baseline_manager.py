"""Baseline Manager — persistent storage for screenshot baselines.

Provides BaselineManager that stores reference screenshots keyed by
URL (+ optional profile and viewport) for visual regression testing.
"""

import hashlib
import json
import os


class BaselineManager:
    """Manage baseline screenshot files on disk.

    Each baseline is stored as a PNG file under *base_dir* with a
    sidecar ``.meta.json`` file that records the original URL and
    viewport so that ``list_baselines()`` can return meaningful data.
    """

    def __init__(self, base_dir: str | None = None):
        """Initialise baseline storage.

        Args:
            base_dir: Root directory for baseline files.
                Default: ``~/.browser-helper/baselines/``
        """
        if base_dir is None:
            base_dir = os.path.join(
                os.path.expanduser("~"),
                ".browser-helper",
                "baselines",
            )
        self._base_dir = str(base_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_baseline_path(
        self,
        url: str,
        profile: str | None = None,
        viewport: dict | None = None,
    ) -> str:
        """Return the filesystem path for a baseline, creating dirs if needed.

        The path is deterministic: same URL + profile + viewport always
        produces the same path.

        Args:
            url: The page URL to derive the path for.
            profile: Optional profile name (scopes the baseline).
            viewport: Optional viewport dict (e.g. ``{"width": 1280, "height": 720}``).

        Returns:
            Absolute path ending in ``.png``.
        """
        subdir = self._profile_dir(profile)
        os.makedirs(subdir, exist_ok=True)
        filename = self._hash_for(url, viewport) + ".png"
        return os.path.join(subdir, filename)

    def save_baseline(
        self,
        url: str,
        image_data: bytes,
        profile: str | None = None,
        viewport: dict | None = None,
        format: str = "png",
    ) -> str:
        """Save a baseline screenshot to disk.

        Writes the image as PNG plus a sidecar ``.meta.json`` file that
        records the URL, viewport and creation timestamp.

        Args:
            url: The page URL this baseline belongs to.
            image_data: Raw PNG bytes of the screenshot.
            profile: Optional profile name.
            viewport: Optional viewport dict.
            format: Image format (default ``"png"``).

        Returns:
            The absolute path to the saved file.
        """
        path = self.get_baseline_path(url, profile=profile, viewport=viewport)
        with open(path, "wb") as f:
            f.write(image_data)

        # Write sidecar metadata
        self._write_meta(path, url, viewport)

        return path

    def get_baseline(
        self,
        url: str,
        profile: str | None = None,
        viewport: dict | None = None,
    ) -> str | None:
        """Return the path to an existing baseline, or None.

        Args:
            url: The page URL.
            profile: Optional profile name.
            viewport: Optional viewport dict.

        Returns:
            The file path if the baseline exists, else None.
        """
        path = self.get_baseline_path(url, profile=profile, viewport=viewport)
        return path if os.path.isfile(path) else None

    def list_baselines(self, profile: str | None = None) -> list[dict]:
        """List every stored baseline, optionally filtered by profile.

        Returns:
            A list of dicts, each with keys ``url``, ``path``, ``size``,
            ``timestamp``, and ``profile``.
        """
        results: list[dict] = []

        if profile:
            directories = [self._profile_dir(profile)]
        else:
            directories = [self._base_dir]
            if os.path.isdir(self._base_dir):
                for entry in sorted(os.listdir(self._base_dir)):
                    sub = os.path.join(self._base_dir, entry)
                    if os.path.isdir(sub):
                        directories.append(sub)

        seen_paths: set[str] = set()
        for directory in directories:
            if not os.path.isdir(directory):
                continue
            for fname in sorted(os.listdir(directory)):
                if not fname.endswith(".png"):
                    continue
                fpath = os.path.join(directory, fname)
                if fpath in seen_paths:
                    continue
                seen_paths.add(fpath)
                stat_info = os.stat(fpath)
                meta = self._read_meta(fpath)
                results.append(
                    {
                        "url": meta.get("url", self._url_from_hash(fname.replace(".png", ""))),
                        "path": fpath,
                        "size": stat_info.st_size,
                        "timestamp": self._iso_ts(stat_info.st_mtime),
                        "profile": self._profile_name_from(fpath),
                    }
                )

        return results

    def delete_baseline(
        self,
        url: str,
        profile: str | None = None,
    ) -> bool:
        """Delete a baseline from disk.

        Args:
            url: The page URL.
            profile: Optional profile name.

        Returns:
            True if the baseline existed and was removed, False otherwise.
        """
        subdir = self._profile_dir(profile)
        filename = self._hash_for(url, None) + ".png"
        path = os.path.join(subdir, filename)

        if not os.path.isfile(path):
            return False

        os.remove(path)
        # Remove sidecar meta file if present
        meta_path = path.replace(".png", ".meta.json")
        if os.path.isfile(meta_path):
            os.remove(meta_path)
        return True

    def get_app_data_dir(self) -> str:
        """Return the root data directory for baseline storage."""
        return self._base_dir

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def _write_meta(self, png_path: str, url: str, viewport: dict | None) -> None:
        """Write a sidecar JSON metadata file next to a PNG."""
        from datetime import UTC, datetime

        meta = {
            "url": url,
            "viewport": viewport,
            "created_at": datetime.now(UTC).isoformat(),
        }
        meta_path = png_path.replace(".png", ".meta.json")
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
        except OSError:
            pass  # Non-fatal — listing just uses fallback URL

    def _read_meta(self, png_path: str) -> dict:
        """Read the sidecar metadata file for a PNG, if present."""
        meta_path = png_path.replace(".png", ".meta.json")
        if not os.path.isfile(meta_path):
            return {}
        try:
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _profile_dir(self, profile: str | None) -> str:
        """Return the subdirectory for a given profile (or the root)."""
        if profile:
            return os.path.join(self._base_dir, profile)
        return self._base_dir

    @staticmethod
    def _hash_for(url: str, viewport: dict | None) -> str:
        """Compute a deterministic hex hash for a URL (+ optional viewport)."""
        material = url
        if viewport:
            material += json.dumps(viewport, sort_keys=True)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _iso_ts(mtime: float) -> str:
        """Convert a Unix timestamp to ISO-8601 string."""
        from datetime import UTC, datetime

        return datetime.fromtimestamp(mtime, tz=UTC).isoformat()

    @staticmethod
    def _url_from_hash(hash_str: str) -> str:
        """Return a placeholder URL from a hash (when metadata is missing)."""
        return f"hash://{hash_str}"

    def _profile_name_from(self, fpath: str) -> str:
        """Derive the profile name from a file's parent directory."""
        parent = os.path.dirname(fpath)
        if parent == self._base_dir:
            return ""
        return os.path.basename(parent)
