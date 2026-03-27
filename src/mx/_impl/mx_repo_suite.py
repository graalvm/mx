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
from pathlib import Path
from urllib.parse import urlparse


def _mx_module():
    from . import mx as _mx
    return _mx


_RepoSuiteInfo = namedtuple('_RepoSuiteInfo', ['name', 'suite_dir', 'mx_dir', 'repo_root', 'suite_key'])
_RepoSuiteDiscovery = namedtuple('_RepoSuiteDiscovery', ['repo_root', 'repo_roots', 'suites', 'local_edges', 'root_suites', 'external_imports', 'ambiguous_imports'])


def _absolute_path(path):
    return Path(path).absolute()


def _resolve_path(path):
    return Path(path).resolve()


def _contains_path(parent, child):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _diff_branch_fix_message(repo_root, branch, detail):
    return (
        f'`--diff-branch-suites` {detail} in git repository `{repo_root}`.\n'
        f'Create or update the local `{branch}` branch first, for example:\n'
        f'  git fetch origin {branch}\n'
        f'  git branch -f {branch} FETCH_HEAD'
    )


def _safe_unique_name_match(name_matches):
    return name_matches[0] if len(name_matches) == 1 else None


def _importer_relative_candidates(repo_suite, suite_import, suites_by_key):
    candidates = []

    def add_candidate(path):
        suite_info = suites_by_key.get(str(_resolve_path(path)))
        if suite_info is not None and suite_info not in candidates:
            candidates.append(suite_info)

    if suite_import.suite_dir:
        add_candidate(suite_import.suite_dir)

    if suite_import.in_subdir:
        add_candidate(Path(repo_suite.repo_root) / suite_import.name)
        return candidates

    sibling_root = Path(repo_suite.repo_root).parent
    for urlinfo in suite_import.urlinfos or ():
        if urlinfo.abs_kind() != 'source':
            continue
        repo_name = Path(urlparse(urlinfo.url).path).stem
        if repo_name:
            add_candidate(sibling_root / repo_name)
            break
    add_candidate(sibling_root / suite_import.name)
    return candidates


def _ambiguous_import_label(import_name, candidate_suites):
    candidates = ', '.join(_suite_label(candidate, show_locations=False) for candidate in candidate_suites)
    return f'{import_name} (ambiguous: {candidates})'


def _discover_repo_suites(start_dir=None):
    _mx = _mx_module()
    if start_dir is None:
        start_dir = Path.cwd()
    start_dir = _absolute_path(start_dir)
    _, enclosing_repo_root = _mx.SuiteModel.get_vc(str(start_dir))
    repo_root = _absolute_path(enclosing_repo_root) if enclosing_repo_root and Path(enclosing_repo_root).exists() else start_dir

    discovered = []
    discovered_repo_roots = set()
    skip_dirs = {
        '.git',
        '.hg',
        '.svn',
        '.idea',
        '.metadata',
        '.mypy_cache',
        '.pytest_cache',
        '.tox',
        '.venv',
        '__pycache__',
        '__pypackages__',
        'mx.imports',
        'mxbuild',
    }
    for dirpath, dirnames, filenames in os.walk(str(repo_root)):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        dirpath = Path(dirpath)
        mx_dir_name = dirpath.name
        if 'suite.py' not in filenames or not (mx_dir_name.startswith('mx.') or mx_dir_name.startswith('.mx.')):
            continue
        suite_dir = dirpath.parent
        _, suite_repo_root = _mx.SuiteModel.get_vc(str(_absolute_path(suite_dir)))
        suite_repo_root = _absolute_path(suite_repo_root) if suite_repo_root and Path(suite_repo_root).exists() else repo_root
        suite_key = str(_resolve_path(suite_dir))
        discovered.append(_RepoSuiteInfo(_mx._suitename(str(dirpath)), str(suite_dir), str(dirpath), str(suite_repo_root), suite_key))
        discovered_repo_roots.add(str(_resolve_path(suite_repo_root)))
        dirnames[:] = []

    if not discovered:
        return _RepoSuiteDiscovery(str(repo_root), [], [], [], [], {}, {})

    discovered.sort(key=lambda s: (s.name, s.suite_key))
    suites_by_key = {s.suite_key: s for s in discovered}
    suites_by_name = {}
    for suite_info in discovered:
        suites_by_name.setdefault(suite_info.name, []).append(suite_info)
    incoming_edges = {s.suite_key: 0 for s in discovered}
    local_edges = []
    external_imports = {}
    ambiguous_imports = {}
    repo_root_real = _resolve_path(repo_root)

    for repo_suite in discovered:
        suite_obj = _mx.SourceSuite(repo_suite.mx_dir, primary=True, load=False)
        for suite_import in suite_obj.suite_imports:
            import_name = suite_import.name
            name_matches = list(suites_by_name.get(import_name, ()))
            importer_relative = _importer_relative_candidates(repo_suite, suite_import, suites_by_key)
            imported_suite = _safe_unique_name_match(importer_relative)
            if imported_suite is None and len(importer_relative) > 1:
                ambiguous_imports.setdefault(repo_suite.suite_key, []).append(_ambiguous_import_label(import_name, importer_relative))
                continue
            if imported_suite is None:
                if len(name_matches) > 1:
                    ambiguous_imports.setdefault(repo_suite.suite_key, []).append(_ambiguous_import_label(import_name, name_matches))
                    continue
                imported_suite = _safe_unique_name_match(name_matches)
            if imported_suite is not None and _contains_path(repo_root_real, _resolve_path(imported_suite.suite_key)):
                local_edges.append((repo_suite.suite_key, imported_suite.suite_key))
                incoming_edges[imported_suite.suite_key] += 1
            else:
                external_imports.setdefault(repo_suite.suite_key, []).append(import_name)

    for imports in external_imports.values():
        imports.sort()
    for imports in ambiguous_imports.values():
        imports.sort()
    local_edges.sort()
    root_suites = [suite for suite in discovered if incoming_edges[suite.suite_key] == 0]
    return _RepoSuiteDiscovery(str(repo_root), sorted(discovered_repo_roots), discovered, local_edges, root_suites, external_imports, ambiguous_imports)


def _suite_label(suite_info, show_locations=False):
    suite_dir_path = Path(suite_info.suite_dir)
    if show_locations:
        suite_dir = str(suite_dir_path)
    else:
        try:
            suite_dir = suite_dir_path.relative_to(Path.cwd()).as_posix()
        except ValueError:
            suite_dir = Path(os.path.relpath(str(suite_dir_path), os.getcwd())).as_posix()
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
    if discovery.ambiguous_imports:
        if lines:
            lines.append('')
        lines.append('Ambiguous dependencies:')
        for suite_info in discovery.suites:
            imports = discovery.ambiguous_imports.get(suite_info.suite_key)
            if imports:
                lines.append(f"  {_suite_label(suite_info, show_locations=show_locations)}: depends on: {', '.join(imports)}")
    return '\n'.join(lines)


def _dot_quote(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


_ROOT_NODE_COLOR = '#e76f00'
_LOCAL_NODE_COLOR = '#437291'
_LOCAL_EDGE_COLOR = '#999999'
_EXTERNAL_NODE_COLOR = _LOCAL_EDGE_COLOR
_EXTERNAL_EDGE_COLOR = '#dddddd'


def _dot_graph_header():
    return [
        'digraph suites {',
        '  graph [bgcolor=white, newrank=true, compound=true];',
        '  rankdir=TB;',
        '  node [shape=plain, fontname="DejaVu Sans", fontsize=12];',
        '  edge [penwidth=2, arrowsize=0.7];',
    ]


def _dot_node_color(external=False, root=False):
    if external:
        return _EXTERNAL_NODE_COLOR
    if root:
        return _ROOT_NODE_COLOR
    return _LOCAL_NODE_COLOR


def _dot_append_key(lines, anchor_node_ids=()):
    lines.extend([
        '  subgraph "cluster_key" {',
        '    rank=sink;',
        '    color="white";',
        '    pencolor="white";',
        '    "key_left_anchor" [shape=point, width=0.01, height=0.01, label="", style=invis, group="left"];',
        '    "key" [shape=plain, margin=0, label=<',
        '      <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="3" COLOR="#cccccc">',
        '        <TR><TD BGCOLOR="#f5f5f5"><FONT POINT-SIZE="9" COLOR="#777777"><B>Node type</B></FONT></TD><TD BGCOLOR="#f5f5f5"><FONT POINT-SIZE="9" COLOR="#777777"><B>Meaning</B></FONT></TD></TR>',
        '        <TR><TD><FONT POINT-SIZE="9" COLOR="' + _ROOT_NODE_COLOR + '">root suite</FONT></TD><TD ALIGN="LEFT"><FONT POINT-SIZE="9">local suite with no local importers</FONT></TD></TR>',
        '        <TR><TD><FONT POINT-SIZE="9" COLOR="' + _LOCAL_NODE_COLOR + '">non-root suite</FONT></TD><TD ALIGN="LEFT"><FONT POINT-SIZE="9">local suite imported by another local suite</FONT></TD></TR>',
        '        <TR><TD><FONT POINT-SIZE="9" COLOR="' + _EXTERNAL_NODE_COLOR + '">external suite</FONT></TD><TD ALIGN="LEFT"><FONT POINT-SIZE="9">imported suite not discovered locally</FONT></TD></TR>',
        '      </TABLE>',
        '    >];',
        '    { rank=same; "key_left_anchor"; "key"; }',
        '    "key_left_anchor" -> "key" [style=invis, color="white", weight=100];',
        '  }',
        '  "graph_left_anchor" -> "key_left_anchor" [style=invis, color="white", weight=100, ltail="cluster_graph", lhead="cluster_key"];',
    ])
    for anchor_node_id in anchor_node_ids:
        lines.append(f'  {_dot_quote(anchor_node_id)} -> "key" [style=invis, color="white", weight=100, ltail="cluster_graph", lhead="cluster_key"];')


def _format_repo_suite_discovery_dot(discovery, show_locations=False):
    suites_by_key = {suite.suite_key: suite for suite in discovery.suites}
    root_keys = {suite.suite_key for suite in discovery.root_suites}
    name_counts = {}
    for suite_info in discovery.suites:
        name_counts[suite_info.name] = name_counts.get(suite_info.name, 0) + 1

    def _suite_reference_label(suite_info):
        if name_counts.get(suite_info.name, 0) > 1:
            return _suite_label(suite_info, show_locations=show_locations)
        return suite_info.name

    def _suite_node_id(suite_info):
        if name_counts.get(suite_info.name, 0) > 1:
            return 'suite:' + suite_info.suite_key
        return 'suite:' + suite_info.name

    lines = _dot_graph_header()
    lines.extend([
        '  subgraph "cluster_graph" {',
        '    color="white";',
        '    pencolor="white";',
        '    "graph_left_anchor" [shape=point, width=0.01, height=0.01, label="", style=invis, group="left"];',
    ])
    emitted_nodes = set()
    emitted_edges = set()
    all_node_ids = set()
    nodes_with_outgoing_edges = set()

    def _emit_node(node_id, label, external=False, root=False):
        if node_id in emitted_nodes:
            return
        color = _dot_node_color(external=external, root=root)
        attrs = [f'label={_dot_quote(label)}', f'fontcolor={_dot_quote(color)}']
        lines.append(f'    {_dot_quote(node_id)} [{", ".join(attrs)}];')
        emitted_nodes.add(node_id)
        all_node_ids.add(node_id)

    def _emit_edge(source_id, target_id, external=False):
        edge = (source_id, target_id)
        if edge in emitted_edges:
            return
        color = _EXTERNAL_EDGE_COLOR if external else _LOCAL_EDGE_COLOR
        lines.append(f'    {_dot_quote(source_id)} -> {_dot_quote(target_id)} [color={_dot_quote(color)}];')
        emitted_edges.add(edge)
        nodes_with_outgoing_edges.add(source_id)

    for suite_info in discovery.suites:
        _emit_node(_suite_node_id(suite_info), _suite_reference_label(suite_info), root=suite_info.suite_key in root_keys)

    for importer, imported in discovery.local_edges:
        _emit_edge(_suite_node_id(suites_by_key[importer]), _suite_node_id(suites_by_key[imported]))

    for suite_info in discovery.suites:
        source_id = _suite_node_id(suite_info)
        for import_name in discovery.external_imports.get(suite_info.suite_key, ()):
            target_id = 'external:' + import_name
            _emit_node(target_id, import_name, external=True)
            _emit_edge(source_id, target_id, external=True)

    isolated_root_node_ids = sorted(
        _suite_node_id(suite_info)
        for suite_info in discovery.root_suites
        if _suite_node_id(suite_info) not in nodes_with_outgoing_edges
    )
    if isolated_root_node_ids:
        lines.append('    { rank=min; "graph_left_anchor"; ' + '; '.join(_dot_quote(node_id) for node_id in isolated_root_node_ids) + '; }')

    sink_node_ids = sorted(all_node_ids - nodes_with_outgoing_edges)
    lines.append('  }')
    _dot_append_key(lines, anchor_node_ids=sink_node_ids)
    lines.append('}')
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
    from .mx_codeowners import parse_git_diff_output

    return parse_git_diff_output(output)


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
            relative_paths = _parse_git_diff_name_status_z(_git_diff_name_status_z(repo_root, ['HEAD']))
            changed_paths.extend(str(_resolve_path(Path(repo_root) / path)) for path in relative_paths)
    else:
        base = getattr(_mx._opts, 'diff_branch_suites', None)
        assert base
        git = _mx.GitConfig()
        if git_repo_roots:
            git.check_for_git()
        merge_bases = []
        for repo_root in git_repo_roots:
            base_rev = git._commitish_revision(repo_root, base, abortOnError=False)
            if base_rev is None:
                _mx.abort(_diff_branch_fix_message(repo_root, base, f'requires a local `{base}` branch'))
            merge_base = git.git_command(repo_root, ['merge-base', 'HEAD', base_rev], abortOnError=False)
            if merge_base is None or not merge_base.strip():
                _mx.abort(_diff_branch_fix_message(repo_root, base, f'could not determine the merge-base with local `{base}`'))
            merge_base = merge_base.strip()
            merge_bases.append(merge_base)
            relative_paths = _parse_git_diff_name_status_z(_git_diff_name_status_z(repo_root, [f'{merge_base}..HEAD']))
            changed_paths.extend(str(_resolve_path(Path(repo_root) / path)) for path in relative_paths)
        if len(git_repo_roots) == 1:
            diff_desc = f'{merge_bases[0]}..HEAD'
        else:
            diff_desc = f'branch changes against {base} across {len(git_repo_roots)} git repositories'
    return diff_desc, changed_paths


def _select_repo_suites_by_paths(discovery, changed_paths, root_suites_only):
    repo_root = _resolve_path(discovery.repo_root)
    suite_roots = sorted(((suite_info, _resolve_path(suite_info.suite_dir)) for suite_info in discovery.suites), key=lambda item: len(str(item[1])), reverse=True)
    repo_roots = sorted({_resolve_path(suite_info.repo_root) for suite_info in discovery.suites}, key=lambda path: len(str(path)), reverse=True)
    suites_by_repo_root = {}
    for suite_info in discovery.suites:
        suites_by_repo_root.setdefault(_resolve_path(suite_info.repo_root), []).append(suite_info)
    touched_suite_keys = set()

    for changed_path in changed_paths:
        changed_path = _resolve_path(changed_path)
        if not _contains_path(repo_root, changed_path):
            continue
        matched_suite = None
        for suite_info, suite_root in suite_roots:
            if _contains_path(suite_root, changed_path):
                matched_suite = suite_info
                break
        if matched_suite is not None:
            touched_suite_keys.add(matched_suite.suite_key)
            continue
        for suite_repo_root in repo_roots:
            if _contains_path(suite_repo_root, changed_path):
                touched_suite_keys.update(suite_info.suite_key for suite_info in suites_by_repo_root.get(suite_repo_root, ()))
                break

    if not root_suites_only:
        return [suite_info for suite_info in discovery.suites if suite_info.suite_key in touched_suite_keys]

    return _select_affected_root_suites(discovery, touched_suite_keys)


def _select_affected_root_suites(discovery, affected_suite_keys):
    reverse_edges = {}
    for importer, imported in discovery.local_edges:
        reverse_edges.setdefault(imported, set()).add(importer)
    affected = set(affected_suite_keys)
    worklist = deque(affected_suite_keys)
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
    return _repo_suite_selection_mode() is not None


def _select_repo_suites(discovery, default_all=False):
    _mx = _mx_module()
    selection_mode = _repo_suite_selection_mode()
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
        diff_desc, changed_paths = _get_repo_diff_paths(discovery)
        return _select_repo_suites_by_paths(discovery, changed_paths, root_suites_only), diff_desc, root_suites_only

    _mx.abort(f'Unexpected repo suite selection mode: {selection_mode}')


def _optimize_repo_suite_selection(command, discovery, selected_suites, diff_desc, root_suites_only):
    if root_suites_only:
        return selected_suites, diff_desc, root_suites_only, None

    _mx = _mx_module()
    selection_mode = _repo_suite_selection_mode()
    dispatch_behavior = _mx._mx_commands.get_command_property(command, _mx.SUITE_DISPATCH_SCOPE_PROP)
    if dispatch_behavior != _mx._SUITE_DISPATCH_ROOT_SUITES:
        return selected_suites, diff_desc, root_suites_only, None

    if selection_mode == 'all':
        return (
            discovery.root_suites,
            diff_desc,
            True,
            f'Command `{command}` already traverses imported suites; running only for root suites.',
        )

    if selection_mode in ('diff', 'diff-branch'):
        selected_suites = _select_affected_root_suites(discovery, {suite_info.suite_key for suite_info in selected_suites})
        return (
            selected_suites,
            diff_desc,
            True,
            f'Command `{command}` already traverses imported suites; reducing diff-selected suites to affected root suites.',
        )

    return selected_suites, diff_desc, root_suites_only, None


def _recursive_mx_base_args(primary_suite_path):
    _mx = _mx_module()
    original_args = sys.argv[1:]
    initial_command_and_args = getattr(_mx._argParser, 'initialCommandAndArgs', [])
    command_index = len(original_args) - len(initial_command_and_args)
    if command_index < 0:
        command_index = len(original_args)
    global_args = []
    raw_global_args = original_args[:command_index]
    i = 0
    while i < len(raw_global_args):
        arg = raw_global_args[i]
        if arg in ('--all-suites', '--root-suites', '--diff-suites', '--skip-missing-imports'):
            i += 1
            continue
        if arg == '--diff-branch-suites':
            i += 1
            if i < len(raw_global_args) and not raw_global_args[i].startswith('-'):
                i += 1
            continue
        if arg.startswith('--diff-branch-suites='):
            i += 1
            continue
        global_args.append(arg)
        i += 1
    command_and_args = original_args[command_index:]
    base_args = [sys.executable, '-u', str(Path(_mx._mx_home) / 'mx.py')] + global_args + ['-p', primary_suite_path]
    return base_args, command_and_args


def _recursive_mx_args_for_suite(primary_suite_path):
    base_args, command_and_args = _recursive_mx_base_args(primary_suite_path)
    return base_args + command_and_args


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
    base_args, _ = _recursive_mx_base_args(primary_suite_path)
    retcode = _mx.run(base_args + ['--check-command-availability', command], nonZeroIsFatal=False, cwd=primary_suite_path, out=out, err=err)
    return retcode == 0


def _run_command_for_repo_suites(command, discovery):
    _mx = _mx_module()
    if _mx._primary_suite_path is not None:
        source = '`MX_PRIMARY_SUITE_PATH`'
        if getattr(_mx._opts, 'primary_suite_path', None):
            source = '`-p/--primary-suite-path` or `MX_PRIMARY_SUITE_PATH`'
        _mx.abort(f'{source} cannot be used together with `--all-suites`, `--root-suites`, `--diff-suites`, or `--diff-branch-suites`.')
    if getattr(_mx._opts, 'primary', False) or getattr(_mx._opts, 'specific_suites', []):
        _mx.abort('`--primary` and `--suite` cannot be used together with `--all-suites`, `--root-suites`, `--diff-suites`, or `--diff-branch-suites`.')
    if not discovery or not discovery.suites:
        _mx.abort('No suites found in this directory tree.')

    selected_suites, diff_desc, root_suites_only = _select_repo_suites(discovery)
    selected_suites, diff_desc, root_suites_only, optimization_note = _optimize_repo_suite_selection(
        command, discovery, selected_suites, diff_desc, root_suites_only
    )
    name_counts = {}
    for suite_info in discovery.suites:
        name_counts[suite_info.name] = name_counts.get(suite_info.name, 0) + 1

    def _suite_run_label(suite_info):
        if name_counts.get(suite_info.name, 0) > 1:
            return _suite_label(suite_info)
        return suite_info.name

    suite_kind = 'root suites' if root_suites_only else 'suites'
    selected_names = ', '.join(_suite_run_label(suite_info) for suite_info in selected_suites) if selected_suites else '<none>'
    if optimization_note is not None:
        _mx.log(optimization_note)
    if diff_desc is not None:
        _mx.log(f'Diff filter ({diff_desc}) selected {suite_kind}: {selected_names}')
    elif root_suites_only:
        _mx.log(f'Selected root suites: {selected_names}')
    else:
        _mx.log(f'Selected suites: {selected_names}')

    skipped = []
    executable_suites = selected_suites
    if getattr(_mx._opts, 'skip_missing_imports', False):
        executable_suites = []
        for suite_info in selected_suites:
            missing_imports = _missing_local_imports(suite_info.suite_dir)
            if missing_imports:
                skipped.append((suite_info, missing_imports))
                _mx.log(f"Skipping suite `{_suite_run_label(suite_info)}` due to missing local imports: {', '.join(missing_imports)}")
            else:
                executable_suites.append(suite_info)

    failures = []
    unavailable = set()
    for suite_info in executable_suites:
        suite_kind = 'root suite' if root_suites_only else 'suite'
        if not _check_command_available_for_suite(command, suite_info.suite_dir):
            unavailable.add(suite_info.suite_key)
            continue
        _mx.log(f"Running `{command}` for {suite_kind} `{_suite_run_label(suite_info)}`")
        try:
            retcode = _mx.run(_recursive_mx_args_for_suite(suite_info.suite_dir), nonZeroIsFatal=False, cwd=suite_info.suite_dir, interruptIsFatal=True)
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
        _mx.abort(_repo_suite_failure_message(command, len(failures), len(unavailable), root_suites_only))
    if executable_suites:
        plural = '' if len(executable_suites) == 1 else 's'
        _mx.log(f'{len(executable_suites)} command{plural} executed successfully')
    else:
        _mx.log('No commands executed; all selected suites were skipped due to missing local imports')
    return 0


def _handle_missing_primary_suite_command(command):
    _mx = _mx_module()
    discovery = _mx._discover_repo_suites()
    if _repo_suite_selection_requested():
        return _run_command_for_repo_suites(command, discovery)
    _abort_for_missing_primary_suite(command, discovery)
