# Tech stack

- Python >=3.10 (`pyproject.toml`); CI runs 3.11; ruff target py311, line-length 100.
- Runtime deps: fastapi, uvicorn, websockets, httpx, Pillow, python-multipart, playwright, psutil.
- Extras: `dev` (pytest, pytest-asyncio, pytest-xdist, pytest-testmon, ruff); `mcp` (`mcp>=1.24,<2`, keep the `<2` pin: FastMCP moved to `fastmcp` in 2.x).
- No `[build-system]` table in `pyproject.toml`; editable installs rely on pip defaults.
- `uv.lock` exists, but CI and the README install with `python -m venv .venv` + pip.
- pytest config: `asyncio_mode=auto`, `xfail_strict=true`, default addopts `-n auto -q --dist loadgroup` (xdist).
- Packaging: `Dockerfile`, `docker-compose.yml`; `scripts/release-validate.sh`, `scripts/install-global-mcp.sh`.
