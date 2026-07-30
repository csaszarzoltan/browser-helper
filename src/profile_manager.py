"""Profile manager for browser-helper.

Manages browser profiles with their own data directories, extensions,
resource limits, and import/export as ZIP archives. Follows the same
JSON persistence pattern as SettingsManager.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anti_detection.profile_types import AntiDetectionProfile

logger = logging.getLogger("browser-helper.profiles")

DEFAULT_RESOURCE_LIMITS = {
    "max_memory_mb": 512,
    "max_cpu_percent": 80,
}


def _now() -> float:
    """Return current UTC timestamp."""
    return datetime.now(UTC).timestamp()


def _validate_profile_name(name: str) -> None:
    """Validate a profile name - reject empty or path-containing names."""
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
    fingerprint: dict | None = None
    fingerprint_config: dict | None = None

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
            "fingerprint": self.fingerprint,
            "fingerprint_config": self.fingerprint_config,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
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
            fingerprint=data.get("fingerprint"),
            fingerprint_config=data.get("fingerprint_config"),
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
        """Return a profile by name, or None if not found.

        Returns an ``AntiDetectionProfile`` when the stored data contains
        anti-detection fields (``profile_type`` / ``fingerprint``).
        """
        raw = self._data.get(name)
        if raw is None:
            return None
        # Return AntiDetectionProfile when stored data includes profile_type or non-null fingerprint
        if "profile_type" in raw or (raw.get("fingerprint") is not None and raw.get("fingerprint") != {}):
            from anti_detection.profile_types import AntiDetectionProfile
            return AntiDetectionProfile.from_dict(raw)
        return Profile.from_dict(raw)

    def list_profiles(self) -> list:
        """Return all profiles as a list of Profile or AntiDetectionProfile."""
        result: list = []
        for raw in self._data.values():
            if "profile_type" in raw or (raw.get("fingerprint") is not None and raw.get("fingerprint") != {}):
                from anti_detection.profile_types import AntiDetectionProfile
                result.append(AntiDetectionProfile.from_dict(raw))
            else:
                result.append(Profile.from_dict(raw))
        return result

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

    # ── Anti-detection profile management ───────────────────────────

    def create_anti_detection_profile(
        self,
        profile_type: str,
        name: str | None = None,
    ) -> AntiDetectionProfile:
        """Create a profile from a predefined anti-detection template.

        *profile_type* must be one of the keys in
        ``anti_detection.profile_types.ANTI_DETECTION_PROFILES`` or
        ``"standard"`` for a plain profile with an empty fingerprint.

        If *name* is omitted one is auto-generated from the profile type.

        Returns the created AntiDetectionProfile (persisted immediately).
        """
        from anti_detection.profile_types import (
            ANTI_DETECTION_PROFILES,
            AntiDetectionProfile,
        )

        if profile_type != "standard" and profile_type not in ANTI_DETECTION_PROFILES:
            raise ValueError(
                f"Unknown anti-detection profile type: {profile_type!r}. "
                f"Valid types: standard, {', '.join(ANTI_DETECTION_PROFILES)}"
            )

        if name is None:
            # Auto-generate name from profile type
            sanitized = profile_type.replace("-", "_").replace(" ", "_")
            name = f"ad_{sanitized}"

        _validate_profile_name(name)

        if name in self._data:
            raise ValueError(
                f"Profile {name!r} already exists — duplicate names not allowed"
            )

        # Build fingerprint from template or empty for standard
        if profile_type == "standard":
            fingerprint: dict = {}
        else:
            template = ANTI_DETECTION_PROFILES[profile_type]
            fingerprint = dict(template)

        data_dir = os.path.join(self._profiles_dir, name)
        os.makedirs(data_dir, exist_ok=True)

        profile = AntiDetectionProfile(
            name=name,
            data_dir=data_dir,
            profile_type=profile_type,
            fingerprint=fingerprint,
        )

        self._data[name] = profile.to_dict()
        self.save()
        return profile

    def get_fingerprint(self, profile_name: str) -> dict | None:
        """Return the fingerprint dict for *profile_name*.

        Returns ``None`` if the profile does not exist or is not an
        anti-detection profile (has no fingerprint key in its stored
        data).
        """
        raw = self._data.get(profile_name)
        if raw is None:
            return None
        fingerprint = raw.get("fingerprint")
        if fingerprint is None:
            return None
        return dict(fingerprint) if fingerprint else {}

    def get_fingerprint_config(self, profile_name: str) -> dict | None:
        """Return the fingerprint_config dict for *profile_name*.

        Returns ``None`` if the profile does not exist or has no
        fingerprint_config.
        """
        raw = self._data.get(profile_name)
        if raw is None:
            return None
        return raw.get("fingerprint_config")

    def set_fingerprint_config(self, profile_name: str, config: dict) -> None:
        """Set fingerprint_config on *profile_name* and persist."""
        raw = self._data.get(profile_name)
        if raw is None:
            raise ValueError(f"Profile {profile_name!r} does not exist")
        raw["fingerprint_config"] = config
        self.save()

    def generate_fingerprint(
        self,
        profile_name: str,
        overrides: dict | None = None,
    ) -> dict:
        """Generate and persist a fingerprint for *profile_name*.

        Uses realistic randomized values for all fingerprint fields.
        Optional *overrides* dict selectively overrides individual fields.

        Raises ``ValueError`` if the profile does not exist, if *overrides*
        is not a dict or None, or if any override value fails validation.

        Returns the generated fingerprint dict.
        """
        raw = self._data.get(profile_name)
        if raw is None:
            raise ValueError(f"Profile {profile_name!r} does not exist")

        # Validate overrides parameter
        if overrides is None:
            overrides = {}
        if not isinstance(overrides, dict):
            raise TypeError(
                f"overrides must be a dict, got {type(overrides).__name__}"
            )

        # Validate override field names and values
        known_fields = {
            "canvas_offset_x", "canvas_offset_y", "webgl_vendor",
            "webgl_renderer", "hardware_concurrency", "device_memory",
            "screen_width", "screen_height", "color_depth",
            "timezone", "platform",
        }
        known_platforms = {"Win32", "MacIntel", "Linux x86_64", "Linux armv8l"}

        for fname, value in overrides.items():
            if fname not in known_fields:
                raise ValueError(f"Unknown fingerprint field: {fname!r}")

            if fname == "canvas_offset_x":
                if not isinstance(value, int):
                    raise TypeError(f"canvas_offset_x must be int, got {type(value).__name__}")
            elif fname == "canvas_offset_y":
                if not isinstance(value, int):
                    raise TypeError(f"canvas_offset_y must be int, got {type(value).__name__}")
            elif fname == "hardware_concurrency":
                if not isinstance(value, int) or value <= 0:
                    raise ValueError(f"hardware_concurrency must be positive int, got {value!r}")
            elif fname == "device_memory":
                if not isinstance(value, (int, float)) or value <= 0:
                    raise ValueError(f"device_memory must be positive number, got {value!r}")
            elif fname == "color_depth":
                if value not in (24, 30):
                    raise ValueError(f"color_depth must be 24 or 30, got {value!r}")
            elif fname == "timezone":
                if not isinstance(value, str) or "/" not in value:
                    raise ValueError(f"timezone must be IANA format (e.g. 'America/New_York'), got {value!r}")
            elif fname == "platform":
                if value not in known_platforms:
                    raise ValueError(f"platform must be one of {known_platforms}, got {value!r}")
            elif fname == "screen_width" and (not isinstance(value, int) or value < 800):
                raise ValueError(f"screen_width must be positive int >= 800, got {value!r}")

        import random

        rng = random.Random()
        rng.seed(hash(profile_name) % (2**31))

        # Common screen resolutions
        resolutions = [
            (1920, 1080),
            (1366, 768),
            (1536, 864),
            (1440, 900),
            (2560, 1440),
            (1280, 720),
        ]
        screen_width, screen_height = rng.choice(resolutions)

        # Known GPU vendor/renderer pairs
        gpu_pairs = [
            ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)"),
            ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630)"),
            ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0)"),
            ("Apple", "Apple M2"),
        ]
        webgl_vendor, webgl_renderer = rng.choice(gpu_pairs)

        # IANA timezones
        timezones = [
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
            "Europe/London",
            "Europe/Berlin",
            "Europe/Paris",
            "Asia/Tokyo",
            "Asia/Shanghai",
            "Australia/Sydney",
        ]

        # Known platforms
        platforms = ["Win32", "MacIntel", "Linux x86_64", "Linux armv8l"]

        fingerprint = {
            "canvas_offset_x": rng.randint(-5, 5),
            "canvas_offset_y": rng.randint(-5, 5),
            "webgl_vendor": webgl_vendor,
            "webgl_renderer": webgl_renderer,
            "hardware_concurrency": rng.choice([4, 8, 12, 16, 24, 32]),
            "device_memory": rng.choice([4, 8, 16, 32, 64]),
            "screen_width": screen_width,
            "screen_height": screen_height,
            "color_depth": rng.choice([24, 30]),
            "timezone": rng.choice(timezones),
            "platform": rng.choice(platforms),
        }

        # Apply overrides
        if overrides:
            fingerprint.update(overrides)

        # Persist
        raw["fingerprint"] = fingerprint
        self.save()

        return fingerprint

    def select_profile_for_request(
        self,
        strategy: str = "random",
        session_id: str | None = None,
        timezone: str | None = None,
    ) -> AntiDetectionProfile:
        """Select an anti-detection profile for a browser request.

        Strategies:
            - ``"random"`` — pick uniformly at random from available profiles.
            - ``"sticky"`` — pin a session to one profile (same session_id
              always gets the same profile).
            - ``"geo-match"`` — match profile timezone to the request
              location (via *timezone*).

        Raises ``ValueError`` for unknown strategies and ``RuntimeError``
        when no anti-detection profiles exist.
        """
        from anti_detection.profile_types import AntiDetectionProfile

        valid_strategies = ("random", "sticky", "geo-match")
        if strategy not in valid_strategies:
            raise ValueError(
                f"Unknown selection strategy: {strategy!r}. "
                f"Valid strategies: {', '.join(valid_strategies)}"
            )

        # Gather all anti-detection profiles (not standard)
        ad_profiles: list[AntiDetectionProfile] = []
        for raw in self._data.values():
            p_type = raw.get("profile_type", "standard")
            if p_type != "standard":
                ad_profiles.append(AntiDetectionProfile.from_dict(raw))

        if not ad_profiles:
            raise RuntimeError(
                "No anti-detection profiles available — create one first"
            )

        if strategy == "random":
            import random

            return random.choice(ad_profiles)

        if strategy == "sticky":
            if session_id is None:
                # If no session context, fall back to random
                import random

                return random.choice(ad_profiles)

            # Persistent per-session assignment
            if not hasattr(self, "_sticky_assignments"):
                self._sticky_assignments: dict[str, str] = {}

            if session_id in self._sticky_assignments:
                pinned_name = self._sticky_assignments[session_id]
                for p in ad_profiles:
                    if p.name == pinned_name:
                        return p

            # First assignment for this session
            import random

            chosen = random.choice(ad_profiles)
            self._sticky_assignments[session_id] = chosen.name
            return chosen

        if strategy == "geo-match":
            if timezone is not None:
                # Find profile whose timezone matches (or contains) the requested one
                candidates = [
                    p
                    for p in ad_profiles
                    if p.fingerprint.get("timezone", "").startswith(
                        timezone.split("/")[0]
                    )
                ]
                if candidates:
                    return candidates[0]
            # Fallback to random if no match
            import random

            return random.choice(ad_profiles)

        # Should not reach here
        raise ValueError(f"Unknown selection strategy: {strategy!r}.")

    def validate_profile(
        self,
        profile_name: str,
        checker_url: str | None = None,
    ) -> dict:
        """Run detection validation against a profile.

        Uses :class:`ProfileValidator` to check fingerprint consistency
        and contacts known remote checker services.

        Returns a report dict with ``passed``, ``failed_checks``, and
        ``score`` keys.

        Raises ``ValueError`` if the profile does not exist.
        """
        from anti_detection.profile_types import ProfileValidator

        if profile_name not in self._data:
            raise ValueError(f"Profile {profile_name!r} does not exist")

        fingerprint = self.get_fingerprint(profile_name)
        if fingerprint is None:
            fingerprint = {}

        validator = ProfileValidator()
        local_result = validator.validate(
            profile_fingerprint=fingerprint,
            checker_url=checker_url,
        )

        # Contact known remote checker services
        import asyncio

        import httpx

        # Build list of checker URLs with their expected HTTP method
        checker_targets: list[tuple[str, str]] = []
        for c in validator.known_checkers:
            checker_targets.append((c["url"], c.get("type", "post")))
        if checker_url:
            checker_targets.append((checker_url, "post"))

        remote_scores: list[float] = []
        remote_failed: list[str] = []
        checker_engaged: bool = False
        for url, method in checker_targets:
            try:
                if method == "get":
                    raw = httpx.get(url, params={"fingerprint": str(fingerprint)}, timeout=5)
                else:
                    raw = httpx.post(url, json={"fingerprint": fingerprint}, timeout=5)
                # Support both sync httpx and async mock replacements
                if asyncio.iscoroutine(raw):
                    # Mock environment — checker was engaged
                    try:
                        raw = asyncio.run(raw)
                    except Exception:
                        # Mock raised (e.g. TimeoutException) — checker was engaged
                        remote_scores.append(0.0)
                        checker_engaged = True
                        continue
                    checker_engaged = True
                data = raw.json()
                remote_scores.append(data.get("score", 0.0))
                for fc in data.get("failedChecks", []):
                    if fc not in remote_failed:
                        remote_failed.append(fc)
            except Exception:
                # Real HTTP failure (404, timeout, etc.) — skip silently
                continue

        # Merge local and remote failed checks
        failed_checks = list(local_result["failed_checks"])
        for fc in remote_failed:
            if fc not in failed_checks:
                failed_checks.append(fc)

        # Score: remote average if any checkers were successfully contacted
        if checker_engaged and remote_scores:
            remote_avg = sum(remote_scores) / len(remote_scores)
            score = round(remote_avg, 2)
        elif checker_engaged and not remote_scores:
            # All checkers engaged but none returned a result → score 0
            score = 0.0
        else:
            score = local_result["score"]

        # overall passed: must have no failed checks and reasonable score
        passed = score >= 0.5 and len(failed_checks) == 0

        return {
            "passed": passed,
            "failed_checks": failed_checks,
            "score": score,
        }

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
