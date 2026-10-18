"""`run.py --debug-port N` points the server at Chrome on N, with or without --launch-chrome.

Found 2026-10-18: without --launch-chrome the flag was dropped, the server fell back to the saved
port (9557) and a throwaway server meant for a private Chrome opened tabs in the person's own one.
"""

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

RUN_PY = Path(__file__).resolve().parent.parent / "run.py"


def _run(monkeypatch, argv):
    monkeypatch.delenv("CHROME_AUTO_PORT", raising=False)
    monkeypatch.delenv("CHROME_AUTO_LAUNCH", raising=False)
    monkeypatch.setitem(sys.modules, "uvicorn", MagicMock())
    monkeypatch.setattr(sys, "argv", ["run.py", *argv])
    spec = importlib.util.spec_from_file_location("run_under_test", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


@pytest.mark.parametrize("extra", [[], ["--launch-chrome"]])
def test_debug_port_reaches_the_server_env(monkeypatch, extra):
    try:
        _run(monkeypatch, ["--debug-port", "9779", *extra])
        assert os.environ["CHROME_AUTO_PORT"] == "9779"
    finally:
        os.environ.pop("CHROME_AUTO_PORT", None)
        os.environ.pop("CHROME_AUTO_LAUNCH", None)
        os.environ.pop("CHROME_AUTO_PROFILE", None)


def test_no_flag_leaves_the_env_alone(monkeypatch):
    _run(monkeypatch, [])
    assert "CHROME_AUTO_PORT" not in os.environ
