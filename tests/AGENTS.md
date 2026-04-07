# Tests (`tests/`)

**Complexity:** medium (Python unittest suite + test fixtures)

## OVERVIEW
Repository-local tests for mx, primarily Python `unittest`-style modules plus test fixtures/projects under `tests/mxtests/`.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Python unit tests | `tests/*_tests.py`, `tests/test_*.py` | Run with `python -m unittest discover -s tests` |
| Test fixtures/projects | `tests/mxtests/` | Contains small suites/projects used by tests |
| JUnit wrapper code | `java/com.oracle.mxtool.junit/` | Not under `tests/` but drives Java-side testing |
| Gate wiring for mx's own test suite | `src/mx/_impl/mx_gate.py` (`_run_mx_suite_tests`) | `MxTests` does **not** use automatic discovery; new tests must be wired in explicitly |

## CONVENTIONS
- Prefer `unittest` patterns used in existing tests (no pytest config present in `pyproject.toml`).
- Keep code Python 3.8 compatible; use `from __future__ import annotations` if needed.
- For new Python tests, prefer one of these existing patterns:
  - simple module-level `test_*` functions plus a `tests()` entry point for direct invocation from `mx_gate.py`
  - `unittest.TestCase` classes, runnable via `python -m unittest ...`
- If you add a new test module that should run in CI via `MxTests`, also update `src/mx/_impl/mx_gate.py`:
  - modules with a `tests()` helper should be imported and called from `_run_mx_suite_tests()`
  - `unittest.TestCase`-based modules should be loaded/run explicitly from `_run_mx_suite_tests()`
- Keep tests self-contained: use temporary directories/files, and patch minimal `mx._opts` state when calling deep `mx` internals directly.
- For integration tests that invoke external tools (for example `git` or `mvn`), prefer temporary local repositories/workspaces over networked resources.

## ANTI-PATTERNS
- Avoid adding tests that depend on `mxbuild/` outputs from previous runs; make tests self-contained.
- Do not assume `MxTests` will pick up a new file automatically just because it lives under `tests/`; gate coverage must be wired in explicitly.
