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

### mx versioning ###

`mx` uses a `major`.`minor`.`patch` versioning scheme.  To figure out if you
version is sufficient for a given `mx` suite, first compare the major version
number of your `mx` version against the major number of the required version
specified in the suite.  If these versions are not equal, you cannot expect
`mx` to be compatible with this suite.  The minor number has to be greater or
equal to the specified minor version number.  Compatibility is ensured
regardless of the patch level.  However, if your patch level is lower than the
required patch level you might trigger bugs in `mx`.

From a developer point of view this versioning scheme enforces the following
update policy:
- If you make a change that prevents the new version of `mx` from loading
older files, increase the major number and reset both the minor and the patch
level to 0.
- If you add new functionality without breaking backward compatibility, leave
the major as it is, increase the minor number and reset the patch level.
- If you only fixed a bug without changing the public API (i.e., all files for
the current version can still be loaded with the new version and vice versa),
leave the major and minor versions as they are but increase the patch level.

[1]: https://wiki.openjdk.java.net/display/Graal/Instructions
