#!/usr/bin/env python2.7
#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2007, 2015, Oracle and/or its affiliates. All rights reserved.
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

Full documentation can be found in the Wiki at the site from which mxtool was downloaded.

This version (2.x) of mx is an evolution of mx 1.x (provided with the Graal distribution),
and supports multiple suites in separate Mercurial repositories. It is intended to be backwards
compatible and is periodically merged with mx 1.x. The following changeset id is the last mx.1.x
version that was merged.

ec47283499ef49ddc5074b6d05e102bf6e31bab4
"""

import sys, os, errno, time, datetime, subprocess, shlex, types, StringIO, zipfile, signal, xml.sax.saxutils, tempfile, fnmatch, platform
import textwrap
import socket
import xml.parsers.expat
import tarfile
import hashlib
import shutil, re, xml.dom.minidom
import pipes
import difflib
from collections import Callable
from threading import Thread
from argparse import ArgumentParser, REMAINDER
from os.path import join, basename, dirname, exists, getmtime, isabs, expandvars, isdir, isfile

# This works because when mx loads this file, it makes sure __file__ gets an absolute path
_mx_home = dirname(__file__)

try:
    # needed to work around https://bugs.python.org/issue1927
    import readline
    #then make pylint happy..
    readline.get_line_buffer()
except ImportError:
    pass

# Support for Python 2.6
def check_output(*popenargs, **kwargs):
    process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
    output, _ = process.communicate()
    retcode = process.poll()
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = popenargs[0]
        error = subprocess.CalledProcessError(retcode, cmd)
        error.output = output
        raise error
    return output

# Support for jython
def is_jython():
    return sys.platform.startswith('java')

if not is_jython():
    import multiprocessing

def cpu_count():
    if is_jython():
        from java.lang import Runtime
        runtime = Runtime.getRuntime()
        return runtime.availableProcessors()
    else:
        return multiprocessing.cpu_count()

try: subprocess.check_output
except: subprocess.check_output = check_output

try: zipfile.ZipFile.__enter__
except:
    zipfile.ZipFile.__enter__ = lambda self: self
    zipfile.ZipFile.__exit__ = lambda self, t, value, traceback: self.close()

_projects = dict()
_libs = dict()
_jreLibs = dict()
_dists = dict()
_suites = dict()
_annotationProcessors = None
_primary_suite_path = None
_primary_suite = None
_src_suitemodel = None
_dst_suitemodel = None
_opts = None
_extra_java_homes = []
_default_java_home = None
_check_global_structures = True  # can be set False to allow suites with duplicate definitions to load without aborting
_warn = False
_hg = None


"""
A distribution is a jar or zip file containing the output from one or more Java projects.
"""
class Distribution:
    def __init__(self, suite, name, path, sourcesPath, deps, mainClass, excludedDependencies, distDependencies, javaCompliance, isProcessorDistribution=False):
        self.suite = suite
        self.name = name
        self.path = path.replace('/', os.sep)
        self.path = _make_absolute(self.path, suite.dir)
        self.sourcesPath = _make_absolute(sourcesPath.replace('/', os.sep), suite.dir) if sourcesPath else None
        self.deps = deps
        self.update_listeners = set()
        self.mainClass = mainClass
        self.excludedDependencies = excludedDependencies
        self.distDependencies = distDependencies
        self.javaCompliance = JavaCompliance(javaCompliance) if javaCompliance else None
        self.isProcessorDistribution = isProcessorDistribution

    def sorted_deps(self, includeLibs=False, transitive=False):
        deps = []
        if transitive:
            for depDist in [distribution(name) for name in self.distDependencies]:
                for d in depDist.sorted_deps(includeLibs=includeLibs, transitive=True):
                    if d not in deps:
                        deps.append(d)
        try:
            excl = [dependency(d) for d in self.excludedDependencies]
        except SystemExit as e:
            abort('invalid excluded dependency for {0} distribution: {1}'.format(self.name, e))
        return deps + [d for d in sorted_deps(self.deps, includeLibs=includeLibs) if d not in excl]

    def __str__(self):
        return self.name

    def add_update_listener(self, listener):
        self.update_listeners.add(listener)

    """
    Gets the directory in which the IDE project configuration
    for this distribution is generated. If this is a distribution
    derived from a project defining an annotation processor, then
    None is return to indicate no IDE configuration should be
    created for this distribution.
    """
    def get_ide_project_dir(self):
        if hasattr(self, 'definingProject') and self.definingProject.definedAnnotationProcessorsDist == self:
            return None
        if hasattr(self, 'subDir'):
            return join(self.suite.dir, self.subDir, self.name + '.dist')
        else:
            return join(self.suite.dir, self.name + '.dist')

    def make_archive(self):
        # are sources combined into main archive?
        unified = self.path == self.sourcesPath

        with Archiver(self.path) as arc:
            with Archiver(None if unified else self.sourcesPath) as srcArcRaw:
                srcArc = arc if unified else srcArcRaw
                services = {}
                def overwriteCheck(zf, arcname, source):
                    if not hasattr(zf, '_provenance'):
                        zf._provenance = {}
                    existingSource = zf._provenance.get(arcname, None)
                    isOverwrite = False
                    if existingSource and existingSource != source:
                        if arcname[-1] != os.path.sep:
                            logv('warning: ' + self.path + ': avoid overwrite of ' + arcname + '\n  new: ' + source + '\n  old: ' + existingSource)
                        isOverwrite = True
                    zf._provenance[arcname] = source
                    return isOverwrite

                if self.mainClass:
                    manifest = "Manifest-Version: 1.0\nMain-Class: %s\n\n" % (self.mainClass)
                    if not overwriteCheck(arc.zf, "META-INF/MANIFEST.MF", "project files"):
                        arc.zf.writestr("META-INF/MANIFEST.MF", manifest)

                for dep in self.sorted_deps(includeLibs=True):
                    isCoveredByDependecy = False
                    for d in self.distDependencies:
                        if dep in _dists[d].sorted_deps(includeLibs=True, transitive=True):
                            logv("Excluding {0} from {1} because it's provided by the dependency {2}".format(dep.name, self.path, d))
                            isCoveredByDependecy = True
                            break

                    if isCoveredByDependecy:
                        continue

                    if dep.isLibrary():
                        l = dep
                        # merge library jar into distribution jar
                        logv('[' + self.path + ': adding library ' + l.name + ']')
                        lpath = l.get_path(resolve=True)
                        libSourcePath = l.get_source_path(resolve=True)
                        if lpath:
                            with zipfile.ZipFile(lpath, 'r') as lp:
                                for arcname in lp.namelist():
                                    if arcname.startswith('META-INF/services/') and not arcname == 'META-INF/services/':
                                        service = arcname[len('META-INF/services/'):]
                                        assert '/' not in service
                                        services.setdefault(service, []).extend(lp.read(arcname).splitlines())
                                    else:
                                        if not overwriteCheck(arc.zf, arcname, lpath + '!' + arcname):
                                            arc.zf.writestr(arcname, lp.read(arcname))
                        if srcArc.zf and libSourcePath:
                            with zipfile.ZipFile(libSourcePath, 'r') as lp:
                                for arcname in lp.namelist():
                                    if not overwriteCheck(srcArc.zf, arcname, lpath + '!' + arcname):
                                        srcArc.zf.writestr(arcname, lp.read(arcname))
                    elif dep.isProject():
                        p = dep

                        if self.javaCompliance:
                            if p.javaCompliance > self.javaCompliance:
                                abort("Compliance level doesn't match: Distribution {0} requires {1}, but {2} is {3}.".format(self.name, self.javaCompliance, p.name, p.javaCompliance))

                        logv('[' + self.path + ': adding project ' + p.name + ']')
                        outputDir = p.output_dir()
                        for root, _, files in os.walk(outputDir):
                            relpath = root[len(outputDir) + 1:]
                            if relpath == join('META-INF', 'services'):
                                for service in files:
                                    with open(join(root, service), 'r') as fp:
                                        services.setdefault(service, []).extend([provider.strip() for provider in fp.readlines()])
                            elif relpath == join('META-INF', 'providers'):
                                for provider in files:
                                    with open(join(root, provider), 'r') as fp:
                                        for service in fp:
                                            services.setdefault(service.strip(), []).append(provider)
                            else:
                                for f in files:
                                    arcname = join(relpath, f).replace(os.sep, '/')
                                    if not overwriteCheck(arc.zf, arcname, join(root, f)):
                                        arc.zf.write(join(root, f), arcname)
                        if srcArc.zf:
                            sourceDirs = p.source_dirs()
                            if p.source_gen_dir():
                                sourceDirs.append(p.source_gen_dir())
                            for srcDir in sourceDirs:
                                for root, _, files in os.walk(srcDir):
                                    relpath = root[len(srcDir) + 1:]
                                    for f in files:
                                        if f.endswith('.java'):
                                            arcname = join(relpath, f).replace(os.sep, '/')
                                            if not overwriteCheck(srcArc.zf, arcname, join(root, f)):
                                                srcArc.zf.write(join(root, f), arcname)

                for service, providers in services.iteritems():
                    arcname = 'META-INF/services/' + service
                    arc.zf.writestr(arcname, '\n'.join(providers))

        self.notify_updated()


    def notify_updated(self):
        for l in self.update_listeners:
            l(self)

"""
A dependency is a library or project specified in a suite.
"""
class Dependency:
    def __init__(self, suite, name):
        self.name = name
        self.suite = suite

    def __cmp__(self, other):
        return cmp(self.name, other.name)

    def __str__(self):
        return self.name

    def __eq__(self, other):
        return self.name == other.name

    def __ne__(self, other):
        return self.name != other.name

    def __hash__(self):
        return hash(self.name)

    def isLibrary(self):
        return isinstance(self, Library)

    def isJreLibrary(self):
        return isinstance(self, JreLibrary)

    def isProject(self):
        return isinstance(self, Project)

class Project(Dependency):
    def __init__(self, suite, name, srcDirs, deps, javaCompliance, workingSets, d):
        Dependency.__init__(self, suite, name)
        self.srcDirs = srcDirs
        self.deps = deps
        self.checkstyleProj = name
        self.javaCompliance = JavaCompliance(javaCompliance) if javaCompliance is not None else None
        self.native = False
        self.workingSets = workingSets
        self.dir = d

        # The annotation processors defined by this project
        self.definedAnnotationProcessors = None
        self.definedAnnotationProcessorsDist = None

        # Create directories for projects that don't yet exist
        if not exists(d):
            os.mkdir(d)
        for s in self.source_dirs():
            if not exists(s):
                os.mkdir(s)

    def all_deps(self, deps, includeLibs, includeSelf=True, includeJreLibs=False, includeAnnotationProcessors=False):
        """
        Add the transitive set of dependencies for this project, including
        libraries if 'includeLibs' is true, to the 'deps' list.
        """
        return sorted(self._all_deps_helper(deps, [], includeLibs, includeSelf, includeJreLibs, includeAnnotationProcessors))

    def _all_deps_helper(self, deps, dependants, includeLibs, includeSelf=True, includeJreLibs=False, includeAnnotationProcessors=False):
        if self in dependants:
            abort(str(self) + 'Project dependency cycle found:\n    ' +
                  '\n        |\n        V\n    '.join(map(str, dependants[dependants.index(self):])) +
                  '\n        |\n        V\n    ' + self.name)
        childDeps = list(self.deps)
        if includeAnnotationProcessors and len(self.annotation_processors()) > 0:
            childDeps = self.annotation_processors() + childDeps
        if self in deps:
            return deps
        for name in childDeps:
            assert name != self.name
            dep = dependency(name)
            if not dep in deps:
                if dep.isProject():
                    dep._all_deps_helper(deps, dependants + [self], includeLibs=includeLibs, includeJreLibs=includeJreLibs, includeAnnotationProcessors=includeAnnotationProcessors)
                elif dep.isProject or (dep.isLibrary() and includeLibs) or (dep.isJreLibrary() and includeJreLibs):
                    dep.all_deps(deps, includeLibs=includeLibs, includeJreLibs=includeJreLibs, includeAnnotationProcessors=includeAnnotationProcessors)
        if not self in deps and includeSelf:
            deps.append(self)
        return deps

    def _compute_max_dep_distances(self, name, distances, dist):
        currentDist = distances.get(name)
        if currentDist is None or currentDist < dist:
            distances[name] = dist
            p = project(name, False)
            if p is not None:
                for dep in p.deps:
                    self._compute_max_dep_distances(dep, distances, dist + 1)

    def canonical_deps(self):
        """
        Get the dependencies of this project that are not recursive (i.e. cannot be reached
        via other dependencies).
        """
        distances = dict()
        result = set()
        self._compute_max_dep_distances(self.name, distances, 0)
        for n, d in distances.iteritems():
            assert d > 0 or n == self.name
            if d == 1:
                result.add(n)

        if len(result) == len(self.deps) and frozenset(self.deps) == result:
            return self.deps
        return result

    def max_depth(self):
        """
        Get the maximum canonical distance between this project and its most distant dependency.
        """
        distances = dict()
        self._compute_max_dep_distances(self.name, distances, 0)
        return max(distances.values())

    def source_dirs(self):
        """
        Get the directories in which the sources of this project are found.
        """
        return [join(self.dir, s) for s in self.srcDirs]

    def source_gen_dir(self):
        """
        Get the directory in which source files generated by the annotation processor are found/placed.
        """
        if self.native:
            return None
        return join(self.dir, 'src_gen')

    def output_dir(self):
        """
        Get the directory in which the class files of this project are found/placed.
        """
        if self.native:
            return None
        return join(self.dir, 'bin')

    def jasmin_output_dir(self):
        """
        Get the directory in which the Jasmin assembled class files of this project are found/placed.
        """
        if self.native:
            return None
        return join(self.dir, 'jasmin_classes')

    def append_to_classpath(self, cp, resolve):
        if not self.native:
            cp.append(self.output_dir())

    def find_classes_with_matching_source_line(self, pkgRoot, function, includeInnerClasses=False):
        """
        Scan the sources of this project for Java source files containing a line for which
        'function' returns true. A map from class name to source file path for each existing class
        corresponding to a matched source file is returned.
        """
        result = dict()
        pkgDecl = re.compile(r"^package\s+([a-zA-Z_][\w\.]*)\s*;$")
        for srcDir in self.source_dirs():
            outputDir = self.output_dir()
            for root, _, files in os.walk(srcDir):
                for name in files:
                    if name.endswith('.java') and name != 'package-info.java':
                        matchFound = False
                        source = join(root, name)
                        with open(source) as f:
                            pkg = None
                            for line in f:
                                if line.startswith("package "):
                                    match = pkgDecl.match(line)
                                    if match:
                                        pkg = match.group(1)
                                if function(line.strip()):
                                    matchFound = True
                                if pkg and matchFound:
                                    break

                        if matchFound:
                            simpleClassName = name[:-len('.java')]
                            assert pkg is not None, 'could not find package statement in file ' + name
                            if pkgRoot is None or pkg.startswith(pkgRoot):
                                pkgOutputDir = join(outputDir, pkg.replace('.', os.path.sep))
                                if exists(pkgOutputDir):
                                    for e in os.listdir(pkgOutputDir):
                                        if includeInnerClasses:
                                            if e.endswith('.class') and (e.startswith(simpleClassName) or e.startswith(simpleClassName + '$')):
                                                className = pkg + '.' + e[:-len('.class')]
                                                result[className] = source
                                        elif e == simpleClassName + '.class':
                                            className = pkg + '.' + simpleClassName
                                            result[className] = source
        return result

    def _init_packages_and_imports(self):
        if not hasattr(self, '_defined_java_packages'):
            packages = set()
            extendedPackages = set()
            depPackages = set()
            for d in self.all_deps([], includeLibs=False, includeSelf=False):
                depPackages.update(d.defined_java_packages())
            imports = set()
            importRe = re.compile(r'import\s+(?:static\s+)?([^;]+);')
            for sourceDir in self.source_dirs():
                for root, _, files in os.walk(sourceDir):
                    javaSources = [name for name in files if name.endswith('.java')]
                    if len(javaSources) != 0:
                        pkg = root[len(sourceDir) + 1:].replace(os.sep, '.')
                        if not pkg in depPackages:
                            packages.add(pkg)
                        else:
                            # A project extends a package already defined by one of it dependencies
                            extendedPackages.add(pkg)
                            imports.add(pkg)

                        for n in javaSources:
                            with open(join(root, n)) as fp:
                                content = fp.read()
                                imports.update(importRe.findall(content))
            self._defined_java_packages = frozenset(packages)
            self._extended_java_packages = frozenset(extendedPackages)

            importedPackages = set()
            for imp in imports:
                name = imp
                while not name in depPackages and len(name) > 0:
                    lastDot = name.rfind('.')
                    if lastDot == -1:
                        name = None
                        break
                    name = name[0:lastDot]
                if name is not None:
                    importedPackages.add(name)
            self._imported_java_packages = frozenset(importedPackages)

    def defined_java_packages(self):
        """Get the immutable set of Java packages defined by the Java sources of this project"""
        self._init_packages_and_imports()
        return self._defined_java_packages

    def extended_java_packages(self):
        """Get the immutable set of Java packages extended by the Java sources of this project"""
        self._init_packages_and_imports()
        return self._extended_java_packages

    def imported_java_packages(self):
        """Get the immutable set of Java packages defined by other Java projects that are
           imported by the Java sources of this project."""
        self._init_packages_and_imports()
        return self._imported_java_packages

    """
    Gets the list of projects defining the annotation processors that will be applied
    when compiling this project. This includes the projects declared by the annotationProcessors property
    of this project and any of its project dependencies. It also includes
    any project dependencies that define an annotation processors.
    """
    def annotation_processors(self):
        if not hasattr(self, '_annotationProcessors'):
            aps = set()
            if hasattr(self, '_declaredAnnotationProcessors'):
                aps = set(self._declaredAnnotationProcessors)
                for ap in aps:
                    if project(ap).definedAnnotationProcessorsDist is None:
                        config = join(project(ap).source_dirs()[0], 'META-INF', 'services', 'javax.annotation.processing.Processor')
                        if not exists(config):
                            TimeStampFile(config).touch()
                        abort('Project ' + ap + ' declared in annotationProcessors property of ' + self.name + ' does not define any annotation processors.\n' +
                              'Please specify the annotation processors in ' + config)

            allDeps = self.all_deps([], includeLibs=False, includeSelf=False, includeAnnotationProcessors=False)
            for p in allDeps:
                # Add an annotation processor dependency
                if p.definedAnnotationProcessorsDist is not None:
                    aps.add(p.name)

                # Inherit annotation processors from dependencies
                aps.update(p.annotation_processors())

            self._annotationProcessors = sorted(list(aps))
        return self._annotationProcessors

    """
    Gets the class path composed of the distribution jars containing the
    annotation processors that will be applied when compiling this project.
    """
    def annotation_processors_path(self):
        aps = [project(ap) for ap in self.annotation_processors()]
        libAps = [dep for dep in self.all_deps([], includeLibs=True, includeSelf=False) if dep.isLibrary() and hasattr(dep, 'annotationProcessor') and getattr(dep, 'annotationProcessor').lower() == 'true']
        if len(aps) + len(libAps):
            return os.pathsep.join([ap.definedAnnotationProcessorsDist.path for ap in aps if ap.definedAnnotationProcessorsDist] + [lib.get_path(False) for lib in libAps])
        return None

    def uses_annotation_processor_library(self):
        for dep in self.all_deps([], includeLibs=True, includeSelf=False):
            if dep.isLibrary() and hasattr(dep, 'annotationProcessor'):
                return True
        return False

    def update_current_annotation_processors_file(self):
        aps = self.annotation_processors()
        outOfDate = False
        currentApsFile = join(self.suite.mxDir, 'currentAnnotationProcessors', self.name)
        currentApsFileExists = exists(currentApsFile)
        if currentApsFileExists:
            with open(currentApsFile) as fp:
                currentAps = [l.strip() for l in fp.readlines()]
                if currentAps != aps:
                    outOfDate = True
        if outOfDate or not currentApsFileExists:
            if not exists(dirname(currentApsFile)):
                os.mkdir(dirname(currentApsFile))
            with open(currentApsFile, 'w') as fp:
                for ap in aps:
                    print >> fp, ap
        return outOfDate

    def make_archive(self, path=None):
        outputDir = self.output_dir()
        if not path:
            path = join(self.dir, self.name + '.jar')
        with Archiver(path) as arc:
            for root, _, files in os.walk(outputDir):
                for f in files:
                    relpath = root[len(outputDir) + 1:]
                    arcname = join(relpath, f).replace(os.sep, '/')
                    arc.zf.write(join(root, f), arcname)
        return path


def _make_absolute(path, prefix):
    """
    Makes 'path' absolute if it isn't already by prefixing 'prefix'
    """
    if not isabs(path):
        return join(prefix, path)
    return path

def sha1(args):
    """generate sha1 digest for given file"""
    parser = ArgumentParser(prog='sha1')
    parser.add_argument('--path', action='store', help='path to file', metavar='<path>', required=True)
    args = parser.parse_args(args)
    print 'sha1 of ' + args.path + ': ' + sha1OfFile(args.path)

def sha1OfFile(path):
    with open(path, 'rb') as f:
        d = hashlib.sha1()
        while True:
            buf = f.read(4096)
            if not buf:
                break
            d.update(buf)
        return d.hexdigest()

def download_file_with_sha1(name, path, urls, sha1, sha1path, resolve, mustExist, sources=False, canSymlink=True):
    canSymlink = canSymlink and not (get_os() == 'windows' or get_os() == 'cygwin')
    def _download_lib():
        cacheDir = _cygpathW2U(get_env('MX_CACHE_DIR', join(_opts.user_home, '.mx', 'cache')))
        if not exists(cacheDir):
            os.makedirs(cacheDir)
        base = basename(path)
        cachePath = join(cacheDir, base + '_' + sha1)

        if not exists(cachePath) or sha1OfFile(cachePath) != sha1:
            if exists(cachePath):
                log('SHA1 of ' + cachePath + ' does not match expected value (' + sha1 + ') - found ' + sha1OfFile(cachePath) + ' - re-downloading')
            print 'Downloading ' + ("sources " if sources else "") + name + ' from ' + str(urls)
            download(cachePath, urls)

        d = dirname(path)
        if d != '' and not exists(d):
            os.makedirs(d)
        if canSymlink and 'symlink' in dir(os):
            try:
                if exists(path):
                    os.unlink(path)
                print 'Path ' + cachePath + ' path: ' + path
                os.symlink(cachePath, path)
            except OSError as e:
                abort('download_file_with_sha1 symlink({0}, {1}) failed, error {2}'.format(cachePath, path, str(e)))

        else:
            shutil.copy(cachePath, path)

    def _sha1Cached():
        with open(sha1path, 'r') as f:
            return f.read()[0:40]

    def _writeSha1Cached():
        with open(sha1path, 'w') as f:
            f.write(sha1OfFile(path))

    def _check():
        return sha1 != "NOCHECK"

    if resolve and mustExist and not exists(path):
        assert not len(urls) == 0, 'cannot find required library ' + name + ' ' + path
        _download_lib()

    if exists(path):
        if _check():
            if sha1 and not exists(sha1path):
                _writeSha1Cached()

            if sha1 and sha1 != _sha1Cached():
                _download_lib()
                if sha1 != sha1OfFile(path):
                    abort("SHA1 does not match for " + name + ". Broken download? SHA1 not updated in projects file?")
                _writeSha1Cached()

    return path

class BaseLibrary(Dependency):
    def __init__(self, suite, name, optional):
        Dependency.__init__(self, suite, name)
        self.optional = optional

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

"""
A library that will be provided by the JRE but may be absent.
Any project or normal library that depends on a missing library
will be removed from the global project and library dictionaries
(i.e., _projects and _libs).

This mechanism exists primarily to be able to support code
that may use functionality in one JRE (e.g., Oracle JRE)
that is not present in another JRE (e.g., OpenJDK). A
motivating example is the Java Flight Recorder library
found in the Oracle JRE.
"""
class JreLibrary(BaseLibrary):
    def __init__(self, suite, name, jar, optional):
        BaseLibrary.__init__(self, suite, name, optional)
        self.jar = jar

    def __eq__(self, other):
        if isinstance(other, JreLibrary):
            return self.jar == other.jar
        else:
            return NotImplemented

    def is_present_in_jdk(self, jdk):
        return jdk.containsJar(self.jar)

    def all_deps(self, deps, includeLibs, includeSelf=True, includeJreLibs=False, includeAnnotationProcessors=False):
        """
        Add the transitive set of dependencies for this JRE library to the 'deps' list.
        """
        if includeJreLibs and includeSelf and not self in deps:
            deps.append(self)
        return sorted(deps)

class Library(BaseLibrary):
    def __init__(self, suite, name, path, optional, urls, sha1, sourcePath, sourceUrls, sourceSha1, deps):
        BaseLibrary.__init__(self, suite, name, optional)
        self.path = path.replace('/', os.sep)
        self.urls = urls
        self.sha1 = sha1
        self.sourcePath = sourcePath
        self.sourceUrls = sourceUrls
        if sourcePath == path:
            assert sourceSha1 is None or sourceSha1 == sha1
            sourceSha1 = sha1
        self.sourceSha1 = sourceSha1
        self.deps = deps
        abspath = _make_absolute(path, self.suite.dir)
        if not optional and not exists(abspath):
            if not len(urls):
                abort('Non-optional library {0} must either exist at {1} or specify one or more URLs from which it can be retrieved'.format(name, abspath))

        def _checkSha1PropertyCondition(propName, cond, inputPath):
            if not cond:
                absInputPath = _make_absolute(inputPath, self.suite.dir)
                if exists(absInputPath):
                    abort('Missing "{0}" property for library {1}. Add the following line to projects file:\nlibrary@{2}@{3}={4}'.format(propName, name, name, propName, sha1OfFile(absInputPath)))
                abort('Missing "{0}" property for library {1}'.format(propName, name))

        _checkSha1PropertyCondition('sha1', sha1, path)
        _checkSha1PropertyCondition('sourceSha1', not sourcePath or sourceSha1, sourcePath)

        for url in urls:
            if url.endswith('/') != self.path.endswith(os.sep):
                abort('Path for dependency directory must have a URL ending with "/": path=' + self.path + ' url=' + url)

    def __eq__(self, other):
        if isinstance(other, Library):
            if len(self.urls) == 0:
                return self.path == other.path
            else:
                return self.urls == other.urls
        else:
            return NotImplemented

    def get_path(self, resolve):
        path = _make_absolute(self.path, self.suite.dir)
        sha1path = path + '.sha1'

        includedInJDK = getattr(self, 'includedInJDK', None)
        # TODO since we don't know which JDK will be used, this check is dubious
        if includedInJDK and java().javaCompliance >= JavaCompliance(includedInJDK):
            return None

        bootClassPathAgent = getattr(self, 'bootClassPathAgent').lower() == 'true' if hasattr(self, 'bootClassPathAgent') else False

        return download_file_with_sha1(self.name, path, self.urls, self.sha1, sha1path, resolve, not self.optional, canSymlink=not bootClassPathAgent)

    def get_source_path(self, resolve):
        if self.sourcePath is None:
            return None
        path = _make_absolute(self.sourcePath, self.suite.dir)
        sha1path = path + '.sha1'

        return download_file_with_sha1(self.name, path, self.sourceUrls, self.sourceSha1, sha1path, resolve, len(self.sourceUrls) != 0, sources=True)

    def append_to_classpath(self, cp, resolve):
        path = self.get_path(resolve)
        if path and (exists(path) or not resolve):
            cp.append(path)

    def all_deps(self, deps, includeLibs, includeSelf=True, includeJreLibs=False, includeAnnotationProcessors=False):
        """
        Add the transitive set of dependencies for this library to the 'deps' list.
        """
        if not includeLibs:
            return sorted(deps)
        childDeps = list(self.deps)
        if self in deps:
            return sorted(deps)
        for name in childDeps:
            assert name != self.name
            dep = library(name)
            if not dep in deps:
                dep.all_deps(deps, includeLibs=includeLibs, includeJreLibs=includeJreLibs, includeAnnotationProcessors=includeAnnotationProcessors)
        if not self in deps and includeSelf:
            deps.append(self)
        return sorted(deps)

class HgConfig:
    """
    Encapsulates access to Mercurial (hg)
    """
    def __init__(self):
        self.missing = 'no hg executable found'
        self.has_hg = None

    def check(self, abortOnFail=True):
        if self.has_hg is None:
            try:
                subprocess.check_output(['hg'])
                self.has_hg = True
            except OSError:
                self.has_hg = False
                warn(self.missing)

        if not self.has_hg:
            if abortOnFail:
                abort(self.missing)
            else:
                warn(self.missing)

    def tip(self, sDir, abortOnError=True):
        try:
            return subprocess.check_output(['hg', 'tip', '-R', sDir, '--template', '{node}'])
        except OSError:
            warn(self.missing)
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('failed to get tip revision id')
            else:
                return None

    def isDirty(self, sDir, abortOnError=True):
        try:
            return len(subprocess.check_output(['hg', 'status', '-R', sDir])) > 0
        except OSError:
            warn(self.missing)
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('failed to get status')
            else:
                return None

    def locate(self, sDir, patterns=None, abortOnError=True):
        try:
            if patterns is None:
                patterns = []
            elif not isinstance(patterns, list):
                patterns = [patterns]
            return subprocess.check_output(['hg', 'locate', '-R', sDir] + patterns).split('\n')
        except OSError:
            warn(self.missing)
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                # hg locate returns 1 if no matches were found
                return []
            if abortOnError:
                abort('failed to locate')
            else:
                return None

    def can_push(self, s, strict=True):
        try:
            output = subprocess.check_output(['hg', '-R', s.dir, 'status'])
            if strict:
                return output == ''
            else:
                if len(output) > 0:
                    for line in output.split('\n'):
                        if len(line) > 0 and not line.startswith('?'):
                            return False
                return True
        except OSError:
            warn(self.missing)
        except subprocess.CalledProcessError:
            return False

    def default_push(self, sdir):
        with open(join(sdir, '.hg', 'hgrc')) as f:
            for line in f:
                line = line.rstrip()
                if line.startswith('default = '):
                    return line[len('default = '):]
        return None

class SuiteModel:
    """
    Defines how to locate a URL/path for a suite, including imported suites.
    Conceptually a SuiteModel is defined by a kind (src,dst), a primary suite URL/path,
    and a map from suite name to URL/path for imported suites.
    Subclasses define a specfic implementation.
    """
    def __init__(self, kind):
        self.kind = kind
        self.primaryDir = None
        self.suitenamemap = {}

    def find_suite_dir(self, suitename):
        """locates the URL/path for suitename or None if not found"""
        abort('find_suite_dir not implemented')

    def set_primary_dir(self, d):
        """informs that d is the primary suite directory"""
        self._primaryDir = d

    def importee_dir(self, importer_dir, suite_import, check_alternate=True):
        """
        returns the directory path for an import of suite_import.name, given importer_dir.
        For a "src" suite model, if check_alternate == True and if suite_import specifies an alternate URL,
        check whether path exists and if not, return the alternate.
        """
        abort('importee_dir not implemented')

    def nestedsuites_dirname(self):
        """Returns the dirname that contains any nested suites if the model supports that"""
        return None

    def _mxDirName(self, name):
        # temporary workaround until mx.graal exists
        if name == 'graal':
            return 'mx'
        else:
            return 'mx.' + name

    def _search_dir(self, searchDir, mxDirName):
        if not exists(searchDir):
            return None
        for dd in os.listdir(searchDir):
            sd = _is_suite_dir(join(searchDir, dd), mxDirName)
            if sd is not None:
                return sd

    def _check_exists(self, suite_import, path, check_alternate=True):
        if check_alternate and self.kind == "src" and suite_import.alternate is not None and not exists(path):
            return suite_import.alternate
        return path

    def _create_suitenamemap(self, optionspec, suitemap):
        """Three ways to specify a suite name mapping, in order of precedence:
        1. Explicitly in optionspec.
        2. In suitemap.
        3. in MX_SUITEMAP environment variable.
        """
        if optionspec != '':
            spec = optionspec
        elif suitemap is not None:
            spec = suitemap
        elif get_env('MX_SUITEMAP') is not None:
            spec = get_env('MX_SUITEMAP')
        else:
            return
        pairs = spec.split(',')
        for pair in pairs:
            mappair = pair.split('=')
            self.suitenamemap[mappair[0]] = mappair[1]

    @staticmethod
    def set_suitemodel(kind, option, suitemap):
        if option.startswith('sibling'):
            return SiblingSuiteModel(kind, os.getcwd(), option, suitemap)
        elif option.startswith('nested'):
            return NestedImportsSuiteModel(kind, os.getcwd(), option, suitemap)
        elif option.startswith('path'):
            return PathSuiteModel(kind, option[len('path:'):])
        else:
            abort('unknown suitemodel type: ' + option)

    @staticmethod
    def parse_options():
        # suite-specific args may match the known args so there is no way at this early stage
        # to use ArgParser to handle the suite model global arguments, so we just do it manually.
        def _get_argvalue(arg, args, i):
            if i < len(args):
                return args[i]
            else:
                abort('value expected with ' + arg)

        args = sys.argv[1:]
        if len(args) == 0:
            _argParser.print_help()
            sys.exit(0)

        if len(args) == 1:
            if args[0] == '--version':
                print 'mx version ' + str(version)
                sys.exit(0)
            if args[0] == '--help' or args[0] == '-h':
                _argParser.print_help()
                sys.exit(0)

        # set defaults
        env_src_suitemodel = os.environ.get('MX_SRC_SUITEMODEL')
        env_dst_suitemodel = os.environ.get('MX_DST_SUITEMODEL')
        src_suitemodel_arg = 'sibling' if env_src_suitemodel is None else env_src_suitemodel
        dst_suitemodel_arg = 'sibling' if env_dst_suitemodel is None else env_dst_suitemodel
        suitemap_arg = None
        env_primary_suite_path = os.environ.get('MX_PRIMARY_SUITE_PATH')
        global _primary_suite_path

        i = 0
        while i < len(args):
            arg = args[i]
            if arg == '--src-suitemodel':
                src_suitemodel_arg = _get_argvalue(arg, args, i + 1)
            elif arg == '--dst-suitemodel':
                dst_suitemodel_arg = _get_argvalue(arg, args, i + 1)
            elif arg == '--suitemap':
                suitemap_arg = _get_argvalue(arg, args, i + 1)
            elif arg == '-w':
                # to get warnings on suite loading issues before command line is parsed
                global _warn
                _warn = True
            elif arg == '--primary-suite-path':
                _primary_suite_path = os.path.abspath(_get_argvalue(arg, args, i + 1))
            i = i + 1

        os.environ['MX_SRC_SUITEMODEL'] = src_suitemodel_arg
        global _src_suitemodel
        _src_suitemodel = SuiteModel.set_suitemodel("src", src_suitemodel_arg, suitemap_arg)
        os.environ['MX_DST_SUITEMODEL'] = dst_suitemodel_arg
        global _dst_suitemodel
        _dst_suitemodel = SuiteModel.set_suitemodel("dst", dst_suitemodel_arg, suitemap_arg)
        if _primary_suite_path is None:
            if env_primary_suite_path is not None:
                _primary_suite_path = env_primary_suite_path

class SiblingSuiteModel(SuiteModel):
    """All suites are siblings in the same parent directory, recorded as _suiteRootDir"""
    def __init__(self, kind, suiteRootDir, option, suitemap):
        SuiteModel.__init__(self, kind)
        self._suiteRootDir = suiteRootDir
        self._create_suitenamemap(option[len('sibling:'):], suitemap)

    def find_suite_dir(self, name):
        return self._search_dir(self._suiteRootDir, self._mxDirName(name))

    def set_primary_dir(self, d):
        SuiteModel.set_primary_dir(self, d)
        self._suiteRootDir = dirname(d)

    def importee_dir(self, importer_dir, suite_import, check_alternate=True):
        suitename = suite_import.name
        if self.suitenamemap.has_key(suitename):
            suitename = self.suitenamemap[suitename]
        path = join(dirname(importer_dir), suitename)
        return self._check_exists(suite_import, path, check_alternate)

class NestedImportsSuiteModel(SuiteModel):
    """Imported suites are all siblings in an 'imported_suites' directory of the primary suite"""
    def _imported_suites_dirname(self):
        return "imported_suites"

    def __init__(self, kind, primaryDir, option, suitemap):
        SuiteModel.__init__(self, kind)
        self._primaryDir = primaryDir
        self._create_suitenamemap(option[len('nested:'):], suitemap)

    def find_suite_dir(self, name):
        return self._search_dir(join(self._primaryDir, self._imported_suites_dirname()), self._mxDirName(name))

    def importee_dir(self, importer_dir, suite_import, check_alternate=True):
        suitename = suite_import.name
        if self.suitenamemap.has_key(suitename):
            suitename = self.suitenamemap[suitename]
        if basename(importer_dir) == basename(self._primaryDir):
            # primary is importer
            this_imported_suites_dirname = join(importer_dir, self._imported_suites_dirname())
            if not exists(this_imported_suites_dirname):
                os.mkdir(this_imported_suites_dirname)
            path = join(this_imported_suites_dirname, suitename)
        else:
            path = join(dirname(importer_dir), suitename)
        return self._check_exists(suite_import, path, check_alternate)

    def nestedsuites_dirname(self):
        return self._imported_suites_dirname()

class PathSuiteModel(SuiteModel):
    """The most general model. Uses a map from suitename to URL/path provided by the user"""
    def __init__(self, kind, path):
        SuiteModel.__init__(self, kind)
        paths = path.split(',')
        self.suit_to_url = {}
        for path in paths:
            pair = path.split('=')
            if len(pair) > 1:
                suitename = pair[0]
                suiteurl = pair[1]
            else:
                suitename = basename(pair[0])
                suiteurl = pair[0]
            self.suit_to_url[suitename] = suiteurl

    def find_suite_dir(self, suitename):
        if self.suit_to_url.has_key(suitename):
            return self.suit_to_url[suitename]
        else:
            return None

    def importee_dir(self, importer_dir, suite_import):
        # since this is completely explicit, we pay no attention to any suite_import.alternate
        suitename = suite_import.name
        if suitename in self.suit_to_url:
            return self.suit_to_url[suitename]
        else:
            abort('suite ' + suitename + ' not found')

class SuiteImport:
    def __init__(self, name, version, alternate):
        self.name = name
        self.version = version
        self.alternate = alternate

    @staticmethod
    def parse_specification(specification):
        parts = specification.split(',')
        name = parts[0]
        alternate = None
        if len(parts) > 1:
            version = parts[1]
            if len(version) == 0:
                version = None
            if len(parts) > 2:
                alternate = parts[2]
        else:
            version = None
        return SuiteImport(name, version, alternate)

    @staticmethod
    def tostring(name, version=None, alternate=None):
        result = name
        if version:
            result = result + ',' + version
        if alternate is not None:
            result = result + ',' + alternate
        return result

    def __str__(self):
        return SuiteImport.tostring(self.name, self.version, self.alternate)

def _load_suite_dict(mxDir):

    suffix = 1
    suite = None
    dictName = 'suite'

    def expand(value, context):
        if isinstance(value, types.DictionaryType):
            for n, v in value.iteritems():
                value[n] = expand(v, context + [n])
        elif isinstance(value, types.ListType):
            for i in range(len(value)):
                value[i] = expand(value[i], context + [str(i)])
        else:
            if not isinstance(value, types.StringTypes):
                abort('value of ' + '.'.join(context) + ' is of unexpected type ' + str(type(value)))
            value = expandvars(value)
            if '$' in value or '%' in value:
                abort('value of ' + '.'.join(context) + ' contains an undefined environment variable: ' + value)

        return value

    moduleName = 'suite'
    modulePath = join(mxDir, moduleName + '.py')
    while exists(modulePath):

        savedModule = sys.modules.get(moduleName)
        if savedModule:
            warn(modulePath + ' conflicts with ' + savedModule.__file__)
        # temporarily extend the Python path
        sys.path.insert(0, mxDir)

        snapshot = frozenset(sys.modules.keys())
        module = __import__(moduleName)

        if savedModule:
            # restore the old module into the module name space
            sys.modules[moduleName] = savedModule
        else:
            # remove moduleName from the module name space
            sys.modules.pop(moduleName)

        # For now fail fast if extra modules were loaded.
        # This can later be relaxed to simply remove the extra modules
        # from the sys.modules name space if necessary.
        extraModules = frozenset(sys.modules.keys()) - snapshot
        assert len(extraModules) == 0, 'loading ' + modulePath + ' caused extra modules to be loaded: ' + ', '.join([m for m in extraModules])

        # revert the Python path
        del sys.path[0]

        if not hasattr(module, dictName):
            abort(modulePath + ' must define a variable named "' + dictName + '"')
        d = expand(getattr(module, dictName), [dictName])
        sections = ['projects', 'libraries', 'jrelibraries', 'distributions'] + (['distribution_extensions'] if suite else ['name', 'mxversion'])
        unknown = frozenset(d.keys()) - frozenset(sections)
        if unknown:
            abort(modulePath + ' defines unsupported suite sections: ' + ', '.join(unknown))

        if suite is None:
            suite = d
        else:
            for s in sections:
                existing = suite.get(s)
                additional = d.get(s)
                if additional:
                    if not existing:
                        suite[s] = additional
                    else:
                        conflicting = frozenset(additional.keys()) & frozenset(existing.keys())
                        if conflicting:
                            abort(modulePath + ' redefines: ' + ', '.join(conflicting))
                        existing.update(additional)
            distExtensions = d.get('distribution_extensions')
            if distExtensions:
                existing = suite['distributions']
                for n, attrs in distExtensions.iteritems():
                    original = existing.get(n)
                    if not original:
                        abort('cannot extend non-existing distribution ' + n)
                    for k, v in attrs.iteritems():
                        if k != 'dependencies':
                            abort('Only the dependencies of distribution ' + n + ' can be extended')
                        if not isinstance(v, types.ListType):
                            abort('distribution_extensions.' + n + '.dependencies must be a list')
                        original['dependencies'] += v

        dictName = 'extra'
        moduleName = 'suite' + str(suffix)
        modulePath = join(mxDir, moduleName + '.py')

        deprecatedModulePath = join(mxDir, 'projects' + str(suffix) + '.py')
        if exists(deprecatedModulePath):
            abort('Please rename ' + deprecatedModulePath + ' to ' + modulePath)

        suffix = suffix + 1

    return suite, modulePath

class Suite:
    def __init__(self, mxDir, primary, load=True):
        self.dir = dirname(mxDir)
        self.mxDir = mxDir
        self.projects = []
        self.libs = []
        self.jreLibs = []
        self.dists = []
        self.imports = []
        self.commands = None
        self.primary = primary
        self.requiredMxVersion = None
        self.name = _suitename(mxDir)  # validated in _load_projects
        self.post_init = False
        if load:
            # load suites bottom up to make sure command overriding works properly
            self._load_imports()
            self._load_env()
            self._load_commands()
        _suites[self.name] = self

    def __str__(self):
        return self.name

    def version(self, abortOnError=True):
        # we do not cache the version
        return _hg.tip(self.dir, abortOnError)

    def _load_projects(self):
        suitePyFile = join(self.mxDir, 'suite.py')
        if not exists(suitePyFile):
            return

        suiteDict, _ = _load_suite_dict(self.mxDir)

        if suiteDict.get('name') is not None and suiteDict.get('name') != self.name:
            abort('suite name in project file does not match ' + _suitename(self.mxDir))

        if suiteDict.has_key('mxversion'):
            try:
                self.requiredMxVersion = VersionSpec(suiteDict['mxversion'])
            except AssertionError as ae:
                abort('Exception while parsing "mxversion" in project file: ' + str(ae))

        def check_suiteDict(key):
            return dict() if suiteDict.get(key) is None else suiteDict[key]

        libsMap = check_suiteDict('libraries')
        jreLibsMap = check_suiteDict('jrelibraries')
        projsMap = check_suiteDict('projects')
        distsMap = check_suiteDict('distributions')

        def pop_list(attrs, name, context):
            v = attrs.pop(name, None)
            if not v:
                return []
            if not isinstance(v, list):
                abort('Attribute "' + name + '" for ' + context + ' must be a list')
            return v

        for name, attrs in sorted(projsMap.iteritems()):
            context = 'project ' + name
            srcDirs = pop_list(attrs, 'sourceDirs', context)
            deps = pop_list(attrs, 'dependencies', context)
            ap = pop_list(attrs, 'annotationProcessors', context)
            javaCompliance = attrs.pop('javaCompliance', None)
            subDir = attrs.pop('subDir', None)
            if subDir is None:
                d = join(self.dir, name)
            else:
                d = join(self.dir, subDir, name)
            workingSets = attrs.pop('workingSets', None)
            p = Project(self, name, srcDirs, deps, javaCompliance, workingSets, d)
            p.checkstyleProj = attrs.pop('checkstyle', name)
            p.native = attrs.pop('native', '') == 'true'
            p.checkPackagePrefix = attrs.pop('checkPackagePrefix', 'true') == 'true'
            if not p.native and p.javaCompliance is None:
                abort('javaCompliance property required for non-native project ' + name)
            if len(ap) > 0:
                p._declaredAnnotationProcessors = ap
            p.__dict__.update(attrs)
            self.projects.append(p)

        for name, attrs in sorted(jreLibsMap.iteritems()):
            jar = attrs.pop('jar')
            # JRE libraries are optional by default
            optional = attrs.pop('optional', 'true') != 'false'
            l = JreLibrary(self, name, jar, optional)
            self.jreLibs.append(l)

        for name, attrs in sorted(libsMap.iteritems()):
            context = 'library ' + name
            if "|" in name:
                if name.count('|') != 2:
                    abort("Format error in library name: " + name + "\nsyntax: libname|os-platform|architecture")
                name, platform, architecture = name.split("|")
                if platform != get_os() or architecture != get_arch():
                    continue
            path = attrs.pop('path')
            urls = pop_list(attrs, 'urls', context)
            sha1 = attrs.pop('sha1', None)
            sourcePath = attrs.pop('sourcePath', None)
            sourceUrls = pop_list(attrs, 'sourceUrls', context)
            sourceSha1 = attrs.pop('sourceSha1', None)
            deps = pop_list(attrs, 'dependencies', context)
            # Add support optional libraries once we have a good use case
            optional = False
            l = Library(self, name, path, optional, urls, sha1, sourcePath, sourceUrls, sourceSha1, deps)
            l.__dict__.update(attrs)
            self.libs.append(l)

        for name, attrs in sorted(distsMap.iteritems()):
            context = 'distribution ' + name
            path = attrs.pop('path')
            sourcesPath = attrs.pop('sourcesPath', None)
            deps = pop_list(attrs, 'dependencies', context)
            mainClass = attrs.pop('mainClass', None)
            exclDeps = pop_list(attrs, 'exclude', context)
            distDeps = pop_list(attrs, 'distDependencies', context)
            javaCompliance = attrs.pop('javaCompliance', None)
            d = Distribution(self, name, path, sourcesPath, deps, mainClass, exclDeps, distDeps, javaCompliance)
            d.__dict__.update(attrs)
            self.dists.append(d)

        # Create a distribution for each project that defines annotation processors
        for p in self.projects:
            annotationProcessors = None
            for srcDir in p.source_dirs():
                configFile = join(srcDir, 'META-INF', 'services', 'javax.annotation.processing.Processor')
                if exists(configFile):
                    with open(configFile) as fp:
                        annotationProcessors = [ap.strip() for ap in fp]
                        if len(annotationProcessors) != 0:
                            for ap in annotationProcessors:
                                if not ap.startswith(p.name):
                                    abort(ap + ' in ' + configFile + ' does not start with ' + p.name)
            if annotationProcessors:
                dname = p.name.replace('.', '_').upper()
                apDir = join(p.dir, 'ap')
                path = join(apDir, p.name + '.jar')
                sourcesPath = None
                deps = [p.name]
                mainClass = None
                exclDeps = []
                distDeps = []
                javaCompliance = None
                d = Distribution(self, dname, path, sourcesPath, deps, mainClass, exclDeps, distDeps, javaCompliance, True)
                d.subDir = os.path.relpath(os.path.dirname(p.dir), self.dir)
                self.dists.append(d)
                p.definedAnnotationProcessors = annotationProcessors
                p.definedAnnotationProcessorsDist = d
                d.definingProject = p

                # Restrict exported annotation processors to those explicitly defined by the project
                def _refineAnnotationProcessorServiceConfig(dist):
                    aps = dist.definingProject.definedAnnotationProcessors
                    apsJar = dist.path
                    config = 'META-INF/services/javax.annotation.processing.Processor'
                    with zipfile.ZipFile(apsJar, 'r') as zf:
                        currentAps = zf.read(config).split()
                    if currentAps != aps:
                        logv('[updating ' + config + ' in ' + apsJar + ']')
                        with Archiver(apsJar) as arc:
                            with zipfile.ZipFile(apsJar, 'r') as lp:
                                for arcname in lp.namelist():
                                    if arcname == config:
                                        arc.zf.writestr(arcname, '\n'.join(aps))
                                    else:
                                        arc.zf.writestr(arcname, lp.read(arcname))
                d.add_update_listener(_refineAnnotationProcessorServiceConfig)
                self.dists.append(d)

        if self.name is None:
            abort('Missing "suite=<name>" in ' + suitePyFile)

    def _commands_name(self):
        return 'mx_' + self.name.replace('-', '_')

    def _find_commands(self, name):
        commandsPath = join(self.mxDir, name + '.py')
        if exists(commandsPath):
            return name
        else:
            return None

    def _load_commands(self):
        commandsName = self._find_commands(self._commands_name())
        if commandsName is None:
            # backwards compatibility
            commandsName = self._find_commands('commands')
        if commandsName is not None:
            if commandsName in sys.modules:
                abort(commandsName + '.py in suite ' + self.name + ' duplicates ' + sys.modules[commandsName].__file__)
            # temporarily extend the Python path
            sys.path.insert(0, self.mxDir)
            mod = __import__(commandsName)

            self.commands = sys.modules.pop(commandsName)
            sys.modules[commandsName] = self.commands

            # revert the Python path
            del sys.path[0]

            if not hasattr(mod, 'mx_init'):
                abort(commandsName + '.py in suite ' + self.name + ' must define an mx_init(suite) function')
            if hasattr(mod, 'mx_post_parse_cmd_line'):
                self.mx_post_parse_cmd_line = mod.mx_post_parse_cmd_line

            mod.mx_init(self)
            self.commands = mod

    def _imports_file(self):
        return join(self.mxDir, 'imports')

    def import_timestamp(self):
        return TimeStampFile(self._imports_file())

    def visit_imports(self, visitor, **extra_args):
        """
        Visitor support for the imports file.
        For each line of the imports file that specifies an import, the visitor function is
        called with this suite, a SuiteImport instance created from the line and any extra args
        passed to this call. In addition, if extra_args contains a key 'update_versions' that is True,
        a StringIO value is added to extra_args with key 'updated_imports', and the visitor is responsible
        for writing a (possibly) updated import line to the file, and the file is (possibly) updated after
        all imports are processed.
        N.B. There is no built-in support for avoiding visiting the same suite multiple times,
        as this function only visits the imports of a single suite. If a (recursive) visitor function
        wishes to visit a suite exactly once, it must manage that through extra_args.
        """
        importsFile = self._imports_file()
        if exists(importsFile):
            update_versions = extra_args.has_key('update_versions') and extra_args['update_versions']
            out = StringIO.StringIO() if update_versions else None
            extra_args['updated_imports'] = out
            with open(importsFile) as f:
                for line in f:
                    sline = line.strip()
                    if len(sline) == 0 or sline.startswith('#'):
                        if out is not None:
                            out.write(sline + '\n')
                        continue
                    suite_import = SuiteImport.parse_specification(line.strip())
                    visitor(self, suite_import, **extra_args)

            if out is not None:
                update_file(importsFile, out.getvalue())

    @staticmethod
    def _find_and_loadsuite(importing_suite, suite_import, **extra_args):
        """visitor for the initial suite load"""
        for s in _suites.itervalues():
            if s.name == suite_import.name:
                return s
        importMxDir = _src_suitemodel.find_suite_dir(suite_import.name)
        if importMxDir is None:
            fail = False
            if suite_import.alternate is not None:
                _hg.check()
                cmd = ['hg', 'clone']
                if suite_import.version is not None:
                    cmd.append('-r')
                    cmd.append(suite_import.version)
                cmd.append(suite_import.alternate)
                cmd.append(_src_suitemodel.importee_dir(importing_suite.dir, suite_import, check_alternate=False))
                try:
                    subprocess.check_output(cmd)
                    importMxDir = _src_suitemodel.find_suite_dir(suite_import.name)
                    if importMxDir is None:
                        # wasn't a suite after all
                        fail = True
                except subprocess.CalledProcessError:
                    fail = True
            else:
                fail = True

            if fail:
                if extra_args.has_key("dynamicImport") and extra_args["dynamicImport"]:
                    return None
                else:
                    abort('import ' + suite_import.name + ' not found')
        importing_suite.imports.append(suite_import)
        return Suite(importMxDir, False)
        # we do not check at this stage whether the tip version of imported_suite
        # matches that of the import, since during development, this can and will change

    def import_suite(self, name, version=None, alternate=None):
        """Dynamic import of a suite. Returns None if the suite cannot be found"""
        suite_import = SuiteImport(name, version, alternate)
        imported_suite = Suite._find_and_loadsuite(self, suite_import, dynamicImport=True)
        if imported_suite:
            # if alternate is set, force the import to version in case it already existed
            if alternate:
                if version:
                    run(['hg', '-R', imported_suite.dir, 'pull', '-r', suite_import.version, '-u', alternate])
                else:
                    run(['hg', '-R', imported_suite.dir, 'pull', '-u', alternate])
            if not imported_suite.post_init:
                imported_suite._post_init()
        return imported_suite

    def _load_imports(self):
        self.visit_imports(self._find_and_loadsuite)

    def _load_env(self):
        e = join(self.mxDir, 'env')
        if exists(e):
            with open(e) as f:
                lineNum = 0
                for line in f:
                    lineNum = lineNum + 1
                    line = line.strip()
                    if len(line) != 0 and line[0] != '#':
                        if not '=' in line:
                            abort(e + ':' + str(lineNum) + ': line does not match pattern "key=value"')
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = expandvars_in_property(value.strip())

    def _post_init(self):
        self._load_projects()
        if self.requiredMxVersion is None:
            warn("This suite does not express any required mx version. Consider adding 'mxversion=<version>' to your projects file.")
        elif self.requiredMxVersion > version:
            abort("This suite requires mx version " + str(self.requiredMxVersion) + " while your current mx version is " + str(version) + ". Please update mx.")
        # set the global data structures, checking for conflicts unless _check_global_structures is False
        for p in self.projects:
            existing = _projects.get(p.name)
            if existing is not None and _check_global_structures:
                abort('cannot override project  ' + p.name + ' in ' + p.dir + " with project of the same name in  " + existing.dir)
            if not p.name in _opts.ignored_projects:
                _projects[p.name] = p
        for l in self.libs:
            existing = _libs.get(l.name)
            # Check that suites that define same library are consistent
            if existing is not None and existing != l and _check_global_structures:
                abort('inconsistent library redefinition of ' + l.name + ' in ' + existing.suite.dir + ' and ' + l.suite.dir)
            _libs[l.name] = l
        for l in self.jreLibs:
            existing = _jreLibs.get(l.name)
            # Check that suites that define same library are consistent
            if existing is not None and existing != l:
                abort('inconsistent JRE library redefinition of ' + l.name + ' in ' + existing.suite.dir + ' and ' + l.suite.dir)
            _jreLibs[l.name] = l
        for d in self.dists:
            existing = _dists.get(d.name)
            if existing is not None and _check_global_structures:
                # allow redefinition, so use path from existing
                # abort('cannot redefine distribution  ' + d.name)
                warn('distribution ' + d.name + ' redefined')
                d.path = existing.path
            _dists[d.name] = d

        if hasattr(self, 'mx_post_parse_cmd_line'):
            self.mx_post_parse_cmd_line(_opts)
        self.post_init = True

    @staticmethod
    def _post_init_visitor(importing_suite, suite_import, **extra_args):
        imported_suite = suite(suite_import.name)
        if not imported_suite.post_init:
            imported_suite.visit_imports(imported_suite._post_init_visitor)
            imported_suite._post_init()

    def _depth_first_post_init(self):
        '''depth first _post_init driven by imports graph'''
        self.visit_imports(self._post_init_visitor)
        self._post_init()

    @staticmethod
    def _projects_recursive(importing_suite, imported_suite, projects, visitmap):
        if visitmap.has_key(imported_suite.name):
            return
        projects += imported_suite.projects
        visitmap[imported_suite.name] = True
        imported_suite.visit_imports(importing_suite._projects_recursive_visitor, projects=projects, visitmap=visitmap)

    @staticmethod
    def _projects_recursive_visitor(importing_suite, suite_import, projects, visitmap, **extra_args):
        importing_suite._projects_recursive(importing_suite, suite(suite_import.name), projects, visitmap)

    def projects_recursive(self):
        """return all projects including those in imported suites"""
        result = []
        result += self.projects
        visitmap = dict()
        self.visit_imports(self._projects_recursive_visitor, projects=result, visitmap=visitmap,)
        return result


class XMLElement(xml.dom.minidom.Element):
    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "<" + self.tagName)

        attrs = self._get_attributes()
        a_names = attrs.keys()
        a_names.sort()

        for a_name in a_names:
            writer.write(" %s=\"" % a_name)
            xml.dom.minidom._write_data(writer, attrs[a_name].value)
            writer.write("\"")
        if self.childNodes:
            if not self.ownerDocument.padTextNodeWithoutSiblings and len(self.childNodes) == 1 and isinstance(self.childNodes[0], xml.dom.minidom.Text):
                # if the only child of an Element node is a Text node, then the
                # text is printed without any indentation or new line padding
                writer.write(">")
                self.childNodes[0].writexml(writer)
                writer.write("</%s>%s" % (self.tagName, newl))
            else:
                writer.write(">%s" % (newl))
                for node in self.childNodes:
                    node.writexml(writer, indent + addindent, addindent, newl)
                writer.write("%s</%s>%s" % (indent, self.tagName, newl))
        else:
            writer.write("/>%s" % (newl))

class XMLDoc(xml.dom.minidom.Document):

    def __init__(self):
        xml.dom.minidom.Document.__init__(self)
        self.current = self
        self.padTextNodeWithoutSiblings = False

    def createElement(self, tagName):
        # overwritten to create XMLElement
        e = XMLElement(tagName)
        e.ownerDocument = self
        return e

    def comment(self, txt):
        self.current.appendChild(self.createComment(txt))

    def open(self, tag, attributes=None, data=None):
        if attributes is None:
            attributes = {}
        element = self.createElement(tag)
        for key, value in attributes.items():
            element.setAttribute(key, value)
        self.current.appendChild(element)
        self.current = element
        if data is not None:
            element.appendChild(self.createTextNode(data))
        return self

    def close(self, tag):
        assert self.current != self
        assert tag == self.current.tagName, str(tag) + ' != ' + self.current.tagName
        self.current = self.current.parentNode
        return self

    def element(self, tag, attributes=None, data=None):
        if attributes is None:
            attributes = {}
        return self.open(tag, attributes, data).close(tag)

    def xml(self, indent='', newl='', escape=False, standalone=None):
        assert self.current == self
        result = self.toprettyxml(indent, newl, encoding="UTF-8")
        if escape:
            entities = {'"':  "&quot;", "'":  "&apos;", '\n': '&#10;'}
            result = xml.sax.saxutils.escape(result, entities)
        if standalone is not None:
            result = result.replace('encoding="UTF-8"?>', 'encoding="UTF-8" standalone="' + str(standalone) + '"?>')
        return result

class GateTask:
    def __init__(self, title):
        self.start = time.time()
        self.title = title
        self.end = None
        self.duration = None
        log(time.strftime('gate: %d %b %Y %H:%M:%S: BEGIN: ') + title)
    def stop(self):
        self.end = time.time()
        self.duration = datetime.timedelta(seconds=self.end - self.start)
        log(time.strftime('gate: %d %b %Y %H:%M:%S: END:   ') + self.title + ' [' + str(self.duration) + ']')
        return self
    def abort(self, codeOrMessage):
        self.end = time.time()
        self.duration = datetime.timedelta(seconds=self.end - self.start)
        log(time.strftime('gate: %d %b %Y %H:%M:%S: ABORT: ') + self.title + ' [' + str(self.duration) + ']')
        abort(codeOrMessage)
        return self

def _basic_gate_body(args, tasks):
    return

def _add_omit_clean_args(parser):
    parser.add_argument('-j', '--omit-java-clean', action='store_false', dest='cleanJava', help='omit cleaning Java native code')
    parser.add_argument('-n', '--omit-native-clean', action='store_false', dest='cleanNative', help='omit cleaning and building native code')
    parser.add_argument('-e', '--omit-ide-clean', action='store_false', dest='cleanIDE', help='omit ideclean/ideinit')
    parser.add_argument('-d', '--omit-dist-clean', action='store_false', dest='cleanDist', help='omit cleaning distributions')
    parser.add_argument('-o', '--omit-clean', action='store_true', dest='noClean', help='equivalent to -j -n -e')

def gate(args, gate_body=_basic_gate_body, parser=None):
    """run the tests used to validate a push
    This provides a generic gate that does all the standard things.
    Additional tests can be provided by passing a custom 'gate_body'.

    If this command exits with a 0 exit code, then the gate passed."""

    suppliedParser = parser is not None
    parser = parser if suppliedParser else ArgumentParser(prog='mx gate')

    _add_omit_clean_args(parser)
    parser.add_argument('-p', '--omit-pylint', action='store_false', dest='pylint', help='omit pylint check')
    if suppliedParser:
        parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    if args.noClean:
        args.cleanIDE = False
        args.cleanJava = False
        args.cleanNative = False
        args.cleanDist = False

    tasks = []
    total = GateTask('Gate')

    try:
        if args.pylint:
            t = GateTask('Pylint')
            pylint([])
            tasks.append(t.stop())

        t = GateTask('Clean')
        cleanArgs = []
        if not args.cleanNative:
            cleanArgs.append('--no-native')
        if not args.cleanJava:
            cleanArgs.append('--no-java')
        if not args.cleanDist:
            cleanArgs.append('--no-dist')
        command_function('clean')(cleanArgs)
        tasks.append(t.stop())

        if args.cleanIDE:
            t = GateTask('IDEConfigCheck')
            command_function('ideclean')([])
            command_function('ideinit')([])
            tasks.append(t.stop())

        eclipse_exe = os.environ.get('ECLIPSE_EXE')
        if eclipse_exe is not None:
            t = GateTask('CodeFormatCheck')
            if eclipseformat(['-e', eclipse_exe]) != 0:
                t.abort('Formatter modified files - run "mx eclipseformat", check in changes and repush')
            tasks.append(t.stop())

        t = GateTask('Canonicalization Check')
        log(time.strftime('%d %b %Y %H:%M:%S - Ensuring mx/projects files are canonicalized...'))
        if canonicalizeprojects([]) != 0:
            t.abort('Rerun "mx canonicalizeprojects" and check-in the modified mx/projects files.')
        tasks.append(t.stop())

        t = GateTask('BuildJava')
        # Make sure we use any overridden build command
        command_function('build')([])
        tasks.append(t.stop())

        gate_body(args, tasks)

    except KeyboardInterrupt:
        total.abort(1)

    except BaseException as e:
        import traceback
        traceback.print_exc()
        total.abort(str(e))

    total.stop()

    log('Gate task times:')
    for t in tasks:
        log('  ' + str(t.duration) + '\t' + t.title)
    log('  =======')
    log('  ' + str(total.duration))

def _bench_test_common(args, parser, suppliedParser):
    parser.add_argument('--J', dest='vm_args', help='target VM arguments (e.g. --J @-dsa)', metavar='@<args>')
    _add_omit_clean_args(parser)
    if suppliedParser:
        parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    if args.noClean:
        args.cleanIDE = False
        args.cleanJava = False
        args.cleanNative = False
        args.cleanDist = False

    cleanArgs = []
    if not args.cleanNative:
        cleanArgs.append('--no-native')
    if not args.cleanJava:
        cleanArgs.append('--no-java')
    if not args.cleanDist:
        cleanArgs.append('--no-dist')
    command_function('clean')(cleanArgs)

    if args.cleanIDE:
        command_function('ideclean')([])
        command_function('ideinit')([])

    command_function('build')([])
    return args


def _basic_bench_harness(args, vmArgs):
    return 0

def bench(args, harness=_basic_bench_harness, parser=None):
    '''run benchmarks (suite-specfic) after clean build (optional)'''
    suppliedParser = parser is not None
    parser = parser if suppliedParser else ArgumentParser(prog='mx bench')
    args = _bench_test_common(args, parser, suppliedParser)
    return harness(args, args.vm_args)

def _basic_test_harness(args, vmArgs):
    return 0

def test(args, harness=_basic_test_harness, parser=None):
    '''run tests (suite-specific) after clean build (optional)'''
    suppliedParser = parser is not None
    parser = parser if suppliedParser else ArgumentParser(prog='mx test')
    args = _bench_test_common(args, parser, suppliedParser)
    return harness(args, args.vm_args)

def get_jython_os():
    from java.lang import System as System
    os_name = System.getProperty('os.name').lower()
    if System.getProperty('isCygwin'):
        return 'cygwin'
    elif os_name.startswith('mac'):
        return 'darwin'
    elif os_name.startswith('linux'):
        return 'linux'
    elif os_name.startswith('sunos'):
        return 'solaris'
    elif os_name.startswith('win'):
        return 'windows'
    else:
        abort('Unknown operating system ' + os_name)

def get_os():
    """
    Get a canonical form of sys.platform.
    """
    if is_jython():
        return get_jython_os()
    elif sys.platform.startswith('darwin'):
        return 'darwin'
    elif sys.platform.startswith('linux'):
        return 'linux'
    elif sys.platform.startswith('sunos'):
        return 'solaris'
    elif sys.platform.startswith('win32'):
        return 'windows'
    elif sys.platform.startswith('cygwin'):
        return 'cygwin'
    else:
        abort('Unknown operating system ' + sys.platform)

def _cygpathU2W(p):
    """
    Translate a path from unix-style to windows-style.
    This method has no effects on other platforms than cygwin.
    """
    if p is None or get_os() != "cygwin":
        return p
    return subprocess.check_output(['cygpath', '-a', '-w', p]).strip()

def _cygpathW2U(p):
    """
    Translate a path from windows-style to unix-style.
    This method has no effects on other platforms than cygwin.
    """
    if p is None or get_os() != "cygwin":
        return p
    return subprocess.check_output(['cygpath', '-a', '-u', p]).strip()

def _separatedCygpathU2W(p):
    """
    Translate a group of paths, separated by a path separator.
    unix-style to windows-style.
    This method has no effects on other platforms than cygwin.
    """
    if p is None or p == "" or get_os() != "cygwin":
        return p
    return ';'.join(map(_cygpathU2W, p.split(os.pathsep)))

def _separatedCygpathW2U(p):
    """
    Translate a group of paths, separated by a path separator.
    windows-style to unix-style.
    This method has no effects on other platforms than cygwin.
    """
    if p is None or p == "" or get_os() != "cygwin":
        return p
    return os.pathsep.join(map(_cygpathW2U, p.split(';')))

def get_arch():
    machine = platform.uname()[4]
    if machine in ['amd64', 'AMD64', 'x86_64', 'i86pc']:
        return 'amd64'
    if machine in ['sun4v', 'sun4u']:
        return 'sparcv9'
    if machine == 'i386' and get_os() == 'darwin':
        try:
            # Support for Snow Leopard and earlier version of MacOSX
            if subprocess.check_output(['sysctl', '-n', 'hw.cpu64bit_capable']).strip() == '1':
                return 'amd64'
        except OSError:
            # sysctl is not available
            pass
    abort('unknown or unsupported architecture: os=' + get_os() + ', machine=' + machine)

def suites(opt_limit_to_suite=False):
    """
    Get the list of all loaded suites.
    """
    if opt_limit_to_suite and _opts.specific_suites:
        result = []
        for s in _suites.values():
            if s.name in _opts.specific_suites:
                result.append(s)
        return result
    else:
        return _suites.values()

def createsuite(args):
    """create new suite in a subdirectory of cwd"""
    parser = ArgumentParser(prog='mx createsuite')
    parser.add_argument('--name', help='suite name', required=True)
    parser.add_argument('--py', action='store_true', help='create (empty) extensions file')
    args = parser.parse_args(args)

    suite_name = args.name
    if exists(suite_name):
        abort('suite directory already exists')
    os.mkdir(suite_name)
    mx_dot_suite_name = 'mx.' + suite_name
    mxDirPath = join(suite_name, mx_dot_suite_name)
    os.mkdir(mxDirPath)

    def update_file(template_file, target_file):
        with open(join(dirname(__file__), 'templates', template_file)) as f:
            content = f.read()
        with open(join(mxDirPath, target_file), 'w') as f:
            f.write(content.replace('MXPROJECT', mx_dot_suite_name))

    with open(join(mxDirPath, 'projects'), 'w') as f:
        f.write('suite=' + suite_name + '\n')
        f.write('mxversion=' + str(version) + '\n')

    update_file('hg-ignore', '.hgignore')

    _hg.check()
    run(['hg', 'init'], cwd=suite_name)

    if args.py:
        with open(join(mxDirPath, 'mx_' + suite_name + '.py'), 'w') as f:
            f.write('import mx\n\n')
            f.write('def mx_init(suite):\n')
            f.write('    commands = {\n')
            f.write('    }\n')
            f.write('    mx.update_commands(suite, commands)\n')

        update_file('eclipse-pyproject', '.project')
        update_file('eclipse-pydevproject', '.pydevproject')

def suite(name, fatalIfMissing=True):
    """
    Get the suite for a given name.
    """
    s = _suites.get(name)
    if s is None and fatalIfMissing:
        abort('suite named ' + name + ' not found')
    return s


def projects_from_names(projectNames):
    """
    Get the list of projects corresponding to projectNames; all projects if None
    """
    if projectNames is None:
        return projects()
    else:
        return [project(name) for name in projectNames]

def projects(opt_limit_to_suite=False):
    """
    Get the list of all loaded projects limited by --suite option if opt_limit_to_suite == True
    """

    sortedProjects = sorted(_projects.values(), key=lambda p: p.name)
    if opt_limit_to_suite:
        return _projects_opt_limit_to_suites(sortedProjects)
    else:
        return sortedProjects

def projects_opt_limit_to_suites():
    """
    Get the list of all loaded projects optionally limited by --suite option
    """
    return projects(True)

def _projects_opt_limit_to_suites(projects):
    if not _opts.specific_suites:
        return projects
    else:
        result = []
        for p in projects:
            s = p.suite
            if s.name in _opts.specific_suites:
                result.append(p)
        return result

def annotation_processors():
    """
    Get the list of all loaded projects that define an annotation processor.
    """
    global _annotationProcessors
    if _annotationProcessors is None:
        aps = set()
        for p in projects():
            for ap in p.annotation_processors():
                if project(ap, False):
                    aps.add(ap)
        _annotationProcessors = list(aps)
    return _annotationProcessors

def distribution(name, fatalIfMissing=True):
    """
    Get the distribution for a given name. This will abort if the named distribution does
    not exist and 'fatalIfMissing' is true.
    """
    d = _dists.get(name)
    if d is None and fatalIfMissing:
        abort('distribution named ' + name + ' not found')
    return d

def dependency(name, fatalIfMissing=True):
    """
    Get the project or library for a given name. This will abort if a project  or library does
    not exist for 'name' and 'fatalIfMissing' is true.
    """
    d = _projects.get(name)
    if d is None:
        d = _libs.get(name)
        if d is None:
            d = _jreLibs.get(name)
    if d is None and fatalIfMissing:
        if name in _opts.ignored_projects:
            abort('project named ' + name + ' is ignored')
        abort('project or library named ' + name + ' not found')
    return d

def project(name, fatalIfMissing=True):
    """
    Get the project for a given name. This will abort if the named project does
    not exist and 'fatalIfMissing' is true.
    """
    p = _projects.get(name)
    if p is None and fatalIfMissing:
        if name in _opts.ignored_projects:
            abort('project named ' + name + ' is ignored')
        abort('project named ' + name + ' not found')
    return p

def library(name, fatalIfMissing=True):
    """
    Gets the library for a given name. This will abort if the named library does
    not exist and 'fatalIfMissing' is true.
    """
    l = _libs.get(name)
    if l is None and fatalIfMissing:
        if _projects.get(name):
            abort(name + ' is a project, not a library')
        abort('library named ' + name + ' not found')
    return l

def _as_classpath(deps, resolve):
    cp = []
    if _opts.cp_prefix is not None:
        cp = [_opts.cp_prefix]
    for d in deps:
        d.append_to_classpath(cp, resolve)
    if _opts.cp_suffix is not None:
        cp += [_opts.cp_suffix]
    return os.pathsep.join(cp)

def classpath(names=None, resolve=True, includeSelf=True, includeBootClasspath=False):
    """
    Get the class path for a list of given dependencies and distributions, resolving each entry in the
    path (e.g. downloading a missing library) if 'resolve' is true.
    """
    if names is None:
        deps = sorted_deps(includeLibs=True)
        dists = list(_dists.values())
    else:
        deps = []
        dists = []
        if isinstance(names, types.StringTypes):
            names = [names]
        for n in names:
            dep = dependency(n, fatalIfMissing=False)
            if dep:
                dep.all_deps(deps, True, includeSelf)
            else:
                dist = distribution(n)
                if not dist:
                    abort('project, library or distribution named ' + n + ' not found')
                dists.append(dist)

    if len(dists):
        distsDeps = set()
        for d in dists:
            distsDeps.update(d.sorted_deps())

        # remove deps covered by a dist that will be on the class path
        deps = [d for d in deps if d not in distsDeps]

    result = _as_classpath(deps, resolve)

    # prepend distributions
    if len(dists):
        distsCp = os.pathsep.join(dist.path for dist in dists)
        if len(result):
            result = distsCp + os.pathsep + result
        else:
            result = distsCp

    if includeBootClasspath:
        result = os.pathsep.join([java().bootclasspath(), result])

    return result

def classpath_walk(names=None, resolve=True, includeSelf=True, includeBootClasspath=False):
    """
    Walks the resources available in a given classpath, yielding a tuple for each resource
    where the first member of the tuple is a directory path or ZipFile object for a
    classpath entry and the second member is the qualified path of the resource relative
    to the classpath entry.
    """
    cp = classpath(names, resolve, includeSelf, includeBootClasspath)
    for entry in cp.split(os.pathsep):
        if not exists(entry):
            continue
        if isdir(entry):
            for root, dirs, files in os.walk(entry):
                for d in dirs:
                    entryPath = join(root[len(entry) + 1:], d)
                    yield entry, entryPath
                for f in files:
                    entryPath = join(root[len(entry) + 1:], f)
                    yield entry, entryPath
        elif entry.endswith('.jar') or entry.endswith('.zip'):
            with zipfile.ZipFile(entry, 'r') as zf:
                for zi in zf.infolist():
                    entryPath = zi.filename
                    yield zf, entryPath

def sorted_deps(projectNames=None, includeLibs=False, includeJreLibs=False, includeAnnotationProcessors=False):
    """
    Gets projects and libraries sorted such that dependencies
    are before the projects that depend on them. Unless 'includeLibs' is
    true, libraries are omitted from the result.
    """
    projects = projects_from_names(projectNames)

    return sorted_project_deps(projects, includeLibs=includeLibs, includeJreLibs=includeJreLibs, includeAnnotationProcessors=includeAnnotationProcessors)

def sorted_dists():
    """
    Gets distributions sorted such that each distribution comes after
    any distributions it depends upon.
    """
    dists = []
    def add_dist(dist):
        if not dist in dists:
            for depDist in [distribution(name) for name in dist.distDependencies]:
                add_dist(depDist)
            if not dist in dists:
                dists.append(dist)

    for d in _dists.itervalues():
        add_dist(d)
    return dists

def sorted_project_deps(projects, includeLibs=False, includeJreLibs=False, includeAnnotationProcessors=False):
    deps = []
    for p in projects:
        p.all_deps(deps, includeLibs=includeLibs, includeJreLibs=includeJreLibs, includeAnnotationProcessors=includeAnnotationProcessors)
    return deps

class ArgParser(ArgumentParser):
    # Override parent to append the list of available commands
    def format_help(self):
        return ArgumentParser.format_help(self) + _format_commands()


    def __init__(self):
        self.java_initialized = False
        # this doesn't resolve the right way, but can't figure out how to override _handle_conflict_resolve in _ActionsContainer
        ArgumentParser.__init__(self, prog='mx', conflict_handler='resolve')

        self.add_argument('-v', action='store_true', dest='verbose', help='enable verbose output')
        self.add_argument('-V', action='store_true', dest='very_verbose', help='enable very verbose output')
        self.add_argument('-w', action='store_true', dest='warn', help='enable warning messages')
        self.add_argument('-p', '--primary-suite-path', help='set the primary suite directory', metavar='<path>')
        self.add_argument('--dbg', type=int, dest='java_dbg_port', help='make Java processes wait on <port> for a debugger', metavar='<port>')
        self.add_argument('-d', action='store_const', const=8000, dest='java_dbg_port', help='alias for "-dbg 8000"')
        self.add_argument('--backup-modified', action='store_true', help='backup generated files if they pre-existed and are modified')
        self.add_argument('--cp-pfx', dest='cp_prefix', help='class path prefix', metavar='<arg>')
        self.add_argument('--cp-sfx', dest='cp_suffix', help='class path suffix', metavar='<arg>')
        self.add_argument('--J', dest='java_args', help='Java VM arguments (e.g. --J @-dsa)', metavar='@<args>')
        self.add_argument('--Jp', action='append', dest='java_args_pfx', help='prefix Java VM arguments (e.g. --Jp @-dsa)', metavar='@<args>', default=[])
        self.add_argument('--Ja', action='append', dest='java_args_sfx', help='suffix Java VM arguments (e.g. --Ja @-dsa)', metavar='@<args>', default=[])
        self.add_argument('--user-home', help='users home directory', metavar='<path>', default=os.path.expanduser('~'))
        self.add_argument('--java-home', help='primary JDK directory (must be JDK 7 or later)', metavar='<path>')
        self.add_argument('--extra-java-homes', help='secondary JDK directories separated by "' + os.pathsep + '"', metavar='<path>')
        self.add_argument('--strict-compliance', action='store_true', dest='strict_compliance', help='Projects with an explicit compliance will only be built if a JDK exactly matching the compliance is available', default=False)
        self.add_argument('--ignore-project', action='append', dest='ignored_projects', help='name of project to ignore', metavar='<name>', default=[])
        self.add_argument('--kill-with-sigquit', action='store_true', dest='killwithsigquit', help='send sigquit first before killing child processes')
        self.add_argument('--suite', action='append', dest='specific_suites', help='limit command to given suite', default=[])
        self.add_argument('--src-suitemodel', help='mechanism for locating imported suites', metavar='<arg>', default='sibling')
        self.add_argument('--dst-suitemodel', help='mechanism for placing cloned/pushed suites', metavar='<arg>', default='sibling')
        self.add_argument('--suitemap', help='explicit remapping of suite names', metavar='<args>')
        self.add_argument('--primary', action='store_true', help='limit command to primary suite')
        self.add_argument('--no-download-progress', action='store_true', help='disable download progress meter')
        self.add_argument('--version', action='store_true', help='print version and exit')
        if get_os() != 'windows':
            # Time outs are (currently) implemented with Unix specific functionality
            self.add_argument('--timeout', help='timeout (in seconds) for command', type=int, default=0, metavar='<secs>')
            self.add_argument('--ptimeout', help='timeout (in seconds) for subprocesses', type=int, default=0, metavar='<secs>')

    def _parse_cmd_line(self, args=None):
        if args is None:
            args = sys.argv[1:]

        self.add_argument('commandAndArgs', nargs=REMAINDER, metavar='command args...')

        opts = self.parse_args()

        global _opts
        _opts = opts

        # Give the timeout options a default value to avoid the need for hasattr() tests
        opts.__dict__.setdefault('timeout', 0)
        opts.__dict__.setdefault('ptimeout', 0)

        if opts.very_verbose:
            opts.verbose = True

        if opts.user_home is None or opts.user_home == '':
            abort('Could not find user home. Use --user-home option or ensure HOME environment variable is set.')

        if opts.primary and _primary_suite:
            opts.specific_suites.append(_primary_suite.name)

        if opts.java_home:
            os.environ['JAVA_HOME'] = opts.java_home
        os.environ['HOME'] = opts.user_home

        if os.environ.get('STRICT_COMPLIANCE'):
            _opts.strict_compliance = True

        opts.ignored_projects = opts.ignored_projects + os.environ.get('IGNORED_PROJECTS', '').split(',')

        commandAndArgs = opts.__dict__.pop('commandAndArgs')
        return opts, commandAndArgs

    def _handle_conflict_resolve(self, action, conflicting_actions):
        self._handle_conflict_error(action, conflicting_actions)

def _format_commands():
    msg = '\navailable commands:\n\n'
    for cmd in sorted(_commands.iterkeys()):
        c, _ = _commands[cmd][:2]
        doc = c.__doc__
        if doc is None:
            doc = ''
        msg += ' {0:<20} {1}\n'.format(cmd, doc.split('\n', 1)[0])
    return msg + '\n'

_canceled_java_requests = set()

def java(requiredCompliance=None, purpose=None, cancel=None):
    """
    Get a JavaConfig object containing Java commands launch details.
    If requiredCompliance is None, the compliance level specified by --java-home/JAVA_HOME
    is returned. Otherwise, the JavaConfig exactly matching requiredCompliance is returned
    or None if there is no exact match.
    """

    global _default_java_home
    if cancel and (requiredCompliance, purpose) in _canceled_java_requests:
        return None

    if not requiredCompliance:
        if not _default_java_home:
            _default_java_home = _find_jdk(purpose=purpose, cancel=cancel)
            if not _default_java_home:
                assert cancel
                _canceled_java_requests.add((requiredCompliance, purpose))
        return _default_java_home

    if _opts.strict_compliance:
        complianceCheck = requiredCompliance.exactMatch
        desc = str(requiredCompliance)
    else:
        compVersion = VersionSpec(str(requiredCompliance))
        complianceCheck = lambda version: version >= compVersion
        desc = '>=' + str(requiredCompliance)

    for java in _extra_java_homes:
        if complianceCheck(java.version):
            return java

    jdk = _find_jdk(versionCheck=complianceCheck, versionDescription=desc, purpose=purpose, cancel=cancel)
    if jdk:
        assert jdk not in _extra_java_homes
        _extra_java_homes.append(jdk)
    else:
        assert cancel
        _canceled_java_requests.add((requiredCompliance, purpose))
    return jdk

def java_version(versionCheck, versionDescription=None, purpose=None):
    if _default_java_home and versionCheck(_default_java_home.version):
        return _default_java_home
    for java in _extra_java_homes:
        if versionCheck(java.version):
            return java
    jdk = _find_jdk(versionCheck, versionDescription, purpose)
    assert jdk not in _extra_java_homes
    _extra_java_homes.append(jdk)
    return jdk

def _find_jdk(versionCheck=None, versionDescription=None, purpose=None, cancel=None):
    if not versionCheck:
        versionCheck = lambda v: True
    assert not versionDescription or versionCheck
    if not versionCheck and not purpose:
        isDefaultJdk = True
    else:
        isDefaultJdk = False

    candidateJdks = []
    source = ''
    if _opts.java_home:
        candidateJdks.append(_opts.java_home)
        source = '--java-home'
    elif os.environ.get('JAVA_HOME'):
        candidateJdks.append(os.environ.get('JAVA_HOME'))
        source = 'JAVA_HOME'

    result = _find_jdk_in_candidates(candidateJdks, versionCheck, warn=True, source=source)
    if result:
        return result

    candidateJdks = []

    if _opts.extra_java_homes:
        candidateJdks += _opts.extra_java_homes.split(os.pathsep)
        source = '--extra-java-homes'
    elif os.environ.get('EXTRA_JAVA_HOMES'):
        candidateJdks += os.environ.get('EXTRA_JAVA_HOMES').split(os.pathsep)
        source = 'EXTRA_JAVA_HOMES'

    result = _find_jdk_in_candidates(candidateJdks, versionCheck, warn=True, source=source)
    if not result:
        candidateJdks = []
        source = ''

        if get_os() == 'darwin':
            base = '/Library/Java/JavaVirtualMachines'
            if exists(base):
                candidateJdks = [join(base, n, 'Contents/Home') for n in os.listdir(base)]
        elif get_os() == 'linux':
            base = '/usr/lib/jvm'
            if exists(base):
                candidateJdks = [join(base, n) for n in os.listdir(base)]
            base = '/usr/java'
            if exists(base):
                candidateJdks += [join(base, n) for n in os.listdir(base)]
        elif get_os() == 'solaris':
            base = '/usr/jdk/instances'
            if exists(base):
                candidateJdks = [join(base, n) for n in os.listdir(base)]
        elif get_os() == 'windows':
            base = r'C:\Program Files\Java'
            if exists(base):
                candidateJdks = [join(base, n) for n in os.listdir(base)]

        configs = _filtered_jdk_configs(candidateJdks, versionCheck)
    else:
        if not isDefaultJdk:
            return result
        configs = [result]

    if len(configs) > 1:
        if not is_interactive():
            msg = "Multiple possible choices for a JDK"
            if purpose:
                msg += ' for' + purpose
            msg += ': '
            if versionDescription:
                msg += '(' + versionDescription + ')'
            selected = configs[0]
            msg += ". Selecting " + str(selected)
            log(msg)
        else:
            msg = 'Please select a '
            if isDefaultJdk:
                msg += 'default '
            msg += 'JDK'
            if purpose:
                msg += ' for' + purpose
            msg += ': '
            if versionDescription:
                msg += '(' + versionDescription + ')'
            log(msg)
            choices = configs + ['<other>']
            if cancel:
                choices.append('Cancel (' + cancel + ')')
            selected = select_items(choices, allowMultiple=False)
            if isinstance(selected, types.StringTypes) and selected == '<other>':
                selected = None
            if isinstance(selected, types.StringTypes) and selected == 'Cancel (' + cancel + ')':
                return None
    elif len(configs) == 1:
        selected = configs[0]
        msg = 'Selected ' + str(selected) + ' as '
        if isDefaultJdk:
            msg += 'default'
        msg += 'JDK'
        if versionDescription:
            msg = msg + ' ' + versionDescription
        if purpose:
            msg += ' for' + purpose
        log(msg)
    else:
        msg = 'Could not find any JDK'
        if purpose:
            msg += ' for' + purpose
        msg += ' '
        if versionDescription:
            msg = msg + '(' + versionDescription + ')'
        log(msg)
        selected = None

    while not selected:
        jdkLocation = raw_input('Enter path of JDK: ')
        selected = _find_jdk_in_candidates([jdkLocation], versionCheck, warn=True)

    varName = 'JAVA_HOME' if isDefaultJdk else 'EXTRA_JAVA_HOMES'
    allowMultiple = not isDefaultJdk
    envPath = join(_primary_suite.mxDir, 'env')
    if is_interactive() and ask_yes_no('Persist this setting by adding "{0}={1}" to {2}'.format(varName, selected.jdk, envPath), 'y'):
        envLines = []
        with open(envPath) as fp:
            append = True
            for line in fp:
                if line.rstrip().startswith(varName):
                    _, currentValue = line.split('=', 1)
                    currentValue = currentValue.strip()
                    if not allowMultiple and currentValue:
                        if not ask_yes_no('{0} is already set to {1}, overwrite with {2}?'.format(varName, currentValue, selected.jdk), 'n'):
                            return selected
                        else:
                            line = varName + '=' + selected.jdk + os.linesep
                    else:
                        line = line.rstrip()
                        if currentValue:
                            line += os.pathsep
                        line += selected.jdk + os.linesep
                    append = False
                envLines.append(line)
        if append:
            envLines.append(varName + '=' + selected.jdk)

        with open(envPath, 'w') as fp:
            for line in envLines:
                fp.write(line)

    if varName == 'JAVA_HOME':
        os.environ['JAVA_HOME'] = selected.jdk

    return selected

def is_interactive():
    return sys.__stdin__.isatty()

def _filtered_jdk_configs(candidates, versionCheck, warn=False, source=None):
    filtered = []
    for candidate in candidates:
        try:
            config = JavaConfig(candidate)
            if versionCheck(config.version):
                filtered.append(config)
        except JavaConfigException as e:
            if warn:
                log('Path in ' + source + "' is not pointing to a JDK (" + e.message + ")")
    return filtered

def _find_jdk_in_candidates(candidates, versionCheck, warn=False, source=None):
    filtered = _filtered_jdk_configs(candidates, versionCheck, warn, source)
    if filtered:
        return filtered[0]
    return None


def run_java(args, nonZeroIsFatal=True, out=None, err=None, cwd=None, addDefaultArgs=True, javaConfig=None):
    if not javaConfig:
        javaConfig = java()
    return run(javaConfig.format_cmd(args, addDefaultArgs), nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, cwd=cwd)

def _kill_process_group(pid, sig):
    pgid = os.getpgid(pid)
    try:
        os.killpg(pgid, sig)
        return True
    except:
        log('Error killing subprocess ' + str(pgid) + ': ' + str(sys.exc_info()[1]))
        return False

def _waitWithTimeout(process, args, timeout):
    def _waitpid(pid):
        while True:
            try:
                return os.waitpid(pid, os.WNOHANG)
            except OSError, e:
                if e.errno == errno.EINTR:
                    continue
                raise

    def _returncode(status):
        if os.WIFSIGNALED(status):
            return -os.WTERMSIG(status)
        elif os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        else:
            # Should never happen
            raise RuntimeError("Unknown child exit status!")

    end = time.time() + timeout
    delay = 0.0005
    while True:
        (pid, status) = _waitpid(process.pid)
        if pid == process.pid:
            return _returncode(status)
        remaining = end - time.time()
        if remaining <= 0:
            abort('Process timed out after {0} seconds: {1}'.format(timeout, ' '.join(args)))
        delay = min(delay * 2, remaining, .05)
        time.sleep(delay)

# Makes the current subprocess accessible to the abort() function
# This is a list of tuples of the subprocess.Popen or
# multiprocessing.Process object and args.
_currentSubprocesses = []

def _addSubprocess(p, args):
    entry = (p, args)
    _currentSubprocesses.append(entry)
    return entry

def _removeSubprocess(entry):
    if entry and entry in _currentSubprocesses:
        try:
            _currentSubprocesses.remove(entry)
        except:
            pass

def waitOn(p):
    if get_os() == 'windows':
        # on windows use a poll loop, otherwise signal does not get handled
        retcode = None
        while retcode == None:
            retcode = p.poll()
            time.sleep(0.05)
    else:
        retcode = p.wait()
    return retcode

def run(args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None):
    """
    Run a command in a subprocess, wait for it to complete and return the exit status of the process.
    If the exit status is non-zero and `nonZeroIsFatal` is true, then mx is exited with
    the same exit status.
    Each line of the standard output and error streams of the subprocess are redirected to
    out and err if they are callable objects.
    """

    assert isinstance(args, types.ListType), "'args' must be a list: " + str(args)
    for arg in args:
        assert isinstance(arg, types.StringTypes), 'argument is not a string: ' + str(arg)

    if env is None:
        env = os.environ.copy()

    # Ideally the command line could be communicated directly in an environment
    # variable. However, since environment variables share the same resource
    # space as the command line itself (on Unix at least), this would cause the
    # limit to be exceeded too easily.
    with tempfile.NamedTemporaryFile(suffix='', prefix='mx_subprocess_command.', mode='w', delete=False) as fp:
        subprocessCommandFile = fp.name
        for arg in args:
            # TODO: handle newlines in args once there's a use case
            assert '\n' not in arg
            print >> fp, arg
    env['MX_SUBPROCESS_COMMAND_FILE'] = subprocessCommandFile

    if _opts.verbose:
        if _opts.very_verbose:
            log('Environment variables:')
            for key in sorted(env.keys()):
                log('    ' + key + '=' + env[key])
        log(' '.join(map(pipes.quote, args)))

    if timeout is None and _opts.ptimeout != 0:
        timeout = _opts.ptimeout

    sub = None

    try:
        # On Unix, the new subprocess should be in a separate group so that a timeout alarm
        # can use os.killpg() to kill the whole subprocess group
        preexec_fn = None
        creationflags = 0
        if not is_jython():
            if get_os() == 'windows':
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            elif timeout is not None:
                preexec_fn = os.setsid

        def redirect(stream, f):
            for line in iter(stream.readline, ''):
                f(line)
            stream.close()
        stdout = out if not callable(out) else subprocess.PIPE
        stderr = err if not callable(err) else subprocess.PIPE
        p = subprocess.Popen(args, cwd=cwd, stdout=stdout, stderr=stderr, preexec_fn=preexec_fn, creationflags=creationflags, env=env)
        sub = _addSubprocess(p, args)
        joiners = []
        if callable(out):
            t = Thread(target=redirect, args=(p.stdout, out))
            # Don't make the reader thread a daemon otherwise output can be droppped
            t.start()
            joiners.append(t)
        if callable(err):
            t = Thread(target=redirect, args=(p.stderr, err))
            # Don't make the reader thread a daemon otherwise output can be droppped
            t.start()
            joiners.append(t)
        while any([t.is_alive() for t in joiners]):
            # Need to use timeout otherwise all signals (including CTRL-C) are blocked
            # see: http://bugs.python.org/issue1167930
            for t in joiners:
                t.join(10)
        if timeout is None or timeout == 0:
            retcode = waitOn(p)
        else:
            if get_os() == 'windows':
                abort('Use of timeout not (yet) supported on Windows')
            retcode = _waitWithTimeout(p, args, timeout)
    except OSError as e:
        log('Error executing \'' + ' '.join(args) + '\': ' + str(e))
        if _opts.verbose:
            raise e
        abort(e.errno)
    except KeyboardInterrupt:
        abort(1)
    finally:
        _removeSubprocess(sub)
        os.remove(subprocessCommandFile)

    if retcode and nonZeroIsFatal:
        if _opts.verbose:
            if _opts.very_verbose:
                raise subprocess.CalledProcessError(retcode, ' '.join(args))
            else:
                log('[exit code: ' + str(retcode) + ']')
        abort(retcode)

    return retcode

def exe_suffix(name):
    """
    Gets the platform specific suffix for an executable
    """
    if get_os() == 'windows':
        return name + '.exe'
    return name

def add_lib_prefix(name):
    """
    Adds the platform specific library prefix to a name
    """
    os = get_os()
    if os == 'linux' or os == 'solaris' or os == 'darwin':
        return 'lib' + name
    return name

def add_lib_suffix(name):
    """
    Adds the platform specific library suffix to a name
    """
    os = get_os()
    if os == 'windows':
        return name + '.dll'
    if os == 'linux' or os == 'solaris':
        return name + '.so'
    if os == 'darwin':
        return name + '.dylib'
    return name

"""
Utility for filtering duplicate lines.
"""
class DuplicateSuppressingStream:
    """
    Creates an object that will suppress duplicate lines sent to 'out'.
    The lines considered for suppression are those that contain one of the
    strings in 'restrictTo' if it is not None.
    """
    def __init__(self, restrictTo=None, out=sys.stdout):
        self.restrictTo = restrictTo
        self.seen = set()
        self.out = out
        self.currentFilteredLineCount = 0
        self.currentFilteredTime = None

    def isSuppressionCandidate(self, line):
        if self.restrictTo:
            for p in self.restrictTo:
                if p in line:
                    return True
            return False
        else:
            return True

    def write(self, line):
        if self.isSuppressionCandidate(line):
            if line in self.seen:
                self.currentFilteredLineCount += 1
                if self.currentFilteredTime:
                    if time.time() - self.currentFilteredTime > 1 * 60:
                        self.out.write("  Filtered " + str(self.currentFilteredLineCount) + " repeated lines...\n")
                        self.currentFilteredTime = time.time()
                else:
                    self.currentFilteredTime = time.time()
                return
            self.seen.add(line)
        self.currentFilteredLineCount = 0
        self.out.write(line)
        self.currentFilteredTime = None

"""
A JavaCompliance simplifies comparing Java compliance values extracted from a JDK version string.
"""
class JavaCompliance:
    def __init__(self, ver):
        m = re.match(r'1\.(\d+).*', ver)
        assert m is not None, 'not a recognized version string: ' + ver
        self.value = int(m.group(1))

    def __str__(self):
        return '1.' + str(self.value)

    def __cmp__(self, other):
        if isinstance(other, types.StringType):
            other = JavaCompliance(other)

        return cmp(self.value, other.value)

    def __hash__(self):
        return self.value.__hash__()

    def exactMatch(self, version):
        assert isinstance(version, VersionSpec)
        return len(version.parts) > 1 and version.parts[0] == 1 and version.parts[1] == self.value

"""
A version specification as defined in JSR-56
"""
class VersionSpec:
    def __init__(self, versionString):
        validChar = r'[\x21-\x25\x27-\x29\x2c\x2f-\x5e\x60-\x7f]'
        separator = r'[.\-_]'
        m = re.match("^" + validChar + '+(' + separator + validChar + '+)*$', versionString)
        assert m is not None, 'not a recognized version string: ' + versionString
        self.versionString = versionString
        self.parts = [int(f) if f.isdigit() else f for f in re.split(separator, versionString)]

    def __str__(self):
        return self.versionString

    def __cmp__(self, other):
        return cmp(self.parts, other.parts)

def _filter_non_existant_paths(paths):
    if paths:
        return os.pathsep.join([path for path in _separatedCygpathW2U(paths).split(os.pathsep) if exists(path)])
    return None

class JavaConfigException(Exception):
    def __init__(self, value):
        Exception.__init__(self, value)

"""
A JavaConfig object encapsulates info on how Java commands are run.
"""
class JavaConfig:
    def __init__(self, java_home):
        self.jdk = java_home
        self.jar = exe_suffix(join(self.jdk, 'bin', 'jar'))
        self.java = exe_suffix(join(self.jdk, 'bin', 'java'))
        self.javac = exe_suffix(join(self.jdk, 'bin', 'javac'))
        self.javap = exe_suffix(join(self.jdk, 'bin', 'javap'))
        self.javadoc = exe_suffix(join(self.jdk, 'bin', 'javadoc'))
        self.pack200 = exe_suffix(join(self.jdk, 'bin', 'pack200'))
        self.toolsjar = join(self.jdk, 'lib', 'tools.jar')
        self._classpaths_initialized = False
        self._bootclasspath = None
        self._extdirs = None
        self._endorseddirs = None

        if not exists(self.java):
            raise JavaConfigException('Java launcher does not exist: ' + self.java)

        def delAtAndSplit(s):
            return shlex.split(s.lstrip('@'))

        self.java_args = delAtAndSplit(_opts.java_args) if _opts.java_args else []
        self.java_args_pfx = sum(map(delAtAndSplit, _opts.java_args_pfx), [])
        self.java_args_sfx = sum(map(delAtAndSplit, _opts.java_args_sfx), [])

        # Prepend the -d64 VM option only if the java command supports it
        try:
            output = subprocess.check_output([self.java, '-d64', '-version'], stderr=subprocess.STDOUT)
            self.java_args = ['-d64'] + self.java_args
        except subprocess.CalledProcessError as e:
            try:
                output = subprocess.check_output([self.java, '-version'], stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                raise JavaConfigException(e.returncode + " :" + e.output)

        def _checkOutput(out):
            return 'version' in out

        # hotspot can print a warning, e.g. if there's a .hotspot_compiler file in the cwd
        output = output.split('\n')
        version = None
        for o in output:
            if _checkOutput(o):
                assert version is None
                version = o

        self.version = VersionSpec(version.split()[2].strip('"'))
        self.javaCompliance = JavaCompliance(self.version.versionString)

        if _opts.java_dbg_port is not None:
            self.java_args += ['-Xdebug', '-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address=' + str(_opts.java_dbg_port)]

    def _init_classpaths(self):
        if not self._classpaths_initialized:
            _, binDir = _compile_mx_class('ClasspathDump', jdk=self)
            self._bootclasspath, self._extdirs, self._endorseddirs = [x if x != 'null' else None for x in subprocess.check_output([self.java, '-cp', _cygpathU2W(binDir), 'ClasspathDump'], stderr=subprocess.PIPE).split('|')]
            if self.javaCompliance <= JavaCompliance('1.8'):
                # All 3 system properties accessed by ClasspathDump are expected to exist
                if not self._bootclasspath or not self._extdirs or not self._endorseddirs:
                    warn("Could not find all classpaths: boot='" + str(self._bootclasspath) + "' extdirs='" + str(self._extdirs) + "' endorseddirs='" + str(self._endorseddirs) + "'")
            self._bootclasspath = _filter_non_existant_paths(self._bootclasspath)
            self._extdirs = _filter_non_existant_paths(self._extdirs)
            self._endorseddirs = _filter_non_existant_paths(self._endorseddirs)
            self._classpaths_initialized = True

    def __repr__(self):
        return "JavaConfig(" + str(self.jdk) + ")"

    def __str__(self):
        return "Java " + str(self.version) + " (" + str(self.javaCompliance) + ") from " + str(self.jdk)

    def __hash__(self):
        return hash(self.jdk)

    def __cmp__(self, other):
        if isinstance(other, JavaConfig):
            compilanceCmp = cmp(self.javaCompliance, other.javaCompliance)
            if compilanceCmp:
                return compilanceCmp
            versionCmp = cmp(self.version, other.version)
            if versionCmp:
                return versionCmp
            return cmp(self.jdk, other.jdk)
        raise TypeError()

    def format_cmd(self, args, addDefaultArgs):
        if addDefaultArgs:
            return [self.java] + self.processArgs(args)
        else:
            return [self.java] + args

    def processArgs(self, args):
        return self.java_args_pfx + self.java_args + self.java_args_sfx + args

    def bootclasspath(self):
        self._init_classpaths()
        return _separatedCygpathU2W(self._bootclasspath)

    """
    Add javadoc style options for the library paths of this JDK.
    """
    def javadocLibOptions(self, args):
        self._init_classpaths()
        if args is None:
            args = []
        if self._bootclasspath:
            args.append('-bootclasspath')
            args.append(self._bootclasspath)
        if self._extdirs:
            args.append('-extdirs')
            args.append(self._extdirs)
        return args

    """
    Add javac style options for the library paths of this JDK.
    """
    def javacLibOptions(self, args):
        args = self.javadocLibOptions(args)
        if self._endorseddirs:
            args.append('-endorseddirs')
            args.append(self._endorseddirs)
        return args

    def containsJar(self, jar):
        self._init_classpaths()

        if self._bootclasspath:
            for e in self._bootclasspath.split(os.pathsep):
                if basename(e) == jar:
                    return True
        if self._extdirs:
            for d in self._extdirs.split(os.pathsep):
                if len(d) and jar in os.listdir(d):
                    return True
        if self._endorseddirs:
            for d in self._endorseddirs.split(os.pathsep):
                if len(d) and jar in os.listdir(d):
                    return True
        return False

def check_get_env(key):
    """
    Gets an environment variable, aborting with a useful message if it is not set.
    """
    value = get_env(key)
    if value is None:
        abort('Required environment variable ' + key + ' must be set')
    return value

def get_env(key, default=None):
    """
    Gets an environment variable.
    """
    value = os.environ.get(key, default)
    return value

def logv(msg=None):
    if _opts.verbose:
        log(msg)

def log(msg=None):
    """
    Write a message to the console.
    All script output goes through this method thus allowing a subclass
    to redirect it.
    """
    if msg is None:
        print
    else:
        print msg

def expand_project_in_class_path_arg(cpArg):
    cp = []
    for part in cpArg.split(os.pathsep):
        if part.startswith('@'):
            cp += classpath(part[1:]).split(os.pathsep)
        else:
            cp.append(part)
    return os.pathsep.join(cp)

def expand_project_in_args(args):
    for i in range(len(args)):
        if args[i] == '-cp' or args[i] == '-classpath':
            if i + 1 < len(args):
                args[i + 1] = expand_project_in_class_path_arg(args[i + 1])
            return


def gmake_cmd():
    for a in ['make', 'gmake', 'gnumake']:
        try:
            output = subprocess.check_output([a, '--version'])
            if 'GNU' in output:
                return a
        except:
            pass
    abort('Could not find a GNU make executable on the current path.')

def expandvars_in_property(value):
    result = expandvars(value)
    if '$' in result or '%' in result:
        abort('Property contains an undefined environment variable: ' + value)
    return result

def _send_sigquit():
    for p, args in _currentSubprocesses:

        def _isJava():
            if args:
                name = args[0].split(os.sep)[-1]
                return name == "java"
            return False

        if p is not None and _isJava():
            if get_os() == 'windows':
                log("mx: implement me! want to send SIGQUIT to my child process")
            else:
                _kill_process_group(p.pid, sig=signal.SIGQUIT)
            time.sleep(0.1)

def abort(codeOrMessage):
    """
    Aborts the program with a SystemExit exception.
    If 'codeOrMessage' is a plain integer, it specifies the system exit status;
    if it is None, the exit status is zero; if it has another type (such as a string),
    the object's value is printed and the exit status is one.
    """

    if _opts and _opts.killwithsigquit:
        _send_sigquit()

    def is_alive(p):
        if isinstance(p, subprocess.Popen):
            return p.poll() is None
        assert is_jython() or isinstance(p, multiprocessing.Process), p
        return p.is_alive()

    for p, args in _currentSubprocesses:
        if is_alive(p):
            try:
                if get_os() == 'windows':
                    p.terminate()
                else:
                    _kill_process_group(p.pid, signal.SIGKILL)
            except BaseException as e:
                if is_alive(p):
                    log('error while killing subprocess {0} "{1}": {2}'.format(p.pid, ' '.join(args), e))

    if _opts and _opts.verbose:
        import traceback
        traceback.print_stack()
    raise SystemExit(codeOrMessage)

def download(path, urls, verbose=False):
    """
    Attempts to downloads content for each URL in a list, stopping after the first successful download.
    If the content cannot be retrieved from any URL, the program is aborted. The downloaded content
    is written to the file indicated by 'path'.
    """
    d = dirname(path)
    if d != '' and not exists(d):
        os.makedirs(d)

    assert not path.endswith(os.sep)

    _, binDir = _compile_mx_class('URLConnectionDownload')
    command = [java().java, '-cp', _cygpathU2W(binDir), 'URLConnectionDownload']
    if _opts.no_download_progress or not sys.stderr.isatty():
        command.append('--no-progress')
    command.append(_cygpathU2W(path))
    command += urls
    if run(command, nonZeroIsFatal=False) == 0:
        return

    abort('Could not download to ' + path + ' from any of the following URLs:\n\n    ' +
              '\n    '.join(urls) + '\n\nPlease use a web browser to do the download manually')

def update_file(path, content):
    """
    Updates a file with some given content if the content differs from what's in
    the file already. The return value indicates if the file was updated.
    """
    existed = exists(path)
    try:
        old = None
        if existed:
            with open(path, 'rb') as f:
                old = f.read()

        if old == content:
            return False

        if existed and _opts.backup_modified:
            shutil.move(path, path + '.orig')

        with open(path, 'wb') as f:
            f.write(content)

        log(('modified ' if existed else 'created ') + path)
        return True
    except IOError as e:
        abort('Error while writing to ' + path + ': ' + str(e))

# Builtin commands

def _defaultEcjPath():
    return get_env('JDT', join(_primary_suite.mxDir, 'ecj.jar'))

class JavaCompileTask:
    def __init__(self, args, proj, reason, javafilelist, jdk, outputDir, jdtJar, deps):
        self.proj = proj
        self.reason = reason
        self.javafilelist = javafilelist
        self.deps = deps
        self.jdk = jdk
        self.outputDir = outputDir
        self.done = False
        self.jdtJar = jdtJar
        self.args = args

    def __str__(self):
        return self.proj.name

    def logCompilation(self, compiler):
        log('Compiling Java sources for {0} with {1}... [{2}]'.format(self.proj.name, compiler, self.reason))

    def execute(self):
        argfileName = join(self.proj.dir, 'javafilelist.txt')
        argfile = open(argfileName, 'wb')
        argfile.write('\n'.join(map(_cygpathU2W, self.javafilelist)))
        argfile.close()

        processorArgs = []

        processorPath = self.proj.annotation_processors_path()
        if processorPath:
            genDir = self.proj.source_gen_dir()
            if exists(genDir):
                shutil.rmtree(genDir)
            os.mkdir(genDir)
            processorArgs += ['-processorpath', _separatedCygpathU2W(join(processorPath)), '-s', _cygpathU2W(genDir)]
        else:
            processorArgs += ['-proc:none']

        args = self.args
        jdk = self.jdk
        outputDir = _cygpathU2W(self.outputDir)
        compliance = str(jdk.javaCompliance)
        cp = _separatedCygpathU2W(classpath(self.proj.name, includeSelf=True))
        toBeDeleted = [argfileName]

        try:
            if not self.jdtJar:
                mainJava = java()
                if not args.error_prone:
                    javac = args.alt_javac if args.alt_javac else mainJava.javac
                    self.logCompilation('javac' if not args.alt_javac else args.alt_javac)
                    javacCmd = [javac, '-g', '-J-Xmx1500m', '-source', compliance, '-target', compliance, '-classpath', cp, '-d', outputDir]
                    jdk.javacLibOptions(javacCmd)
                    if _opts.java_dbg_port is not None:
                        javacCmd += ['-J-Xdebug', '-J-Xrunjdwp:transport=dt_socket,server=y,suspend=y,address=' + str(jdk.debug_port)]
                    javacCmd += processorArgs
                    javacCmd += ['@' + _cygpathU2W(argfile.name)]

                    if not args.warnAPI:
                        javacCmd.append('-XDignore.symbol.file')
                    run(javacCmd)
                else:
                    self.logCompilation('javac (with error-prone)')
                    javaArgs = ['-Xmx1500m']
                    javacArgs = ['-g', '-source', compliance, '-target', compliance, '-classpath', cp, '-d', outputDir]
                    jdk.javacLibOptions(javacCmd)
                    javacArgs += processorArgs
                    javacArgs += ['@' + argfile.name]
                    if not args.warnAPI:
                        javacArgs.append('-XDignore.symbol.file')
                    run_java(javaArgs + ['-cp', os.pathsep.join([mainJava.toolsjar, args.error_prone]), 'com.google.errorprone.ErrorProneCompiler'] + javacArgs)
            else:
                self.logCompilation('JDT')

                jdtVmArgs = ['-Xmx1500m', '-jar', _cygpathU2W(self.jdtJar)]

                jdtArgs = ['-' + compliance,
                         '-cp', cp, '-g', '-enableJavadoc',
                         '-d', outputDir]
                jdk.javacLibOptions(jdtArgs)
                jdtArgs += processorArgs

                jdtProperties = join(self.proj.dir, '.settings', 'org.eclipse.jdt.core.prefs')
                rootJdtProperties = join(self.proj.suite.mxDir, 'eclipse-settings', 'org.eclipse.jdt.core.prefs')
                if not exists(jdtProperties) or os.path.getmtime(jdtProperties) < os.path.getmtime(rootJdtProperties):
                    # Try to fix a missing properties file by running eclipseinit
                    _eclipseinit_project(self.proj)
                if not exists(jdtProperties):
                    log('JDT properties file {0} not found'.format(jdtProperties))
                else:
                    with open(jdtProperties) as fp:
                        origContent = fp.read()
                        content = origContent
                        if self.proj.uses_annotation_processor_library():
                            # unfortunately, the command line compiler doesn't let us ignore warnings for generated files only
                            content = content.replace('=warning', '=ignore')
                        elif args.jdt_warning_as_error:
                            content = content.replace('=warning', '=error')
                        if not args.jdt_show_task_tags:
                            content = content + '\norg.eclipse.jdt.core.compiler.problem.tasks=ignore'
                    if origContent != content:
                        jdtPropertiesTmp = jdtProperties + '.tmp'
                        with open(jdtPropertiesTmp, 'w') as fp:
                            fp.write(content)
                        toBeDeleted.append(jdtPropertiesTmp)
                        jdtArgs += ['-properties', _cygpathU2W(jdtPropertiesTmp)]
                    else:
                        jdtArgs += ['-properties', _cygpathU2W(jdtProperties)]
                jdtArgs.append('@' + _cygpathU2W(argfile.name))

                run_java(jdtVmArgs + jdtArgs)

            # Create annotation processor jar for a project that defines annotation processors
            if self.proj.definedAnnotationProcessorsDist:
                self.proj.definedAnnotationProcessorsDist.make_archive()

        finally:
            # Do not clean up temp files if verbose as there's
            # a good chance the user wants to copy and paste the
            # Java compiler command directly
            if not _opts.verbose:
                for n in toBeDeleted:
                    os.remove(n)

            self.done = True

def build(args, parser=None):
    """compile the Java and C sources, linking the latter

    Compile all the Java source code using the appropriate compilers
    and linkers for the various source code types."""

    suppliedParser = parser is not None
    if not suppliedParser:
        parser = ArgumentParser(prog='mx build')

    parser = parser if parser is not None else ArgumentParser(prog='mx build')
    parser.add_argument('-f', action='store_true', dest='force', help='force build (disables timestamp checking)')
    parser.add_argument('-c', action='store_true', dest='clean', help='removes existing build output')
    parser.add_argument('-p', action='store_true', dest='parallelize', help='parallelizes Java compilation')
    parser.add_argument('--source', dest='compliance', help='Java compliance level for projects without an explicit one')
    parser.add_argument('--Wapi', action='store_true', dest='warnAPI', help='show warnings about using internal APIs')
    parser.add_argument('--check-distributions', action='store_true', dest='check_distributions', help='check built distributions for overlap')
    parser.add_argument('--projects', action='store', help='comma separated projects to build (omit to build all projects)')
    parser.add_argument('--only', action='store', help='comma separated projects to build, without checking their dependencies (omit to build all projects)')
    parser.add_argument('--no-java', action='store_false', dest='java', help='do not build Java projects')
    parser.add_argument('--no-native', action='store_false', dest='native', help='do not build native projects')
    parser.add_argument('--jdt-warning-as-error', action='store_true', help='convert all Eclipse batch compiler warnings to errors')
    parser.add_argument('--jdt-show-task-tags', action='store_true', help='show task tags as Eclipse batch compiler warnings')
    parser.add_argument('--alt-javac', dest='alt_javac', help='path to alternative javac executable', metavar='<path>')
    compilerSelect = parser.add_mutually_exclusive_group()
    compilerSelect.add_argument('--error-prone', dest='error_prone', help='path to error-prone.jar', metavar='<path>')
    compilerSelect.add_argument('--jdt', help='path to ecj.jar, the Eclipse batch compiler', default=_defaultEcjPath(), metavar='<path>')
    compilerSelect.add_argument('--force-javac', action='store_true', dest='javac', help='use javac whether ecj.jar is found or not')

    if suppliedParser:
        parser.add_argument('remainder', nargs=REMAINDER, metavar='...')

    args = parser.parse_args(args)

    if is_jython():
        if args.parallelize:
            logv('[multiprocessing not available in jython]')
            args.parallelize = False

    jdtJar = None
    if not args.javac and args.jdt is not None:
        if not args.jdt.endswith('.jar'):
            abort('Path for Eclipse batch compiler does not look like a jar file: ' + args.jdt)
        jdtJar = args.jdt
        if not exists(jdtJar):
            if os.path.abspath(jdtJar) == os.path.abspath(_defaultEcjPath()) and get_env('JDT', None) is None:
                # Silently ignore JDT if default location is used but does not exist
                jdtJar = None
            else:
                abort('Eclipse batch compiler jar does not exist: ' + args.jdt)

    if args.only is not None:
        # N.B. This build will not include dependencies including annotation processor dependencies
        projectNames = args.only.split(',')
        sortedProjects = [project(name) for name in projectNames]

    else:
        if args.projects is not None:
            projectNames = args.projects.split(',')
        else:
            projectNames = None

        projects = _projects_opt_limit_to_suites(projects_from_names(projectNames))
        # N.B. Limiting to a suite only affects the starting set of projects. Dependencies in other suites will still be compiled
        sortedProjects = sorted_project_deps(projects, includeAnnotationProcessors=True)

    if args.java and jdtJar:
        ideinit([], refreshOnly=True, buildProcessorJars=False)

    tasks = {}
    updatedAnnotationProcessorDists = set()
    for p in sortedProjects:
        if p.native:
            if args.native:
                # resolve any dependency downloads
                for dep in p.all_deps([], includeLibs=True, includeAnnotationProcessors=False, includeSelf=False):
                    dep.get_path(True)

                log('Calling GNU make {0}...'.format(p.dir))

                if args.clean:
                    run([gmake_cmd(), 'clean'], cwd=p.dir)

                run([gmake_cmd()], cwd=p.dir)
            continue
        else:
            if not args.java:
                continue
            if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
                continue

        # skip building this Java project if its Java compliance level is "higher" than the configured JDK
        requiredCompliance = p.javaCompliance if p.javaCompliance else JavaCompliance(args.compliance) if args.compliance else None
        jdk = java(requiredCompliance)

        outputDir = p.output_dir()

        sourceDirs = p.source_dirs()
        buildReason = None
        if args.force:
            buildReason = 'forced build'
        elif args.clean:
            buildReason = 'clean'

        taskDeps = []

        for dep in p.all_deps([], includeLibs=False, includeAnnotationProcessors=True):
            taskDep = tasks.get(dep.name)
            if taskDep:
                if not buildReason:
                    buildReason = dep.name + ' rebuilt'
                taskDeps.append(taskDep)

        javafilelist = []
        nonjavafiletuples = []
        for sourceDir in sourceDirs:
            for root, _, files in os.walk(sourceDir):
                javafiles = [join(root, name) for name in files if name.endswith('.java') and name != 'package-info.java']
                javafilelist += javafiles

                nonjavafiletuples += [(sourceDir, [join(root, name) for name in files if not name.endswith('.java')])]

                if not buildReason:
                    for javafile in javafiles:
                        classfile = TimeStampFile(outputDir + javafile[len(sourceDir):-len('java')] + 'class')
                        if not classfile.exists() or classfile.isOlderThan(javafile):
                            buildReason = 'class file(s) out of date'
                            break

        apsOutOfDate = p.update_current_annotation_processors_file()
        if apsOutOfDate:
            buildReason = 'annotation processor(s) changed'

        if not buildReason:
            logv('[all class files for {0} are up to date - skipping]'.format(p.name))
            _handleNonJavaFiles(outputDir, p, False, nonjavafiletuples)
            continue

        _handleNonJavaFiles(outputDir, p, True, nonjavafiletuples)

        if len(javafilelist) == 0:
            logv('[no Java sources for {0} - skipping]'.format(p.name))
            continue

        javafilelist = sorted(javafilelist)

        task = JavaCompileTask(args, p, buildReason, javafilelist, jdk, outputDir, jdtJar, taskDeps)
        if p.definedAnnotationProcessorsDist:
            updatedAnnotationProcessorDists.add(p.definedAnnotationProcessorsDist)

        tasks[p.name] = task
        if args.parallelize:
            # Best to initialize class paths on main process
            jdk.bootclasspath()
            task.proc = None
        else:
            task.execute()

    if args.parallelize:

        def joinTasks(tasks):
            failed = []
            for t in tasks:
                t.proc.join()
                _removeSubprocess(t.sub)
                if t.proc.exitcode != 0:
                    failed.append(t)
            return failed

        def checkTasks(tasks):
            active = []
            for t in tasks:
                if t.proc.is_alive():
                    active.append(t)
                else:
                    if t.proc.exitcode != 0:
                        return ([], joinTasks(tasks))
            return (active, [])

        def remainingDepsDepth(task):
            if task._d is None:
                incompleteDeps = [d for d in task.deps if d.proc is None or d.proc.is_alive()]
                if len(incompleteDeps) == 0:
                    task._d = 0
                else:
                    task._d = max([remainingDepsDepth(t) for t in incompleteDeps]) + 1
            return task._d

        def compareTasks(t1, t2):
            d = remainingDepsDepth(t1) - remainingDepsDepth(t2)
            if d == 0:
                t1Work = (1 + len(t1.proj.annotation_processors())) * len(t1.javafilelist)
                t2Work = (1 + len(t2.proj.annotation_processors())) * len(t2.javafilelist)
                d = t1Work - t2Work
            return d

        def sortWorklist(tasks):
            for t in tasks:
                t._d = None
            return sorted(tasks, compareTasks)

        cpus = cpu_count()
        worklist = sortWorklist(tasks.values())
        active = []
        failed = []
        while len(worklist) != 0:
            while True:
                active, failed = checkTasks(active)
                if len(failed) != 0:
                    assert not active, active
                    break
                if len(active) == cpus:
                    # Sleep for 1 second
                    time.sleep(1)
                else:
                    break

            if len(failed) != 0:
                break

            def executeTask(task):
                # Clear sub-process list cloned from parent process
                del _currentSubprocesses[:]
                task.execute()

            def depsDone(task):
                for d in task.deps:
                    if d.proc is None or d.proc.exitcode is None:
                        return False
                return True

            for task in worklist:
                if depsDone(task):
                    worklist.remove(task)
                    task.proc = multiprocessing.Process(target=executeTask, args=(task,))
                    task.proc.start()
                    active.append(task)
                    task.sub = _addSubprocess(task.proc, ['JavaCompileTask', str(task)])
                if len(active) == cpus:
                    break

            worklist = sortWorklist(worklist)

        failed += joinTasks(active)
        if len(failed):
            for t in failed:
                log('Compiling {0} failed'.format(t.proj.name))
            abort('{0} Java compilation tasks failed'.format(len(failed)))

    if args.java:
        # do not process a distribution unless it corresponds to one of sortedProjects
        # limit it even further if an explicit list of projects given as arg
        if projectNames:
            distProjects = projects_from_names(projectNames)
        else:
            distProjects = sortedProjects
        suites = {p.suite for p in distProjects}

        files = []
        for dist in sorted_dists():
            if dist.suite in suites:
                if dist not in updatedAnnotationProcessorDists:
                    archive(['@' + dist.name])
            if args.check_distributions and not dist.isProcessorDistribution:
                with zipfile.ZipFile(dist.path, 'r') as zf:
                    files.extend([member for member in zf.namelist() if not member.startswith('META-INF')])
        dups = set([x for x in files if files.count(x) > 1])
        if len(dups) > 0:
            abort('Distributions overlap! duplicates: ' + str(dups))


    if suppliedParser:
        return args
    return None

def _handleNonJavaFiles(outputDir, p, clean, nonjavafiletuples):
    if exists(outputDir):
        if clean:
            log('Cleaning {0}...'.format(outputDir))
            shutil.rmtree(outputDir)
            os.mkdir(outputDir)
    else:
        os.mkdir(outputDir)
    genDir = p.source_gen_dir()
    if genDir != '' and exists(genDir) and clean:
        log('Cleaning {0}...'.format(genDir))
        for f in os.listdir(genDir):
            shutil.rmtree(join(genDir, f))

    # Copy all non Java resources or assemble Jasmin files
    jasminAvailable = None
    for nonjavafiletuple in nonjavafiletuples:
        sourceDir = nonjavafiletuple[0]
        nonjavafilelist = nonjavafiletuple[1]

        for src in nonjavafilelist:
            if src.endswith('.jasm'):
                className = None
                with open(src) as f:
                    for line in f:
                        if line.startswith('.class '):
                            className = line.split()[-1]
                            break

                if className is not None:
                    jasminOutputDir = p.jasmin_output_dir()
                    classFile = join(jasminOutputDir, className.replace('/', os.sep) + '.class')
                    if exists(dirname(classFile)) and (not exists(classFile) or os.path.getmtime(classFile) < os.path.getmtime(src)):
                        if jasminAvailable is None:
                            try:
                                with open(os.devnull) as devnull:
                                    subprocess.call('jasmin', stdout=devnull, stderr=subprocess.STDOUT)
                                jasminAvailable = True
                            except OSError:
                                jasminAvailable = False

                        if jasminAvailable:
                            log('Assembling Jasmin file ' + src)
                            run(['jasmin', '-d', jasminOutputDir, src])
                        else:
                            log('The jasmin executable could not be found - skipping ' + src)
                            with file(classFile, 'a'):
                                os.utime(classFile, None)

                else:
                    log('could not file .class directive in Jasmin source: ' + src)
            else:
                dst = join(outputDir, src[len(sourceDir) + 1:])
                if not exists(dirname(dst)):
                    os.makedirs(dirname(dst))
                if exists(dirname(dst)) and (not exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src)):
                    shutil.copyfile(src, dst)

def build_suite(s):
    '''build all projects in suite (for dynamic import)'''
    # Note we must use the "build" method in "s" and not the one
    # in the dict. If there isn't one we use mx.build
    project_names = [p.name for p in s.projects]
    if hasattr(s.commands, 'build'):
        build_command = s.commands.build
    else:
        build_command = build
    build_command(['--projects', ','.join(project_names)])

def _chunk_files_for_command_line(files, limit=None, pathFunction=lambda f: f):
    """
    Returns a generator for splitting up a list of files into chunks such that the
    size of the space separated file paths in a chunk is less than a given limit.
    This is used to work around system command line length limits.
    """
    chunkSize = 0
    chunkStart = 0
    if limit is None:
        commandLinePrefixAllowance = 3000
        if get_os() == 'windows':
            # The CreateProcess function on Windows limits the length of a command line to
            # 32,768 characters (http://msdn.microsoft.com/en-us/library/ms682425%28VS.85%29.aspx)
            limit = 32768 - commandLinePrefixAllowance
        else:
            # Using just SC_ARG_MAX without extra downwards adjustment
            # results in "[Errno 7] Argument list too long" on MacOS.
            commandLinePrefixAllowance = 20000
            syslimit = os.sysconf('SC_ARG_MAX')
            if syslimit == -1:
                syslimit = 262144 # we could use sys.maxint but we prefer a more robust smaller value
            limit = syslimit - commandLinePrefixAllowance
            assert limit > 0
    for i in range(len(files)):
        path = pathFunction(files[i])
        size = len(path) + 1
        assert size < limit
        if chunkSize + size < limit:
            chunkSize += size
        else:
            assert i > chunkStart
            yield files[chunkStart:i]
            chunkStart = i
            chunkSize = 0
    if chunkStart == 0:
        assert chunkSize < limit
        yield files

def eclipseformat(args):
    """run the Eclipse Code Formatter on the Java sources

    The exit code 1 denotes that at least one file was modified."""

    parser = ArgumentParser(prog='mx eclipseformat')
    parser.add_argument('-e', '--eclipse-exe', help='location of the Eclipse executable')
    parser.add_argument('-C', '--no-backup', action='store_false', dest='backup', help='do not save backup of modified files')
    parser.add_argument('--projects', action='store', help='comma separated projects to process (omit to process all projects)')

    args = parser.parse_args(args)
    if args.eclipse_exe is None:
        args.eclipse_exe = os.environ.get('ECLIPSE_EXE')
    if args.eclipse_exe is None:
        abort('Could not find Eclipse executable. Use -e option or ensure ECLIPSE_EXE environment variable is set.')

    # Maybe an Eclipse installation dir was specified - look for the executable in it
    if isdir(args.eclipse_exe):
        args.eclipse_exe = join(args.eclipse_exe, exe_suffix('eclipse'))
        warn("The eclipse-exe was a directory, now using " + args.eclipse_exe)

    if not os.path.isfile(args.eclipse_exe):
        abort('File does not exist: ' + args.eclipse_exe)
    if not os.access(args.eclipse_exe, os.X_OK):
        abort('Not an executable file: ' + args.eclipse_exe)

    eclipseinit([], buildProcessorJars=False)

    # build list of projects to be processed
    projects = sorted_deps()
    if args.projects is not None:
        projects = [project(name) for name in args.projects.split(',')]

    class Batch:
        def __init__(self, settingsDir, javaCompliance):
            self.path = join(settingsDir, 'org.eclipse.jdt.core.prefs')
            self.javaCompliance = javaCompliance
            with open(join(settingsDir, 'org.eclipse.jdt.ui.prefs')) as fp:
                jdtUiPrefs = fp.read()
            self.removeTrailingWhitespace = 'sp_cleanup.remove_trailing_whitespaces_all=true' in jdtUiPrefs
            if self.removeTrailingWhitespace:
                assert 'sp_cleanup.remove_trailing_whitespaces=true' in jdtUiPrefs and 'sp_cleanup.remove_trailing_whitespaces_ignore_empty=false' in jdtUiPrefs
            self.cachedHash = None

        def __hash__(self):
            if not self.cachedHash:
                with open(self.path) as fp:
                    self.cachedHash = (fp.read(), self.javaCompliance, self.removeTrailingWhitespace).__hash__()
            return self.cachedHash

        def __eq__(self, other):
            if not isinstance(other, Batch):
                return False
            if self.removeTrailingWhitespace != other.removeTrailingWhitespace:
                return False
            if self.javaCompliance != other.javaCompliance:
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
            self.times = (os.path.getatime(path), os.path.getmtime(path))

        def update(self, removeTrailingWhitespace):
            with open(self.path) as fp:
                content = fp.read()

            if self.content != content:
                # Only apply *after* formatting to match the order in which the IDE does it
                if removeTrailingWhitespace:
                    content, n = re.subn(r'[ \t]+$', '', content, flags=re.MULTILINE)
                    if n != 0 and self.content == content:
                        # undo on-disk changes made by the Eclipse formatter
                        with open(self.path, 'w') as fp:
                            fp.write(content)

                if self.content != content:
                    self.diff = difflib.unified_diff(self.content.splitlines(1), content.splitlines(1))
                    self.content = content
                    return True

            # reset access and modification time of file
            os.utime(self.path, self.times)

    modified = list()
    batches = dict()  # all sources with the same formatting settings are formatted together
    for p in projects:
        if p.native:
            continue
        sourceDirs = p.source_dirs()

        batch = Batch(join(p.dir, '.settings'), p.javaCompliance)

        if not exists(batch.path):
            if _opts.verbose:
                log('[no Eclipse Code Formatter preferences at {0} - skipping]'.format(batch.path))
            continue

        javafiles = []
        for sourceDir in sourceDirs:
            for root, _, files in os.walk(sourceDir):
                for f in [join(root, name) for name in files if name.endswith('.java')]:
                    javafiles.append(FileInfo(f))
        if len(javafiles) == 0:
            logv('[no Java sources in {0} - skipping]'.format(p.name))
            continue

        res = batches.setdefault(batch, javafiles)
        if res is not javafiles:
            res.extend(javafiles)

    log("we have: " + str(len(batches)) + " batches")
    for batch, javafiles in batches.iteritems():
        for chunk in _chunk_files_for_command_line(batch.javafiles, pathFunction=lambda f: f.path):
            run([args.eclipse_exe,
                '-nosplash',
                '-application',
                'org.eclipse.jdt.core.JavaCodeFormatter',
                '-vm', java(batch.javaCompliance).java,
                '-config', batch.path]
                + [f.path for f in chunk])
            for fi in chunk:
                if fi.update(batch.removeTrailingWhitespace):
                    modified.append(fi)

    log('{0} files were modified'.format(len(modified)))

    if len(modified) != 0:
        arcbase = _primary_suite.dir
        if args.backup:
            backup = os.path.abspath('eclipseformat.backup.zip')
            zf = zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED)
        for fi in modified:
            name = os.path.relpath(fi.path, arcbase)
            log(' - {0}'.format(name))
            log('Changes:')
            log(''.join(fi.diff))
            if args.backup:
                arcname = name.replace(os.sep, '/')
                zf.writestr(arcname, fi.content)
        if args.backup:
            zf.close()
            log('Wrote backup of {0} modified files to {1}'.format(len(modified), backup))
        return 1
    return 0

def processorjars():
    for s in suites(True):
        _processorjars_suite(s)

def _processorjars_suite(s):
    projs = [p for p in s.projects if p.definedAnnotationProcessors is not None]
    if len(projs) <= 0:
        return []

    pnames = [p.name for p in projs]
    build(['--jdt-warning-as-error', '--projects', ",".join(pnames)])
    return [p.definedAnnotationProcessorsDist.path for p in s.projects if p.definedAnnotationProcessorsDist is not None]

def pylint(args):
    """run pylint (if available) over Python source files (found by 'hg locate' or by tree walk with -walk)"""

    parser = ArgumentParser(prog='mx pylint')
    parser.add_argument('--walk', action='store_true', help='use tree walk find .py files')
    args = parser.parse_args(args)

    rcfile = join(dirname(__file__), '.pylintrc')
    if not exists(rcfile):
        log('pylint configuration file does not exist: ' + rcfile)
        return

    try:
        output = subprocess.check_output(['pylint', '--version'], stderr=subprocess.STDOUT)
        m = re.match(r'.*pylint (\d+)\.(\d+)\.(\d+).*', output, re.DOTALL)
        if not m:
            log('could not determine pylint version from ' + output)
            return
        major, minor, micro = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if major != 1 or minor != 1:
            log('require pylint version = 1.1.x (got {0}.{1}.{2})'.format(major, minor, micro))
            return
    except BaseException:
        log('pylint is not available')
        return

    def findfiles_by_walk():
        result = []
        for suite in suites(True):
            for root, dirs, files in os.walk(suite.dir):
                for f in files:
                    if f.endswith('.py'):
                        pyfile = join(root, f)
                        result.append(pyfile)
                if 'bin' in dirs:
                    dirs.remove('bin')
                if 'lib' in dirs:
                    # avoids downloaded .py files
                    dirs.remove('lib')
        return result

    def findfiles_by_hg():
        result = []
        for suite in suites(True):
            versioned = subprocess.check_output(['hg', 'locate', '-f'], stderr=subprocess.STDOUT, cwd=suite.dir).split(os.linesep)
            for f in versioned:
                if f.endswith('.py') and exists(f):
                    result.append(f)
        return result

    # Perhaps we should just look in suite.mxDir directories for .py files?
    if args.walk:
        pyfiles = findfiles_by_walk()
    else:
        pyfiles = findfiles_by_hg()

    env = os.environ.copy()

    pythonpath = dirname(__file__)
    for suite in suites(True):
        pythonpath = os.pathsep.join([pythonpath, suite.mxDir])

    env['PYTHONPATH'] = pythonpath

    for pyfile in pyfiles:
        log('Running pylint on ' + pyfile + '...')
        run(['pylint', '--reports=n', '--rcfile=' + rcfile, pyfile], env=env)

"""
Utility for creating and updating a zip file atomically.
"""
class Archiver:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        if self.path:
            if not isdir(dirname(self.path)):
                os.makedirs(dirname(self.path))
            fd, tmp = tempfile.mkstemp(suffix='', prefix=basename(self.path) + '.', dir=dirname(self.path))
            self.tmpFd = fd
            self.tmpPath = tmp
            self.zf = zipfile.ZipFile(tmp, 'w')
        else:
            self.tmpFd = None
            self.tmpPath = None
            self.zf = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.zf:
            self.zf.close()
            os.close(self.tmpFd)
            # Correct the permissions on the temporary file which is created with restrictive permissions
            os.chmod(self.tmpPath, 0o666 & ~currentUmask)
            # Atomic on Unix
            shutil.move(self.tmpPath, self.path)

def _archive(args):
    archive(args)
    return 0

def archive(args):
    """create jar files for projects and distributions"""
    parser = ArgumentParser(prog='mx archive')
    parser.add_argument('names', nargs=REMAINDER, metavar='[<project>|@<distribution>]...')
    args = parser.parse_args(args)

    archives = []
    for name in args.names:
        if name.startswith('@'):
            dname = name[1:]
            d = distribution(dname)
            d.make_archive()
            archives.append(d.path)
        else:
            p = project(name)
            archives.append(p.make_archive())

    logv("generated archives: " + str(archives))
    return archives

def canonicalizeprojects(args):
    """check all project specifications for canonical dependencies

    The exit code of this command reflects how many projects have non-canonical dependencies."""

    nonCanonical = []
    for s in suites(True):
        projectsPyFile = join(s.mxDir, 'projects')
        if not exists(projectsPyFile):
            continue

        for p in s.projects:
            if p.checkPackagePrefix:
                for pkg in p.defined_java_packages():
                    if not pkg.startswith(p.name):
                        abort('package in {0} does not have prefix matching project name: {1}'.format(p, pkg))

            ignoredDeps = set([name for name in p.deps if project(name, False) is not None])
            for pkg in p.imported_java_packages():
                for name in p.deps:
                    dep = project(name, False)
                    if dep is None:
                        ignoredDeps.discard(name)
                    else:
                        if pkg in dep.defined_java_packages():
                            ignoredDeps.discard(name)
                        if pkg in dep.extended_java_packages():
                            ignoredDeps.discard(name)
            if len(ignoredDeps) != 0:
                candidates = set()
                # Compute dependencies based on projects required by p
                for d in sorted_deps():
                    if not d.defined_java_packages().isdisjoint(p.imported_java_packages()):
                        candidates.add(d)
                # Remove non-canonical candidates
                for c in list(candidates):
                    candidates.difference_update(c.all_deps([], False, False))
                candidates = [d.name for d in candidates]

                abort('{0} does not use any packages defined in these projects: {1}\nComputed project dependencies: {2}'.format(
                    p, ', '.join(ignoredDeps), ','.join(candidates)))

            excess = frozenset(p.deps) - set(p.canonical_deps())
            if len(excess) != 0:
                nonCanonical.append(p)
    if len(nonCanonical) != 0:
        for p in nonCanonical:
            canonicalDeps = p.canonical_deps()
            if len(canonicalDeps) != 0:
                log('Canonical dependencies for project ' + p.name + ' are: [')
                for d in canonicalDeps:
                    log('        "' + d + '",')
                log('      ],')
            else:
                log('Canonical dependencies for project ' + p.name + ' are: []')
    return len(nonCanonical)

class TimeStampFile:
    def __init__(self, path):
        self.path = path
        self.timestamp = os.path.getmtime(path) if exists(path) else None

    def isOlderThan(self, arg):
        if not self.timestamp:
            return True
        if isinstance(arg, TimeStampFile):
            if arg.timestamp is None:
                return False
            else:
                return arg.timestamp > self.timestamp
        elif isinstance(arg, types.ListType):
            files = arg
        else:
            files = [arg]
        for f in files:
            if os.path.getmtime(f) > self.timestamp:
                return True
        return False

    def exists(self):
        return exists(self.path)

    def touch(self):
        if exists(self.path):
            os.utime(self.path, None)
        else:
            if not isdir(dirname(self.path)):
                os.makedirs(dirname(self.path))
            file(self.path, 'a')

def checkstyle(args):
    """run Checkstyle on the Java sources

   Run Checkstyle over the Java sources. Any errors or warnings
   produced by Checkstyle result in a non-zero exit code."""

    parser = ArgumentParser(prog='mx checkstyle')

    parser.add_argument('-f', action='store_true', dest='force', help='force checking (disables timestamp checking)')
    parser.add_argument('--primary', action='store_true', help='limit checks to primary suite')
    args = parser.parse_args(args)

    totalErrors = 0
    for p in projects_opt_limit_to_suites():
        if p.native:
            continue
        if args.primary and not p.suite.primary:
            continue
        sourceDirs = p.source_dirs()

        config = join(project(p.checkstyleProj).dir, '.checkstyle_checks.xml')
        if not exists(config):
            logv('[No Checkstyle configuration found for {0} - skipping]'.format(p))
            continue

        # skip checking this Java project if its Java compliance level is "higher" than the configured JDK
        jdk = java(p.javaCompliance)
        assert jdk

        for sourceDir in sourceDirs:
            javafilelist = []
            for root, _, files in os.walk(sourceDir):
                javafilelist += [join(root, name) for name in files if name.endswith('.java') and name != 'package-info.java']
            if len(javafilelist) == 0:
                logv('[no Java sources in {0} - skipping]'.format(sourceDir))
                continue

            timestamp = TimeStampFile(join(p.suite.mxDir, 'checkstyle-timestamps', sourceDir[len(p.suite.dir) + 1:].replace(os.sep, '_') + '.timestamp'))
            mustCheck = False
            if not args.force and timestamp.exists():
                mustCheck = timestamp.isOlderThan(javafilelist)
            else:
                mustCheck = True

            if not mustCheck:
                if _opts.verbose:
                    log('[all Java sources in {0} already checked - skipping]'.format(sourceDir))
                continue

            exclude = join(p.dir, '.checkstyle.exclude')
            if exists(exclude):
                with open(exclude) as f:
                    # Convert patterns to OS separators
                    patterns = [name.rstrip().replace('/', os.sep) for name in f.readlines()]
                def match(name):
                    for p in patterns:
                        if p in name:
                            if _opts.verbose:
                                log('excluding: ' + name)
                            return True
                    return False

                javafilelist = [name for name in javafilelist if not match(name)]

            auditfileName = join(p.dir, 'checkstyleOutput.txt')
            log('Running Checkstyle on {0} using {1}...'.format(sourceDir, config))

            try:
                for chunk in _chunk_files_for_command_line(javafilelist):
                    try:
                        run_java(['-Xmx1g', '-jar', library('CHECKSTYLE').get_path(True), '-f', 'xml', '-c', config, '-o', auditfileName] + chunk, nonZeroIsFatal=False)
                    finally:
                        if exists(auditfileName):
                            errors = []
                            source = [None]
                            def start_element(name, attrs):
                                if name == 'file':
                                    source[0] = attrs['name']
                                elif name == 'error':
                                    errors.append('{0}:{1}: {2}'.format(source[0], attrs['line'], attrs['message']))

                            xp = xml.parsers.expat.ParserCreate()
                            xp.StartElementHandler = start_element
                            with open(auditfileName) as fp:
                                xp.ParseFile(fp)
                            if len(errors) != 0:
                                map(log, errors)
                                totalErrors = totalErrors + len(errors)
                            else:
                                timestamp.touch()
            finally:
                if exists(auditfileName):
                    os.unlink(auditfileName)
    return totalErrors

def clean(args, parser=None):
    """remove all class files, images, and executables

    Removes all files created by a build, including Java class files, executables, and
    generated images.
    """

    suppliedParser = parser is not None

    parser = parser if suppliedParser else ArgumentParser(prog='mx clean')
    parser.add_argument('--no-native', action='store_false', dest='native', help='do not clean native projects')
    parser.add_argument('--no-java', action='store_false', dest='java', help='do not clean Java projects')
    parser.add_argument('--projects', action='store', help='comma separated projects to clean (omit to clean all projects)')
    parser.add_argument('--no-dist', action='store_false', dest='dist', help='do not delete distributions')

    args = parser.parse_args(args)

    if args.projects is not None:
        projects = [project(name) for name in args.projects.split(',')]
    else:
        projects = projects_opt_limit_to_suites()

    def _rmtree(dirPath):
        path = dirPath
        if get_os() == 'windows':
            path = unicode("\\\\?\\" + dirPath)
        shutil.rmtree(path)

    def _rmIfExists(name):
        if name and os.path.isfile(name):
            os.unlink(name)

    for p in projects:
        if p.native:
            if args.native:
                run([gmake_cmd(), '-C', p.dir, 'clean'])
        else:
            if args.java:
                genDir = p.source_gen_dir()
                if genDir != '' and exists(genDir):
                    log('Clearing {0}...'.format(genDir))
                    for f in os.listdir(genDir):
                        _rmtree(join(genDir, f))


                outputDir = p.output_dir()
                if outputDir != '' and exists(outputDir):
                    log('Removing {0}...'.format(outputDir))
                    _rmtree(outputDir)

            for configName in ['netbeans-config.zip', 'eclipse-config.zip']:
                config = TimeStampFile(join(p.suite.mxDir, configName))
                if config.exists():
                    os.unlink(config.path)

    if args.java:
        if args.dist:
            for d in _dists.keys():
                log('Removing distribution {0}...'.format(d))
                _rmIfExists(distribution(d).path)
                _rmIfExists(distribution(d).sourcesPath)


    if suppliedParser:
        return args

def about(args):
    """show the 'man page' for mx"""
    print __doc__

def help_(args):
    """show help for a given command

With no arguments, print a list of commands and short help for each command.

Given a command name, print help for that command."""
    if len(args) == 0:
        _argParser.print_help()
        return

    name = args[0]
    if not _commands.has_key(name):
        hits = [c for c in _commands.iterkeys() if c.startswith(name)]
        if len(hits) == 1:
            name = hits[0]
        elif len(hits) == 0:
            abort('mx: unknown command \'{0}\'\n{1}use "mx help" for more options'.format(name, _format_commands()))
        else:
            abort('mx: command \'{0}\' is ambiguous\n    {1}'.format(name, ' '.join(hits)))

    value = _commands[name]
    (func, usage) = value[:2]
    doc = func.__doc__
    if len(value) > 2:
        docArgs = value[2:]
        fmtArgs = []
        for d in docArgs:
            if isinstance(d, Callable):
                fmtArgs += [d()]
            else:
                fmtArgs += [str(d)]
        doc = doc.format(*fmtArgs)
    print 'mx {0} {1}\n\n{2}\n'.format(name, usage, doc)

def projectgraph(args, suite=None):
    """create graph for project structure ("mx projectgraph | dot -Tpdf -oprojects.pdf" or "mx projectgraph --igv")"""

    parser = ArgumentParser(prog='mx projectgraph')
    parser.add_argument('--igv', action='store_true', help='output to IGV listening on 127.0.0.1:4444')
    parser.add_argument('--igv-format', action='store_true', help='output graph in IGV format')

    args = parser.parse_args(args)

    if args.igv or args.igv_format:
        ids = {}
        nextToIndex = {}
        igv = XMLDoc()
        igv.open('graphDocument')
        igv.open('group')
        igv.open('properties')
        igv.element('p', {'name' : 'name'}, 'GraalProjectDependencies')
        igv.close('properties')
        igv.open('graph', {'name' : 'dependencies'})
        igv.open('nodes')
        for p in sorted_deps(includeLibs=True, includeJreLibs=True):
            ident = len(ids)
            ids[p.name] = str(ident)
            igv.open('node', {'id' : str(ident)})
            igv.open('properties')
            igv.element('p', {'name' : 'name'}, p.name)
            igv.close('properties')
            igv.close('node')
        igv.close('nodes')
        igv.open('edges')
        for p in projects():
            fromIndex = 0
            for dep in p.canonical_deps():
                toIndex = nextToIndex.get(dep, 0)
                nextToIndex[dep] = toIndex + 1
                igv.element('edge', {'from' : ids[p.name], 'fromIndex' : str(fromIndex), 'to' : ids[dep], 'toIndex' : str(toIndex), 'label' : 'dependsOn'})
                fromIndex = fromIndex + 1
        igv.close('edges')
        igv.close('graph')
        igv.close('group')
        igv.close('graphDocument')

        if args.igv:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(('127.0.0.1', 4444))
            s.send(igv.xml())
        else:
            print igv.xml(indent='  ', newl='\n')
        return

    print 'digraph projects {'
    print 'rankdir=BT;'
    print 'node [shape=rect];'
    for p in projects():
        for dep in p.canonical_deps():
            print '"' + p.name + '"->"' + dep + '";'
        if hasattr(p, '_declaredAnnotationProcessors'):
            for ap in p._declaredAnnotationProcessors:
                print '"' + p.name + '"->"' + ap + '" [style="dashed"];'
    print '}'

def _source_locator_memento(deps):
    slm = XMLDoc()
    slm.open('sourceLookupDirector')
    slm.open('sourceContainers', {'duplicates' : 'false'})

    javaCompliance = None

    for dep in deps:
        if dep.isLibrary():
            if hasattr(dep, 'eclipse.container'):
                memento = XMLDoc().element('classpathContainer', {'path' : getattr(dep, 'eclipse.container')}).xml(standalone='no')
                slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})
            elif dep.get_source_path(resolve=True):
                memento = XMLDoc().element('archive', {'detectRoot' : 'true', 'path' : dep.get_source_path(resolve=True)}).xml(standalone='no')
                slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.debug.core.containerType.externalArchive'})
        elif dep.isProject():
            if dep.native:
                continue
            memento = XMLDoc().element('javaProject', {'name' : dep.name}).xml(standalone='no')
            slm.element('container', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.javaProject'})
            if javaCompliance is None or dep.javaCompliance > javaCompliance:
                javaCompliance = dep.javaCompliance

    if javaCompliance:
        memento = XMLDoc().element('classpathContainer', {'path' : 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/JavaSE-' + str(javaCompliance)}).xml(standalone='no')
        slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})
    else:
        memento = XMLDoc().element('classpathContainer', {'path' : 'org.eclipse.jdt.launching.JRE_CONTAINER'}).xml(standalone='no')
        slm.element('classpathContainer', {'memento' : memento, 'typeId':'org.eclipse.jdt.launching.sourceContainer.classpathContainer'})

    slm.close('sourceContainers')
    slm.close('sourceLookupDirector')
    return slm

def make_eclipse_attach(suite, hostname, port, name=None, deps=None):
    """
    Creates an Eclipse launch configuration file for attaching to a Java process.
    """
    if deps is None:
        deps = []
    slm = _source_locator_memento(deps)
    launch = XMLDoc()
    launch.open('launchConfiguration', {'type' : 'org.eclipse.jdt.launching.remoteJavaApplication'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_id', 'value' : 'org.eclipse.jdt.launching.sourceLocator.JavaSourceLookupDirector'})
    launch.element('stringAttribute', {'key' : 'org.eclipse.debug.core.source_locator_memento', 'value' : '%s'})
    launch.element('booleanAttribute', {'key' : 'org.eclipse.jdt.launching.ALLOW_TERMINATE', 'value' : 'true'})
    launch.open('mapAttribute', {'key' : 'org.eclipse.jdt.launching.CONNECT_MAP'})
    launch.element('mapEntry', {'key' : 'hostname', 'value' : hostname})
    launch.element('mapEntry', {'key' : 'port', 'value' : port})
    launch.close('mapAttribute')
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.PROJECT_ATTR', 'value' : ''})
    launch.element('stringAttribute', {'key' : 'org.eclipse.jdt.launching.VM_CONNECTOR_ID', 'value' : 'org.eclipse.jdt.launching.socketAttachConnector'})
    launch.close('launchConfiguration')
    launch = launch.xml(newl='\n', standalone='no') % slm.xml(escape=True, standalone='no')

    if name is None:
        if len(suites()) == 1:
            suitePrefix = ''
        else:
            suitePrefix = suite.name + '-'
        name = suitePrefix + 'attach-' + hostname + '-' + port
    eclipseLaunches = join(suite.mxDir, 'eclipse-launches')
    if not exists(eclipseLaunches):
        os.makedirs(eclipseLaunches)
    launchFile = join(eclipseLaunches, name + '.launch')
    return update_file(launchFile, launch), launchFile

def make_eclipse_launch(javaArgs, jre, name=None, deps=None):
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
        if a == '-cp' or a == '-classpath':
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
        log('Cannot create Eclipse launch configuration without main class or jar file: java ' + ' '.join(javaArgs))
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
            for s in suites():
                deps += [p for p in s.projects if e == p.output_dir()]
                deps += [l for l in s.libs if e == l.get_path(False)]

    slm = _source_locator_memento(deps)

    launch = XMLDoc()
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

    eclipseLaunches = join('mx', 'eclipse-launches')
    if not exists(eclipseLaunches):
        os.makedirs(eclipseLaunches)
    return update_file(join(eclipseLaunches, name + '.launch'), launch)

def eclipseinit(args, buildProcessorJars=True, refreshOnly=False):
    """(re)generate Eclipse project configurations and working sets"""
    for s in suites(True):
        _eclipseinit_suite(args, s, buildProcessorJars, refreshOnly)

    generate_eclipse_workingsets()

def _check_ide_timestamp(suite, configZip, ide):
    """return True if and only if the projects file, imports file, eclipse-settings files, and mx itself are all older than configZip"""
    suitePyFiles = [join(suite.mxDir, e) for e in os.listdir(suite.mxDir) if e.startswith('suite') and e.endswith('.py')]
    if configZip.isOlderThan(suitePyFiles):
        return False
    if configZip.isOlderThan(suite.import_timestamp()):
        return False
    # Assume that any mx change might imply changes to the generated IDE files
    if configZip.isOlderThan(__file__):
        return False

    if ide == 'eclipse':
        eclipseSettingsDir = join(suite.mxDir, 'eclipse-settings')
        if exists(eclipseSettingsDir):
            for name in os.listdir(eclipseSettingsDir):
                path = join(eclipseSettingsDir, name)
                if configZip.isOlderThan(path):
                    return False
    return True

def _eclipseinit_project(p, files=None, libFiles=None):
    assert java(p.javaCompliance)

    if not exists(p.dir):
        os.makedirs(p.dir)

    out = XMLDoc()
    out.open('classpath')

    for src in p.srcDirs:
        srcDir = join(p.dir, src)
        if not exists(srcDir):
            os.mkdir(srcDir)
        out.element('classpathentry', {'kind' : 'src', 'path' : src})

    processorPath = p.annotation_processors_path()
    if processorPath:
        genDir = p.source_gen_dir()
        if not exists(genDir):
            os.mkdir(genDir)
        out.open('classpathentry', {'kind' : 'src', 'path' : 'src_gen'})
        if p.uses_annotation_processor_library():
            # ignore warnings produced by third-party annotation processors
            out.open('attributes')
            out.element('attribute', {'name' : 'ignore_optional_problems', 'value' : 'true'})
            out.close('attributes')
        out.close('classpathentry')
        if files:
            files.append(genDir)

    # Every Java program depends on a JRE
    out.element('classpathentry', {'kind' : 'con', 'path' : 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/JavaSE-' + str(p.javaCompliance)})

    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        out.element('classpathentry', {'kind' : 'con', 'path' : 'org.eclipse.pde.core.requiredPlugins'})

    containerDeps = set()
    libraryDeps = set()
    projectDeps = set()

    for dep in p.all_deps([], True):
        if dep == p:
            continue
        if dep.isLibrary():
            if hasattr(dep, 'eclipse.container'):
                container = getattr(dep, 'eclipse.container')
                containerDeps.add(container)
                libraryDeps -= set(dep.all_deps([], True))
            else:
                libraryDeps.add(dep)
        elif dep.isProject():
            projectDeps.add(dep)

    for dep in sorted(containerDeps):
        out.element('classpathentry', {'exported' : 'true', 'kind' : 'con', 'path' : dep})

    for dep in sorted(libraryDeps):
        path = dep.path
        dep.get_path(resolve=True)

        # Relative paths for "lib" class path entries have various semantics depending on the Eclipse
        # version being used (e.g. see https://bugs.eclipse.org/bugs/show_bug.cgi?id=274737) so it's
        # safest to simply use absolute paths.

        # It's important to use dep.suite as the location for when one suite references
        # a library in another suite.
        path = _make_absolute(path, dep.suite.dir)

        attributes = {'exported' : 'true', 'kind' : 'lib', 'path' : path}

        sourcePath = dep.get_source_path(resolve=True)
        if sourcePath is not None:
            attributes['sourcepath'] = sourcePath
        out.element('classpathentry', attributes)
        if libFiles:
            libFiles.append(path)

    for dep in sorted(projectDeps):
        out.element('classpathentry', {'combineaccessrules' : 'false', 'exported' : 'true', 'kind' : 'src', 'path' : '/' + dep.name})

    out.element('classpathentry', {'kind' : 'output', 'path' : getattr(p, 'eclipse.output', 'bin')})
    out.close('classpath')
    classpathFile = join(p.dir, '.classpath')
    update_file(classpathFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(classpathFile)

    csConfig = join(project(p.checkstyleProj).dir, '.checkstyle_checks.xml')
    if exists(csConfig):
        out = XMLDoc()

        dotCheckstyle = join(p.dir, ".checkstyle")
        checkstyleConfigPath = '/' + p.checkstyleProj + '/.checkstyle_checks.xml'
        out.open('fileset-config', {'file-format-version' : '1.2.0', 'simple-config' : 'true'})
        out.open('local-check-config', {'name' : 'Checks', 'location' : checkstyleConfigPath, 'type' : 'project', 'description' : ''})
        out.element('additional-data', {'name' : 'protect-config-file', 'value' : 'false'})
        out.close('local-check-config')
        out.open('fileset', {'name' : 'all', 'enabled' : 'true', 'check-config-name' : 'Checks', 'local' : 'true'})
        out.element('file-match-pattern', {'match-pattern' : '.', 'include-pattern' : 'true'})
        out.close('fileset')
        out.open('filter', {'name' : 'all', 'enabled' : 'true', 'check-config-name' : 'Checks', 'local' : 'true'})
        out.element('filter-data', {'value' : 'java'})
        out.close('filter')

        exclude = join(p.dir, '.checkstyle.exclude')
        if exists(exclude):
            out.open('filter', {'name' : 'FilesFromPackage', 'enabled' : 'true'})
            with open(exclude) as f:
                for line in f:
                    if not line.startswith('#'):
                        line = line.strip()
                        exclDir = join(p.dir, line)
                        assert isdir(exclDir), 'excluded source directory listed in ' + exclude + ' does not exist or is not a directory: ' + exclDir
                    out.element('filter-data', {'value' : line})
            out.close('filter')

        out.close('fileset-config')
        update_file(dotCheckstyle, out.xml(indent='  ', newl='\n'))
        if files:
            files.append(dotCheckstyle)
    else:
        # clean up existing .checkstyle file
        dotCheckstyle = join(p.dir, ".checkstyle")
        if exists(dotCheckstyle):
            os.unlink(dotCheckstyle)

    out = XMLDoc()
    out.open('projectDescription')
    out.element('name', data=p.name)
    out.element('comment', data='')
    out.element('projects', data='')
    out.open('buildSpec')
    out.open('buildCommand')
    out.element('name', data='org.eclipse.jdt.core.javabuilder')
    out.element('arguments', data='')
    out.close('buildCommand')
    if exists(csConfig):
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

    if p.definedAnnotationProcessorsDist:
        # Create a launcher that will (re)build the annotation processor
        # jar any time one of its sources is modified.
        dist = p.definedAnnotationProcessorsDist

        distProjects = [d for d in dist.sorted_deps(transitive=True) if d.isProject()]
        relevantResources = []
        for p in distProjects:
            for srcDir in p.source_dirs():
                relevantResources.append(join(p.name, os.path.relpath(srcDir, p.dir)))
            relevantResources.append(join(p.name, os.path.relpath(p.output_dir(), p.dir)))

        # The path should always be p.name/dir independent of where the workspace actually is.
        # So we use the parent folder of the project, whatever that is, to generate such a relative path.
        logicalWorkspaceRoot = os.path.dirname(p.dir)
        refreshFile = os.path.relpath(p.definedAnnotationProcessorsDist.path, logicalWorkspaceRoot)
        _genEclipseBuilder(out, p, 'CreateAnnotationProcessorJar', 'archive @' + dist.name, refresh=True, refreshFile=refreshFile, relevantResources=relevantResources, async=True, xmlIndent='', xmlStandalone='no')

    out.close('buildSpec')
    out.open('natures')
    out.element('nature', data='org.eclipse.jdt.core.javanature')
    if exists(csConfig):
        out.element('nature', data='net.sf.eclipsecs.core.CheckstyleNature')
    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        out.element('nature', data='org.eclipse.pde.PluginNature')
    out.close('natures')
    out.close('projectDescription')
    projectFile = join(p.dir, '.project')
    update_file(projectFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(projectFile)

    settingsDir = join(p.dir, ".settings")
    if not exists(settingsDir):
        os.mkdir(settingsDir)

    # collect the defaults from mxtool
    defaultEclipseSettingsDir = join(dirname(__file__), 'eclipse-settings')
    esdict = {}
    if exists(defaultEclipseSettingsDir):
        for name in os.listdir(defaultEclipseSettingsDir):
            if isfile(join(defaultEclipseSettingsDir, name)):
                esdict[name] = os.path.abspath(join(defaultEclipseSettingsDir, name))

    # check for suite overrides
    eclipseSettingsDir = join(p.suite.mxDir, 'eclipse-settings')
    if exists(eclipseSettingsDir):
        for name in os.listdir(eclipseSettingsDir):
            if isfile(join(eclipseSettingsDir, name)):
                esdict[name] = os.path.abspath(join(eclipseSettingsDir, name))

    # check for project overrides
    projectSettingsDir = join(p.dir, 'eclipse-settings')
    if exists(projectSettingsDir):
        for name in os.listdir(projectSettingsDir):
            if isfile(join(projectSettingsDir, name)):
                esdict[name] = os.path.abspath(join(projectSettingsDir, name))

    # copy a possibly modified file to the project's .settings directory
    for name, path in esdict.iteritems():
        # ignore this file altogether if this project has no annotation processors
        if name == "org.eclipse.jdt.apt.core.prefs" and not processorPath:
            continue

        with open(path) as f:
            content = f.read()
        content = content.replace('${javaCompliance}', str(p.javaCompliance))
        if processorPath:
            content = content.replace('org.eclipse.jdt.core.compiler.processAnnotations=disabled', 'org.eclipse.jdt.core.compiler.processAnnotations=enabled')
        update_file(join(settingsDir, name), content)
        if files:
            files.append(join(settingsDir, name))

    if processorPath:
        out = XMLDoc()
        out.open('factorypath')
        out.element('factorypathentry', {'kind' : 'PLUGIN', 'id' : 'org.eclipse.jst.ws.annotations.core', 'enabled' : 'true', 'runInBatchMode' : 'false'})
        for e in processorPath.split(os.pathsep):
            out.element('factorypathentry', {'kind' : 'EXTJAR', 'id' : e, 'enabled' : 'true', 'runInBatchMode' : 'false'})
        out.close('factorypath')
        update_file(join(p.dir, '.factorypath'), out.xml(indent='\t', newl='\n'))
        if files:
            files.append(join(p.dir, '.factorypath'))

def _eclipseinit_suite(args, suite, buildProcessorJars=True, refreshOnly=False):
    configZip = TimeStampFile(join(suite.mxDir, 'eclipse-config.zip'))
    configLibsZip = join(suite.mxDir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    if _check_ide_timestamp(suite, configZip, 'eclipse'):
        logv('[Eclipse configurations are up to date - skipping]')
        return



    files = []
    libFiles = []
    if buildProcessorJars:
        files += _processorjars_suite(suite)

    for p in suite.projects:
        if p.native:
            continue
        _eclipseinit_project(p, files, libFiles)

    _, launchFile = make_eclipse_attach(suite, 'localhost', '8000', deps=sorted_deps(projectNames=None, includeLibs=True))
    files.append(launchFile)

    # Create an Eclipse project for each distribution that will create/update the archive
    # for the distribution whenever any (transitively) dependent project of the
    # distribution is updated.
    for dist in suite.dists:
        projectDir = dist.get_ide_project_dir()
        if not projectDir:
            continue
        if not exists(projectDir):
            os.makedirs(projectDir)
        distProjects = [d for d in dist.sorted_deps(transitive=True) if d.isProject()]
        relevantResources = []
        for p in distProjects:
            for srcDir in p.source_dirs():
                relevantResources.append(join(p.name, os.path.relpath(srcDir, p.dir)))
            relevantResources.append(join(p.name, os.path.relpath(p.output_dir(), p.dir)))
        out = XMLDoc()
        out.open('projectDescription')
        out.element('name', data=dist.name)
        out.element('comment', data='Updates ' + dist.path + ' if a project dependency of ' + dist.name + ' is updated')
        out.open('projects')
        for p in distProjects:
            out.element('project', data=p.name)
        for d in dist.distDependencies:
            out.element('project', data=d)
        out.close('projects')
        out.open('buildSpec')
        dist.dir = projectDir
        dist.javaCompliance = max([p.javaCompliance for p in distProjects])
        _genEclipseBuilder(out, dist, 'Create' + dist.name + 'Dist', 'archive @' + dist.name, relevantResources=relevantResources, logToFile=True, refresh=False, async=True)
        out.close('buildSpec')
        out.open('natures')
        out.element('nature', data='org.eclipse.jdt.core.javanature')
        out.close('natures')
        out.close('projectDescription')
        projectFile = join(projectDir, '.project')
        update_file(projectFile, out.xml(indent='\t', newl='\n'))
        files.append(projectFile)

    _zip_files(files, suite.dir, configZip.path)
    _zip_files(libFiles, suite.dir, configLibsZip)

def _zip_files(files, baseDir, zipPath):
    fd, tmp = tempfile.mkstemp(suffix='', prefix=basename(zipPath), dir=baseDir)
    try:
        zf = zipfile.ZipFile(tmp, 'w')
        for f in sorted(set(files)):
            relpath = os.path.relpath(f, baseDir)
            arcname = relpath.replace(os.sep, '/')
            zf.write(f, arcname)
        zf.close()
        os.close(fd)
        # Atomic on Unix
        shutil.move(tmp, zipPath)
        # Correct the permissions on the temporary file which is created with restrictive permissions
        os.chmod(zipPath, 0o666 & ~currentUmask)
    finally:
        if exists(tmp):
            os.remove(tmp)

def _genEclipseBuilder(dotProjectDoc, p, name, mxCommand, refresh=True, refreshFile=None, relevantResources=None, async=False, logToConsole=False, logToFile=False, appendToLogFile=True, xmlIndent='\t', xmlStandalone=None):
    externalToolDir = join(p.dir, '.externalToolBuilders')
    launchOut = XMLDoc()
    consoleOn = 'true' if logToConsole else 'false'
    launchOut.open('launchConfiguration', {'type' : 'org.eclipse.ui.externaltools.ProgramBuilderLaunchConfigurationType'})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.core.capture_output', 'value': consoleOn})
    launchOut.open('mapAttribute', {'key' : 'org.eclipse.debug.core.environmentVariables'})
    launchOut.element('mapEntry', {'key' : 'JAVA_HOME', 'value' : _default_java_home.jdk})
    launchOut.element('mapEntry', {'key' : 'EXTRA_JAVA_HOMES', 'value' :  os.pathsep.join([extraJavaHome.jdk for extraJavaHome in _extra_java_homes])})
    launchOut.close('mapAttribute')

    if refresh:
        if refreshFile is None:
            refreshScope = '${project}'
        else:
            refreshScope = '${working_set:<?xml version="1.0" encoding="UTF-8"?><resources><item path="' + refreshFile + '" type="1"/></resources>}'

        launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.core.ATTR_REFRESH_RECURSIVE', 'value':  'false'})
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.debug.core.ATTR_REFRESH_SCOPE', 'value':  refreshScope})

    if relevantResources is not None:
        resources = '${working_set:<?xml version="1.0" encoding="UTF-8"?><resources>'
        for relevantResource in relevantResources:
            resources += '<item path="' + relevantResource + '" type="2" />'
        resources += '</resources>}'
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_BUILD_SCOPE', 'value': resources})

    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_CONSOLE_OUTPUT_ON', 'value': consoleOn})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_LAUNCH_IN_BACKGROUND', 'value': 'true' if async else 'false'})
    if logToFile:
        logFile = join(externalToolDir, name + '.log')
        launchOut.element('stringAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_CAPTURE_IN_FILE', 'value': logFile})
        launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.ui.ATTR_APPEND_TO_FILE', 'value': 'true' if appendToLogFile else 'false'})

    # expect to find the OS command to invoke mx in the same directory
    baseDir = dirname(os.path.abspath(__file__))

    cmd = 'mx'
    if get_os() == 'windows':
        cmd = 'mx.cmd'
    cmdPath = join(baseDir, cmd)
    if not os.path.exists(cmdPath):
        # backwards compatibility for when the commands lived in parent of mxtool
        if cmd == 'mx':
            cmd = 'mx.sh'
        cmdPath = join(dirname(baseDir), cmd)
        if not os.path.exists(cmdPath):
            abort('cannot locate ' + cmd)

    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_LOCATION', 'value':  cmdPath})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_RUN_BUILD_KINDS', 'value': 'auto,full,incremental'})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_TOOL_ARGUMENTS', 'value': mxCommand})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_TRIGGERS_CONFIGURED', 'value': 'true'})
    launchOut.element('stringAttribute', {'key' : 'org.eclipse.ui.externaltools.ATTR_WORKING_DIRECTORY', 'value': p.suite.dir})


    launchOut.close('launchConfiguration')

    if not exists(externalToolDir):
        os.makedirs(externalToolDir)
    update_file(join(externalToolDir, name + '.launch'), launchOut.xml(indent=xmlIndent, standalone=xmlStandalone, newl='\n'))

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
    if os.environ.has_key('WORKSPACE'):
        expected_wsroot = os.environ['WORKSPACE']
    else:
        expected_wsroot = _primary_suite.dir

    wsroot = _find_eclipse_wsroot(expected_wsroot)
    if wsroot is None:
        # failed to find it
        wsroot = expected_wsroot

    wsdir = join(wsroot, wsloc)
    if not exists(wsdir):
        wsdir = wsroot
        logv('Could not find Eclipse metadata directory. Please place ' + wsfilename + ' in ' + wsloc + ' manually.')
    wspath = join(wsdir, wsfilename)

    def _add_to_working_set(key, value):
        if not workingSets.has_key(key):
            workingSets[key] = [value]
        else:
            workingSets[key].append(value)

    # gather working set info from project data
    workingSets = dict()
    for p in projects():
        if p.workingSets is None:
            continue
        for w in p.workingSets.split(","):
            _add_to_working_set(w, p.name)

    # the mx metdata directories are included in the appropriate working sets
    _add_to_working_set('MX', 'mxtool')
    for suite in suites(True):
        _add_to_working_set('MX', basename(suite.mxDir))

    if exists(wspath):
        wsdoc = _copy_workingset_xml(wspath, workingSets)
    else:
        wsdoc = _make_workingset_xml(workingSets)

    update_file(wspath, wsdoc.xml(newl='\n'))

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
    wsdoc = XMLDoc()
    wsdoc.open('workingSetManager')

    for w in sorted(workingSets.keys()):
        _workingset_open(wsdoc, w)
        for p in workingSets[w]:
            _workingset_element(wsdoc, p)
        wsdoc.close('workingSet')

    wsdoc.close('workingSetManager')
    return wsdoc

def _copy_workingset_xml(wspath, workingSets):
    target = XMLDoc()
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
            if attributes.has_key('name'):
                ps.current_ws_name = attributes['name']
                if attributes.has_key('aggregate') and attributes['aggregate'] == 'true':
                    ps.aggregate_ws = True
                    ps.current_ws = None
                elif workingSets.has_key(ps.current_ws_name):
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
            elif not attributes.has_key('elementID') and attributes.has_key('factoryID') and attributes.has_key('path') and attributes.has_key('type'):
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
    with open(wspath, 'r') as wsfile:
        parser.ParseFile(wsfile)

    target.close('workingSetManager')
    return target

def _workingset_open(wsdoc, ws):
    wsdoc.open('workingSet', {'editPageID': 'org.eclipse.jdt.ui.JavaWorkingSetPage', 'factoryID': 'org.eclipse.ui.internal.WorkingSetFactory', 'id': 'wsid_' + ws, 'label': ws, 'name': ws})

def _workingset_element(wsdoc, p):
    wsdoc.element('item', {'elementID': '=' + p, 'factoryID': 'org.eclipse.jdt.ui.PersistableJavaElementFactory'})

def netbeansinit(args, refreshOnly=False, buildProcessorJars=True):
    """(re)generate NetBeans project configurations"""

    for suite in suites(True):
        _netbeansinit_suite(args, suite, refreshOnly, buildProcessorJars)

def _netbeansinit_project(p, jdks=None, files=None, libFiles=None):
    if not exists(join(p.dir, 'nbproject')):
        os.makedirs(join(p.dir, 'nbproject'))

    jdk = java(p.javaCompliance)
    assert jdk

    if jdks:
        jdks.add(jdk)

    out = XMLDoc()
    out.open('project', {'name' : p.name, 'default' : 'default', 'basedir' : '.'})
    out.element('description', data='Builds, tests, and runs the project ' + p.name + '.')
    out.element('import', {'file' : 'nbproject/build-impl.xml'})
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
    out.open('target', {'name' : 'compile'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true'})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.jdk})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'build'})
    out.element('arg', {'value' : '--only'})
    out.element('arg', {'value' : p.name})
    out.element('arg', {'value' : '--force-javac'})
    out.element('arg', {'value' : '--no-native'})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'jar', 'depends' : 'compile'})
    out.close('target')
    out.close('project')
    update_file(join(p.dir, 'build.xml'), out.xml(indent='\t', newl='\n'))
    if files:
        files.append(join(p.dir, 'build.xml'))

    out = XMLDoc()
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

    firstDep = True
    for dep in p.all_deps([], includeLibs=False, includeAnnotationProcessors=True):
        if dep == p:
            continue

        if dep.isProject():
            n = dep.name.replace('.', '_')
            if firstDep:
                out.open('references', {'xmlns' : 'http://www.netbeans.org/ns/ant-project-references/1'})
                firstDep = False

            out.open('reference')
            out.element('foreign-project', data=n)
            out.element('artifact-type', data='jar')
            out.element('script', data='build.xml')
            out.element('target', data='jar')
            out.element('clean-target', data='clean')
            out.element('id', data='jar')
            out.close('reference')

    if not firstDep:
        out.close('references')

    out.close('configuration')
    out.close('project')
    update_file(join(p.dir, 'nbproject', 'project.xml'), out.xml(indent='    ', newl='\n'))
    if files:
        files.append(join(p.dir, 'nbproject', 'project.xml'))

    out = StringIO.StringIO()
    jdkPlatform = 'JDK_' + str(jdk.version)

    annotationProcessorEnabled = "false"
    annotationProcessorSrcFolder = ""
    if len(p.annotation_processors()) > 0:
        annotationProcessorEnabled = "true"
        genSrcDir = p.source_gen_dir()
        if not exists(genSrcDir):
            os.makedirs(genSrcDir)
        annotationProcessorSrcFolder = "src.ap-source-output.dir=" + genSrcDir

    content = """
annotation.processing.enabled=""" + annotationProcessorEnabled + """
annotation.processing.enabled.in.editor=""" + annotationProcessorEnabled + """
annotation.processing.processors.list=
annotation.processing.run.all.processors=true
application.title=""" + p.name + """
application.vendor=mx
build.classes.dir=${build.dir}
build.classes.excludes=**/*.java,**/*.form
# This directory is removed when the project is cleaned:
build.dir=bin
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
main.class=
manifest.file=manifest.mf
meta.inf.dir=${src.dir}/META-INF
mkdist.disabled=false
platforms.""" + jdkPlatform + """.home=""" + jdk.jdk + """
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
""" + annotationProcessorSrcFolder + """
source.encoding=UTF-8""".replace(':', os.pathsep).replace('/', os.sep)
    print >> out, content

    mainSrc = True
    for src in p.srcDirs:
        srcDir = join(p.dir, src)
        if not exists(srcDir):
            os.mkdir(srcDir)
        ref = 'file.reference.' + p.name + '-' + src
        print >> out, ref + '=' + src
        if mainSrc:
            print >> out, 'src.dir=${' + ref + '}'
            mainSrc = False
        else:
            print >> out, 'src.' + src + '.dir=${' + ref + '}'

    javacClasspath = []

    deps = p.all_deps([], True)
    annotationProcessorOnlyDeps = []
    if len(p.annotation_processors()) > 0:
        for ap in p.annotation_processors():
            apDep = dependency(ap)
            if not apDep in deps:
                deps.append(apDep)
                annotationProcessorOnlyDeps.append(apDep)

    annotationProcessorReferences = []

    for dep in deps:
        if dep == p:
            continue

        if dep.isLibrary():
            path = dep.get_path(resolve=True)
            if path:
                if os.sep == '\\':
                    path = path.replace('\\', '\\\\')
                ref = 'file.reference.' + dep.name + '-bin'
                print >> out, ref + '=' + path
                if libFiles:
                    libFiles.append(path)

        elif dep.isProject():
            n = dep.name.replace('.', '_')
            relDepPath = os.path.relpath(dep.dir, p.dir).replace(os.sep, '/')
            ref = 'reference.' + n + '.jar'
            print >> out, 'project.' + n + '=' + relDepPath
            print >> out, ref + '=${project.' + n + '}/dist/' + dep.name + '.jar'

        if not dep in annotationProcessorOnlyDeps:
            javacClasspath.append('${' + ref + '}')
        else:
            annotationProcessorReferences.append('${' + ref + '}')

    print >> out, 'javac.classpath=\\\n    ' + (os.pathsep + '\\\n    ').join(javacClasspath)
    print >> out, 'javac.processorpath=' + (os.pathsep + '\\\n    ').join(['${javac.classpath}'] + annotationProcessorReferences)
    print >> out, 'javac.test.processorpath=' + (os.pathsep + '\\\n    ').join(['${javac.test.classpath}'] + annotationProcessorReferences)

    update_file(join(p.dir, 'nbproject', 'project.properties'), out.getvalue())
    out.close()
    if files:
        files.append(join(p.dir, 'nbproject', 'project.properties'))

def _netbeansinit_suite(args, suite, refreshOnly=False, buildProcessorJars=True):
    configZip = TimeStampFile(join(suite.mxDir, 'netbeans-config.zip'))
    configLibsZip = join(suite.mxDir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    if _check_ide_timestamp(suite, configZip, 'netbeans'):
        logv('[NetBeans configurations are up to date - skipping]')
        return

    files = []
    libFiles = []
    jdks = set()
    for p in suite.projects:
        if p.native:
            continue

        if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
            continue

        _netbeansinit_project(p, jdks, files, libFiles)

    log('If using NetBeans:')
    # http://stackoverflow.com/questions/24720665/cant-resolve-jdk-internal-package
    log('  1. Edit etc/netbeans.conf in your NetBeans installation and modify netbeans_default_options variable to include "-J-DCachingArchiveProvider.disableCtSym=true"')
    log('  2. Ensure that the following platform(s) are defined (Tools -> Java Platforms):')
    for jdk in jdks:
        log('        JDK_' + str(jdk.version))
    log('  3. Open/create a Project Group for the directory containing the projects (File -> Project Group -> New Group... -> Folder of Projects)')

    _zip_files(files, suite.dir, configZip.path)
    _zip_files(libFiles, suite.dir, configLibsZip)

def intellijinit(args, refreshOnly=False):
    """(re)generate Intellij project configurations"""
    # In a multiple suite context, the .idea directory in each suite
    # has to be complete and contain information that is repeated
    # in dependent suites.

    for suite in suites(True):
        _intellij_suite(args, suite, refreshOnly)

def _intellij_suite(args, suite, refreshOnly=False):

    libraries = set()

    ideaProjectDirectory = join(suite.dir, '.idea')

    if not exists(ideaProjectDirectory):
        os.mkdir(ideaProjectDirectory)
    nameFile = join(ideaProjectDirectory, '.name')
    update_file(nameFile, suite.name)
    modulesXml = XMLDoc()
    modulesXml.open('project', attributes={'version': '4'})
    modulesXml.open('component', attributes={'name': 'ProjectModuleManager'})
    modulesXml.open('modules')


    def _intellij_exclude_if_exists(xml, p, name):
        path = join(p.dir, name)
        if exists(path):
            xml.element('excludeFolder', attributes={'url':'file://$MODULE_DIR$/' + name})

    annotationProcessorProfiles = {}

    def _complianceToIntellijLanguageLevel(compliance):
        return 'JDK_1_' + str(compliance.value)

    # create the modules (1 module  = 1 Intellij project)
    for p in suite.projects_recursive():
        if p.native:
            continue

        assert java(p.javaCompliance)

        if not exists(p.dir):
            os.makedirs(p.dir)

        annotationProcessorProfileKey = tuple(p.annotation_processors())

        if not annotationProcessorProfileKey in annotationProcessorProfiles:
            annotationProcessorProfiles[annotationProcessorProfileKey] = [p]
        else:
            annotationProcessorProfiles[annotationProcessorProfileKey].append(p)

        intellijLanguageLevel = _complianceToIntellijLanguageLevel(p.javaCompliance)

        moduleXml = XMLDoc()
        moduleXml.open('module', attributes={'type': 'JAVA_MODULE', 'version': '4'})

        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'LANGUAGE_LEVEL': intellijLanguageLevel, 'inherit-compiler-output': 'false'})
        moduleXml.element('output', attributes={'url': 'file://$MODULE_DIR$/bin'})
        moduleXml.element('exclude-output')

        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        for src in p.srcDirs:
            srcDir = join(p.dir, src)
            if not exists(srcDir):
                os.mkdir(srcDir)
            moduleXml.element('sourceFolder', attributes={'url':'file://$MODULE_DIR$/' + src, 'isTestSource': 'false'})

        if len(p.annotation_processors()) > 0:
            genDir = p.source_gen_dir()
            if not exists(genDir):
                os.mkdir(genDir)
            moduleXml.element('sourceFolder', attributes={'url':'file://$MODULE_DIR$/' + os.path.relpath(genDir, p.dir), 'isTestSource': 'false'})

        for name in ['.externalToolBuilders', '.settings', 'nbproject']:
            _intellij_exclude_if_exists(moduleXml, p, name)
        moduleXml.close('content')

        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': 'JavaSDK', 'jdkName': str(p.javaCompliance)})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

        deps = p.all_deps([], True, includeAnnotationProcessors=True)
        for dep in deps:
            if dep == p:
                continue

            if dep.isLibrary():
                libraries.add(dep)
                moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
            elif dep.isProject():
                moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': dep.name})

        moduleXml.close('component')
        moduleXml.close('module')
        moduleFile = join(p.dir, p.name + '.iml')
        update_file(moduleFile, moduleXml.xml(indent='  ', newl='\n'))

        moduleFilePath = "$PROJECT_DIR$/" + os.path.relpath(moduleFile, suite.dir)
        modulesXml.element('module', attributes={'fileurl': 'file://' + moduleFilePath, 'filepath': moduleFilePath})

    modulesXml.close('modules')
    modulesXml.close('component')
    modulesXml.close('project')
    moduleXmlFile = join(ideaProjectDirectory, 'modules.xml')
    update_file(moduleXmlFile, modulesXml.xml(indent='  ', newl='\n'))

    librariesDirectory = join(ideaProjectDirectory, 'libraries')

    if not exists(librariesDirectory):
        os.mkdir(librariesDirectory)

    # Setup the libraries that were used above
    # TODO: setup all the libraries from the suite regardless of usage?
    for library in libraries:
        libraryXml = XMLDoc()

        libraryXml.open('component', attributes={'name': 'libraryTable'})
        libraryXml.open('library', attributes={'name': library.name})
        libraryXml.open('CLASSES')
        libraryXml.element('root', attributes={'url': 'jar://$PROJECT_DIR$/' + os.path.relpath(library.get_path(True), suite.dir) + '!/'})
        libraryXml.close('CLASSES')
        libraryXml.element('JAVADOC')
        if library.sourcePath:
            libraryXml.open('SOURCES')
            libraryXml.element('root', attributes={'url': 'jar://$PROJECT_DIR$/' + os.path.relpath(library.get_source_path(True), suite.dir) + '!/'})
            libraryXml.close('SOURCES')
        else:
            libraryXml.element('SOURCES')
        libraryXml.close('library')
        libraryXml.close('component')

        libraryFile = join(librariesDirectory, library.name + '.xml')
        update_file(libraryFile, libraryXml.xml(indent='  ', newl='\n'))



    # Set annotation processor profiles up, and link them to modules in compiler.xml
    compilerXml = XMLDoc()
    compilerXml.open('project', attributes={'version': '4'})
    compilerXml.open('component', attributes={'name': 'CompilerConfiguration'})

    compilerXml.element('option', attributes={'name': "DEFAULT_COMPILER", 'value': 'Javac'})
    compilerXml.element('resourceExtensions')
    compilerXml.open('wildcardResourcePatterns')
    compilerXml.element('entry', attributes={'name': '!?*.java'})
    compilerXml.close('wildcardResourcePatterns')

    if annotationProcessorProfiles:
        compilerXml.open('annotationProcessing')
        for processors, modules in sorted(annotationProcessorProfiles.iteritems()):
            compilerXml.open('profile', attributes={'default': 'false', 'name': '-'.join(processors), 'enabled': 'true'})
            compilerXml.element('sourceOutputDir', attributes={'name': 'src_gen'})  # TODO use p.source_gen_dir() ?
            compilerXml.element('outputRelativeToContentRoot', attributes={'value': 'true'})
            compilerXml.open('processorPath', attributes={'useClasspath': 'false'})
            for apName in processors:
                pDep = dependency(apName)
                for entry in pDep.all_deps([], True):
                    if entry.isLibrary():
                        compilerXml.element('entry', attributes={'name': '$PROJECT_DIR$/' + os.path.relpath(entry.path, suite.dir)})
                    elif entry.isProject():
                        assert entry.isProject()
                        compilerXml.element('entry', attributes={'name': '$PROJECT_DIR$/' + os.path.relpath(entry.output_dir(), suite.dir)})
            compilerXml.close('processorPath')
            for module in modules:
                compilerXml.element('module', attributes={'name': module.name})
            compilerXml.close('profile')
        compilerXml.close('annotationProcessing')

    compilerXml.close('component')
    compilerXml.close('project')
    compilerFile = join(ideaProjectDirectory, 'compiler.xml')
    update_file(compilerFile, compilerXml.xml(indent='  ', newl='\n'))

    # Wite misc.xml for global JDK config
    miscXml = XMLDoc()
    miscXml.open('project', attributes={'version': '4'})
    miscXml.element('component', attributes={'name': 'ProjectRootManager', 'version': '2', 'languageLevel': _complianceToIntellijLanguageLevel(java().javaCompliance), 'project-jdk-name': str(java().javaCompliance), 'project-jdk-type': 'JavaSDK'})
    miscXml.close('project')
    miscFile = join(ideaProjectDirectory, 'misc.xml')
    update_file(miscFile, miscXml.xml(indent='  ', newl='\n'))

    # TODO look into copyright settings
    # TODO should add vcs.xml support

def ideclean(args):
    """remove all IDE project configurations"""
    def rm(path):
        if exists(path):
            os.remove(path)

    for s in suites():
        rm(join(s.mxDir, 'eclipse-config.zip'))
        rm(join(s.mxDir, 'netbeans-config.zip'))
        shutil.rmtree(join(s.dir, '.idea'), ignore_errors=True)

    for p in projects():
        if p.native:
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
            log("Error removing {0}".format(p.name + '.jar'))

    for d in _dists.itervalues():
        if d.get_ide_project_dir():
            shutil.rmtree(d.get_ide_project_dir(), ignore_errors=True)

def ideinit(args, refreshOnly=False, buildProcessorJars=True):
    """(re)generate IDE project configurations"""
    mx_ide = os.environ.get('MX_IDE', 'all').lower()
    all_ides = mx_ide == 'all'
    if all_ides or mx_ide == 'eclipse':
        eclipseinit(args, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars)
    if all_ides or mx_ide == 'netbeans':
        netbeansinit(args, refreshOnly=refreshOnly, buildProcessorJars=buildProcessorJars)
    if all_ides or mx_ide == 'intellij':
        intellijinit(args, refreshOnly=refreshOnly)
    if not refreshOnly:
        fsckprojects([])

def fsckprojects(args):
    """find directories corresponding to deleted Java projects and delete them"""
    if not is_interactive():
        log('fsckprojects command must be run in an interactive shell')
        return
    hg = HgConfig()
    for suite in suites(True):
        projectDirs = [p.dir for p in suite.projects]
        distIdeDirs = [d.get_ide_project_dir() for d in suite.dists if d.get_ide_project_dir() is not None]
        for dirpath, dirnames, files in os.walk(suite.dir):
            if dirpath == suite.dir:
                # no point in traversing .hg or lib/
                dirnames[:] = [d for d in dirnames if d not in ['.hg', 'lib']]
                # if there are nested suites must not scan those now, as they are not in projectDirs
                if _src_suitemodel.nestedsuites_dirname() in dirnames:
                    dirnames.remove(_src_suitemodel.nestedsuites_dirname())
            elif dirpath in projectDirs:
                # don't traverse subdirs of an existing project in this suite
                dirnames[:] = []
            elif dirpath in distIdeDirs:
                # don't traverse subdirs of an existing distributions in this suite
                dirnames[:] = []
            else:
                projectConfigFiles = frozenset(['.classpath', '.project', 'nbproject'])
                indicators = projectConfigFiles.intersection(files)
                if len(indicators) != 0:
                    indicators = [os.path.relpath(join(dirpath, i), suite.dir) for i in indicators]
                    indicatorsInHg = hg.locate(suite.dir, indicators)
                    # Only proceed if there are indicator files that are not under HG
                    if len(indicators) > len(indicatorsInHg):
                        if not is_interactive() or ask_yes_no(dirpath + ' looks like a removed project -- delete it', 'n'):
                            shutil.rmtree(dirpath)
                            log('Deleted ' + dirpath)

def javadoc(args, parser=None, docDir='javadoc', includeDeps=True, stdDoclet=True):
    """generate javadoc for some/all Java projects"""

    parser = ArgumentParser(prog='mx javadoc') if parser is None else parser
    parser.add_argument('-d', '--base', action='store', help='base directory for output')
    parser.add_argument('--unified', action='store_true', help='put javadoc in a single directory instead of one per project')
    parser.add_argument('--force', action='store_true', help='(re)generate javadoc even if package-list file exists')
    parser.add_argument('--projects', action='store', help='comma separated projects to process (omit to process all projects)')
    parser.add_argument('--Wapi', action='store_true', dest='warnAPI', help='show warnings about using internal APIs')
    parser.add_argument('--argfile', action='store', help='name of file containing extra javadoc options')
    parser.add_argument('--arg', action='append', dest='extra_args', help='extra Javadoc arguments (e.g. --arg @-use)', metavar='@<arg>', default=[])
    parser.add_argument('-m', '--memory', action='store', help='-Xmx value to pass to underlying JVM')
    parser.add_argument('--packages', action='store', help='comma separated packages to process (omit to process all packages)')
    parser.add_argument('--exclude-packages', action='store', help='comma separated packages to exclude')

    args = parser.parse_args(args)

    # build list of projects to be processed
    if args.projects is not None:
        candidates = [project(name) for name in args.projects.split(',')]
    else:
        candidates = projects_opt_limit_to_suites()

    # optionally restrict packages within a project
    packages = []
    if args.packages is not None:
        packages = [name for name in args.packages.split(',')]

    exclude_packages = []
    if args.exclude_packages is not None:
        exclude_packages = [name for name in args.exclude_packages.split(',')]

    def outDir(p):
        if args.base is None:
            return join(p.dir, docDir)
        return join(args.base, p.name, docDir)

    def check_package_list(p):
        return not exists(join(outDir(p), 'package-list'))

    def assess_candidate(p, projects):
        if p in projects:
            return False
        if args.force or args.unified or check_package_list(p):
            projects.append(p)
            return True
        return False

    projects = []
    for p in candidates:
        if not p.native:
            if includeDeps:
                deps = p.all_deps([], includeLibs=False, includeSelf=False)
                for d in deps:
                    assess_candidate(d, projects)
            if not assess_candidate(p, projects):
                logv('[package-list file exists - skipping {0}]'.format(p.name))


    def find_packages(sourceDirs, pkgs=None):
        if pkgs is None:
            pkgs = set()
        for sourceDir in sourceDirs:
            for root, _, files in os.walk(sourceDir):
                if len([name for name in files if name.endswith('.java')]) != 0:
                    pkg = root[len(sourceDir) + 1:].replace(os.sep, '.')
                    if len(packages) == 0 or pkg in packages:
                        if len(exclude_packages) == 0 or not pkg in exclude_packages:
                            pkgs.add(pkg)
        return pkgs

    extraArgs = [a.lstrip('@') for a in args.extra_args]
    if args.argfile is not None:
        extraArgs += ['@' + args.argfile]
    memory = '2g'
    if args.memory is not None:
        memory = args.memory
    memory = '-J-Xmx' + memory

    if not args.unified:
        for p in projects:
            # The project must be built to ensure javadoc can find class files for all referenced classes
            build(['--no-native', '--projects', p.name])

            pkgs = find_packages(p.source_dirs(), set())
            deps = p.all_deps([], includeLibs=False, includeSelf=False)
            links = ['-link', 'http://docs.oracle.com/javase/' + str(p.javaCompliance.value) + '/docs/api/']
            out = outDir(p)
            for d in deps:
                depOut = outDir(d)
                links.append('-link')
                links.append(os.path.relpath(depOut, out))
            cp = classpath(p.name, includeSelf=True)
            sp = os.pathsep.join(p.source_dirs())
            overviewFile = join(p.dir, 'overview.html')
            delOverviewFile = False
            if not exists(overviewFile):
                with open(overviewFile, 'w') as fp:
                    print >> fp, '<html><body>Documentation for the <code>' + p.name + '</code> project.</body></html>'
                delOverviewFile = True
            nowarnAPI = []
            if not args.warnAPI:
                nowarnAPI.append('-XDignore.symbol.file')

            # windowTitle onloy applies to the standard doclet processor
            windowTitle = []
            if stdDoclet:
                windowTitle = ['-windowtitle', p.name + ' javadoc']
            try:
                log('Generating {2} for {0} in {1}'.format(p.name, out, docDir))
                projectJava = java(p.javaCompliance)

                # Once https://bugs.openjdk.java.net/browse/JDK-8041628 is fixed,
                # this should be reverted to:
                # javadocExe = java().javadoc
                # we can then also respect _opts.relatex_compliance
                javadocExe = projectJava.javadoc

                run([javadocExe, memory,
                     '-XDignore.symbol.file',
                     '-classpath', cp,
                     '-quiet',
                     '-d', out,
                     '-overview', overviewFile,
                     '-sourcepath', sp,
                     '-source', str(projectJava.javaCompliance)] +
                     projectJava.javadocLibOptions([]) +
                     ([] if projectJava.javaCompliance < JavaCompliance('1.8') else ['-Xdoclint:none']) +
                     links +
                     extraArgs +
                     nowarnAPI +
                     windowTitle +
                     list(pkgs))
                log('Generated {2} for {0} in {1}'.format(p.name, out, docDir))
            finally:
                if delOverviewFile:
                    os.remove(overviewFile)

    else:
        # The projects must be built to ensure javadoc can find class files for all referenced classes
        build(['--no-native'])

        pkgs = set()
        sp = []
        names = []
        for p in projects:
            find_packages(p.source_dirs(), pkgs)
            sp += p.source_dirs()
            names.append(p.name)

        links = ['-link', 'http://docs.oracle.com/javase/' + str(java().javaCompliance.value) + '/docs/api/']
        out = join(_primary_suite.dir, docDir)
        if args.base is not None:
            out = join(args.base, docDir)
        cp = classpath()
        sp = os.pathsep.join(sp)
        nowarnAPI = []
        if not args.warnAPI:
            nowarnAPI.append('-XDignore.symbol.file')
        log('Generating {2} for {0} in {1}'.format(', '.join(names), out, docDir))
        run([java().javadoc, memory,
             '-classpath', cp,
             '-quiet',
             '-d', out,
             '-sourcepath', sp] +
             ([] if java().javaCompliance < JavaCompliance('1.8') else ['-Xdoclint:none']) +
             links +
             extraArgs +
             nowarnAPI +
             list(pkgs))
        log('Generated {2} for {0} in {1}'.format(', '.join(names), out, docDir))

def site(args):
    """creates a website containing javadoc and the project dependency graph"""

    parser = ArgumentParser(prog='site')
    parser.add_argument('-d', '--base', action='store', help='directory for generated site', required=True, metavar='<dir>')
    parser.add_argument('--tmp', action='store', help='directory to use for intermediate results', metavar='<dir>')
    parser.add_argument('--name', action='store', help='name of overall documentation', required=True, metavar='<name>')
    parser.add_argument('--overview', action='store', help='path to the overview content for overall documentation', required=True, metavar='<path>')
    parser.add_argument('--projects', action='store', help='comma separated projects to process (omit to process all projects)')
    parser.add_argument('--jd', action='append', help='extra Javadoc arguments (e.g. --jd @-use)', metavar='@<arg>', default=[])
    parser.add_argument('--exclude-packages', action='store', help='comma separated packages to exclude', metavar='<pkgs>')
    parser.add_argument('--dot-output-base', action='store', help='base file name (relative to <dir>/all) for project dependency graph .svg and .jpg files generated by dot (omit to disable dot generation)', metavar='<path>')
    parser.add_argument('--title', action='store', help='value used for -windowtitle and -doctitle javadoc args for overall documentation (default: "<name>")', metavar='<title>')
    args = parser.parse_args(args)

    args.base = os.path.abspath(args.base)
    tmpbase = args.tmp if args.tmp else  tempfile.mkdtemp(prefix=basename(args.base) + '.', dir=dirname(args.base))
    unified = join(tmpbase, 'all')

    exclude_packages_arg = []
    if args.exclude_packages is not None:
        exclude_packages_arg = ['--exclude-packages', args.exclude_packages]

    projects = sorted_deps()
    projects_arg = []
    if args.projects is not None:
        projects_arg = ['--projects', args.projects]
        projects = [project(name) for name in args.projects.split(',')]

    extra_javadoc_args = []
    for a in args.jd:
        extra_javadoc_args.append('--arg')
        extra_javadoc_args.append('@' + a)

    try:
        # Create javadoc for each project
        javadoc(['--base', tmpbase] + exclude_packages_arg + projects_arg + extra_javadoc_args)

        # Create unified javadoc for all projects
        with open(args.overview) as fp:
            content = fp.read()
            idx = content.rfind('</body>')
            if idx != -1:
                args.overview = join(tmpbase, 'overview_with_projects.html')
                with open(args.overview, 'w') as fp2:
                    print >> fp2, content[0:idx]
                    print >> fp2, """<div class="contentContainer">
<table class="overviewSummary" border="0" cellpadding="3" cellspacing="0" summary="Projects table">
<caption><span>Projects</span><span class="tabEnd">&nbsp;</span></caption>
<tr><th class="colFirst" scope="col">Project</th><th class="colLast" scope="col">&nbsp;</th></tr>
<tbody>"""
                    color = 'row'
                    for p in projects:
                        print >> fp2, '<tr class="{1}Color"><td class="colFirst"><a href="../{0}/javadoc/index.html",target = "_top">{0}</a></td><td class="colLast">&nbsp;</td></tr>'.format(p.name, color)
                        color = 'row' if color == 'alt' else 'alt'

                    print >> fp2, '</tbody></table></div>'
                    print >> fp2, content[idx:]

        title = args.title if args.title is not None else args.name
        javadoc(['--base', tmpbase,
                 '--unified',
                 '--arg', '@-windowtitle', '--arg', '@' + title,
                 '--arg', '@-doctitle', '--arg', '@' + title,
                 '--arg', '@-overview', '--arg', '@' + args.overview] + exclude_packages_arg + projects_arg + extra_javadoc_args)

        if exists(unified):
            shutil.rmtree(unified)
        os.rename(join(tmpbase, 'javadoc'), unified)

        # Generate dependency graph with Graphviz
        if args.dot_output_base is not None:
            dotErr = None
            try:
                if not 'version' in subprocess.check_output(['dot', '-V'], stderr=subprocess.STDOUT):
                    dotErr = 'dot -V does not print a string containing "version"'
            except subprocess.CalledProcessError as e:
                dotErr = 'error calling "dot -V": {0}'.format(e)
            except OSError as e:
                dotErr = 'error calling "dot -V": {0}'.format(e)

            if dotErr != None:
                abort('cannot generate dependency graph: ' + dotErr)

            dot = join(tmpbase, 'all', str(args.dot_output_base) + '.dot')
            svg = join(tmpbase, 'all', str(args.dot_output_base) + '.svg')
            jpg = join(tmpbase, 'all', str(args.dot_output_base) + '.jpg')
            html = join(tmpbase, 'all', str(args.dot_output_base) + '.html')
            with open(dot, 'w') as fp:
                dim = len(projects)
                print >> fp, 'digraph projects {'
                print >> fp, 'rankdir=BT;'
                print >> fp, 'size = "' + str(dim) + ',' + str(dim) + '";'
                print >> fp, 'node [shape=rect, fontcolor="blue"];'
                # print >> fp, 'edge [color="green"];'
                for p in projects:
                    print >> fp, '"' + p.name + '" [URL = "../' + p.name + '/javadoc/index.html", target = "_top"]'
                    for dep in p.canonical_deps():
                        if dep in [proj.name for proj in projects]:
                            print >> fp, '"' + p.name + '" -> "' + dep + '"'
                depths = dict()
                for p in projects:
                    d = p.max_depth()
                    depths.setdefault(d, list()).append(p.name)
                print >> fp, '}'

            run(['dot', '-Tsvg', '-o' + svg, '-Tjpg', '-o' + jpg, dot])

            # Post-process generated SVG to remove title elements which most browsers
            # render as redundant (and annoying) tooltips.
            with open(svg, 'r') as fp:
                content = fp.read()
            content = re.sub('<title>.*</title>', '', content)
            content = re.sub('xlink:title="[^"]*"', '', content)
            with open(svg, 'w') as fp:
                fp.write(content)

            # Create HTML that embeds the svg file in an <object> frame
            with open(html, 'w') as fp:
                print >> fp, '<html><body><object data="{0}.svg" type="image/svg+xml"></object></body></html>'.format(args.dot_output_base)


        if args.tmp:
            shutil.copytree(tmpbase, args.base)
        else:
            shutil.move(tmpbase, args.base)

        print 'Created website - root is ' + join(args.base, 'all', 'index.html')

    finally:
        if not args.tmp and exists(tmpbase):
            shutil.rmtree(tmpbase)

def _kwArg(kwargs):
    if len(kwargs) > 0:
        return kwargs.pop(0)
    return None

def sclone(args):
    """clone a suite repository, and its imported suites"""
    parser = ArgumentParser(prog='mx sclone')
    parser.add_argument('--source', help='url/path of repo containing suite', metavar='<url>')
    parser.add_argument('--dest', help='destination directory (default basename of source)', metavar='<path>')
    parser.add_argument("--no-imports", action='store_true', help='do not clone imported suites')
    parser.add_argument('nonKWArgs', nargs=REMAINDER, metavar='source [dest]...')
    args = parser.parse_args(args)
    # check for non keyword args
    if args.source is None:
        args.source = _kwArg(args.nonKWArgs)
    if args.dest is None:
        args.dest = _kwArg(args.nonKWArgs)
    if len(args.nonKWArgs) > 0:
        abort('unrecognized args: ' + ' '.join(args.nonKWArgs))

    if args.source is None:
        # must be primary suite and dest is required
        if _primary_suite is None:
            abort('--source missing and no primary suite found')
        if args.dest is None:
            abort('--dest required when --source is not given')
        source = _primary_suite.dir
    else:
        source = args.source

    _hg.check()

    if args.dest is not None:
        dest = args.dest
    else:
        dest = basename(source)

    dest = os.path.abspath(dest)
    # We can now set the primary dir for the src/dst suitemodel
    _dst_suitemodel.set_primary_dir(dest)
    _src_suitemodel.set_primary_dir(source)

    _sclone(source, dest, None, args.no_imports)

def _sclone(source, dest, suite_import, no_imports):
    cmd = ['hg', 'clone']
    if suite_import is not None and suite_import.version is not None:
        cmd.append('-r')
        cmd.append(suite_import.version)
    cmd.append(source)
    cmd.append(dest)

    run(cmd)

    mxDir = _is_suite_dir(dest)
    if mxDir is None:
        warn(source + ' is not an mx suite')
        return None

    # create a Suite (without loading) to enable imports visitor
    s = Suite(mxDir, False, load=False)
    if not no_imports:
        s.visit_imports(_scloneimports_visitor, source=source)
    return s

def _scloneimports_visitor(s, suite_import, source, **extra_args):
    """
    cloneimports visitor for Suite.visit_imports.
    The destination information is encapsulated by 's'
    """
    _scloneimports(s, suite_import, source)

def _scloneimports_suitehelper(sdir):
    mxDir = _is_suite_dir(sdir)
    if mxDir is None:
        abort(sdir + ' is not an mx suite')
    else:
        # create a Suite (without loading) to enable imports visitor
        return Suite(mxDir, False, load=False)

def _scloneimports(s, suite_import, source):
    # clone first, then visit imports once we can locate them
    importee_source = _src_suitemodel.importee_dir(source, suite_import)
    importee_dest = _dst_suitemodel.importee_dir(s.dir, suite_import)
    if exists(importee_dest):
        # already exists in the suite model, but may be wrong version
        importee_suite = _scloneimports_suitehelper(importee_dest)
        if suite_import.version is not None and importee_suite.version() != suite_import.version:
            abort("imported version of " + suite_import.name + " in " + s.name + " does not match the version in already existing suite: " + importee_suite.dir)
        importee_suite.visit_imports(_scloneimports_visitor, source=importee_source)
    else:
        _sclone(importee_source, importee_dest, suite_import, False)
        # _clone handles the recursive visit of the new imports

def scloneimports(args):
    """clone the imports of an existing suite"""
    parser = ArgumentParser(prog='mx scloneimports')
    parser.add_argument('--source', help='url/path of repo containing suite', metavar='<url>')
    parser.add_argument('nonKWArgs', nargs=REMAINDER, metavar='source [dest]...')
    args = parser.parse_args(args)
    # check for non keyword args
    if args.source is None:
        args.source = _kwArg(args.nonKWArgs)

    if not os.path.isdir(args.source):
        abort(args.source + ' is not a directory')

    _hg.check()
    s = _scloneimports_suitehelper(args.source)

    default_path = _hg.default_push(args.source)

    if default_path is None:
        abort('no default path in ' + join(args.source, '.hg', 'hgrc'))

    # We can now set the primary dir for the dst suitemodel
    # N.B. source is effectively the destination and the default_path is the (original) source
    _dst_suitemodel.set_primary_dir(args.source)

    s.visit_imports(_scloneimports_visitor, source=default_path)

def _spush_import_visitor(s, suite_import, dest, checks, clonemissing, **extra_args):
    """push visitor for Suite.visit_imports"""
    if dest is not None:
        dest = _dst_suitemodel.importee_dir(dest, suite_import)
    _spush(suite(suite_import.name), suite_import, dest, checks, clonemissing)

def _spush_check_import_visitor(s, suite_import, **extra_args):
    """push check visitor for Suite.visit_imports"""
    currentTip = suite(suite_import.name).version()
    if currentTip != suite_import.version:
        abort('imported version of ' + suite_import.name + ' in suite ' + s.name + ' does not match tip')

def _spush(s, suite_import, dest, checks, clonemissing):
    if checks['on']:
        if not _hg.can_push(s, checks['strict']):
            abort('working directory ' + s.dir + ' contains uncommitted changes, push aborted')

    # check imports first
    if checks['on']:
        s.visit_imports(_spush_check_import_visitor)

    # ok, push imports
    s.visit_imports(_spush_import_visitor, dest=dest, checks=checks, clonemissing=clonemissing)

    dest_exists = True

    if clonemissing:
        if not os.path.exists(dest):
            dest_exists = False

    def add_version(cmd, suite_import):
        if suite_import is not None and suite_import.version is not None:
            cmd.append('-r')
            cmd.append(suite_import.version)

    if dest_exists:
        cmd = ['hg', '-R', s.dir, 'push']
        add_version(cmd, suite_import)
        if dest is not None:
            cmd.append(dest)
        rc = run(cmd, nonZeroIsFatal=False)
        if rc != 0:
            # rc of 1 not an error,  means no changes
            if rc != 1:
                abort("push failed, exit code " + str(rc))
    else:
        cmd = ['hg', 'clone']
        add_version(cmd, suite_import)
        cmd.append(s.dir)
        cmd.append(dest)
        run(cmd)

def spush(args):
    """push primary suite and all its imports"""
    parser = ArgumentParser(prog='mx spush')
    parser.add_argument('--dest', help='url/path of repo to push to (default as per hg push)', metavar='<path>')
    parser.add_argument('--no-checks', action='store_true', help='checks on status, versions are disabled')
    parser.add_argument('--no-strict', action='store_true', help='allows not tracked files')
    parser.add_argument('--clonemissing', action='store_true', help='clone missing imported repos at destination (forces --no-checks)')
    parser.add_argument('nonKWArgs', nargs=REMAINDER, metavar='source [dest]...')
    args = parser.parse_args(args)
    if args.dest is None:
        args.dest = _kwArg(args.nonKWArgs)
    if len(args.nonKWArgs) > 0:
        abort('unrecognized args: ' + ' '.join(args.nonKWArgs))

    _hg.check()
    s = _check_primary_suite()

    if args.clonemissing:
        if args.dest is None:
            abort('--dest required with --clonemissing')
        args.nochecks = True

    if args.dest is not None:
        _dst_suitemodel.set_primary_dir(args.dest)

    checks = dict()
    checks['on'] = not args.no_checks
    checks['strict'] = not args.no_strict
    _spush(s, None, args.dest, checks, args.clonemissing)

def _supdate_import_visitor(s, suite_import, **extra_args):
    _supdate(suite(suite_import.name), suite_import)

def _supdate(s, suite_import):
    s.visit_imports(_supdate_import_visitor)

    run(['hg', '-R', s.dir, 'update'])

def supdate(args):
    """update primary suite and all its imports"""

    parser = ArgumentParser(prog='mx supdate')
    args = parser.parse_args(args)
    _hg.check()
    s = _check_primary_suite()

    _supdate(s, None)

def _scheck_imports_visitor(s, suite_import, update_versions, updated_imports):
    """scheckimports visitor for Suite.visit_imports"""
    _scheck_imports(s, suite(suite_import.name), suite_import, update_versions, updated_imports)

def _scheck_imports(importing_suite, imported_suite, suite_import, update_versions, updated_imports):
    # check imports recursively
    imported_suite.visit_imports(_scheck_imports_visitor, update_versions=update_versions)

    currentTip = imported_suite.version()
    if currentTip != suite_import.version:
        print 'imported version of ' + imported_suite.name + ' in ' + importing_suite.name + ' does not match tip' + (': updating' if update_versions else '')

    if update_versions:
        suite_import.version = currentTip
        line = str(suite_import)
        updated_imports.write(line + '\n')

def scheckimports(args):
    """check that suite import versions are up to date"""
    parser = ArgumentParser(prog='mx scheckimports')
    parser.add_argument('--update-versions', action='store_true', help='update imported version ids')
    args = parser.parse_args(args)
    _hg.check()
    _check_primary_suite().visit_imports(_scheck_imports_visitor, update_versions=args.update_versions)

def _sforce_imports_visitor(s, suite_import, import_map, strict_versions, **extra_args):
    """sforceimports visitor for Suite.visit_imports"""
    _sforce_imports(s, suite(suite_import.name), suite_import, import_map, strict_versions)

def _sforce_imports(importing_suite, imported_suite, suite_import, import_map, strict_versions):
    if imported_suite.name in import_map:
        # we have seen this already
        if strict_versions:
            if suite_import.version and import_map[imported_suite.name] != suite_import.version:
                abort('inconsistent import versions for suite ' + imported_suite.name)
        return
    else:
        import_map[imported_suite.name] = suite_import.version

    if suite_import.version:
        currentTip = imported_suite.version()
        if currentTip != suite_import.version:
            run(['hg', '-R', imported_suite.dir, 'pull', '-r', suite_import.version])
            run(['hg', '-R', imported_suite.dir, 'update', '-C', '-r', suite_import.version])
            run(['hg', '-R', imported_suite.dir, 'purge'])
            # now (may) need to force imports of this suite if the above changed its import revs
            imported_suite.visit_imports(_sforce_imports_visitor, import_map=import_map, strict_versions=strict_versions)
    else:
        # simple case, pull the tip
        run(['hg', '-R', imported_suite.dir, 'pull', '-u'])

def sforceimports(args):
    '''force working directory revision of imported suites to match primary suite imports'''
    parser = ArgumentParser(prog='mx sforceimports')
    parser.add_argument('--strict-versions', action='store_true', help='strict version checking')
    args = parser.parse_args(args)
    _hg.check()
    _check_primary_suite().visit_imports(_sforce_imports_visitor, import_map=dict(), strict_versions=args.strict_versions)

def _spull_import_visitor(s, suite_import, update_versions, updated_imports):
    """pull visitor for Suite.visit_imports"""
    _spull(suite(suite_import.name), suite_import, update_versions, updated_imports)

def _spull(s, suite_import, update_versions, updated_imports):
    # s is primary suite if suite_import is None otherwise it is an imported suite
    # proceed top down to get any updated version ids first

    # by default we pull to the revision id in the import
    cmd = ['hg', '-R', s.dir, 'pull', '-u']
    if not update_versions and suite_import and suite_import.version:
        cmd += ['-r', suite_import.version]
    run(cmd, nonZeroIsFatal=False)
    if update_versions and updated_imports is not None:
        suite_import.version = s.version()
        updated_imports.write(str(suite_import) + '\n')

    s.visit_imports(_spull_import_visitor, update_versions=update_versions)

def spull(args):
    """pull primary suite and all its imports"""
    parser = ArgumentParser(prog='mx spull')
    parser.add_argument('--update-versions', action='store_true', help='update version ids of imported suites')
    args = parser.parse_args(args)

    _hg.check()
    _spull(_check_primary_suite(), None, args.update_versions, None)

def _sincoming_import_visitor(s, suite_import, **extra_args):
    _sincoming(suite(suite_import.name), suite_import)

def _sincoming(s, suite_import):
    s.visit_imports(_sincoming_import_visitor)

    run(['hg', '-R', s.dir, 'incoming'], nonZeroIsFatal=False)

def sincoming(args):
    '''check incoming for primary suite and all imports'''
    parser = ArgumentParser(prog='mx sincoming')
    args = parser.parse_args(args)
    _hg.check()
    s = _check_primary_suite()

    _sincoming(s, None)

def _stip_import_visitor(s, suite_import, **extra_args):
    _stip(suite(suite_import.name), suite_import)

def _stip(s, suite_import):
    s.visit_imports(_stip_import_visitor)

    print 'tip of %s' % s.name
    run(['hg', '-R', s.dir, 'tip'], nonZeroIsFatal=False)

def stip(args):
    '''check tip for primary suite and all imports'''
    parser = ArgumentParser(prog='mx stip')
    args = parser.parse_args(args)
    _hg.check()
    s = _check_primary_suite()

    _stip(s, None)

def findclass(args, logToConsole=True, matcher=lambda string, classname: string in classname):
    """find all classes matching a given substring"""
    matches = []
    for entry, filename in classpath_walk(includeBootClasspath=True):
        if filename.endswith('.class'):
            if isinstance(entry, zipfile.ZipFile):
                classname = filename.replace('/', '.')
            else:
                classname = filename.replace(os.sep, '.')
            classname = classname[:-len('.class')]
            for a in args:
                if matcher(a, classname):
                    matches.append(classname)
                    if logToConsole:
                        log(classname)
    return matches

def select_items(items, descriptions=None, allowMultiple=True):
    """
    Presents a command line interface for selecting one or more (if allowMultiple is true) items.

    """
    if len(items) <= 1:
        return items
    else:
        assert is_interactive()
        numlen = str(len(str(len(items))))
        if allowMultiple:
            log(('[{0:>' + numlen + '}] <all>').format(0))
        for i in range(0, len(items)):
            if descriptions is None:
                log(('[{0:>' + numlen + '}] {1}').format(i + 1, items[i]))
            else:
                assert len(items) == len(descriptions)
                wrapper = textwrap.TextWrapper(subsequent_indent='    ')
                log('\n'.join(wrapper.wrap(('[{0:>' + numlen + '}] {1} - {2}').format(i + 1, items[i], descriptions[i]))))
        while True:
            if allowMultiple:
                s = raw_input('Enter number(s) of selection (separate multiple choices with spaces): ').split()
            else:
                s = [raw_input('Enter number of selection: ')]
            try:
                s = [int(x) for x in s]
            except:
                log('Selection contains non-numeric characters: "' + ' '.join(s) + '"')
                continue

            if allowMultiple and 0 in s:
                return items

            indexes = []
            for n in s:
                if n not in range(1, len(items) + 1):
                    log('Invalid selection: ' + str(n))
                    continue
                else:
                    indexes.append(n - 1)
            if allowMultiple:
                return [items[i] for i in indexes]
            if len(indexes) == 1:
                return items[indexes[0]]
            return None

def exportlibs(args):
    """export libraries to an archive file"""

    parser = ArgumentParser(prog='exportlibs')
    parser.add_argument('-b', '--base', action='store', help='base name of archive (default: libs)', default='libs', metavar='<path>')
    parser.add_argument('-a', '--include-all', action='store_true', help="include all defined libaries")
    parser.add_argument('--arc', action='store', choices=['tgz', 'tbz2', 'tar', 'zip'], default='tgz', help='the type of the archive to create')
    parser.add_argument('--no-sha1', action='store_false', dest='sha1', help='do not create SHA1 signature of archive')
    parser.add_argument('--no-md5', action='store_false', dest='md5', help='do not create MD5 signature of archive')
    parser.add_argument('--include-system-libs', action='store_true', help='include system libraries (i.e., those not downloaded from URLs)')
    parser.add_argument('extras', nargs=REMAINDER, help='extra files and directories to add to archive', metavar='files...')
    args = parser.parse_args(args)

    def createArchive(addMethod):
        entries = {}
        def add(path, arcname):
            apath = os.path.abspath(path)
            if not entries.has_key(arcname):
                entries[arcname] = apath
                logv('[adding ' + path + ']')
                addMethod(path, arcname=arcname)
            elif entries[arcname] != apath:
                logv('[warning: ' + apath + ' collides with ' + entries[arcname] + ' as ' + arcname + ']')
            else:
                logv('[already added ' + path + ']')

        libsToExport = set()
        if args.include_all:
            for lib in _libs.itervalues():
                libsToExport.add(lib)
        else:
            def isValidLibrary(dep):
                if dep in _libs.iterkeys():
                    lib = _libs[dep]
                    if len(lib.urls) != 0 or args.include_system_libs:
                        return lib
                return None

            # iterate over all project dependencies and find used libraries
            for p in _projects.itervalues():
                for dep in p.deps:
                    r = isValidLibrary(dep)
                    if r:
                        libsToExport.add(r)

            # a library can have other libraries as dependency
            size = 0
            while size != len(libsToExport):
                size = len(libsToExport)
                for lib in libsToExport.copy():
                    for dep in lib.deps:
                        r = isValidLibrary(dep)
                        if r:
                            libsToExport.add(r)

        for lib in libsToExport:
            add(lib.get_path(resolve=True), lib.path)
            if lib.sha1:
                add(lib.get_path(resolve=True) + ".sha1", lib.path + ".sha1")
            if lib.sourcePath:
                add(lib.get_source_path(resolve=True), lib.sourcePath)
                if lib.sourceSha1:
                    add(lib.get_source_path(resolve=True) + ".sha1", lib.sourcePath + ".sha1")

        if args.extras:
            for e in args.extras:
                if os.path.isdir(e):
                    for root, _, filenames in os.walk(e):
                        for name in filenames:
                            f = join(root, name)
                            add(f, f)
                else:
                    add(e, e)

    if args.arc == 'zip':
        path = args.base + '.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            createArchive(zf.write)
    else:
        path = args.base + '.tar'
        mode = 'w'
        if args.arc != 'tar':
            sfx = args.arc[1:]
            mode = mode + ':' + sfx
            path = path + '.' + sfx
        with tarfile.open(path, mode) as tar:
            createArchive(tar.add)
    log('created ' + path)

    def digest(enabled, path, factory, suffix):
        if enabled:
            d = factory()
            with open(path, 'rb') as f:
                while True:
                    buf = f.read(4096)
                    if not buf:
                        break
                    d.update(buf)
            with open(path + '.' + suffix, 'w') as fp:
                print >> fp, d.hexdigest()
            log('created ' + path + '.' + suffix)

    digest(args.sha1, path, hashlib.sha1, 'sha1')
    digest(args.md5, path, hashlib.md5, 'md5')

def javap(args):
    """disassemble classes matching given pattern with javap"""

    javapExe = java().javap
    if not exists(javapExe):
        abort('The javap executable does not exists: ' + javapExe)
    else:
        candidates = findclass(args, logToConsole=False)
        if len(candidates) == 0:
            log('no matches')
        selection = select_items(candidates)
        run([javapExe, '-private', '-verbose', '-classpath', classpath()] + selection)

def show_projects(args):
    """show all projects"""
    for s in suites():
        if len(s.projects) != 0:
            log(join(s.mxDir, 'suite*.py'))
            for p in s.projects:
                log('\t' + p.name)

def show_suites(args):
    """show all suites"""
    def _show_section(name, section):
        if len(section) != 0:
            log('  ' + name + ':')
            for e in section:
                log('    ' + e.name)

    for s in suites():
        log(join(s.mxDir, 'suite*.py'))
        _show_section('libraries', s.libs)
        _show_section('jrelibraries', s.jreLibs)
        _show_section('projects', s.projects)
        _show_section('distributions', s.dists)

def _compile_mx_class(javaClassName, classpath=None, jdk=None, myDir=None):
    myDir = dirname(__file__) if myDir is None else myDir
    binDir = join(myDir, 'bin' if not jdk else '.jdk' + str(jdk.version))
    javaSource = join(myDir, javaClassName + '.java')
    javaClass = join(binDir, javaClassName + '.class')
    if not exists(javaClass) or getmtime(javaClass) < getmtime(javaSource):
        if not exists(binDir):
            os.mkdir(binDir)
        javac = jdk.javac if jdk else java().javac
        cmd = [javac, '-d', _cygpathU2W(binDir)]
        if classpath:
            cmd += ['-cp', _separatedCygpathU2W(binDir + os.pathsep + classpath)]
        cmd += [_cygpathU2W(javaSource)]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            abort('failed to compile:' + javaSource)


    return (myDir, binDir)

def checkcopyrights(args):
    '''run copyright check on the sources'''
    class CP(ArgumentParser):
        def format_help(self):
            return ArgumentParser.format_help(self) + self._get_program_help()

        def _get_program_help(self):
            help_output = subprocess.check_output([java().java, '-cp', _cygpathU2W(binDir), 'CheckCopyright', '--help'])
            return '\nother argumemnts preceded with --\n' +  help_output

    # ensure compiled form of code is up to date
    myDir, binDir = _compile_mx_class('CheckCopyright')

    parser = CP(prog='mx checkcopyrights')

    parser.add_argument('--primary', action='store_true', help='limit checks to primary suite')
    parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)
    remove_doubledash(args.remainder)


    result = 0
    # copyright checking is suite specific as each suite may have different overrides
    for s in suites(True):
        if args.primary and not s.primary:
            continue
        custom_copyrights = _cygpathU2W(join(s.mxDir, 'copyrights'))
        custom_args = []
        if exists(custom_copyrights):
            custom_args = ['--custom-copyright-dir', custom_copyrights]
        rc = run([java().java, '-cp', _cygpathU2W(binDir), 'CheckCopyright', '--copyright-dir', _cygpathU2W(myDir)] + custom_args + args.remainder, cwd=s.dir, nonZeroIsFatal=False)
        result = result if rc == 0 else rc
    return result

def _find_classes_with_annotations(p, pkgRoot, annotations, includeInnerClasses=False):
    """
    Scan the sources of project 'p' for Java source files containing a line starting with 'annotation'
    (ignoring preceding whitespace) and return the fully qualified class name for each Java
    source file matched in a list.
    """

    matches = lambda line: len([a for a in annotations if line == a or line.startswith(a + '(')]) != 0
    return p.find_classes_with_matching_source_line(pkgRoot, matches, includeInnerClasses)

def _basic_junit_harness(args, vmArgs, junitArgs):
    return run_java(junitArgs)

def junit(args, harness=_basic_junit_harness, parser=None):
    '''run Junit tests'''
    suppliedParser = parser is not None
    parser = parser if suppliedParser else ArgumentParser(prog='mx junit')
    parser.add_argument('--tests', action='store', help='pattern to match test classes')
    parser.add_argument('--J', dest='vm_args', help='target VM arguments (e.g. --J @-dsa)', metavar='@<args>')
    if suppliedParser:
        parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    vmArgs = ['-ea', '-esa']

    if args.vm_args:
        vmArgs = vmArgs + shlex.split(args.vm_args.lstrip('@'))

    testfile = os.environ.get('MX_TESTFILE', None)
    if testfile is None:
        (_, testfile) = tempfile.mkstemp(".testclasses", "mx")
        os.close(_)

    candidates = []
    for p in projects_opt_limit_to_suites():
        if p.native or java().javaCompliance < p.javaCompliance:
            continue
        candidates += _find_classes_with_annotations(p, None, ['@Test']).keys()

    tests = [] if args.tests is None else [name for name in args.tests.split(',')]
    classes = []
    if len(tests) == 0:
        classes = candidates
    else:
        for t in tests:
            found = False
            for c in candidates:
                if t in c:
                    found = True
                    classes.append(c)
            if not found:
                log('warning: no tests matched by substring "' + t)

    projectscp = classpath([pcp.name for pcp in projects_opt_limit_to_suites() if not pcp.native and pcp.javaCompliance <= java().javaCompliance])

    if len(classes) != 0:
        # Compiling wrt projectscp avoids a dependency on junit.jar in mxtool itself
        # However, perhaps because it's Friday 13th javac is not actually compiling
        # this file, yet not returning error. It is perhaps related to annotation processors
        # so the workaround is to extract the junit path as that is all we need.
        junitpath = [s for s in projectscp.split(":") if "junit" in s][0]

        _, binDir = _compile_mx_class('MX2JUnitWrapper', junitpath)

        if len(classes) == 1:
            testClassArgs = ['--testclass', classes[0]]
        else:
            with open(testfile, 'w') as f:
                for c in classes:
                    f.write(c + '\n')
            testClassArgs = ['--testsfile', testfile]
        junitArgs = ['-cp', _separatedCygpathU2W(binDir + os.pathsep + projectscp), 'MX2JUnitWrapper'] + testClassArgs
        rc = harness(args, vmArgs, junitArgs)
        return rc
    else:
        return 0

def remove_doubledash(args):
    if '--' in args:
        args.remove('--')

def ask_yes_no(question, default=None):
    """"""
    assert not default or default == 'y' or default == 'n'
    if not is_interactive():
        if default:
            return default
        else:
            abort("Can not answer '" + question + "?' if stdout is not a tty")
    questionMark = '? [yn]: '
    if default:
        questionMark = questionMark.replace(default, default.upper())
    answer = raw_input(question + questionMark) or default
    while not answer:
        answer = raw_input(question + questionMark)
    return answer.lower().startswith('y')

def add_argument(*args, **kwargs):
    """
    Define how a single command-line argument.
    """
    assert _argParser is not None
    _argParser.add_argument(*args, **kwargs)

def update_commands(suite, new_commands):
    for key, value in new_commands.iteritems():
        if _commands.has_key(key):
            warn("redefining command '" + key + "' in suite " + suite.name)
        _commands[key] = value

def command_function(name, fatalIfMissing=True):
    '''
    Return the function for the (possibly overridden) command named name.
    If no such command, abort if FatalIsMissing=True, else return None
    '''
    if _commands.has_key(name):
        return _commands[name][0]
    else:
        if fatalIfMissing:
            abort('command ' + name + ' does not exist')
        else:
            return None

def warn(msg):
    if _warn:
        print 'WARNING: ' + msg

# Table of commands in alphabetical order.
# Keys are command names, value are lists: [<function>, <usage msg>, <format args to doc string of function>...]
# If any of the format args are instances of Callable, then they are called with an 'env' are before being
# used in the call to str.format().
# Suite extensions should not update this table directly, but use update_commands
_commands = {
    'about': [about, ''],
    'bench': [bench, ''],
    'build': [build, '[options]'],
    'checkstyle': [checkstyle, ''],
    'canonicalizeprojects': [canonicalizeprojects, ''],
    'clean': [clean, ''],
    'checkcopyrights': [checkcopyrights, '[options]'],
    'createsuite': [createsuite, '[options]'],
    'eclipseinit': [eclipseinit, ''],
    'eclipseformat': [eclipseformat, ''],
    'exportlibs': [exportlibs, ''],
    'findclass': [findclass, ''],
    'fsckprojects': [fsckprojects, ''],
    'gate': [gate, '[options]'],
    'help': [help_, '[command]'],
    'ideclean': [ideclean, ''],
    'ideinit': [ideinit, ''],
    'intellijinit': [intellijinit, ''],
    'archive': [_archive, '[options]'],
    'projectgraph': [projectgraph, ''],
    'sclone': [sclone, '[options]'],
    'scheckimports': [scheckimports, '[options]'],
    'scloneimports': [scloneimports, '[options]'],
    'sforceimports': [sforceimports, ''],
    'sincoming': [sincoming, ''],
    'spull': [spull, '[options]'],
    'spush': [spush, '[options]'],
    'stip': [stip, ''],
    'supdate': [supdate, ''],
    'pylint': [pylint, ''],
    'javap': [javap, '<class name patterns>'],
    'javadoc': [javadoc, '[options]'],
    'junit': [junit, '[options]'],
    'site': [site, '[options]'],
    'netbeansinit': [netbeansinit, ''],
    'suites': [show_suites, ''],
    'projects': [show_projects, ''],
    'sha1': [sha1, ''],
    'test': [test, '[options]'],
}

_argParser = ArgParser()

def _suitename(mxDir):
    base = os.path.basename(mxDir)
    parts = base.split('.')
    # temporary workaround until mx.graal exists
    if len(parts) == 1:
        return 'graal'
    else:
        return parts[1]

def _is_suite_dir(d, mxDirName=None):
    """
    Checks if d contains a suite.
    If mxDirName is None, matches any suite name, otherwise checks for exactly that suite.
    """
    if os.path.isdir(d):
        for f in os.listdir(d):
            if (mxDirName == None and (f == 'mx' or fnmatch.fnmatch(f, 'mx.*'))) or f == mxDirName:
                mxDir = join(d, f)
                if exists(mxDir) and isdir(mxDir) and (exists(join(mxDir, 'suite.py'))):
                    return mxDir

def _check_primary_suite():
    if _primary_suite is None:
        abort('no primary suite found')
    else:
        return _primary_suite

Needs_primary_suite_exemptions = ['sclone', 'scloneimports', 'createsuite']

def _needs_primary_suite(command):
    return not command in Needs_primary_suite_exemptions

def _needs_primary_suite_cl():
    args = sys.argv[1:]
    if len(args) == 0:
        return False
    for s in args:
        if s in Needs_primary_suite_exemptions:
            return False
    return True

def _findPrimarySuiteMxDirFrom(d):
    """ search for a suite directory upwards from 'd' """
    while d:
        mxDir = _is_suite_dir(d)
        if mxDir is not None:
            return mxDir
        parent = dirname(d)
        if d == parent:
            return None
        d = parent

    return None

def _findPrimarySuiteMxDir():
    # check for explicit setting
    if _primary_suite_path is not None:
        mxDir = _is_suite_dir(_primary_suite_path)
        if mxDir is not None:
            return mxDir
        else:
            abort(_primary_suite_path + ' does not contain an mx suite')

    # try current working directory first
    mxDir = _findPrimarySuiteMxDirFrom(os.getcwd())
    if mxDir is not None:
        return mxDir
    # backwards compatibility: search from path of this file
    return _findPrimarySuiteMxDirFrom(dirname(__file__))

def _remove_bad_deps():
    '''Remove projects and libraries that (recursively) depend on an optional library
    whose artifact does not exist or on a JRE library that is not present in the
    JDK for a project. Also remove projects whose Java compliance requirement
    cannot be satisfied by the configured JDKs.
    Removed projects and libraries are also removed from
    distributions in they are listed as dependencies.'''
    ommittedDeps = set()
    for d in sorted_deps(includeLibs=True):
        if d.isLibrary():
            if d.optional:
                try:
                    d.optional = False
                    path = d.get_path(resolve=True)
                except SystemExit:
                    path = None
                finally:
                    d.optional = True
                if not path:
                    logv('[omitting optional library {0} as {1} does not exist]'.format(d, d.path))
                    ommittedDeps.add(d.name)
                    del _libs[d.name]
                    d.suite.libs.remove(d)
        elif d.isProject():
            if java(d.javaCompliance, cancel='some projects will be omitted which may result in errrors') is None:
                logv('[omitting project {0} as Java compliance {1} cannot be satisfied by configured JDKs]'.format(d, d.javaCompliance))
                ommittedDeps.add(d.name)
                del _projects[d.name]
                d.suite.projects.remove(d)
            else:
                for name in list(d.deps):
                    jreLib = _jreLibs.get(name)
                    if jreLib:
                        if not jreLib.is_present_in_jdk(java(d.javaCompliance)):
                            if jreLib.optional:
                                logv('[omitting project {0} as dependency {1} is missing]'.format(d, name))
                                ommittedDeps.add(d.name)
                                del _projects[d.name]
                                d.suite.projects.remove(d)
                            else:
                                abort('JRE library {0} required by {1} not found'.format(jreLib, d))
                    elif not dependency(name, fatalIfMissing=False):
                        logv('[omitting project {0} as dependency {1} is missing]'.format(d, name))
                        ommittedDeps.add(d.name)
                        del _projects[d.name]
                        d.suite.projects.remove(d)

    for dist in _dists.itervalues():
        for name in list(dist.deps):
            if name in ommittedDeps:
                logv('[omitting {0} from distribution {1}]'.format(name, dist))
                dist.deps.remove(name)

def main():
    SuiteModel.parse_options()
    os.environ['MX_HOME'] = _mx_home

    global _hg
    _hg = HgConfig()

    primary_suite_error = 'no primary suite found'
    primarySuiteMxDir = _findPrimarySuiteMxDir()
    if primarySuiteMxDir:
        _src_suitemodel.set_primary_dir(dirname(primarySuiteMxDir))
        global _primary_suite
        _primary_suite = Suite(primarySuiteMxDir, True)
    else:
        # in general this is an error, except for the Needs_primary_suite_exemptions commands,
        # and an extensions command will likely not parse in this case, as any extra arguments
        # will not have been added to _argParser.
        # If the command line does not contain a string matching one of the exemptions, we can safely abort,
        # but not otherwise, as we can't be sure the string isn't in a value for some other option.
        if _needs_primary_suite_cl():
            abort(primary_suite_error)


    opts, commandAndArgs = _argParser._parse_cmd_line()
    assert _opts == opts

    if primarySuiteMxDir is None:
        if len(commandAndArgs) > 0 and _needs_primary_suite(commandAndArgs[0]):
            abort(primary_suite_error)
        else:
            warn(primary_suite_error)
    else:
        os.environ['MX_PRIMARY_SUITE_PATH'] = dirname(primarySuiteMxDir)

    if primarySuiteMxDir:
        _primary_suite._depth_first_post_init()

    _remove_bad_deps()

    if len(commandAndArgs) == 0:
        _argParser.print_help()
        return

    command = commandAndArgs[0]
    command_args = commandAndArgs[1:]

    if not _commands.has_key(command):
        hits = [c for c in _commands.iterkeys() if c.startswith(command)]
        if len(hits) == 1:
            command = hits[0]
        elif len(hits) == 0:
            abort('mx: unknown command \'{0}\'\n{1}use "mx help" for more options'.format(command, _format_commands()))
        else:
            abort('mx: command \'{0}\' is ambiguous\n    {1}'.format(command, ' '.join(hits)))

    c, _ = _commands[command][:2]
    def term_handler(signum, frame):
        abort(1)
    if not is_jython():
        signal.signal(signal.SIGTERM, term_handler)

    def quit_handler(signum, frame):
        _send_sigquit()
    if not is_jython() and get_os() != 'windows':
        signal.signal(signal.SIGQUIT, quit_handler)

    try:
        if opts.timeout != 0:
            def alarm_handler(signum, frame):
                abort('Command timed out after ' + str(opts.timeout) + ' seconds: ' + ' '.join(commandAndArgs))
            signal.signal(signal.SIGALRM, alarm_handler)
            signal.alarm(opts.timeout)
        retcode = c(command_args)
        if retcode is not None and retcode != 0:
            abort(retcode)
    except KeyboardInterrupt:
        # no need to show the stack trace when the user presses CTRL-C
        abort(1)

version = VersionSpec("3.3.0")

currentUmask = None

if __name__ == '__main__':
    # rename this module as 'mx' so it is not imported twice by the commands.py modules
    sys.modules['mx'] = sys.modules.pop('__main__')

    # Capture the current umask since there's no way to query it without mutating it.
    currentUmask = os.umask(0)
    os.umask(currentUmask)

    main()
