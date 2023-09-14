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

import argparse
import fnmatch
import logging
import os

import mx
import mx_stoml

class TomlParsingException(Exception):
    pass

def load_toml_from_fd(fd):
    try:
        import tomllib
        try:
            return tomllib.load(fd)
        except tomllib.TOMLDecodeError:
            raise TomlParsingException()
    except ImportError:
        # Try another library
        pass

    try:
        import toml
        try:
            return toml.load(fd)
        except toml.TomlDecodeError:
            raise TomlParsingException()
    except ImportError:
        # Try another library
        pass

    # No other libraries to try, falling back to our simplified parser
    try:
        tree = mx_stoml.parse_fd(fd)
        return {
            'rule': tree,
        }
    except RuntimeError:
        raise TomlParsingException()


def whitespace_split_(inp):
    if isinstance(inp, str):
        return inp.split()
    else:
        return inp

def is_some_item_in_set(items, the_set):
    for i in items:
        if i in the_set:
            return True
    return False

class FileOwners:
    def __init__(self, src_root):
        self.src = os.path.abspath(src_root)

    def get_path_components(self, filepath):
        res = []
        while filepath != '':
            (dirs, filename) = os.path.split(filepath)
            res.append(filepath)
            filepath = dirs
        return reversed(res)

    def parse_ownership(self, fd, name):
        try:
            tree = load_toml_from_fd(fd)
            logging.debug("Tree is %s", tree)
            for rule in tree.get('rule', []):
                if not 'files' in rule:
                    logging.warning("Ignoring rule %s in %s as it contains no files", rule, name)
                    continue
                if (not 'any' in rule) and (not 'all' in rule):
                    logging.warning("Ignoring rule %s in %s as it contains no owner specification", rule, name)
                    continue

                rule['files'] = whitespace_split_(rule['files'])
                optional_owners = whitespace_split_(rule.get('any', []))
                if optional_owners:
                    for pat in rule['files']:
                        yield pat, optional_owners, "any"
                mandatory_owners = whitespace_split_(rule.get('all', []))
                if mandatory_owners:
                    for pat in rule['files']:
                        yield pat, mandatory_owners, "all"

        except TomlParsingException:
            logging.warning("Ignoring invalid input from %s", name)

    def parse_ownership_from_files(self, files):
        for fo in files:
            try:
                full_path = os.path.join(self.src, fo)
                with open(full_path, 'rb') as f:
                    for i in self.parse_ownership(f, full_path):
                        yield i
            except IOError:
                pass

    def get_owners_of(self, filepath):
        components = ['.'] + list(self.get_path_components(filepath))
        filename = os.path.split(filepath)[1]
        owners_files = [
            os.path.join(i, 'OWNERS.toml')
            for i in components[:-1]
        ]
        result = {}
        ownership = self.parse_ownership_from_files(owners_files)
        for pat, owners, modifiers in ownership:
            if fnmatch.fnmatch(filename, pat):
                if "all" in modifiers:
                    result["all"] = sorted(owners)
                if "any" in modifiers:
                    result["any"] = sorted(owners)
        return result

def summarize_owners(all_owners):
    must_review = set()
    anyof_reviewers = []

    for owners in all_owners:
        for owner in owners.get('all', []):
            must_review.add(owner)

    for owners in all_owners:
        if owners.get('any', []):
            # One reviewer is already present? Skip this completely
            if not is_some_item_in_set(owners['any'], must_review):
                anyof_reviewers.append(owners['any'])

    return {
        "all": sorted(must_review),
        "any": list(set(map(tuple, anyof_reviewers))),
    }

def run_capture(args, must_succeed=True):
    cmd_stdout = mx.OutputCapture()
    cmd_stderr = mx.OutputCapture()
    cmd_rc = mx.run(args, must_succeed, cmd_stdout, cmd_stderr)
    return (cmd_rc, cmd_stdout.data, cmd_stderr.data)

def git_diff_name_only(extra_args=None):
    args = ['git', 'diff', '--name-only', '-z']
    if extra_args:
        args.extend(extra_args)
    rc, out, errout = run_capture(args)
    assert rc == 0
    return list(filter(lambda x: x != '', out.split('\0')))

MX_CODEOWNERS_HELP = """Find code owners from OWNERS.toml files.


Can be executed in three modes.

* Without any options but with list of files: print owners of the
  provided files. Example:

    mx codeowners -- substratevm/LICENSE substratevm/ci/ci.jsonnet

* Without any arguments at all it prints owners of currently modified
  but unstaged files (for Git). In other words, it prints possible
  reviewers for changed but uncomitted files. Internally uses
  git diff --name-only to query list of files.

* When -a or -b BRANCH is provided, it looks also for all files
  modified with comparison to given BRANCH (or to master with -a
  only). In other words, it prints possible reviewers for the whole
  pull request.
"""

@mx.command('mx', 'codeowners')
def codeowners(args):
    """Find code owners from OWNERS.toml files."""
    parser = argparse.ArgumentParser(prog='mx codeowners', formatter_class=argparse.RawTextHelpFormatter, description=MX_CODEOWNERS_HELP)
    parser.add_argument('files', metavar='FILENAME', nargs='*', help='Filenames to list owners of')
    parser.add_argument('-a', dest='all_changes', action='store_true', default=False, help='Print reviewers for this branch against master.')
    parser.add_argument('-b', dest='upstream_branch', metavar='BRANCH', default=None, help='Print reviewers for this branch against BRANCH.')
    args = parser.parse_args(args)

    if args.upstream_branch:
        args.all_changes = True
    else:
        args.upstream_branch = 'master'

    if args.all_changes and args.files:
        mx.abort("Do not specify list of files with -b or -a")

    # TODO: what is the right starting directory?
    owners = FileOwners('.')

    if args.all_changes:
        # Current modifications and all changes up to the upstream branch
        args.files = git_diff_name_only([args.upstream_branch]) + git_diff_name_only()
    elif not args.files:
        # No arguments, query list of currently modified files
        args.files = git_diff_name_only()

    file_owners = [owners.get_owners_of(f) for f in args.files]
    reviewers = summarize_owners(file_owners)

    if reviewers['all']:
        print("Mandatory reviewers (all of these must review):")
        for i in reviewers['all']:
            print(" o", i)
    if reviewers['any']:
        print("Any-of reviewers (at least one from each line):")
        for i in reviewers['any']:
            print(" o", ' or '.join(i))

