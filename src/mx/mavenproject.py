#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2023, Oracle and/or its affiliates. All rights reserved.
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#
# This code is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 only, as
# published by the Free Software Foundation.
#
# This code is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# version 2 for more details (a copy is included in the LICENSE file that
# accompanied this code).
#
# You should have received a copy of the GNU General Public License version
# 2 along with this work; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
# or visit www.oracle.com if you need additional information or have any
# questions.
#
# ----------------------------------------------------------------------------------------------------
#
"""A module to support including maven projects in mx suites.

When we develop things that integrate with maven, such as archetypes and or
maven plugins, we want to use maven projects to do it. This avoids the headache
of matching the behavior of the appropriate maven development plugins.

With this commit, a project in a suite.py can be of `class: MavenProject`. A
MavenProject is both a Java project as well as a Jar distribution from the
point of view of mx - it is a single, self-contained source tree that goes all
the way to a distribution. As such, it can be built with `mx build` and be
deployed with `mx maven-deploy`.

MavenProjects can have `dependencies` on other mx distributions or libraries.
Both library and distribution dependencies must have maven specifications - so
libraries should be referring to existing maven artifacts, and other mx
distributions should have a `maven` property. All dependencies specified in the
suite.py must also be in the default pom.xml of the maven project. There is no
consideration for mx "buildDependencies" or the "exclude" attribute that other
distributions support - these kinds of features should be specified only in the
pom.xml of the project.

When building a MavenProject, the dependencies are deployed into a local
repository in the `mxbuild` directory. A pom.xml is created for an out-of-tree
build into the `mxbuild` output directory for the maven project as well, with a
reference to the local repository. This generated pom.xml also receives the
correct version specifiers to match the dependency versions.

So, a Truffle language developed as a MavenProject inside an mx suite could,
for example, have dependencies on the appropriate distributions from the
Truffle suite. A development approach could be to write the versions of the
last Truffle LTS into the pom.xml for all dependencies. Thus, when developing
the language independent of mx, we are developing against the last LTS. When
building and running unittests with mx, however, mx will generate the
out-of-tree pom.xml with updated versions, so we can also develop and test
against the latest master version of Truffle.

The `mx ideinit` command is supported for MavenProjects. It will not generate
IDE configuration, but instead just creates a second POM xml: `pom-mx.xml`.
This can be used to develop in the IDE against the concrete imported version of
Truffle from the suite as would be used during `mx build`. IntelliJ, for
example, fully supports opening maven projects and selecting which xml file
should be used to build and run the project and its tests. This way, in the IDE
using the same source tree, we can switch to see if your project builds and
tests run successfully against the latest dependency versions declared in the
`pom.xml` and those versions imported via the `suite.py`.

The `mx maven-deploy` command when used to deploy a MavenProject will use the
project pom patched to the requested version, but otherwise intact. This
ensures that maven packaging formats not directly supported by mx (e.g.
maven-plugin) are kept intact. The developers, license, description, and scm
sections are also updated with the information from the suite.py, to keep them
in sync with what `mx maven-deploy` generates for other mx distributions.

The `mx unittest` command is not supported with maven projects. Their unittests
have to be run explicitly using `mx maventests`.

"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import os
import shutil
import pathlib

from typing import cast, Callable
from argparse import ArgumentParser

from ._impl.mx_javacompliance import JavaCompliance
from ._impl import mx

__all__ = [
    "MavenProject",
]


class ETMavenPOM:
    """
    A convenience wrapper around ElementTree Elements for
    use with Maven's pom.xml files.
    """

    DefaultNamespace = "http://maven.apache.org/POM/4.0.0"

    def __init__(self, path: str):
        self._path = path
        self._pom: ET.ElementTree = ET.parse(path)
        self._element: ET.Element = self._pom.getroot()

    def __getattr__(self, name: str):
        no_value = object()
        value = getattr(self._element, name, no_value)
        if value is no_value or callable(value):
            value = getattr(self._pom, name, no_value)
        if value is no_value:
            raise AttributeError(f"{type(self).__name__} object has no attribute {name}")
        return value

    def __setattr__(self, name: str, value):
        if not name.startswith("_"):
            setattr(self._element, name, value)
        else:
            super().__setattr__(name, value)

    def copy(self) -> ETMavenPOM:
        """
        Construct a new ETMavenPOM from the same file.
        """
        return ETMavenPOM(self._path)

    def get_text(self, path: str, default: str = "") -> str:
        """
        Return the text content of the child element named 'path', or the default if that element does not exist.
        """
        try:
            return cast(str, self[path].text)
        except KeyError:
            return default

    def add(self, path: str) -> ETMavenPOM:
        """
        Add a new child element and return it.
        """
        e = ET.Element(f"{{{self.DefaultNamespace}}}{path}")
        self._element.append(e)
        return self._wrap(e)

    def setdefault(self, path: str) -> ETMavenPOM:
        """
        Get an existing child element or create it.
        """
        try:
            return self[path]
        except KeyError:
            return self.add(path)

    def get(self, path: str, default: None | ETMavenPOM = None) -> None | ETMavenPOM:
        """
        Get an existing child element or return the default argument.
        """
        try:
            return self[path]
        except KeyError:
            return default

    def getall(self, path: str) -> list[ETMavenPOM]:
        """
        Get all child elements matching 'path'.
        """
        return [self._wrap(e) for e in self._element.findall(path, namespaces={"": self.DefaultNamespace})]

    def _wrap(self, e: ET.Element) -> ETMavenPOM:
        result = self.__class__.__new__(self.__class__)
        result._pom = self._pom  # pylint: disable=protected-access
        result._element = e  # pylint: disable=protected-access
        return result

    def write(self, path: str) -> None:
        """
        Write the entire pom to the file 'path'
        """
        if hasattr(ET, "indent"):
            ET.indent(self._pom, space="  ", level=0)
        self._pom.write(path, default_namespace=self.DefaultNamespace)

    def tostring(self) -> str:
        """
        Return a stringified version of this element and all children.
        """
        if hasattr(ET, "indent"):
            ET.indent(self._pom, space="  ", level=0)
        return ET.tostring(self._element, encoding="unicode", default_namespace=self.DefaultNamespace)

    def __getitem__(self, path: str) -> ETMavenPOM:
        if (e := self._element.find(path, namespaces={"": self.DefaultNamespace})) is not None:
            return self._wrap(e)
        raise KeyError(path)

    def __enter__(self) -> ETMavenPOM:
        return self

    def __exit__(self, *_) -> None:
        pass


class MavenProject(mx.Distribution, mx.ClasspathDependency):  # pylint: disable=too-many-instance-attributes
    """
    An mx project and distribution for Maven projects. These have properties of both
    mx Java projects as well as mx (Jar) distributions. See the module docs for
    details.
    """

    def __init__(
        self, suite: mx.Suite, name: str, deps, excludedLibs, platformDependent, theLicense, **args
    ):  # pylint: disable=too-many-arguments
        super().__init__(suite, name, deps, excludedLibs, platformDependent, theLicense, **args)

        self.maven_directory = os.path.join(suite.dir, args.get("subDir", ""), name)
        self.pom = ETMavenPOM(os.path.join(self.maven_directory, "pom.xml"))

        # prepare distribution maven dictionary from actual pom.xml
        self.maven = getattr(self, "maven", {})
        if any(k != "tag" for k in self.maven.keys()):
            mx.abort("MavenProjects should not repeat properties except tags in suite.py")
        self.maven["groupId"] = self.pom["groupId"].text
        self.maven["artifactId"] = self.pom["artifactId"].text
        if self.maven["artifactId"] != self.name:
            mx.abort(f"MavenProject {self.name} should match artifactId to project name {self.maven['artifactId']}")

        # self.javaCompliance must be set since this is a kind of JavaProject
        self.javaCompliance = JavaCompliance(  # pylint: disable=invalid-name
            self.pom.setdefault("properties").get_text("maven.compiler.target", "17") + "+", context=self
        )

        # localExtension, remoteExtension, description, sourcesPath, and path
        # must all be set for Jar distributions that can be deployed to maven
        self._packaging = self._remote_ext = self.pom.get_text("packaging", "jar")
        if self._remote_ext == "maven-plugin":
            self._local_ext = "jar"
        elif self._remote_ext == "maven-archetype":
            self._local_ext = self._remote_ext = "jar"
        else:
            self._local_ext = self._remote_ext
        self.description = self.pom.get_text("description", "")
        self.sourcesname = f"{self.name}-sources.{self._local_ext}"
        self.sourcesPath = os.path.join(self.get_output_root(), self.sourcesname)  # pylint: disable=invalid-name
        self.path = self._default_path()

        # right now we don't let maven projects define annotation processors
        self.definedAnnotationProcessors = []  # pylint: disable=invalid-name

    def get_ide_project_dir(self):
        """
        We generate the ide pom.xml here, but don't use mx's support for generating
        ide configs besides that.
        """
        self.getBuildTask([]).create_ide_pom()

    def classpath_repr(self, resolve=True) -> str | None:
        """
        Returns this project's output jar if it has <packaging>jar</packaging>
        """
        jar = self._default_path()
        if jar.endswith(".jar"):
            if resolve and not os.path.exists(jar):
                mx.abort(f"unbuilt Maven project {self} cannot be on a class path ({jar})")
            return jar
        return None

    def build_pom(self) -> str:
        """
        The path to this project's generated out-of-tree build pom.xml
        """
        return os.path.join(self.get_output_root(), "pom.xml")

    def generate_deployment_pom(self, version: str, validation_callback: Callable | None = None):
        """
        Generate and return a pom.xml suitable for deployment, with the
        specified version. If the optional validation_callback argument
        is given, validations are done on the resulting xml.
        """
        generated_pom = self.getBuildTask([]).print_deploy_pom(version)
        if self._packaging == "maven-plugin":
            # Maven plugins store their version inside the Jar, so only for
            # those we need to rebuild with that version before deploying
            self.getBuildTask([]).build(version=version)
        if validation_callback:
            parsed_pom = ET.fromstring(generated_pom)
            self._validate_pom(parsed_pom, version, validation_callback)
        return generated_pom

    def _validate_pom(
        self, parsed_pom: ET.Element, version: str, cb: Callable
    ):  # pylint: disable=too-many-locals,too-many-branches
        ns = {"": ETMavenPOM.DefaultNamespace}

        def match_not_empty(element: ET.Element, path: str, value: str, errorstr=None):
            errorstr = errorstr or f"include {path}"
            if not (value and element.findtext(path, namespaces=ns) == value):
                cb(f"Generated POM for {self} does not {errorstr}")
                return False
            return True

        def get_section(element: ET.Element, path: str, errorstr=None):
            errorstr = errorstr or f"include {path} section"
            result = element.find(path, namespaces=ns)
            if not result:
                cb(f"Generated POM for {self} does not {errorstr}")
            return result

        match_not_empty(parsed_pom, "url", self.suite.url, "include suite url")
        match_not_empty(parsed_pom, "description", getattr(self.suite, "description", ""), "suite description")
        if devs := get_section(parsed_pom, "developers"):
            if dev := get_section(devs, "developer"):
                for attr in ["name", "email", "organization"]:
                    match_not_empty(dev, attr, self.suite.developer.get(attr, ""), f"suite developer {attr}")
                match_not_empty(dev, "organizationUrl", self.suite.developer.get("organizationUrl", self.suite.url))
        if licenses := get_section(parsed_pom, "licenses"):
            licenses = licenses.findall("license", namespaces=ns)
            if not licenses:
                cb(f"Generated POM for {self} does not include licenses")
            expected_licenses: list[mx.License] = cast(list[mx.License], list(self.theLicense))
            if len(licenses) != expected_licenses:
                cb(f"Generated POM for {self} has different licenses than suite")
            for pl in licenses:
                for l in expected_licenses:
                    if match_not_empty(pl, "name", l.fullname) and match_not_empty(pl, "url", l.url):
                        break
                else:
                    cb(f"Generated POM for {self} is missing license {pl}")
        deps = parsed_pom.find("dependencies", namespaces=ns)
        if deps:
            for dep in deps.findall("dependency", namespaces=ns):
                if "SNAPSHOT" in (dep.findtext("version", namespaces=ns) or "") and "SNAPSHOT" not in version:
                    cb(f"Generated non-snapshot POM for {self} is depending on a snapshot distribution")
        if self.suite.vc:
            scm = self.suite.scm_metadata(abortOnError=True)
            if pomscm := get_section(parsed_pom, "scm"):
                match_not_empty(pomscm, "connection", f"scm:{self.suite.vc.kind}:{scm.read}", "scm connection of suite")
                match_not_empty(
                    pomscm,
                    "developerConnection",
                    f"scm:{self.suite.vc.kind}:{scm.write}",
                    "scm developerConnection of suite",
                )
                match_not_empty(pomscm, "url", scm.url, "scm url of suite")
        else:
            cb(f"Suite {self.suite.name} is not in a vcs repository")

    def make_archive(self):
        os.makedirs(os.path.dirname(self._default_path()), exist_ok=True)
        shutil.copy(os.path.join(self.get_output_root(), self.default_filename()), self._default_path())
        return self._default_path()

    def exists(self):
        return os.path.exists(self._default_path())

    def prePush(self, f):
        return f

    def get_output_root(self):
        """
        Gets the root of the directory hierarchy under which generated artifacts for this
        dependency such as class files and annotation generated sources should be placed.
        """
        return os.path.join(self.get_output_base(), self.name)

    def isJARDistribution(self):
        return self.localExtension() == "jar"

    def isJavaProject(self):
        return True

    def remoteExtension(self) -> str:
        return self._remote_ext

    def localExtension(self) -> str:
        return self._local_ext

    def set_archiveparticipant(self, _):
        pass

    def needsUpdate(self, newestInput):
        if not os.path.exists(self._default_path()):
            return True, "Maven package does not exist"
        if not os.path.exists(self.sourcesPath):
            return True, "Maven sources do not exist"
        newest_source = newestInput.timestamp if newestInput else 0
        for root, _, files in os.walk(self.maven_directory):
            if files:
                newest_source = max(newest_source, max(mx.getmtime(os.path.join(root, f)) for f in files))
        if mx.getmtime(self._default_path()) < newest_source:
            return True, "Maven package out of date"
        if mx.getmtime(self.sourcesPath) < newest_source:
            return True, "Maven sources out of date"
        return False, "Maven package is up to date"

    def getBuildTask(self, args):
        self.deps = [mx.dependency(d) for d in self.deps]
        return _MavenBuildTask(self, args)


class _MavenBuildTask(mx.BuildTask):
    def __init__(self, subject: MavenProject, args):
        super().__init__(subject, args, 1)

    def needsBuild(self, newestInput):
        if self.args.force:
            return (True, "forced build")
        return self.subject.needsUpdate(newestInput)

    def clean(self, forBuild=False):
        shutil.rmtree(self.subject.get_output_root(), ignore_errors=True)
        if os.path.exists(self.subject.path):
            os.unlink(self.subject.path)

    def __str__(self):
        return self.subject.name

    def build(self, version: str | None = None):
        os.makedirs(self.subject.get_output_root(), exist_ok=True)
        os.makedirs(os.path.dirname(self.subject.path), exist_ok=True)
        self._create_build_pom(version=version)
        self._deploy_dependencies(version=version)
        if mx.get_opts().verbose:
            verbosity = "-e"
        elif mx.get_opts().very_verbose:
            verbosity = "-X"
        else:
            verbosity = "-q"
        mx.run_maven([verbosity, "package", "-DskipTests"], cwd=self.subject.get_output_root())
        mx.run_maven([verbosity, "source:jar", "-DskipTests"], cwd=self.subject.get_output_root())
        self.subject.make_archive()

    def _local_dependency_repo(self) -> str:
        return os.path.join(self.subject.get_output_root(), "local-maven-repo")

    def _local_repo_id(self) -> str:
        return f"{self.subject.name}-dependencies"

    def _maven_version_for_dist(self, dist: mx.Distribution) -> str:
        ver = dist.suite.release_version()
        if ver.endswith("-dev"):
            return f"{ver}-SNAPSHOT"
        return ver

    def _deploy_dependencies(self, version: str | None = None):
        path = self._local_dependency_repo()
        shutil.rmtree(path, ignore_errors=True)
        os.mkdir(path)
        transitive_deps = set(self.subject.deps)
        sz = 0
        while True:
            if sz == len(transitive_deps):
                break
            sz = len(transitive_deps)
            for build_dep in list(transitive_deps):
                if build_dep.isLibrary():
                    transitive_deps.remove(build_dep)
                    continue
                for d in build_dep.deps:
                    if (
                        d.isDistribution()
                        and not d.isLayoutDirDistribution()
                        and not d.suite.internal
                        and hasattr(d, "maven")
                    ):
                        transitive_deps.add(d)
        # (tfel): A note about the versions: the mx maven-deploy command
        # generates a versionGetter closure that enforces that all generated
        # dependencies in a generated pom have the same version, regardless of
        # their suite version. I am unsure if this makes sense, I guess it's
        # just practical right now assuming that all packages follow the same
        # versions. If/when this changes, we need to revisit the deployment
        # code here. It should be as simple as calculating the "ver" variable
        # for each build_dep rather than just for this distribution
        ver = version or self._maven_version_for_dist(self.subject)
        for build_dep in transitive_deps:
            if build_dep.theLicense:
                licenses = ",".join([l.name for l in build_dep.theLicense])
            else:
                licenses = ""
            deploy_args = [
                "--all-suites",
                "--all-distribution-types",
                f"--only={build_dep}",
                f"--version-string={ver}",
                "--validate=none",
                f"--licenses={licenses}",
                "--suppress-javadoc",
                self._local_repo_id(),
                pathlib.Path(path).as_uri(),
            ]
            mx.maven_deploy(deploy_args)

    def _create_base_pom(self, version: str | None = None, with_repositories: bool = True):
        pom = self.subject.pom.copy()
        pom["version"].text = version or self._maven_version_for_dist(self.subject)
        self._create_base_build_section(pom)
        self._create_base_dependency_section(pom, version)
        if with_repositories:
            self._create_base_repository_section(pom)
        self._create_base_meta_information(pom)
        return pom

    def _create_base_build_section(self, pom: ETMavenPOM):
        with pom.setdefault("build") as build:
            for k in [
                "sourceDirectory",
                "directory",
                "finalName",
                "scriptSourceDirectory",
                "testSourceDirectory",
                "resources",
                "testResources",
            ]:
                if build.get(k):
                    mx.abort(f"{self} should not define {k}")

    def _get_artifact_id(self, dep):
        if hasattr(dep, "maven_artifact_id"):
            return dep.maven_artifact_id()
        else:
            return dep.maven["artifactId"]

    def _get_group_id(self, dep):
        if hasattr(dep, "maven_group_id"):
            return dep.maven_group_id()
        else:
            return dep.maven["groupId"]

    def _create_base_dependency_section(self, pom: ETMavenPOM, version: str | None):
        for d in self.subject.deps:
            if not hasattr(d, "maven"):
                mx.abort(f"Maven projects can only depend on distributions with maven spec, not {d!r}")
            dep_id = self._get_artifact_id(d)
            dep_grp = self._get_group_id(d)
            version = d.maven["version"] if d.isLibrary() else (version or self._maven_version_for_dist(d))
            with pom.setdefault("dependencies") as dependencies:
                for dependency in dependencies.getall("dependency"):
                    if dep_grp == dependency.get_text("groupId") and dep_id == dependency.get_text("artifactId"):
                        dependency.setdefault("version").text = version
                        break
                else:
                    mx.abort(
                        f"Dependency {d} is not listed as {dep_grp}:{dep_id} in {self}'s pom.xml. Please make suite.py and pom.xml consistent."
                    )

    def _create_base_repository_section(self, pom: ETMavenPOM):
        if self.subject.deps:
            with pom.setdefault("repositories") as repositories:
                with repositories.add("repository") as repository:
                    repository.add("id").text = self._local_repo_id()
                    repository.add("url").text = pathlib.Path(self._local_dependency_repo()).as_uri()
                    with repository.add("releases") as releases:
                        releases.add("enabled").text = "true"
                    with repository.add("snapshots") as releases:
                        releases.add("enabled").text = "true"
                        releases.add("updatePolicy").text = "always"

    def _create_base_meta_information(self, pom: ETMavenPOM):
        suite = self.subject.suite
        if suite.developer:
            with pom.setdefault("developers") as developers:
                with developers.add("developer") as developer:
                    developer.add("name").text = suite.developer["name"]
                    developer.add("email").text = suite.developer["email"]
                    developer.add("organization").text = suite.developer["organization"]
                    developer.add("organizationUrl").text = suite.developer.get("organizationUrl", suite.url)
        with pom.setdefault("licenses") as licenses:
            for dist_license in self.subject.theLicense:
                with licenses.add("license") as l:
                    l.add("name").text = dist_license.fullname
                    l.add("url").text = dist_license.url
        if suite.vc:
            scm_metadata = suite.scm_metadata(abortOnError=True)
            with pom.setdefault("scm") as scm:
                scm.add("connection").text = f"scm:{suite.vc.kind}:{scm_metadata.read}"
                scm.add("developerConnection").text = f"scm:{suite.vc.kind}:{scm_metadata.write}"
                scm.add("url").text = scm_metadata.url

    def create_ide_pom(self, version: str | None = None):
        """
        Create a derived POM xml that builds into mxbuild with the dependencies
        and their versions taken from the mx suite.py
        """
        pom = self._create_base_pom(version=version, with_repositories=True)
        with pom["build"] as build:
            build.add("directory").text = os.path.relpath(self.subject.get_output_root(), self.subject.maven_directory)
            build.add("finalName").text = os.path.splitext(self.subject.default_filename())[0]
        pom.write(os.path.join(self.subject.maven_directory, "pom-mx.xml"))

    def print_deploy_pom(self, version: str) -> str:
        """
        Return a XML string suitable as a pom.xml for deployment, notably
        with the requested version and without local repositories.
        """
        pom = self._create_base_pom(version=version, with_repositories=False)
        return pom.tostring()

    def _create_build_pom(self, version: str | None = None):
        pom = self._create_base_pom(version=version)
        with pom["build"] as build:
            srcpath = os.path.relpath(self.subject.maven_directory, self.subject.get_output_root())
            build.add("directory").text = "${project.basedir}"
            build.add("finalName").text = os.path.splitext(self.subject.default_filename())[0]
            build.add("sourceDirectory").text = os.path.join(srcpath, "src", "main", "java")
            build.add("scriptSourceDirectory").text = os.path.join(srcpath, "src", "main", "scripts")
            build.add("testSourceDirectory").text = os.path.join(srcpath, "src", "test", "java")
            with build.add("resources") as resources:
                with resources.add("resource") as resource:
                    resource.add("directory").text = os.path.join(srcpath, "src", "main", "resources")
            with build.add("testResources") as resources:
                with resources.add("testResource") as resource:
                    resource.add("directory").text = os.path.join(srcpath, "src", "test", "resources")
        pom.write(self.subject.build_pom())


@mx.command("mx", "maventests")
def mvn_tests(args: list[str]):
    """
    Run tests for maven projects in all suites.
    """
    parser = ArgumentParser(prog="mx maventests", description="""Run MavenProject tests.""")
    parser.add_argument("--primary", action="store_true", help="limit command to primary suite")
    parser.add_argument("projects", nargs="*", default=[], help="MavenProjects to run tests in (all if omitted)")
    parsed_args = parser.parse_args(args)
    suites: list[mx.Suite] = []
    if parsed_args.primary and (primary_suite := mx.primary_suite()):
        suites = [primary_suite]
    else:
        suites = cast(list[mx.Suite], mx.suites())
    dists: list[MavenProject] = [d for s in suites for d in s.dists if isinstance(d, MavenProject)]
    if parsed_args.projects:
        dists = [d for d in dists if d.name in parsed_args.projects]
    rc = 0
    for d in dists:
        needs_update, _ = d.needsUpdate(None)
        if needs_update:
            mx.abort(f"{d.name} is not built, did you run mx build --dep {d.name}?")
        if mx.get_opts().verbose:
            verbosity = "-e"
        elif mx.get_opts().very_verbose:
            verbosity = "-X"
        else:
            verbosity = "-q"
        rc = mx.run_maven([verbosity, "test"], cwd=d.get_output_root(), nonZeroIsFatal=False) or rc
    if rc != 0:
        mx.abort("Failed")
