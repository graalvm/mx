# Packaging with distributions

In mx, projects build intermediate outputs and distributions package those outputs into artifacts that other tools, other suites, or end users consume.

That split is important: if you want to understand what a suite _publishes_, look at `distributions`, not just at `projects`.

## Core packaging model

A distribution depends on projects, libraries, and sometimes other distributions.
The kind of distribution determines how those dependencies are turned into an artifact.

The most important rule is that direct distribution dependencies are normally treated as separate packaged artifacts, not as contents to be merged into the current artifact.
In other words, a dependency on another distribution usually means "this artifact needs that artifact on its class path or module path", not "copy that artifact's contents into this one".

A notable exception is a layout directory distribution used as an input to another distribution: that assembled directory is meant to be consumed as content, not just as a separate published archive.

That rule is the source of much of mx's packaging behavior, especially for JAR distributions and launcher layouts.

## The main packaging forms

### JAR distributions

A plain distribution entry without `layout`, `native`, or `type: "pom"` becomes a JAR distribution.

This is the standard packaging form for Java code.
A JAR distribution:

* packages the outputs of its archived project and library dependencies
* can generate a source zip alongside the binary JAR
* can declare `moduleInfo` to produce a Java module
* can carry Maven metadata via `maven`
* can add manifest entries via `manifestEntries`
* can declare a `mainClass`, which becomes the `Main-Class` manifest entry

`mainClass` is the built-in launcher entry point for Java packaging.
It tells mx which class should be used as the application entry point for that JAR.

What it does **not** mean is "bundle every runtime dependency into one fat JAR".
If the distribution has `distDependencies`, those remain separate artifacts.
A JAR with `mainClass` is therefore best thought of as an _entry-point JAR_, not automatically as a self-contained launcher image.

### Layout distributions

A distribution with a `layout` attribute becomes a layout distribution.

Layout distributions are the general assembly mechanism in mx.
They package files by describing where each file or file set should appear in the result.
Their inputs can come from:

* files in the suite directory
* outputs of other dependencies
* extracted contents of archive dependencies
* generated strings
* symbolic links

By default a layout distribution produces a JAR, but `type` can change that to `jar`, `zip`, `tar`, or `dir`.

Use layout distributions when you need to assemble a package that is larger or more structured than a single Java JAR: SDK layouts, bundles with native code, launchers plus support files, mixed-language artifacts, and installable images are all typical examples.

See [Layout distributions](layout-distributions.md) for the layout syntax.

### Layout directory distributions

A layout distribution with `type: "dir"` produces an output directory instead of a final archive.

This is useful when a suite wants a reusable assembled directory, or when another distribution should consume the assembled layout as an input.

### Native TAR distributions

A distribution with `native: True` and no `layout` becomes a native TAR distribution.

This packaging form is for artifacts built from native projects.
mx collects the native project results and packages those outputs into a TAR archive.

If `native: True` is combined with `layout`, the `layout` still drives the assembly, but the default archive type becomes TAR.

### POM distributions

A distribution with `type: "pom"` is a metadata-only Maven artifact.

It does not package code or resources.
Instead, it groups Maven dependencies under a POM packaging artifact.
This is useful when a suite wants to publish dependency metadata without publishing another binary.

### MavenProject distributions

A distribution with `class: MavenProject` delegates the build and packaging of a self-contained source tree to Maven, while still letting mx treat the result as a suite distribution.

This is useful for Maven plugins, archetypes, and other artifacts whose native packaging semantics are better expressed in Maven than in plain mx distribution metadata.

See [Adding Maven projects to mx suites](maven-projects.md) for details.

## How launchers work

mx has packaging primitives for launchers, but not a single special "language launcher" distribution kind.

In practice launchers are usually assembled in layers.

### 1. Define the entry point

At the Java level, the entry point is the `mainClass` of a JAR distribution.
That gives the distribution a `Main-Class` manifest entry.

This answers the question "what code should start?".

### 2. Assemble the runnable package

A runnable launcher usually needs more than one JAR.
It may need additional distributions on the class path or module path, native libraries, scripts, config files, licenses, or platform-specific wrapper files.

That second step is usually handled by a layout distribution or, for more specialized cases, by a custom distribution class in `mx_<suite>.py`.

This answers the question "what files should be shipped together, and with what on-disk layout?".

### 3. Add platform-specific wrapping if needed

If the launcher should look like a platform command rather than a raw JAR, suites typically add wrapper scripts, platform-specific files, or native binaries through the layout itself or through custom distribution code.

mx therefore separates:

* the Java entry point (`mainClass`)
* the packaged set of files (the distribution layout)
* any platform wrapper or launcher-specific behavior (usually layout content or custom suite code)

That separation is deliberate.
It lets the same code payload participate in several different packaged forms.

## When to use which packaging form

Typical choices are:

* a **JAR distribution** for standard Java deliverables
* a **layout distribution** for assembled archives or directories with explicit file layout
* a **native TAR distribution** for native project outputs
* a **POM distribution** for metadata-only Maven publication
* a **MavenProject** when Maven should remain the source of truth for packaging behavior

If the built-in distribution kinds are close but not sufficient, add a custom distribution class in `mx_<suite>.py`.

## Related topics

* [The structure of `suite.py`](suite-py.md)
* [Suite extension points](extension-points.md)
* [Layout distributions](layout-distributions.md)
* [Adding Maven projects to mx suites](maven-projects.md)
