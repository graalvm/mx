#
# ----------------------------------------------------------------------------------------------------
#
# pylint: disable=consider-using-with,duplicate-code

# Copyright (c) 2007, 2020, Oracle and/or its affiliates. All rights reserved.
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

import os, zipfile
import shutil
import sys
from argparse import ArgumentParser, ArgumentTypeError, REMAINDER
from os.path import join, basename, exists, dirname
from pprint import pformat

from . import mx, mx_util
from . import mx_ide_intellij
from . import mx_ide_netbeans
from . import mx_ide_eclipse


def _check_ide_timestamp(suite, configZip, ide, settingsFile=None):
    """
    Returns True if and only if suite.py for `suite`, all `configZip` related resources in
    `suite` and mx itself are older than `configZip`.
    """
    suitePyFiles = [join(suite.mxDir, e) for e in os.listdir(suite.mxDir) if e == 'suite.py']
    if configZip.isOlderThan(suitePyFiles):
        return False
    # Assume that any mx change might imply changes to the generated IDE files
    if configZip.isOlderThan(__file__):
        return False

    if settingsFile and configZip.isOlderThan(settingsFile):
        return False

    if ide == 'eclipse':
        for proj in suite.projects:
            if not proj.eclipse_config_up_to_date(configZip):
                return False

    if ide == 'netbeans':
        for proj in suite.projects:
            if not proj.netbeans_config_up_to_date(configZip):
                return False

    return True


_ide_envvars = {
    'MX_ALT_OUTPUT_ROOT' : None,
    'MX_BUILD_EXPLODED' : None,
    # On the mac, applications are launched with a different path than command
    # line tools, so capture the current PATH.  In general this ensures that
    # the eclipse builders see the same path as a working command line build.
    'PATH' : None,
}

def add_ide_envvar(name, value=None):
    """
    Adds a given name to the set of environment variables that will
    be captured in generated IDE configurations. If `value` is not
    None, then it will be the captured value. Otherwise the result of
    get_env(name) is not None as capturing time, it will be used.
    Otherwise no value is captured.
    """
    _ide_envvars[name] = value

def _get_ide_envvars():
    """
    Gets a dict of environment variables that must be captured in generated IDE configurations.
    """
    result = {
        'JAVA_HOME' : mx.get_env('JAVA_HOME') or mx.get_jdk().home,
        'EXTRA_JAVA_HOMES' : mx.get_env('EXTRA_JAVA_HOMES'),
    }
    for name, value in _ide_envvars.items():
        if value is None:
            value = mx.get_env(name)
        if value is not None:
            result[name] = value
    return result


def _zip_files(files, baseDir, zipPath):
    with mx_util.SafeFileCreation(zipPath) as sfc:
        zf = zipfile.ZipFile(sfc.tmpPath, 'w')
        for f in sorted(set(files)):
            relpath = os.path.relpath(f, baseDir)
            arcname = relpath.replace(os.sep, '/')
            zf.write(f, arcname)
        zf.close()


_workspace_scan_excluded_dirs = frozenset([
    '.git',
    '.hg',
    '.idea',
    '.settings',
    '.workspace',
    'mx.imports',
    'mxbuild',
    '__pycache__',
])


def _workspace_suite_mx_dir(dirpath):
    mx_dir_name = basename(dirpath)
    suite_mx_dir = mx._is_suite_dir(dirname(dirpath), mx_dir_name)
    return suite_mx_dir if suite_mx_dir == dirpath else None


def _is_workspace_repository(path):
    return any(exists(join(path, marker)) for marker in ('.git', '.hg', '.mx_vcs_root', 'ci.hocon'))


def _repository_contains_suite(repository_root):
    for dirpath, dirnames, files in os.walk(repository_root):
        dirnames[:] = [d for d in dirnames if d not in _workspace_scan_excluded_dirs]
        if 'suite.py' in files and _workspace_suite_mx_dir(dirpath):
            return True
    return False


def _parse_comma_separated_arg(value):
    values = [entry.strip() for entry in value.split(',') if entry.strip()]
    if not values:
        raise ArgumentTypeError('Expected a comma-separated list with at least one value')
    return values


def _parse_workspace_repositories(workspace_root, repositories_arg):
    if repositories_arg:
        repositories = []
        for repository in repositories_arg:
            repository_path = repository if os.path.isabs(repository) else join(workspace_root, repository)
            repository_path = os.path.realpath(repository_path)
            if not os.path.isdir(repository_path):
                mx.abort(f"Workspace repository '{repository}' does not exist: {repository_path}")
            if not _repository_contains_suite(repository_path):
                mx.abort(f"Workspace repository '{repository}' does not contain any suites: {repository_path}")
            repositories.append(repository_path)
        if not repositories:
            mx.abort("No workspace repositories selected")
        return sorted(set(repositories))

    repositories = []
    for child in sorted(os.listdir(workspace_root)):
        repository_path = join(workspace_root, child)
        if not os.path.isdir(repository_path):
            continue
        if not _is_workspace_repository(repository_path):
            continue
        if _repository_contains_suite(repository_path):
            repositories.append(os.path.realpath(repository_path))
    return repositories


def _repository_revision(repository_root):
    vc, vc_dir = mx.SuiteModel.get_vc(repository_root)
    if vc and vc_dir:
        revision = vc.parent(vc_dir, abortOnError=False)
        if revision:
            return str(revision)
    return 'workspace'


def _discover_workspace_suites(repository_roots):
    suite_infos = []
    skipped_suites = []
    revision_cache = {}

    for repository_root in repository_roots:
        revision = revision_cache.setdefault(repository_root, _repository_revision(repository_root))
        for dirpath, dirnames, files in os.walk(repository_root):
            dirnames[:] = [d for d in dirnames if d not in _workspace_scan_excluded_dirs]

            if 'suite.py' not in files:
                continue

            suite_mx_dir = _workspace_suite_mx_dir(dirpath)
            if suite_mx_dir is None:
                continue

            try:
                suite_name = mx._suitename(suite_mx_dir)
            except AssertionError:
                continue

            suite_root = dirname(suite_mx_dir)
            if suite_name == 'mx':
                # The mx suite is represented by mx._mx_suite and cannot be imported as a regular source suite.
                skipped_suites.append((suite_name, suite_root))
                continue
            if suite_root == repository_root:
                in_subdir = False
            elif basename(suite_root) == suite_name:
                in_subdir = True
            else:
                skipped_suites.append((suite_name, suite_root))
                continue

            suite_infos.append({
                'name': suite_name,
                'version': revision,
                'subdir': in_subdir,
                'suite_root': suite_root,
                'mx_dir': suite_mx_dir,
            })

    by_name = {}
    for suite_info in suite_infos:
        by_name.setdefault(suite_info['name'], []).append(suite_info)

    duplicate_suites = {name: infos for name, infos in by_name.items() if len(infos) > 1}
    if duplicate_suites:
        duplicate_details = []
        for name, infos in sorted(duplicate_suites.items()):
            locations = ', '.join(sorted(info['suite_root'] for info in infos))
            duplicate_details.append(f"{name}: {locations}")
        mx.abort('Workspace suite discovery found duplicate suite names:\n' + '\n'.join(duplicate_details))

    suite_infos.sort(key=lambda suite_info: suite_info['name'])
    return suite_infos, skipped_suites


def _write_workspace_suite(workspace_root, suite_infos):
    workspace_suite_root = workspace_root
    workspace_mx_dir = mx_util.ensure_dir_exists(join(workspace_suite_root, 'mx.workspace'))
    suite_py = join(workspace_mx_dir, 'suite.py')
    marker_file = join(workspace_mx_dir, mx.WORKSPACE_PRIMARY_SUITE_MARKER)

    imports = []
    for suite_info in suite_infos:
        suite_import = {
            'name': suite_info['name'],
            'version': suite_info['version'],
            'subdir': suite_info['subdir'],
        }
        if not suite_info['subdir']:
            suite_import['noUrl'] = True
        imports.append(suite_import)

    suite_dict = {
        'name': 'workspace',
        'mxversion': str(mx.version),
        'imports': {
            'suites': imports,
        },
        'libraries': {},
        'projects': {},
    }

    content = (
        "# Auto-generated by `mx ideinit --workspace`.\n"
        "# Re-run the command to refresh discovered repositories and suites.\n\n"
        f"suite = {pformat(suite_dict, width=160, sort_dicts=False)}\n"
    )
    mx.update_file(suite_py, content)
    mx.update_file(marker_file, '# Marker file for synthetic workspace primary suite.\n')
    return workspace_suite_root, suite_py


def _workspace_ideinit(args):
    workspace_root = os.path.realpath(os.getcwd())

    repository_roots = _parse_workspace_repositories(workspace_root, args.workspaceRepositories)
    if not repository_roots:
        mx.abort(f"No repositories containing mx suites were discovered under {workspace_root}")

    suite_infos, skipped_suites = _discover_workspace_suites(repository_roots)
    if skipped_suites:
        skipped_details = '\n'.join(sorted(f"{name}: {path}" for name, path in skipped_suites))
        mx.warn("Skipping suites that cannot be represented as simple workspace imports:\n" + skipped_details)

    known_suites = {suite_info['name'] for suite_info in suite_infos}

    if args.workspaceSuites:
        requested_suites = set(args.workspaceSuites)
        missing_suites = requested_suites - known_suites
        if missing_suites:
            mx.abort('Unknown suites requested via --workspace-suites: ' + ', '.join(sorted(missing_suites)))
        suite_infos = [suite_info for suite_info in suite_infos if suite_info['name'] in requested_suites]

    if args.workspaceExcludeSuites:
        excluded_suites = set(args.workspaceExcludeSuites)
        unknown_excluded_suites = excluded_suites - known_suites
        if unknown_excluded_suites:
            mx.warn('Ignoring unknown suites in --workspace-exclude-suites: ' + ', '.join(sorted(unknown_excluded_suites)))
        suite_infos = [suite_info for suite_info in suite_infos if suite_info['name'] not in excluded_suites]

    if not suite_infos and not args.pythonProjects:
        mx.abort("No suites discovered for workspace ide initialization")
    if not suite_infos:
        mx.warn('Workspace suite imports are empty. Only mx Python modules will be generated.')

    workspace_suite_root, suite_py = _write_workspace_suite(workspace_root, suite_infos)
    mx.log(f"Generated workspace suite descriptor at {suite_py}")

    # Run ideinit in a fresh mx process after writing mx.workspace/suite.py.
    # This process started through optional-suite-context (potentially with no primary suite),
    # while the child process reboots mx with the synthetic workspace suite as primary.
    command = [
        sys.executable,
        '-u',
        join(mx._mx_home, 'mx.py'),
    ]
    java_home = mx.get_env('JAVA_HOME')
    if java_home:
        command.append('--java-home=' + java_home)
    command.append('ideinit')
    if not args.pythonProjects:
        command.append('--no-python-projects')
    command += args.remainder

    env = os.environ.copy()
    # Workspace mode only generates parent-level IDE files. Skip the child fsckprojects
    # pass to avoid expensive cross-repository scans and interactive cleanup prompts.
    env['MX_IDEINIT_SKIP_FSCK'] = 'true'
    mx.run(command, cwd=workspace_suite_root, env=env, nonZeroIsFatal=True)


@mx.command('mx', 'ideclean', props=mx.SUITE_DISPATCH_ROOT_SUITES_PROPS)
def ideclean(args):
    """remove all IDE project configurations"""
    def rm(path):
        if exists(path):
            os.remove(path)

    for s in mx.suites() + [mx._mx_suite]:
        rm(join(s.get_mx_output_dir(), 'eclipse-config.zip'))
        rm(join(s.get_mx_output_dir(), 'netbeans-config.zip'))
        shutil.rmtree(join(s.dir, '.idea'), ignore_errors=True)

    for p in mx.projects() + mx._mx_suite.projects:
        if not p.isJavaProject():
            continue

        shutil.rmtree(join(p.dir, '.settings'), ignore_errors=True)
        shutil.rmtree(join(p.dir, '.externalToolBuilders'), ignore_errors=True)
        shutil.rmtree(join(p.dir, 'nbproject'), ignore_errors=True)
        rm(join(p.dir, '.classpath'))
        rm(join(p.dir, '.checkstyle'))
        rm(join(p.dir, '.project'))
        rm(join(p.dir, '.factorypath'))
        rm(join(p.dir, p.name + '.iml'))
        rm(join(p.dir, 'build.xml'))
        rm(join(p.dir, 'eclipse-build.xml'))
        try:
            rm(join(p.dir, p.name + '.jar'))
        except:
            mx.log_error(f"Error removing {p.name + '.jar'}")

    for d in mx._dists.values():
        if not d.isJARDistribution():
            continue
        if d.get_ide_project_dir():
            shutil.rmtree(d.get_ide_project_dir(), ignore_errors=True)

@mx.command('mx', 'ideinit', props=mx.SUITE_DISPATCH_ROOT_SUITES_PROPS)
@mx.optional_suite_context
def ideinit(args, refreshOnly=False, buildProcessorJars=True):
    """(re)generate IDE project configurations"""
    parser = ArgumentParser(prog='mx ideinit')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate projects for the mx python projects.')
    parser.add_argument('--workspace', action='store_true', help='Generate IDE configuration from a synthetic workspace suite rooted at the current directory.')
    parser.add_argument('--workspace-repositories', '--workspace-repos', dest='workspaceRepositories', type=_parse_comma_separated_arg, help='Comma-separated list of repositories to include in workspace mode (default: all direct child repositories containing suites).')
    parser.add_argument('--workspace-suites', dest='workspaceSuites', type=_parse_comma_separated_arg, help='Comma-separated list of suite names to include in workspace mode (default: all discovered compatible suites).')
    parser.add_argument('--workspace-exclude-suites', dest='workspaceExcludeSuites', type=_parse_comma_separated_arg, help='Comma-separated list of suite names to exclude in workspace mode.')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    if args.workspace:
        _workspace_ideinit(args)
        return

    if mx.primary_suite() is None:
        mx.abort('No primary suite found. Run from a suite root or use --workspace.')

    mx_ide = os.environ.get('MX_IDE', 'all').lower()
    all_ides = mx_ide == 'all'
    if all_ides or mx_ide == 'eclipse':
        mx_ide_eclipse.eclipseinit(args.remainder, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars, doFsckProjects=False, pythonProjects=args.pythonProjects)
    if all_ides or mx_ide == 'netbeans':
        mx_ide_netbeans.netbeansinit(args.remainder, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars, doFsckProjects=False)
    if all_ides or mx_ide == 'intellij':
        mx_ide_intellij.intellijinit(mx_ide_intellij.IntellijConfig(args=args.remainder, refresh_only=refreshOnly, do_fsck_projects=False, python_projects=args.pythonProjects))
    skip_fsck = os.environ.get('MX_IDEINIT_SKIP_FSCK', '').lower() in ('1', 'true', 'yes')
    if not refreshOnly and not skip_fsck:
        fsckprojects([])

@mx.command('mx', 'fsckprojects')
def fsckprojects(args):
    """find directories corresponding to deleted Java projects and delete them"""
    for suite in mx.suites(True, includeBinary=False):
        if suite.vc is None:
            mx.logv(f"Skipping fsckprojects for suite {suite.name} because it has no VCS metadata")
            continue
        projectDirs = [p.dir for p in suite.projects]
        distIdeDirs = [d.get_ide_project_dir() for d in suite.dists if d.isJARDistribution() and d.get_ide_project_dir() is not None]
        for dirpath, dirnames, files in os.walk(suite.dir):
            if dirpath == suite.dir:
                # no point in traversing vc metadata dir, lib, .workspace
                # if there are nested source suites must not scan those now, as they are not in projectDirs (but contain .project files)
                omitted = [suite.mxDir, 'lib', '.workspace', 'mx.imports']
                if suite.vc:
                    omitted.append(suite.vc.metadir())
                dirnames[:] = [d for d in dirnames if d not in omitted]
            elif dirpath == suite.get_output_root(platformDependent=False, jdkDependent=False):
                # don't want to traverse output dir
                dirnames[:] = []
            elif dirpath == suite.mxDir:
                # don't want to traverse mx.name as it contains a .project
                dirnames[:] = []
            elif dirpath in projectDirs:
                # don't traverse subdirs of an existing project in this suite
                dirnames[:] = []
            elif dirpath in distIdeDirs:
                # don't traverse subdirs of an existing distribution in this suite
                dirnames[:] = []
            else:
                maybe_project = basename(dirpath)
                if not mx._removedDeps.get(maybe_project):
                    projectConfigFiles = frozenset(['.classpath', '.project', 'nbproject', maybe_project + '.iml', 'pom.xml'])
                    indicators = projectConfigFiles.intersection(files)
                    if len(indicators) != 0 and "pom.xml" not in indicators:
                        indicators = [os.path.relpath(join(dirpath, i), suite.vc_dir) for i in indicators]
                        indicatorsInVC = suite.vc.locate(suite.vc_dir, indicators)
                        # Only proceed if there are indicator files that are not under VC
                        if len(indicators) > len(indicatorsInVC):
                            extra_files = []
                            for p, dirs, files in os.walk(dirpath):
                                dirs[:] = [d for d in dirs if not d.startswith('.') and not d in projectConfigFiles]
                                files[:] = [f for f in files if not f.startswith('.') and not f in projectConfigFiles]
                                extra_files += [join(p, f) for f in files]
                            if len(extra_files) > 0:
                                mx.warn('Removed project ' + dirpath + ' has extra files:\n' + '\n'.join(extra_files))
                            if mx.ask_yes_no(dirpath + ' looks like a removed project -- delete it', 'n'):
                                shutil.rmtree(dirpath)
                                mx.log('Deleted ' + dirpath)

        ideaProjectDirectory = join(suite.dir, '.idea')
        librariesDirectory = join(ideaProjectDirectory, 'libraries')
        if librariesDirectory and exists(librariesDirectory):
            neededLibraries = set()
            unique_library_file_names = set()
            for p in suite.projects_recursive() + mx._mx_suite.projects_recursive():
                if not p.isJavaProject():
                    continue
                def processDep(dep, edge):
                    if dep is p:
                        return
                    if dep.isLibrary() or dep.isJARDistribution() or dep.isJdkLibrary() or dep.isClasspathDependency():
                        neededLibraries.add(dep)
                p.walk_deps(visit=processDep, ignoredEdges=[mx.DEP_EXCLUDED])
            neededLibraryFiles = frozenset([mx_ide_intellij._intellij_library_file_name(l.name, unique_library_file_names) for l in neededLibraries])
            existingLibraryFiles = frozenset(os.listdir(librariesDirectory))
            for library_file in existingLibraryFiles - neededLibraryFiles:
                file_path = join(librariesDirectory, library_file)
                relative_file_path = os.path.relpath(file_path, os.curdir)
                if mx.ask_yes_no(relative_file_path + ' looks like a removed library -- delete it', 'n'):
                    os.remove(file_path)
                    mx.log('Deleted ' + relative_file_path)
