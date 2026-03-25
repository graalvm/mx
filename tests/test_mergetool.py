import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.create_mergetool_test_repos import create_multi_import_case, create_simple_case


def run_command(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=repo, check=False, text=True, capture_output=True)


class MergetoolFixtureTest(unittest.TestCase):
    def test_mock_repos_resolve_to_expected_branch(self):
        repo_root = Path(__file__).resolve().parent.parent
        mx = repo_root / "mx"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            simple_repo = tmp_path / "simple"
            complex_repo = tmp_path / "complex"
            create_simple_case(simple_repo)
            create_multi_import_case(complex_repo)

            for repo in (simple_repo, complex_repo):
                with self.subTest(repo=repo.name):
                    mergetool_cmd = f'{mx} -p {repo_root} mergetool-suite-import "$LOCAL" "$BASE" "$REMOTE" "$MERGED"'
                    subprocess.run(
                        ["git", "config", "mergetool.mx-suite-import.cmd", mergetool_cmd],
                        cwd=repo,
                        check=True,
                        text=True,
                        capture_output=True,
                    )
                    subprocess.run(
                        ["git", "config", "mergetool.mx-suite-import.trustExitCode", "true"],
                        cwd=repo,
                        check=True,
                        text=True,
                        capture_output=True,
                    )
                    subprocess.run(["git", "checkout", "-q", "local"], cwd=repo, check=True)
                    subprocess.run(["git", "reset", "--hard", "-q", "local"], cwd=repo, check=True)
                    subprocess.run(["git", "clean", "-fdq"], cwd=repo, check=True)

                    merge = run_command(repo, "git", "merge", "--no-ff", "--no-commit", "remote")
                    if merge.returncode != 0:
                        mergetool = run_command(repo, "git", "mergetool", "--no-prompt", "--tool", "mx-suite-import")
                        self.assertEqual(mergetool.returncode, 0, msg=mergetool.stdout + mergetool.stderr)

                    diff = run_command(repo, "git", "diff", "--exit-code", "expected")
                    self.assertEqual(diff.returncode, 0, msg=diff.stdout + diff.stderr)


if __name__ == "__main__":
    unittest.main()
