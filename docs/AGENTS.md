# Documentation (`docs/`)

**Complexity:** low-medium (conceptual docs + Sphinx API docs)

## OVERVIEW
Design/usage docs for mx (suites, IDE integration, package structure) plus Sphinx API doc build scaffolding.

## WHERE TO LOOK
| Need | Location | Notes |
|------|----------|-------|
| Bootstrap/package layout | `docs/package-structure.md` | Explains why root `mx.py` bootstraps `src/mx` |
| IDE integration | `docs/IDE.md` | Entry point for IDE config generation details |
| Suite concepts | `README.md` (root) + `docs/*.md` | README is the primary conceptual doc |
| Build API docs | `docs/api/Makefile` | Sphinx Makefile; output under `docs/api/_build/` |

## CONVENTIONS
- Keep docs concrete to mx behaviors and commands; link to source modules when helpful.

## ANTI-PATTERNS
- Don’t document `mxbuild/` paths as stable inputs; they are build outputs and vary by platform/JDK.
