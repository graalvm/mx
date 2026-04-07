# pylint: disable=duplicate-code

import importlib
import pathlib
import shutil
import sys
import tempfile
import unittest

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
