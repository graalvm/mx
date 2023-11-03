import os
import pathlib
import re
import tempfile

from typing import cast

from mx._impl import mx
from mx.mavenproject import ETMavenPOM, MavenProject


def test_pom_helper():
    with tempfile.NamedTemporaryFile(mode="w", prefix="pom", suffix=".xml") as f:
        pomtext = """
        <project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/maven-v4_0_0.xsd">
        <modelVersion>4.0.0</modelVersion>
        <groupId>org.graalvm.testpom</groupId>
        <artifactId>testpom</artifactId>
        <packaging>jar</packaging>
        <version>1-SNAPSHOT</version>
        <name>testpom</name>
        </project>
        """
        f.write(pomtext)
        f.flush()

        # Test all the accessors and creating sections and such
        pom = ETMavenPOM(f.name)
        assert pom["groupId"].text == "org.graalvm.testpom"
        try:
            pom["moupId"]
        except KeyError:
            pass
        else:
            assert False, "should have raised KeyError"
        assert pom.get_text("artifactId") == "testpom"
        assert pom.get_text("shmartifactId") == ""
        assert pom.get_text("shmartifactId", "foo") == "foo"

        with pom.add("section") as section:
            element1 = section.add("element")
            element1.text = "1"
            section.add("element").text = "2"
            assert section.setdefault("element").text == element1.text
            assert section.setdefault("another_element").text is None
            assert len(section.getall("element")) == 2

        assert pom["section"]["element"].text == "1"
        pomcopy = pom.copy()

        # copys are based on the file state
        assert pomcopy.get("section") is None

        assert re.sub(r"\s", "", pomcopy.tostring()) == re.sub(r"\s", "", pomtext)
        assert "section" in pom.tostring()
        assert "another_element" in pom.tostring()


def test_maven_project():
    pomtext = """
    <project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/maven-v4_0_0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>org.graalvm.testpom</groupId>
    <artifactId>testpom</artifactId>
    <packaging>jar</packaging>
    <version>1-SNAPSHOT</version>
    <name>testpom</name>
    <dependencies>
    <dependency>
    <groupId>junit</groupId>
    <artifactId>junit</artifactId>
    <version>128</version>
    </dependency>
    <dependency>
    <groupId>com.oracle.mx</groupId>
    <artifactId>junit-tool</artifactId>
    <version>129</version>
    </dependency>
    </dependencies>
    </project>
    """

    def create_project():
        with open(os.path.join(tmpdir, "pom.xml"), "w") as f:
            f.write(pomtext)
        suite = cast(mx.Suite, mx.primary_suite())
        lisense = [l.theLicense for l in suite.libs if l.theLicense is not None][0]
        return MavenProject(
            suite, os.path.basename(tmpdir), ["JUNIT", "JUNIT_TOOL"], [], False, lisense, subDir=os.path.dirname(tmpdir)
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            create_project()
        except SystemExit:
            pass
        else:
            assert False, "artifactid and project name must match"
        pomtext = pomtext.replace("testpom", os.path.basename(tmpdir))
        project = create_project()

        assert project.javaCompliance.highest_specified_value() == 17

        assert not os.path.exists(os.path.join(tmpdir, "pom-mx.xml"))
        assert project.get_ide_project_dir() is None
        assert os.path.exists(os.path.join(tmpdir, "pom-mx.xml"))

        assert project.needsUpdate(newestInput=None)[0]

        assert project.isJARDistribution()
        assert project.isJavaProject()
        assert project.remoteExtension() == "jar"
        assert project.localExtension() == "jar"
        try:
            assert project.classpath_repr()
        except SystemExit:
            pass
        else:
            assert False, "classpath needs a built artifact"
        os.makedirs(project.get_output_root(), exist_ok=True)
        defaultjarpath = pathlib.Path(project.get_output_root()) / project.default_filename()
        defaultjarpath.touch()
        default_path = project.make_archive()
        assert project.classpath_repr() == default_path

        assert project.needsUpdate(newestInput=None)[0]
        pathlib.Path(project.sourcesPath).touch()
        assert not project.needsUpdate(newestInput=None)[0]

        assert os.path.exists(default_path)
        bt = project.getBuildTask([])
        bt.clean()
        assert not os.path.exists(default_path)

        assert not os.path.exists(os.path.join(project.get_output_root(), "pom.xml"))
        run_maven = mx.run_maven
        maven_deploy = mx.maven_deploy
        maven_runs = []
        maven_deployments = []
        mx.run_maven = lambda *args, **kwargs: maven_runs.append([args, kwargs]) or defaultjarpath.touch()
        mx.maven_deploy = lambda *args, **kwargs: maven_deployments.append([args, kwargs])
        try:
            bt.build()
        except:
            bt.clean()
        finally:
            mx.run_maven = run_maven
            mx.maven_deploy = maven_deploy

        try:
            buildpom = ETMavenPOM(os.path.join(project.get_output_root(), "pom.xml"))
            assert os.path.exists(os.path.join(project.get_output_root(), "local-maven-repo"))
        finally:
            bt.clean()

        assert buildpom.get("repositories")
        assert (
            buildpom.setdefault("licenses").setdefault("license").get_text("name")
            == cast(mx.License, project.theLicense[0]).fullname
        )

        assert len(maven_deployments) == 1, "only JUNIT_TOOL should be deployed"
        assert "--only=JUNIT_TOOL" in " ".join(maven_deployments[0][0][0])
        assert len(maven_runs) == 2
        assert "package" in " ".join(maven_runs[0][0][0])
        assert "source:jar" in " ".join(maven_runs[1][0][0])


def tests():
    test_pom_helper()
    test_maven_project()
