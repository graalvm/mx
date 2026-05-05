# pylint: disable=duplicate-code

import importlib
import pathlib
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from contextlib import contextmanager


class _FakeFileRepo:
    def __init__(self, repo_dir):
        self.name = "test-file-repo"
        self._repo_dir = repo_dir

    def get_maven_id(self):
        return "test-file-repo"

    def get_url(self, deployed_version):
        return self._repo_dir.as_uri()


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

orig_mx = importlib.import_module("mx._impl.mx")
orig_mx_maven = importlib.import_module("mx._impl.mx_maven")


@contextmanager
def monkeypatch_attr(obj, name, value):
    previous = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield value
    finally:
        setattr(obj, name, previous)


@contextmanager
def monkeypatch_opt(**kwargs):
    sentinel = object()
    previous = {name: getattr(orig_mx._opts, name, sentinel) for name in kwargs}
    for name, value in kwargs.items():
        setattr(orig_mx._opts, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is sentinel:
                delattr(orig_mx._opts, name)
            else:
                setattr(orig_mx._opts, name, value)


class _MockMxCompatibility:
    def mavenSupportsClassifier(self):
        return True


class _MockSuite:
    name = "test-suite"
    internal = False
    url = None
    developer = None

    def __init__(self):
        setattr(self, "vc", None)

    def getMxCompatibility(self):
        return _MockMxCompatibility()


class _MockDistribution:
    def __init__(self, name, deps=None, excluded_libs=None, optional_dependencies=None, maven=True, suite=None):
        self.name = name
        self.deps = deps or []
        self.excludedLibs = excluded_libs or []
        self.optionalDependencies = optional_dependencies or []
        self.maven = maven
        self.suite = suite or _MockSuite()
        self.theLicense = []
        self.description = name
        self.platforms = [None]

    def isDistribution(self):
        return True

    def isLayoutDirDistribution(self):
        return False

    def isJARDistribution(self):
        return True

    def isPOMDistribution(self):
        return False

    def is_runtime_dependency(self, dep):
        return False

    def remoteExtension(self):
        return "jar"

    def maven_group_id(self):
        return "org.example"

    def maven_artifact_id(self, platform=None):
        return self.name.lower().replace("_", "-")

    def qualifiedName(self):
        return f"{self.suite.name}:{self.name}"

    def abort(self, message):
        raise AssertionError(message)

    def warn(self, message):
        raise AssertionError(message)

    def __str__(self):
        return self.qualifiedName()


class _MockLibrary:
    def __init__(self, name):
        self.name = name
        self.maven = {
            "groupId": "org.example.libs",
            "artifactId": name.lower().replace("_", "-"),
            "version": "1.2.3",
        }

    def isJdkLibrary(self):
        return False

    def isJreLibrary(self):
        return False

    def isDistribution(self):
        return False

    def qualifiedName(self):
        return f"library:{self.name}"

    def abort(self, message):
        raise AssertionError(message)


class MavenOptionalDependencyPomTest(unittest.TestCase):
    def test_gen_pom_marks_mx_optional_dependencies_optional(self):
        required_dist = _MockDistribution("REQUIRED_DIST")
        optional_dist = _MockDistribution("OPTIONAL_DIST")
        optional_lib = _MockLibrary("OPTIONAL_LIB")
        dist = _MockDistribution(
            "MAIN_DIST",
            deps=[required_dist, optional_dist],
            excluded_libs=[optional_lib],
            optional_dependencies=[optional_dist, optional_lib],
        )

        with monkeypatch_attr(orig_mx_maven, "_deployment_module_requires_for_maven", lambda _dist: (None, None)):
            pom_xml = orig_mx_maven._genPom(dist, lambda _suite: "1.0")

        root = ET.fromstring(pom_xml)
        namespace = {"m": "http://maven.apache.org/POM/4.0.0"}
        dependencies = {
            dependency.findtext("m:artifactId", namespaces=namespace): dependency.findtext(
                "m:optional", namespaces=namespace
            )
            for dependency in root.findall("./m:dependencies/m:dependency", namespace)
        }
        self.assertEqual({"required-dist": None, "optional-dist": "true", "optional-lib": "true"}, dependencies)


class BatchedMavenDeployIntegrationTest(unittest.TestCase):
    def test_run_batched_maven_deploy_deploys_multiple_artifacts_to_file_repository(self):
        self.assertIsNotNone(shutil.which("mvn"), "requires Maven")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = pathlib.Path(tmpdir)
            artifact_one = tmpdir_path / "dist-one.jar"
            sources_one = tmpdir_path / "dist-one-sources.jar"
            javadoc_one = tmpdir_path / "dist-one-javadoc.jar"
            extra_one = tmpdir_path / "suite-revisions.xml"
            pom_one = tmpdir_path / "dist-one.pom"
            artifact_two = tmpdir_path / "dist-two.jar"
            pom_two = tmpdir_path / "dist-two.pom"
            repo_dir = tmpdir_path / "repo"
            repo_dir.mkdir()

            artifact_one.write_text("jar-one", encoding="utf-8")
            sources_one.write_text("sources-one", encoding="utf-8")
            javadoc_one.write_text("javadoc-one", encoding="utf-8")
            extra_one.write_text("<suite-revisions/>", encoding="utf-8")
            artifact_two.write_text("jar-two", encoding="utf-8")
            pom_one.write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.oracle.test</groupId>
  <artifactId>dist-one</artifactId>
  <version>1.0</version>
</project>
""",
                encoding="utf-8",
            )
            pom_two.write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.oracle.test</groupId>
  <artifactId>dist-two</artifactId>
  <version>1.0</version>
</project>
""",
                encoding="utf-8",
            )

            specs = [
                orig_mx_maven._create_maven_deploy_spec(
                    "com.oracle.test",
                    "dist-one",
                    str(artifact_one),
                    "1.0",
                    srcPath=str(sources_one),
                    pomFile=str(pom_one),
                    javadocPath=str(javadoc_one),
                    extraFiles=[(str(extra_one), "suite-revisions", "xml")],
                ),
                orig_mx_maven._create_maven_deploy_spec(
                    "com.oracle.test",
                    "dist-two",
                    str(artifact_two),
                    "1.0",
                    pomFile=str(pom_two),
                ),
            ]

            repo = _FakeFileRepo(repo_dir)
            local_repo_sentinel = object()

            def fake_local_repo():
                return local_repo_sentinel

            with monkeypatch_attr(orig_mx_maven, "maven_local_repository", fake_local_repo):
                with monkeypatch_opt(exec_log=False, ptimeout=0, quiet=True):
                    orig_mx_maven._run_batched_maven_deploy(specs, repo, settingsXml=None, dryRun=False)

            group_dir = repo_dir / "com" / "oracle" / "test"
            self.assertTrue((group_dir / "dist-one" / "1.0" / "dist-one-1.0.jar").exists())
            self.assertTrue((group_dir / "dist-one" / "1.0" / "dist-one-1.0.pom").exists())
            self.assertTrue((group_dir / "dist-one" / "1.0" / "dist-one-1.0-sources.jar").exists())
            self.assertTrue((group_dir / "dist-one" / "1.0" / "dist-one-1.0-javadoc.jar").exists())
            self.assertTrue((group_dir / "dist-one" / "1.0" / "dist-one-1.0-suite-revisions.xml").exists())
            self.assertTrue((group_dir / "dist-two" / "1.0" / "dist-two-1.0.jar").exists())
            self.assertTrue((group_dir / "dist-two" / "1.0" / "dist-two-1.0.pom").exists())


if __name__ == "__main__":
    unittest.main()
