#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import textwrap
from pathlib import Path


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True)


def write_suite(repo: Path, *, sdk_version: str, compiler_version: str, sdk_url: str, metadata_key: str) -> None:
    suite = textwrap.dedent(
        f"""\
        suite = {{
            "mxversion": "7.0.0",
            "name": "fixture",
            "imports": {{
                "suites": [
                    {{
                        "name": "sdk",
                        "subdir": True,
                        "version": "{sdk_version}",
                        "urls": [{{"url": "{sdk_url}", "kind": "git"}}],
                    }},
                    {{
                        "name": "compiler",
                        "subdir": True,
                        "version": "{compiler_version}",
                        "urls": [{{"url": "https://example.invalid/compiler.git", "kind": "git"}}],
                    }},
                ],
            }},
            "metadata": {{
                "key": "{metadata_key}",
            }},
        }}
        """
    )
    (repo / "suite.py").write_text(suite, encoding="utf-8")


def commit(repo: Path, message: str) -> None:
    run_git(repo, "add", "suite.py")
    run_git(repo, "commit", "-q", "-m", message)


def init_repo(repo: Path) -> None:
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    run_git(repo, "init", "-q")
    # Keep the initial branch name stable without depending on newer git options.
    run_git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
    run_git(repo, "config", "user.name", "mx-mergetool-tests")
    run_git(repo, "config", "user.email", "mx-mergetool-tests@example.invalid")


def create_simple_case(repo: Path) -> None:
    init_repo(repo)

    write_suite(
        repo,
        sdk_version="base-sdk",
        compiler_version="base-compiler",
        sdk_url="https://example.invalid/sdk-base.git",
        metadata_key="base",
    )
    commit(repo, "base")

    run_git(repo, "checkout", "-q", "-b", "local")
    write_suite(
        repo,
        sdk_version="local-sdk",
        compiler_version="base-compiler",
        sdk_url="https://example.invalid/sdk-base.git",
        metadata_key="base",
    )
    commit(repo, "local")
    run_git(repo, "branch", "expected")

    run_git(repo, "checkout", "-q", "master")
    run_git(repo, "checkout", "-q", "-b", "remote")
    write_suite(
        repo,
        sdk_version="remote-sdk",
        compiler_version="base-compiler",
        sdk_url="https://example.invalid/sdk-base.git",
        metadata_key="base",
    )
    commit(repo, "remote")

    run_git(repo, "checkout", "-q", "master")


def create_multi_import_case(repo: Path) -> None:
    init_repo(repo)

    write_suite(
        repo,
        sdk_version="base-sdk",
        compiler_version="base-compiler",
        sdk_url="https://example.invalid/sdk-base.git",
        metadata_key="base",
    )
    commit(repo, "base")

    run_git(repo, "checkout", "-q", "-b", "local")
    write_suite(
        repo,
        sdk_version="local-sdk",
        compiler_version="local-compiler",
        sdk_url="https://example.invalid/sdk-base.git",
        metadata_key="base",
    )
    commit(repo, "local")

    run_git(repo, "checkout", "-q", "-b", "expected")
    write_suite(
        repo,
        sdk_version="local-sdk",
        compiler_version="local-compiler",
        sdk_url="https://example.invalid/sdk-remote.git",
        metadata_key="remote",
    )
    commit(repo, "expected")

    run_git(repo, "checkout", "-q", "master")
    run_git(repo, "checkout", "-q", "-b", "remote")
    write_suite(
        repo,
        sdk_version="remote-sdk",
        compiler_version="remote-compiler",
        sdk_url="https://example.invalid/sdk-remote.git",
        metadata_key="remote",
    )
    commit(repo, "remote")

    run_git(repo, "checkout", "-q", "master")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create local git repositories for mx mergetool CI tests")
    parser.add_argument("simple_repo", help="Path for the simple conflict fixture repository")
    parser.add_argument("complex_repo", help="Path for the multi-import conflict fixture repository")
    args = parser.parse_args()

    create_simple_case(Path(args.simple_repo))
    create_multi_import_case(Path(args.complex_repo))


if __name__ == "__main__":
    main()
