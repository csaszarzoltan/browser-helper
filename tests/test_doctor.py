"""``bh doctor``: reports each connection problem with its fix, exit 1 on a FAIL."""

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from click.testing import CliRunner

sys.path.insert(0, "src")

from browser_helper import doctor as doctor_mod  # noqa: E402
from browser_helper.__main__ import bh  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    seen: list = []
    ready_code = 200

    def do_GET(self):  # noqa: N802
        type(self).seen.append(self.path)
        if self.path == "/json/version":
            body, code = {"Browser": "Chrome/999.0"}, 200
        elif self.path == "/ready":
            body, code = {"ready": type(self).ready_code == 200}, type(self).ready_code
        else:
            body, code = {}, 404
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _Handler.seen = []
    _Handler.ready_code = 200
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, _Handler
    srv.shutdown()
    srv.server_close()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(*args, env=None):
    return CliRunner().invoke(bh, ["doctor", *args], env=env or {})


def test_all_reachable_exits_0_and_only_reads(server, monkeypatch):
    srv, h = server
    port = srv.server_address[1]
    monkeypatch.setattr(doctor_mod, "_chrome_args", lambda p: ["chrome", f"--remote-debugging-port={p}", "--user-data-dir=/x"])
    r = _run("--debug-port", str(port), "--api-port", str(port))
    assert r.exit_code == 0, r.output
    assert r.output.count("PASS") == 3
    assert "Chrome/999.0" in r.output
    assert set(h.seen) == {"/json/version", "/ready"}  # reads only: no /json/new, no tab


def test_nothing_listening_exits_1_and_names_the_chrome_command():
    port = _free_port()
    r = _run("--debug-port", str(port), "--api-port", str(port))
    assert r.exit_code == 1
    assert "FAIL" in r.output
    assert f"--remote-debugging-port={port}" in r.output
    assert "--user-data-dir" in r.output


def test_service_up_but_not_connected_is_a_fail(server, monkeypatch):
    srv, h = server
    h.ready_code = 503
    port = srv.server_address[1]
    monkeypatch.setattr(doctor_mod, "_chrome_args", lambda p: None)
    r = _run("--debug-port", str(port), "--api-port", str(port))
    assert r.exit_code == 1
    assert "not connected to Chrome" in r.output


def test_default_profile_chrome_is_a_warning(server, monkeypatch):
    srv, _ = server
    port = srv.server_address[1]
    monkeypatch.setattr(doctor_mod, "_chrome_args", lambda p: ["chrome", f"--remote-debugging-port={p}"])
    r = _run("--debug-port", str(port), "--api-port", str(port))
    assert "WARN  Chrome profile" in r.output
    assert r.exit_code == 0


def test_placeholder_token_is_a_fail(server, monkeypatch):
    srv, _ = server
    port = srv.server_address[1]
    monkeypatch.setattr(doctor_mod, "_chrome_args", lambda p: None)
    r = _run("--debug-port", str(port), "--api-port", str(port), env={"API_TOKEN": "changeme"})
    assert r.exit_code == 1
    assert "placeholder" in r.output


def test_existing_subcommands_still_register():
    for cmd in ("mcp", "memory"):
        r = CliRunner().invoke(bh, [cmd, "--help"])
        assert r.exit_code == 0, (cmd, r.output)
