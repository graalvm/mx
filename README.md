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

For an example of `mx` usage, you can read the [Instructions][1] for the Graal project. 

### mx environment variable processing ###

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

[1]: https://wiki.openjdk.java.net/display/Graal/Instructions
