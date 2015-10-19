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

For more detailed but unfortunately slightly out of date information about `mx`, you can look at the [wiki][2]. We are planning to bring the documentation up to date soon.
[1]: https://wiki.openjdk.java.net/display/Graal/Instructions
[2]: https://bitbucket.org/allr/mx/wiki/Home