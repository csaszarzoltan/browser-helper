"""Tests for browser-helper resource monitor."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from resource_monitor import ResourceMonitor


class TestResourceMonitorInit:
    def test_create_with_current_pid(self):
        """ResourceMonitor should accept a valid PID."""
        import os
        monitor = ResourceMonitor(os.getpid())
        assert monitor.pid == os.getpid()

    def test_create_with_invalid_pid(self):
        """ResourceMonitor should handle non-existent PID gracefully."""
        monitor = ResourceMonitor(999999999)
        assert monitor.pid == 999999999
        assert monitor.is_alive() is False


class TestCpuTracking:
    def test_cpu_percent_returns_float(self):
        """CPU percent should be a float >= 0."""
        import os
        monitor = ResourceMonitor(os.getpid())
        cpu = monitor.get_cpu_percent()
        assert isinstance(cpu, float)
        assert cpu >= 0.0

    def test_cpu_percent_dead_process(self):
        """Dead process should return 0.0."""
        monitor = ResourceMonitor(999999999)
        cpu = monitor.get_cpu_percent()
        assert cpu == 0.0


class TestMemoryTracking:
    def test_memory_usage_returns_dict(self):
        """Memory usage should return dict with rss_mb, vms_mb, percent."""
        import os
        monitor = ResourceMonitor(os.getpid())
        mem = monitor.get_memory_usage()
        assert "rss_mb" in mem
        assert "vms_mb" in mem
        assert "percent" in mem
        assert mem["rss_mb"] > 0
        assert mem["vms_mb"] > 0

    def test_memory_usage_dead_process(self):
        """Dead process should return zeroed dict."""
        monitor = ResourceMonitor(999999999)
        mem = monitor.get_memory_usage()
        assert mem["rss_mb"] == 0.0
        assert mem["vms_mb"] == 0.0
        assert mem["percent"] == 0.0


class TestLimitChecking:
    def test_check_limits_within_bounds(self):
        """Current process should be within default limits."""
        import os
        monitor = ResourceMonitor(os.getpid())
        result = monitor.check_limits(cpu_threshold=99.0, memory_limit_mb=9999.0)
        assert result["ok"] is True
        assert result["cpu_ok"] is True
        assert result["mem_ok"] is True
        assert "details" in result
        assert result["details"]["cpu_threshold"] == 99.0
        assert result["details"]["memory_limit_mb"] == 9999.0

    def test_check_limits_exceeds_memory(self):
        """Should detect memory limit exceeded with very low threshold."""
        import os
        monitor = ResourceMonitor(os.getpid())
        result = monitor.check_limits(cpu_threshold=99.0, memory_limit_mb=0.001)
        assert result["ok"] is False
        assert result["mem_ok"] is False

    def test_is_alive_current_process(self):
        """Current process should be alive."""
        import os
        monitor = ResourceMonitor(os.getpid())
        assert monitor.is_alive() is True

    def test_is_alive_dead_process(self):
        """Non-existent process should not be alive."""
        monitor = ResourceMonitor(999999999)
        assert monitor.is_alive() is False
