# README #

`mx` is a command line based tool for managing the development of (primarily) Java code. It includes a mechanism for specifying the dependencies as well as making it simple to build, test, run, update, etc the code and built artifacts. `mx` contains support for developing code spread across multiple source repositories. `mx` is written in Python (version 2.7) and is extensible.

The organizing principle of `mx` is a _suite_. A _suite_ is both a directory and the container for the components of the suite.
A suite component is either a _project_, _library_ or _distribution_. There are various flavors of each of these.
A suite may import and depend on other suites. For an execution of mx, exactly one suite is the primary suite.
This is either the suite in whose directory `mx` is executed or the value of the global `-p` mx option.
The set of suites reachable from the primary suite by transitive closure of the imports relation form the set that `mx` operates on.

### Running mx

`mx` can be run directly (i.e., `python2.7 mx/mx.py ...`), but is more commonly invoked via the `mx/mx` bash script (which includes a Python version check). Adding the `mx/` directory to your PATH simplifies executing `mx`. The `mx/mx.cmd` script should be used on Windows.

The general form of the `mx` command line is:

```
mx [global options] [command] [command-specific options]
```

If no options or command is specified, `mx` prints information on the available options and commands, which will include any suite-specfic options and commands. Help for a specific command is obtained via `mx help <command>`. Global options are expected to have wide applicability to many commands and as such precede the command to be executed.

For an example of `mx` usage, see the [README][1] for the Graal project.

Note: There is a Bash completion script for global options and commands, located in `bash_completion` directory. Install it for example by `source`ing this script in your `~/.bashrc` file. If used, a temporary file `/tmp/mx-bash-completion-<project-path-hash>` is created and used for better performance. This should be OK since the `/tmp` directory is usually cleaned on every system startup.  
[mx-honey](https://github.com/mukel/mx-honey) provides richer completions for `zsh` users.

### Suites

The definition of a suite and its components is in a file named `suite.py` in the _mx metadata directory_ of the
primary suite. This is the directory named `mx.<suite name>` in the suite's top level directory. For example,
for the `compiler` suite, it is `mx.compiler`. The format of `suite.py` is JSON with the following extensions:
* Python multi-line and single-quoted strings are supported
* Python hash comments are supported

### Java projects

Java source code is contained in a `project`. Here's an example of two [Graal compiler projects](https://github.com/oracle/graal/blob/b95d8827609d8b28993bb4468f5daa128a614e52/compiler/mx.compiler/suite.py#L129-L147):
```python
"org.graalvm.compiler.serviceprovider" : {
  "subDir" : "src",
  "sourceDirs" : ["src"],
  "dependencies" : ["JVMCI_SERVICES"],
  "checkstyle" : "org.graalvm.compiler.graph",
  "javaCompliance" : "8",
  "workingSets" : "API,Graal",
},

"org.graalvm.compiler.serviceprovider.jdk9" : {
  "subDir" : "src",
  "sourceDirs" : ["src"],
  "dependencies" : ["org.graalvm.compiler.serviceprovider"],
  "uses" : ["org.graalvm.compiler.serviceprovider.GraalServices.JMXService"],
  "checkstyle" : "org.graalvm.compiler.graph",
  "javaCompliance" : "9+",
  "multiReleaseJarVersion" : "9",
  "workingSets" : "API,Graal",
},
```

The `javaCompliance` attribute can be a single number (e.g. `8`), the lower bound of a range (e.g. `8+`) or a fixed range (e.g. `9..11`).
This attribute specifies the following information:
* The maximum Java language level used by the project. This is the lower bound in a range. It is also used at the value for the `-source`
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

### Java modules support

A distribution that has a `moduleInfo` attribute will result in a [Java module](https://openjdk.java.net/projects/jigsaw/quick-start) being
built from the distribution. The `moduleInfo` attribute must specify the name of the module and can include
other parts of a [module descriptor](https://docs.oracle.com/en/java/javase/11/docs/api/java.base/java/lang/module/ModuleDescriptor.html).

This is best shown with examples from [Truffle](https://github.com/oracle/graal/blob/master/truffle/mx.truffle/suite.py) and [Graal](https://github.com/oracle/graal/blob/master/compiler/mx.compiler/suite.py):

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
            "com.oracle.truffle.api.nodes to jdk.internal.vm.compiler",
            "com.oracle.truffle.api.impl to jdk.internal.vm.compiler, org.graalvm.locator",
            "com.oracle.truffle.api to jdk.internal.vm.compiler, org.graalvm.locator, com.oracle.graal.graal_enterprise",
            "com.oracle.truffle.api.object to jdk.internal.vm.compiler, com.oracle.graal.graal_enterprise",
            "com.oracle.truffle.object to jdk.internal.vm.compiler, com.oracle.graal.graal_enterprise",
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
    exports com.oracle.truffle.api to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler, org.graalvm.locator;
    exports com.oracle.truffle.api.impl to jdk.internal.vm.compiler, org.graalvm.locator;
    exports com.oracle.truffle.api.nodes to jdk.internal.vm.compiler;
    exports com.oracle.truffle.api.object to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler;
    exports com.oracle.truffle.object to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler;
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

The GRAAL distribution shows how a single `exports` attribute can be used to specify multiple `exports` clauses:

```
"GRAAL" : {
    "moduleInfo" : {
        "name" : "jdk.internal.vm.compiler",
        "exports" : [
            # Qualified exports of all packages in GRAAL to modules built from
            # ENTERPRISE_GRAAL and GRAAL_MANAGEMENT distributions
            "* to com.oracle.graal.graal_enterprise,jdk.internal.vm.compiler.management",
        ],
        ...
    },
    ...
},
```

This results info a `module-info.java` as that contains qualified exports, a small subset of which are shown below:
```
module jdk.internal.vm.compiler {
    ...
    exports org.graalvm.compiler.api.directives to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler.management;
    exports org.graalvm.compiler.api.replacements to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler.management;
    exports org.graalvm.compiler.api.runtime to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler.management;
    exports org.graalvm.compiler.asm to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler.management;
    exports org.graalvm.compiler.asm.aarch64 to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler.management;
    exports org.graalvm.compiler.asm.amd64 to com.oracle.graal.graal_enterprise, jdk.internal.vm.compiler.management;
    ...
```

The jars build for a distribution are in `<suite>/mxbuild/dists/jdk*/`. The modular jars are in the `jdk<N>` directories
where `N >= 9`. There is a modular jar built for each JDK version denoted by the `javaCompliance` values of the distribution's
constituent projects.

#### Specifying required modules

If a project uses a package from a module other than `java.base` or a module
implied by a dependency (e.g., the [`JVMCI_API` library](https://github.com/oracle/graal/blob/1655543b5670948e56333827f3a8f65e1ba8f3c6/compiler/mx.compiler/suite.py#L46-L55)
defined by Graal), it must specify these additional modules with the `requires` attribute.
For example:
```
"org.graalvm.compiler.hotspot.management.jdk11" : {
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
  `org.graalvm.compiler.hotspot.amd64` depends on `org.graalvm.compiler.hotspot`
  and the classes of both these projects are contained in the `jdk.internal.vm.compiler`
  module. When compiling `org.graalvm.compiler.hotspot.amd64`, we must compile against
  classes in `org.graalvm.compiler.hotspot` as they might be different (i.e., newer)
  than the classes in `jdk.internal.vm.compiler`. The value of `--limit-modules` will
  omit `jdk.internal.vm.compiler` in this case to achieve this hiding. In the absence
  of a `requires` attribute, only the `java.base` module is observable when compiling
  on JDK 9+.

#### Use of concealed packages

Concealed packages are those defined by a module but not exported by the module.
If a project uses concealed packages, it must specify a `requiresConcealed` attribute
denoting the concealed packages it accesses. For example:
```
"org.graalvm.compiler.lir.aarch64.jdk11" : {
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
command line when the `org.graalvm.compiler.lir.aarch64.jdk11` project is compiled by a
JDK 9+ `javac`.

Note that the `requires` and `requiresConcealed` attributes only apply to projects with
a minimum `javaCompliance` value of 9 or greater. When `javac` from jdk 9+ is used in
conjunction with `-source 8` (as will be the case for projects with a minimum `javaCompliance`
of 8 or less), all classes in the JDK are observable. However, if an 8 project would need a
`requires` or `requiresConcealed` attribute were it a 9+ project, then these attributes must be
applied to any module containing the project. For example,
`org.graalvm.compiler.serviceprovider` has `"javaCompliance" : "8+"` and contains
code that imports `sun.misc.Unsafe`. Since `org.graalvm.compiler.serviceprovider`
is part of the `jdk.internal.vm.compiler` module defined by the `GRAAL` distribution,
`GRAAL` must include a `requires` attribute in its `moduleInfo` attribute:
```
"GRAAL" : {
    "moduleInfo" : {
        "name" : "jdk.internal.vm.compiler",
        "requires" : ["jdk.unsupported"],
        ...
    }
}
```

Modules can be removed from the JDK. For example, [JDK-8255616](https://bugs.openjdk.java.net/browse/JDK-8255616)
removed the `jdk.aot`, `jdk.internal.vm.compile` and `jdk.internal.vm.compile.management` modules from standard JDK binaries
as of JDK 16. Any `requiresConcealed` attributes targeting these modules must use a Java compliance qualifier so that
the relevant sources can still be built on JDK 16:
```
"com.oracle.svm.enterprise.jdk11.test": {
    ...
    "requiresConcealed": {
        "jdk.internal.vm.compiler@11..15": [
            "org.graalvm.compiler.serviceprovider"
        ],
        ...
    }
}
```

As shown above, a module name in a `requiresConcealed` attribute can be qualified by appending `@` followed by
a valid Java compliance specifier. Such a module will be ignored if the JDK version used to compile the sources
is not matched by the specified Java compliance.

### Selecting JDKs

Specifying JDKs to mx is done via the `--java-home` and `--extra-java-homes` options or
via the `JAVA_HOME` and `EXTRA_JAVA_HOMES` environment variables.
An option has precedence over the corresponding environment variable.
Mx comes with a [`select_jdk.py`](select_jdk.py) helper that simplifies
switching between different values for `JAVA_HOME` and `EXTRA_JAVA_HOMES`.

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

### URL rewriting

Mx includes support for the primary suite to be able to override the source URLs of imported suites.
The suite level `urlrewrites` attribute allows regular expression URL rewriting. For example:
```
  "urlrewrites" : [
    {
      "https://git.acme.com/(.*).git" : {
        "replacement" : r”https://my.company.com/foo-git-cache/\1.git",
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

### mx versioning ###

`mx` uses a `major`.`minor`.`patch` versioning scheme.  To figure out if the
version is sufficient for a given `mx` suite, first compare the major version
number of your `mx` version against the major number of the required version
specified in the suite.  If these versions are not equal, you cannot expect
`mx` to be compatible with this suite.  The minor number has to be greater or
equal to the specified minor version number.  Compatibility is ensured
regardless of the patch level.  However, if your patch level is lower than the
required patch level you might trigger bugs in `mx`.

From an `mx` developer point of view this versioning scheme enforces the following
update policy:
- If you make a change that prevents the new version of `mx` from loading
older files, increase the major number and reset both the minor and the patch
level to 0.
- If you add new functionality without breaking backward compatibility, leave
the major as it is, increase the minor number and reset the patch level.
- If you only fixed a bug without changing the public API (i.e., all files for
the current version can still be loaded with the new version and vice versa),
leave the major and minor versions as they are but increase the patch level.

The version update strategy is designed to help users to detect if their `mx`
version is compatible with a suite.  Thus, changes to the code that do not
affect users do not require a change in the version number.  See the following
examples.  In these examples, by *user* we mean command line clients or `mx`
extensions (for example `mx_graal-core.py`).

- "I found a for-loop in the code that could be expressed using a map
function. I changed it accordingly."  This change has no influence on users.
Thus, no version change is required!

- "I added a new `mx` command."  Since this function was not available to
users before, old scripts will continue to work with the new version.  New
scripts, however, might not work with old versions.  This is a minor update
and requires a new minor number and a reset of the patch level.

- "I fixed a bug that caused a wrong result of a publicly available function."
This is a bugfix that is user visible.  The patch level should be increased
since users of old versions can expect at least the bug that was just fixed.

- "I fixed some documentation."  This fix has no impact on the usage of `mx`
and should thus not change the version of `mx`.

- "I fixed a function.  The result now differs from the results before.  A
user cannot call this function."  Since this function is invisible to the
user, no version update is required.

- "I fixed a function.  The result now differs from the results before.  A
user could call this function."  Since the semantics of the function changed
and the function is part of the API, old scripts might not work properly
anymore.  Since this change is not backward compatible, this is a major update.

- "I added some internal functions."  Since the functions are internal, they
have no impact on users.  No version changed is required.

- "I added some new commands."  Since the commands did not change the old
commands, old scripts will continue to work as expected.  New scripts that
depend on the new commands will not work with older versions of `mx`.  Thus,
we need a new minor release.

- "I removed some commands from `mx`.  There are alternative commands now."
This change essentially changed the API.  Thus, we require a new major release.

[1]: https://github.com/graalvm/graal/blob/master/compiler/README.md
