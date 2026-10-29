# Conventions

- Commits: `type(scope): what changed` (see `git log --format=%s -40`).
- Type hints required on all params and returns (`docs/engineering-standards.md` METH-COD-008).
- Docstrings on non-trivial functions: purpose, chosen approach and why, rejected alternative, edge cases and error paths (METH-COD-001..003). Module header: 1-2 lines with role, entry functions, dependencies.
- Comments only for the WHY (METH-COD-006); no what-comments.
- TDD: a red test before the implementation (engineering-standards section 4).
- Regression test for every fixed bug.
- xfail marks must be real: `xfail_strict=true` makes a passing xfail fail the suite.
- Markers: `quick`, `integration` (skipped by default), `slow`.
- User-facing error messages are in Hungarian (engineering-standards section 1).
- Caution: `docs/engineering-standards.md` says mypy/pyright and radon gates run in CI. `.github/workflows/ci.yml` runs only `ruff check src/` and pytest. Do not claim those gates pass without running them.
