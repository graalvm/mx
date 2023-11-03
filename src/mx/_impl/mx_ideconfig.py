#
# ----------------------------------------------------------------------------------------------------
#
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
from argparse import ArgumentParser, REMAINDER
from os.path import join, basename, exists

from . import mx
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
    with mx.SafeFileCreation(zipPath) as sfc:
        zf = zipfile.ZipFile(sfc.tmpPath, 'w')
        for f in sorted(set(files)):
            relpath = os.path.relpath(f, baseDir)
            arcname = relpath.replace(os.sep, '/')
            zf.write(f, arcname)
        zf.close()


@mx.command('mx', 'ideclean')
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

@mx.command('mx', 'ideinit')
def ideinit(args, refreshOnly=False, buildProcessorJars=True):
    """(re)generate IDE project configurations"""
    parser = ArgumentParser(prog='mx ideinit')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate projects for the mx python projects.')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)
    mx_ide = os.environ.get('MX_IDE', 'all').lower()
    all_ides = mx_ide == 'all'
    if all_ides or mx_ide == 'eclipse':
        mx_ide_eclipse.eclipseinit(args.remainder, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars, doFsckProjects=False, pythonProjects=args.pythonProjects)
    if all_ides or mx_ide == 'netbeans':
        mx_ide_netbeans.netbeansinit(args.remainder, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars, doFsckProjects=False)
    if all_ides or mx_ide == 'intellij':
        mx_ide_intellij.intellijinit(mx_ide_intellij.IntellijConfig(args=args.remainder, refresh_only=refreshOnly, do_fsck_projects=False, python_projects=args.pythonProjects))
    if not refreshOnly:
        fsckprojects([])

@mx.command('mx', 'fsckprojects')
def fsckprojects(args):
    """find directories corresponding to deleted Java projects and delete them"""
    for suite in mx.suites(True, includeBinary=False):
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
                    if dep.isLibrary() or dep.isJARDistribution() or dep.isJdkLibrary() or dep.isMavenProject() or dep.isClasspathDependency():
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
