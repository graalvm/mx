# mx core implementation (`src/mx/_impl`)

**Complexity:** very high (bulk of `mx` logic; dense module graph)

## OVERVIEW
Primary implementation package for the `mx` CLI; most bug fixes and features belong here.

## STRUCTURE
```text
src/mx/_impl/
├── mx.py              # main CLI implementation + command registration
├── mx_gate.py         # gate command / CI orchestration helpers
├── mx_unittest.py     # unittest command implementation (Java + Python integration points)
├── mx_ide_*.py        # IDE config generators (Eclipse/IntelliJ/NetBeans)
├── mx_fetchjdk.py     # fetch-jdk implementation
├── mx_*.py            # command modules / subsystems
└── support/           # shared helpers (logging, etc.)
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Add/modify CLI commands | `mx.py` | Contains argument parsing and command table wiring |
| CI/gate behavior | `mx_gate.py` | Used by suites and by `./mx ... gate` |
| IDE config generation | `mx_ide_eclipse.py`, `mx_ide_intellij.py`, `mx_ide_netbeans.py` | Some output is marked GENERATED |
| JDK selection / fetch | `select_jdk.py`, `mx_fetchjdk.py` | `select_jdk.py` also exists as a root symlink |
| Deprecation warnings | `support/logging.py`, `mx.py` | Look for "[MX DEPRECATED]" and deprecated options |
| Benchmarking | `mx_benchmark.py` | Contains harness used to run benchmarks and report results |

## CONVENTIONS
- Keep changes here, not in `src/mx_*.py` proxies.
- Formatting: **Black is force-excluded** for `src/mx/_impl/(mx|mx_*.py|select_jdk).py` (see `pyproject.toml`). Avoid reformat-only diffs.

## ANTI-PATTERNS
- Do not add implementation to proxy modules under `src/` that say “DO NOT WRITE IMPLEMENTATION CODE HERE.”
- Don’t edit generated IDE output templates/streams that are explicitly labeled `GENERATED -- DO NOT EDIT`.
