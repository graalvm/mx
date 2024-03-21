#!/usr/bin/env python3
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

"""
Checks that a PR updates `mx.version` to a higher version.
The PR content is the diff between commits P and M where P is the branch
named by the FROM_BRANCH environment variable and M is the merge-base
of P and the branch named by the TO_BRANCH environment variable.
"""

import subprocess
import re
import os
from os.path import realpath, dirname, join

mx_home = realpath(join(dirname(__file__), ".."))


def _check_output_str(*args, **kwargs):
    return subprocess.check_output(*args, **kwargs).decode()


def git(args):
    return _check_output_str(["git"] + args, cwd=mx_home)


version_re = re.compile(r'.*version = VersionSpec\("([^"]+)"\).*', re.DOTALL)
new_version_re = re.compile(r'.*\+version = VersionSpec\("([^"]+)"\).*', re.DOTALL)
old_version_re = re.compile(r'.*\-version = VersionSpec\("([^"]+)"\).*', re.DOTALL)


def find_remote_branch(local_branch):
    all_branches = frozenset((e.strip() for e in git(["branch", "-a"]).split()))
    for remote in git(["remote"]).split():
        remote_branch = f"remotes/{remote}/{local_branch}"
        if remote_branch in all_branches:
            return remote_branch
    raise SystemExit(f"Could not find remote branch corresponding to {local_branch}")


try:
    from_branch = find_remote_branch(os.environ["FROM_BRANCH"])
    to_branch = find_remote_branch(os.environ["TO_BRANCH"])
except KeyError as e:
    raise SystemExit(f"Missing environment variable {e}")

merge_base = git(["merge-base", to_branch, from_branch]).strip()
diff = git(["diff", merge_base, from_branch, "--", "src/mx/_impl/mx.py"]).strip()
new_version = new_version_re.match(diff)
old_version = old_version_re.match(diff)

# Get mx version of the TO_BRANCH
to_branch_mx_py = git(["cat-file", "-p", f"{to_branch}:src/mx/_impl/mx.py"]).strip()
to_branch_version = version_re.match(to_branch_mx_py)


def version_to_ints(spec):
    try:
        return [int(e) for e in spec.split(".")]
    except ValueError as e:
        raise SystemExit(f"{spec} is not a valid mx version string: {e}")


if new_version and old_version:
    new_tag = new_version.group(1)
    old_tag = old_version.group(1)
    print(f"Found update of mx version from {old_tag} to {new_tag}")
    old = version_to_ints(old_tag)
    new = version_to_ints(new_tag)
    if old >= new:
        raise SystemExit(f"Version update does not go forward ({new_tag} < {old_tag})")
    to_branch_tag = to_branch_version.group(1)
    to_branch_val = version_to_ints(to_branch_tag)
    if to_branch_val >= new:
        raise SystemExit(f"Version update does not go forward ({new_tag} < {to_branch_tag})")
else:
    raise SystemExit(
        f"Could not find mx version update in the PR (based on `git diff {merge_base}..{from_branch}`).\n\nPlease bump the value of the `version` field near the bottom of src/mx/_impl/mx.py"
    )
