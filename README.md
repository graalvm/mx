# README #

`mx` is a command line based tool for managing the development of (primarily) Java code. It includes a mechanism for specifying the dependencies as well as making it simple to build, test, run, update, etc the code and built artifacts. `mx` contains support for developing code spread across multiple source repositories. `mx` is written in Python (version 2.7) and is extensible.

The organizing principle of `mx` is a _suite_. A _suite_ is a directory containing one or more _projects_ and also under the control of a version control system. A suite may import one or more dependent suites. One suite is designated as the primary suite. This is normally the suite in whose directory `mx` is executed. The set of suites that are reachable from the primary suite by transitive closure of the imports relation form the set that `mx` operates on. The set of suites implicitly defines the set of projects. The action of building a suite is to compile the code in the projects and generate one or more distributions which are 'jar' files containing the compiled classes and related metadata.

### Running mx ###

`mx` can be run directly (i.e., `python2.7 mx/mx.py ...`), but is more commonly invoked via the `mx/mx` bash script (which includes a Python version check). Adding the `mx/` directory to your PATH simplifies executing `mx`. The `mx/mx.cmd` script should be used on Windows.

The general form of the `mx` command line is:

```
mx [global options] [command] [command-specific options]
```

If no options or command is specified, `mx` prints information on the available options and commands, which will include any suite-specfic options and commands. Help for a specific command is obtained via `mx help <command>`. Global options are expected to have wide applicability to many commands and as such precede the command to be executed.

For an example of `mx` usage, see the [README][1] for the Graal project.

Note: There is a Bash completion script for global options and commands, located in `bash_completion` directory. Install it for example by `source`ing this script in your `~/.bashrc` file. If used, a temporary file `/tmp/mx-bash-completion-<project-path-hash>` is created and used for better performance. This should be OK since the `/tmp` directory is usually cleaned on every system startup.

### Unit testing with Junit ###

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

### URL rewriting ###

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

### Environment variable processing ###

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

### Multiple suites per repository ###

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
