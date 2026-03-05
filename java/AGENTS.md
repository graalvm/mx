# Java utilities (`java/`)

**Complexity:** medium (multiple small tools; mostly independent)

## OVERVIEW
Java-side helper tools used by `mx` (JUnit wrapper, JaCoCo report tooling, compiler daemons, etc.).

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| JUnit integration | `java/com.oracle.mxtool.junit/` | `MxJUnitWrapper` + decorators used by `mx unittest` |
| JaCoCo reporting | `java/com.oracle.mxtool.jacoco/` | `JacocoReport`, LCOV formatting |
| Compiler server | `java/com.oracle.mxtool.compilerserver/` | Javac/ECJ daemon implementations |
| Misc examples/tools | `java/*.java` | e.g. `ClasspathDump.java`, `ListModules.java` |

## CONVENTIONS
- Many files include “DO NOT ALTER OR REMOVE COPYRIGHT NOTICES…” headers; preserve them.

## ANTI-PATTERNS
- Don’t strip/modify Oracle copyright headers.
- Avoid mixing mx Python logic into Java tools; they are invoked from Python side.
