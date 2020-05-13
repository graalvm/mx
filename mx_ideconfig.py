#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2007, 2019, Oracle and/or its affiliates. All rights reserved.
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
r"""
mx is a command line tool for managing the development of Java code organized as suites of projects.

"""
from __future__ import print_function

import sys

if sys.version_info < (2, 7):
    major, minor, micro, _, _ = sys.version_info
    raise SystemExit('mx requires python 2.7+, not {0}.{1}.{2}'.format(major, minor, micro))

from abc import ABCMeta, abstractmethod, abstractproperty

if __name__ == '__main__':
    # Rename this module as 'mx' so it is not re-executed when imported by other modules.
    sys.modules['mx'] = sys.modules.pop('__main__')

try:
    import defusedxml #pylint: disable=unused-import
    from defusedxml.ElementTree import parse as etreeParse
except ImportError:
    from xml.etree.ElementTree import parse as etreeParse
import os, errno, time, subprocess, shlex, zipfile, signal, tempfile, platform
import textwrap
import socket
import tarfile, gzip
import hashlib
import itertools
from functools import cmp_to_key
# TODO use defusedexpat?
import xml.parsers.expat, xml.sax.saxutils, xml.dom.minidom
from xml.dom.minidom import parseString as minidomParseString
import shutil, re
import pipes
import difflib
import glob
import filecmp
import json
from collections import OrderedDict, namedtuple, deque
from datetime import datetime
from threading import Thread
from argparse import ArgumentParser, PARSER, REMAINDER, Namespace, FileType, HelpFormatter, ArgumentTypeError, RawTextHelpFormatter
from os.path import join, basename, dirname, exists, lexists, isabs, expandvars, isdir, islink, normpath, realpath, splitext
from tempfile import mkdtemp, mkstemp
from io import BytesIO
import fnmatch
import operator
import calendar
import multiprocessing
from stat import S_IWRITE
from mx_commands import MxCommands, MxCommand
from copy import copy

import mx


def eclipseformat(args):
    """run the Eclipse Code Formatter on the Java sources

    The exit code 1 denotes that at least one file was modified."""

    parser = ArgumentParser(prog='mx eclipseformat')
    parser.add_argument('-e', '--eclipse-exe', help='location of the Eclipse executable')
    parser.add_argument('-C', '--no-backup', action='store_false', dest='backup', help='do not save backup of modified files')
    parser.add_argument('--projects', action='store', help='comma separated projects to process (omit to process all projects)')
    parser.add_argument('--primary', action='store_true', help='limit checks to primary suite')
    parser.add_argument('--patchfile', type=FileType("w"), help='file to which a patch denoting the applied formatting changes is written')
    parser.add_argument('--restore', action='store_true', help='restore original files after the formatting job (does not create a backup).')

    args = parser.parse_args(args)
    if args.eclipse_exe is None:
        args.eclipse_exe = os.environ.get('ECLIPSE_EXE')
    if args.eclipse_exe is None:
        mx.abort('Could not find Eclipse executable. Use -e option or ensure ECLIPSE_EXE environment variable is set.')
    if args.restore:
        args.backup = False

    # Maybe an Eclipse installation dir was specified - look for the executable in it
    if isdir(args.eclipse_exe):
        args.eclipse_exe = join(args.eclipse_exe, mx.exe_suffix('eclipse'))
        mx.warn("The eclipse-exe was a directory, now using " + args.eclipse_exe)

    if not os.path.isfile(args.eclipse_exe):
        mx.abort('File does not exist: ' + args.eclipse_exe)
    if not os.access(args.eclipse_exe, os.X_OK):
        mx.abort('Not an executable file: ' + args.eclipse_exe)

    wsroot = eclipseinit([], buildProcessorJars=False, doFsckProjects=False)

    # build list of projects to be processed
    if args.projects is not None:
        projectsToProcess = [mx.project(name) for name in args.projects.split(',')]
    elif args.primary:
        projectsToProcess = mx.projects(limit_to_primary=True)
    else:
        projectsToProcess = mx.projects(opt_limit_to_suite=True)

    class Batch:
        def __init__(self, settingsDir):
            self.path = join(settingsDir, 'org.eclipse.jdt.core.prefs')
            with open(join(settingsDir, 'org.eclipse.jdt.ui.prefs')) as fp:
                jdtUiPrefs = fp.read()
            self.removeTrailingWhitespace = 'sp_cleanup.remove_trailing_whitespaces_all=true' in jdtUiPrefs
            if self.removeTrailingWhitespace:
                assert 'sp_cleanup.remove_trailing_whitespaces=true' in jdtUiPrefs and 'sp_cleanup.remove_trailing_whitespaces_ignore_empty=false' in jdtUiPrefs
            self.cachedHash = None

        def __hash__(self):
            if not self.cachedHash:
                with open(self.path) as fp:
                    self.cachedHash = (fp.read(), self.removeTrailingWhitespace).__hash__()
            return self.cachedHash

        def __eq__(self, other):
            if not isinstance(other, Batch):
                return False
            if self.removeTrailingWhitespace != other.removeTrailingWhitespace:
                return False
            if self.path == other.path:
                return True
            with open(self.path) as fp:
                with open(other.path) as ofp:
                    if fp.read() != ofp.read():
                        return False
            return True


    class FileInfo:
        def __init__(self, path):
            self.path = path
            with open(path) as fp:
                self.content = fp.read()
            self.times = (os.path.getatime(path), mx.getmtime(path))

        def update(self, removeTrailingWhitespace, restore):
            with open(self.path) as fp:
                content = fp.read()
            file_modified = False  # whether the file was modified by formatting
            file_updated = False  # whether the file is really different on disk after the update
            if self.content != content:
                # Only apply *after* formatting to match the order in which the IDE does it
                if removeTrailingWhitespace:
                    content, n = re.subn(r'[ \t]+$', '', content, flags=re.MULTILINE)
                    if n != 0 and self.content == content:
                        # undo on-disk changes made by the Eclipse formatter
                        with open(self.path, 'w') as fp:
                            fp.write(content)

                if self.content != content:
                    rpath = os.path.relpath(self.path, mx.primary_suite().dir)
                    self.diff = difflib.unified_diff(self.content.splitlines(1), content.splitlines(1), fromfile=join('a', rpath), tofile=join('b', rpath))
                    if restore:
                        with open(self.path, 'w') as fp:
                            fp.write(self.content)
                    else:
                        file_updated = True
                        self.content = content
                    file_modified = True

            if not file_updated and (os.path.getatime(self.path), mx.getmtime(self.path)) != self.times:
                # reset access and modification time of file
                os.utime(self.path, self.times)
            return file_modified

    modified = list()
    batches = dict()  # all sources with the same formatting settings are formatted together
    for p in projectsToProcess:
        if not p.isJavaProject():
            continue
        sourceDirs = p.source_dirs()

        batch = Batch(join(p.dir, '.settings'))

        if not exists(batch.path):
            if mx._opts.verbose:
                mx.log('[no Eclipse Code Formatter preferences at {0} - skipping]'.format(batch.path))
            continue

        javafiles = []
        for sourceDir in sourceDirs:
            for root, _, files in os.walk(sourceDir):
                for f in [join(root, name) for name in files if name.endswith('.java')]:
                    javafiles.append(FileInfo(f))
        if len(javafiles) == 0:
            mx.logv('[no Java sources in {0} - skipping]'.format(p.name))
            continue

        res = batches.setdefault(batch, javafiles)
        if res is not javafiles:
            res.extend(javafiles)

    mx.log("we have: " + str(len(batches)) + " batches")
    batch_num = 0
    for batch, javafiles in batches.items():
        batch_num += 1
        mx.log("Processing batch {0} ({1} files)...".format(batch_num, len(javafiles)))

        jdk = mx.get_jdk()

        with tempfile.NamedTemporaryFile(mode='w') as tmp_eclipseini:
            with open(join(dirname(args.eclipse_exe), join('..', 'eclipse', 'eclipse.ini') if mx.is_darwin() else 'eclipse.ini'), 'r') as src:
                locking_added = False
                for line in src.readlines():
                    tmp_eclipseini.write(line)
                    if line.strip() == '-vmargs':
                        tmp_eclipseini.write('-Dosgi.locking=none\n')
                        locking_added = True
                if not locking_added:
                    tmp_eclipseini.write('-vmargs\n-Dosgi.locking=none\n')
            tmp_eclipseini.flush()

            for chunk in mx._chunk_files_for_command_line(javafiles, pathFunction=lambda f: f.path):
                capture = mx.OutputCapture()
                rc = mx.run([args.eclipse_exe,
                          '--launcher.ini', tmp_eclipseini.name,
                          '-nosplash',
                          '-application',
                          '-consolelog',
                          '-data', wsroot,
                          '-vm', jdk.java,
                          'org.eclipse.jdt.core.JavaCodeFormatter',
                          '-config', batch.path]
                            + [f.path for f in chunk], out=capture, err=capture, nonZeroIsFatal=False)
                if rc != 0:
                    mx.log(capture.data)
                    mx.abort("Error while running formatter")
                for fi in chunk:
                    if fi.update(batch.removeTrailingWhitespace, args.restore):
                        modified.append(fi)

    mx.log('{0} files were modified'.format(len(modified)))

    if len(modified) != 0:
        arcbase = mx.primary_suite().dir
        if args.backup:
            backup = os.path.abspath('eclipseformat.backup.zip')
            zf = zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED)
        for fi in modified:
            diffs = ''.join(fi.diff)
            if args.patchfile:
                args.patchfile.write(diffs)
            name = os.path.relpath(fi.path, arcbase)
            mx.log(' - {0}'.format(name))
            mx.log('Changes:')
            mx.log(diffs)
            if args.backup:
                arcname = name.replace(os.sep, '/')
                zf.writestr(arcname, fi.content)
        if args.backup:
            zf.close()
            mx.log('Wrote backup of {0} modified files to {1}'.format(len(modified), backup))
        if args.patchfile:
            mx.log('Wrote patches to {0}'.format(args.patchfile.name))
            args.patchfile.close()
        return 1
    return 0

def _source_locator_memento(deps, jdk=None):
    slm = mx.XMLDoc()
    slm.open('sourceLookupDirector')
    slm.open('sourceContainers', {'duplicates' : 'false'})

    javaCompliance = None

    sources = []
    for dep in deps:
        if dep.isLibrary():
            if hasattr(dep, 'eclipse.container'):
                memento = mx.XMLDoc().element('classpathContainer', {'path' : getattr(dep, 'eclipse.container')}).xml(standalone='no')
                slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})
                sources.append(getattr(dep, 'eclipse.container') +' [classpathContainer]')
            elif dep.get_source_path(resolve=True):
                memento = mx.XMLDoc().element('archive', {'detectRoot' : 'true', 'path' : dep.get_source_path(resolve=True)}).xml(standalone='no')
                slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.debug.core.containerType.externalArchive'})
                sources.append(dep.get_source_path(resolve=True) + ' [externalArchive]')
        elif dep.isJdkLibrary():
            if jdk is None:
                jdk = mx.get_jdk(tag='default')
            path = dep.get_source_path(jdk)
            if path:
                if os.path.isdir(path):
                    memento = mx.XMLDoc().element('directory', {'nest' : 'false', 'path' : path}).xml(standalone='no')
                    slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.debug.core.containerType.directory'})
                    sources.append(path + ' [directory]')
                else:
                    memento = mx.XMLDoc().element('archive', {'detectRoot' : 'true', 'path' : path}).xml(standalone='no')
                    slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.debug.core.containerType.externalArchive'})
                    sources.append(path + ' [externalArchive]')
        elif dep.isProject():
            if not dep.isJavaProject():
                continue
            memento = mx.XMLDoc().element('javaProject', {'name' : dep.name}).xml(standalone='no')
            slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.javaProject'})
            sources.append(dep.name + ' [javaProject]')
            if javaCompliance is None or dep.javaCompliance > javaCompliance:
                javaCompliance = dep.javaCompliance

    if javaCompliance:
        jdkContainer = 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/' +  _to_EclipseJRESystemLibrary(javaCompliance)
        memento = mx.XMLDoc().element('classpathContainer', {'path' : jdkContainer}).xml(standalone='no')
        slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})
        sources.append(jdkContainer + ' [classpathContainer]')
    else:
        memento = mx.XMLDoc().element('classpathContainer', {'path' : 'org.eclipse.jdt.launching.JRE_CONTAINER'}).xml(standalone='no')
        slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})
        sources.append('org.eclipse.jdt.launching.JRE_CONTAINER [classpathContainer]')

    slm.close('sourceContainers')
    slm.close('sourceLookupDirector')
    return slm, sources

### ~~~~~~~~~~~~~ IDE / Eclipse / Netbeans / IntelliJ

def make_eclipse_attach(suite, hostname, port, name=None, deps=None, jdk=None):
    """
    Creates an Eclipse launch configuration file for attaching to a Java process.
    """
    if deps is None:
        deps = []
    javaProjects = [p for p in suite.projects if p.isJavaProject()]
    if len(javaProjects) == 0:
        return None, None

    slm, sources = _source_locator_memento(deps, jdk=jdk)
    # Without an entry for the "Project:" field in an attach configuration, Eclipse Neon has problems connecting
    # to a waiting VM and leaves it hanging. Putting any valid project entry in the field seems to solve it.
    firstProjectName = javaProjects[0].name

    launch = mx.XMLDoc()
    launch.open('launchConfiguration', {'type' : 'org.eclipse.jdt.launching.remoteJavaApplication'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_id', 'value' : 'org.eclipse.jdt.launching.sourceLocator.JavaSourceLookupDirector'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_memento', 'value' : '%s'})
    launch.element('booleanAttribute', {'key' : 'org.eclipse.jdt.launching.ALLOW_TERMINATE', 'value' : 'true'})
    launch.open('mapAttribute', {'key' : 'org.eclipse.jdt.launching.CONNECT_MAP'})
    launch.element('mapEntry', {'key' : 'hostname', 'value' : hostname})
    launch.element('mapEntry', {'key' : 'port', 'value' : port})
    launch.close('mapAttribute')
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.PROJECT_ATTR', 'value' : firstProjectName})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.VM_CONNECTOR_ID', 'value' : 'org.eclipse.jdt.launching.socketAttachConnector'})
    launch.close('launchConfiguration')
    launch = launch.xml(newl='\n', standalone='no') % slm.xml(escape=True, standalone='no')

    if name is None:
        if len(mx.suites()) == 1:
            suitePrefix = ''
        else:
            suitePrefix = suite.name + '-'
        name = suitePrefix + 'attach-' + hostname + '-' + port
    eclipseLaunches = join(suite.mxDir, 'eclipse-launches')
    mx.ensure_dir_exists(eclipseLaunches)
    launchFile = join(eclipseLaunches, name + '.launch')
    sourcesFile = join(eclipseLaunches, name + '.sources')
    mx.update_file(sourcesFile, '\n'.join(sources))
    return mx.update_file(launchFile, launch), launchFile

def make_eclipse_launch(suite, javaArgs, jre, name=None, deps=None):
    """
    Creates an Eclipse launch configuration file for running/debugging a Java command.
    """
    if deps is None:
        deps = []
    mainClass = None
    vmArgs = []
    appArgs = []
    cp = None
    argsCopy = list(reversed(javaArgs))
    while len(argsCopy) != 0:
        a = argsCopy.pop()
        if a == '-jar':
            mainClass = '-jar'
            appArgs = list(reversed(argsCopy))
            break
        if a in mx._VM_OPTS_SPACE_SEPARATED_ARG:
            assert len(argsCopy) != 0
            cp = argsCopy.pop()
            vmArgs.append(a)
            vmArgs.append(cp)
        elif a.startswith('-'):
            vmArgs.append(a)
        else:
            mainClass = a
            appArgs = list(reversed(argsCopy))
            break

    if mainClass is None:
        mx.log('Cannot create Eclipse launch configuration without main class or jar file: java ' + ' '.join(javaArgs))
        return False

    if name is None:
        if mainClass == '-jar':
            name = basename(appArgs[0])
            if len(appArgs) > 1 and not appArgs[1].startswith('-'):
                name = name + '_' + appArgs[1]
        else:
            name = mainClass
        name = time.strftime('%Y-%m-%d-%H%M%S_' + name)

    if cp is not None:
        for e in cp.split(os.pathsep):
            for s in mx.suites():
                deps += [p for p in s.projects if e == p.output_dir()]
                deps += [l for l in s.libs if e == l.get_path(False)]

    slm, sources = _source_locator_memento(deps)

    launch = mx.XMLDoc()
    launch.open('launchConfiguration', {'type' : 'org.eclipse.jdt.launching.localJavaApplication'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_id', 'value' : 'org.eclipse.jdt.launching.sourceLocator.JavaSourceLookupDirector'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_memento', 'value' : '%s'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.JRE_CONTAINER', 'value' : 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/' + jre})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.MAIN_TYPE', 'value' : mainClass})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.PROGRAM_ARGUMENTS', 'value' : ' '.join(appArgs)})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.PROJECT_ATTR', 'value' : ''})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.VM_ARGUMENTS', 'value' : ' '.join(vmArgs)})
    launch.close('launchConfiguration')
    launch = launch.xml(newl='\n', standalone='no') % slm.xml(escape=True, standalone='no')

    eclipseLaunches = join(suite.mxDir, 'eclipse-launches')
    mx.ensure_dir_exists(eclipseLaunches)
    launchFile = join(eclipseLaunches, name + '.launch')
    sourcesFile = join(eclipseLaunches, name + '.sources')
    mx.update_file(sourcesFile, '\n'.join(sources))
    return mx.update_file(launchFile, launch)

def eclipseinit_cli(args):
    """(re)generate Eclipse project configurations and working sets"""
    parser = ArgumentParser(prog='mx eclipseinit')
    parser.add_argument('--no-build', action='store_false', dest='buildProcessorJars', help='Do not build annotation processor jars.')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate PyDev projects for the mx python projects.')
    parser.add_argument('-C', '--log-to-console', action='store_true', dest='logToConsole', help='Send builder output to eclipse console.')
    parser.add_argument('-f', '--force', action='store_true', dest='force', default=False, help='Ignore timestamps when updating files.')
    parser.add_argument('-A', '--absolute-paths', action='store_true', dest='absolutePaths', default=False, help='Use absolute paths in project files.')
    args = parser.parse_args(args)
    eclipseinit(None, args.buildProcessorJars, logToConsole=args.logToConsole, force=args.force, absolutePaths=args.absolutePaths, pythonProjects=args.pythonProjects)
    if _EclipseJRESystemLibraries:
        mx.log('----------------------------------------------')
        executionEnvironments = [n for n in _EclipseJRESystemLibraries if n.startswith('JavaSE-')]
        installedJREs = [n for n in _EclipseJRESystemLibraries if not n.startswith('JavaSE-')]
        if executionEnvironments:
            mx.log('Ensure that these Execution Environments have a Compatible JRE in Eclipse (Preferences -> Java -> Installed JREs -> Execution Environments):')
            for name in executionEnvironments:
                mx.log('  ' + name)
        if installedJREs:
            mx.log('Ensure that there are Installed JREs with these exact names in Eclipse (Preferences -> Java -> Installed JREs):')
            for name in installedJREs:
                mx.log('  ' + name)
            mx.log('You can set the "JRE name" field for a JDK when initially adding it or later with the "Edit..." button.')
            mx.log('See https://help.eclipse.org/photon/topic/org.eclipse.jdt.doc.user/tasks/task-add_new_jre.htm on how to add')
            mx.log('a new JDK to Eclipse. Be sure to select "Standard VM" (even on macOS) for the JRE type.')
        mx.log('----------------------------------------------')

def eclipseinit(args, buildProcessorJars=True, refreshOnly=False, logToConsole=False, doFsckProjects=True, force=False, absolutePaths=False, pythonProjects=False):
    """(re)generate Eclipse project configurations and working sets"""

    for s in mx.suites(True) + [mx._mx_suite]:
        _eclipseinit_suite(s, buildProcessorJars, refreshOnly, logToConsole, force, absolutePaths, pythonProjects)

    wsroot = generate_eclipse_workingsets()

    if doFsckProjects and not refreshOnly:
        fsckprojects([])

    return wsroot

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

EclipseLinkedResource = namedtuple('LinkedResource', ['name', 'type', 'location'])
def _eclipse_linked_resource(name, tp, location):
    return EclipseLinkedResource(name, tp, location)

def get_eclipse_project_rel_locationURI(path, eclipseProjectDir):
    """
    Gets the URI for a resource relative to an Eclipse project directory (i.e.,
    the directory containing the `.project` file for the project). The URI
    returned is based on the builtin PROJECT_LOC Eclipse variable.
    See http://stackoverflow.com/a/7585095
    """
    relpath = os.path.relpath(path, eclipseProjectDir)
    names = relpath.split(os.sep)
    parents = len([n for n in names if n == '..'])
    sep = '/' # Yes, even on Windows...
    if parents:
        projectLoc = 'PARENT-{}-PROJECT_LOC'.format(parents)
    else:
        projectLoc = 'PROJECT_LOC'
    return sep.join([projectLoc] + [n for n in names if n != '..'])

def _get_eclipse_output_path(p, linkedResources=None):
    """
    Gets the Eclipse path attribute value for the output of project `p`.
    """
    outputDirRel = p.output_dir(relative=True)
    if outputDirRel.startswith('..'):
        outputDirName = basename(outputDirRel)
        if linkedResources is not None:
            linkedResources.append(_eclipse_linked_resource(outputDirName, '2', p.output_dir()))
        return outputDirName
    else:
        return outputDirRel

#: Highest Execution Environment defined by most recent Eclipse release.
#: https://wiki.eclipse.org/Execution_Environments
#: https://git.eclipse.org/c/jdt/eclipse.jdt.debug.git/plain/org.eclipse.jdt.launching/plugin.properties
_max_Eclipse_JavaExecutionEnvironment = 13 # pylint: disable=invalid-name

_EclipseJRESystemLibraries = set()

def _to_EclipseJRESystemLibrary(compliance):
    """
    Converts a Java compliance value to a JRE System Library that
    can be put on a project's Build Path.
    """
    if not isinstance(compliance, mx.JavaCompliance):
        compliance = mx.JavaCompliance(compliance)

    if compliance.value > _max_Eclipse_JavaExecutionEnvironment:
        res = 'jdk-' + str(compliance)
    else:
        res = 'JavaSE-' + str(compliance)
    _EclipseJRESystemLibraries.add(res)
    return res

def _eclipseinit_project(p, files=None, libFiles=None, absolutePaths=False):
    mx.ensure_dir_exists(p.dir)

    linkedResources = []

    out = mx.XMLDoc()
    out.open('classpath')

    for src in p.srcDirs:
        srcDir = join(p.dir, src)
        mx.ensure_dir_exists(srcDir)
        out.element('classpathentry', {'kind' : 'src', 'path' : src})

    processors = p.annotation_processors()
    if processors:
        genDir = p.source_gen_dir()
        mx.ensure_dir_exists(genDir)
        if not genDir.startswith(p.dir):
            genDirName = basename(genDir)
            out.open('classpathentry', {'kind' : 'src', 'path' : genDirName})
            linkedResources.append(_eclipse_linked_resource(genDirName, '2', genDir))
        else:
            out.open('classpathentry', {'kind' : 'src', 'path' : p.source_gen_dir(relative=True)})

        if [ap for ap in p.declaredAnnotationProcessors if ap.isLibrary()]:
            # ignore warnings produced by third-party annotation processors
            out.open('attributes')
            out.element('attribute', {'name' : 'ignore_optional_problems', 'value' : 'true'})
            out.close('attributes')
        out.close('classpathentry')
        if files:
            files.append(genDir)

    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        out.element('classpathentry', {'kind' : 'con', 'path' : 'org.eclipse.pde.core.requiredPlugins'})

    projectDeps = []
    jdk = mx.get_jdk(p.javaCompliance)

    def preVisitDep(dep, edge):
        if dep.isLibrary() and hasattr(dep, 'eclipse.container'):
            container = getattr(dep, 'eclipse.container')
            out.element('classpathentry', {'exported' : 'true', 'kind' : 'con', 'path' : container})
            # Ignore the dependencies of this library
            return False
        return True

    def processLibraryDep(dep):
        assert not hasattr(dep, 'eclipse.container'), dep.name + ' should have been handled in preVisitDep'
        path = dep.get_path(resolve=True)

        # Relative paths for "lib" class path entries have various semantics depending on the Eclipse
        # version being used (e.g. see https://bugs.eclipse.org/bugs/show_bug.cgi?id=274737) so it's
        # safest to simply use absolute paths.

        # It's important to use dep.suite as the location for when one suite references
        # a library in another suite.
        path = mx._make_absolute(path, dep.suite.dir)

        attributes = {'exported' : 'true', 'kind' : 'lib', 'path' : path}

        sourcePath = dep.get_source_path(resolve=True)
        if sourcePath is not None:
            attributes['sourcepath'] = sourcePath
        out.element('classpathentry', attributes)
        if libFiles:
            libFiles.append(path)

    def processJdkLibraryDep(dep):
        path = dep.classpath_repr(jdk, resolve=True)
        if path:
            attributes = {'exported' : 'true', 'kind' : 'lib', 'path' : path}
            sourcePath = dep.get_source_path(jdk)
            if sourcePath is not None:
                attributes['sourcepath'] = sourcePath
            out.element('classpathentry', attributes)
            if libFiles:
                libFiles.append(path)

    def processDep(dep, edge):
        if dep is p:
            return
        if dep.isLibrary() or dep.isMavenProject():
            processLibraryDep(dep)
        elif dep.isJavaProject() or dep.isNativeProject():
            projectDeps.append(dep)
        elif dep.isJdkLibrary():
            processJdkLibraryDep(dep)
        elif dep.isJARDistribution() and isinstance(dep.suite, mx.BinarySuite):
            out.element('classpathentry', {'exported' : 'true', 'kind' : 'lib', 'path' : dep.path, 'sourcepath' : dep.sourcesPath})
        elif dep.isJreLibrary() or dep.isDistribution():
            pass
        elif dep.isProject():
            mx.logv('ignoring project ' + dep.name + ' for eclipseinit')
        else:
            mx.abort('unexpected dependency: ' + str(dep))

    p.walk_deps(preVisit=preVisitDep, visit=processDep)

    # When targeting JDK 8 or earlier, dependencies need to precede the JDK on the Eclipse build path.
    # There may be classes in dependencies that are also in the JDK. We want to compile against the
    # former. This is the same -Xbootclasspath:/p trick done in JavacLikeCompiler.prepare.
    putJREFirstOnBuildPath = p.javaCompliance.value >= 9

    allProjectPackages = set()
    for dep in projectDeps:
        if not dep.isNativeProject():
            allProjectPackages.update(dep.defined_java_packages())
            if not putJREFirstOnBuildPath:
                out.element('classpathentry', {'combineaccessrules' : 'false', 'exported' : 'true', 'kind' : 'src', 'path' : '/' + dep.name})

    # Every Java program depends on a JRE
    jreSystemLibrary = _to_EclipseJRESystemLibrary(jdk.javaCompliance)
    out.open('classpathentry', {'kind' : 'con', 'path' : 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/' + jreSystemLibrary})
    if jdk.javaCompliance >= '9':
        out.open('attributes')
        out.element('attribute', {'name' : 'module', 'value' : 'true'})
        moduleDeps = p.get_concealed_imported_packages(jdk=jdk)
        if len(moduleDeps) != 0:
            # Ignore modules (such as jdk.internal.vm.compiler) that define packages
            # that are also defined by project deps as the latter will have the most
            # recent API.
            exports = sorted([(module, pkgs) for module, pkgs in moduleDeps.items() if allProjectPackages.isdisjoint(pkgs)])
            if exports:
                addExportsValue = []
                exported_modules = []
                for module, pkgs in exports:
                    addExportsValue.extend([module + '/' + pkg + '=ALL-UNNAMED' for pkg in pkgs])
                    exported_modules.append(module)
                out.element('attribute', {'name' : 'add-exports', 'value' : ':'.join(addExportsValue)})
                roots = jdk.get_root_modules()
                observable_modules = jdk.get_modules()
                default_module_graph = mx.get_transitive_closure(roots, observable_modules)
                module_graph = mx.get_transitive_closure(roots + exported_modules, observable_modules)
                if default_module_graph != module_graph:
                    # https://github.com/eclipse/eclipse.jdt.core/blob/00dd337bcfe08d8b2d60529b0f7874b88e621c06/org.eclipse.jdt.core/model/org/eclipse/jdt/internal/core/JavaProject.java#L704-L715
                    out.element('attribute', {'name' : 'limit-modules', 'value' : ','.join([m.name for m in module_graph])})
        out.close('attributes')
    out.close('classpathentry')

    if putJREFirstOnBuildPath:
        for dep in projectDeps:
            if not dep.isNativeProject():
                out.element('classpathentry', {'combineaccessrules' : 'false', 'exported' : 'true', 'kind' : 'src', 'path' : '/' + dep.name})

    out.element('classpathentry', {'kind' : 'output', 'path' : _get_eclipse_output_path(p, linkedResources)})

    out.close('classpath')
    classpathFile = join(p.dir, '.classpath')
    mx.update_file(classpathFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(classpathFile)

    csConfig, _, checkstyleProj = p.get_checkstyle_config()
    if csConfig:
        out = mx.XMLDoc()

        dotCheckstyle = join(p.dir, ".checkstyle")
        checkstyleConfigPath = '/' + checkstyleProj.name + '/.checkstyle_checks.xml'
        out.open('fileset-config', {'file-format-version' : '1.2.0', 'simple-config' : 'false'})
        out.open('local-check-config', {'name' : 'Checks', 'location' : checkstyleConfigPath, 'type' : 'project', 'description' : ''})
        out.element('additional-data', {'name' : 'protect-config-file', 'value' : 'false'})
        out.close('local-check-config')
        out.open('fileset', {'name' : 'all', 'enabled' : 'true', 'check-config-name' : 'Checks', 'local' : 'true'})
        out.element('file-match-pattern', {'match-pattern' : r'.*\.java$', 'include-pattern' : 'true'})
        out.element('file-match-pattern', {'match-pattern' : p.source_gen_dir_name() + os.sep + '.*', 'include-pattern' : 'false'})
        out.element('file-match-pattern', {'match-pattern' : '/package-info.java$', 'include-pattern' : 'false'})
        out.close('fileset')

        exclude = join(p.dir, '.checkstyle.exclude')
        if False  and exists(exclude):
            out.open('filter', {'name' : 'FilesFromPackage', 'enabled' : 'true'})
            with open(exclude) as f:
                for line in f:
                    if not line.startswith('#'):
                        line = line.strip()
                    out.element('filter-data', {'value' : line})
            out.close('filter')

        out.close('fileset-config')
        mx.update_file(dotCheckstyle, out.xml(indent='  ', newl='\n'))
        if files:
            files.append(dotCheckstyle)
    else:
        # clean up existing .checkstyle file
        dotCheckstyle = join(p.dir, ".checkstyle")
        if exists(dotCheckstyle):
            os.unlink(dotCheckstyle)

    out = mx.XMLDoc()
    out.open('projectDescription')
    out.element('name', data=p.name)
    out.element('comment', data='')
    out.open('projects')
    for dep in projectDeps:
        if not dep.isNativeProject():
            out.element('project', data=dep.name)
    out.close('projects')
    out.open('buildSpec')
    out.open('buildCommand')
    out.element('name', data='org.eclipse.jdt.core.javabuilder')
    out.element('arguments', data='')
    out.close('buildCommand')
    if csConfig:
        out.open('buildCommand')
        out.element('name', data='net.sf.eclipsecs.core.CheckstyleBuilder')
        out.element('arguments', data='')
        out.close('buildCommand')
    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        for buildCommand in ['org.eclipse.pde.ManifestBuilder', 'org.eclipse.pde.SchemaBuilder']:
            out.open('buildCommand')
            out.element('name', data=buildCommand)
            out.element('arguments', data='')
            out.close('buildCommand')

    out.close('buildSpec')
    out.open('natures')
    out.element('nature', data='org.eclipse.jdt.core.javanature')
    if csConfig:
        out.element('nature', data='net.sf.eclipsecs.core.CheckstyleNature')
    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        out.element('nature', data='org.eclipse.pde.PluginNature')
    out.close('natures')
    if linkedResources:
        out.open('linkedResources')
        for lr in linkedResources:
            out.open('link')
            out.element('name', data=lr.name)
            out.element('type', data=lr.type)
            out.element('locationURI', data=get_eclipse_project_rel_locationURI(lr.location, p.dir) if not absolutePaths else lr.location)
            out.close('link')
        out.close('linkedResources')
    out.close('projectDescription')
    projectFile = join(p.dir, '.project')
    mx.update_file(projectFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(projectFile)

    # copy a possibly modified file to the project's .settings directory
    _copy_eclipse_settings(p, files)

    if processors:
        out = mx.XMLDoc()
        out.open('factorypath')
        out.element('factorypathentry', {'kind' : 'PLUGIN', 'id' : 'org.eclipse.jst.ws.annotations.core', 'enabled' : 'true', 'runInBatchMode' : 'false'})
        processorsPath = mx.classpath_entries(names=processors)
        for e in processorsPath:
            if e.isDistribution() and not isinstance(e.suite, mx.BinarySuite):
                out.element('factorypathentry', {'kind' : 'WKSPJAR', 'id' : '/{0}/{1}'.format(e.name, basename(e.path)), 'enabled' : 'true', 'runInBatchMode' : 'false'})
            elif e.isJdkLibrary() or e.isJreLibrary():
                path = e.classpath_repr(jdk, resolve=True)
                if path:
                    out.element('factorypathentry', {'kind' : 'EXTJAR', 'id' : path, 'enabled' : 'true', 'runInBatchMode' : 'false'})
            else:
                out.element('factorypathentry', {'kind' : 'EXTJAR', 'id' : e.classpath_repr(resolve=True), 'enabled' : 'true', 'runInBatchMode' : 'false'})

        if p.javaCompliance >= '9':
            concealedAPDeps = {}
            for dep in mx.classpath_entries(names=processors, preferProjects=True):
                if dep.isJavaProject():
                    concealed = dep.get_concealed_imported_packages(jdk)
                    if concealed:
                        for module, pkgs in concealed.items():
                            concealedAPDeps.setdefault(module, []).extend(pkgs)
            if concealedAPDeps:
                exports = []
                for module, pkgs in concealedAPDeps.items():
                    for pkg in pkgs:
                        exports.append('--add-exports=' + module + '/' + pkg + '=ALL-UNNAMED')
                mx.warn('Annotation processor(s) for ' + p.name + ' uses non-exported module packages, requiring ' +
                     'the following to be added to eclipse.ini:\n' +
                     '\n'.join(exports))

        out.close('factorypath')
        mx.update_file(join(p.dir, '.factorypath'), out.xml(indent='\t', newl='\n'))
        if files:
            files.append(join(p.dir, '.factorypath'))

_ide_envvars = {
    'MX_ALT_OUTPUT_ROOT' : None,
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

def _capture_eclipse_settings(logToConsole, absolutePaths):
    # Capture interesting settings which drive the output of the projects.
    # Changes to these values should cause regeneration of the project files.
    settings = 'logToConsole=%s\n' % logToConsole
    settings = settings + 'absolutePaths=%s\n' % absolutePaths
    for name, value in _get_ide_envvars().items():
        settings = settings + '%s=%s\n' % (name, value)
    return settings

def _eclipseinit_suite(s, buildProcessorJars=True, refreshOnly=False, logToConsole=False, force=False, absolutePaths=False, pythonProjects=False):
    # a binary suite archive is immutable and no project sources, only the -sources.jar
    # TODO We may need the project (for source debugging) but it needs different treatment
    if isinstance(s, mx.BinarySuite):
        return

    mxOutputDir = mx.ensure_dir_exists(s.get_mx_output_dir())
    configZip = mx.TimeStampFile(join(mxOutputDir, 'eclipse-config.zip'))
    configLibsZip = join(mxOutputDir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    settingsFile = join(mxOutputDir, 'eclipse-project-settings')
    mx.update_file(settingsFile, _capture_eclipse_settings(logToConsole, absolutePaths))
    if not force and _check_ide_timestamp(s, configZip, 'eclipse', settingsFile):
        mx.logv('[Eclipse configurations for {} are up to date - skipping]'.format(s.name))
        return

    files = []
    libFiles = []
    if buildProcessorJars:
        files += mx._processorjars_suite(s)

    for p in s.projects:
        code = mx._function_code(p._eclipseinit)
        if 'absolutePaths' in code.co_varnames[:code.co_argcount]:
            p._eclipseinit(files, libFiles, absolutePaths=absolutePaths)
        else:
            # Support legacy signature
            p._eclipseinit(files, libFiles)

    jdk = mx.get_jdk(tag='default')
    _, launchFile = make_eclipse_attach(s, 'localhost', '8000', deps=mx.dependencies(), jdk=jdk)
    if launchFile:
        files.append(launchFile)

    # Create an Eclipse project for each distribution that will create/update the archive
    # for the distribution whenever any (transitively) dependent project of the
    # distribution is updated.
    for dist in s.dists:
        if not dist.isJARDistribution():
            continue
        projectDir = dist.get_ide_project_dir()
        if not projectDir:
            continue
        mx.ensure_dir_exists(projectDir)
        relevantResources = []
        relevantResourceDeps = set(dist.archived_deps())
        for d in sorted(relevantResourceDeps):
            # Eclipse does not seem to trigger a build for a distribution if the references
            # to the constituent projects are of type IRESOURCE_PROJECT.
            if d.isJavaProject():
                for srcDir in d.srcDirs:
                    relevantResources.append(RelevantResource('/' + d.name + '/' + srcDir, IRESOURCE_FOLDER))
                relevantResources.append(RelevantResource('/' +d.name + '/' + _get_eclipse_output_path(d), IRESOURCE_FOLDER))

        out = mx.XMLDoc()
        out.open('projectDescription')
        out.element('name', data=dist.name)
        out.element('comment', data='Updates ' + dist.path + ' if a project dependency of ' + dist.name + ' is updated')
        out.open('projects')
        for d in sorted(relevantResourceDeps):
            out.element('project', data=d.name)
        out.close('projects')
        out.open('buildSpec')
        dist.dir = projectDir
        builders = _genEclipseBuilder(out, dist, 'Create' + dist.name + 'Dist', '-v archive @' + dist.name,
                                      relevantResources=relevantResources,
                                      logToFile=True, refresh=True, isAsync=False,
                                      logToConsole=logToConsole, appendToLogFile=False,
                                      refreshFile='/{0}/{1}'.format(dist.name, basename(dist.path)))
        files = files + builders

        out.close('buildSpec')
        out.open('natures')
        out.element('nature', data='org.eclipse.jdt.core.javanature')
        out.close('natures')
        out.open('linkedResources')
        out.open('link')
        out.element('name', data=basename(dist.path))
        out.element('type', data=str(IRESOURCE_FILE))
        out.element('location', data=get_eclipse_project_rel_locationURI(dist.path, projectDir) if not absolutePaths else dist.path)
        out.close('link')
        out.close('linkedResources')
        out.close('projectDescription')
        projectFile = join(projectDir, '.project')
        mx.update_file(projectFile, out.xml(indent='\t', newl='\n'))
        files.append(projectFile)

    if pythonProjects:
        projectXml = mx.XMLDoc()
        projectXml.open('projectDescription')
        projectXml.element('name', data=s.name if s is mx._mx_suite else 'mx.' + s.name)
        projectXml.element('comment')
        projectXml.open('projects')
        if s is not mx._mx_suite:
            projectXml.element('project', data=mx._mx_suite.name)
        processed_suites = set([s.name])
        def _mx_projects_suite(visited_suite, suite_import):
            if suite_import.name in processed_suites:
                return
            processed_suites.add(suite_import.name)
            dep_suite = mx.suite(suite_import.name)
            projectXml.element('project', data='mx.' + suite_import.name)
            dep_suite.visit_imports(_mx_projects_suite)
        s.visit_imports(_mx_projects_suite)
        projectXml.close('projects')
        projectXml.open('buildSpec')
        projectXml.open('buildCommand')
        projectXml.element('name', data='org.python.pydev.PyDevBuilder')
        projectXml.element('arguments')
        projectXml.close('buildCommand')
        projectXml.close('buildSpec')
        projectXml.open('natures')
        projectXml.element('nature', data='org.python.pydev.pythonNature')
        projectXml.close('natures')
        projectXml.close('projectDescription')
        projectFile = join(s.dir if s is mx._mx_suite else s.mxDir, '.project')
        mx.update_file(projectFile, projectXml.xml(indent='  ', newl='\n'))
        files.append(projectFile)

        pydevProjectXml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<?eclipse-pydev version="1.0"?>
<pydev_project>
<pydev_property name="org.python.pydev.PYTHON_PROJECT_INTERPRETER">Default</pydev_property>
<pydev_property name="org.python.pydev.PYTHON_PROJECT_VERSION">python 2.7</pydev_property>
<pydev_pathproperty name="org.python.pydev.PROJECT_SOURCE_PATH">
<path>/{}</path>
</pydev_pathproperty>
</pydev_project>
""".format(s.name if s is mx._mx_suite else 'mx.' + s.name)
        pydevProjectFile = join(s.dir if s is mx._mx_suite else s.mxDir, '.pydevproject')
        mx.update_file(pydevProjectFile, pydevProjectXml)
        files.append(pydevProjectFile)

    _zip_files(files + [settingsFile], s.dir, configZip.path)
    _zip_files(libFiles, s.dir, configLibsZip)

def _zip_files(files, baseDir, zipPath):
    with mx.SafeFileCreation(zipPath) as sfc:
        zf = zipfile.ZipFile(sfc.tmpPath, 'w')
        for f in sorted(set(files)):
            relpath = os.path.relpath(f, baseDir)
            arcname = relpath.replace(os.sep, '/')
            zf.write(f, arcname)
        zf.close()

RelevantResource = namedtuple('RelevantResource', ['path', 'type'])

# http://grepcode.com/file/repository.grepcode.com/java/eclipse.org/4.4.2/org.eclipse.core/resources/3.9.1/org/eclipse/core/resources/IResource.java#76
IRESOURCE_FILE = 1
IRESOURCE_FOLDER = 2

def _genEclipseBuilder(dotProjectDoc, p, name, mxCommand, refresh=True, refreshFile=None, relevantResources=None, isAsync=False, logToConsole=False, logToFile=False, appendToLogFile=True, xmlIndent='\t', xmlStandalone=None):
    externalToolDir = join(p.dir, '.externalToolBuilders')
    launchOut = mx.XMLDoc()
    consoleOn = 'true' if logToConsole else 'false'
    launchOut.open('launchConfiguration', {'type' : 'org.eclipse.ui.externaltools.ProgramBuilderLaunchConfigurationType'})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.core.capture_output', 'value': consoleOn})
    launchOut.open('mapAttribute', {'key' : 'org.eclipse.debug.core.environmentVariables'})
    for key, value in _get_ide_envvars().items():
        launchOut.element('mapEntry', {'key' : key, 'value' : value})
    launchOut.close('mapAttribute')

    if refresh:
        if refreshFile is None:
            refreshScope = '${project}'
        else:
            refreshScope = '${working_set:<?xml version="1.0" encoding="UTF-8"?><resources><item path="' + refreshFile + '" type="' + str(IRESOURCE_FILE) + '"/></resources>}'

        launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.core.ATTR_REFRESH_RECURSIVE', 'value':  'false'})
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.debug.core.ATTR_REFRESH_SCOPE', 'value':  refreshScope})

    if relevantResources:
        # http://grepcode.com/file/repository.grepcode.com/java/eclipse.org/4.4.2/org.eclipse.debug/core/3.9.1/org/eclipse/debug/core/RefreshUtil.java#169
        resources = '${working_set:<?xml version="1.0" encoding="UTF-8"?><resources>'
        for relevantResource in relevantResources:
            resources += '<item path="' + relevantResource.path + '" type="' + str(relevantResource.type) + '"/>'
        resources += '</resources>}'
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_BUILD_SCOPE', 'value': resources})

    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_CONSOLE_OUTPUT_ON', 'value': consoleOn})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_LAUNCH_IN_BACKGROUND', 'value': 'true' if isAsync else 'false'})
    if logToFile:
        logFile = join(externalToolDir, name + '.log')
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_CAPTURE_IN_FILE', 'value': logFile})
        launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_APPEND_TO_FILE', 'value': 'true' if appendToLogFile else 'false'})

    # expect to find the OS command to invoke mx in the same directory
    baseDir = dirname(os.path.abspath(__file__))

    cmd = 'mx'
    if mx.is_windows():
        cmd = 'mx.cmd'
    cmdPath = join(baseDir, cmd)
    if not os.path.exists(cmdPath):
        # backwards compatibility for when the commands lived in parent of mxtool
        if cmd == 'mx':
            cmd = 'mx.sh'
        cmdPath = join(dirname(baseDir), cmd)
        if not os.path.exists(cmdPath):
            mx.abort('cannot locate ' + cmd)

    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_LOCATION', 'value':  cmdPath})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_RUN_BUILD_KINDS', 'value': 'auto,full,incremental'})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_TOOL_ARGUMENTS', 'value': mxCommand})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_TRIGGERS_CONFIGURED', 'value': 'true'})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_WORKING_DIRECTORY', 'value': p.suite.dir})


    launchOut.close('launchConfiguration')

    mx.ensure_dir_exists(externalToolDir)
    launchFile = join(externalToolDir, name + '.launch')
    mx.update_file(launchFile, launchOut.xml(indent=xmlIndent, standalone=xmlStandalone, newl='\n'))

    dotProjectDoc.open('buildCommand')
    dotProjectDoc.element('name', data='org.eclipse.ui.externaltools.ExternalToolBuilder')
    dotProjectDoc.element('triggers', data='auto,full,incremental,')
    dotProjectDoc.open('arguments')
    dotProjectDoc.open('dictionary')
    dotProjectDoc.element('key', data='LaunchConfigHandle')
    dotProjectDoc.element('value', data='<project>/.externalToolBuilders/' + name + '.launch')
    dotProjectDoc.close('dictionary')
    dotProjectDoc.open('dictionary')
    dotProjectDoc.element('key', data='incclean')
    dotProjectDoc.element('value', data='true')
    dotProjectDoc.close('dictionary')
    dotProjectDoc.close('arguments')
    dotProjectDoc.close('buildCommand')
    return [launchFile]

def generate_eclipse_workingsets():
    """
    Populate the workspace's working set configuration with working sets generated from project data for the primary suite
    If the workspace already contains working set definitions, the existing ones will be retained and extended.
    In case mx/env does not contain a WORKSPACE definition pointing to the workspace root directory, a parent search from the primary suite directory is performed.
    If no workspace root directory can be identified, the primary suite directory is used and the user has to place the workingsets.xml file by hand.
    """

    # identify the location where to look for workingsets.xml
    wsfilename = 'workingsets.xml'
    wsloc = '.metadata/.plugins/org.eclipse.ui.workbench'
    if 'WORKSPACE' in os.environ:
        expected_wsroot = os.environ['WORKSPACE']
    else:
        expected_wsroot = mx.primary_suite().dir

    wsroot = _find_eclipse_wsroot(expected_wsroot)
    if wsroot is None:
        # failed to find it
        wsroot = expected_wsroot

    wsdir = join(wsroot, wsloc)
    if not exists(wsdir):
        wsdir = wsroot
        mx.logv('Could not find Eclipse metadata directory. Please place ' + wsfilename + ' in ' + wsloc + ' manually.')
    wspath = join(wsdir, wsfilename)

    def _add_to_working_set(key, value):
        if key not in workingSets:
            workingSets[key] = [value]
        else:
            workingSets[key].append(value)

    # gather working set info from project data
    workingSets = dict()
    for p in mx.projects():
        if p.workingSets is None:
            continue
        for w in p.workingSets.split(","):
            _add_to_working_set(w, p.name)

    # the mx metdata directories are included in the appropriate working sets
    _add_to_working_set('MX', 'mxtool')
    for suite in mx.suites(True):
        _add_to_working_set('MX', basename(suite.mxDir))

    if exists(wspath):
        wsdoc = _copy_workingset_xml(wspath, workingSets)
    else:
        wsdoc = _make_workingset_xml(workingSets)

    mx.update_file(wspath, wsdoc.xml(newl='\n'))
    return wsroot

def _find_eclipse_wsroot(wsdir):
    md = join(wsdir, '.metadata')
    if exists(md):
        return wsdir
    split = os.path.split(wsdir)
    if split[0] == wsdir:  # root directory
        return None
    else:
        return _find_eclipse_wsroot(split[0])

def _make_workingset_xml(workingSets):
    wsdoc = mx.XMLDoc()
    wsdoc.open('workingSetManager')

    for w in sorted(workingSets.keys()):
        _workingset_open(wsdoc, w)
        for p in workingSets[w]:
            _workingset_element(wsdoc, p)
        wsdoc.close('workingSet')

    wsdoc.close('workingSetManager')
    return wsdoc

def _copy_workingset_xml(wspath, workingSets):
    target = mx.XMLDoc()
    target.open('workingSetManager')

    parser = xml.parsers.expat.ParserCreate()

    class ParserState(object):
        def __init__(self):
            self.current_ws_name = 'none yet'
            self.current_ws = None
            self.seen_ws = list()
            self.seen_projects = list()
            self.aggregate_ws = False
            self.nested_ws = False

    ps = ParserState()

    # parsing logic
    def _ws_start(name, attributes):
        if name == 'workingSet':
            if 'name' in attributes:
                ps.current_ws_name = attributes['name']
                if 'aggregate' in attributes and attributes['aggregate'] == 'true':
                    ps.aggregate_ws = True
                    ps.current_ws = None
                elif ps.current_ws_name in workingSets:
                    ps.current_ws = workingSets[ps.current_ws_name]
                    ps.seen_ws.append(ps.current_ws_name)
                    ps.seen_projects = list()
                else:
                    ps.current_ws = None
            target.open(name, attributes)
            parser.StartElementHandler = _ws_item

    def _ws_end(name):
        closeAndResetHandler = False
        if name == 'workingSet':
            if ps.aggregate_ws:
                if ps.nested_ws:
                    ps.nested_ws = False
                else:
                    ps.aggregate_ws = False
                    closeAndResetHandler = True
            else:
                if not ps.current_ws is None:
                    for p in ps.current_ws:
                        if not p in ps.seen_projects:
                            _workingset_element(target, p)
                closeAndResetHandler = True
            if closeAndResetHandler:
                target.close('workingSet')
                parser.StartElementHandler = _ws_start
        elif name == 'workingSetManager':
            # process all working sets that are new to the file
            for w in sorted(workingSets.keys()):
                if not w in ps.seen_ws:
                    _workingset_open(target, w)
                    for p in workingSets[w]:
                        _workingset_element(target, p)
                    target.close('workingSet')

    def _ws_item(name, attributes):
        if name == 'item':
            if ps.current_ws is None:
                target.element(name, attributes)
            elif not 'elementID' in attributes and 'factoryID' in attributes and 'path' in attributes and 'type' in attributes:
                target.element(name, attributes)
                p_name = attributes['path'][1:]  # strip off the leading '/'
                ps.seen_projects.append(p_name)
            else:
                p_name = attributes['elementID'][1:]  # strip off the leading '='
                _workingset_element(target, p_name)
                ps.seen_projects.append(p_name)
        elif name == 'workingSet':
            ps.nested_ws = True
            target.element(name, attributes)

    # process document
    parser.StartElementHandler = _ws_start
    parser.EndElementHandler = _ws_end
    with open(wspath, 'rb') as wsfile:
        parser.ParseFile(wsfile)

    target.close('workingSetManager')
    return target

def _workingset_open(wsdoc, ws):
    wsdoc.open('workingSet', {'editPageID': 'org.eclipse.jdt.ui.JavaWorkingSetPage', 'factoryID': 'org.eclipse.ui.internal.WorkingSetFactory', 'id': 'wsid_' + ws, 'label': ws, 'name': ws})

def _workingset_element(wsdoc, p):
    wsdoc.element('item', {'elementID': '=' + p, 'factoryID': 'org.eclipse.jdt.ui.PersistableJavaElementFactory'})

def netbeansinit(args, refreshOnly=False, buildProcessorJars=True, doFsckProjects=True):
    """(re)generate NetBeans project configurations"""

    for suite in mx.suites(True) + [mx._mx_suite]:
        _netbeansinit_suite(args, suite, refreshOnly, buildProcessorJars)

    if doFsckProjects and not refreshOnly:
        fsckprojects([])

def _netbeansinit_project(p, jdks=None, files=None, libFiles=None, dists=None):
    dists = [] if dists is None else dists
    mx.ensure_dir_exists(join(p.dir, 'nbproject'))

    jdk = mx.get_jdk(p.javaCompliance)
    assert jdk

    if jdks:
        jdks.add(jdk)

    execDir = mx.primary_suite().dir

    out = mx.XMLDoc()
    out.open('project', {'name' : p.name, 'default' : 'default', 'basedir' : '.'})
    out.element('description', data='Builds, tests, and runs the project ' + p.name + '.')
    out.element('available', {'file' : 'nbproject/build-impl.xml', 'property' : 'build.impl.exists'})
    out.element('import', {'file' : 'nbproject/build-impl.xml', 'optional' : 'true'})
    out.element('extension-point', {'name' : '-mx-init'})
    out.element('available', {'file' : 'nbproject/build-impl.xml', 'property' : 'mx.init.targets', 'value' : 'init'})
    out.element('property', {'name' : 'mx.init.targets', 'value' : ''})
    out.element('bindtargets', {'extensionPoint' : '-mx-init', 'targets' : '${mx.init.targets}'})

    out.open('target', {'name' : '-post-init'})
    out.open('pathconvert', {'property' : 'comma.javac.classpath', 'pathsep' : ','})
    out.element('path', {'path' : '${javac.classpath}'})
    out.close('pathconvert')

    out.open('restrict', {'id' : 'missing.javac.classpath'})
    out.element('filelist', {'dir' : '${basedir}', 'files' : '${comma.javac.classpath}'})
    out.open('not')
    out.element('exists')
    out.close('not')
    out.close('restrict')

    out.element('property', {'name' : 'missing.javac.classpath', 'refid' : 'missing.javac.classpath'})

    out.open('condition', {'property' : 'no.dependencies', 'value' : 'true'})
    out.element('equals', {'arg1' : '${missing.javac.classpath}', 'arg2' : ''})
    out.close('condition')

    out.element('property', {'name' : 'no.dependencies', 'value' : 'false'})

    out.open('condition', {'property' : 'no.deps'})
    out.element('equals', {'arg1' : '${no.dependencies}', 'arg2' : 'true'})
    out.close('condition')

    out.close('target')
    out.open('target', {'name' : 'clean'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'clean'})
    out.element('arg', {'value' : '--projects'})
    out.element('arg', {'value' : p.name})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'compile'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'build'})
    dependsOn = p.name
    for d in dists:
        dependsOn = dependsOn + ',' + d.name
    out.element('arg', {'value' : '--only'})
    out.element('arg', {'value' : dependsOn})
    out.element('arg', {'value' : '--force-javac'})
    out.element('arg', {'value' : '--no-native'})
    out.element('arg', {'value' : '--no-daemon'})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'package', 'if' : 'build.impl.exists'})
    out.element('antcall', {'target': '-package', 'inheritall': 'true', 'inheritrefs': 'true'})
    out.close('target')
    out.open('target', {'name' : '-package', 'depends' : '-mx-init'})
    out.element('loadfile', {'srcFile' : join(p.suite.get_output_root(), 'netbeans.log'), 'property' : 'netbeans.log', 'failonerror' : 'false'})
    out.element('echo', {'message' : '...truncated...${line.separator}', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
    out.element('echo', {'message' : '${netbeans.log}'})
    for d in dists:
        if d.isDistribution():
            out.element('touch', {'file' : '${java.io.tmpdir}/' + d.name})
            out.element('echo', {'message' : d.name + ' set to now${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
    out.open('copy', {'todir' : '${build.classes.dir}', 'overwrite' : 'true'})
    out.element('resources', {'refid' : 'changed.files'})
    out.close('copy')
    if len(p.annotation_processors()) > 0:
        out.open('copy', {'todir' : '${src.ap-source-output.dir}'})
        out.open('fileset', {'dir': '${cos.src.dir.internal}/../sources/'})
        out.element('include', {'name': '**/*.java'})
        out.close('fileset')
        out.close('copy')
    out.open('exec', {'executable' : '${ant.home}/bin/ant', 'spawn' : 'true'})
    out.element('arg', {'value' : '-f'})
    out.element('arg', {'value' : '${ant.file}'})
    out.element('arg', {'value' : 'packagelater'})
    out.close('exec')
    out.close('target')
    for d in dists:
        if d.isDistribution():
            out.open('target', {'name' : 'checkpackage-' + d.name})
            out.open('tstamp')
            out.element('format', {'pattern' : 'S', 'unit' : 'millisecond', 'property' : 'at.' + d.name})
            out.close('tstamp')
            out.element('touch', {'file' : '${java.io.tmpdir}/' + d.name, 'millis' : '${at.' + d.name + '}0000'})
            out.element('echo', {'message' : d.name + ' touched to ${at.' + d.name + '}0000${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
            out.element('sleep', {'seconds' : '3'})
            out.open('condition', {'property' : 'mx.' + d.name, 'value' : sys.executable})
            out.open('islastmodified', {'millis' : '${at.' + d.name + '}0000', 'mode' : 'equals'})
            out.element('file', {'file' : '${java.io.tmpdir}/' + d.name})
            out.close('islastmodified')
            out.close('condition')
            out.element('echo', {'message' : d.name + ' defined as ' + '${mx.' + d.name + '}${line.separator}', 'append' : 'true', 'output' : join(p.suite.get_output_root(), 'netbeans.log')})
            out.close('target')
            out.open('target', {'name' : 'packagelater-' + d.name, 'depends' : 'checkpackage-' + d.name, 'if' : 'mx.' + d.name})
            out.open('exec', {'executable' : '${mx.' + d.name + '}', 'failonerror' : 'true', 'dir' : execDir, 'output' : join(p.suite.get_output_root(), 'netbeans.log'), 'append' : 'true'})
            out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
            out.element('arg', {'value' : os.path.abspath(__file__)})
            out.element('arg', {'value' : 'build'})
            out.element('arg', {'value' : '-f'})
            out.element('arg', {'value' : '--only'})
            out.element('arg', {'value' : d.name})
            out.element('arg', {'value' : '--force-javac'})
            out.element('arg', {'value' : '--no-native'})
            out.element('arg', {'value' : '--no-daemon'})
            out.close('exec')
            out.close('target')
    dependsOn = ''
    sep = ''
    for d in dists:
        dependsOn = dependsOn + sep + 'packagelater-' + d.name
        sep = ','
    out.open('target', {'name' : 'packagelater', 'depends' : dependsOn})
    out.close('target')
    out.open('target', {'name' : 'jar', 'depends' : 'compile'})
    out.close('target')
    out.element('target', {'name' : 'test', 'depends' : 'run'})
    out.element('target', {'name' : 'test-single', 'depends' : 'run'})
    out.open('target', {'name' : 'run'})
    out.element('property', {'name' : 'test.class', 'value' : p.name})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'unittest'})
    out.element('arg', {'value' : '${test.class}'})
    out.close('exec')
    out.close('target')
    out.element('target', {'name' : 'debug-test', 'depends' : 'debug'})
    out.open('target', {'name' : 'debug', 'depends' : '-mx-init'})
    out.element('property', {'name' : 'test.class', 'value' : p.name})
    out.open('nbjpdastart', {'addressproperty' : 'jpda.address', 'name' : p.name})
    out.open('classpath')
    out.open('fileset', {'dir' : '..'})
    out.element('include', {'name' : '*/bin/'})
    out.close('fileset')
    out.close('classpath')
    out.open('sourcepath')
    out.element('pathelement', {'location' : 'src'})
    out.close('sourcepath')
    out.close('nbjpdastart')
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : '-d'})
    out.element('arg', {'value' : '--attach'})
    out.element('arg', {'value' : '${jpda.address}'})
    out.element('arg', {'value' : 'unittest'})
    out.element('arg', {'value' : '${test.class}'})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'javadoc'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true', 'dir' : execDir})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'javadoc'})
    out.element('arg', {'value' : '--projects'})
    out.element('arg', {'value' : p.name})
    out.element('arg', {'value' : '--force'})
    out.close('exec')
    out.element('nbbrowse', {'file' : 'javadoc/index.html'})
    out.close('target')
    out.close('project')
    mx.update_file(join(p.dir, 'build.xml'), out.xml(indent='\t', newl='\n'))
    if files is not None:
        files.append(join(p.dir, 'build.xml'))

    out = mx.XMLDoc()
    out.open('project', {'xmlns' : 'http://www.netbeans.org/ns/project/1'})
    out.element('type', data='org.netbeans.modules.java.j2seproject')
    out.open('configuration')
    out.open('data', {'xmlns' : 'http://www.netbeans.org/ns/j2se-project/3'})
    out.element('name', data=p.name)
    out.element('explicit-platform', {'explicit-source-supported' : 'true'})
    out.open('source-roots')
    out.element('root', {'id' : 'src.dir'})
    if len(p.annotation_processors()) > 0:
        out.element('root', {'id' : 'src.ap-source-output.dir', 'name' : 'Generated Packages'})
    out.close('source-roots')
    out.open('test-roots')
    out.close('test-roots')
    out.close('data')

    firstDep = []

    def processDep(dep, edge):
        if dep is p:
            return

        if dep.isProject():
            n = dep.name.replace('.', '_')
            if not firstDep:
                out.open('references', {'xmlns' : 'http://www.netbeans.org/ns/ant-project-references/1'})
                firstDep.append(dep)

            out.open('reference')
            out.element('foreign-project', data=n)
            out.element('artifact-type', data='jar')
            out.element('script', data='build.xml')
            out.element('target', data='jar')
            out.element('clean-target', data='clean')
            out.element('id', data='jar')
            out.close('reference') #pylint: disable=too-many-function-args
    p.walk_deps(visit=processDep, ignoredEdges=[mx.DEP_EXCLUDED])

    if firstDep:
        out.close('references')

    out.close('configuration')
    out.close('project')
    mx.update_file(join(p.dir, 'nbproject', 'project.xml'), out.xml(indent='    ', newl='\n'))
    if files is not None:
        files.append(join(p.dir, 'nbproject', 'project.xml'))

    out = mx.StringIO()
    jdkPlatform = 'JDK_' + str(jdk.version)

    annotationProcessorEnabled = "false"
    annotationProcessorSrcFolder = ""
    annotationProcessorSrcFolderRef = ""
    if len(p.annotation_processors()) > 0:
        annotationProcessorEnabled = "true"
        mx.ensure_dir_exists(p.source_gen_dir())
        annotationProcessorSrcFolder = os.path.relpath(p.source_gen_dir(), p.dir)
        annotationProcessorSrcFolder = annotationProcessorSrcFolder.replace('\\', '\\\\')
        annotationProcessorSrcFolderRef = "src.ap-source-output.dir=" + annotationProcessorSrcFolder

    canSymlink = not (mx.is_windows() or mx.is_cygwin()) and 'symlink' in dir(os)
    if canSymlink:
        nbBuildDir = join(p.dir, 'nbproject', 'build')
        apSourceOutRef = "annotation.processing.source.output=" + annotationProcessorSrcFolder
        if os.path.lexists(nbBuildDir):
            os.unlink(nbBuildDir)
        os.symlink(p.output_dir(), nbBuildDir)
    else:
        nbBuildDir = p.output_dir()
        apSourceOutRef = ""
    mx.ensure_dir_exists(p.output_dir())

    _copy_eclipse_settings(p)

    content = """
annotation.processing.enabled=""" + annotationProcessorEnabled + """
annotation.processing.enabled.in.editor=""" + annotationProcessorEnabled + """
""" + apSourceOutRef + """
annotation.processing.processors.list=
annotation.processing.run.all.processors=true
application.title=""" + p.name + """
application.vendor=mx
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterActiveProfile=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterEnabled=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterLocation=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.enableFormatAsSaveAction=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.linefeed=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.preserveBreakPoints=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.SaveActionModifiedLinesOnly=false
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.showNotifications=false
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.sourcelevel=
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.useProjectPref=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.useProjectSettings=true
auxiliary.de-markiewb-netbeans-plugins-eclipse-formatter.eclipseFormatterActiveProfile=
auxiliary.org-netbeans-spi-editor-hints-projects.perProjectHintSettingsEnabled=true
auxiliary.org-netbeans-spi-editor-hints-projects.perProjectHintSettingsFile=nbproject/cfg_hints.xml
build.classes.dir=${build.dir}
build.classes.excludes=**/*.java,**/*.form
# This directory is removed when the project is cleaned:
build.dir=""" + nbBuildDir + """
$cos.update=package
$cos.update.resources=changed.files
compile.on.save=true
build.generated.sources.dir=${build.dir}/generated-sources
# Only compile against the classpath explicitly listed here:
build.sysclasspath=ignore
build.test.classes.dir=${build.dir}/test/classes
build.test.results.dir=${build.dir}/test/results
# Uncomment to specify the preferred debugger connection transport:
#debug.transport=dt_socket
debug.classpath=\\
${run.classpath}
debug.test.classpath=\\
${run.test.classpath}
# This directory is removed when the project is cleaned:
dist.dir=dist
dist.jar=${dist.dir}/""" + p.name + """.jar
dist.javadoc.dir=${dist.dir}/javadoc
endorsed.classpath=
excludes=
includes=**
jar.compress=false
java.main.action=test
# Space-separated list of extra javac options
javac.compilerargs=-XDignore.symbol.file
javac.deprecation=false
javac.source=""" + str(p.javaCompliance) + """
javac.target=""" + str(p.javaCompliance) + """
javac.test.classpath=\\
${javac.classpath}:\\
${build.classes.dir}
javadoc.additionalparam=
javadoc.author=false
javadoc.encoding=${source.encoding}
javadoc.noindex=false
javadoc.nonavbar=false
javadoc.notree=false
javadoc.private=false
javadoc.splitindex=true
javadoc.use=true
javadoc.version=false
javadoc.windowtitle=
manifest.file=manifest.mf
meta.inf.dir=${src.dir}/META-INF
mkdist.disabled=false
platforms.""" + jdkPlatform + """.home=""" + jdk.home + """
platform.active=""" + jdkPlatform + """
run.classpath=\\
${javac.classpath}:\\
${build.classes.dir}
# Space-separated list of JVM arguments used when running the project
# (you may also define separate properties like run-sys-prop.name=value instead of -Dname=value
# or test-sys-prop.name=value to set system properties for unit tests):
run.jvmargs=
run.test.classpath=\\
${javac.test.classpath}:\\
${build.test.classes.dir}
test.src.dir=./test
""" + annotationProcessorSrcFolderRef + """
source.encoding=UTF-8""".replace(':', os.pathsep).replace('/', os.sep)
    print(content, file=out)

    # Workaround for NetBeans "too clever" behavior. If you want to be
    # able to press F6 or Ctrl-F5 in NetBeans and run/debug unit tests
    # then the project must have its main.class property set to an
    # existing class with a properly defined main method. Until this
    # behavior is remedied, we specify a well known Truffle class
    # that will be on the class path for most Truffle projects.
    # This can be overridden by defining a netbeans.project.properties
    # attribute for a project in suite.py (see below).
    print("main.class=com.oracle.truffle.api.impl.Accessor", file=out)

    # Add extra properties specified in suite.py for this project
    if hasattr(p, 'netbeans.project.properties'):
        properties = getattr(p, 'netbeans.project.properties')
        for prop in [properties] if isinstance(properties, str) else properties:
            print(prop, file=out)

    mainSrc = True
    for src in p.srcDirs:
        srcDir = join(p.dir, src)
        mx.ensure_dir_exists(srcDir)
        ref = 'file.reference.' + p.name + '-' + src
        print(ref + '=' + src, file=out)
        if mainSrc:
            print('src.dir=${' + ref + '}', file=out)
            mainSrc = False
        else:
            print('src.' + src + '.dir=${' + ref + '}', file=out)

    javacClasspath = []

    def newDepsCollector(into):
        return lambda dep, edge: into.append(dep) if dep.isLibrary() or dep.isJdkLibrary() or dep.isProject() or dep.isClasspathDependency() else None

    deps = []
    p.walk_deps(visit=newDepsCollector(deps))
    annotationProcessorOnlyDeps = []
    if len(p.annotation_processors()) > 0:
        for apDep in p.annotation_processors():
            resolvedApDeps = []
            apDep.walk_deps(visit=newDepsCollector(resolvedApDeps))
            for resolvedApDep in resolvedApDeps:
                if not resolvedApDep in deps:
                    deps.append(resolvedApDep)
                    annotationProcessorOnlyDeps.append(resolvedApDep)

    annotationProcessorReferences = []

    for dep in deps:
        if dep == p:
            continue

        if dep.isLibrary() or dep.isJdkLibrary():
            if dep.isLibrary():
                path = dep.get_path(resolve=True)
                sourcePath = dep.get_source_path(resolve=True)
            else:
                path = dep.classpath_repr(jdk, resolve=True)
                sourcePath = dep.get_source_path(jdk)
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print(ref + '=' + path, file=out)
                if libFiles:
                    libFiles.append(path)
            if sourcePath:
                if os.sep == '\\':
                    sourcePath = sourcePath.replace('\\', '\\\\')
                print('source.reference.' + dep.name + '-bin=' + sourcePath, file=out)
        elif dep.isMavenProject():
            path = dep.get_path(resolve=False)
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print(ref + '=' + path, file=out)
        elif dep.isProject():
            n = dep.name.replace('.', '_')
            relDepPath = os.path.relpath(dep.dir, p.dir).replace(os.sep, '/')
            if canSymlink:
                depBuildPath = join('nbproject', 'build')
            else:
                depBuildPath = 'dist/' + dep.name + '.jar'
            ref = 'reference.' + n + '.jar'
            print('project.' + n + '=' + relDepPath, file=out)
            print(ref + '=${project.' + n + '}/' + depBuildPath, file=out)
        elif dep.isJreLibrary():
            continue
        elif dep.isClasspathDependency():
            extra = [di for di in dep.deps if di not in deps]
            if dep.isDistribution() and dep.deps and not extra:
                # ignore distribution classpath dependencies that only contain other explicit depedencies
                continue
            path = dep.classpath_repr(resolve=True)
            sourcePath = dep.get_source_path(jdk) if hasattr(dep, 'get_source_path') else None
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print(ref + '=' + path, file=out)
                if libFiles:
                    libFiles.append(path)
                if sourcePath:
                    if os.sep == '\\':
                        sourcePath = sourcePath.replace('\\', '\\\\')
                    print('source.reference.' + dep.name + '-bin=' + sourcePath, file=out)

        if not dep in annotationProcessorOnlyDeps:
            javacClasspath.append('${' + ref + '}')
        else:
            annotationProcessorReferences.append('${' + ref + '}')

    print('javac.classpath=\\\n    ' + (os.pathsep + '\\\n    ').join(javacClasspath), file=out)
    print('javac.processorpath=' + (os.pathsep + '\\\n    ').join(['${javac.classpath}'] + annotationProcessorReferences), file=out)
    print('javac.test.processorpath=' + (os.pathsep + '\\\n    ').join(['${javac.test.classpath}'] + annotationProcessorReferences), file=out)

    mx.update_file(join(p.dir, 'nbproject', 'project.properties'), out.getvalue())
    out.close()

    if files is not None:
        files.append(join(p.dir, 'nbproject', 'project.properties'))

    for source in p.suite.netbeans_settings_sources().get('cfg_hints.xml'):
        with open(source) as fp:
            content = fp.read()
    mx.update_file(join(p.dir, 'nbproject', 'cfg_hints.xml'), content)

    if files is not None:
        files.append(join(p.dir, 'nbproject', 'cfg_hints.xml'))

def _netbeansinit_suite(args, suite, refreshOnly=False, buildProcessorJars=True):
    mxOutputDir = mx.ensure_dir_exists(suite.get_mx_output_dir())
    configZip = mx.TimeStampFile(join(mxOutputDir, 'netbeans-config.zip'))
    configLibsZip = join(mxOutputDir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    if _check_ide_timestamp(suite, configZip, 'netbeans'):
        mx.logv('[NetBeans configurations are up to date - skipping]')
        return

    files = []
    libFiles = []
    jdks = set()
    for p in suite.projects:
        if not p.isJavaProject():
            continue

        if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
            continue

        includedInDists = [d for d in suite.dists if p in d.archived_deps()]
        _netbeansinit_project(p, jdks, files, libFiles, includedInDists)
    mx.log('If using NetBeans:')
    # http://stackoverflow.com/questions/24720665/cant-resolve-jdk-internal-package
    mx.log('  1. Edit etc/netbeans.conf in your NetBeans installation and modify netbeans_default_options variable to include "-J-DCachingArchiveProvider.disableCtSym=true"')
    mx.log('  2. Ensure that the following platform(s) are defined (Tools -> Java Platforms):')
    for jdk in jdks:
        mx.log('        JDK_' + str(jdk.version))
    mx.log('  3. Open/create a Project Group for the directory containing the projects (File -> Project Group -> New Group... -> Folder of Projects)')

    _zip_files(files, suite.dir, configZip.path)
    _zip_files(libFiles, suite.dir, configLibsZip)


# IntelliJ SDK types.
intellij_java_sdk_type = 'JavaSDK'
intellij_python_sdk_type = 'Python SDK'
intellij_ruby_sdk_type = 'RUBY_SDK'


@mx.command('mx', 'intellijinit')
def intellijinit_cli(args):
    """(re)generate Intellij project configurations"""
    parser = ArgumentParser(prog='mx ideinit')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate projects for the mx python projects.')
    parser.add_argument('--no-external-projects', action='store_false', dest='externalProjects', help='Do not generate external projects.')
    parser.add_argument('--no-java-projects', '--mx-python-modules-only', action='store_false', dest='javaModules', help='Do not generate projects for the java projects.')
    parser.add_argument('--native-projects', action='store_true', dest='nativeProjects', help='Generate native projects.')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)
    intellijinit(args.remainder, mx_python_modules=args.pythonProjects, java_modules=args.javaModules,
                 generate_external_projects=args.externalProjects, native_projects=args.nativeProjects)


def intellijinit(args, refreshOnly=False, doFsckProjects=True, mx_python_modules=True, java_modules=True,
                 generate_external_projects=True, native_projects=False):
    # In a multiple suite context, the .idea directory in each suite
    # has to be complete and contain information that is repeated
    # in dependent suites.
    declared_modules = set()
    referenced_modules = set()
    sdks = intellij_read_sdks()
    for suite in mx.suites(True) + ([mx._mx_suite] if mx_python_modules else []):
        _intellij_suite(args, suite, declared_modules, referenced_modules, sdks, refreshOnly, mx_python_modules,
                        generate_external_projects, java_modules and not suite.isBinarySuite(), suite != mx.primary_suite(),
                        generate_native_projects=native_projects)

    if len(referenced_modules - declared_modules) != 0:
        mx.abort('Some referenced modules are missing from modules.xml: {}'.format(referenced_modules - declared_modules))

    if mx_python_modules:
        # mx module
        moduleXml = mx.XMLDoc()
        moduleXml.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        moduleXml.element('exclude-output')
        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$', 'isTestSource': 'false'})
        for d in set((p.subDir for p in mx._mx_suite.projects if p.subDir)):
            moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + d})
        if dirname(mx._mx_suite.get_output_root()) == mx._mx_suite.dir:
            moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + basename(mx._mx_suite.get_output_root())})
        moduleXml.close('content')
        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
        moduleXml.close('component')
        moduleXml.close('module')
        mxModuleFile = join(mx._mx_suite.dir, basename(mx._mx_suite.dir) + '.iml')
        mx.update_file(mxModuleFile, moduleXml.xml(indent='  ', newl='\n'))

    if doFsckProjects and not refreshOnly:
        fsckprojects([])

def intellij_read_sdks():
    sdks = dict()
    if mx.is_linux() or mx.is_openbsd() or mx.is_sunos() or mx.is_windows():
        xmlSdks = glob.glob(os.path.expanduser("~/.IdeaIC*/config/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/.IntelliJIdea*/config/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/.config/JetBrains/IdeaIC*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/.config/JetBrains/IntelliJIdea*/options/jdk.table.xml"))
    elif mx.is_darwin():
        xmlSdks = \
          glob.glob(os.path.expanduser("~/Library/Application Support/JetBrains/IdeaIC*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/Library/Application Support/JetBrains/IntelliJIdea*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/Library/Preferences/IdeaIC*/options/jdk.table.xml")) + \
          glob.glob(os.path.expanduser("~/Library/Preferences/IntelliJIdea*/options/jdk.table.xml"))
    else:
        mx.warn("Location of IntelliJ SDK definitions on {} is unknown".format(mx.get_os()))
        return sdks
    if len(xmlSdks) == 0:
        mx.warn("IntelliJ SDK definitions not found")
        return sdks

    verRE = re.compile(r'^.*[/\\]\.?(IntelliJIdea|IdeaIC)([^/\\]+)[/\\].*$')
    def verSort(path):
        match = verRE.match(path)
        return match.group(2) + (".a" if match.group(1) == "IntellijIC" else ".b")

    xmlSdks.sort(key=verSort)
    xmlSdk = xmlSdks[-1]  # Pick the most recent IntelliJ version, preferring Ultimate over Community edition.
    mx.log("Using SDK definitions from {}".format(xmlSdk))

    versionRegexes = {}
    versionRegexes[intellij_java_sdk_type] = re.compile(r'^java\s+version\s+"([^"]+)"$|^([\d._]+)$')
    versionRegexes[intellij_python_sdk_type] = re.compile(r'^Python\s+(.+)$')
    # Examples:
    #   truffleruby 19.2.0-dev-2b2a7f81, like ruby 2.6.2, Interpreted JVM [x86_64-linux]
    #   ver.2.2.4p230 ( revision 53155) p230
    versionRegexes[intellij_ruby_sdk_type] = re.compile(r'^\D*(\d[^ ,]+)')

    for sdk in etreeParse(xmlSdk).getroot().findall("component[@name='ProjectJdkTable']/jdk[@version='2']"):
        name = sdk.find("name").get("value")
        kind = sdk.find("type").get("value")
        home = realpath(os.path.expanduser(sdk.find("homePath").get("value").replace('$USER_HOME$', '~')))
        if home.find('$APPLICATION_HOME_DIR$') != -1:
            # Don't know how to convert this into a real path so ignore it
            continue
        versionRE = versionRegexes.get(kind)
        if not versionRE or sdk.find("version") is None:
            # ignore unknown kinds
            continue

        match = versionRE.match(sdk.find("version").get("value"))
        if match:
            version = match.group(1)
            sdks[home] = {'name': name, 'type': kind, 'version': version}
            mx.logv("Found SDK {} with values {}".format(home, sdks[home]))
        else:
            mx.warn("Couldn't understand Java version specification \"{}\" for {} in {}".format(sdk.find("version").get("value"), home, xmlSdk))
    return sdks

def intellij_get_java_sdk_name(sdks, jdk):
    if jdk.home in sdks:
        sdk = sdks[jdk.home]
        if sdk['type'] == intellij_java_sdk_type:
            return sdk['name']
    return str(jdk.javaCompliance)

def intellij_get_python_sdk_name(sdks):
    exe = realpath(sys.executable)
    if exe in sdks:
        sdk = sdks[exe]
        if sdk['type'] == intellij_python_sdk_type:
            return sdk['name']
    return "Python {v[0]}.{v[1]} ({exe})".format(v=sys.version_info, exe=exe)

def intellij_get_ruby_sdk_name(sdks):
    for sdk in sdks.values():
        if sdk['type'] == intellij_ruby_sdk_type and 'truffleruby-jvm' in sdk['name']:
            return sdk['name']
    for sdk in sdks.values():
        if sdk['type'] == intellij_ruby_sdk_type:
            return sdk['name']
    return "truffleruby"

_not_intellij_filename = re.compile(r'[^a-zA-Z0-9]')

def _intellij_library_file_name(library_name, unique_library_file_names):
    def _gen_name(n=None):
        suffix = '' if n is None else str(n)
        return _not_intellij_filename.sub('_', library_name) + suffix + '.xml'

    # Find a unique name like intellij does
    file_name = _gen_name()
    i = 2
    while file_name in unique_library_file_names:
        file_name = _gen_name(i)
        i += 1

    unique_library_file_names.add(file_name)
    return file_name


def _intellij_suite(args, s, declared_modules, referenced_modules, sdks, refreshOnly=False, mx_python_modules=False,
                    generate_external_projects=True, java_modules=True, module_files_only=False, generate_native_projects=False):
    libraries = set()
    jdk_libraries = set()

    ideaProjectDirectory = join(s.dir, '.idea')

    modulesXml = mx.XMLDoc()
    if not module_files_only and not s.isBinarySuite():
        mx.ensure_dir_exists(ideaProjectDirectory)
        nameFile = join(ideaProjectDirectory, '.name')
        mx.update_file(nameFile, s.name)
        modulesXml.open('project', attributes={'version': '4'})
        modulesXml.open('component', attributes={'name': 'ProjectModuleManager'})
        modulesXml.open('modules')


    def _intellij_exclude_if_exists(xml, p, name, output=False):
        root = p.get_output_root() if output else p.dir
        path = join(root, name)
        if exists(path):
            excludeRoot = p.get_output_root() if output else '$MODULE_DIR$'
            excludePath = join(excludeRoot, name)
            xml.element('excludeFolder', attributes={'url':'file://' + excludePath})

    annotationProcessorProfiles = {}

    def _complianceToIntellijLanguageLevel(compliance):
        # they changed the name format starting with JDK_10
        if compliance.value >= 10:
            # Lastest Idea 2018.2 only understands JDK_11 so clamp at that value
            return 'JDK_' + str(min(compliance.value, 11))
        return 'JDK_1_' + str(compliance.value)

    def _intellij_external_project(externalProjects, sdks, host):
        if externalProjects:
            for project_name, project_definition in externalProjects.items():
                if not project_definition.get('path', None):
                    mx.abort("external project {} is missing path attribute".format(project_name))
                if not project_definition.get('type', None):
                    mx.abort("external project {} is missing type attribute".format(project_name))

                supported = ['path', 'type', 'source', 'test', 'excluded', 'load_path']
                unknown = set(project_definition.keys()) - frozenset(supported)
                if unknown:
                    mx.abort("There are unsupported {} keys in {} external project".format(unknown, project_name))

                path = os.path.realpath(join(host.dir, project_definition["path"]))
                module_type = project_definition["type"]

                moduleXml = mx.XMLDoc()
                moduleXml.open('module',
                               attributes={'type': {'ruby': 'RUBY_MODULE',
                                                    'python': 'PYTHON_MODULE',
                                                    'web': 'WEB_MODULE'}.get(module_type, 'UKNOWN_MODULE'),
                                           'version': '4'})
                moduleXml.open('component',
                               attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
                moduleXml.element('exclude-output')

                moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
                for name in project_definition.get('source', []):
                    moduleXml.element('sourceFolder',
                                      attributes={'url':'file://$MODULE_DIR$/' + name, 'isTestSource': str(False)})
                for name in project_definition.get('test', []):
                    moduleXml.element('sourceFolder',
                                      attributes={'url':'file://$MODULE_DIR$/' + name, 'isTestSource': str(True)})
                for name in project_definition.get('excluded', []):
                    _intellij_exclude_if_exists(moduleXml, type('', (object,), {"dir": path})(), name)
                moduleXml.close('content')

                if module_type == "ruby":
                    moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_ruby_sdk_type, 'jdkName': intellij_get_ruby_sdk_name(sdks)})
                elif module_type == "python":
                    moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
                elif module_type == "web":
                    # nothing to do
                    pass
                else:
                    mx.abort("External project type {} not supported".format(module_type))

                moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
                moduleXml.close('component')

                load_paths = project_definition.get('load_path', [])
                if load_paths:
                    if not module_type == "ruby":
                        mx.abort("load_path is supported only for ruby type external project")
                    moduleXml.open('component', attributes={'name': 'RModuleSettingsStorage'})
                    load_paths_attributes = {}
                    load_paths_attributes['number'] = str(len(load_paths))
                    for i, name in enumerate(load_paths):
                        load_paths_attributes["string" + str(i)] = "$MODULE_DIR$/" + name
                    moduleXml.element('LOAD_PATH', load_paths_attributes)
                    moduleXml.close('component')

                moduleXml.close('module')
                moduleFile = join(path, project_name + '.iml')
                mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

                if not module_files_only:
                    declared_modules.add(project_name)
                    moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                    modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

    if generate_external_projects:
        for p in s.projects_recursive() + mx._mx_suite.projects_recursive():
            _intellij_external_project(getattr(p, 'externalProjects', None), sdks, p)

    max_checkstyle_version = None
    compilerXml = None

    if java_modules:
        if not module_files_only:
            compilerXml = mx.XMLDoc()
            compilerXml.open('project', attributes={'version': '4'})

        # The IntelliJ parser seems to mishandle empty ADDITIONAL_OPTIONS_OVERRIDE elements
        # so only emit the section if there will be something in it.
        additionalOptionsOverrides = False
        assert not s.isBinarySuite()
        # create the modules (1 IntelliJ module = 1 mx project/distribution)
        for p in s.projects_recursive() + mx._mx_suite.projects_recursive():
            if not p.isJavaProject():
                continue

            jdk = mx.get_jdk(p.javaCompliance)
            assert jdk

            mx.ensure_dir_exists(p.dir)

            processors = p.annotation_processors()
            if processors:
                annotationProcessorProfiles.setdefault((p.source_gen_dir_name(),) + tuple(processors), []).append(p)

            intellijLanguageLevel = _complianceToIntellijLanguageLevel(p.javaCompliance)

            moduleXml = mx.XMLDoc()
            moduleXml.open('module', attributes={'type': 'JAVA_MODULE', 'version': '4'})

            moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'LANGUAGE_LEVEL': intellijLanguageLevel, 'inherit-compiler-output': 'false'})
            moduleXml.element('output', attributes={'url': 'file://$MODULE_DIR$/' + p.output_dir(relative=True)})

            moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
            for src in p.srcDirs:
                srcDir = join(p.dir, src)
                mx.ensure_dir_exists(srcDir)
                moduleXml.element('sourceFolder', attributes={'url':'file://$MODULE_DIR$/' + src, 'isTestSource': str(p.is_test_project())})
            for name in ['.externalToolBuilders', '.settings', 'nbproject']:
                _intellij_exclude_if_exists(moduleXml, p, name)
            moduleXml.close('content')

            if processors:
                moduleXml.open('content', attributes={'url': 'file://' + p.get_output_root()})
                genDir = p.source_gen_dir()
                mx.ensure_dir_exists(genDir)
                moduleXml.element('sourceFolder', attributes={'url':'file://' + p.source_gen_dir(), 'isTestSource': str(p.is_test_project()), 'generated': 'true'})
                for name in [basename(p.output_dir())]:
                    _intellij_exclude_if_exists(moduleXml, p, name, output=True)
                moduleXml.close('content')

            moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

            proj = p

            dependencies_project_packages = set()

            def should_process_dep(dep, edge):
                if dep.isTARDistribution() or dep.isNativeProject() or dep.isArchivableProject() or dep.isResourceLibrary():
                    mx.logv("Ignoring dependency from {} to {}".format(proj.name, dep.name))
                    return False
                return True

            def process_dep(dep, edge):
                if dep is proj:
                    return
                if dep.isLibrary() or dep.isJARDistribution() or dep.isMavenProject():
                    libraries.add(dep)
                    moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                elif dep.isJavaProject():
                    dependencies_project_packages.update(dep.defined_java_packages())
                    referenced_modules.add(dep.name)
                    moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': dep.name})
                elif dep.isJdkLibrary():
                    jdk_libraries.add(dep)
                    if jdk.javaCompliance < dep.jdkStandardizedSince:
                        moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                    else:
                        mx.logv("{} skipping {} for {}".format(p, dep, jdk)) #pylint: disable=undefined-loop-variable
                elif dep.isJreLibrary():
                    pass
                elif dep.isClasspathDependency():
                    moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
                else:
                    mx.abort("Dependency not supported: {0} ({1})".format(dep, dep.__class__.__name__))

            p.walk_deps(preVisit=should_process_dep, visit=process_dep, ignoredEdges=[mx.DEP_EXCLUDED])

            moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_java_sdk_type, 'jdkName': intellij_get_java_sdk_name(sdks, jdk)})

            moduleXml.close('component')

            if compilerXml and jdk.javaCompliance >= '9':
                moduleDeps = p.get_concealed_imported_packages(jdk=jdk)
                if moduleDeps:
                    exports = sorted([(m, pkgs) for m, pkgs in moduleDeps.items() if dependencies_project_packages.isdisjoint(pkgs)])
                    if exports:
                        args = []
                        exported_modules = set()
                        for m, pkgs in exports:
                            args += ['--add-exports={}/{}=ALL-UNNAMED'.format(m, pkg) for pkg in pkgs]
                            exported_modules.add(m)
                        roots = set(jdk.get_root_modules())
                        observable_modules = jdk.get_modules()
                        default_module_graph = mx.get_transitive_closure(roots, observable_modules)
                        module_graph = mx.get_transitive_closure(roots | exported_modules, observable_modules)
                        extra_modules = module_graph - default_module_graph
                        if extra_modules:
                            args.append('--add-modules=' + ','.join((m.name for m in extra_modules)))
                        if not additionalOptionsOverrides:
                            additionalOptionsOverrides = True
                            compilerXml.open('component', {'name': 'JavacSettings'})
                            compilerXml.open('option', {'name': 'ADDITIONAL_OPTIONS_OVERRIDE'})
                        compilerXml.element('module', {'name': p.name, 'options': ' '.join(args)})

            # Checkstyle
            csConfig, checkstyleVersion, checkstyleProj = p.get_checkstyle_config()
            if csConfig:
                max_checkstyle_version = max(max_checkstyle_version, mx.VersionSpec(checkstyleVersion)) if max_checkstyle_version else mx.VersionSpec(checkstyleVersion)

                moduleXml.open('component', attributes={'name': 'CheckStyle-IDEA-Module'})
                moduleXml.open('option', attributes={'name': 'configuration'})
                moduleXml.open('map')
                moduleXml.element('entry', attributes={'key': "checkstyle-version", 'value': checkstyleVersion})
                moduleXml.element('entry', attributes={'key': "active-configuration", 'value': "PROJECT_RELATIVE:" + join(checkstyleProj.dir, ".checkstyle_checks.xml") + ":" + checkstyleProj.name})
                moduleXml.close('map')
                moduleXml.close('option')
                moduleXml.close('component')

            moduleXml.close('module')
            moduleFile = join(p.dir, p.name + '.iml')
            mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

            if not module_files_only:
                declared_modules.add(p.name)
                moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})
        if additionalOptionsOverrides:
            compilerXml.close('option')
            compilerXml.close('component')

    if mx_python_modules:
        # mx.<suite> python module:
        moduleXml = mx.XMLDoc()
        moduleXml.open('module', attributes={'type': 'PYTHON_MODULE', 'version': '4'})
        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'true'})
        moduleXml.element('exclude-output')
        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$', 'isTestSource': 'false'})
        for d in os.listdir(s.mxDir):
            directory = join(s.mxDir, d)
            if isdir(directory) and mx.dir_contains_files_recursively(directory, r".*\.java"):
                moduleXml.element('excludeFolder', attributes={'url': 'file://$MODULE_DIR$/' + d})
        moduleXml.close('content')
        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': intellij_python_sdk_type, 'jdkName': intellij_get_python_sdk_name(sdks)})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})
        processes_suites = {s.name}

        def _mx_projects_suite(visited_suite, suite_import):
            if suite_import.name in processes_suites:
                return
            processes_suites.add(suite_import.name)
            dep_suite = mx.suite(suite_import.name)
            moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': basename(dep_suite.mxDir)})
            moduleFile = join(dep_suite.mxDir, basename(dep_suite.mxDir) + '.iml')
            if not module_files_only:
                declared_modules.add(basename(dep_suite.mxDir))
                moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
                modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})
            dep_suite.visit_imports(_mx_projects_suite)
        s.visit_imports(_mx_projects_suite)
        moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': 'mx'})
        moduleXml.close('component')
        moduleXml.close('module')
        moduleFile = join(s.mxDir, basename(s.mxDir) + '.iml')
        mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))
        if not module_files_only:
            declared_modules.add(basename(s.mxDir))
            moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

            declared_modules.add(basename(mx._mx_suite.dir))
            mxModuleFile = join(mx._mx_suite.dir, basename(mx._mx_suite.dir) + '.iml')
            mxModuleFilePath = "$PROJECT_DIR$/" + os.path.relpath(mxModuleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + mxModuleFilePath, 'filepath': mxModuleFilePath})

    if generate_native_projects:
        _intellij_native_projects(s, module_files_only, declared_modules, modulesXml)

    if generate_external_projects:
        _intellij_external_project(s.suiteDict.get('externalProjects', None), sdks, s)

    if not module_files_only:
        modulesXml.close('modules')
        modulesXml.close('component')
        modulesXml.close('project')
        moduleXmlFile = join(ideaProjectDirectory, 'modules.xml')
        mx.update_file(moduleXmlFile, modulesXml.xml(indent='  ', newl='\n'))

    if java_modules and not module_files_only:
        unique_library_file_names = set()
        librariesDirectory = join(ideaProjectDirectory, 'libraries')

        mx.ensure_dir_exists(librariesDirectory)

        def make_library(name, path, source_path, suite_dir):
            libraryXml = mx.XMLDoc()

            libraryXml.open('component', attributes={'name': 'libraryTable'})
            libraryXml.open('library', attributes={'name': name})
            libraryXml.open('CLASSES')
            pathX = mx.relpath_or_absolute(path, suite_dir, prefix='$PROJECT_DIR$')
            libraryXml.element('root', attributes={'url': 'jar://' + pathX + '!/'})
            libraryXml.close('CLASSES')
            libraryXml.element('JAVADOC')
            if sourcePath:
                libraryXml.open('SOURCES')
                if os.path.isdir(sourcePath):
                    sourcePathX = mx.relpath_or_absolute(sourcePath, suite_dir, prefix='$PROJECT_DIR$')
                    libraryXml.element('root', attributes={'url': 'file://' + sourcePathX})
                else:
                    source_pathX = mx.relpath_or_absolute(source_path, suite_dir, prefix='$PROJECT_DIR$')
                    libraryXml.element('root', attributes={'url': 'jar://' + source_pathX + '!/'})
                libraryXml.close('SOURCES')
            else:
                libraryXml.element('SOURCES')
            libraryXml.close('library')
            libraryXml.close('component')

            libraryFile = join(librariesDirectory, _intellij_library_file_name(name, unique_library_file_names))
            return mx.update_file(libraryFile, libraryXml.xml(indent='  ', newl='\n'))

        # Setup the libraries that were used above
        for library in libraries:
            sourcePath = None
            if library.isLibrary():
                path = library.get_path(True)
                if library.sourcePath:
                    sourcePath = library.get_source_path(True)
            elif library.isMavenProject():
                path = library.get_path(True)
                sourcePath = library.get_source_path(True)
            elif library.isJARDistribution():
                path = library.path
                if library.sourcesPath:
                    sourcePath = library.sourcesPath
            elif library.isClasspathDependency():
                path = library.classpath_repr()
            else:
                mx.abort('Dependency not supported: {} ({})'.format(library.name, library.__class__.__name__))
            make_library(library.name, path, sourcePath, s.dir)

        jdk = mx.get_jdk()
        updated = False
        for library in jdk_libraries:
            if library.classpath_repr(jdk) is not None:
                if make_library(library.name, library.classpath_repr(jdk), library.get_source_path(jdk), s.dir):
                    updated = True
        if jdk_libraries and updated:
            mx.log("Setting up JDK libraries using {0}".format(jdk))

        # Set annotation processor profiles up, and link them to modules in compiler.xml

        compilerXml.open('component', attributes={'name': 'CompilerConfiguration'})

        compilerXml.element('option', attributes={'name': "DEFAULT_COMPILER", 'value': 'Javac'})
        # using the --release option with javac interferes with using --add-modules which is required for some projects
        compilerXml.element('option', attributes={'name': "USE_RELEASE_OPTION", 'value': 'false'})
        compilerXml.element('resourceExtensions')
        compilerXml.open('wildcardResourcePatterns')
        compilerXml.element('entry', attributes={'name': '!?*.java'})
        compilerXml.close('wildcardResourcePatterns')
        if annotationProcessorProfiles:
            compilerXml.open('annotationProcessing')
            for t, modules in sorted(annotationProcessorProfiles.items()):
                source_gen_dir = t[0]
                processors = t[1:]
                compilerXml.open('profile', attributes={'default': 'false', 'name': '-'.join([ap.name for ap in processors]) + "-" + source_gen_dir, 'enabled': 'true'})
                compilerXml.element('sourceOutputDir', attributes={'name': join(os.pardir, source_gen_dir)})
                compilerXml.element('sourceTestOutputDir', attributes={'name': join(os.pardir, source_gen_dir)})
                compilerXml.open('processorPath', attributes={'useClasspath': 'false'})

                # IntelliJ supports both directories and jars on the annotation processor path whereas
                # Eclipse only supports jars.
                for apDep in processors:
                    def processApDep(dep, edge):
                        if dep.isLibrary() or dep.isJARDistribution():
                            compilerXml.element('entry', attributes={'name': mx.relpath_or_absolute(dep.path, s.dir, prefix='$PROJECT_DIR$')})
                        elif dep.isProject():
                            compilerXml.element('entry', attributes={'name': mx.relpath_or_absolute(dep.output_dir(), s.dir, prefix='$PROJECT_DIR$')})
                    apDep.walk_deps(visit=processApDep)
                compilerXml.close('processorPath')
                for module in modules:
                    compilerXml.element('module', attributes={'name': module.name})
                compilerXml.close('profile')
            compilerXml.close('annotationProcessing')

        compilerXml.close('component')

    if compilerXml:
        compilerXml.close('project')
        compilerFile = join(ideaProjectDirectory, 'compiler.xml')
        mx.update_file(compilerFile, compilerXml.xml(indent='  ', newl='\n'))

    if not module_files_only:
        # Write misc.xml for global JDK config
        miscXml = mx.XMLDoc()
        miscXml.open('project', attributes={'version' : '4'})

        if java_modules:
            mainJdk = mx.get_jdk()
            miscXml.open('component', attributes={'name' : 'ProjectRootManager', 'version': '2', 'languageLevel': _complianceToIntellijLanguageLevel(mainJdk.javaCompliance), 'project-jdk-name': intellij_get_java_sdk_name(sdks, mainJdk), 'project-jdk-type': intellij_java_sdk_type})
            miscXml.element('output', attributes={'url' : 'file://$PROJECT_DIR$/' + os.path.relpath(s.get_output_root(), s.dir)})
            miscXml.close('component')
        else:
            miscXml.element('component', attributes={'name' : 'ProjectRootManager', 'version': '2', 'project-jdk-name': intellij_get_python_sdk_name(sdks), 'project-jdk-type': intellij_python_sdk_type})

        miscXml.close('project')
        miscFile = join(ideaProjectDirectory, 'misc.xml')
        mx.update_file(miscFile, miscXml.xml(indent='  ', newl='\n'))

        # Generate a default configuration for debugging Graal
        runConfig = mx.XMLDoc()
        runConfig.open('component', attributes={'name' : 'ProjectRunConfigurationManager'})
        runConfig.open('configuration', attributes={'default' :'false', 'name' : 'GraalDebug', 'type' : 'Remote', 'factoryName': 'Remote'})
        runConfig.element('option', attributes={'name' : 'USE_SOCKET_TRANSPORT', 'value' : 'true'})
        runConfig.element('option', attributes={'name' : 'SERVER_MODE', 'value' : 'false'})
        runConfig.element('option', attributes={'name' : 'SHMEM_ADDRESS', 'value' : 'javadebug'})
        runConfig.element('option', attributes={'name' : 'HOST', 'value' : 'localhost'})
        runConfig.element('option', attributes={'name' : 'PORT', 'value' : '8000'})
        runConfig.open('RunnerSettings', attributes={'RunnerId' : 'Debug'})
        runConfig.element('option', attributes={'name' : 'DEBUG_PORT', 'value' : '8000'})
        runConfig.element('option', attributes={'name' : 'LOCAL', 'value' : 'false'})
        runConfig.close('RunnerSettings')
        runConfig.element('method')
        runConfig.close('configuration')
        runConfig.close('component')
        runConfigFile = join(ideaProjectDirectory, 'runConfigurations', 'GraalDebug.xml')
        mx.ensure_dir_exists(join(ideaProjectDirectory, 'runConfigurations'))
        mx.update_file(runConfigFile, runConfig.xml(indent='  ', newl='\n'))

        if java_modules:
            # Eclipse formatter config
            corePrefsSources = s.eclipse_settings_sources().get('org.eclipse.jdt.core.prefs')
            uiPrefsSources = s.eclipse_settings_sources().get('org.eclipse.jdt.ui.prefs')
            if corePrefsSources:
                miscXml = mx.XMLDoc()
                miscXml.open('project', attributes={'version' : '4'})
                out = mx.StringIO()
                print('# GENERATED -- DO NOT EDIT', file=out)
                for source in corePrefsSources:
                    print('# Source:', source, file=out)
                    with open(source) as fileName:
                        for line in fileName:
                            if line.startswith('org.eclipse.jdt.core.formatter.'):
                                print(line.strip(), file=out)
                formatterConfigFile = join(ideaProjectDirectory, 'EclipseCodeFormatter.prefs')
                mx.update_file(formatterConfigFile, out.getvalue())
                importConfigFile = None
                if uiPrefsSources:
                    out = mx.StringIO()
                    print('# GENERATED -- DO NOT EDIT', file=out)
                    for source in uiPrefsSources:
                        print('# Source:', source, file=out)
                        with open(source) as fileName:
                            for line in fileName:
                                if line.startswith('org.eclipse.jdt.ui.importorder') \
                                        or line.startswith('org.eclipse.jdt.ui.ondemandthreshold') \
                                        or line.startswith('org.eclipse.jdt.ui.staticondemandthreshold'):
                                    print(line.strip(), file=out)
                    importConfigFile = join(ideaProjectDirectory, 'EclipseImports.prefs')
                    mx.update_file(importConfigFile, out.getvalue())
                miscXml.open('component', attributes={'name' : 'EclipseCodeFormatterProjectSettings'})
                miscXml.open('option', attributes={'name' : 'projectSpecificProfile'})
                miscXml.open('ProjectSpecificProfile')
                miscXml.element('option', attributes={'name' : 'formatter', 'value' : 'ECLIPSE'})
                custom_eclipse_exe = mx.get_env('ECLIPSE_EXE')
                if custom_eclipse_exe:
                    custom_eclipse = dirname(custom_eclipse_exe)
                    if mx.is_darwin():
                        custom_eclipse = join(dirname(custom_eclipse), 'Eclipse', 'plugins')
                    if not exists(custom_eclipse_exe):
                        mx.abort('Custom eclipse "{}" does not exist'.format(custom_eclipse_exe))
                    miscXml.element('option', attributes={'name' : 'eclipseVersion', 'value' : 'CUSTOM'})
                    miscXml.element('option', attributes={'name' : 'pathToEclipse', 'value' : custom_eclipse})
                miscXml.element('option', attributes={'name' : 'pathToConfigFileJava', 'value' : '$PROJECT_DIR$/.idea/' + basename(formatterConfigFile)})
                if importConfigFile:
                    miscXml.element('option', attributes={'name' : 'importOrderConfigFilePath', 'value' : '$PROJECT_DIR$/.idea/' + basename(importConfigFile)})
                    miscXml.element('option', attributes={'name' : 'importOrderFromFile', 'value' : 'true'})

                miscXml.close('ProjectSpecificProfile')
                miscXml.close('option')
                miscXml.close('component')
                miscXml.close('project')
                miscFile = join(ideaProjectDirectory, 'eclipseCodeFormatter.xml')
                mx.update_file(miscFile, miscXml.xml(indent='  ', newl='\n'))

        if java_modules:
            # Write codestyle settings
            mx.ensure_dir_exists(join(ideaProjectDirectory, 'codeStyles'))

            codeStyleConfigXml = mx.XMLDoc()
            codeStyleConfigXml.open('component', attributes={'name': 'ProjectCodeStyleConfiguration'})
            codeStyleConfigXml.open('state')
            codeStyleConfigXml.element('option', attributes={'name': 'USE_PER_PROJECT_SETTINGS', 'value': 'true'})
            codeStyleConfigXml.close('state')
            codeStyleConfigXml.close('component')
            codeStyleConfigFile = join(ideaProjectDirectory, 'codeStyles', 'codeStyleConfig.xml')
            mx.update_file(codeStyleConfigFile, codeStyleConfigXml.xml(indent='  ', newl='\n'))

            codeStyleProjectXml = mx.XMLDoc()
            codeStyleProjectXml.open('component', attributes={'name': 'ProjectCodeStyleConfiguration'})
            codeStyleProjectXml.open('code_scheme', attributes={'name': 'Project', 'version': '173'})
            codeStyleProjectXml.open('JavaCodeStyleSettings')
            # We cannot entirely disable wildcards import, but we can set the threshold to an insane number.
            codeStyleProjectXml.element('option', attributes={'name': 'CLASS_COUNT_TO_USE_IMPORT_ON_DEMAND', 'value': '65536'})
            codeStyleProjectXml.element('option', attributes={'name': 'NAMES_COUNT_TO_USE_IMPORT_ON_DEMAND', 'value': '65536'})
            codeStyleProjectXml.close('JavaCodeStyleSettings')
            codeStyleProjectXml.close('code_scheme')
            codeStyleProjectXml.close('component')
            codeStyleProjectFile = join(ideaProjectDirectory, 'codeStyles', 'Project.xml')
            mx.update_file(codeStyleProjectFile, codeStyleProjectXml.xml(indent='  ', newl='\n'))

            # Write checkstyle-idea.xml for the CheckStyle-IDEA
            checkstyleXml = mx.XMLDoc()
            checkstyleXml.open('project', attributes={'version': '4'})
            checkstyleXml.open('component', attributes={'name': 'CheckStyle-IDEA'})
            checkstyleXml.open('option', attributes={'name' : "configuration"})
            checkstyleXml.open('map')

            if max_checkstyle_version:
                checkstyleXml.element('entry', attributes={'key': "checkstyle-version", 'value': str(max_checkstyle_version)})

            # Initialize an entry for each style that is used
            checkstyleConfigs = set([])
            for p in s.projects_recursive():
                if not p.isJavaProject():
                    continue
                csConfig, checkstyleVersion, checkstyleProj = p.get_checkstyle_config()
                if not csConfig or csConfig in checkstyleConfigs:
                    continue
                checkstyleConfigs.add(csConfig)
                checkstyleXml.element('entry', attributes={'key' : "location-" + str(len(checkstyleConfigs)), 'value': "PROJECT_RELATIVE:" + join(checkstyleProj.dir, ".checkstyle_checks.xml") + ":" + checkstyleProj.name})

            checkstyleXml.close('map')
            checkstyleXml.close('option')
            checkstyleXml.close('component')
            checkstyleXml.close('project')
            checkstyleFile = join(ideaProjectDirectory, 'checkstyle-idea.xml')
            mx.update_file(checkstyleFile, checkstyleXml.xml(indent='  ', newl='\n'))

            # mx integration
            def antTargetName(dist):
                return 'archive_' + dist.name

            def artifactFileName(dist):
                return dist.name.replace('.', '_').replace('-', '_') + '.xml'
            validDistributions = [dist for dist in mx.sorted_dists() if not dist.suite.isBinarySuite() and not dist.isTARDistribution()]

            # 1) Make an ant file for archiving the distributions.
            antXml = mx.XMLDoc()
            antXml.open('project', attributes={'name': s.name, 'default': 'archive'})
            for dist in validDistributions:
                antXml.open('target', attributes={'name': antTargetName(dist)})
                antXml.open('exec', attributes={'executable': sys.executable})
                antXml.element('arg', attributes={'value': join(mx._mx_home, 'mx.py')})
                antXml.element('arg', attributes={'value': 'archive'})
                antXml.element('arg', attributes={'value': '@' + dist.name})
                antXml.close('exec')
                antXml.close('target')

            antXml.close('project')
            antFile = join(ideaProjectDirectory, 'ant-mx-archive.xml')
            mx.update_file(antFile, antXml.xml(indent='  ', newl='\n'))

            # 2) Tell IDEA that there is an ant-build.
            ant_mx_archive_xml = 'file://$PROJECT_DIR$/.idea/ant-mx-archive.xml'
            metaAntXml = mx.XMLDoc()
            metaAntXml.open('project', attributes={'version': '4'})
            metaAntXml.open('component', attributes={'name': 'AntConfiguration'})
            metaAntXml.open('buildFile', attributes={'url': ant_mx_archive_xml})
            metaAntXml.close('buildFile')
            metaAntXml.close('component')
            metaAntXml.close('project')
            metaAntFile = join(ideaProjectDirectory, 'ant.xml')
            mx.update_file(metaAntFile, metaAntXml.xml(indent='  ', newl='\n'))

            # 3) Make an artifact for every distribution
            validArtifactNames = {artifactFileName(dist) for dist in validDistributions}
            artifactsDir = join(ideaProjectDirectory, 'artifacts')
            mx.ensure_dir_exists(artifactsDir)
            for fileName in os.listdir(artifactsDir):
                filePath = join(artifactsDir, fileName)
                if os.path.isfile(filePath) and fileName not in validArtifactNames:
                    os.remove(filePath)

            for dist in validDistributions:
                artifactXML = mx.XMLDoc()
                artifactXML.open('component', attributes={'name': 'ArtifactManager'})
                artifactXML.open('artifact', attributes={'build-on-make': 'true', 'name': dist.name})
                artifactXML.open('output-path', data='$PROJECT_DIR$/mxbuild/artifacts/' + dist.name)
                artifactXML.close('output-path')
                artifactXML.open('properties', attributes={'id': 'ant-postprocessing'})
                artifactXML.open('options', attributes={'enabled': 'true'})
                artifactXML.open('file', data=ant_mx_archive_xml)
                artifactXML.close('file')
                artifactXML.open('target', data=antTargetName(dist))
                artifactXML.close('target')
                artifactXML.close('options')
                artifactXML.close('properties')
                artifactXML.open('root', attributes={'id': 'root'})
                for javaProject in [dep for dep in dist.archived_deps() if dep.isJavaProject()]:
                    artifactXML.element('element', attributes={'id': 'module-output', 'name': javaProject.name})
                for javaProject in [dep for dep in dist.deps if dep.isLibrary() or dep.isDistribution()]:
                    artifactXML.element('element', attributes={'id': 'artifact', 'artifact-name': javaProject.name})
                artifactXML.close('root')
                artifactXML.close('artifact')
                artifactXML.close('component')

                artifactFile = join(artifactsDir, artifactFileName(dist))
                mx.update_file(artifactFile, artifactXML.xml(indent='  ', newl='\n'))

        def intellij_scm_name(vc_kind):
            if vc_kind == 'git':
                return 'Git'
            elif vc_kind == 'hg':
                return 'hg4idea'

        vcsXml = mx.XMLDoc()
        vcsXml.open('project', attributes={'version': '4'})
        vcsXml.open('component', attributes={'name': 'VcsDirectoryMappings'})

        suites_for_vcs = mx.suites() + ([mx._mx_suite] if mx_python_modules else [])
        sourceSuitesWithVCS = [vc_suite for vc_suite in suites_for_vcs if vc_suite.isSourceSuite() and vc_suite.vc is not None]
        uniqueSuitesVCS = {(vc_suite.vc_dir, vc_suite.vc.kind) for vc_suite in sourceSuitesWithVCS}
        for vcs_dir, kind in uniqueSuitesVCS:
            vcsXml.element('mapping', attributes={'directory': vcs_dir, 'vcs': intellij_scm_name(kind)})

        vcsXml.close('component')
        vcsXml.close('project')

        vcsFile = join(ideaProjectDirectory, 'vcs.xml')
        mx.update_file(vcsFile, vcsXml.xml(indent='  ', newl='\n'))

        # TODO look into copyright settings


def _intellij_native_projects(s, module_files_only, declared_modules, modulesXml):
    for p in s.projects_recursive() + mx._mx_suite.projects_recursive():
        if not p.isNativeProject():
            continue

        mx.ensure_dir_exists(p.dir)

        moduleXml = mx.XMLDoc()
        moduleXml.open('module', attributes={'type': 'CPP_MODULE'})

        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'inherit-compiler-output': 'false'})

        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        for src in p.srcDirs:
            srcDir = join(p.dir, src)
            mx.ensure_dir_exists(srcDir)
            moduleXml.element('sourceFolder', attributes={'url': 'file://$MODULE_DIR$/' + src,
                                                          'isTestSource': str(p.is_test_project())})
        moduleXml.close('content')

        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

        moduleXml.close('component')
        moduleXml.close('module')
        moduleFile = join(p.dir, p.name + '.iml')
        mx.update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

        if not module_files_only:
            declared_modules.add(p.name)
            moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, s.dir)
            modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

### ~~~~~~~~~~~~~ IDE, IntelliJ

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
            mx.log_error("Error removing {0}".format(p.name + '.jar'))

    for d in mx._dists.values():
        if not d.isJARDistribution():
            continue
        if d.get_ide_project_dir():
            shutil.rmtree(d.get_ide_project_dir(), ignore_errors=True)

def ideinit(args, refreshOnly=False, buildProcessorJars=True):
    """(re)generate IDE project configurations"""
    parser = ArgumentParser(prog='mx ideinit')
    parser.add_argument('--no-python-projects', action='store_false', dest='pythonProjects', help='Do not generate projects for the mx python projects.')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)
    mx_ide = os.environ.get('MX_IDE', 'all').lower()
    all_ides = mx_ide == 'all'
    if all_ides or mx_ide == 'eclipse':
        eclipseinit(args.remainder, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars, doFsckProjects=False, pythonProjects=args.pythonProjects)
    if all_ides or mx_ide == 'netbeans':
        netbeansinit(args.remainder, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars, doFsckProjects=False)
    if all_ides or mx_ide == 'intellij':
        intellijinit(args.remainder, refreshOnly=refreshOnly, doFsckProjects=False, mx_python_modules=args.pythonProjects)
    if not refreshOnly:
        fsckprojects([])

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
            elif dirpath == suite.get_output_root():
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
                    projectConfigFiles = frozenset(['.classpath', '.project', 'nbproject', maybe_project + '.iml'])
                    indicators = projectConfigFiles.intersection(files)
                    if len(indicators) != 0:
                        indicators = [os.path.relpath(join(dirpath, i), suite.vc_dir) for i in indicators]
                        indicatorsInVC = suite.vc.locate(suite.vc_dir, indicators)
                        # Only proceed if there are indicator files that are not under VC
                        if len(indicators) > len(indicatorsInVC):
                            if mx.ask_yes_no(dirpath + ' looks like a removed project -- delete it', 'n'):
                                shutil.rmtree(dirpath)
                                mx.log('Deleted ' + dirpath)
        ideaProjectDirectory = join(suite.dir, '.idea')
        librariesDirectory = join(ideaProjectDirectory, 'libraries')
        if exists(librariesDirectory):
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
            neededLibraryFiles = frozenset([_intellij_library_file_name(l.name, unique_library_file_names) for l in neededLibraries])
            existingLibraryFiles = frozenset(os.listdir(librariesDirectory))
            for library_file in existingLibraryFiles - neededLibraryFiles:
                file_path = join(librariesDirectory, library_file)
                relative_file_path = os.path.relpath(file_path, os.curdir)
                if mx.ask_yes_no(relative_file_path + ' looks like a removed library -- delete it', 'n'):
                    os.remove(file_path)
                    mx.log('Deleted ' + relative_file_path)

### ~~~~~~~~~~~~~ _private, eclipse

def _copy_eclipse_settings(p, files=None):
    processors = p.annotation_processors()

    settingsDir = join(p.dir, ".settings")
    mx.ensure_dir_exists(settingsDir)

    for name, sources in p.eclipse_settings_sources().items():
        out = mx.StringIO()
        print('# GENERATED -- DO NOT EDIT', file=out)
        for source in sources:
            print('# Source:', source, file=out)
            with open(source) as f:
                print(f.read(), file=out)
        if p.javaCompliance:
            jc = p.javaCompliance if p.javaCompliance.value < _max_Eclipse_JavaExecutionEnvironment else mx.JavaCompliance(_max_Eclipse_JavaExecutionEnvironment)
            content = out.getvalue().replace('${javaCompliance}', str(jc))
        else:
            content = out.getvalue()
        if processors:
            content = content.replace('org.eclipse.jdt.core.compiler.processAnnotations=disabled', 'org.eclipse.jdt.core.compiler.processAnnotations=enabled')
        mx.update_file(join(settingsDir, name), content)
        if files:
            files.append(join(settingsDir, name))
