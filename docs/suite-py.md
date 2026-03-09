# The structure of `suite.py`

A suite is the basic unit of structure in mx.
Its `suite.py` file declares what the suite contains, what it imports, and how its outputs should be packaged and deployed.

`suite.py` is a data file, not the place for arbitrary Python logic.
mx and other tools inspect it without executing arbitrary Python code, so it is expected to stay JSON-like.
If a suite needs executable behavior, that behavior belongs in the optional `mx_<suite>.py` module next to `suite.py`.

## Top-level shape

A typical suite definition has this shape:

```python
suite = {
    "name": "example",
    "mxversion": "7.0.0",

    "imports": {
        "suites": [
            # other suites
        ],
        "libraries": {
            # imported libraries
        },
    },

    "licenses": {
        # license definitions
    },
    "repositories": {
        # named deployment repositories
    },

    "libraries": {
        # downloaded libraries and other external artifacts
    },

    "projects": {
        # source projects built by mx
    },
    "distributions": {
        # packaged outputs assembled by mx
    },
}
```

Not every suite needs every section, but many suites can be read in that order: metadata, imports, build inputs, then packaged outputs.

## The most important parts

### `name`

The suite name.
It must match the `mx.<suite>` directory and is used to qualify references from other suites.

### `mxversion`

The minimum mx version required by the suite.
This is the compatibility boundary for the schema and behavior used by that suite.

### `imports`

This section declares what the suite depends on outside its own directory.

The most important part is `imports["suites"]`, which lists imported suites.
Those imports determine which other suites participate in suite discovery and therefore which projects, distributions and commands become visible.
A suite import entry typically contains at least a `name` and may additionally record import metadata such as `version`, `urls`, `subdir`, `dynamic`, `versionFrom`, or `foreign`.

`subdir` indicates that the imported suite lives in a subdirectory of the same repository instead of at the repository root.
This is the common shape in multi-suite repositories such as `graal`, where a suite such as `compiler` lives under `<repo>/compiler`.
In that case, `subdir: True` lets mx resolve the suite relative to the repository checkout instead of requiring explicit import URLs.
The same distinction appears on the command line for dynamic imports: `--dy /compiler` refers to a suite in a repository subdirectory.

`imports["libraries"]` is different: it imports library definitions, not whole suites.

See [Dynamic imports](dynamic-imports.md) for the special case where a suite import is optional.

### `libraries`

This section describes external inputs.

`libraries` are downloaded artifacts such as JARs, source archives or other files.

Projects and distributions depend on these entries by name.

### `projects`

Projects are the buildable units of source code.
In practice this section answers:

* where the sources live
* which other inputs they depend on
* which toolchain rules apply
* what kind of project mx should instantiate

A plain Java project is declared directly in `suite.py`.
If a project needs custom behavior, it can use a custom `"class"` implemented in `mx_<suite>.py`.

Common project-level fields include:

* `checkstyleVersion` selects the Checkstyle version for a project that supplies its own Checkstyle configuration.
  It cannot be combined with `checkstyle`; if a project reuses another project's Checkstyle configuration, the version comes from that referenced project instead.
* `testProject` marks a project as a test project.
  If it is omitted, mx infers this from naming conventions such as `.test` suffixes.
  Use it when a test project does not follow the default naming convention, or when a project with a conventional name should not be treated as a test project.
* `defaultBuild` is a boolean that controls whether the project is part of the default dependency set used by `mx build` and related gate tasks.
  `False` keeps the project out of default builds while still allowing it to be built explicitly.

### `distributions`

Distributions are the packaging units of mx.
They take projects, libraries and sometimes other distributions and turn those inputs into archives or output directories.

This is the section that usually matters most for consumers of a suite, because distributions are the artifacts that get published, installed, run, or handed to other suites.

The common cases are:

* JAR distributions
* layout distributions (`layout`)
* native TAR distributions (`native`)
* POM distributions (`type: "pom"`)
* custom distribution classes

Common distribution-level fields include:

* `testDistribution` marks a distribution as a test distribution.
  If it is omitted, mx infers this from names ending in `_TEST` or `_TESTS`.
  Test distributions are expected to archive test projects and are excluded from Maven deployment.
* `unittestConfig` names a unittest configuration registered from Python code, typically in `mx_<suite>.py` via `mx_unittest.register_unittest_config(...)`.
  When `mx unittest` runs over dependencies including that distribution, the named configuration is applied.
* `defaultBuild` has the same meaning as for projects: `False` removes the distribution from the default dependency set while still allowing it to be built explicitly.
* `platformDependent` marks the built artifact as platform-specific.
  mx places its outputs under a platform-specific output root, such as `<os>-<arch>`, instead of the platform-independent output root.
* `useModulePath` applies to JAR distributions.
  It places the distribution and its dependencies on the module path instead of the class path and requires a `moduleInfo` name.

A typical explicit test setup looks like this:

```python
"projects": {
    "com.example.tool.tests": {
        "subDir": "src",
        "sourceDirs": ["src"],
        "dependencies": ["com.example.tool"],
        "javaCompliance": "17+",
        "testProject": True,
        "defaultBuild": False,
    },
},
"distributions": {
    "EXAMPLE_TOOL_TESTS": {
        "dependencies": ["com.example.tool.tests"],
        "testDistribution": True,
        "unittestConfig": "hosted-tests",
        "defaultBuild": False,
    },
},
```

In that example, `hosted-tests` must be registered from Python code; `defaultBuild: False` keeps the test project and its test distribution out of default builds.

See [Packaging with distributions](packaging.md) for an overview.

## Important suite-level metadata

These fields are easy to miss because they are not themselves projects or distributions, but they influence how a suite is built or published.

### `defaultLicense`

The default license applied to suite constituents that do not specify their own license.

### `licenses`

Named license definitions referenced by distributions, libraries and repositories.

### `repositories`

Named binary or Maven deployment targets.
These are used by commands such as `mx binary-deploy` and `mx maven-deploy`.

### Maven publication metadata: `groupId`, `url`, `developer`, `scm`

These fields describe how deployable distributions from the suite should appear in generated Maven metadata.

* `groupId` provides the default Maven group id for deployable distributions in the suite.
* `url` provides the suite URL written into generated POM metadata.
* `developer` provides developer metadata written into generated POM metadata.
* `scm` provides source-control metadata written into generated POM metadata.

### `version`

An explicit release version for the suite.
This affects deployment metadata and release version computation.
It is separate from the `version` field used inside suite imports.

### `release`

Declares whether the suite should be treated as a release suite when an explicit `version` is present.

### `outputRoot`

Overrides where mx places build output for the suite when an alternate output root is in effect.

### `urlrewrites`

Primary-suite URL rewrite rules for imported suite URLs.
This is the mechanism for redirecting suite fetches to mirrors or internal caches.

### `versionConflictResolution`

Sets the default policy for resolving version conflicts between imported suites.

### `javac.lint.overrides`

Provides suite-wide javac lint overrides that projects inherit.

### `snippetsPattern`

Marks source snippets for features that scan or package snippet content.

### `spotbugs`

Sets the suite-wide default for whether Java projects participate in SpotBugs.

### `<suite-name>:...`

Any top-level key prefixed with the suite name and a colon is treated as suite-specific metadata.
mx keeps the original key in `suite.suiteDict` and also exposes the suffix as an attribute on the loaded suite object.
This allows suite extensions to read additional declarative configuration without adding arbitrary Python code to `suite.py`.

For example, GraalPython defines:

```python
"graalpython:pythonVersion": "3.12.8",
```

and its suite code reads that value as:

```python
SUITE.suiteDict[f"{SUITE.name}:pythonVersion"]
```

The same value is also available as `SUITE.pythonVersion`.

## Where custom behavior goes

The suite data file describes structure.
The suite extension module implements behavior.

If `mx.<suite>/mx_<suite>.py` exists, mx loads it as the suite's extension module.
This is where suites typically:

* register custom commands
* add gate tasks
* define custom project or distribution classes referenced via `"class"`
* dynamically create suite constituents that are awkward to spell out statically

See [Suite extension points](extension-points.md) for the supported hooks.

## Important constraints

* Keep `suite.py` declarative.
  Function calls, string concatenation and other arbitrary Python expressions are not supported.
* Put executable logic in `mx_<suite>.py`.
* Use static suite imports for normal, always-required dependencies.
* Use dynamic imports only for optional composition between suites.
* Treat `projects` as build inputs and `distributions` as packaged outputs; many mx behaviors are organized around that boundary.

## Related topics

* [Dynamic imports](dynamic-imports.md)
* [Suite extension points](extension-points.md)
* [Packaging with distributions](packaging.md)
