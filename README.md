# README #

`mx` is a command line based tool for managing the development of (primarily) Java code.
It includes a mechanism for specifying the dependencies as well as making it simple to build,
test, run, update, etc the code and built artifacts. `mx` contains support for developing code
spread across multiple source repositories. `mx` is written in Python and is extensible.

The organizing principle of `mx` is a _suite_. A _suite_ is both a directory and the container for the components of the suite.
A suite component is either a _project_, _library_ or _distribution_. There are various flavors of each of these.
A suite may import and depend on other suites. For an execution of mx, exactly one suite is the primary suite.
This is either the suite in whose directory `mx` is executed or the value of the global `-p` mx option.
The set of suites reachable from the primary suite by transitive closure of the imports relation form the set that `mx` operates on.

### Running mx

`mx` can be run directly (i.e., `python mx/mx.py ...`), but is more commonly invoked via the `mx/mx` bash script.
Adding the `mx/` directory to your PATH simplifies executing `mx`. The `mx/mx.cmd` script should be used on Windows.

The general form of the `mx` command line is:

```
mx [global options] [command] [command-specific options]
```

If no options or command is specified, `mx` prints information on the available options and commands,
which will include any suite-specific options and commands. Help for a specific command is obtained
via `mx help <command>`. Global options are expected to have wide applicability to many commands and as
such precede the command to be executed.

For an example of `mx` usage, see [README.md](https://github.com/oracle/graal/blob/master/compiler/README.md).

Note: There is a Bash completion script for global options and commands, located in `bash_completion` directory.
Install it for example by `source`ing this script in your `~/.bashrc` file. If used, a temporary file
`/tmp/mx-bash-completion-<project-path-hash>` is created and used for better performance.

[mx-honey](https://github.com/mukel/mx-honey) provides richer completions for `zsh` users.

### Suites

The definition of a suite and its components is in a file named `suite.py` in the _mx metadata directory_ of the
primary suite. This is the directory named `mx.<suite name>` in the suite's top level directory. For example,
for the `compiler` suite, it is `mx.compiler`. The format of `suite.py` is JSON with the following extensions:
* Python multi-line and single-quoted strings are supported
* Python hash-prefixed comments are supported

### Java projects

Java source code is contained in a `project`. Here's an example of two [Graal compiler projects](https://github.com/oracle/graal/blob/b95d8827609d8b28993bb4468f5daa128a614e52/compiler/mx.compiler/suite.py#L129-L147):
```python
"jdk.graal.compiler.serviceprovider" : {
  "subDir" : "src",
  "sourceDirs" : ["src"],
  "dependencies" : ["JVMCI_SERVICES"],
  "checkstyle" : "jdk.graal.compiler.graph",
  "javaCompliance" : "8",
  "workingSets" : "API,Graal",
},

"jdk.graal.compiler.serviceprovider.jdk9" : {
  "subDir" : "src",
  "sourceDirs" : ["src"],
  "dependencies" : ["jdk.graal.compiler.serviceprovider"],
  "uses" : ["jdk.graal.compiler.serviceprovider.GraalServices.JMXService"],
  "checkstyle" : "jdk.graal.compiler.graph",
  "javaCompliance" : "9+",
  "multiReleaseJarVersion" : "9",
  "workingSets" : "API,Graal",
},
```

The `javaCompliance` attribute can be a single number (e.g. `8`), the lower bound of a range (e.g. `8+`) or a fixed range (e.g. `9..11`).
This attribute specifies the following information:
* The maximum Java language level used by the project. This is the lower bound in a range. It is also used as the value for the `-source`
and `-target` javac options when compiling the project.
* The JDKs providing any internal JDK API used by the project. A project that does not use any internal JDK API should specify an
open range (e.g. `8+`). Otherwise, a JDK matching the exact version or range is required to compile the project.

The `multiReleaseJarVersion` attribute is explained in the "Versioning sources for different JDK releases" section below.

### Java distributions

A distribution encompasses one or more Java projects and enables the class files and related resources from projects
to be packaged into a jar file. If a distribution declares itself as a module (see [Java modules support](#java-modules-support)),
a JMOD file will also be produced when the distribution is built. The path to the jar file for a distribution is given
by `mx paths <distribution name>`. For example:
```
> mx paths GRAAL
/Users/dnsimon/graal/graal/compiler/mxbuild/dists/jdk11/graal.jar
```

When building the jar for a distribution, mx will create the layout for the jar in a directory
that is a sibling of the distribution's jar path. For example:

```
├── graal.jar
├── graal.jar.files
│   ├── META-INF
│   └── org
```

For efficiency, the files under the `*.files` hierarchy will be symlinks where possible. On Windows,
creating symlinks is a privileged operation and so if symlinks cannot be created, files are copied
instead. There are plenty of internet resources describing how to elevate your privileges on
Windows to enable symlinking (e.g. [here](https://www.scivision.dev/windows-symbolic-link-permission-enable/)).

#### Exploded builds

By default, mx will produce a jar for each distribution. If a distribution defines a module, the jar is further processed
to make it a [multi-release](#versioning-sources-for-different-jdk-releases)
[modular jar](https://openjdk.java.net/projects/jigsaw/spec/sotms/#module-artifacts) and a jmod file is also created.
Creating the jar and jmod files increases build time. For faster development, it's possible to
leave a distribution in its exploded form, a directory with the same layout as the jar structure. To work in
this mode, set `MX_BUILD_EXPLODED=true`. Also, ensure that exactly one
JDK is specified by the union of `JAVA_HOME` and `EXTRA_JAVA_HOMES` (required since there is no equivalent of
multi-release jar support for directories).

Using `MX_BUILD_EXPLODED=true` is roughly equivalent to
[building the OpenJDK](https://github.com/openjdk/jdk/blob/master/doc/building.md#running-make) with `make` instead of `make images`.

Note that `MX_BUILD_EXPLODED=true` should not be used when building for deployment.

### Java modules support

A distribution that has a `moduleInfo` attribute will result in a [Java module](https://openjdk.java.net/projects/jigsaw/quick-start) being
built from the distribution. The `moduleInfo` attribute must specify the name of the module and can include
other parts of a [module descriptor](https://docs.oracle.com/en/java/javase/11/docs/api/java.base/java/lang/module/ModuleDescriptor.html).

This is best shown with examples from [Truffle](https://github.com/oracle/graal/blob/master/truffle/mx.truffle/suite.py)
and [Graal](https://github.com/oracle/graal/blob/master/compiler/mx.compiler/suite.py):

Here is an extract from the definition of the `TRUFFLE_API` distribution which produces the
`org.graavm.truffle` module:
```
"TRUFFLE_API" : {
    "moduleInfo" : {
        "name" : "org.graalvm.truffle",
        "requires" : [
            "static java.desktop"
        ],
        "exports" : [
            "com.oracle.truffle.api.nodes to jdk.graal.compiler",
            "com.oracle.truffle.api.impl to jdk.graal.compiler, org.graalvm.locator",
            "com.oracle.truffle.api to jdk.graal.compiler, org.graalvm.locator, com.oracle.graal.graal_enterprise",
            "com.oracle.truffle.api.object to jdk.graal.compiler, com.oracle.graal.graal_enterprise",
            "com.oracle.truffle.object to jdk.graal.compiler, com.oracle.graal.graal_enterprise",
        ],
        "uses" : [
          "com.oracle.truffle.api.TruffleRuntimeAccess",
          "java.nio.file.spi.FileTypeDetector",
          "com.oracle.truffle.api.impl.TruffleLocator",
        ],
    },
    ...
    "distDependencies" : [
        # These distributions must also have `moduleInfo` attributes and the corresponding
        # modules will be added to the set of `requires` for this module.
        "sdk:GRAAL_SDK"
    ],
}
```

The `module-info.java` created by `mx` from the above is:
```
module org.graalvm.truffle {
    requires java.base;
    requires static java.desktop;
    requires java.logging;
    requires jdk.unsupported;
    requires transitive org.graalvm.sdk;
    exports com.oracle.truffle.api to com.oracle.graal.graal_enterprise, jdk.graal.compiler, org.graalvm.locator;
    exports com.oracle.truffle.api.impl to jdk.graal.compiler, org.graalvm.locator;
    exports com.oracle.truffle.api.nodes to jdk.graal.compiler;
    exports com.oracle.truffle.api.object to com.oracle.graal.graal_enterprise, jdk.graal.compiler;
    exports com.oracle.truffle.object to com.oracle.graal.graal_enterprise, jdk.graal.compiler;
    uses com.oracle.truffle.api.TruffleRuntimeAccess;
    uses com.oracle.truffle.api.impl.TruffleLocator;
    uses com.oracle.truffle.api.object.LayoutFactory;
    uses java.nio.file.spi.FileTypeDetector;
    provides com.oracle.truffle.api.object.LayoutFactory with com.oracle.truffle.object.basic.DefaultLayoutFactory;
    provides org.graalvm.polyglot.impl.AbstractPolyglotImpl with com.oracle.truffle.polyglot.PolyglotImpl;
    // conceals: com.oracle.truffle.api.debug
    // conceals: com.oracle.truffle.api.debug.impl
    // conceals: com.oracle.truffle.api.dsl
    // conceals: com.oracle.truffle.api.frame
    // conceals: com.oracle.truffle.api.instrumentation
    // conceals: com.oracle.truffle.api.interop
    // conceals: com.oracle.truffle.api.interop.impl
    // conceals: com.oracle.truffle.api.io
    // conceals: com.oracle.truffle.api.library
    // conceals: com.oracle.truffle.api.object.dsl
    // conceals: com.oracle.truffle.api.profilesLayoutFactory
    // conceals: com.oracle.truffle.api.source
    // conceals: com.oracle.truffle.api.utilities
    // conceals: com.oracle.truffle.object.basic
    // conceals: com.oracle.truffle.polyglot
    // jarpath: /Users/dnsimon/hs/graal/truffle/mxbuild/dists/jdk11/truffle-api.jar
    // dist: TRUFFLE_API
    // modulepath: org.graalvm.sdk
}
```

The `provides` clauses are automatically derived from the `META-INF/services/` directory in the distribution's jar file.
The generation of the `provides` clauses can be modified by utilizing the `ignoredServiceTypes` attribute.
Here is an extract from the definition of the `TRUFFLE_NFI` distribution, which prevents adding `DefaultExportProvider` and
`EagerExportProvider` implementations to `provides` clauses.
```
"TRUFFLE_NFI" : {
    "moduleInfo" : {
        "name" : "com.oracle.truffle.truffle_nfi",
        "exports" : [
            "com.oracle.truffle.nfi.api",
            "com.oracle.truffle.nfi.backend.spi",
            "com.oracle.truffle.nfi.backend.spi.types",
            "com.oracle.truffle.nfi.backend.spi.util",
        ],
        "ignoredServiceTypes" : [
            "com.oracle.truffle.api.library.DefaultExportProvider",
            "com.oracle.truffle.api.library.EagerExportProvider",
        ],
    }
    ...
}
```

The GRAAL distribution shows how a single `exports` attribute can be used to specify multiple `exports` clauses:

```
"GRAAL" : {
    "moduleInfo" : {
        "name" : "jdk.graal.compiler",
        "exports" : [
            # Qualified exports of all packages in GRAAL to modules built from
            # ENTERPRISE_GRAAL and GRAAL_MANAGEMENT distributions
            "* to com.oracle.graal.graal_enterprise,jdk.graal.compiler.management",
        ],
        ...
    },
    ...
},
```

This results info a `module-info.java` as that contains qualified exports, a small subset of which are shown below:
```
module jdk.graal.compiler {
    ...
    exports jdk.graal.compiler.api.directives to com.oracle.graal.graal_enterprise, jdk.graal.compiler.management;
    exports jdk.graal.compiler.api.replacements to com.oracle.graal.graal_enterprise, jdk.graal.compiler.management;
    exports jdk.graal.compiler.api.runtime to com.oracle.graal.graal_enterprise, jdk.graal.compiler.management;
    exports jdk.graal.compiler.asm to com.oracle.graal.graal_enterprise, jdk.graal.compiler.management;
    exports jdk.graal.compiler.asm.aarch64 to com.oracle.graal.graal_enterprise, jdk.graal.compiler.management;
    exports jdk.graal.compiler.asm.amd64 to com.oracle.graal.graal_enterprise, jdk.graal.compiler.management;
    ...
```

The jars build for a distribution are in `<suite>/mxbuild/dists/jdk*/`. The modular jars are in the `jdk<N>` directories
where `N >= 9`. There is a modular jar built for each JDK version denoted by the `javaCompliance` values of the distribution's
constituent projects.

#### Specifying required modules

If a project with a Java compliance >= 9 uses a package from a module other than `java.base`, it must specify these
additional modules with the `requires` attribute. For example:
```
"jdk.graal.compiler.hotspot.management.jdk11" : {
    ...
    "requires" : [
        "jdk.management"
    ],
    "javaCompliance" : "11+",
    ...
},
```
The `requires` attribute is used for two purposes:
* As input to the `requires` attribute of the descriptor for the module
  encapsulating the project.
* To derive a value for the `--limit-modules` javac option
  which restricts the modules observable during compilation. This is required to support
  separate compilation of projects that are part of a JDK module. For example,
  `jdk.graal.compiler.hotspot.amd64` depends on `jdk.graal.compiler.hotspot`
  and the classes of both these projects are contained in the `jdk.graal.compiler`
  module. When compiling `jdk.graal.compiler.hotspot.amd64`, we must compile against
  classes in `jdk.graal.compiler.hotspot` as they might be different (i.e., newer)
  than the classes in `jdk.graal.compiler`. The value of `--limit-modules` will
  omit `jdk.graal.compiler` in this case to achieve this hiding. In the absence
  of a `requires` attribute, only the `java.base` module is observable when compiling
  on JDK 9+.

#### Use of concealed packages

Concealed packages are those defined by a module but not exported by the module.
If a project uses concealed packages, it must specify a `requiresConcealed` attribute
denoting the concealed packages it accesses. For example:
```
"jdk.graal.compiler.lir.aarch64.jdk11" : {
    "requiresConcealed" : {
        "jdk.internal.vm.ci" : [
            "jdk.vm.ci.aarch64",
            "jdk.vm.ci.code",
        ],
    },
    "javaCompliance" : "11+",
},
```
This will result in `--add-exports=jdk.internal.vm.ci/jdk.vm.ci.aarch64=ALL-UNNAMED` and
`--add-exports=jdk.internal.vm.ci/jdk.vm.ci.code=ALL-UNNAMED` being added to the `javac`
command line when the `jdk.graal.compiler.lir.aarch64.jdk11` project is compiled by a
JDK 9+ `javac`.

Note that the `requires` and `requiresConcealed` attributes only apply to projects with
a minimum `javaCompliance` value of 9 or greater. When `javac` from jdk 9+ is used in
conjunction with `-source 8` (as will be the case for projects with a minimum `javaCompliance`
of 8 or less), all classes in the JDK are observable. However, if an 8 project would need a
`requires` or `requiresConcealed` attribute were it a 9+ project, then these attributes must be
applied to any module containing the project. For example,
`jdk.graal.compiler.serviceprovider` has `"javaCompliance" : "8+"` and contains
code that imports `sun.misc.Unsafe`. Since `jdk.graal.compiler.serviceprovider`
is part of the `jdk.graal.compiler` module defined by the `GRAAL` distribution,
`GRAAL` must include a `requires` attribute in its `moduleInfo` attribute:
```
"GRAAL" : {
    "moduleInfo" : {
        "name" : "jdk.graal.compiler",
        "requires" : ["jdk.unsupported"],
        ...
    }
}
```

Modules can be removed from the JDK. For example, [JDK-8255616](https://bugs.openjdk.java.net/browse/JDK-8255616)
removed the `jdk.aot`, `jdk.internal.vm.compiler` and `jdk.internal.vm.compiler.management` modules from standard JDK binaries
as of JDK 16. Any `requiresConcealed` attributes targeting these modules must use a Java compliance qualifier so that
the relevant sources can still be built on JDK 16:
```
"com.oracle.svm.enterprise.jdk11.test": {
    ...
    "requiresConcealed": {
        "jdk.graal.compiler@11..15": [
            "jdk.graal.compiler.serviceprovider"
        ],
        ...
    }
}
```

As shown above, a module name in a `requiresConcealed` attribute can be qualified by appending `@` followed by
a valid Java compliance specifier. Such a module will be ignored if the JDK version used to compile the sources
is not matched by the specified Java compliance. This also works for the regular `requires` attribute. E.g.
```
    "requires": [
        ...
        "jdk.scripting.nashorn@11..14",
    ],
    ...
```
is needed to ensure that a given module requires module `jdk.scripting.nashorn` only when the specified compliance matches.

### Selecting JDKs

Specifying JDKs to mx is done via the `--java-home` and `--extra-java-homes` options or
via the `JAVA_HOME` and `EXTRA_JAVA_HOMES` environment variables.
An option has precedence over the corresponding environment variable.
Mx comes with a [`select_jdk.py`](select_jdk.py) helper that simplifies
switching between different values for `JAVA_HOME` and `EXTRA_JAVA_HOMES`.

#### Install a JDK with fetch-jdk

The `mx fetch-jdk` command can download and install JDKs defined in JSON files. See `mx fetch-jdk --help` for more detail.    

### Generated artifacts

The build artifacts of mx are in directories separate from the source file directories.
Output for platform dependent suite constituents is under a directory whose name
reflects the current platform. For example:

```
<suite>/mxbuild/<project>               # Platform independent project
<suite>/mxbuild/darwin-amd64/<project>  # Platform dependent project
```

Partitioning build output to take the platform into account has the following advantages:
* A file system shared between different platforms (e.g. via NFS or virtualization host/guest
 file system sharing) keeps its platform dependent output separated.

Unless `MX_OUTPUT_ROOT_INCLUDES_CONFIG=false` then:
* The output for JDK dependent suite constituents is under a directory reflecting the
 JDK(s) specified by `JAVA_HOME` and `EXTRA_JAVA_HOMES`.
* The output for platform and JDK dependent suite constituents is under a directory
 reflecting both the platform and JDKs.

For example:

```
<suite>/mxbuild/jdk16+8/<project>               # JDK dependent project
<suite>/mxbuild/darwin-amd64/<project>          # Platform dependent project
<suite>/mxbuild/darwin-amd64-jdk16+8/<project>  # Platform and JDK dependent project
```

Partitioning build output to take JDK configuration into account has the following advantages:
* Avoids re-compilation after changing the value of `JAVA_HOME` or `EXTRA_JAVA_HOMES` in the
 case where no sources have changed since `mx build` was last executed with the new values.
* Avoid issues related to API changes between JDK versions. If only public JDK API was
 used by Java projects, this could be solved with the `--release` option introduced by
 [JEP 247](https://openjdk.java.net/jeps/247). However, a significant number of mx managed
 projects use JDK internal API in which case `--release` does not help.

Note that IDE configurations ignore `MX_OUTPUT_ROOT_INCLUDES_CONFIG` and so must be regenerated after
changing the value of `JAVA_HOME` or `EXTRA_JAVA_HOMES` if you want output generated by an IDE to be
visible to subsequent mx commands.

The JDK configuration dependent layout of build artifacts is best shown by an example.
Consider the following directory tree containing `graal` and `truffleruby`
repositories where `graal` defines the suites `compiler`, `truffle` and `sdk`
and `truffleruby` defines a single `truffleruby` suite:
```
ws
├── graal
│   ├── compiler
│   ├── sdk
│   └── truffle
└── truffleruby
```

With this layout when working on macOS with `$JAVA_HOME` set to a JDK 8
and `$EXTRA_JAVA_HOMES` set to a JDK 16, after running `mx build`, the layout will be:

```
ws
├── graal
│   ├── compiler
│   │   └── mxbuild
│   │       ├── darwin-amd64
│   │       │   └── <project>
│   │       └── jdk8+16
│   │           └── <project>
│   ├── sdk
│   │   └── mxbuild
│   │       ├── darwin-amd64
│   │       │   └── <project>
│   │       └── jdk8+16
│   │           └── <project>
│   └── truffle
│       └── mxbuild
│           ├── darwin-amd64
│           │   └── <project>
│           └── jdk8+16
│               └── <project>
└── truffleruby
    └── mxbuild
        ├── darwin-amd64
        │   └── <project>
        └── jdk8+16
            └── <project>
```

### Unit testing with Junit <a name="junit"></a>

The `unittest` command supports running Junit tests in `mx` suites.

The unit test harness will use any `org.junit.runner.notification.RunListener`
objects available via `java.util.ServiceLoader.load()`.

Executing tests on JDK 9 or later can be complicated if the tests access
packages that are publicly available in JDK 8 or earlier but are not public as
of JDK 9. That is, the packages are *concealed* by their declaring module. Such
tests can be compiled simply enough by specifying their Java compliance as
"1.8=". Running the tests on JDK 9 however requires that the concealed packages
are exported to the test classes. To achieve this, an `AddExports` annotation
should be applied to the test class requiring the export or to any of its super
classes or super interfaces. To avoid the need for a dependency on mx, unittest
harness simply looks for an annotation named `AddExports` that matches the
following definition:

```
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Specifies packages concealed in JDK modules used by a test. The mx unit test runner will ensure
 * the packages are exported to the module containing annotated test class.
 */
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.TYPE)
public @interface AddExports {
    /**
     * The qualified name of the concealed package(s) in {@code <module>/<package>} format (e.g.,
     * "jdk.vm.ci/jdk.vm.ci.code").
     */
    String[] value() default "";
}
```

#### Coverage testing with JaCoCo

To enable code coverage testing with JaCoCo, the JaCoCo agent needs to be
injected through VM command line arguments. For this, mx provides the
convenience method `mx_gate.get_jacoco_agent_args()` which returns a list of
those arguments if coverage is requested (e.g. by using
`mx gate --jacocout ...`), otherwise `None`.
[Here](https://github.com/oracle/graal/blob/07412155ab8edc6b67b819c215f0d6dc986aef59/compiler/mx.compiler/mx_compiler.py#L746)
is an example how it is used to enable coverage testing of the sources of the
Graal compiler.
Running code with the JaCoCo agent enabled outputs a `jacoco.exec` which can be
converted into an HTML or CSV report with the `mx jacocoreport` command.

The packages or classes to be included in the JaCoCo report can be customized
by importing `mx_gate` and using the helper functions:

- `add_jacoco_includes` (adds one or more package patterns to the list of packages to include in the report)
- `add_jacoco_excludes` (adds one or more package patterns to the list of packages to exclude from the report)
- `add_jacoco_excluded_annotations` (adds one or more annotations to the list of annotations that will cause a class to be excluded from the report)

The include patterns can include an explicit trailing `.*` wildcard match. The exclude patterns have an implicit trailing wildcard match. Annotation names added to the annotation exclusion list must start with an `@` character.

As an example from `mx_compiler.py`:
```
mx_gate.add_jacoco_includes(['org.graalvm.*'])
mx_gate.add_jacoco_excludes(['com.oracle.truffle.*'])
mx_gate.add_jacoco_excluded_annotations(['@Snippet', '@ClassSubstitution'])
```
This adds classes from packages starting with org.graalvm to the report, excludes classes in packages startng with com.oracle.truffle and also excludes classes annotated with `@Snippet` and `@ClassSubstitution`.

To omit excluded classes from the JaCoCo data and report use the gate option `--jacoco-omit-excluded`.

### Versioning sources for different JDK releases

Mx includes support for multiple versions of a Java class. The mechanism is inspired by and
similar to [multi-release jars](https://docs.oracle.com/javase/10/docs/specs/jar/jar.html#multi-release-jar-files).
A versioned Java class has a base version and one or more versioned copies. The public signature of each
copy (i.e., methods and fields accessed from outside the source file) must be identical.
Note that the only API that is visible from the JAR is the one from the base version.

Versioned classes for JDK 9 or later need to be in a project with a `javaCompliance` greater than
or equal to 9 and a `multiReleaseJarVersion` attribute whose value is also greater or equal to 9.
The versioned project must have the base project as a dependency.

Versioned classes for JDK 8 or earlier need to be in a project with a `javaCompliance` less than or
equal to 8 and an `overlayTarget` attribute denoting the base project.

### Profiling with proftool

Mx includes `proftool`, a utility for capturing and examining profiles of Java programs.
Further details are [here](README-proftool.md).

### URL rewriting

Mx includes support for the primary suite to be able to override the source URLs of imported suites.
The suite level `urlrewrites` attribute allows regular expression URL rewriting, and, optionally, digest rewriting. For example:
```
  "urlrewrites" : [
    {
      "https://git.acme.com/(.*).git" : {
        "replacement" : r”https://my.company.com/foo-git-cache/\1.git",
        "digest" : "sha1:da39a3ee5e6b4b0d3255bfef95601890afd80709",
      }
    },
    {
      "https://hg.acme.com/(.*)" : {
        "replacement" : r”https://my.company.com/foo-hg-cache/\1",
      }
    }
  ],
```
The rules are applied in definition order. Only rewrite rules from the primary suite are used meaning a suite may have to replicate the rewrite rules of its suite dependencies.
This allows the primary suite to retain full control over where its dependencies are sourced from.

Rewrite rules can also be specified by the `MX_URLREWRITES` environment variable.
The value of this variable must either be a JSON object describing a single rewrite rule, a JSON array describing a list of rewrite rules or a file containing one of these JSON values.
Rewrites rules specified by `MX_URLREWRITES` are applied after rules specified by the primary suite.

### IDE configuration generation

Mx supports generating IDE configurations using the `mx ideinit` command.
There are also specific commands that generate configurations for Eclipse (`mx eclipseinit`), Netbeans (`mx netbeansinit`) or IntelliJ (`mx intellijinit`) individually.
Please see [here](docs/IDE.md) for details.

### Environment variable processing

Suites might require various environment variables to be defined for
the suite to work and mx provides `env` files to cache this
information for a suite.  Each suite can have an `env` file in
_suite_/mx._suite_/`env` and a default env file can be provided for
the user in ~/.mx/env.  Env files are loaded in the following order
and override any value provided by the shell environment.

1.  ~/.mx/`env` is loaded first.

2.  The primary suite's `env` file is loaded before loading of the suites begins.

3.  The env files of any subsuites are loaded in a depth first fashion
    such that subsuite `env` files are loaded before their dependents.

4.  The primary suite's `env` file is reloaded so that it overrides
    any definitions provided by subsuites.

The `-v` option to `mx` will show the loading of `env` files during suite parsing.

### Multiple suites per repository

Sometimes it might be convenient to group multiple suites inside a single repository.
In particular, this helps ensure that all these suites are synchronized and tested together.

* A suite inside a 'big repo' must be in a directory that has the same name as the suite
* If you depend on a suite that is inside a 'big repo', you have to set `subdir` to `True` in the suite import.
* If you depend on a suite that is in the same 'big repo' as the current suite, you should not specify `urls` in the suite import.
* In order to `sclone` something that is inside a 'big repo' you have to use the `--subdir` argument for `sclone` which tells in which directory the suite that you want to clone is
* In order to dynamically import a suite that is inside a 'big repo' you have to use `--dynamicimport bigrepo/suite` (e.g., `--dynamicimport graal-enterprise/substratrevm`)

Note that a suite in a "big repo" should not have a dependency to a suite in a different repository that in turn has a transitive dependency to the same "big repo".
In other words, there should be no back-and-forth to the same repo.


### Preview features

Java projects may use language or runtime features which are considered _preview features_ in certain Java versions, in which case preview features must be enabled for compilation (`--enable-preview`).
This is specified using the `javaPreviewNeeded` attribute, which is a version specification in the same format as `javaCompliance`, for example: `"javaPreviewNeeded": "19..20"`
If the compiling JDK matches that version or version range, preview features are enabled for compilation.
Given that javac and the JVM must be on the same JDK version for preview features (see [here](https://nipafx.dev/enable-preview-language-features/#same-version-for-feature-compiler-and-jvm) for details),
compiling a project with preview features will force the javac `-source` and `-target` options to `N` where `N` is
the minimum of:
* the version of the JDK being used for compilation (i.e. `JAVA_HOME`) and
* the lowest version where `--enable-preview` is not needed.

The following table of examples should make this clearer:

| JDK | javaPreviewNeeded | -target / -source | --enable-preview |
| ----|-------------------|-------------------|------------------|
| 19  | 19+               | 19                | Yes              |
| 20  | 19+               | 20                | Yes              |
| 20  | 19                | 20                | No               |
| 21  | 19                | 20                | No               |
| 22  | 20                | 21                | No               |
| 22  | 19..20            | 21                | No               |

### System dependent configuration

A project can specify system dependent configuration options depending on which
operating system and architecture are in use. The following example shows how
the `bar` property can be set to `A` on Windows and `B` on all other operating
systems.

```python
"project" : {
  "foo" : "A",
  "os" : {
    "windows" : {
      "bar" : "A"
    },
    "<others>" : {
      "bar" : "B"
    }
  }
}
```

Commonly supported operating system names are `darwin`, `linux` and `windows`.
The `<others>` value can be used as a wildcard to match any other operating
system. A warning is emitted if no operating system is matched.

The `arch` property can be used to alter the configuration depending on which
system architecture is used. Common examples of examples of system architectures
are `amd64` and `aarch64`. The following example shows how the `bar` property
can be set to `A` on amd64 and to `B` on all other platforms.

```python
"project" : {
  "foo" : "A",
  "arch" : {
    "amd64" : {
      "bar" : "A"
    },
    "<others>" : {
      "bar" : "B"
    }
  }
}
```

Configuration options that should depend on both the operating system and the
architecture value can be specified using the `os_arch` property as follows. The
following configuration example sets the property `bar` to `A` on amd64 linux
systems, and to `B` for all other systems.

```python
"project" : {
  "foo" : "A",
  "os_arch" : {
    "linux" : {
      "amd64" : {
        "bar" : "A"
      },
      "<others>" : {
        "bar" : "B"
      }
    },
    "<others>" : {
      "<others>" : {
        "bar" : "B"
      }
    }
  }
}
```

It is only possible to specify one of either the `os`, `arch` or `os_arch`
options for any project.
