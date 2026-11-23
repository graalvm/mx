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
# pylint: disable=protected-access

import hashlib
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_git_parent_cache import git_head, mx_run_opts, orig_mx, run_git


class GitCacheNegotiationTest(unittest.TestCase):
    def test_fetch_option_support(self):
        for supported in (False, True):
            with self.subTest(supported=supported), mx_run_opts(), patch.object(
                orig_mx.GitConfig, "_fetch_negotiation_tip_supported", None
            ):
                git = orig_mx.GitConfig()
                help_text = "usage: git fetch\n" + ("--negotiation-tip <revision>" if supported else "")
                result = subprocess.CompletedProcess(["git", "fetch", "-h"], 129, stdout=help_text)
                with patch.object(orig_mx.subprocess, "run", return_value=result) as probe:
                    with patch.object(orig_mx.subprocess, "check_call", return_value=0) as fetch:
                        git._fetch("repo", "url")
                        probe.assert_not_called()
                        fetch.assert_called_with(["git", "fetch", "--quiet", "url"], cwd="repo")
                        tip = "refs/remotes/repository/*"
                        for _ in range(2):
                            orig_mx.GitConfig()._fetch("repo", "url", negotiation_tip=tip)
                        expected = ["git", "fetch", "--quiet"]
                        if supported:
                            expected.append("--negotiation-tip=" + tip)
                        fetch.assert_called_with(expected + ["url"], cwd="repo")
                probe.assert_called_once()

    @staticmethod
    def init_repo(root, name, bare=False):
        repo = root / name
        repo.mkdir()
        run_git(repo, "init", "-q", *(["--bare"] if bare else []))
        run_git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
        if not bare:
            run_git(repo, "config", "user.name", "Test User")
            run_git(repo, "config", "user.email", "test@example.com")
        return repo

    @staticmethod
    def commit(repo, text):
        (repo / "tracked.txt").write_text(text, encoding="utf-8")
        run_git(repo, "add", "tracked.txt")
        run_git(repo, "commit", "-q", "-m", text)
        return git_head(repo)

    def test_packet_negotiation_excludes_unrelated_history(self):
        git = orig_mx.GitConfig()
        if not git._supports_fetch_negotiation_tip():
            self.skipTest("Git does not support --negotiation-tip")
        with tempfile.TemporaryDirectory() as tmp_dir, mx_run_opts():
            root = Path(tmp_dir)
            unrelated = self.init_repo(root, "unrelated")
            unrelated_head = self.commit(unrelated, "unrelated history")
            source = self.init_repo(root, "source")
            first = self.commit(source, "target history")
            url = source.as_uri()
            namespace = "refs/remotes/" + hashlib.sha1(url.encode()).hexdigest() + "/"
            refspec = "+refs/heads/*:" + namespace + "*"
            trace = root / "packets.log"

            def fetch_haves(cache, tip):
                trace.write_text("", encoding="utf-8")
                with patch.dict(os.environ, {"GIT_TRACE_PACKET": str(trace)}):
                    git._fetch(str(cache), url, refspec, negotiation_tip=tip)
                return set(re.findall(r"> have ([0-9a-f]{40})", trace.read_text(encoding="utf-8")))

            caches = []
            for name in ("unrestricted", "restricted"):
                cache = self.init_repo(root, name, bare=True)
                # Protocol v0 makes the negative control negotiate even for a
                # new, unrelated repository. Configure only this temporary repo.
                run_git(cache, "config", "protocol.version", "0")
                run_git(cache, "fetch", "-q", unrelated.as_uri(), "+refs/heads/*:refs/remotes/unrelated/*")
                # Tags and branch refs outside the target namespace must not
                # leak into negotiation either.
                run_git(cache, "update-ref", "refs/tags/unrelated", unrelated_head)
                run_git(cache, "update-ref", "refs/heads/unrelated", unrelated_head)
                caches.append(cache)
            self.assertIn(unrelated_head, fetch_haves(caches[0], None))
            self.assertEqual(fetch_haves(caches[1], namespace + "*"), set())
            self.assertEqual(run_git(caches[1], "rev-parse", namespace + "master").stdout.strip(), first)

            second = self.commit(source, "new target commit")
            haves = fetch_haves(caches[1], namespace + "*")
            self.assertIn(first, haves)
            self.assertNotIn(unrelated_head, haves)
            self.assertEqual(run_git(caches[1], "rev-parse", namespace + "master").stdout.strip(), second)
            self.assertEqual(
                run_git(caches[1], "rev-parse", "refs/remotes/unrelated/master").stdout.strip(), unrelated_head
            )


if __name__ == "__main__":
    unittest.main()
