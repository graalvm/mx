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

__all__ = [
    "FileOwners",
]

import argparse
import fnmatch
import logging
import os

from . import mx
from . import mx_stoml

class _TomlParsingException(Exception):
    def __init__(self, cause):
        Exception.__init__()
        self.cause = cause

    def __str__(self):
        return str(self.cause)

def _load_toml_from_fd(fd):
    try:
        import tomllib
        try:
            return tomllib.load(fd)
        except tomllib.TOMLDecodeError as e:
            raise _TomlParsingException(str(e))
    except ImportError:
        # Try another library
        pass

    try:
        import toml
        try:
            # This is kind of confusing because tomllib expects 'rb',
            # toml expects 'rt' mode when reading from a file and for
            # mx_stoml we also decode from UTF-8 ourselves explicitly.
            return toml.loads(fd.read().decode('utf-8'))
        except toml.TomlDecodeError as e:
            raise _TomlParsingException(e)
    except ImportError:
        # Try another library
        pass

    # No other libraries to try, falling back to our simplified parser
    try:
        tree = mx_stoml.parse_fd(fd)
        return {
            'rule': tree,
        }
    except RuntimeError as e:
        raise _TomlParsingException(e)


def _whitespace_split(inp):
    if isinstance(inp, str):
        return inp.split()
    else:
        return inp

def _is_some_item_in_set(items, the_set):
    for i in items:
        if i in the_set:
            return True
    return False

class FileOwners:
    def __init__(self, src_root):
        self.src = os.path.abspath(src_root)

    def _get_path_components(self, filepath):
        res = []
        while filepath != '':
            (dirs, _) = os.path.split(filepath)
            res.append(filepath)
            # For absolute path on Unix, we end with '/'
            if filepath == dirs:
                break
            filepath = dirs
        return reversed(res)

    def _parse_ownership(self, fd, name):
        try:
            tree = _load_toml_from_fd(fd)
            logging.debug("Tree is %s", tree)
            for rule in tree.get('rule', []):
                if not 'files' in rule:
                    logging.warning("Ignoring rule %s in %s as it contains no files", rule, name)
                    continue
                if (not 'any' in rule) and (not 'all' in rule):
                    logging.warning("Ignoring rule %s in %s as it contains no owner specification", rule, name)
                    continue

                rule['files'] = _whitespace_split(rule['files'])
                optional_owners = _whitespace_split(rule.get('any', []))
                if optional_owners:
                    for pat in rule['files']:
                        yield pat, optional_owners, "any"
                mandatory_owners = _whitespace_split(rule.get('all', []))
                if mandatory_owners:
                    for pat in rule['files']:
                        yield pat, mandatory_owners, "all"

        except _TomlParsingException as e:
            logging.warning("Ignoring invalid input from %s: %s", name, e)

    def _parse_ownership_from_files(self, files):
        for fo in files:
            try:
                if os.path.isabs(fo):
                    full_path = fo
                else:
                    full_path = os.path.join(self.src, fo)
                with open(full_path, 'rb') as f:
                    for i in self._parse_ownership(f, full_path):
                        yield i
            except IOError:
                pass

    def get_owners_of(self, filepath):
        components = ([] if os.path.isabs(filepath) else ['.']) + list(self._get_path_components(filepath))
        filename = os.path.split(filepath)[1]
        owners_files = [
            os.path.join(i, 'OWNERS.toml') if os.path.isabs(i) else os.path.join(self.src, i, 'OWNERS.toml')
            for i in components[:-1]
        ]
        owners_files = [i for i in owners_files if os.path.commonprefix([i, self.src]) == self.src]
        result = {}
        ownership = self._parse_ownership_from_files(owners_files)
        for pat, owners, modifiers in ownership:
            if fnmatch.fnmatch(filename, pat):
                if "all" in modifiers:
                    result["all"] = sorted(owners)
                if "any" in modifiers:
                    result["any"] = sorted(owners)
        logging.debug("File %s owned by %s (looked into %s)", filepath, result, owners_files)
        return result

def _summarize_owners(all_owners):
    must_review = set()
    anyof_reviewers = []

    for owners in all_owners:
        for owner in owners.get('all', []):
            must_review.add(owner)

    for owners in all_owners:
        if owners.get('any', []):
            # One reviewer is already present? Skip this completely
            if not _is_some_item_in_set(owners['any'], must_review):
                anyof_reviewers.append(owners['any'])

    return {
        "all": sorted(must_review),
        "any": list(set(map(tuple, anyof_reviewers))),
    }

def _run_capture(args, must_succeed=True):
    cmd_stdout = mx.OutputCapture()
    cmd_stderr = mx.OutputCapture()
    cmd_rc = mx.run(args, must_succeed, cmd_stdout, cmd_stderr)
    return (cmd_rc, cmd_stdout.data, cmd_stderr.data)

def _git_diff_name_only(extra_args=None):
    args = ['git', 'diff', '--name-only', '-z']
    if extra_args:
        args.extend(extra_args)
    rc, out, _ = _run_capture(args)
    assert rc == 0
    return list(filter(lambda x: x != '', out.split('\0')))

def _git_get_repo_root_or_cwd():
    rc, out, _ = _run_capture(['git', 'rev-parse', '--show-toplevel'])
    if rc != 0:
        return '.'
    else:
        return out.rstrip('\n')

_MX_CODEOWNERS_HELP = """Find code owners from OWNERS.toml files.


Can be executed in three modes.

* Without any options but with list of files: print owners of the
  provided files. Example:

    mx codeowners -- substratevm/LICENSE substratevm/ci/ci.jsonnet

* Without any arguments at all it prints owners of currently modified
  but unstaged files (for Git). In other words, it prints possible
  reviewers for changed but uncommitted files. Internally uses
  git diff --name-only to query list of files.

* When -a or -b BRANCH is provided, it looks also for all files
  modified with comparison to given BRANCH (or to master with -a
  only). In other words, it prints possible reviewers for the whole
  pull request.
"""

_MX_CODEOWNERS_HELP2 = """The ownership is read from OWNERS.toml files that can be added to any
directory. As an example, let us have a look at the following snippet.

    [[rule]]
    files = "*.jsonnet *.libsonnet"
    any = [
        "ci.master@oracle.com",
        "another.ci.master@oracle.com",
    ]
    [[rule]]
    files = "*.md"
    any = "doc.owner@oracle.com release.manager@oracle.com"

This says that files matching *.jsonnet and *.libsonnet are owned
by ci.master@oracle.com and another.ci.master@oracle.com.
Similarly, *.md files are owned by doc.owner@oracle.com and
release.manager@oracle.com.

These rules are applied to files in the same directory (i.e. same
as the one where this OWNERS.toml is stored) as well as to files
matching the pattern in subdirectories. The pattern can be
overridden by another OWNERS.toml in a subdirectory. In other words,
ownership tries to find first matching rule, starting with file
OWNERS.toml in current directory and traversing to parent ones.
Directories without OWNERS.toml are skipped and search continues
in their parent.

Note that we allow both explicit TOML arrays as well as implicit
separator of whitespace when specifying list of owners or list
of file patterns.

When no rule matches, the tool searches in parent directories too
(up to nearest Git repository root).

"""

@mx.command('mx', 'codeowners')
def codeowners(args):
    """Find code owners from OWNERS.toml files."""
    parser = argparse.ArgumentParser(prog='mx codeowners', formatter_class=argparse.RawTextHelpFormatter, description=_MX_CODEOWNERS_HELP, epilog=_MX_CODEOWNERS_HELP2)
    parser.add_argument('files', metavar='FILENAME', nargs='*', help='File names to list owners of (relative to current work dir).')
    parser.add_argument('-a', dest='all_changes', action='store_true', default=False, help='Print reviewers for this branch against master.')
    parser.add_argument('-b', dest='upstream_branch', metavar='BRANCH', default=None, help='Print reviewers for this branch against BRANCH.')
    args = parser.parse_args(args)

    if args.upstream_branch:
        args.all_changes = True
    else:
        args.upstream_branch = 'master'

    if args.all_changes and args.files:
        mx.abort("Do not specify list of files with -b or -a")

    owners = FileOwners(_git_get_repo_root_or_cwd())

    if args.all_changes:
        # Current modifications and all changes up to the upstream branch
        args.files = _git_diff_name_only([args.upstream_branch]) + _git_diff_name_only()
    elif not args.files:
        # No arguments, query list of currently modified files
        args.files = _git_diff_name_only()

    file_owners = {f: owners.get_owners_of(os.path.abspath(f)) for f in args.files}
    reviewers = _summarize_owners(file_owners.values())

    if reviewers['all']:
        print("Mandatory reviewers (all of these must review):")
        for i in reviewers['all']:
            mx.log(" o " + i)
    if reviewers['any']:
        print("Any-of reviewers (at least one from each line):")
        for i in reviewers['any']:
            mx.log(" o " + ' or '.join(i))

    if len(reviewers["all"]) == 0 and len(reviewers["any"]) == 0:
        mx.log("No specific reviewer requested by OWNERS.toml files for the given changeset.")

    num_files_changed = len(file_owners.keys())
    num_owned_files = len([f for f, o in file_owners.items() if o])

    if num_files_changed == 0:
        mx.warn("The changeset is empty!")
    else:
        print(f"\n{num_owned_files}/{num_files_changed} of the files have ownership defined by one or more OWNERS.toml file(s)")
        if num_owned_files < num_files_changed:
            mx.log("Consider adding ownership for the files with no ownership! (mx verbose mode shows details)")

        import pprint
        mx.logv("Ownership of each file:")
        mx.logv(pprint.pformat(file_owners, indent=2))
