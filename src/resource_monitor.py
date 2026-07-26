"""
Resource monitor for headless Chrome sessions.

Tracks per-process CPU and memory usage using psutil, with configurable
limits that can auto-kill sessions exceeding thresholds.
"""

import logging
import time

import psutil

logger = logging.getLogger("browser-helper.resource_monitor")


class ResourceMonitor:
    """Monitor CPU and memory usage for a specific process."""

    def __init__(self, pid: int):
        self.pid = pid
        self._process: psutil.Process | None = None
        try:
            self._process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            self._process = None
        self._last_cpu_check = 0.0
        self._cached_cpu: float = 0.0

    def _ensure_process(self) -> psutil.Process | None:
        """Re-acquire process handle if it was lost."""
        if self._process is None:
            try:
                self._process = psutil.Process(self.pid)
            except psutil.NoSuchProcess:
                return None
        # Verify the PID is still the same process
        try:
            if not self._process.is_running():
                self._process = None
                return None
            if self._process.pid != self.pid:
                self._process = None
                return None
        except psutil.NoSuchProcess:
            self._process = None
            return None
        return self._process

    def get_cpu_percent(self) -> float:
        """Return CPU usage percentage for the process.

        Uses psutil's sampling approach — the first call returns 0.0,
        subsequent calls return the percentage since the last call.
        Returns 0.0 if the process is no longer running.
        """
        proc = self._ensure_process()
        if proc is None:
            return 0.0
        try:
            now = time.monotonic()
            # psutil.cpu_percent() needs two calls to measure interval
            # For per-process, we use the interval-based approach
            if now - self._last_cpu_check < 0.5:
                return self._cached_cpu
            self._cached_cpu = proc.cpu_percent(interval=0.1)
            self._last_cpu_check = now
            return self._cached_cpu
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._process = None
            return 0.0

    def get_memory_usage(self) -> dict:
        """Return memory usage dict with rss_mb, vms_mb, percent.

        Returns zeroed dict if the process is no longer running.
        """
        proc = self._ensure_process()
        if proc is None:
            return {"rss_mb": 0.0, "vms_mb": 0.0, "percent": 0.0}
        try:
            mem = proc.memory_info()
            vm = psutil.virtual_memory()
            return {
                "rss_mb": round(mem.rss / (1024 * 1024), 2),
                "vms_mb": round(mem.vms / (1024 * 1024), 2),
                "percent": round(vm.percent, 1) if vm else 0.0,
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._process = None
            return {"rss_mb": 0.0, "vms_mb": 0.0, "percent": 0.0}

    def check_limits(
        self, cpu_threshold: float = 80.0, memory_limit_mb: float = 512.0
    ) -> dict:
        """Check if the process exceeds resource limits.

        Returns:
            dict with keys: ok, cpu_ok, mem_ok, details
            - ok: True if all limits are within bounds
            - cpu_ok: True if CPU is below threshold
            - mem_ok: True if memory is below limit
            - details: dict with cpu_percent, memory_mb, and threshold info
        """
        cpu = self.get_cpu_percent()
        mem = self.get_memory_usage()
        rss_mb = mem["rss_mb"]

        cpu_ok = cpu < cpu_threshold
        mem_ok = rss_mb < memory_limit_mb

        return {
            "ok": cpu_ok and mem_ok,
            "cpu_ok": cpu_ok,
            "mem_ok": mem_ok,
            "details": {
                "cpu_percent": cpu,
                "cpu_threshold": cpu_threshold,
                "memory_mb": rss_mb,
                "memory_limit_mb": memory_limit_mb,
                "vms_mb": mem["vms_mb"],
            },
        }

    def is_alive(self) -> bool:
        """Check if the monitored process is still running."""
        return self._ensure_process() is not None
