# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-05
**Commit:** 3db69d20
**Branch:** master

## OVERVIEW
`mx` is a Python-based CLI tool (with some Java utilities) for building/testing multi-repo “suites” used by GraalVM projects.

## STRUCTURE
```text
./
├── mx                # primary CLI wrapper (bash) -> runs mx.py
├── mx.py             # bootstrapper; real impl in src/mx/_impl
├── src/mx/_impl/     # core mx implementation (Python)
├── src/mx/__main__.py# python -m mx entry point
├── tests/            # Python tests (mostly unittest style)
├── java/             # Java tools used by mx (JUnit wrapper, JaCoCo, etc.)
├── docs/             # conceptual + how-to docs (IDE, package structure, etc.)
├── .github/workflows/gate.yml  # CI entry (runs ./mx ... gate)
└── mxbuild/          # build artifacts/output (often huge; avoid editing)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| CLI entry / argument parsing | `mx` + `mx.py` | `mx` picks python executable; `mx.py` patches `sys.path` then `runpy.run_module("mx")` |
| Core implementation | `src/mx/_impl/` | High symbol density; most changes belong here |
| User-facing docs / architecture | `README.md`, `docs/` | `docs/package-structure.md` explains the bootstrap layout |
| Tests | `tests/` | Run via Python; CI also runs `./mx ... gate` |
| Java-side utilities | `java/` | e.g. custom JUnit wrapper + JaCoCo report support |
| CI behavior | `.github/workflows/gate.yml` | Downloads Eclipse; runs `./mx --strict-compliance gate --strict-mode` |

## CODE MAP (HIGH CENTRALITY)
| Symbol / File | Type | Location | Role |
|---|---|---|---|
| `mx` | bash script | `./mx` | Preferred entry point; chooses python and launches `mx.py` |
| `mx.py` | python script | `./mx.py` | Bootstraps import path; delegates to `mx` module |
| `mx` implementation | python package | `src/mx/_impl/` | Main command implementations and internals |
| `python -m mx` | module entry | `src/mx/__main__.py` | Module-mode entry point |

## CONVENTIONS (PROJECT-SPECIFIC)
- **Implementation separation:** many root-level `src/mx_*.py` files are *proxies*; real implementations live in `src/mx/_impl/`.
- **Formatting:** Black is configured in `pyproject.toml` (line length 120) but uses **force-exclude** for large/legacy hotspots (notably `src/mx/_impl/mx*.py`, `mx.mx/suite.py`, `select_jdk`, `remove_jdks.py`).
- **Versioning policy (`src/mx/mx_version.py`):** version is `<major>.<minor>.<bugfix>` and must be updated in every PR.
  - `major`: reserved for high-impact backward-incompatible changes (usually unchanged).
  - `minor`: bump when a PR adds a new feature that did not exist before.
  - `bugfix`: bump when a PR fixes existing features.
  - Keep the `src/mx/mx_version.py` bump in its own commit so branch rebases can resolve version conflicts cleanly.

## ANTI-PATTERNS (THIS PROJECT)
- Files explicitly state **“DO NOT WRITE IMPLEMENTATION CODE HERE.”** in several `src/mx_*.py` modules — put real logic under `src/mx/_impl/`.
- Do not edit files marked **“GENERATED -- DO NOT EDIT”** (e.g. parts of IDE config generation).
- Avoid touching `mxbuild/` content; it is build output and can be enormous/noisy.
- Do not do non-functional reformatting unless explicitly asked; keep surrounding formatting/style unchanged when making behavioral edits.

## COMMANDS
```bash
# Help / discovery
./mx --help
./mx help <command>

# CI-equivalent gate (see .github/workflows/gate.yml)
./mx --strict-compliance gate --strict-mode

# Python tests (repository-local)
python -m unittest discover -s tests

# Docs (Sphinx, under docs/api)
make -C docs/api html
```

## NOTES
- Cache files (`*.pyc`, `__pycache__/`) are not tracked in git, but they can exist locally as ignored files; use targeted searches that exclude `mxbuild/`, caches, and other generated outputs.
- CI downloads Eclipse from `archive.eclipse.org`; failures here can be external/network-related.
