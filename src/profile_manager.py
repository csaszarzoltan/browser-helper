"""
Profile manager for browser-helper.

Manages browser profiles with their own data directories, extensions,
resource limits, and import/export as ZIP archives. Follows the same
JSON persistence pattern as SettingsManager.
"""

import json
import logging
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("browser-helper.profiles")

DEFAULT_RESOURCE_LIMITS = {
    "max_memory_mb": 512,
    "max_cpu_percent": 80,
}


def _now() -> float:
    """Return current UTC timestamp."""
    return datetime.now(UTC).timestamp()


def _validate_profile_name(name: str) -> None:
    """Validate a profile name — reject empty or path-containing names."""
    if not name:
        raise ValueError("Profile name must not be empty")
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Profile name must not contain path separators: {name!r}")


@dataclass
class Profile:
    """Represents a single browser profile with metadata and resource limits."""

    name: str
    data_dir: str
    created_at: float = field(default_factory=_now)
    last_used: float = field(default_factory=_now)
    extensions: list[str] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    resource_limits: dict = field(
        default_factory=lambda: dict(DEFAULT_RESOURCE_LIMITS)
    )

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "name": self.name,
            "data_dir": self.data_dir,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "extensions": list(self.extensions),
            "description": self.description,
            "tags": list(self.tags),
            "resource_limits": dict(self.resource_limits),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        """Deserialize from a dict loaded from JSON."""
        return cls(
            name=data["name"],
            data_dir=data["data_dir"],
            created_at=data.get("created_at", _now()),
            last_used=data.get("last_used", _now()),
            extensions=data.get("extensions", []),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            resource_limits=data.get(
                "resource_limits", dict(DEFAULT_RESOURCE_LIMITS)
            ),
        )


class ProfileManager:
    """Manages profiles with JSON persistence and file system operations.

    Each profile gets its own data directory under ``<storage_dir>/profiles/<name>/``
    and metadata is persisted to ``<storage_dir>/profiles.json``.
    """

    def __init__(self, storage_dir: str = "~/.browser-helper"):
        self._storage_dir = os.path.expanduser(storage_dir)
        self._profiles_file = os.path.join(self._storage_dir, "profiles.json")
        self._profiles_dir = os.path.join(self._storage_dir, "profiles")
        self._data: dict[str, dict] = {}

        # Ensure storage directories exist
        os.makedirs(self._profiles_dir, exist_ok=True)

        # Load existing profiles or create empty file
        self._load()

    # ── Persistence ─────────────────────────────────────────────────

    def _load(self) -> None:
        """Deserialize profiles from JSON on disk."""
        if os.path.isfile(self._profiles_file):
            try:
                with open(self._profiles_file, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Could not load profiles from %s: %s",
                    self._profiles_file, exc,
                )
                self._data = {}
        else:
            self._data = {}
            self.save()

    def save(self) -> None:
        """Persist current profiles to disk."""
        try:
            with open(self._profiles_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.error("Failed to save profiles: %s", exc)

    # ── CRUD ────────────────────────────────────────────────────────

    def create_profile(
        self,
        name: str,
        extensions: list[str] | None = None,
        description: str = "",
        tags: list[str] | None = None,
        resource_limits: dict | None = None,
    ) -> Profile:
        """Create a new profile and persist.

        Raises ``ValueError`` for invalid or duplicate names.
        """
        _validate_profile_name(name)

        if name in self._data:
            raise ValueError(
                f"Profile {name!r} already exists — duplicate names not allowed"
            )

        data_dir = os.path.join(self._profiles_dir, name)
        os.makedirs(data_dir, exist_ok=True)

        profile = Profile(
            name=name,
            data_dir=data_dir,
            extensions=extensions or [],
            description=description,
            tags=tags or [],
            resource_limits=resource_limits or dict(DEFAULT_RESOURCE_LIMITS),
        )

        self._data[name] = profile.to_dict()
        self.save()
        return profile

    def get_profile(self, name: str) -> Profile | None:
        """Return a profile by name, or None if not found."""
        raw = self._data.get(name)
        if raw is None:
            return None
        return Profile.from_dict(raw)

    def list_profiles(self) -> list[Profile]:
        """Return all profiles as a list."""
        return [Profile.from_dict(raw) for raw in self._data.values()]

    def delete_profile(self, name: str) -> bool:
        """Delete a profile and its data directory. Returns True on success."""
        if name not in self._data:
            return False

        # Remove data directory
        data_dir = os.path.join(self._profiles_dir, name)
        if os.path.isdir(data_dir):
            shutil.rmtree(data_dir, ignore_errors=True)

        del self._data[name]
        self.save()
        return True

    def rename_profile(self, old_name: str, new_name: str) -> bool:
        """Rename a profile. Returns True on success."""
        if old_name not in self._data:
            return False
        if new_name in self._data:
            return False

        _validate_profile_name(new_name)

        profile_dict = self._data.pop(old_name)
        profile_dict["name"] = new_name

        # Rename data directory on disk
        old_dir = os.path.join(self._profiles_dir, old_name)
        new_dir = os.path.join(self._profiles_dir, new_name)
        if os.path.isdir(old_dir):
            shutil.move(old_dir, new_dir)
        else:
            os.makedirs(new_dir, exist_ok=True)

        profile_dict["data_dir"] = new_dir
        self._data[new_name] = profile_dict
        self.save()
        return True

    def get_data_dir(self, name: str) -> str | None:
        """Return the absolute data directory path for a profile.

        Returns None if the profile does not exist.
        """
        if name not in self._data:
            return None
        return os.path.join(self._profiles_dir, name)

    # ── Extension management ────────────────────────────────────────

    def add_extension(self, name: str, extension_path: str) -> bool:
        """Add an extension path to a profile. Returns True on success."""
        if name not in self._data:
            return False

        profile_dict = self._data[name]
        exts = profile_dict.setdefault("extensions", [])
        if extension_path in exts:
            return True  # Already present — idempotent
        exts.append(extension_path)
        self.save()
        return True

    def remove_extension(self, name: str, extension_path: str) -> bool:
        """Remove an extension path from a profile. Returns True on success."""
        if name not in self._data:
            return False

        profile_dict = self._data[name]
        exts = profile_dict.get("extensions", [])
        if extension_path not in exts:
            return False
        exts.remove(extension_path)
        self.save()
        return True

    def get_extensions(self, name: str) -> list[str] | None:
        """Return the list of extension paths for a profile.

        Returns None if the profile does not exist.
        """
        profile_dict = self._data.get(name)
        if profile_dict is None:
            return None
        return list(profile_dict.get("extensions", []))

    # ── Import / export ─────────────────────────────────────────────

    def export_profile(self, name: str, output_path: str) -> str | None:
        """Export a profile as a ZIP archive.

        Returns the output path on success, or None if the profile does not exist.
        """
        if name not in self._data:
            return None

        profile_dict = self._data[name]
        data_dir = os.path.join(self._profiles_dir, name)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Write profiles.json metadata
            zf.writestr("profiles.json", json.dumps(profile_dict, indent=2))

            # Include data directory contents
            if os.path.isdir(data_dir):
                for root, _dirs, files in os.walk(data_dir):
                    for fn in files:
                        file_path = os.path.join(root, fn)
                        arcname = os.path.relpath(file_path, data_dir)
                        zf.write(file_path, arcname)

        logger.info("Exported profile %r to %s", name, output_path)
        return output_path

    def import_profile(self, zip_path: str) -> Profile:
        """Import a profile from a ZIP archive.

        Raises ``ValueError`` or ``zipfile.BadZipFile`` on invalid input
        or duplicate profile name.
        """
        if not os.path.isfile(zip_path):
            raise ValueError(f"Import file not found: {zip_path}")

        if not zipfile.is_zipfile(zip_path):
            raise zipfile.BadZipFile(f"Not a valid ZIP file: {zip_path}")

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Validate metadata
            if "profiles.json" not in zf.namelist():
                raise ValueError(
                    "ZIP archive is missing profiles.json metadata"
                )

            meta = json.loads(zf.read("profiles.json"))
            profile_name = meta["name"]

            # Check for duplicate
            if profile_name in self._data:
                raise ValueError(
                    f"Profile {profile_name!r} already exists — "
                    f"cannot import duplicate name"
                )

            # Recreate data directory
            data_dir = os.path.join(self._profiles_dir, profile_name)
            os.makedirs(data_dir, exist_ok=True)

            # Extract all files into the data directory
            for member in zf.namelist():
                if member == "profiles.json":
                    continue
                zf.extract(member, data_dir)

            # Update metadata with current paths
            meta["data_dir"] = data_dir

            self._data[profile_name] = meta
            self.save()

        logger.info("Imported profile %r from %s", profile_name, zip_path)
        return Profile.from_dict(meta)
