# Task completion

- Run `.venv/bin/ruff check src/`; it must exit 0.
- Run `.venv/bin/python -m pytest` on a clean tree (commit first, or use a clean worktree). Check the pytest summary line or exit code. Use `set -o pipefail` if piping.
- For a user-visible change, exercise the real path (API call, `bh doctor`, or dashboard) and paste the output. Unit tests alone do not close it.
- For a release: bump the version in `pyproject.toml` and the README badge (currently 1.36.21), and add a CHANGELOG.md entry.
