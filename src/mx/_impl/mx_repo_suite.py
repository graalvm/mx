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


_RepoSuiteInfo = namedtuple('_RepoSuiteInfo', ['name', 'suite_dir', 'mx_dir', 'repo_root', 'suite_key'])
_RepoSuiteDiscovery = namedtuple('_RepoSuiteDiscovery', ['repo_root', 'repo_roots', 'suites', 'local_edges', 'root_suites', 'external_imports'])


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
        suite_key = realpath(suite_dir)
        discovered.append(_RepoSuiteInfo(_mx._suitename(dirpath), suite_dir, dirpath, suite_repo_root, suite_key))
        discovered_repo_roots.add(realpath(suite_repo_root))
        dirnames[:] = []

    if not discovered:
        return _RepoSuiteDiscovery(repo_root, [], [], [], [], {})

    discovered.sort(key=lambda s: (s.name, s.suite_key))
    suites_by_key = {s.suite_key: s for s in discovered}
    suites_by_name = {}
    for suite_info in discovered:
        suites_by_name.setdefault(suite_info.name, []).append(suite_info)
    incoming_edges = {s.suite_key: 0 for s in discovered}
    local_edges = []
    external_imports = {}
    repo_root_real = realpath(repo_root)

    for repo_suite in discovered:
        suite_obj = _mx.SourceSuite(repo_suite.mx_dir, primary=True, load=False)
        for suite_import in suite_obj.suite_imports:
            import_name = suite_import.name
            name_matches = suites_by_name.get(import_name, ())
            imported_suite = None
            if suite_import.suite_dir:
                imported_suite = suites_by_key.get(realpath(suite_import.suite_dir))
                if imported_suite is None and suite_import.in_subdir and len(name_matches) == 1:
                    imported_suite = name_matches[0]
            elif suite_import.in_subdir:
                imported_suite = suites_by_key.get(realpath(join(repo_suite.repo_root, import_name)))
                if imported_suite is None and len(name_matches) == 1:
                    imported_suite = name_matches[0]
            if imported_suite is not None and os.path.commonpath([repo_root_real, imported_suite.suite_key]) == repo_root_real:
                local_edges.append((repo_suite.suite_key, imported_suite.suite_key))
                incoming_edges[imported_suite.suite_key] += 1
            else:
                external_imports.setdefault(repo_suite.suite_key, []).append(import_name)

    for imports in external_imports.values():
        imports.sort()
    local_edges.sort()
    root_suites = [suite for suite in discovered if incoming_edges[suite.suite_key] == 0]
    return _RepoSuiteDiscovery(repo_root, sorted(discovered_repo_roots), discovered, local_edges, root_suites, external_imports)


def _suite_label(suite_info, show_locations=False):
    suite_dir = suite_info.suite_dir if show_locations else os.path.relpath(suite_info.suite_dir, os.getcwd())
    return f'{suite_info.name} ({suite_dir})'


def _format_repo_suite_discovery(discovery, show_locations=False):
    suites_by_key = {suite.suite_key: suite for suite in discovery.suites}
    name_counts = {}
    for suite_info in discovery.suites:
        name_counts[suite_info.name] = name_counts.get(suite_info.name, 0) + 1

    local_deps = {}
    for importer_key, imported_key in discovery.local_edges:
        local_deps.setdefault(importer_key, []).append(suites_by_key[imported_key])

    def _suite_reference_label(suite_info):
        if name_counts.get(suite_info.name, 0) > 1:
            return _suite_label(suite_info, show_locations=show_locations)
        return suite_info.name

    root_keys = {suite.suite_key for suite in discovery.root_suites}
    other_suites = [suite_info for suite_info in discovery.suites if suite_info.suite_key not in root_keys]
    lines = []

    def _append_section(title, suites):
        if not suites:
            return
        if lines:
            lines.append('')
        lines.append(f'{title}:')
        for suite_info in suites:
            line = f'  {_suite_label(suite_info, show_locations=show_locations)}'
            imported = local_deps.get(suite_info.suite_key)
            if imported:
                line += f": depends on: {', '.join(_suite_reference_label(dep) for dep in imported)}"
            lines.append(line)

    _append_section('Roots', discovery.root_suites)
    _append_section('Others', other_suites)

    if discovery.external_imports:
        if lines:
            lines.append('')
        lines.append('External dependencies:')
        for suite_info in discovery.suites:
            imports = discovery.external_imports.get(suite_info.suite_key)
            if imports:
                lines.append(f"  {_suite_reference_label(suite_info)}: depends on: {', '.join(imports)}")
    return '\n'.join(lines)


def _abort_for_missing_primary_suite(command, discovery=None):
    _mx = _mx_module()
    if discovery is None:
        discovery = _mx._discover_repo_suites()
    if discovery and discovery.suites:
        root_names = ', '.join(_suite_label(suite_info) for suite_info in discovery.root_suites)
        _mx.abort(
            'No primary suite found.\n'
            f'Found {len(discovery.suites)} local suites in this directory tree; root suites: {root_names}.\n'
            f'Use `mx --root-suites {command}` to run for root suites, '
            f'`mx --all-suites {command}` to run for all local suites, '
            f'`mx --diff-suites {command}` to run only local suites with uncommitted changes in Git repositories, or `mx -p <suite> {command}` for one suite.'
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
    repo_roots = discovery.repo_roots if discovery.repo_roots else [discovery.repo_root]
    git_repo_roots = []
    for repo_root in repo_roots:
        vc = _mx.VC.get_vc(repo_root, abortOnError=False)
        if vc is not None and vc.kind == 'git':
            git_repo_roots.append(repo_root)
    changed_paths = []
    if getattr(_mx._opts, 'diff_suites', False):
        diff_desc = 'uncommitted changes'
        for repo_root in git_repo_roots:
            relative_paths = _mx._parse_git_diff_name_status_z(_mx._git_diff_name_status_z(repo_root, ['HEAD']))
            changed_paths.extend(realpath(join(repo_root, path)) for path in relative_paths)
    else:
        assert getattr(_mx._opts, 'diff_branch_suites', False)
        base = 'master'
        git = _mx.GitConfig()
        if git_repo_roots:
            git.check_for_git()
        merge_bases = []
        for repo_root in git_repo_roots:
            merge_base = git.git_command(repo_root, ['merge-base', 'HEAD', base], abortOnError=True).strip()
            merge_bases.append(merge_base)
            relative_paths = _mx._parse_git_diff_name_status_z(_mx._git_diff_name_status_z(repo_root, [f'{merge_base}..HEAD']))
            changed_paths.extend(realpath(join(repo_root, path)) for path in relative_paths)
        if len(git_repo_roots) == 1:
            diff_desc = f'{merge_bases[0]}..HEAD'
        else:
            diff_desc = f'branch changes against {base} across {len(git_repo_roots)} git repositories'
    return diff_desc, changed_paths


def _select_repo_suites_by_paths(discovery, changed_paths, root_suites_only):
    repo_root = realpath(discovery.repo_root)
    suite_roots = sorted(((suite_info, realpath(suite_info.suite_dir)) for suite_info in discovery.suites), key=lambda item: len(item[1]), reverse=True)
    repo_roots = sorted({realpath(suite_info.repo_root) for suite_info in discovery.suites}, key=len, reverse=True)
    suites_by_repo_root = {}
    for suite_info in discovery.suites:
        suites_by_repo_root.setdefault(realpath(suite_info.repo_root), []).append(suite_info)
    touched_suite_keys = set()

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
            touched_suite_keys.add(matched_suite.suite_key)
            continue
        for suite_repo_root in repo_roots:
            if os.path.commonpath([suite_repo_root, changed_path]) == suite_repo_root:
                touched_suite_keys.update(suite_info.suite_key for suite_info in suites_by_repo_root.get(suite_repo_root, ()))
                break

    if not root_suites_only:
        return [suite_info for suite_info in discovery.suites if suite_info.suite_key in touched_suite_keys]

    reverse_edges = {}
    for importer, imported in discovery.local_edges:
        reverse_edges.setdefault(imported, set()).add(importer)
    affected = set(touched_suite_keys)
    worklist = deque(touched_suite_keys)
    while worklist:
        suite_key = worklist.popleft()
        for importer in reverse_edges.get(suite_key, ()):
            if importer not in affected:
                affected.add(importer)
                worklist.append(importer)
    return [suite_info for suite_info in discovery.root_suites if suite_info.suite_key in affected]


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


def _recursive_mx_base_args(primary_suite_path):
    _mx = _mx_module()
    forwarded_args = []
    for arg in sys.argv[1:]:
        if arg in ('--all-suites', '--root-suites', '--diff-suites', '--diff-branch-suites', '--skip-missing-imports'):
            continue
        forwarded_args.append(arg)
    try:
        command_index = forwarded_args.index(_mx._argParser.initialCommandAndArgs[0])
    except (AttributeError, IndexError, ValueError):
        command_index = len(forwarded_args)
    base_args = [sys.executable, '-u', join(_mx._mx_home, 'mx.py')] + forwarded_args[:command_index] + ['-p', primary_suite_path]
    return base_args, forwarded_args, command_index


def _recursive_mx_args_for_suite(primary_suite_path):
    base_args, forwarded_args, command_index = _recursive_mx_base_args(primary_suite_path)
    return base_args + forwarded_args[command_index:]


def _missing_local_imports(primary_suite_path):
    _mx = _mx_module()
    primary_mx_dir = _mx._is_suite_dir(primary_suite_path)
    assert primary_mx_dir, f'Expected suite dir at {primary_suite_path}'

    _mx._suitemodel.set_primary_dir(primary_suite_path)
    primary_suite = _mx.SourceSuite(primary_mx_dir, primary=True, load=False)
    discovered = {primary_suite.name: primary_suite}
    worklist = deque([primary_suite])
    missing = []

    for name, in_subdir in _mx.get_dynamic_imports():
        if name not in discovered and primary_suite.get_import(name) is None:
            primary_suite.suite_imports.append(_mx.SuiteImport(name, version=None, urlinfos=None, dynamicImport=True, in_subdir=in_subdir))

    while worklist:
        suite_obj = worklist.popleft()
        for suite_import in suite_obj.suite_imports:
            if suite_import.name in discovered:
                continue
            imported_suite, _ = _mx._find_suite_import(suite_obj, suite_import, fatalIfMissing=False, load=False, allow_clone=False)
            if imported_suite is None:
                missing.append((suite_obj.name, suite_import.name))
                continue
            discovered[imported_suite.name] = imported_suite
            worklist.append(imported_suite)

    labels = []
    for importer, imported in missing:
        label = imported if importer == primary_suite.name else f'{importer} -> {imported}'
        if label not in labels:
            labels.append(label)
    return labels


def _repo_suite_failure_message(command, failure_count, unavailable_count, root_suites_only):
    parts = []
    if failure_count:
        plural = '' if failure_count == 1 else 's'
        suite_kind = 'root suite' if root_suites_only else 'suite'
        parts.append(f'{failure_count} {suite_kind} command{plural} failed')
    if unavailable_count:
        suite_plural = '' if unavailable_count == 1 else 's'
        verb = 'does' if unavailable_count == 1 else 'do'
        parts.append(f"{unavailable_count} suite{suite_plural} {verb} not define `{command}`")
    return '; '.join(parts) + '.'


def _check_command_available_for_suite(command, primary_suite_path):
    _mx = _mx_module()
    out = _mx.OutputCapture()
    err = _mx.OutputCapture()
    base_args, _, _ = _recursive_mx_base_args(primary_suite_path)
    retcode = _mx.run(base_args + ['--check-command-availability', command], nonZeroIsFatal=False, cwd=primary_suite_path, out=out, err=err)
    return retcode == 0


def _run_command_for_repo_suites(command, discovery):
    _mx = _mx_module()
    if getattr(_mx._opts, 'primary_suite_path', None):
        _mx.abort('`-p/--primary-suite-path` cannot be used together with `--all-suites`, `--root-suites`, `--diff-suites`, or `--diff-branch-suites`.')
    if getattr(_mx._opts, 'primary', False) or getattr(_mx._opts, 'specific_suites', []):
        _mx.abort('`--primary` and `--suite` cannot be used together with `--all-suites`, `--root-suites`, `--diff-suites`, or `--diff-branch-suites`.')
    if not discovery or not discovery.suites:
        _mx.abort('No suites found in this directory tree.')

    selected_suites, diff_desc, root_suites_only = _mx._select_repo_suites(discovery)
    selection_mode = _mx._repo_suite_selection_mode()
    name_counts = {}
    for suite_info in discovery.suites:
        name_counts[suite_info.name] = name_counts.get(suite_info.name, 0) + 1

    def _suite_run_label(suite_info):
        if name_counts.get(suite_info.name, 0) > 1:
            return _suite_label(suite_info)
        return suite_info.name

    suite_kind = 'root suites' if root_suites_only else 'suites'
    selected_names = ', '.join(_suite_run_label(suite_info) for suite_info in selected_suites) if selected_suites else '<none>'
    if diff_desc is not None:
        _mx.log(f'Diff filter ({diff_desc}) selected {suite_kind}: {selected_names}')
    elif selection_mode == 'root':
        _mx.log(f'Selected root suites: {selected_names}')
    else:
        _mx.log(f'Selected suites: {selected_names}')

    skipped = []
    executable_suites = selected_suites
    if getattr(_mx._opts, 'skip_missing_imports', False):
        executable_suites = []
        for suite_info in selected_suites:
            missing_imports = _mx._missing_local_imports(suite_info.suite_dir)
            if missing_imports:
                skipped.append((suite_info, missing_imports))
                _mx.log(f"Skipping suite `{_suite_run_label(suite_info)}` due to missing local imports: {', '.join(missing_imports)}")
            else:
                executable_suites.append(suite_info)

    failures = []
    unavailable = set()
    for suite_info in executable_suites:
        suite_kind = 'root suite' if root_suites_only else 'suite'
        if not _mx._check_command_available_for_suite(command, suite_info.suite_dir):
            unavailable.add(suite_info.suite_key)
            continue
        _mx.log(f"Running `{command}` for {suite_kind} `{_suite_run_label(suite_info)}`")
        try:
            retcode = _mx.run(_mx._recursive_mx_args_for_suite(suite_info.suite_dir), nonZeroIsFatal=False, cwd=suite_info.suite_dir, interruptIsFatal=True)
        except KeyboardInterrupt:
            _mx.abort(1)
        if retcode != 0:
            failures.append((suite_info.suite_key, retcode))

    if skipped:
        plural = '' if len(skipped) == 1 else 's'
        _mx.log(f'Skipped {len(skipped)} suite{plural} with missing local imports')

    if failures or unavailable:
        _mx.log('')
        _mx.log('Summary:')
        failed = dict(failures)
        grouped = {}
        for suite_info in executable_suites:
            if suite_info.suite_key in failed:
                status = f'FAILED ({failed[suite_info.suite_key]})'
            elif suite_info.suite_key in unavailable:
                status = 'COMMAND UNDEFINED'
            else:
                status = 'OK'
            grouped.setdefault(status, []).append(_suite_run_label(suite_info))
        for status, suite_labels in grouped.items():
            _mx.log(f"  {status}: {', '.join(suite_labels)}")
        _mx.abort(_mx._repo_suite_failure_message(command, len(failures), len(unavailable), root_suites_only))
    if executable_suites:
        plural = '' if len(executable_suites) == 1 else 's'
        _mx.log(f'{len(executable_suites)} command{plural} executed successfully')
    else:
        _mx.log('No commands executed; all selected suites were skipped due to missing local imports')
    return 0


def _handle_missing_primary_suite_command(command):
    _mx = _mx_module()
    discovery = _mx._discover_repo_suites()
    if _mx._repo_suite_selection_requested():
        return _mx._run_command_for_repo_suites(command, discovery)
    _mx._abort_for_missing_primary_suite(command, discovery)
