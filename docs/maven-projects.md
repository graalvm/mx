# Adding Maven projects to mx suites

When we develop things that integrate with maven, such as archetypes and or maven plugins, we want to use maven projects to do it.
This avoids the headache of matching the behavior of the appropriate maven development plugins.

## How to make maven projects known to mx

A distribution in a suite.py can be of `class: MavenProject`.
To use it, `from mx import MavenProject` into your "mx_suitename.py" file so the mx mechanism picks it up.
A MavenProject is both a Java project as well as a Jar distribution from the point of view of mx - it is a single, self-contained source tree that goes all the way to a distribution.
As such, it can be built with `mx build` and be deployed with `mx maven-deploy`.
It needs to be in the `distributions` section of the `suite.py`, since it can be deployed directly.

MavenProjects can have `dependencies` on other mx distributions or libraries.
Both library and distribution dependencies must have maven specifications - so libraries should be referring to existing maven artifacts, and other mx distributions should have a `maven` property.
All dependencies specified in the `suite.py` must also be in the default `pom.xml` of the maven project.
There is no consideration for mx "buildDependencies" or the "exclude" attribute that other distributions support - these kinds of features should be specified only in the `pom.xml` of the project.
You should use the maven properties for dependencies, such as `<scope>test</scope>` or `<optional>true</optional>` and similar as appropriate.

When a `MavenProject` is built, mx builds and deploys all dependencies into a local repository under the `mxbuild` directory.
A `pom.xml` is derived from the project's for an out-of-tree build into the `mxbuild` output directory for the maven project as well, with a reference to the local repository.
This generated `pom.xml` also receives the correct version specifiers to match the dependency versions.

## How maven projects could be used in the context of mx suites

So, a Truffle language developed as a maven project inside an mx suite could, for example, have dependencies on the appropriate distributions from the Truffle suite.
A development approach could be to write the versions of the last Truffle LTS into the pom.xml for all dependencies.
Thus, when developing the language independent of mx, we are developing against the last LTS.
When building and running unittests with mx, however, mx will generate the out-of-tree pom.xml with updated versions, so we can also develop and test against the latest master version of Truffle.

## IDE support

The `mx ideinit` command is supported for MavenProjects.
It will not generate IDE configuration, but instead just creates a second POM xml: `pom-mx.xml`.
This can be used to develop in the IDE against the concrete imported version of Truffle from the suite as would be used during `mx build`.
IntelliJ, for example, fully supports opening maven projects and selecting which xml file should be used to build and run the project and its tests.
This way, in the IDE using the same source tree, we can switch to see if your project builds and tests run successfully against the latest dependency versions declared in the `pom.xml` and those versions imported via the `suite.py`.

## Deployment via mx

The `mx maven-deploy` command when used to deploy a MavenProject will use the project pom patched to the requested version, but otherwise intact.
This ensures that maven packaging formats not directly supported by mx (e.g.
maven-plugin) are kept intact.
The developers, license, description, and scm sections are also updated with the information from the suite.py, to keep them in sync with what `mx maven-deploy` generates for other mx distributions.

## Running unittests

The `mx unittest` command is not supported with maven projects.
Maven project unittests have to be run explicitly using `mx maventests`.
