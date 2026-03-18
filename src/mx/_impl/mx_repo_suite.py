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

from collections import deque, namedtuple
import os
import sys
from os.path import basename, dirname, exists, join, realpath


def _mx_module():
    from . import mx as _mx
    return _mx


class _RepoSuiteInfo(namedtuple('_RepoSuiteInfo', ['name', 'suite_dir', 'mx_dir', 'suite_py', 'repo_root'])):
    __slots__ = ()


class _RepoSuiteDiscovery(namedtuple('_RepoSuiteDiscovery', ['repo_root', 'repo_roots', 'suites', 'local_edges', 'root_suites', 'external_imports'])):
    __slots__ = ()


_MULTI_SUITE_COMMANDS = frozenset(['build', 'checkstyle', 'clean', 'suites'])


def _discover_repo_suites(start_dir=None):
    _mx = _mx_module()
    if start_dir is None:
        start_dir = os.getcwd()
    start_dir = os.path.abspath(start_dir)
    _, enclosing_repo_root = _mx.SuiteModel.get_vc(start_dir)
    repo_root = enclosing_repo_root if enclosing_repo_root and exists(enclosing_repo_root) else start_dir

    discovered = []
    discovered_repo_roots = set()
    skip_dirs = {'.git', '.hg', '.svn', '__pycache__', 'mxbuild'}
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        mx_dir_name = basename(dirpath)
        if 'suite.py' not in filenames or not (mx_dir_name.startswith('mx.') or mx_dir_name.startswith('.mx.')):
            continue
        suite_dir = dirname(dirpath)
        _, suite_repo_root = _mx.SuiteModel.get_vc(os.path.abspath(suite_dir))
        suite_repo_root = suite_repo_root if suite_repo_root and exists(suite_repo_root) else repo_root
        discovered.append(_RepoSuiteInfo(_mx._suitename(dirpath), suite_dir, dirpath, join(dirpath, 'suite.py'), suite_repo_root))
        discovered_repo_roots.add(realpath(suite_repo_root))
        dirnames[:] = []

    if not discovered:
        return _RepoSuiteDiscovery(repo_root, [], [], [], [], {})

    discovered.sort(key=lambda s: s.name)
    suites_by_name = {s.name: s for s in discovered}
    incoming_edges = {s.name: 0 for s in discovered}
    local_edges = []
    external_imports = {}
    repo_root_real = realpath(repo_root)

    for repo_suite in discovered:
        suite_obj = _mx.SourceSuite(repo_suite.mx_dir, primary=True, load=False)
        for suite_import in suite_obj.suite_imports:
            import_name = suite_import.name
            import_path = realpath(suite_import.suite_dir) if suite_import.suite_dir else None
            is_local_import = (
                import_name in suites_by_name and
                (suite_import.in_subdir or (import_path is not None and os.path.commonpath([repo_root_real, import_path]) == repo_root_real))
            )
            if is_local_import:
                local_edges.append((repo_suite.name, import_name))
                incoming_edges[import_name] += 1
            else:
                external_imports.setdefault(repo_suite.name, []).append(import_name)

    for imports in external_imports.values():
        imports.sort()
    local_edges.sort()
    root_suites = [suite for suite in discovered if incoming_edges[suite.name] == 0]
    return _RepoSuiteDiscovery(repo_root, sorted(discovered_repo_roots), discovered, local_edges, root_suites, external_imports)


def _format_repo_suite_discovery(discovery, show_locations=False):
    local_deps = {}
    for importer, imported in discovery.local_edges:
        local_deps.setdefault(importer, []).append(imported)

    def _suite_label(suite_info):
        relative_suite_dir = os.path.relpath(suite_info.suite_dir, os.getcwd())
        return f'{suite_info.name} ({relative_suite_dir})'

    root_names = {suite.name for suite in discovery.root_suites}
    lines = []
    for suite_info in discovery.suites:
        prefix = '> ' if suite_info.name in root_names else '  '
        imported = local_deps.get(suite_info.name)
        if imported:
            lines.append(f"{prefix}{_suite_label(suite_info)} > {', '.join(imported)}")
        else:
            lines.append(f'{prefix}{_suite_label(suite_info)}')
    if discovery.external_imports:
        lines.append('')
        lines.append('External dependencies:')
        for suite_name in sorted(discovery.external_imports):
            lines.append(f"  {suite_name} > {', '.join(discovery.external_imports[suite_name])}")
    return '\n'.join(lines)


def _abort_for_missing_primary_suite(command, discovery=None):
    _mx = _mx_module()
    if discovery is None:
        discovery = _mx._discover_repo_suites()
    if discovery and discovery.suites:
        root_names = ', '.join(suite_info.name for suite_info in discovery.root_suites)
        _mx.abort(
            'No primary suite found.\n'
            f'Found {len(discovery.suites)} local suites in this directory tree; root suites: {root_names}.\n'
            f'Use `mx --root-suites {command}` to run for root suites, '
            f'`mx --all-suites {command}` to run for all local suites, '
            f'`mx --diff-suites {command}` to run only local suites with uncommitted changes, or `mx -p <suite> {command}` for one suite.'
        )
    _mx.abort(f'no primary suite found for {command}')


def _git_diff_name_status_z(vc_dir, extra_args):
    _mx = _mx_module()
    git = _mx.GitConfig()
    output = git.git_command(vc_dir, ['diff', '--name-status', '-z'] + extra_args, abortOnError=True)
    assert output is not None
    return output


def _parse_git_diff_name_status_z(output):
    entries = []
    parts = output.split('\0')
    i = 0
    while i < len(parts):
        if not parts[i]:
            i += 1
            continue
        status = parts[i]
        i += 1
        if status.startswith('R'):
            old_path = parts[i]
            i += 1
            new_path = parts[i]
            i += 1
            entries.append(old_path)
            entries.append(new_path)
        else:
            path = parts[i]
            i += 1
            entries.append(path)
    return [path for path in entries if path]


def _get_repo_diff_paths(discovery):
    _mx = _mx_module()
    git = _mx.GitConfig()
    git.check_for_git()
    repo_roots = discovery.repo_roots if discovery.repo_roots else [discovery.repo_root]
    changed_paths = []
    if getattr(_mx._opts, 'diff_suites', False):
        diff_desc = 'uncommitted changes'
        for repo_root in repo_roots:
            relative_paths = _mx._parse_git_diff_name_status_z(_mx._git_diff_name_status_z(repo_root, ['HEAD']))
            changed_paths.extend(realpath(join(repo_root, path)) for path in relative_paths)
    else:
        assert getattr(_mx._opts, 'diff_branch_suites', False)
        base = 'master'
        merge_bases = []
        for repo_root in repo_roots:
            merge_base = git.git_command(repo_root, ['merge-base', 'HEAD', base], abortOnError=True).strip()
            merge_bases.append(merge_base)
            relative_paths = _mx._parse_git_diff_name_status_z(_mx._git_diff_name_status_z(repo_root, [f'{merge_base}..HEAD']))
            changed_paths.extend(realpath(join(repo_root, path)) for path in relative_paths)
        if len(repo_roots) == 1:
            diff_desc = f'{merge_bases[0]}..HEAD'
        else:
            diff_desc = f'branch changes against {base} across {len(repo_roots)} repositories'
    return diff_desc, changed_paths


def _select_repo_suites_by_paths(discovery, changed_paths, root_suites_only):
    repo_root = realpath(discovery.repo_root)
    suite_roots = sorted(((suite_info, realpath(suite_info.suite_dir)) for suite_info in discovery.suites), key=lambda item: len(item[1]), reverse=True)
    repo_roots = sorted({realpath(suite_info.repo_root) for suite_info in discovery.suites}, key=len, reverse=True)
    suites_by_repo_root = {}
    for suite_info in discovery.suites:
        suites_by_repo_root.setdefault(realpath(suite_info.repo_root), []).append(suite_info)
    touched_names = set()

    for changed_path in changed_paths:
        changed_path = realpath(changed_path)
        if os.path.commonpath([repo_root, changed_path]) != repo_root:
            continue
        matched_suite = None
        for suite_info, suite_root in suite_roots:
            if os.path.commonpath([suite_root, changed_path]) == suite_root:
                matched_suite = suite_info
                break
        if matched_suite is not None:
            touched_names.add(matched_suite.name)
            continue
        for suite_repo_root in repo_roots:
            if os.path.commonpath([suite_repo_root, changed_path]) == suite_repo_root:
                touched_names.update(suite_info.name for suite_info in suites_by_repo_root.get(suite_repo_root, ()))
                break

    if not root_suites_only:
        return [suite_info for suite_info in discovery.suites if suite_info.name in touched_names]

    reverse_edges = {}
    for importer, imported in discovery.local_edges:
        reverse_edges.setdefault(imported, set()).add(importer)
    affected = set(touched_names)
    worklist = deque(touched_names)
    while worklist:
        suite_name = worklist.popleft()
        for importer in reverse_edges.get(suite_name, ()):
            if importer not in affected:
                affected.add(importer)
                worklist.append(importer)
    return [suite_info for suite_info in discovery.root_suites if suite_info.name in affected]


def _repo_suite_selection_mode():
    _mx = _mx_module()
    if getattr(_mx._opts, 'all_suites', False):
        return 'all'
    if getattr(_mx._opts, 'root_suites', False):
        return 'root'
    if getattr(_mx._opts, 'diff_suites', False):
        return 'diff'
    if getattr(_mx._opts, 'diff_branch_suites', False):
        return 'diff-branch'
    return None


def _repo_suite_selection_requested():
    _mx = _mx_module()
    return _mx._repo_suite_selection_mode() is not None


def _select_repo_suites(discovery, default_all=False):
    _mx = _mx_module()
    selection_mode = _mx._repo_suite_selection_mode()
    if selection_mode is None:
        if default_all:
            return discovery.suites, None, False
        return None, None, False

    if selection_mode == 'all':
        return discovery.suites, None, False
    if selection_mode == 'root':
        return discovery.root_suites, None, True

    root_suites_only = False
    if selection_mode in ('diff', 'diff-branch'):
        diff_desc, changed_paths = _mx._get_repo_diff_paths(discovery)
        return _mx._select_repo_suites_by_paths(discovery, changed_paths, root_suites_only), diff_desc, root_suites_only

    _mx.abort(f'Unexpected repo suite selection mode: {selection_mode}')


def _recursive_mx_args_for_suite(primary_suite_path):
    _mx = _mx_module()
    forwarded_args = []
    for arg in sys.argv[1:]:
        if arg in ('--all-suites', '--root-suites', '--diff-suites', '--diff-branch-suites'):
            continue
        forwarded_args.append(arg)
    try:
        command_index = forwarded_args.index(_mx._argParser.initialCommandAndArgs[0])
    except (AttributeError, IndexError, ValueError):
        command_index = len(forwarded_args)
    return [sys.executable, '-u', join(_mx._mx_home, 'mx.py')] + forwarded_args[:command_index] + ['-p', primary_suite_path] + forwarded_args[command_index:]


def _run_command_for_repo_suites(command, discovery):
    _mx = _mx_module()
    if getattr(_mx._opts, 'primary_suite_path', None):
        _mx.abort('`-p/--primary-suite-path` cannot be used together with `--all-suites`, `--root-suites`, `--diff-suites`, or `--diff-branch-suites`.')
    if getattr(_mx._opts, 'primary', False) or getattr(_mx._opts, 'specific_suites', []):
        _mx.abort('`--primary` and `--suite` cannot be used together with `--all-suites`, `--root-suites`, `--diff-suites`, or `--diff-branch-suites`.')
    if _mx.primary_suite() is not None:
        _mx.abort('`--all-suites`, `--root-suites`, `--diff-suites`, and `--diff-branch-suites` cannot be used when a primary suite is already active. Run from the repository root instead.')
    if not discovery or not discovery.suites:
        _mx.abort('No suites found in this directory tree.')

    selected_suites, diff_desc, root_suites_only = _mx._select_repo_suites(discovery)
    if diff_desc is not None:
        suite_kind = 'root suites' if root_suites_only else 'suites'
        selected_names = ', '.join(suite_info.name for suite_info in selected_suites) if selected_suites else '<none>'
        _mx.log(f'Diff filter ({diff_desc}) selected {suite_kind}: {selected_names}')
    failures = []
    for suite_info in selected_suites:
        suite_kind = 'root suite' if root_suites_only else 'suite'
        _mx.log(f"Running `{command}` for {suite_kind} `{suite_info.name}`")
        retcode = _mx.run(_mx._recursive_mx_args_for_suite(suite_info.suite_dir), nonZeroIsFatal=False, cwd=suite_info.suite_dir)
        if retcode != 0:
            failures.append((suite_info.name, retcode))

    _mx.log('')
    _mx.log('Summary:')
    failed = dict(failures)
    for suite_info in selected_suites:
        status = f'FAILED ({failed[suite_info.name]})' if suite_info.name in failed else 'OK'
        _mx.log(f'  {suite_info.name}: {status}')
    if failures:
        plural = '' if len(failures) == 1 else 's'
        suite_kind = 'root suite' if root_suites_only else 'suite'
        _mx.abort(f'{len(failures)} {suite_kind} command{plural} failed.')
    return 0


def _handle_missing_primary_suite_command(command):
    _mx = _mx_module()
    discovery = _mx._discover_repo_suites()
    if _mx._repo_suite_selection_requested():
        return _mx._run_command_for_repo_suites(command, discovery)
    _mx._abort_for_missing_primary_suite(command, discovery)
