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

__all__ = [
    "eclipseinit_and_format_files",
    "eclipseformat",
    "locate_eclipse_exe",
    "make_eclipse_attach",
    "make_eclipse_launch",
    "eclipseinit_cli",
    "eclipseinit",
    "EclipseLinkedResource",
    "get_eclipse_project_rel_locationURI",
    "RelevantResource",
    "IRESOURCE_FILE",
    "IRESOURCE_FOLDER",
    "generate_eclipse_workingsets",
]

import os, time, zipfile, tempfile
# TODO use defusedexpat?
import xml.parsers.expat, xml.sax.saxutils, xml.dom.minidom
from collections import namedtuple
from argparse import ArgumentParser, FileType
from contextlib import ExitStack
from os.path import join, basename, dirname, exists, isdir, abspath
from io import StringIO

from .ide import project_processor

from . import mx, mx_util
from . import mx_ideconfig
from . import mx_javamodules


def eclipseinit_and_format_files(eclipse_exe, config, files):
    """Wrapper for :func:`_format_files` that automatically initializes the workspace and eclipse ini
    with a temporary configuration"""

    wsroot = eclipseinit([], buildProcessorJars=False, doFsckProjects=False)
    with _TempEclipseIni(eclipse_exe) as tmp_eclipseini:
        _format_files(eclipse_exe, wsroot, tmp_eclipseini.name, config, files)


def _format_files(eclipse_exe, wsroot, eclipse_ini, config, files):
    """Formats a list of files with the given Eclipse instance

    :param eclipse_exe the eclipse executable to use for formatting
    :param wsroot an initialized eclipse workspace root
    :param eclipse_ini the eclipse ini configuration file to use
    :param config the JavaCodeFormatter config to use
    :param files a list of file paths to format
    """

    capture = mx.OutputCapture()
    jdk = mx.get_jdk()
    rc = mx.run([eclipse_exe,
                 '--launcher.ini', eclipse_ini,
                 '-nosplash',
                 '-application',
                 '-consolelog',
                 '-data', wsroot,
                 '-vm', jdk.java,
                 'org.eclipse.jdt.core.JavaCodeFormatter',
                 '-config', config]
                + files, out=capture, err=capture, nonZeroIsFatal=False)
    if rc != 0:
        mx.log(capture.data)
        mx.abort("Error while running formatter")


class _TempEclipseIni:
    """Context manager that initializes a temporary eclipse ini file for the given eclipse executable.
    Upon exit, the temporary configuration file is automatically removed."""

    def __init__(self, eclipse_exe):
        self.eclipse_exe = eclipse_exe
        self.tmp_eclipseini = tempfile.NamedTemporaryFile(mode='w')

    def __enter__(self):
        # Use an ExitStack to make sure that the NamedTemporaryFile is closed in case
        # there is an exception while writing its content
        with ExitStack() as stack:
            stack.enter_context(self.tmp_eclipseini)
            with open(join(dirname(self.eclipse_exe),
                           join('..', 'Eclipse', 'eclipse.ini') if mx.is_darwin() else 'eclipse.ini'), 'r') as src:
                locking_added = False
                for line in src.readlines():
                    self.tmp_eclipseini.write(line)
                    if line.strip() == '-vmargs':
                        self.tmp_eclipseini.write('-Dosgi.locking=none\n')
                        locking_added = True
                if not locking_added:
                    self.tmp_eclipseini.write('-vmargs\n-Dosgi.locking=none\n')
            self.tmp_eclipseini.flush()

            # Everything went fine, we will close the NamedTemporaryFile in our own exit method
            stack.pop_all()
            return self.tmp_eclipseini

    def __exit__(self, *args):
        self.tmp_eclipseini.__exit__(*args)


@mx.command('mx', 'eclipseformat')
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
    parser.add_argument('--filelist', type=FileType("r"), help='only format the files listed in the given file')

    args = parser.parse_args(args)
    if args.restore:
        args.backup = False

    eclipse_exe = locate_eclipse_exe(args.eclipse_exe)

    if eclipse_exe is None:
        mx.abort('Could not find Eclipse executable. Use -e option or ensure ECLIPSE_EXE environment variable is set.')

    filelist = None
    if args.filelist:
        filelist = [abspath(line.strip()) for line in args.filelist.readlines()]
        args.filelist.close()

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
                self.cachedHash = (self.read_core_prefs_file(), self.removeTrailingWhitespace).__hash__()
            return self.cachedHash

        def __eq__(self, other):
            if not isinstance(other, Batch):
                return False
            if self.removeTrailingWhitespace != other.removeTrailingWhitespace:
                return False
            if self.path == other.path:
                return True
            return self.read_core_prefs_file() == other.read_core_prefs_file()

        def read_core_prefs_file(self):
            with open(self.path) as fp:
                content = fp.read()
                # processAnnotations does not matter for eclipseformat, ignore its value as otherwise we would create extra batches and slow down eclipseformat
                content = content.replace('org.eclipse.jdt.core.compiler.processAnnotations=disabled\n', '').replace('org.eclipse.jdt.core.compiler.processAnnotations=enabled\n', '')
                return content

    modified = list()
    batches = dict()  # all sources with the same formatting settings are formatted together
    for p in projectsToProcess:
        if not p.isJavaProject():
            continue
        sourceDirs = p.source_dirs()

        batch = Batch(join(p.dir, '.settings'))

        if not exists(batch.path):
            if mx._opts.verbose:
                mx.log(f'[no Eclipse Code Formatter preferences at {batch.path} - skipping]')
            continue

        javafiles = []
        for sourceDir in sourceDirs:
            for root, _, files in os.walk(sourceDir):
                for f in [join(root, name) for name in files if name.endswith('.java')]:
                    if filelist is None or f in filelist:
                        javafiles.append(mx.FileInfo(f))
        if len(javafiles) == 0:
            mx.logv(f'[no Java sources in {p.name} - skipping]')
            continue

        res = batches.setdefault(batch, javafiles)
        if res is not javafiles:
            res.extend(javafiles)

    mx.log("we have: " + str(len(batches)) + " batches")
    batch_num = 0
    for batch, javafiles in batches.items():
        batch_num += 1
        mx.log(f"Processing batch {batch_num} ({len(javafiles)} files)...")

        with _TempEclipseIni(eclipse_exe) as tmp_eclipseini:
            for chunk in mx._chunk_files_for_command_line(javafiles, pathFunction=lambda f: f.path):
                _format_files(eclipse_exe, wsroot, tmp_eclipseini.name, batch.path, [f.path for f in chunk])
                for fi in chunk:
                    if fi.update(batch.removeTrailingWhitespace, args.restore):
                        modified.append(fi)

    mx.log(f'{len(modified)} files were modified')

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
            mx.log(f' - {name}')
            mx.log('Changes:')
            mx.log(diffs)
            if args.backup:
                arcname = name.replace(os.sep, '/')
                zf.writestr(arcname, fi.content)
        if args.backup:
            zf.close()
            mx.log(f'Wrote backup of {len(modified)} modified files to {backup}')
        if args.patchfile:
            mx.log(f'Wrote patches to {args.patchfile.name}')
            args.patchfile.close()
        return 1
    return 0


def locate_eclipse_exe(eclipse_exe):
    """
    Tries to locate an Eclipse executable starting with the given path.
    If the path is None, checks the ECLIPSE_EXE environment variable.
    If the path is a directory, tries to locate the eclipse executable below the directory.
    If the path is a file, ensures that the file is executable.
    Returns a path to the Eclipse executable if one could be found, None otherwise.
    """

    if eclipse_exe is None:
        eclipse_exe = os.environ.get('ECLIPSE_EXE')
    if eclipse_exe is None:
        return None
    # Maybe an Eclipse installation dir was specified - look for the executable in it
    if isdir(eclipse_exe):
        eclipse_exe = join(eclipse_exe, mx.exe_suffix('eclipse'))
        mx.warn("The eclipse-exe was a directory, now using " + eclipse_exe)
    if not os.path.isfile(eclipse_exe):
        mx.abort('File does not exist: ' + eclipse_exe)
    if not os.access(eclipse_exe, os.X_OK):
        mx.abort('Not an executable file: ' + eclipse_exe)

    return eclipse_exe


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
    eclipseLaunches = mx_util.ensure_dir_exists(join(suite.mxDir, 'eclipse-launches'))
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

    eclipseLaunches = mx_util.ensure_dir_exists(join(suite.mxDir, 'eclipse-launches'))
    launchFile = join(eclipseLaunches, name + '.launch')
    sourcesFile = join(eclipseLaunches, name + '.sources')
    mx.update_file(sourcesFile, '\n'.join(sources))
    return mx.update_file(launchFile, launch)

@mx.command('mx', 'eclipseinit')
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

    mx.log('----------------------------------------------')
    workspace_dir = os.path.dirname(os.path.abspath(mx.primary_suite().vc_dir))

    mx.log('Eclipse project generation successfully completed for:')
    mx.log('  ' + (os.linesep + "  ").join(sorted([suite.dir for suite in mx.suites(True)])))
    mx.log('')
    mx.log('The recommended next steps are:')
    mx.log(f' 1) Open Eclipse with workspace path: {workspace_dir}')
    mx.log(' 2) Open project import wizard using: File -> Import -> Existing Projects into Workspace -> Next.')
    mx.log(f' 3) For "select root directory" enter path {workspace_dir}')
    mx.log(' 4) Make sure "Search for nested projects" is checked and press "Finish".')
    mx.log('')
    mx.log(' hint) If you select "Close newly imported projects upon completion" then the import is more efficient. ')
    mx.log('       Projects needed for development can be opened conveniently using the generated Suite working sets from the context menu.')
    mx.log(' 5) Update the type filters (Preferences -> Java -> Appearance -> Type Filters) so that `jdk.*` and `org.graalvm.*` are not filtered.')
    mx.log('    Without this, code completion will not work for JVMCI and Graal code.')
    mx.log('')
    mx.log('Note that setting MX_BUILD_EXPLODED=true can improve Eclipse build times. See "Exploded builds" in the mx README.md.')
    mx.log('----------------------------------------------')

    if _EclipseJRESystemLibraries:
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
        mx_ideconfig.fsckprojects([])

    return wsroot


EclipseLinkedResource = namedtuple('LinkedResource', ['name', 'type', 'location'])
def _eclipse_linked_resource(name, res_type, location):
    return EclipseLinkedResource(name, str(res_type), location)

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
        projectLoc = f'PARENT-{parents}-PROJECT_LOC'
    else:
        projectLoc = 'PROJECT_LOC'
    return sep.join([projectLoc] + [n for n in names if n != '..'])

def _get_eclipse_output_path(project_loc, p, linkedResources=None):
    """
    Gets the Eclipse path attribute value for the output of project `p` whose
    Eclipse configuration is in the directory `project_loc`.
    """
    outputDirRel = os.path.relpath(p.output_dir(), project_loc)
    if outputDirRel.startswith('..'):
        name = basename(outputDirRel)
        if linkedResources is not None:
            linkedResources.append(_eclipse_linked_resource(name, IRESOURCE_FOLDER, p.output_dir()))
        return name
    else:
        return outputDirRel

#: Highest Execution Environment defined by most recent Eclipse release.
#: https://wiki.eclipse.org/Execution_Environments
#: https://git.eclipse.org/c/jdt/eclipse.jdt.debug.git/plain/org.eclipse.jdt.launching/plugin.properties
_max_Eclipse_JavaExecutionEnvironment = 21 # pylint: disable=invalid-name

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

RelevantResource = namedtuple('RelevantResource', ['path', 'type'])

# http://grepcode.com/file/repository.grepcode.com/java/eclipse.org/4.4.2/org.eclipse.core/resources/3.9.1/org/eclipse/core/resources/IResource.java#76
IRESOURCE_FILE = 1
IRESOURCE_FOLDER = 2

def _add_eclipse_linked_resources(xml_doc, project_loc, linked_resources, absolutePaths=False):
    """
    Adds a ``linkedResources`` element to `xml_doc` for the resources described by `linked_resources`.

    :param project_loc: directory containing ``.project`` file containing the content of `xml_doc`
    """
    if linked_resources:
        xml_doc.open('linkedResources')
        for lr in linked_resources:
            xml_doc.open('link')
            xml_doc.element('name', data=lr.name)
            xml_doc.element('type', data=lr.type)
            xml_doc.element('locationURI', data=get_eclipse_project_rel_locationURI(lr.location, project_loc) if not absolutePaths else lr.location)
            xml_doc.close('link')
        xml_doc.close('linkedResources')

def _eclipse_project_rel(project_loc, path, linked_resources, res_type=IRESOURCE_FOLDER):
    """
    Converts `path` to be relative to `project_loc`, adding a linked
    resource to `linked_resources` if `path` is not under `project_loc`.

    :param str res_type: IRESOURCE_FOLDER if path denotes a directory, IRESOURCE_FILE for a regular file
    """
    if not path.startswith(project_loc):
        name = basename(path)
        linked_resources.append(_eclipse_linked_resource(name, res_type, path))
        return name
    else:
        return os.path.relpath(path, project_loc)
def _eclipseinit_project(p, files=None, libFiles=None, absolutePaths=False):
    # PROJECT_LOC Eclipse variable
    project_loc = mx_util.ensure_dir_exists(p.dir)

    linkedResources = []

    out = mx.XMLDoc()
    out.open('classpath')

    def _add_src_classpathentry(path, attributes=None):
        out.open('classpathentry', {'kind' : 'src', 'path' : _eclipse_project_rel(project_loc, path, linkedResources)})
        if attributes:
            out.open('attributes')
            for name, value in attributes.items():
                out.element('attribute', {'name' : name, 'value' : value})
            out.close('attributes')
        out.close('classpathentry')

    for src in p.srcDirs:
        _add_src_classpathentry(mx_util.ensure_dir_exists(join(p.dir, src)))

    processors = p.annotation_processors()
    if processors:
        gen_dir = mx_util.ensure_dir_exists(p.source_gen_dir())
        # ignore warnings produced by third-party annotation processors
        has_external_processors = any((ap for ap in p.declaredAnnotationProcessors if ap.isLibrary()))
        attributes = {'ignore_optional_problems': 'true'} if has_external_processors else None
        _add_src_classpathentry(gen_dir, attributes)
        if files:
            files.append(gen_dir)

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
        if dep.isLibrary():
            processLibraryDep(dep)
        elif dep.isJavaProject():
            high_bound = dep.javaCompliance._high_bound()
            if not high_bound or high_bound >= p.javaCompliance.value:
                projectDeps.append(dep)
            else:
                # Ignore a dep whose highest Java level is less than p's level
                pass
        elif dep.isNativeProject():
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
            # Ignore modules (such as jdk.graal.compiler) that define packages
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
                default_module_graph = mx_javamodules.get_transitive_closure(roots, observable_modules)
                module_graph = mx_javamodules.get_transitive_closure(roots + exported_modules, observable_modules)
                if default_module_graph != module_graph:
                    # https://github.com/eclipse/eclipse.jdt.core/blob/00dd337bcfe08d8b2d60529b0f7874b88e621c06/org.eclipse.jdt.core/model/org/eclipse/jdt/internal/core/JavaProject.java#L704-L715
                    out.element('attribute', {'name' : 'limit-modules', 'value' : ','.join([m.name for m in module_graph])})
        out.close('attributes')
    out.close('classpathentry')

    if putJREFirstOnBuildPath:
        for dep in projectDeps:
            if not dep.isNativeProject():
                out.element('classpathentry', {'combineaccessrules' : 'false', 'exported' : 'true', 'kind' : 'src', 'path' : '/' + dep.name})

    out.element('classpathentry', {'kind' : 'output', 'path' : _get_eclipse_output_path(project_loc, p, linkedResources)})

    out.close('classpath')
    classpathFile = join(project_loc, '.classpath')
    mx.update_file(classpathFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(classpathFile)

    csConfig, _, cs_project = p.get_checkstyle_config()
    if csConfig:
        out = mx.XMLDoc()

        dotCheckstyle = join(project_loc, ".checkstyle")
        cs_path = _eclipse_project_rel(project_loc, csConfig, linkedResources, IRESOURCE_FILE)
        out.open('fileset-config', {'file-format-version' : '1.2.0', 'simple-config' : 'false'})
        out.open('local-check-config', {'name' : 'Checks', 'location' : '/' + cs_project.name + '/' + cs_path, 'type' : 'project', 'description' : ''})
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
        dotCheckstyle = join(project_loc, ".checkstyle")
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
    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        out.element('nature', data='org.eclipse.pde.PluginNature')
    out.close('natures')
    _add_eclipse_linked_resources(out, project_loc, linkedResources, absolutePaths)
    out.close('projectDescription')
    projectFile = join(project_loc, '.project')
    mx.update_file(projectFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(projectFile)

    # copy a possibly modified file to the project's .settings directory
    _copy_eclipse_settings(project_loc, p, files)

    if processors:
        out = mx.XMLDoc()
        out.open('factorypath')
        out.element('factorypathentry', {'kind' : 'PLUGIN', 'id' : 'org.eclipse.jst.ws.annotations.core', 'enabled' : 'true', 'runInBatchMode' : 'false'})
        processorsPath = mx.classpath_entries(names=processors)
        for e in processorsPath:
            if e.isDistribution() and not isinstance(e.suite, mx.BinarySuite):
                out.element('factorypathentry', {'kind' : 'WKSPJAR', 'id' : f'/{e.name}/{basename(e.path)}', 'enabled' : 'true', 'runInBatchMode' : 'false'})
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
        mx.update_file(join(project_loc, '.factorypath'), out.xml(indent='\t', newl='\n'))
        if files:
            files.append(join(project_loc, '.factorypath'))

def _capture_eclipse_settings(logToConsole, absolutePaths):
    # Capture interesting settings which drive the output of the projects.
    # Changes to these values should cause regeneration of the project files.
    settings = f'logToConsole={logToConsole}\n'
    settings = settings + f'absolutePaths={absolutePaths}\n'
    for name, value in mx_ideconfig._get_ide_envvars().items():
        settings = settings + f'{name}={value}\n'
    return settings

def _eclipseinit_suite(s, buildProcessorJars=True, refreshOnly=False, logToConsole=False, force=False, absolutePaths=False, pythonProjects=False):
    # a binary suite archive is immutable and no project sources, only the -sources.jar
    # TODO We may need the project (for source debugging) but it needs different treatment
    if isinstance(s, mx.BinarySuite):
        return

    suite_config_dir = mx_util.ensure_dir_exists(s.get_mx_output_dir())

    configZip = mx.TimeStampFile(join(suite_config_dir, 'eclipse-config.zip'))
    configLibsZip = join(suite_config_dir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    settingsFile = join(suite_config_dir, 'eclipse-project-settings')
    mx.update_file(settingsFile, _capture_eclipse_settings(logToConsole, absolutePaths))
    if not force and mx_ideconfig._check_ide_timestamp(s, configZip, 'eclipse', settingsFile):
        mx.logv(f'[Eclipse configurations for {s.name} are up to date - skipping]')
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
        project_loc = dist.get_ide_project_dir()
        if not project_loc:
            continue
        mx_util.ensure_dir_exists(project_loc)
        relevantResources = []
        relevantResourceDeps = set(dist.archived_deps())
        for d in sorted(relevantResourceDeps):
            # Eclipse does not seem to trigger a build for a distribution if the references
            # to the constituent projects are of type IRESOURCE_PROJECT.
            if d.isJavaProject():
                for srcDir in d.srcDirs:
                    relevantResources.append(RelevantResource('/' + d.name + '/' + srcDir, IRESOURCE_FOLDER))
                relevantResources.append(RelevantResource('/' + d.name + '/' + _get_eclipse_output_path(project_loc, d), IRESOURCE_FOLDER))

        # make sure there is at least one entry otherwise all resources will be implicitly relevant
        if not relevantResources:
            relevantResources.append(RelevantResource(get_eclipse_project_rel_locationURI(dist.path, project_loc), IRESOURCE_FOLDER))

        use_async_distributions = mx.env_var_to_bool('MX_IDE_ECLIPSE_ASYNC_DISTRIBUTIONS')

        # if a distribution is used as annotation processor we need to refresh the project
        # in order to make eclipse reload the annotation processor jar on changes.
        out = mx.XMLDoc()
        out.open('projectDescription')
        out.element('name', data=dist.name)
        out.element('comment', data='Updates ' + dist.path + ' if a project dependency of ' + dist.name + ' is updated')
        out.open('projects')
        for d in sorted(relevantResourceDeps):
            out.element('project', data=d.name)
        out.close('projects')
        out.open('buildSpec')
        dist.dir = project_loc
        builders = _genEclipseBuilder(project_loc, out, dist, 'Create' + dist.name + 'Dist', '-v archive @' + dist.name,
                                      relevantResources=relevantResources,
                                      logToFile=True, refresh=True, isAsync=use_async_distributions,
                                      logToConsole=logToConsole, appendToLogFile=False,
                                      refreshFile=f'/{dist.name}/{basename(dist.path)}')
        files = files + builders

        out.close('buildSpec')
        out.open('natures')
        out.element('nature', data='org.eclipse.jdt.core.javanature')
        out.close('natures')
        if dist.definedAnnotationProcessors:
            linked_resources = [_eclipse_linked_resource(basename(dist.path), str(IRESOURCE_FILE), dist.path)]
            _add_eclipse_linked_resources(out, project_loc, linked_resources, absolutePaths=absolutePaths)
        out.close('projectDescription')
        projectFile = join(project_loc, '.project')
        mx.update_file(projectFile, out.xml(indent='\t', newl='\n'))
        files.append(projectFile)

    if pythonProjects:
        # Whether this is the suite in the mx repo
        is_mx_suite = s is mx._mx_suite

        # In the mx suite, the files go into the repo root
        # Otherwise they are stored in the suite's mx dir
        project_loc = s.dir if is_mx_suite else s.mxDir

        linked_resources = []
        _eclipse_project_rel(project_loc, s.name if is_mx_suite else s.mxDir, linked_resources)

        projectXml = mx.XMLDoc()
        projectXml.open('projectDescription')
        projectXml.element('name', data=s.name if is_mx_suite else 'mx.' + s.name)
        projectXml.element('comment')
        projectXml.open('projects')
        if not is_mx_suite:
            projectXml.element('project', data=mx._mx_suite.name)

        project_processor.iter_projects(s, lambda _, suite_name: projectXml.element('project', data='mx.' + suite_name))

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
        _add_eclipse_linked_resources(projectXml, project_loc, linked_resources, absolutePaths=absolutePaths)

        projectXml.open('filteredResources')

        # Ignore all *.pyc files
        projectXml.open('filter')
        projectXml.element('id', data='1')
        projectXml.element('name')
        projectXml.element('type', data='22')
        projectXml.open('matcher')
        projectXml.element('id', data='org.eclipse.ui.ide.multiFilter')
        projectXml.element('arguments', data='1.0-name-matches-false-false-*.pyc')
        projectXml.close('matcher')
        projectXml.close('filter')

        # Ignore all __pycache__directories
        projectXml.open('filter')
        projectXml.element('id', data='1')
        projectXml.element('name')
        projectXml.element('type', data='26')
        projectXml.open('matcher')
        projectXml.element('id', data='org.eclipse.ui.ide.multiFilter')
        projectXml.element('arguments', data='1.0-name-matches-false-false-__pycache__')
        projectXml.close('matcher')
        projectXml.close('filter')

        projectXml.close('filteredResources')
        projectXml.close('projectDescription')
        projectFile = join(project_loc, '.project')
        mx.update_file(projectFile, projectXml.xml(indent='  ', newl='\n'))
        files.append(projectFile)

        # Paths that should be added as source paths to the pydev project
        # Is the mx dir for regular suites, and the src and mx.mx dirs for the mx suite
        if is_mx_suite:
            pydev_paths = ["/${PROJECT_DIR_NAME}/src", "/${PROJECT_DIR_NAME}/mx.mx"]
        else:
            pydev_paths = ["/${PROJECT_DIR_NAME}"]

        pydevProjectXml = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<?eclipse-pydev version="1.0"?>
<pydev_project>
    <pydev_property name="org.python.pydev.PYTHON_PROJECT_INTERPRETER">Default</pydev_property>
    <pydev_property name="org.python.pydev.PYTHON_PROJECT_VERSION">python 3.8</pydev_property>
    <pydev_pathproperty name="org.python.pydev.PROJECT_SOURCE_PATH">
{os.linesep.join([f"        <path>{p}</path>" for p in pydev_paths])}
    </pydev_pathproperty>
</pydev_project>
"""
        pydevProjectFile = join(project_loc, '.pydevproject')
        mx.update_file(pydevProjectFile, pydevProjectXml)
        files.append(pydevProjectFile)

    mx_ideconfig._zip_files(files + [settingsFile], s.dir, configZip.path)
    mx_ideconfig._zip_files(libFiles, s.dir, configLibsZip)

def _genEclipseBuilder(eclipseConfigRoot, dotProjectDoc, p, name, mxCommand, refresh=True, refreshFile=None, relevantResources=None, isAsync=False, logToConsole=False, logToFile=False, appendToLogFile=True, xmlIndent='\t', xmlStandalone=None):
    externalToolDir = join(eclipseConfigRoot, '.externalToolBuilders')
    launchOut = mx.XMLDoc()
    consoleOn = 'true' if logToConsole else 'false'
    launchOut.open('launchConfiguration', {'type' : 'org.eclipse.ui.externaltools.ProgramBuilderLaunchConfigurationType'})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.core.capture_output', 'value': consoleOn})
    launchOut.open('mapAttribute', {'key' : 'org.eclipse.debug.core.environmentVariables'})
    for key, value in mx_ideconfig._get_ide_envvars().items():
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

    cmdPath = mx.get_mx_path()
    if not os.path.exists(cmdPath):
        mx.abort('cannot locate ' + cmdPath)

    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_LOCATION', 'value':  cmdPath})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_RUN_BUILD_KINDS', 'value': 'auto,full,incremental'})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_TOOL_ARGUMENTS', 'value': mxCommand})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_TRIGGERS_CONFIGURED', 'value': 'true'})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_WORKING_DIRECTORY', 'value': p.suite.dir})


    launchOut.close('launchConfiguration')

    mx_util.ensure_dir_exists(externalToolDir)
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
        if not p.isJavaProject():
            continue
        _add_to_working_set('Suite ' + p.suite.name, p.name)
        if p.workingSets is None:
            continue
        for w in p.workingSets.split(","):
            _add_to_working_set(w, p.name)

    for dist in mx.distributions():
        if not dist.isJARDistribution():
            continue
        projectDir = dist.get_ide_project_dir()
        if not projectDir:
            continue
        _add_to_working_set('Suite ' + dist.suite.name, dist.name)

    # the mx metdata directories are included in the appropriate working sets
    _add_to_working_set('MX', 'mxtool')
    for suite in mx.suites(True):
        _add_to_working_set('MX', basename(suite.mxDir))
        _add_to_working_set('Suite ' + suite.name, basename(suite.mxDir))

    if exists(wspath):
        wsdoc = _copy_workingset_xml(wspath, workingSets)
    else:
        wsdoc = _make_workingset_xml(workingSets)
    if mx.update_file(wspath, wsdoc.xml(newl='\n')):
        mx.log('Please restart Eclipse instances for this workspace to see some of the effects.')
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


### ~~~~~~~~~~~~~ _private, eclipse

def _copy_eclipse_settings(project_loc, p, files=None):
    processors = p.annotation_processors()

    settingsDir = mx_util.ensure_dir_exists(join(project_loc, ".settings"))

    for name, sources in p.eclipse_settings_sources().items():
        out = StringIO()
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
