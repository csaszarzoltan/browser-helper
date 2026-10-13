"""Cloud session pool and fallback chain.

Manages warm cloud browser sessions with auto-scaling, TTL expiry,
cost tracking, and fallback chain for provider failures.
"""

import asyncio
import os
import shutil
import signal
import socket
import tempfile
import time
from dataclasses import dataclass, field

import httpx

from browser_providers.base import BaseProvider, ProviderHealth, ProviderSession


def _signal_group(pgid: int, sig: int) -> None:
    """Send *sig* to a process group, if any member is still alive."""
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


async def _remove_profile(path: str) -> None:
    """Remove a profile directory. Chrome can write one more file into it while it shuts down, so retry briefly."""
    for _ in range(20):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        await asyncio.sleep(0.1)


def _free_local_port() -> int:
    """A TCP port on 127.0.0.1 that nothing is listening on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def _wait_for_devtools(port: int, timeout: float = 15.0) -> str:
    """Return the browser's DevTools WebSocket URL once Chrome answers on *port*."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=2.0) as client:
        while True:
            try:
                resp = await client.get(f"http://127.0.0.1:{port}/json/version")
                return resp.json()["webSocketDebuggerUrl"]
            except (httpx.HTTPError, KeyError, ValueError):
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Chrome did not open DevTools on port {port} within {timeout:.0f}s") from None
                await asyncio.sleep(0.2)


@dataclass
class FallbackResult:
    """Result of a fallback chain attempt."""

    success: bool
    session: ProviderSession | None = None
    chain: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CloudSessionPool:
    """Manages a pool of warm cloud browser sessions.

    Maintains a configurable number of warm (pre-launched) sessions,
    automatically scales up/down, expires idle sessions past TTL,
    and tracks per-provider costs.
    """

    def __init__(
        self,
        providers: list[BaseProvider] | None = None,
        min_warm: int = 1,
        max_warm: int = 5,
        ttl_seconds: int = 300,
    ) -> None:
        """Initialize the cloud session pool.

        Args:
            providers: List of available provider instances.
            min_warm: Minimum number of warm sessions to maintain.
            max_warm: Maximum number of warm sessions allowed.
            ttl_seconds: Idle session TTL in seconds.
        """
        self._providers = providers or []
        self._sessions: dict[str, ProviderSession] = {}
        self.min_warm = min_warm
        self.max_warm = max_warm
        self.ttl_seconds = ttl_seconds
        self._costs: dict[str, float] = {}

    def _evict_expired(self) -> None:
        """Remove sessions that have exceeded the TTL."""
        now = time.time()
        expired_ids = [
            sid for sid, sess in self._sessions.items() if now - sess.last_active > self.ttl_seconds
        ]
        for sid in expired_ids:
            del self._sessions[sid]

    def _get_warm_sessions(self, provider: str | None = None) -> list[ProviderSession]:
        """Get warm sessions, optionally filtered by provider.

        Args:
            provider: Optional provider name to filter by.

        Returns:
            List of warm ProviderSession objects.
        """
        self._evict_expired()
        if provider:
            return [s for s in self._sessions.values() if s.warm and s.provider == provider]
        return list(self._sessions.values())

    async def get_session(self, provider: str | None = None) -> ProviderSession:
        """Get a session, optionally filtered by provider name.

        Prefers existing warm sessions. Falls back to launching a new session
        via the first available provider.

        Args:
            provider: Optional provider name to filter by.

        Returns:
            A ProviderSession from the pool (warm) or newly launched.

        Raises:
            RuntimeError: If no providers are registered and no warm session exists.
        """
        # Prefer an existing warm session
        warm = self._get_warm_sessions(provider)
        if warm:
            session = warm[0]
            session.last_active = time.time()
            return session

        # Launch a new session via the first matching provider
        for prov in self._providers:
            if provider is None or _get_provider_name(prov) == provider:
                session = await prov.launch_sandbox()
                self._sessions[session.session_id] = session
                session.last_active = time.time()
                return session

        raise RuntimeError(
            "No provider available to create session"
            + (f" for provider '{provider}'" if provider else "")
        )

    async def release_session(self, session_id: str) -> None:
        """Release a session back to the warm pool or close it if pool is full.

        Args:
            session_id: Session to release.
        """
        if session_id not in self._sessions:
            return

        session = self._sessions[session_id]
        warm_count = len(self._get_warm_sessions())

        if warm_count >= self.max_warm:
            # Pool is full — close the session
            session.warm = False
            for prov in self._providers:
                if _get_provider_name(prov) == session.provider:
                    await prov.close_session(session_id)
                    break
            del self._sessions[session_id]
        else:
            # Return to warm pool
            session.warm = True
            session.last_active = time.time()

    async def scale_pool(self, target_warm: int) -> None:
        """Scale the warm pool to a target size.

        If target exceeds max_warm, caps at max_warm.
        Launches new sessions or closes extras as needed.

        Args:
            target_warm: Desired number of warm sessions.

        Raises:
            RuntimeError: If no providers are available to scale up.
        """
        target = min(target_warm, self.max_warm)
        current = len(self._get_warm_sessions())

        if target > current:
            # Scale up: launch new sessions
            to_launch = target - current
            for i in range(to_launch):
                # Cycle through providers
                if not self._providers:
                    raise RuntimeError("Cannot scale up: no providers registered")
                prov = self._providers[i % len(self._providers)]
                session = await prov.launch_sandbox()
                session.warm = True
                self._sessions[session.session_id] = session
        elif target < current:
            # Scale down: close excess warm sessions
            warm = self._get_warm_sessions()
            to_close = warm[target:]  # keep first `target`, close the rest
            for session in to_close:
                for prov in self._providers:
                    if _get_provider_name(prov) == session.provider:
                        await prov.close_session(session.session_id)
                        break
                del self._sessions[session.session_id]

    async def run_health_checks(self) -> dict[str, ProviderHealth]:
        """Run health checks against all registered providers.

        Returns:
            Dict mapping provider name to ProviderHealth result.
        """
        results: dict[str, ProviderHealth] = {}
        for prov in self._providers:
            name = _get_provider_name(prov)
            try:
                health = await prov.health_check()
                results[name] = health
            except Exception as exc:  # noqa: BLE001 — one provider failure shouldn't block others
                results[name] = ProviderHealth(
                    healthy=False,
                    latency_ms=0.0,
                    error=str(exc),
                )
        return results

    async def get_costs(self) -> dict[str, float]:
        """Get cumulative cost breakdown per provider.

        Returns:
            Dict with per-provider costs.
        """
        return dict(self._costs)

    def record_cost(self, provider: str, amount: float) -> None:
        """Record a cost for a provider.

        Args:
            provider: Provider name.
            amount: Cost amount to add.
        """
        self._costs[provider] = self._costs.get(provider, 0.0) + amount


class FallbackChain:
    """Ordered fallback chain for cloud browser providers.

    Falls back through providers in order, then to local headless Chrome,
    returning the first successful result or a diagnostic error.
    """

    def __init__(self, providers: list[BaseProvider]) -> None:
        """Initialize the fallback chain.

        Args:
            providers: Ordered list of providers to try.
                       Last entry should be a local headless fallback.
        """
        self._providers = providers
        # Local Chrome started by _launch_local_headless, by session id: the process and the
        # profile directory it owns (None when the profile belongs to the caller).
        self._local_processes: dict[str, tuple[asyncio.subprocess.Process, str | None]] = {}

    async def execute(self, profile: str | None = None) -> FallbackResult:
        """Execute the fallback chain.

        Tries each provider in order. Returns the first successful session.

        Args:
            profile: Optional profile for session configuration.

        Returns:
            FallbackResult with the successful session or error diagnostics.
        """
        chain_names: list[str] = []
        errors: list[str] = []

        for prov in self._providers:
            name = _get_provider_name(prov)
            chain_names.append(name)
            try:
                session = await prov.launch_sandbox(profile=profile)
                return FallbackResult(
                    success=True,
                    session=session,
                    chain=chain_names,
                    errors=errors,
                )
            except Exception as exc:  # noqa: BLE001 — one provider failure shouldn't block others
                errors.append(f"{name}: {exc}")
                continue

        return FallbackResult(
            success=False,
            session=None,
            chain=chain_names,
            errors=errors,
        )

    async def execute_with_local_fallback(
        self,
        profile: str | None = None,
    ) -> FallbackResult:
        """Execute fallback chain with local headless Chrome as last resort.

        Tries each registered provider first. If all fail, attempts to launch
        a local headless Chrome via subprocess as a fallback.

        Args:
            profile: Optional profile for session configuration.

        Returns:
            FallbackResult with session or diagnostics.
        """
        result = await self.execute(profile=profile)
        if result.success:
            return result

        # Try local headless Chrome fallback
        chain_names = list(result.chain)
        errors = list(result.errors)
        chain_names.append("local-headless")

        try:
            session = await self._launch_local_headless(profile)
            return FallbackResult(
                success=True,
                session=session,
                chain=chain_names,
                errors=errors,
            )
        except Exception as exc:  # noqa: BLE001 — local fallback failure shouldn't block provider errors
            errors.append(f"local-headless: {exc}")
            return FallbackResult(
                success=False,
                session=None,
                chain=chain_names,
                errors=errors,
            )

    async def _launch_local_headless(
        self,
        profile: str | None = None,
    ) -> ProviderSession:
        """Launch a local headless Chrome as a last-resort fallback.

        Args:
            profile: Optional profile for Chrome user data dir.

        Returns:
            A ProviderSession pointing to the local instance.

        Raises:
            RuntimeError: If Chrome/Chromium is not installed.
        """
        chrome_candidates = [
            "google-chrome",
            "google-chrome-stable",
            "chromium-browser",
            "chromium",
        ]

        # Find available Chrome
        chrome_path: str | None = None
        for candidate in chrome_candidates:
            proc = await asyncio.create_subprocess_exec(
                "which",
                candidate,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            code = await proc.wait()
            if code == 0:
                chrome_path = candidate
                break

        if not chrome_path:
            raise RuntimeError("Local headless Chrome not found. Install Chrome/Chromium.")

        # A profile of its own: without --user-data-dir Chrome opens the person's default profile,
        # where it would hand off to the browser they already run.
        owned_dir: str | None = None
        if profile:
            user_dir = f"/tmp/chrome-{profile}"
        else:
            owned_dir = tempfile.mkdtemp(prefix="bh-local-")
            user_dir = owned_dir

        # A port we choose, so the session can name the DevTools socket Chrome listens on.
        port = _free_local_port()
        cmd = [
            chrome_path,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--no-first-run",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_dir}",
        ]

        # stderr is not read, so a pipe would fill and block Chrome; it goes to DEVNULL. Chrome leads
        # its own process group, so closing the session can stop its helper processes too.
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        session_id = f"local-{process.pid}"
        self._local_processes[session_id] = (process, owned_dir)
        try:
            cdp_url = await _wait_for_devtools(port)
        except Exception:
            await self.close_local_session(session_id)
            raise

        now = time.time()
        return ProviderSession(
            session_id=session_id,
            provider="local-headless",
            cdp_url=cdp_url,
            created_at=now,
            last_active=now,
            warm=False,
            cost_estimate=0.0,
        )

    async def close_local_session(self, session_id: str) -> bool:
        """Stop the local Chrome that _launch_local_headless started for *session_id*.

        Also removes the profile directory that launch created for it. Returns False when no
        such process is tracked (never started, or already closed).
        """
        tracked = self._local_processes.pop(session_id, None)
        if tracked is None:
            return False
        process, owned_dir = tracked
        group = process.pid
        if process.returncode is None:
            _signal_group(group, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                _signal_group(group, signal.SIGKILL)
                await process.wait()
        # The browser has exited; whatever is left of its group is a helper that may still write.
        _signal_group(group, signal.SIGKILL)
        if owned_dir is not None:
            await _remove_profile(owned_dir)
        return True


def _get_provider_name(provider: BaseProvider) -> str:
    """Get a short human-readable name for a provider instance.

    Args:
        provider: A BaseProvider instance.

    Returns:
        The provider class name in lowercase.
    """
    return type(provider).__name__.replace("Provider", "").lower()