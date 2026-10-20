"""A service restart must not close the person's Chrome (2026-10-20).

Chrome shared the service's process group and, under systemd, its control group, so
`systemctl restart browser-helper` closed the signed-in window. Chrome now starts in its
own session, and `bh doctor` says whether the unit also needs KillMode=process.
"""

import asyncio

from browser_helper import doctor as doctor_mod
from chrome_manager import ChromeManager


def test_launch_starts_chrome_in_its_own_session(monkeypatch, tmp_path):
    import chrome_manager

    seen = {}

    async def fake_exec(*cmd, **kwargs):
        seen.update(kwargs)
        raise FileNotFoundError  # stop launch() right after the spawn call

    monkeypatch.setattr(chrome_manager.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(chrome_manager, "_is_port_in_use", lambda p: False)
    monkeypatch.setattr(chrome_manager, "_find_chrome_with_profile_async", lambda d: _none())
    monkeypatch.delenv("CHROME_AUTO_PORT", raising=False)
    class _Settings(dict):
        def set(self, **kw):
            self.update(kw)

    mgr = ChromeManager(_Settings())
    monkeypatch.setattr(chrome_manager, "_find_chrome_path_from_settings", lambda s: "/bin/true")
    asyncio.run(mgr.launch(profile_dir=str(tmp_path), port=39555))
    assert seen.get("start_new_session") is True


async def _none():
    return None


def test_restart_check_warns_when_the_unit_would_kill_chrome(monkeypatch):
    monkeypatch.setattr(doctor_mod, "_chrome_proc", lambda p: ("42", ["chrome"]))
    monkeypatch.setattr(doctor_mod, "_cgroup_unit", lambda pid: "browser-helper.service")
    monkeypatch.setattr(doctor_mod, "_kill_mode", lambda unit: "control-group")
    c = doctor_mod.check_restart(9557)
    assert c.status == "WARN"
    assert "KillMode=process" in c.fix
    assert "browser-helper.service.d" in c.fix


def test_restart_check_passes_with_kill_mode_process(monkeypatch):
    monkeypatch.setattr(doctor_mod, "_chrome_proc", lambda p: ("42", ["chrome"]))
    monkeypatch.setattr(doctor_mod, "_cgroup_unit", lambda pid: "browser-helper.service")
    monkeypatch.setattr(doctor_mod, "_kill_mode", lambda unit: "process")
    assert doctor_mod.check_restart(9557).status == "PASS"


def test_restart_check_passes_outside_systemd(monkeypatch):
    monkeypatch.setattr(doctor_mod, "_chrome_proc", lambda p: ("42", ["chrome"]))
    monkeypatch.setattr(doctor_mod, "_cgroup_unit", lambda pid: None)
    assert doctor_mod.check_restart(9557).status == "PASS"


def test_cgroup_unit_reads_the_service_name(tmp_path, monkeypatch):
    f = tmp_path / "cgroup"
    f.write_text("0::/system.slice/browser-helper.service\n")
    real_open = open
    monkeypatch.setattr("builtins.open", lambda p, *a, **k: real_open(f if str(p).endswith("/cgroup") else p, *a, **k))
    assert doctor_mod._cgroup_unit("1") == "browser-helper.service"
