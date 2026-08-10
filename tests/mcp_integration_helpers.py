"""Integration helpers for the MCP server end-to-end test suite.

Implements a raw JSON-RPC client over the MCP *wire protocol* (real
subprocess stdio and real HTTP POST) without the MCP SDK's transport layer —
the SDK's high-level ``ClientSession`` is fine, but the task mandates real
transports with no MagicMock, so the client here drives stdio subprocess I/O
and streamable-HTTP sessions directly. Responses are parsed from
``text/event-stream`` (SSE ``event: message`` + ``data:``) and plain JSON
bodies, per the MCP streamable-HTTP spec.
"""

from __future__ import annotations

import json
import re
import time
import select
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: SSE ``data:`` lines for a single ``event: message`` block are joined by
#: newline — safe since we only send string JSON.
_PROTOCOL_VERSION = "2025-11-25"


def repo_python() -> str:
    """Return the repo venv python (``.venv/bin/python``), verified executable."""
    venv_py = REPO_ROOT / ".venv" / "bin" / "python"
    if venv_py.is_file():
        return str(venv_py)
    raise AssertionError(f"repo venv python missing: {venv_py}")


# ---------------------------------------------------------------------------
# Stdio transport — raw JSON-RPC over a real subprocess
# ---------------------------------------------------------------------------


class StdioTransport:
    """JSON-RPC client over a real MCP stdio subprocess (line-delimited JSON)."""

    def __init__(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        timeout: float = 60.0,
        startup_timeout: float = 15.0,
    ) -> None:
        self.cmd = [repo_python(), "-m", "browser_helper.mcp", *args]
        run_env = dict(__import__("os").environ)
        run_env.setdefault("PYTHONPATH", str(REPO_ROOT / "src"))
        run_env.setdefault("PYTHONUNBUFFERED", "1")
        # Test isolation: never launch real Chrome from the MCP server
        # subprocess (it would attach to the live browser-helper service
        # and make CDP-gated tools succeed instead of failing cleanly).
        run_env.setdefault("BH_TEST_NO_CHROME", "1")
        if env:
            run_env.update(env)
        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(REPO_ROOT),
            env=run_env,
            text=True,
            bufsize=1,
        )
        self.timeout = timeout
        self._stderr_lines: list[str] = []
        self._stderr_lock = threading.Lock()
        self._stderr_reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_reader.start()
        # Consume the CLI startup banner line so it never lands on our stdin
        # reader (the SDK client would treat it as an invalid JSON-RPC frame).
        banner = self._readline(timeout=startup_timeout)
        if banner is None:
            self.close()
            raise AssertionError(f"MCP server produced no banner; stderr={self.stderr_tail()}")
        self.banner = banner

    def _drain_stderr(self) -> None:
        """Continuously read stderr so the pipe never fills (deadlock guard)."""
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            with self._stderr_lock:
                self._stderr_lines.append(line.rstrip("\n"))

    def stderr_lines(self) -> list[str]:
        """All stderr output collected so far (async — thread-safe snapshot)."""
        with self._stderr_lock:
            return list(self._stderr_lines)

    def wait_for_stderr(self, pattern: str, timeout: float = 15.0) -> str | None:
        """Block until a stderr line matches ``pattern``; return the line."""
        regex = re.compile(pattern)
        deadline = __import__("time").time() + timeout
        while __import__("time").time() < deadline:
            for line in self.stderr_lines():
                if regex.search(line):
                    return line
            if self.proc.poll() is not None:
                return None
            __import__("time").sleep(0.1)
        return None

    def _readline(self, timeout: float | None = None) -> str | None:
        assert self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        line = self.proc.stdout.readline()
        return line if line else None

    def stderr_tail(self, n: int = 8) -> str:
        return "\n".join(self.stderr_lines()[-n:])

    def request(
        self, method: str, params: dict[str, Any] | None = None, req_id: int = 1
    ) -> dict[str, Any]:
        """Send one JSON-RPC request, read its response line."""
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        if self.proc.stdin is None or self.proc.poll() is not None:
            raise AssertionError(
                f"server exited early (rc={self.proc.poll()}); stderr={self.stderr_tail()}"
            )
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        # The server may interleave notifications (e.g. memory tools log
        # "notifications/message") before the actual response.  Keep reading
        # until a line with our req_id arrives.
        deadline = time.time() + self.timeout
        while True:
            remain = deadline - time.time()
            if remain <= 0:
                raise AssertionError(
                    f"no response to {method} within {self.timeout}s; stderr={self.stderr_tail()}"
                )
            line = self._readline(timeout=remain)
            if line is None:
                raise AssertionError(
                    f"no response to {method} within {self.timeout}s; stderr={self.stderr_tail()}"
                )
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"non-JSON response line {line!r}: {exc}; stderr={self.stderr_tail()}"
                ) from exc
            if isinstance(parsed, dict) and parsed.get("id") == req_id:
                return parsed
            # else: notification or another request's response — skip it.

    def close(self) -> None:
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            self.proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Streamable-HTTP transport — real HTTP client with session-id handshake
# ---------------------------------------------------------------------------


@dataclass
class StreamableHTTPTransport:
    """JSON-RPC client over real streamable-HTTP (session id + SSE parsing)."""

    base_url: str
    session_id: str | None = None
    next_id: int = field(default=1)

    @classmethod
    def connect(cls, base_url: str, timeout: float = 10.0) -> StreamableHTTPTransport:
        """POST initialize; capture the ``mcp-session-id`` response header."""
        t = cls(base_url=base_url)
        resp = t._post(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-integration-test", "version": "1.0"},
            },
            timeout=timeout,
        )
        assert resp.status == 200, f"initialize failed: HTTP {resp.status}"
        sid = resp.headers.get("mcp-session-id")
        assert sid, "initialize response missing mcp-session-id header"
        t.session_id = sid
        return t

    def _post(self, method: str, params: dict[str, Any] | None, timeout: float) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": self.next_id,
            "method": method,
        }
        if params is not None:
            body["params"] = params
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            # HTTP errors still carry JSON-RPC payloads we must surface.
            return exc
        return resp

    def request(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Send one request; return the parsed JSON-RPC response dict."""
        resp = self._post(method, params, timeout=timeout)
        payload = resp.read().decode("utf-8")
        parsed = parse_mcp_response(payload)
        self.next_id += 1
        return parsed

    def close(self) -> None:
        self.session_id = None


def parse_mcp_response(payload: str) -> dict[str, Any]:
    """Parse a streamable-HTTP response into the JSON-RPC dict.

    Accepts a plain JSON body or an SSE frame stream (``event: message``
    followed by one or more ``data:`` lines).

    The server may interleave *notifications* (``notifications/message``)
    with the actual response.  Each ``data:`` line is its own JSON value;
    the *last* one that is a response (has ``id``) is returned.  When only
    a single value exists it is returned directly.
    """
    text = payload.strip()
    if not text.startswith("event:"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"invalid JSON-RPC body {payload!r}") from exc

    values: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            raw = line[len("data:") :].strip()
            try:
                values.append(json.loads(raw))
            except json.JSONDecodeError:
                continue  # partial/invalid frame — ignore
    if not values:
        raise AssertionError(f"SSE frame without data lines: {payload!r}")

    # Prefer the last value that carries an id (a response, not a
    # notification); fall back to the last value overall.
    for value in reversed(values):
        if isinstance(value, dict) and "id" in value:
            return value
    return values[-1]
