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
import os
import sys
import tempfile
import argparse
import textwrap

from . import mx


def remove_conflict_markers(filename):
    """
    Removes conflicts markers from a file's content, keeps only the content of the first
    conflict branch and returns the result.

    Merge conflict marker might be nested. A basic example looks like:

        "imports": {
            "suites": [
                {
                    "name": "substratevm",
                    "subdir": True,
    <<<<<<< HEAD
                    "version": "db85a24b2358c7ebf7850a3cfd7a0e28e693cbb1",
    =======
                    "version": "2449afbb28dadf2d9a70a866da06d664f1d1a539",
    >>>>>>> upstream/master
                    "urls": [
                        {"url": "https://github.com/oracle/graal.git", "kind": "git"},
                    ]
                },
            ],
        },

    A more complex example would be:

        "imports": {
            "suites": [
                {
                    "name": "substratevm",
                    "subdir": True,
    <<<<<<< HEAD
                    "version": "db85a24b2358c7ebf7850a3cfd7a0e28e693cbb1",
    ||||||| merged common ancestors
    <<<<<<<<< Temporary merge branch 1
                    "version": "f1dffe84fdce6f45a42528e4f114cd8c52d1aae1",
    ||||||||| merged common ancestors
    <<<<<<<<<<< Temporary merge branch 1
                    "version": "414d874be3af1a21a3c8ebfd9cbd163b985a0a68",
    ||||||||||| 68ef48ab8db
                    "version": "69baa168b4c0602b078f0bc0b49d95b93582ba95",
    ===========
                    "version": "5b5a1351f3a02177e0878d5f2cd01c56507e8ba4",
    >>>>>>>>>>> Temporary merge branch 2
    =========
                    "version": "06ad740e1c0817d3d555b514ced92dd4465d32db",
    >>>>>>>>> Temporary merge branch 2
    =======
                    "version": "2449afbb28dadf2d9a70a866da06d664f1d1a539",
    >>>>>>> upstream/master
                    "urls": [
                        {"url": "https://github.com/oracle/graal.git", "kind": "git"},
                    ]
                },
            ],
        },

    """
    with open(filename, "r") as fp:
        suite_content = fp.read()
        result = []
        conflict_level = 0
        keep = True
        for line in suite_content.splitlines(keepends=True):
            if line.startswith("<<"):
                if conflict_level > 0:
                    # inner conflict scope -> stop printing
                    keep = False
                conflict_level += 1
                continue
            if line.startswith("||"):
                # in a conflict scope and not in the first branch -> stop printing
                keep = False
                continue
            if line.startswith("=="):
                # in a conflict scope and not in the first branch -> stop printing
                keep = False
                continue
            if line.startswith(">>"):
                conflict_level -= 1
                if conflict_level == 0:
                    # end of conflict scope -> restart printing
                    keep = True
                continue
            if keep:
                result.append(line)
        return "".join(result)


@mx.suite_context_free
def mergetool_suite_import(args):
    parser = argparse.ArgumentParser(
        prog="mx mergetool-suite-import",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """
            A `git mergetool` to fix mx suite import update conflicts in suite.py files.

            The tool resets all suite import revisions to the LOCAL revisions and thus, resolving the merge conflict.
            After updating the imports (if any), `diff3` is called to resolve the remaining conflicts.

            Note that the tool is only meant to resolve the conflict. It is not guaranteed that the import update
            is semantically correct. For example, the imports in the merged file might be older than the merged-in imports.
            Tools like `mx scheckimports` can be used to fix the imported revisions after the merge.

            To use the mergetool via `git`, add the following entry to your `.gitconfig`:

            [mergetool "mx-suite-import"]
                cmd = mx mergetool-suite-import "$LOCAL" "$BASE" "$REMOTE" "$MERGED"
                trustExitCode = true

            Then, merge conflicts can be resolved as follows:

            $ git merge remote-branch
            Automatic merge failed; fix conflicts and then commit the result.
            $ git mergetool --tool=mx-suite-import
            """
        ),
    )
    parser.add_argument(
        "LOCAL",
        help="the name of a temporary file containing the contents of the file on the current branch",
    )
    parser.add_argument(
        "BASE",
        help="the name of a temporary file containing the common base of the files to be merged",
    )
    parser.add_argument(
        "REMOTE",
        help="the name of a temporary file containing the contents of the file from the branch being merged",
    )
    parser.add_argument(
        "MERGED",
        help="the name of the file to which the merge tool should write the results of a successful merge",
    )

    args = parser.parse_args(args)

    local = args.LOCAL
    base = args.BASE
    remote = args.REMOTE
    merged = args.MERGED

    def _run_diff3(local, base, remote, merged):
        out = mx.OutputCapture()
        ret = mx.run(["diff3", "-m", local, base, remote], nonZeroIsFatal=False, out=out)
        with open(merged, "w") as fp:
            fp.write(out.data)
        return ret

    def _fallback(message=None):
        if message:
            print(message)
        ret = _run_diff3(local, base, remote, merged)
        sys.exit(ret)

    def _assert_or_fallback(cond, message=None):
        if cond:
            return
        _fallback(message)

    _assert_or_fallback("suite.py" in os.path.basename(merged), "Only merge suite.py files. Falling back to diff3")

    def read_suite_imports(suite_content, filename):
        my_globals = {}
        my_locals = {}
        try:
            exec(suite_content, my_globals, my_locals)  # pylint: disable=exec-used
        except Exception as ex:  # pylint: disable=broad-except
            msg = f"Cannot load suite file {filename}: {ex}"
            _fallback(msg)
        return my_locals.get("suite", {}).get("imports", {}).get("suites")

    def to_import_dict(suite_imports):
        return {s["name"]: s["version"] for s in suite_imports if "version" in s}

    local_content = remove_conflict_markers(local)
    remote_content = remove_conflict_markers(remote)
    base_content = remove_conflict_markers(base)

    local_imports = read_suite_imports(local_content, local)
    remote_imports = read_suite_imports(remote_content, remote)
    base_imports = read_suite_imports(base_content, base)

    local_import_dict = to_import_dict(local_imports)
    remote_import_dict = to_import_dict(remote_imports)
    base_import_dict = to_import_dict(base_imports)

    _assert_or_fallback(
        set(local_import_dict.keys()) == set(remote_import_dict.keys()),
        f"Cannot merge files which import different suites: {local_import_dict.keys()} vs {remote_import_dict.keys()}",
    )

    mismatches = [
        s
        for s in local_import_dict.keys()
        if local_import_dict[s] != remote_import_dict[s] and local_import_dict[s] != base_import_dict[s]
    ]
    _assert_or_fallback(mismatches, "Not import mismatches. Falling back to diff3")

    # fix mismatches

    for s in mismatches:
        local_rev = local_import_dict[s]
        remote_rev = remote_import_dict[s]
        base_rev = base_import_dict[s]
        remote_content = remote_content.replace(remote_rev, local_rev)
        base_content = base_content.replace(base_rev, local_rev)

    new_local = None
    new_remote = None
    new_base = None
    try:
        # fmt: off
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as new_local_fp, \
              tempfile.NamedTemporaryFile(mode="w", delete=False) as new_remote_fp, \
              tempfile.NamedTemporaryFile(mode="w", delete=False) as new_base_fp:
            # fmt: on
            new_local_fp.write(local_content)
            new_local = new_local_fp.name
            new_remote_fp.write(remote_content)
            new_remote = new_remote_fp.name
            new_base_fp.write(base_content)
            new_base = new_base_fp.name
        ret = _run_diff3(local, new_base, new_remote, merged)
        sys.exit(ret)
    finally:
        if new_local:
            os.unlink(new_local)
        if new_remote:
            os.unlink(new_remote)
        if new_base:
            os.unlink(new_base)
