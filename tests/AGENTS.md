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

## CONVENTIONS
- Prefer `unittest` patterns used in existing tests (no pytest config present in `pyproject.toml`).

## ANTI-PATTERNS
- Avoid adding tests that depend on `mxbuild/` outputs from previous runs; make tests self-contained.
