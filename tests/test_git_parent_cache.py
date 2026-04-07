#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2026, Oracle and/or its affiliates. All rights reserved.
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
# pylint: disable=duplicate-code

from __future__ import annotations

import importlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

orig_mx = importlib.import_module("mx._impl.mx")


@contextmanager
def monkeypatch_attr(obj, name, value):
    previous = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield value
    finally:
        setattr(obj, name, previous)


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True)


def git_head(repo: Path) -> str:
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


@contextmanager
def mx_run_opts():
    sentinel = object()
    overrides = {
        "verbose": False,
        "very_verbose": False,
        "exec_log": None,
        "ptimeout": 0,
        "vm_prefix": None,
    }
    previous = {name: getattr(orig_mx._opts, name, sentinel) for name in overrides}
    for name, value in overrides.items():
        setattr(orig_mx._opts, name, value)

    real_run = orig_mx.run

    def quiet_run(args, *run_args, **run_kwargs):
        if args and args[0] == "git":
            if run_kwargs.get("out") is None:
                run_kwargs["out"] = orig_mx.OutputCapture()
            if run_kwargs.get("err") is None:
                run_kwargs["err"] = orig_mx.OutputCapture()
        return real_run(args, *run_args, **run_kwargs)

    try:
        with monkeypatch_attr(orig_mx, "run", quiet_run):
            with monkeypatch_attr(orig_mx, "log", lambda *args, **kwargs: None):
                yield
    finally:
        for name, value in previous.items():
            if value is sentinel:
                delattr(orig_mx._opts, name)
            else:
                setattr(orig_mx._opts, name, value)


class GitParentCacheInvalidationTest(unittest.TestCase):
    def init_repo(self, root: Path, name: str) -> Path:
        repo = root / name
        repo.mkdir()
        run_git(repo, "init", "-q")
        run_git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
        run_git(repo, "config", "user.name", "Test User")
        run_git(repo, "config", "user.email", "test@example.com")
        (repo / "tracked.txt").write_text("one\n")
        run_git(repo, "add", "tracked.txt")
        run_git(repo, "commit", "-q", "-m", "initial")
        return repo

    def second_commit(self, repo: Path) -> str:
        (repo / "tracked.txt").write_text("two\n")
        run_git(repo, "commit", "-a", "-q", "-m", "second")
        return git_head(repo)

    def assert_parent_cache_updates(self, repo: Path, update_action, expected_head: str):
        git = orig_mx.GitConfig()
        cached_head = git.parent(str(repo))
        self.assertNotEqual(cached_head, expected_head)
        update_action(git)
        self.assertEqual(git.parent(str(repo)), expected_head)

    def test_parent_cache_invalidated_after_commit(self):
        with tempfile.TemporaryDirectory() as tmp_dir, mx_run_opts():
            repo = self.init_repo(Path(tmp_dir), "repo")
            git = orig_mx.GitConfig()
            initial_head = git.parent(str(repo))

            (repo / "tracked.txt").write_text("two\n")
            self.assertTrue(git.commit(str(repo), "second", abortOnError=True))

            expected_head = git_head(repo)
            self.assertNotEqual(initial_head, expected_head)
            self.assertEqual(git.parent(str(repo)), expected_head)

    def test_parent_cache_invalidated_after_detached_checkout_update(self):
        with tempfile.TemporaryDirectory() as tmp_dir, mx_run_opts():
            repo = self.init_repo(Path(tmp_dir), "repo")
            first_head = git_head(repo)
            self.second_commit(repo)

            self.assert_parent_cache_updates(
                repo,
                lambda git: self.assertTrue(git.update(str(repo), rev=first_head, abortOnError=True)),
                first_head,
            )

    def test_parent_cache_invalidated_after_checkout_branch_update(self):
        with tempfile.TemporaryDirectory() as tmp_dir, mx_run_opts():
            repo = self.init_repo(Path(tmp_dir), "repo")
            first_head = git_head(repo)
            self.second_commit(repo)
            run_git(repo, "branch", "older", first_head)

            self.assert_parent_cache_updates(
                repo,
                lambda git: self.assertTrue(git.update_to_branch(str(repo), "older", abortOnError=True)),
                first_head,
            )

    def test_parent_cache_invalidated_after_hard_reset(self):
        with tempfile.TemporaryDirectory() as tmp_dir, mx_run_opts():
            repo = self.init_repo(Path(tmp_dir), "repo")
            first_head = git_head(repo)
            self.second_commit(repo)

            self.assert_parent_cache_updates(
                repo,
                lambda git: self.assertTrue(git._reset_rev(first_head, dest=str(repo), abortOnError=True)),
                first_head,
            )

    def test_parent_cache_invalidated_after_pull_with_update(self):
        with tempfile.TemporaryDirectory() as tmp_dir, mx_run_opts():
            tmp_path = Path(tmp_dir)
            source = self.init_repo(tmp_path, "source")
            remote = tmp_path / "remote.git"
            subprocess.run(
                ["git", "clone", "-q", "--bare", str(source), str(remote)], check=True, text=True, capture_output=True
            )
            run_git(source, "remote", "add", "origin", str(remote))
            run_git(source, "push", "-q", "-u", "origin", "master")

            work = tmp_path / "work"
            subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, text=True, capture_output=True)
            run_git(work, "config", "user.name", "Test User")
            run_git(work, "config", "user.email", "test@example.com")

            (source / "tracked.txt").write_text("two\n")
            run_git(source, "commit", "-a", "-q", "-m", "second")
            expected_head = git_head(source)
            run_git(source, "push", "-q", "origin", "master")

            self.assert_parent_cache_updates(
                work,
                lambda git: self.assertTrue(git.pull(str(work), update=True, abortOnError=True)),
                expected_head,
            )


if __name__ == "__main__":
    unittest.main()
