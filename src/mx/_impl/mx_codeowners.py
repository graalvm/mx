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
import json
import os

from . import mx
from . import mx_stoml

class _TomlParsingException(Exception):
    pass

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
        """Returns all of the sub-paths for a filepath, ordered from shortest to longest.

        Example:
        For filepath = '/full/path/to/file.py'
        The method returns ['/', '/full', '/full/path', '/full/path/to', '/full/path/to/file.py']
        """

        res = []
        while filepath != '':
            (dirs, _) = os.path.split(filepath)
            res.append(filepath)
            # For absolute path on Unix, we end with '/'
            if filepath == dirs:
                break
            filepath = dirs
        return reversed(res)

    def _supported_rule_types(self):
        return ['any', 'all']

    def _parse_ownership(self, fd, name):
        """Generator that yields rule tuples for every rule in the OWNERS file.

        The returned tuple is in the following format: <pattern, owners, type, overwrite>
        * pattern: A pattern to match filenames with, e.g. "*.py".
        * owners: List of owners.
        * type: Type of rule, see `_supported_rule_types` method for possible values.
        * overwrite: Whether rules inherited from the parent OWNERS file should be overwritten.
        Can return multiple tuples for every rule, depending on the number of patterns specified for the rule.

        :param file-object fd: File object open for parsing of rules.
        :param string name: Full path to the OWNERS file being parsed.
        :return: A 4 element tuple: <pattern, owners, type, overwrite>
        :rtype: tuple
        """

        try:
            tree = _load_toml_from_fd(fd)
            mx.logv(f"Tree is {tree}")
            properties = tree.get('properties')
            overwrite_parent = properties is not None and properties.get('overwrite_parent')
            for rule in tree.get('rule', []):
                if not 'files' in rule:
                    mx.log_error(f"Ignoring rule {rule} in {name} as it contains no files")
                    continue
                if (not 'any' in rule) and (not 'all' in rule):
                    mx.log_error(f"Ignoring rule {rule} in {name} as it contains no owner specification")
                    continue

                rule['files'] = _whitespace_split(rule['files'])
                for rule_type in self._supported_rule_types():
                    owners_for_rule_type = _whitespace_split(rule.get(rule_type, []))
                    if owners_for_rule_type:
                        for pat in rule['files']:
                            yield pat, owners_for_rule_type, rule_type, overwrite_parent
                            overwrite_parent = False # Only the first rule in the file should trigger the overwrite

        except _TomlParsingException as e:
            mx.abort(f"Invalid input from {name}: {e}")

    def _parse_ownership_from_files(self, files):
        """Generator that yields rule tuples for all rules found in the list of OWNERS files.

        Processes the file list in-order, generating rule-tuples for every file.

        :param list files: List of OWNERS files to be parsed.
            Should be ordered from the most general one to the most specific one, since when
            parsing an OWNERS file we facilitate inheritance/overwriting of parent's rules.
        :return: A 4 element tuple: <pattern, owners, type, overwrite>. See `_parse_ownership` doc for more details.
        :rtype: tuple
        """

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

    def _no_owners(self):
        return {rule_type: set() for rule_type in self._supported_rule_types()}

    def get_owners_of(self, filepath):
        # Subsequences of the filepath, from the least precise (/) to the most precise (/full/path/to/file.py)
        components = ([] if os.path.isabs(filepath) else ['.']) + list(self._get_path_components(filepath))
        filename = os.path.split(filepath)[1]
        # Paths to possible OWNERS files that could apply to the file, from the most general one (/OWNERS.toml)
        # to the closest one (/full/path/to/OWNERS.toml). This order facilitates correct rule overwriting.
        owners_files = [
            os.path.join(i, 'OWNERS.toml') if os.path.isabs(i) else os.path.join(self.src, i, 'OWNERS.toml')
            for i in components[:-1]
        ]
        owners_files = [i for i in owners_files if os.path.commonprefix([i, self.src]) == self.src]
        result = self._no_owners()
        ownership = self._parse_ownership_from_files(owners_files)
        for pat, owners, modifiers, overwrite_parent in ownership:
            if overwrite_parent:
                # Overwrite parents' rules - relies on parsing rules of parents before those of children OWNERS files.
                result = self._no_owners()
            if fnmatch.fnmatch(filename, pat):
                for rule_type in self._supported_rule_types():
                    if rule_type in modifiers:
                        result[rule_type].update(owners)
        result = {rule_type: sorted(result[rule_type]) for rule_type in self._supported_rule_types() if len(result[rule_type]) > 0}
        mx.logv(f"File {filepath} owned by {result} (looked into {owners_files})")
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
    repo_root = _git_get_repo_root_or_cwd(False)
    # Split the captured output (list of modified files) by the delimiter token ('\0'),
    # filtering out any empty strings (the last delimiter is followed by nothing, or in case of no output)
    # and then concatenating the path to the root of the repo to the relative paths of modified files. Example:
    # 'README.md\0src/Foo.java\0' => ['README.md', 'src/Foo.java', ''] => ['README.md', 'src/Foo.java'] => ['/path/to/repo/README.md', '/path/to/repo/src/Foo.java']
    return list(map(lambda x: os.path.join(repo_root, x), filter(lambda x: x != '', out.split('\0'))))

def _git_get_repo_root_or_cwd(allow_cwd=True):
    rc, out, _ = _run_capture(['git', 'rev-parse', '--show-toplevel'], False)
    assert allow_cwd or rc == 0
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

* Switch -a (and -b BRANCH too) internally calls git diff master to
  query list of modified files. This also prints files modified on master
  in the meantime: consider using explicit hash of the branch-point commit
  if your branch is not newly created or is not after a fresh rebase.

Any of these modes can be accompanied by -s that enables reviewers suggestions.
When reviewer suggestions are turned on, the tool also prints a concrete list
of people that should review the modifications.

It is possible to specify existing reviewers with -r (and author of the changes
with -p): in that case the tool checks that the existing list of reviewers is
complete and if not, suggests further reviewers to cover the modified files
(-s is implied when -r or -p are used).
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
    parser.add_argument('-r', dest='existing_reviewers', metavar='PR-REVIEWER', default=[], action='append', help='Existing reviewer (can be specified multiple times).')
    parser.add_argument('-p', dest='author', metavar='PR-AUTHOR', default=None, help='Author of the pull-request')
    parser.add_argument('-s', dest='suggest_reviewers', default=False, action='store_true', help='Suggest reviewers for pull-request')
    parser.add_argument('-j', dest='json_dump', default=None, metavar='FILENAME.json', help='Store details in JSON file.')
    args = parser.parse_args(args)

    repro_data = {
        'version': 1,
        'mx_version': str(mx.version),
        'files': [],
        'owners': {},
        'branch': None,
        'pull_request': {
            'reviewers': args.existing_reviewers,
            'author': args.author,
            'suggestion': {
                'add': [],
                'details': {
                    'all': [],
                    'any': [],
                },
            }
        }
    }

    if args.upstream_branch:
        args.all_changes = True
    else:
        args.upstream_branch = 'master'

    if args.all_changes and args.files:
        mx.abort("Do not specify list of files with -b or -a")

    if args.author or args.existing_reviewers:
        args.suggest_reviewers = True

    owners = FileOwners(_git_get_repo_root_or_cwd())

    if args.all_changes:
        # Current modifications and all changes up to the upstream branch
        args.files = _git_diff_name_only([args.upstream_branch]) + _git_diff_name_only()
    elif not args.files:
        # No arguments, query list of currently modified files
        args.files = _git_diff_name_only()
    repro_data['files'] = args.files

    file_owners = {f: owners.get_owners_of(os.path.abspath(f)) for f in args.files}
    repro_data['owners'] = file_owners

    reviewers = _summarize_owners(file_owners.values())

    if reviewers['all']:
        mx.log("Mandatory reviewers (all of these must review):")
        for i in reviewers['all']:
            if i in args.existing_reviewers:
                mx.log(" o " + i + " (already reviews)")
            else:
                mx.log(" o " + i)
    if reviewers['any']:
        mx.log("Any-of reviewers (at least one from each line):")
        for i in reviewers['any']:
            if _is_some_item_in_set(args.existing_reviewers, set(i)):
                mx.log(" o " + ' or '.join(i) + ' (one already reviews)')
            else:
                mx.log(" o " + ' or '.join(i))

    if len(reviewers["all"]) == 0 and len(reviewers["any"]) == 0:
        mx.log("No specific reviewer requested by OWNERS.toml files for the given changeset.")


    if args.suggest_reviewers:
        mx.log("")
        mx.log("Reviewers summary for this pull-request")

        missing_mandatory = []
        for i in reviewers['all']:
            if (not i in args.existing_reviewers) and (i != args.author):
                missing_mandatory.append(i)

        mx.log(" o Mandatory reviewers")
        repro_data['pull_request']['suggestion']['details']['all'] = missing_mandatory
        repro_data['pull_request']['suggestion']['add'].extend(missing_mandatory)
        if missing_mandatory:
            mx.log("   - Add following reviewers: " + ' and '.join(missing_mandatory))
        else:
            mx.log("   - All mandatory reviewers already assigned.")

        suggested_optional = []
        for gr in reviewers['any']:
            gr_set = set(gr)
            gr_set.discard(args.author)
            if not gr_set:
                continue

            covered_by_mandatory = _is_some_item_in_set(missing_mandatory, gr_set)
            covered_by_existing = _is_some_item_in_set(args.existing_reviewers, gr_set)
            covered_by_suggestions = _is_some_item_in_set(suggested_optional, gr_set)
            if covered_by_mandatory or covered_by_existing or covered_by_suggestions:
                continue
            suggested_optional.append(list(gr_set)[0])

        mx.log(" o Any-of reviewers")
        repro_data['pull_request']['suggestion']['details']['any'] = suggested_optional
        repro_data['pull_request']['suggestion']['add'].extend(suggested_optional)
        if suggested_optional:
            mx.log("   - Suggesting to add these reviewers: " + ' and '.join(suggested_optional))
        else:
            mx.log("   - All are already assigned or are among the mandatory ones.")
        if suggested_optional or missing_mandatory:
            mx.log(" o Suggested modifications: add the following reviewers")
            for i in sorted(suggested_optional + missing_mandatory):
                mx.log("   - " + i)
        else:
            mx.log(" o Looks like all reviewers are already assigned.")


    repro_data['pull_request']['suggestion']['add'] = list(sorted(repro_data['pull_request']['suggestion']['add']))

    num_files_changed = len(file_owners.keys())
    num_owned_files = len([f for f, o in file_owners.items() if o])

    if num_files_changed == 0:
        mx.warn("The changeset is empty!")
    else:
        mx.log(f"\n{num_owned_files}/{num_files_changed} of the files have ownership defined by one or more OWNERS.toml file(s)")
        if num_owned_files < num_files_changed:
            mx.log("Consider adding ownership for the files with no ownership! (mx verbose mode shows details)")

        import pprint
        mx.logv("Ownership of each file:")
        mx.logv(pprint.pformat(file_owners, indent=2))

    if args.json_dump:
        with open(args.json_dump, 'wt') as f:
            json.dump(repro_data, f, indent=4)


class OwnerStats:
    COLOR_ALERT = "\033[31m"
    COLOR_OKAY = "\033[32m"
    COLOR_RESET = "\033[0m"

    def __init__(self):
        self.owned = {}
        self.orphan_files_count = 0
        self.owned_files_count = 0

    def _add_owner(self, name, details = None):
        if details is None:
            details = {
                'files': 1
            }
        if not name in self.owned:
            self.owned[name] = {
                'files': 0,
            }
        self.owned[name]['files'] = self.owned[name]['files'] + details['files']

    def add_ownership(self, ownership):
        if not ownership:
            self.orphan_files_count = self.orphan_files_count + 1
            return
        self.owned_files_count = self.owned_files_count + 1
        for name in ownership.get('any', []):
            self._add_owner(name)
        for name in ownership.get('all', []):
            self._add_owner(name)

    def merge_with(self, other):
        self.orphan_files_count = self.orphan_files_count + other.orphan_files_count
        self.owned_files_count = self.owned_files_count + other.owned_files_count
        for name, details in other.owned.items():
            self._add_owner(name, details)

    def get_orphan_stats(self, use_colors):
        msg = 'no-one = {} files'.format(self.orphan_files_count)
        if use_colors and self.orphan_files_count > 0:
            msg = OwnerStats.COLOR_ALERT + msg + OwnerStats.COLOR_RESET
        return msg

    def get_assigned_stats(self, use_colors):
        msg = 'assigned = {} files'.format(self.owned_files_count)
        if use_colors and self.owned_files_count > 0:
            msg = OwnerStats.COLOR_OKAY + msg + OwnerStats.COLOR_RESET
        return msg

    def oneline_all(self, use_colors=False):
        owned = [
            '{} = {} files'.format(owner, details['files'])
            for owner, details in self.owned.items()
        ]
        return ', '.join(owned + [self.get_orphan_stats(use_colors)])

    def oneline_brief(self, use_colors=False):
        return self.get_assigned_stats(use_colors) + ', ' + self.get_orphan_stats(use_colors)


def _compute_owned_stats(owners, top):
    result = OwnerStats()
    if not os.path.isdir(top):
        result.add_ownership(owners.get_owners_of(top))
    else:
        for fname in os.listdir(top):
            nested = _compute_owned_stats(owners, os.path.join(top, fname))
            result.merge_with(nested)
    return result


def _get_owned_directory_boundaries(curr_dir):
    for filename in os.listdir(curr_dir):
        if filename in ['.git', ]:
            continue
        filepath = os.path.join(curr_dir, filename)
        if not os.path.isdir(filepath):
            continue
        has_owners_toml = os.path.exists(os.path.join(filepath, 'OWNERS.toml'))
        nested_info = list(_get_owned_directory_boundaries(filepath))
        nested_has_owners = len(list(filter(lambda x : x['nested_has_owners'] or x['has_owners'], nested_info))) > 0
        if not nested_has_owners:
            nested_info = None
        yield {
            'name': filename,
            'path': filepath,
            'nested_has_owners': nested_has_owners,
            'has_owners': has_owners_toml,
            'sub': nested_info
        }

def _compute_owner_stats_for_subtree(owners, subtree):
    # Modifies the structure in place!
    if subtree is None:
        return
    for entry in subtree:
        entry['stats'] = _compute_owned_stats(owners, entry['path'])
        _compute_owner_stats_for_subtree(owners, entry['sub'])


def _print_summary(subtree, get_stats_function, indent=0):
    if subtree is None:
        return
    indent_str = "    " * indent
    for entry in subtree:
        stats = entry.get('stats', None)
        print("{}{}{}{}".format(
            indent_str,
            entry['path'],
            '/OWNERS.toml' if entry['has_owners'] else '/',
            ' ({})'.format(get_stats_function(stats)) if stats else '',
        ))
        _print_summary(entry['sub'], get_stats_function, indent + 1)



_MX_NOCODEOWNERS_HELP = """Compute summaries of non-owned files via OWNERS.toml.


The tool recursively searches the whole directory subtree and prints which
files (directories) are not owned by anybody.

"""

@mx.command('mx', 'nocodeowners')
def nocodeowners(args):
    """Show files not ownered by anybody (via OWNERS.toml files)."""
    parser = argparse.ArgumentParser(prog='mx nocodeowners', formatter_class=argparse.RawTextHelpFormatter, description=_MX_NOCODEOWNERS_HELP)
    parser.add_argument('-a', dest='print_everything', action='store_true', default=False, help='Print information about existing owners too.')
    parser.add_argument('-c', dest='use_colors', action='store_true', default=False, help='Use colors.')
    args = parser.parse_args(args)

    if args.print_everything:
        summary_function = lambda x: x.oneline_all(args.use_colors)
    else:
        summary_function = lambda x: x.oneline_brief(args.use_colors)

    root = '.' # _git_get_repo_root_or_cwd()
    owners = FileOwners(root)

    tree = list(_get_owned_directory_boundaries(root))
    _compute_owner_stats_for_subtree(owners, tree)
    _print_summary(tree, summary_function)
