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

Full documentation can be found in the Wiki at https://bitbucket.org/allr/mxtool2/wiki/Home
"""
import sys
from abc import ABCMeta

if __name__ == '__main__':
    # Rename this module as 'mx' so it is not re-executed when imported by other modules.
    sys.modules['mx'] = sys.modules.pop('__main__')

try:
    import defusedxml #pylint: disable=unused-import
    from defusedxml.ElementTree import parse as etreeParse
except ImportError:
    from xml.etree.ElementTree import parse as etreeParse

import os, errno, time, subprocess, shlex, types, StringIO, zipfile, signal, tempfile, platform
import textwrap
import socket
import tarfile, gzip
import hashlib
import itertools
# TODO use defusedexpat?
import xml.parsers.expat, xml.sax.saxutils, xml.dom.minidom
import shutil, re
import pipes
import difflib
import glob
import urllib2, urlparse
from collections import Callable
from collections import OrderedDict, namedtuple
from threading import Thread
from argparse import ArgumentParser, REMAINDER, Namespace
from os.path import join, basename, dirname, exists, getmtime, isabs, expandvars, isdir

import mx_unittest
import mx_findbugs
import mx_sigtest
import mx_gate
import mx_compat

_mx_home = os.path.realpath(dirname(__file__))

try:
    # needed to work around https://bugs.python.org/issue1927
    import readline #pylint: disable=unused-import
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
_jdkLibs = dict()
_dists = dict()
_distTemplates = dict()
_licenses = dict()
_repositories = dict()

"""
Map from the name of a removed dependency to the reason it was removed.
A reason may be the name of another removed dependency, forming a causality chain.
"""
_removedDeps = {}

_suites = dict()
_loadedSuites = []

_jdkFactories = {}

_annotationProcessors = None
_mx_suite = None
_mx_tests_suite = None
_primary_suite_path = None
_primary_suite = None
_src_suitemodel = None
_dst_suitemodel = None
_opts = Namespace()
_extra_java_homes = []
_default_java_home = None
_check_global_structures = True  # can be set False to allow suites with duplicate definitions to load without aborting
_vc_systems = []
_mvn = None
_binary_suites = None # source suites only if None, [] means all binary, otherwise specific list
_suites_ignore_versions = None # as per _binary_suites, ignore versions on clone

# List of functions to run when the primary suite is initialized
_primary_suite_deferrables = []

def nyi(name, obj):
    abort('{} is not implemented for {}'.format(name, obj.__class__.__name__))

"""
Names of commands that do not need suites loaded.
"""
_suite_context_free = ['scloneimports']

"""
Decorator for commands that do not need suites loaded.
"""
def suite_context_free(func):
    _suite_context_free.append(func.__name__)
    return func

"""
Names of commands that do not need a primary suite to be available.
"""
_primary_suite_exempt = []

"""
Decorator for commands that do not need a primary suite to be available.
"""
def primary_suite_exempt(func):
    _primary_suite_exempt.append(func.__name__)
    return func

DEP_STANDARD = "standard dependency"
DEP_ANNOTATION_PROCESSOR = "annotation processor dependency"
DEP_EXCLUDED = "excluded library"

def _is_edge_ignored(edge, ignoredEdges):
    return ignoredEdges and edge in ignoredEdges

DEBUG_WALK_DEPS = False
DEBUG_WALK_DEPS_LINE = 1
def _debug_walk_deps_helper(dep, edge, ignoredEdges):
    assert edge not in ignoredEdges
    global DEBUG_WALK_DEPS_LINE
    if DEBUG_WALK_DEPS:
        if edge:
            print '{}:walk_deps:{}{}    # {}'.format(DEBUG_WALK_DEPS_LINE, '  ' * edge.path_len(), dep, edge.kind)
        else:
            print '{}:walk_deps:{}'.format(DEBUG_WALK_DEPS_LINE, dep)
        DEBUG_WALK_DEPS_LINE += 1

'''
Represents an edge traversed while visiting a spanning tree of the dependency graph.
'''
class DepEdge:
    def __init__(self, src, kind, prev):
        '''
        src - the source of this dependency edge
        kind - one of the constants DEP_STANDARD, DEP_ANNOTATION_PROCESSOR, DEP_EXCLUDED describing the type
               of graph edge from 'src' to the dependency targeted by this edge
        prev - the dependency edge traversed to reach 'src' or None if 'src' is a root of a dependency
               graph traversal
        '''
        self.src = src
        self.kind = kind
        self.prev = prev

    def __str__(self):
        return '{}@{}'.format(self.src, self.kind)

    def path(self):
        if self.prev:
            return self.prev.path() + [self.src]
        return [self.src]

    def path_len(self):
        return 1 + self.prev.path_len() if self.prev else 0


class SuiteConstituent(object):
    def __init__(self, suite, name):
        self.name = name
        self.suite = suite

        # Should this constituent be visible outside its suite
        self.internal = False

    def origin(self):
        """
        Gets a 2-tuple (file, line) describing the source file where this constituent
        is defined or None if the location cannot be determined.
        """
        suitepy = self.suite.suite_py()
        if exists(suitepy):
            import tokenize
            with open(suitepy) as fp:
                candidate = None
                for t in tokenize.generate_tokens(fp.readline):
                    _, tval, (srow, _), _, _ = t
                    if candidate is None:
                        if tval == '"' + self.name + '"' or tval == "'" + self.name + "'":
                            candidate = srow
                    else:
                        if tval == ':':
                            return (suitepy, srow)
                        else:
                            candidate = None

    def __abort_context__(self):
        '''
        Gets a description of where this constituent was defined in terms of source file
        and line number. If no such description can be generated, None is returned.
        '''
        loc = self.origin()
        if loc:
            path, lineNo = loc
            return '  File "{}", line {} in definition of {}'.format(path, lineNo, self.name)
        return None


class License(SuiteConstituent):
    def __init__(self, suite, name, fullname, url):
        SuiteConstituent.__init__(self, suite, name)
        self.fullname = fullname
        self.url = url

    def __eq__(self, other):
        if not isinstance(other, License):
            return False
        return self.name == other.name and self.url == other.url and self.fullname == other.fullname

    def __ne__(self, other):
        return not self.__eq__(other)


"""
A dependency is a library, distribution or project specified in a suite.
The name must be unique across all Dependency instances.
"""
class Dependency(SuiteConstituent):
    def __init__(self, suite, name, theLicense):
        SuiteConstituent.__init__(self, suite, name)
        self.theLicense = theLicense

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

    def isBaseLibrary(self):
        return isinstance(self, BaseLibrary)

    def isLibrary(self):
        return isinstance(self, Library)

    def isJreLibrary(self):
        return isinstance(self, JreLibrary)

    def isJdkLibrary(self):
        return isinstance(self, JdkLibrary)

    def isProject(self):
        return isinstance(self, Project)

    def isJavaProject(self):
        return isinstance(self, JavaProject)

    def isNativeProject(self):
        return isinstance(self, NativeProject)

    def isDistribution(self):
        return isinstance(self, Distribution)

    def isJARDistribution(self):
        return isinstance(self, JARDistribution)

    def isTARDistribution(self):
        return isinstance(self, NativeTARDistribution)

    def isProjectOrLibrary(self):
        return self.isProject() or self.isLibrary()

    def getGlobalRegistry(self):
        if self.isProject():
            return _projects
        if self.isLibrary():
            return _libs
        if self.isDistribution():
            return _dists
        if self.isJreLibrary():
            return _jreLibs
        assert self.isJdkLibrary()
        return _jdkLibs

    def getSuiteRegistry(self):
        if self.isProject():
            return self.suite.projects
        if self.isLibrary():
            return self.suite.libs
        if self.isDistribution():
            return self.suite.dists
        if self.isJreLibrary():
            return self.suite.jreLibs
        assert self.isJdkLibrary()
        return self.suite.jdkLibs

    """
    Return a BuildTask that can be used to build this dependency.
    """
    def getBuildTask(self, args):
        nyi('getBuildTask', self)

    def abort(self, msg):
        '''
        Aborts with given message prefixed by the origin of this dependency.
        '''
        abort(msg, context=self)

    def warn(self, msg):
        '''
        Warns with given message prefixed by the origin of this dependency.
        '''
        warn(msg, context=self)

    def qualifiedName(self):
        return '{}:{}'.format(self.suite.name, self.name)

    def walk_deps(self, preVisit=None, visit=None, visited=None, ignoredEdges=None, visitEdge=None):
        '''
        Walk the dependency graph rooted at this object.
        See documentation for mx.walk_deps for more info.
        '''
        if visited is not None:
            if self in visited:
                return
        else:
            visited = set()
        if not ignoredEdges:
            # Default ignored edges
            ignoredEdges = [DEP_ANNOTATION_PROCESSOR, DEP_EXCLUDED]
        self._walk_deps_helper(visited, None, preVisit, visit, ignoredEdges, visitEdge)

    def _walk_deps_helper(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        _debug_walk_deps_helper(self, edge, ignoredEdges)
        assert self not in visited, self
        visited.add(self)
        if not preVisit or preVisit(self, edge):
            self._walk_deps_visit_edges(visited, edge, preVisit, visit, ignoredEdges, visitEdge)
            if visit:
                visit(self, edge)

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        nyi('_walk_deps_visit_edges', self)

    def contains_dep(self, dep, includeAnnotationProcessors=False):
        '''
        Determines if the dependency graph rooted at this object contains 'dep'.
        Returns the path from this object to 'dep' if so, otherwise returns None.
        '''
        if dep == self:
            return [self]
        class FoundPath(StopIteration):
            def __init__(self, path):
                StopIteration.__init__(self)
                self.path = path
        def visit(path, d, edge):
            if dep is d:
                raise FoundPath(path)
        try:
            ignoredEdges = [DEP_EXCLUDED] if includeAnnotationProcessors else None
            self.walk_deps(visit=visit, ignoredEdges=ignoredEdges)
        except FoundPath as e:
            return e.path
        return None

    '''Only JavaProjects define Java packages'''
    def defined_java_packages(self):
        return []

    def _resolveDepsHelper(self, deps, fatalIfMissing=True):
        '''
        Resolves any string entries in 'deps' to the Dependency objects named
        by the strings. The 'deps' list is updated in place.
        '''
        if deps:
            if isinstance(deps[0], str):
                resolvedDeps = []
                for name in deps:
                    s, _ = splitqualname(name)
                    dep = dependency(name, context=self, fatalIfMissing=fatalIfMissing)
                    if not dep:
                        continue
                    if dep.isProject() and self.suite is not dep.suite:
                        abort('cannot have an inter-suite reference to a project: ' + dep.name, context=self)
                    if s is None and self.suite is not dep.suite:
                        abort('inter-suite reference must use qualified form ' + dep.suite.name + ':' + dep.name, context=self)
                    if self.suite is not dep.suite and dep.internal:
                        abort('cannot reference internal ' + dep.name + ' from ' + self.suite.name + ' suite', context=self)
                    resolvedDeps.append(dep)
                deps[:] = resolvedDeps
            else:
                # If the first element has been resolved, then all elements should have been resolved
                assert len([d for d in deps if not isinstance(d, str)])

class ClasspathDependency(Dependency):
    def __init__(self): # pylint: disable=super-init-not-called
        pass

    def classpath_repr(self, resolve=True):
        '''
        Gets this dependency as an element on a class path.

        If 'resolve' is True, then this method aborts if the file or directory
        denoted by the class path element does not exist.
        '''
        nyi('classpath_repr', self)

    def isJar(self):
        cp_repr = self.classpath_repr()
        if cp_repr:
            return cp_repr.endswith('.jar') or cp_repr.endswith('.JAR') or '.jar_' in cp_repr
        return True

"""
A build task is used to build a dependency.

Attributes:
    parallelism: how many CPUs are used when running this task
    deps: array of tasks this task depends on
    built: True if a build was performed
"""
class BuildTask(object):
    def __init__(self, subject, args, parallelism):
        self.parallelism = parallelism
        self.subject = subject
        self.deps = []
        self.built = False
        self.args = args
        self.proc = None

    def __str__(self):
        nyi('__str__', self)

    def __repr__(self):
        return str(self)

    def initSharedMemoryState(self):
        self._builtBox = multiprocessing.Value('b', 1 if self.built else 0)

    def pushSharedMemoryState(self):
        self._builtBox.value = 1 if self.built else 0

    def pullSharedMemoryState(self):
        self.built = bool(self._builtBox.value)

    def cleanSharedMemoryState(self):
        self._builtBox = None

    def _persistDeps(self):
        '''
        Saves the dependencies for this task's subject to a file. This can be used to
        determine whether the ordered set of dependencies for this task have changed
        since the last time it was built.
        Returns True if file already existed and did not reflect the current dependencies.
        '''
        savedDepsFile = join(self.subject.suite.get_mx_output_dir(), 'savedDeps', self.subject.name)
        currentDeps = [d.subject.name for d in self.deps]
        outOfDate = False
        if exists(savedDepsFile):
            with open(savedDepsFile) as fp:
                savedDeps = [l.strip() for l in fp.readlines()]
            if savedDeps != [d.subject.name for d in self.deps]:
                outOfDate = True

        if len(currentDeps) == 0:
            if exists(savedDepsFile):
                os.remove(savedDepsFile)
        else:
            ensure_dir_exists(dirname(savedDepsFile))
            with open(savedDepsFile, 'w') as fp:
                for dname in currentDeps:
                    print >> fp, dname

        return outOfDate

    """
    Execute the build task.
    """
    def execute(self):
        if self.buildForbidden():
            self.logSkip(None)
            return
        buildNeeded = False
        if self.args.clean and not self.cleanForbidden():
            self.logClean()
            self.clean()
            buildNeeded = True
            reason = 'clean'
        if not buildNeeded:
            updated = [dep for dep in self.deps if dep.built]
            if any(updated):
                buildNeeded = True
                if not _opts.verbose:
                    reason = 'dependency {} updated'.format(updated[0].subject)
                else:
                    reason = 'dependencies updated: ' + ', '.join([u.subject.name for u in updated])
        changed = self._persistDeps()
        if not buildNeeded and changed:
            buildNeeded = True
            reason = 'dependencies were added, removed or re-ordered'
        if not buildNeeded:
            newestInput = None
            newestInputDep = None
            for dep in self.deps:
                depNewestOutput = dep.newestOutput()
                if depNewestOutput and (not newestInput or depNewestOutput.isNewerThan(newestInput)):
                    newestInput = depNewestOutput
                    newestInputDep = dep
            if newestInputDep:
                logvv('Newest dependency for {}: {} ({})'.format(self.subject.name, newestInputDep.subject.name, newestInput))

            if get_env('MX_BUILD_SHALLOW_DEPENDENCY_CHECKS') is None:
                shallow_dependency_checks = self.args.shallow_dependency_checks is True
            else:
                shallow_dependency_checks = get_env('MX_BUILD_SHALLOW_DEPENDENCY_CHECKS') == 'true'
                if self.args.shallow_dependency_checks is not None and shallow_dependency_checks is True:
                    warn('Explicit -s argument to build command is overridden by MX_BUILD_SHALLOW_DEPENDENCY_CHECKS')

            if newestInput and shallow_dependency_checks and not self.subject.isNativeProject():
                newestInput = None
            if __name__ != self.__module__ and self.subject.suite.getMxCompatibility().newestInputIsTimeStampFile():
                newestInput = newestInput.timestamp if newestInput else float(0)
            buildNeeded, reason = self.needsBuild(newestInput)
        if buildNeeded:
            if not self.args.clean and not self.cleanForbidden():
                self.clean(forBuild=True)
            self.logBuild(reason)
            self.build()
            self.built = True
            logv('Finished {}'.format(self))
        else:
            self.logSkip(reason)

    def logBuild(self, reason):
        if reason:
            log('{}... [{}]'.format(self, reason))
        else:
            log('{}...'.format(self))

    def logClean(self):
        log('Cleaning {}...'.format(self.subject.name))

    def logSkip(self, reason):
        if reason:
            logv('[{} - skipping {}]'.format(reason, self.subject.name))
        else:
            logv('[skipping {}]'.format(self.subject.name))

    def needsBuild(self, newestInput):
        """
        Returns True if the current artifacts of this task are out dated.
        The 'newestInput' argument is either None or a TimeStampFile
        denoting the artifact of a dependency with the most recent modification time.
        Apart from 'newestInput', this method does not inspect this task's dependencies.
        """
        if self.args.force:
            return (True, 'forced build')
        return (False, 'unimplemented')

    def newestOutput(self):
        """
        Gets a TimeStampFile representing the build output file for this task
        with the newest modification time or None if no build output file exists.
        """
        nyi('newestOutput', self)

    def buildForbidden(self):
        if not self.args.only:
            return False
        projectNames = self.args.only.split(',')
        return self.subject.name not in projectNames

    def cleanForbidden(self):
        return False

    """
    Build the artifacts.
    """
    def build(self):
        nyi('build', self)

    """
    Clean the build artifacts.
    """
    def clean(self, forBuild=False):
        nyi('clean', self)

def _needsUpdate(newestInput, path):
    """
    Determines if the file denoted by 'path' does not exist or 'newestInput' is not None
    and 'path's latest modification time is older than the 'newestInput' TimeStampFile.
    Returns a string describing why 'path' needs updating or None if it does not need updating.
    """
    if not exists(path):
        return path + ' does not exist'
    if newestInput:
        ts = TimeStampFile(path, followSymlinks=False)
        if ts.isOlderThan(newestInput):
            return '{} is older than {}'.format(ts, newestInput)
    return None

class DistributionTemplate(SuiteConstituent):
    def __init__(self, suite, name, attrs, parameters):
        SuiteConstituent.__init__(self, suite, name)
        self.attrs = attrs
        self.parameters = parameters

"""
A distribution is a file containing the output from one or more projects.
In some sense it is the ultimate "result" of a build (there can be more than one).
It is a Dependency because a Project or another Distribution may express a dependency on it.

Attributes:
    name: unique name
    deps: "dependencies" that define the components that will comprise the distribution.
        See Distribution.archived_deps for a precise description.
        This is a slightly misleading name, it is more akin to the "srcdirs" attribute of a Project,
        as it defines the eventual content of the distribution
    excludedLibs: Libraries whose jar contents should be excluded from this distribution's jar
"""
class Distribution(Dependency):
    def __init__(self, suite, name, deps, excludedLibs, platformDependent, theLicense):
        Dependency.__init__(self, suite, name, theLicense)
        self.deps = deps
        self.update_listeners = set()
        self.excludedLibs = excludedLibs
        self.platformDependent = platformDependent

    def add_update_listener(self, listener):
        self.update_listeners.add(listener)

    def notify_updated(self):
        for l in self.update_listeners:
            l(self)

    def resolveDeps(self):
        self._resolveDepsHelper(self.deps, fatalIfMissing=not isinstance(self.suite, BinarySuite))
        self._resolveDepsHelper(self.excludedLibs)
        for l in self.excludedLibs:
            if not l.isBaseLibrary():
                abort('"exclude" attribute can only contain libraries: ' + l.name, context=self)
        licenseId = self.theLicense if self.theLicense else self.suite.defaultLicense
        if licenseId:
            self.theLicense = get_license(licenseId, context=self)

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        if not _is_edge_ignored(DEP_STANDARD, ignoredEdges):
            for d in self.deps:
                if visitEdge:
                    visitEdge(self, DEP_STANDARD, d)
                if d not in visited:
                    d._walk_deps_helper(visited, DepEdge(self, DEP_STANDARD, edge), preVisit, visit, ignoredEdges, visitEdge)
        if not _is_edge_ignored(DEP_EXCLUDED, ignoredEdges):
            for d in self.excludedLibs:
                if visitEdge:
                    visitEdge(self, DEP_EXCLUDED, d)
                if d not in visited:
                    d._walk_deps_helper(visited, DepEdge(self, DEP_EXCLUDED, edge), preVisit, visit, ignoredEdges, visitEdge)

    def make_archive(self):
        nyi('make_archive', self)

    def archived_deps(self):
        '''
        Gets the projects and libraries whose artifacts are the contents of the archive
        created by self.make_archive().

        Direct distribution dependencies are considered as "distDependencies".
        Anything contained in the distDependencies will not be included in the archived_deps.
        libraries listed in "excludedLibs" will also not be included.
        Otherwise, archived_deps will contain everything this distribution depends on (including
        indirect distribution dependencies and libraries).
        '''
        if not hasattr(self, '_archived_deps'):
            excluded = set(self.excludedLibs)
            def _visitDists(dep, edges):
                if dep is not self:
                    excluded.add(dep)
                    excluded.update(dep.archived_deps())
            self.walk_deps(visit=_visitDists, preVisit=lambda dst, edge: dst.isDistribution())
            deps = []
            def _visit(dep, edges):
                if dep is not self:
                    deps.append(dep)
            def _preVisit(dst, edge):
                return dst not in excluded and not dst.isJreLibrary()
            self.walk_deps(visit=_visit, preVisit=_preVisit)
            self._archived_deps = deps
        return self._archived_deps

    def exists(self):
        nyi('exists', self)

    def remoteExtension(self):
        nyi('remoteExtension', self)

    def localExtension(self):
        nyi('localExtension', self)

    def remoteName(self):
        if self.platformDependent:
            return '{name}_{os}_{arch}'.format(name=self.name, os=get_os(), arch=get_arch())
        return self.name

    def postPull(self, f):
        pass

    def prePush(self, f):
        return f

    def needsUpdate(self, newestInput):
        '''
        Determines if this distribution needs updating taking into account the
        'newestInput' TimeStampFile if 'newestInput' is not None. Returns the
        reason this distribution needs updating or None if it doesn't need updating.
        '''
        nyi('needsUpdate', self)

    def maven_artifact_id(self):
        return _map_to_maven_dist_name(self.remoteName())

    def maven_group_id(self):
        return _mavenGroupId(self.suite)

"""
A JARDistribution is a distribution for JavaProjects and Java libraries.
A Distribution always generates a jar/zip file for the built components
and may optionally specify a zip for the sources from which the built components were generated.

Attributes:
    path: suite-local path to where the jar file will be placed
    sourcesPath: as path but for source files (optional)
"""
class JARDistribution(Distribution, ClasspathDependency):
    def __init__(self, suite, name, subDir, path, sourcesPath, deps, mainClass, excludedLibs, distDependencies, javaCompliance, platformDependent, theLicense, javadocType="implementation", allowsJavadocWarnings=False, maven=True):
        Distribution.__init__(self, suite, name, deps + distDependencies, excludedLibs, platformDependent, theLicense)
        ClasspathDependency.__init__(self)
        self.subDir = subDir
        self.path = _make_absolute(path.replace('/', os.sep), suite.dir)
        self.sourcesPath = _make_absolute(sourcesPath.replace('/', os.sep), suite.dir) if sourcesPath else None
        self.archiveparticipant = None
        self.mainClass = mainClass
        self.javaCompliance = JavaCompliance(javaCompliance) if javaCompliance else None
        self.definedAnnotationProcessors = []
        self.javadocType = javadocType
        self.allowsJavadocWarnings = allowsJavadocWarnings
        self.maven = maven
        assert path.endswith(self.localExtension())

    def maven_artifact_id(self):
        if isinstance(self.maven, types.DictType):
            artifact_id = self.maven.get('artifactId', None)
            if artifact_id:
                return artifact_id
        return super(JARDistribution, self).maven_artifact_id()

    def maven_group_id(self):
        if isinstance(self.maven, types.DictType):
            group_id = self.maven.get('groupId', None)
            if group_id:
                return group_id
        return super(JARDistribution, self).maven_group_id()

    def set_archiveparticipant(self, archiveparticipant):
        """
        Adds an object that participates in the make_archive method of this distribution by defining the following methods:

        __opened__(arc, srcArc, services)
            Called when archiving starts. The 'arc' and 'srcArc' Archiver objects are for writing to the
            binary and source jars for the distribution. The 'services' dict is for collating the files
            that will be written to META-INF/services in the binary jar. It's a map from service names
            to a list of providers for the named service.
        __add__(arcname, contents)
            Submits an entry for addition to the binary archive (via the 'zf' ZipFile field of the 'arc' object).
            Returns True if this object writes to the archive or wants to exclude the entry from the archive,
            False if the caller should add the entry.
        __addsrc__(arcname, contents)
            Same as __add__ except if targets the source archive.
        __closing__()
            Called just before the 'services' are written to the binary archive and both archives are
            written to their underlying files.
        """
        self.archiveparticipant = archiveparticipant

    def origin(self):
        return Dependency.origin(self)

    def classpath_repr(self, resolve=True):
        if resolve and not exists(self.path):
            abort('unbuilt distribution {} can not be on a class path'.format(self))
        return self.path

    """
    Gets the directory in which the IDE project configuration for this distribution is generated.
    """
    def get_ide_project_dir(self):
        if self.subDir:
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

                if self.archiveparticipant:
                    self.archiveparticipant.__opened__(arc, srcArc, services)

                def overwriteCheck(zf, arcname, source):
                    if os.path.basename(arcname).startswith('.'):
                        logv('Excluding dotfile: ' + source)
                        return True
                    if not hasattr(zf, '_provenance'):
                        zf._provenance = {}
                    existingSource = zf._provenance.get(arcname, None)
                    isOverwrite = False
                    if existingSource and existingSource != source:
                        if arcname[-1] != os.path.sep:
                            warn(self.path + ': avoid overwrite of ' + arcname + '\n  new: ' + source + '\n  old: ' + existingSource)
                        isOverwrite = True
                    zf._provenance[arcname] = source
                    return isOverwrite

                if self.mainClass:
                    manifest = "Manifest-Version: 1.0\nMain-Class: %s\n\n" % (self.mainClass)
                    if not overwriteCheck(arc.zf, "META-INF/MANIFEST.MF", "project files"):
                        arc.zf.writestr("META-INF/MANIFEST.MF", manifest)

                for dep in self.archived_deps():
                    if self.theLicense is not None and dep.theLicense != self.theLicense:
                        if dep.suite.getMxCompatibility().supportsLicenses() and self.suite.getMxCompatibility().supportsLicenses():
                            report = abort
                        else:
                            report = warn
                        depLicense = dep.theLicense.name if dep.theLicense else '??'
                        selfLicense = self.theLicense.name if self.theLicense else '??'
                        report('Incompatible licenses: distribution {} ({}) can not contain {} ({})'.format(self.name, selfLicense, dep.name, depLicense))
                    if dep.isLibrary() or dep.isJARDistribution():
                        if dep.isLibrary():
                            l = dep
                            # merge library jar into distribution jar
                            logv('[' + self.path + ': adding library ' + l.name + ']')
                            jarPath = l.get_path(resolve=True)
                            jarSourcePath = l.get_source_path(resolve=True)
                        elif dep.isJARDistribution():
                            logv('[' + self.path + ': adding distribution ' + dep.name + ']')
                            jarPath = dep.path
                            jarSourcePath = dep.sourcesPath
                        else:
                            abort('Dependency not supported: {} ({})'.format(dep.name, dep.__class__.__name__))
                        if jarPath:
                            if dep.isJARDistribution() or not dep.optional or exists(jarPath):
                                with zipfile.ZipFile(jarPath, 'r') as lp:
                                    entries = lp.namelist()
                                    for arcname in entries:
                                        if arcname.startswith('META-INF/services/') and not arcname == 'META-INF/services/':
                                            service = arcname[len('META-INF/services/'):]
                                            assert '/' not in service
                                            services.setdefault(service, []).extend(lp.read(arcname).splitlines())
                                        else:
                                            if not overwriteCheck(arc.zf, arcname, jarPath + '!' + arcname):
                                                contents = lp.read(arcname)
                                                if not self.archiveparticipant or not self.archiveparticipant.__add__(arcname, contents):
                                                    arc.zf.writestr(arcname, contents)
                        if srcArc.zf and jarSourcePath:
                            with zipfile.ZipFile(jarSourcePath, 'r') as lp:
                                for arcname in lp.namelist():
                                    if not overwriteCheck(srcArc.zf, arcname, jarPath + '!' + arcname):
                                        contents = lp.read(arcname)
                                        if not self.archiveparticipant or not self.archiveparticipant.__addsrc__(arcname, contents):
                                            srcArc.zf.writestr(arcname, contents)
                    elif dep.isProject():
                        p = dep

                        if self.javaCompliance:
                            if p.javaCompliance > self.javaCompliance:
                                abort("Compliance level doesn't match: Distribution {0} requires {1}, but {2} is {3}.".format(self.name, self.javaCompliance, p.name, p.javaCompliance), context=self)

                        logv('[' + self.path + ': adding project ' + p.name + ']')
                        outputDir = p.output_dir()
                        for root, _, files in os.walk(outputDir):
                            relpath = root[len(outputDir) + 1:]
                            if relpath == join('META-INF', 'services'):
                                for service in files:
                                    with open(join(root, service), 'r') as fp:
                                        services.setdefault(service, []).extend([provider.strip() for provider in fp.readlines()])
                            else:
                                for f in files:
                                    arcname = join(relpath, f).replace(os.sep, '/')
                                    with open(join(root, f), 'rb') as fp:
                                        contents = fp.read()
                                    if not self.archiveparticipant or not self.archiveparticipant.__add__(arcname, contents):
                                        arc.zf.writestr(arcname, contents)
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
                                                with open(join(root, f), 'r') as fp:
                                                    contents = fp.read()
                                                if not self.archiveparticipant or not self.archiveparticipant.__addsrc__(arcname, contents):
                                                    srcArc.zf.writestr(arcname, contents)
                    else:
                        abort('Dependency not supported: {} ({})'.format(dep.name, dep.__class__.__name__))

                if self.archiveparticipant:
                    self.archiveparticipant.__closing__()

                for service, providers in services.iteritems():
                    arcname = 'META-INF/services/' + service
                    # Convert providers to a set before printing to remove duplicates
                    arc.zf.writestr(arcname, '\n'.join(frozenset(providers)) + '\n')

        self.notify_updated()

    def getBuildTask(self, args):
        return JARArchiveTask(args, self)

    def exists(self):
        return exists(self.path) and not self.sourcesPath or exists(self.sourcesPath)

    def remoteExtension(self):
        return 'jar'

    def localExtension(self):
        return 'jar'

    def needsUpdate(self, newestInput):
        res = _needsUpdate(newestInput, self.path)
        if res:
            return res
        if self.sourcesPath:
            return _needsUpdate(newestInput, self.sourcesPath)
        return None

class ArchiveTask(BuildTask):
    def __init__(self, args, dist):
        BuildTask.__init__(self, dist, args, 1)

    def needsBuild(self, newestInput):
        sup = BuildTask.needsBuild(self, newestInput)
        if sup[0]:
            return sup
        reason = self.subject.needsUpdate(newestInput)
        if reason:
            return (True, reason)
        return (False, None)

    def build(self):
        self.subject.make_archive()

    def __str__(self):
        return "Archiving {}".format(self.subject.name)

    def buildForbidden(self):
        return isinstance(self.subject.suite, BinarySuite)

    def cleanForbidden(self):
        if BuildTask.cleanForbidden(self):
            return True
        return isinstance(self.subject.suite, BinarySuite)

class JARArchiveTask(ArchiveTask):
    def buildForbidden(self):
        if ArchiveTask.buildForbidden(self):
            return True
        if not self.args.java:
            return True

    def newestOutput(self):
        return TimeStampFile.newest([self.subject.path, self.subject.sourcesPath])

    def clean(self, forBuild=False):
        if isinstance(self.subject.suite, BinarySuite):  # make sure we never clean distributions from BinarySuites
            abort('should not reach here')
        if exists(self.subject.path):
            os.remove(self.subject.path)
        if self.subject.sourcesPath and exists(self.subject.sourcesPath):
            os.remove(self.subject.sourcesPath)

    def cleanForbidden(self):
        if ArchiveTask.cleanForbidden(self):
            return True
        if not self.args.java:
            return True
        return False

"""
A NativeTARDistribution is a distribution for NativeProjects.
It packages all the 'results' of a NativeProject.

Attributes:
    path: suite-local path to where the tar file will be placed
"""
class NativeTARDistribution(Distribution):
    def __init__(self, suite, name, deps, path, excludedLibs, platformDependent, theLicense):
        Distribution.__init__(self, suite, name, deps, excludedLibs, platformDependent, theLicense)
        self.path = _make_absolute(path, suite.dir)

    def make_archive(self):
        directory = dirname(self.path)
        ensure_dir_exists(directory)
        with Archiver(self.path, kind='tar') as arc:
            files = set()
            for d in self.archived_deps():
                if not d.isNativeProject():
                    abort('Unsupported dependency for native distribution {}: {}'.format(self.name, d.name))
                for r in d.getResults():
                    filename = basename(r)
                    assert filename not in files, filename
                    # Make debug-info files optional for distribution
                    if is_debug_lib_file(r) and not os.path.exists(r):
                        warn("File {} for archive {} does not exist.".format(filename, d.name))
                    else:
                        files.add(filename)
                        arc.zf.add(r, arcname=filename)
        self.notify_updated()

    def getBuildTask(self, args):
        return TARArchiveTask(args, self)

    def exists(self):
        return exists(self.path)

    def remoteExtension(self):
        return 'tar.gz'

    def localExtension(self):
        return 'tar'

    def postPull(self, f):
        assert f.endswith('.gz')
        logv('Uncompressing {}...'.format(f))
        with gzip.open(f, 'rb') as gz, open(f[:-len('.gz')], 'wb') as tar:
            shutil.copyfileobj(gz, tar)
        os.remove(f)

    def prePush(self, f):
        tgz = f + '.gz'
        logv('Compressing {}...'.format(f))
        with gzip.open(tgz, 'wb') as gz, open(f, 'rb') as tar:
            shutil.copyfileobj(tar, gz)
        return tgz

    def needsUpdate(self, newestInput):
        return _needsUpdate(newestInput, self.path)

class TARArchiveTask(ArchiveTask):
    def newestOutput(self):
        return TimeStampFile(self.subject.path)

    def buildForbidden(self):
        if ArchiveTask.buildForbidden(self):
            return True
        if not self.args.native:
            return True

    def clean(self, forBuild=False):
        if isinstance(self.subject.suite, BinarySuite):  # make sure we never clean distributions from BinarySuites
            abort('should not reach here')
        if exists(self.subject.path):
            os.remove(self.subject.path)

    def cleanForbidden(self):
        if ArchiveTask.cleanForbidden(self):
            return True
        if not self.args.native:
            return True
        return False

"""
A Project is a collection of source code that is built by mx. For historical reasons
it typically corresponds to an IDE project and the IDE support in mx assumes this.
Additional attributes:
  suite: defining Suite
  name:  unique name (assumed as directory name)
  srcDirs: subdirectories of name containing sources to build
  deps: list of dependencies, Project, Library or Distribution
"""
class Project(Dependency):
    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, theLicense):
        Dependency.__init__(self, suite, name, theLicense)
        self.subDir = subDir
        self.srcDirs = srcDirs
        self.deps = deps
        self.workingSets = workingSets
        self.dir = d

        # Create directories for projects that don't yet exist
        ensure_dir_exists(d)
        map(ensure_dir_exists, self.source_dirs())

    def resolveDeps(self):
        '''
        Resolves symbolic dependency references to be Dependency objects.
        '''
        self._resolveDepsHelper(self.deps)
        licenseId = self.theLicense if self.theLicense else self.suite.defaultLicense
        if licenseId:
            self.theLicense = get_license(licenseId, context=self)

    def get_output_root(self):
        '''
        Gets the root of the directory hierarchy under which generated artifacts for this
        project such as class files and annotation generated sources should be placed.
        '''
        if not self.subDir:
            return join(self.suite.get_output_root(), self.name)
        names = self.subDir.split(os.sep)
        parents = len([n for n in names if n == '..'])
        if parents != 0:
            return os.sep.join([self.suite.get_output_root(), '{}-parent-{}'.format(self.suite, parents)] + names[parents:] + [self.name])
        return join(self.suite.get_output_root(), self.subDir, self.name)

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        if not _is_edge_ignored(DEP_STANDARD, ignoredEdges):
            for d in self.deps:
                if visitEdge:
                    visitEdge(self, DEP_STANDARD, d)
                if d not in visited:
                    d._walk_deps_helper(visited, DepEdge(self, DEP_STANDARD, edge), preVisit, visit, ignoredEdges, visitEdge)

    def _compute_max_dep_distances(self, dep, distances, dist):
        currentDist = distances.get(dep)
        if currentDist is None or currentDist < dist:
            distances[dep] = dist
            if dep.isProject():
                for depDep in dep.deps:
                    self._compute_max_dep_distances(depDep, distances, dist + 1)

    def canonical_deps(self):
        """
        Get the dependencies of this project that are not recursive (i.e. cannot be reached
        via other dependencies).
        """
        distances = dict()
        result = set()
        self._compute_max_dep_distances(self, distances, 0)
        for n, d in distances.iteritems():
            assert d > 0 or n is self
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

    def eclipse_settings_sources(self):
        """
        Gets a dictionary from the name of an Eclipse settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        nyi('eclipse_settings_sources', self)

    def eclipse_config_up_to_date(self, configZip):
        """
        Determines if the zipped up Eclipse configuration
        """
        return True

    def get_javac_lint_overrides(self):
        """
        Gets a string to be added to the -Xlint javac option.
        """
        nyi('get_javac_lint_overrides', self)

    def _eclipseinit(self, files=None, libFiles=None):
        """
        Generates an Eclipse project configuration for this project if Eclipse
        supports projects of this type.
        """
        pass

class ProjectBuildTask(BuildTask):
    def __init__(self, args, parallelism, project):
        BuildTask.__init__(self, project, args, parallelism)

class JavaProject(Project, ClasspathDependency):
    def __init__(self, suite, name, subDir, srcDirs, deps, javaCompliance, workingSets, d, theLicense=None):
        Project.__init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, theLicense)
        ClasspathDependency.__init__(self)
        self.checkstyleProj = name
        if javaCompliance is None:
            abort('javaCompliance property required for Java project ' + name)
        self.javaCompliance = JavaCompliance(javaCompliance)
        # The annotation processors defined by this project
        self.definedAnnotationProcessors = None
        self.declaredAnnotationProcessors = []

    def resolveDeps(self):
        Project.resolveDeps(self)
        self._resolveDepsHelper(self.declaredAnnotationProcessors)
        for ap in self.declaredAnnotationProcessors:
            if not ap.isDistribution() and not ap.isLibrary():
                abort('annotation processor dependency must be a distribution or a library: ' + ap.name, context=self)

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        if not _is_edge_ignored(DEP_ANNOTATION_PROCESSOR, ignoredEdges):
            for d in self.declaredAnnotationProcessors:
                if visitEdge:
                    visitEdge(self, DEP_ANNOTATION_PROCESSOR, d)
                if d not in visited:
                    d._walk_deps_helper(visited, DepEdge(self, DEP_ANNOTATION_PROCESSOR, edge), preVisit, visit, ignoredEdges, visitEdge)
        Project._walk_deps_visit_edges(self, visited, edge, preVisit, visit, ignoredEdges, visitEdge)

    def source_gen_dir_name(self):
        """
        Get the directory name in which source files generated by the annotation processor are found/placed.
        """
        return basename(self.source_gen_dir())

    def source_gen_dir(self, relative=False):
        """
        Get the absolute path to the directory in which source files generated by the annotation processor are found/placed.
        """
        res = join(self.get_output_root(), 'src_gen')
        if relative:
            res = os.path.relpath(res, self.dir)
        return res

    def output_dir(self, relative=False):
        """
        Get the directory in which the class files of this project are found/placed.
        """
        res = join(self.get_output_root(), 'bin')
        if relative:
            res = os.path.relpath(res, self.dir)
        return res

    def jasmin_output_dir(self):
        """
        Get the directory in which the Jasmin assembled class files of this project are found/placed.
        """
        return join(self.get_output_root(), 'jasmin_classes')

    def classpath_repr(self, resolve=True):
        return self.output_dir()

    def get_javac_lint_overrides(self):
        if not hasattr(self, '_javac_lint_overrides'):
            overrides = []
            if get_env('JAVAC_LINT_OVERRIDES'):
                overrides += get_env('JAVAC_LINT_OVERRIDES').split(',')
            if self.suite.javacLintOverrides:
                overrides += self.suite.javacLintOverrides
            if hasattr(self, 'javac.lint.overrides'):
                overrides += getattr(self, 'javac.lint.overrides').split(',')
            self._javac_lint_overrides = overrides
        return self._javac_lint_overrides

    def eclipse_config_up_to_date(self, configZip):
        for _, sources in self.eclipse_settings_sources().iteritems():
            for source in sources:
                if configZip.isOlderThan(source):
                    return False
        return True

    def eclipse_settings_sources(self):
        """
        Gets a dictionary from the name of an Eclipse settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        esdict = self.suite.eclipse_settings_sources()

        # check for project overrides
        projectSettingsDir = join(self.dir, 'eclipse-settings')
        if exists(projectSettingsDir):
            for name in os.listdir(projectSettingsDir):
                esdict.setdefault(name, []).append(os.path.abspath(join(projectSettingsDir, name)))

        if not self.annotation_processors():
            esdict.pop("org.eclipse.jdt.apt.core.prefs", None)

        return esdict

    def find_classes_with_annotations(self, pkgRoot, annotations, includeInnerClasses=False):
        """
        Scan the sources of this project for Java source files containing a line starting with 'annotation'
        (ignoring preceding whitespace) and return a dict mapping fully qualified class names to a tuple
        consisting of the source file and line number of a match.
        """

        matches = lambda line: len([a for a in annotations if line == a or line.startswith(a + '(')]) != 0
        return self.find_classes_with_matching_source_line(pkgRoot, matches, includeInnerClasses)

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
                        matchingLineFound = None
                        source = join(root, name)
                        with open(source) as f:
                            pkg = None
                            lineNo = 1
                            for line in f:
                                if line.startswith("package "):
                                    match = pkgDecl.match(line)
                                    if match:
                                        pkg = match.group(1)
                                if function(line.strip()):
                                    matchingLineFound = lineNo
                                if pkg and matchingLineFound:
                                    break
                                lineNo += 1

                        if matchingLineFound:
                            simpleClassName = name[:-len('.java')]
                            assert pkg is not None, 'could not find package statement in file ' + name
                            className = pkg + '.' + simpleClassName
                            result[className] = (source, matchingLineFound)
                            if includeInnerClasses:
                                if pkgRoot is None or pkg.startswith(pkgRoot):
                                    pkgOutputDir = join(outputDir, pkg.replace('.', os.path.sep))
                                    if exists(pkgOutputDir):
                                        for e in os.listdir(pkgOutputDir):
                                            if e.endswith('.class') and (e.startswith(simpleClassName) or e.startswith(simpleClassName + '$')):
                                                className = pkg + '.' + e[:-len('.class')]
                                                result[className] = (source, matchingLineFound)
        return result

    def _init_packages_and_imports(self):
        if not hasattr(self, '_defined_java_packages'):
            packages = set()
            extendedPackages = set()
            depPackages = set()
            def visit(dep, edge):
                if dep is not self and dep.isProject():
                    depPackages.update(dep.defined_java_packages())
            self.walk_deps(visit=visit)
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

    def annotation_processors(self):
        """
        Gets the list of dependencies defining the annotation processors that will be applied
        when compiling this project.
        """
        return self.declaredAnnotationProcessors

    def annotation_processors_path(self):
        """
        Gets the class path composed of this project's annotation processor jars and the jars they depend upon.
        """
        aps = self.annotation_processors()
        if len(aps):
            entries = classpath_entries(names=aps)
            invalid = [e.classpath_repr(resolve=True) for e in entries if not e.isJar()]
            if invalid:
                abort('Annotation processor path can only contain jars: ' + str(invalid), context=self)
            return os.pathsep.join((e for e in (e.classpath_repr(resolve=True) for e in entries) if e))
        return None

    def check_current_annotation_processors_file(self):
        aps = self.annotation_processors()
        outOfDate = False
        currentApsFile = join(self.suite.get_mx_output_dir(), 'currentAnnotationProcessors', self.name)
        currentApsFileExists = exists(currentApsFile)
        if currentApsFileExists:
            with open(currentApsFile) as fp:
                currentAps = [l.strip() for l in fp.readlines()]
            if currentAps != [ap.name for ap in aps]:
                outOfDate = True
            elif len(aps) == 0:
                os.remove(currentApsFile)
        else:
            outOfDate = len(aps) != 0
        return outOfDate

    def update_current_annotation_processors_file(self):
        aps = self.annotation_processors()
        currentApsFile = join(self.suite.get_mx_output_dir(), 'currentAnnotationProcessors', self.name)
        if len(aps) != 0:
            ensure_dir_exists(dirname(currentApsFile))
            with open(currentApsFile, 'w') as fp:
                for ap in aps:
                    print >> fp, ap
        else:
            if exists(currentApsFile):
                os.remove(currentApsFile)

    def make_archive(self, path=None):
        outputDir = self.output_dir()
        if not path:
            path = join(self.get_output_root(), self.name + '.jar')
        with Archiver(path) as arc:
            for root, _, files in os.walk(outputDir):
                for f in files:
                    relpath = root[len(outputDir) + 1:]
                    arcname = join(relpath, f).replace(os.sep, '/')
                    arc.zf.write(join(root, f), arcname)
        return path

    def _eclipseinit(self, files=None, libFiles=None):
        """
        Generates an Eclipse project configuration for this project.
        """
        _eclipseinit_project(self, files=files, libFiles=libFiles)

    def getBuildTask(self, args):
        requiredCompliance = self.javaCompliance
        if hasattr(args, 'javac_crosscompile') and args.javac_crosscompile:
            jdk = get_jdk() # build using default JDK
            if jdk.javaCompliance < requiredCompliance:
                jdk = get_jdk(requiredCompliance)
            if hasattr(args, 'parallelize') and args.parallelize:
                # Best to initialize class paths on main process
                get_jdk(requiredCompliance).bootclasspath()
        else:
            jdk = get_jdk(requiredCompliance)

        if hasattr(args, "jdt") and args.jdt and not args.force_javac:
            ec = _convert_to_eclipse_supported_compliance(max(jdk.javaCompliance, requiredCompliance))
            if ec < jdk.javaCompliance:
                jdk = get_jdk(versionCheck=ec.exactMatch, versionDescription=str(ec))
            if ec < requiredCompliance:
                requiredCompliance = ec

        return JavaBuildTask(args, self, jdk, requiredCompliance)

class JavaBuildTask(ProjectBuildTask):
    def __init__(self, args, project, jdk, requiredCompliance):
        ProjectBuildTask.__init__(self, args, 1, project)
        self.jdk = jdk
        self.requiredCompliance = requiredCompliance
        self.javafilelist = None
        self.jasmfilelist = None
        self.nonjavafiletuples = None
        self.nonjavafilecount = None
        self._newestOutput = None

    def __str__(self):
        return "Compiling {} with {}".format(self.subject.name, self._getCompiler().name())

    def initSharedMemoryState(self):
        ProjectBuildTask.initSharedMemoryState(self)
        self._newestBox = multiprocessing.Array('c', 2048)

    def pushSharedMemoryState(self):
        ProjectBuildTask.pushSharedMemoryState(self)
        self._newestBox.value = self._newestOutput.path if self._newestOutput else ''

    def pullSharedMemoryState(self):
        ProjectBuildTask.pullSharedMemoryState(self)
        self._newestOutput = TimeStampFile(self._newestBox.value) if self._newestBox.value else None

    def cleanSharedMemoryState(self):
        ProjectBuildTask.cleanSharedMemoryState(self)
        self._newestBox = None

    def buildForbidden(self):
        if ProjectBuildTask.buildForbidden(self):
            return True
        if not self.args.java:
            return True
        if exists(join(self.subject.dir, 'plugin.xml')):  # eclipse plugin project
            return True
        return False

    def cleanForbidden(self):
        if ProjectBuildTask.cleanForbidden(self):
            return True
        if not self.args.java:
            return True
        return False

    def needsBuild(self, newestInput):
        sup = ProjectBuildTask.needsBuild(self, newestInput)
        if sup[0]:
            return sup
        reason = self._collectFiles(checkBuildReason=True, newestInput=newestInput)
        if reason:
            return (True, reason)

        if self.subject.check_current_annotation_processors_file():
            return (True, 'annotation processor(s) changed')

        if len(self._javaFileList()) == 0 and len(self._jasmFileList()) == 0 and self._nonJavaFileCount() == 0:
            return (False, 'no sources')
        return (False, 'all files are up to date')

    def newestOutput(self):
        return self._newestOutput

    def _javaFileList(self):
        if not self.javafilelist:
            self._collectFiles()
        return self.javafilelist

    def _jasmFileList(self):
        if not self.jasmfilelist:
            self._collectFiles()
        return self.jasmfilelist

    def _nonJavaFileTuples(self):
        if not self.nonjavafiletuples:
            self._collectFiles()
        return self.nonjavafiletuples

    def _nonJavaFileCount(self):
        if self.nonjavafiletuples is None:
            self._collectFiles()
        return self.nonjavafiletuples

    def _collectFiles(self, checkBuildReason=False, newestInput=None):
        self.javafilelist = []
        self.jasmfilelist = []
        self.nonjavafiletuples = []
        self.nonjavafilecount = 0
        buildReason = None
        outputDir = self.subject.output_dir()
        for sourceDir in self.subject.source_dirs():
            for root, _, files in os.walk(sourceDir):
                javafiles = [join(root, name) for name in files if name.endswith('.java')]
                jasmfiles = [join(root, name) for name in files if name.endswith('.jasm')]
                self.javafilelist += javafiles
                self.jasmfilelist += jasmfiles
                nonjavafiles = [join(root, name) for name in files if not name.endswith('.java') and not name.endswith('.jasm')]
                self.nonjavafiletuples += [(sourceDir, nonjavafiles)]
                self.nonjavafilecount += len(nonjavafiles)

                def findBuildReason():
                    for inputs, inputSuffix, outputSuffix in [(javafiles, 'java', 'class'), (jasmfiles, 'jasm', 'class'), (nonjavafiles, None, None)]:
                        for inputFile in inputs:
                            if basename(inputFile) == 'package-info.java':
                                continue
                            if inputSuffix:
                                witness = TimeStampFile(outputDir + inputFile[len(sourceDir):-len(inputSuffix)] + outputSuffix)
                            else:
                                witness = TimeStampFile(outputDir + inputFile[len(sourceDir):])
                            if not witness.exists():
                                return witness.path + ' does not exist'
                            if not self._newestOutput or witness.isNewerThan(self._newestOutput):
                                self._newestOutput = witness
                            if witness.isOlderThan(inputFile):
                                return '{} is older than {}'.format(witness, TimeStampFile(inputFile))
                            if newestInput and witness.isOlderThan(newestInput):
                                return '{} is older than {}'.format(witness, newestInput)
                        return None

                if not buildReason and checkBuildReason:
                    buildReason = findBuildReason()

        self.javafilelist = sorted(self.javafilelist)  # for reproducibility
        return buildReason

    def _getCompiler(self):
        if self.args.jdt and not self.args.force_javac:
            return ECJCompiler(self.args.jdt, self.args.extra_javac_args)
        else:
            return JavacCompiler(self.args.alt_javac, self.args.extra_javac_args)

    def build(self):
        compiler = self._getCompiler()
        outputDir = self.subject.output_dir()
        ensure_dir_exists(outputDir)
        # Java build
        if self._javaFileList():
            compiler.build(
                sourceFiles=[_cygpathU2W(f) for f in self._javaFileList()],
                project=self.subject,
                jdk=self.jdk,
                compliance=self.requiredCompliance,
                outputDir=_cygpathU2W(outputDir),
                classPath=_separatedCygpathU2W(classpath(self.subject.name, includeSelf=False)),
                sourceGenDir=self.subject.source_gen_dir(),
                processorPath=_separatedCygpathU2W(self.subject.annotation_processors_path()),
                disableApiRestrictions=not self.args.warnAPI,
                warningsAsErrors=self.args.warning_as_error,
                showTasks=self.args.jdt_show_task_tags
            )
            logvv('Finished Java compilation for {}'.format(self.subject.name))
            def allOutputFiles():
                for root, _, filenames in os.walk(outputDir):
                    for fname in filenames:
                        yield os.path.join(root, fname)
            self._newestOutput = TimeStampFile(max(allOutputFiles(), key=os.path.getmtime))
        # Jasmin build
        for src in self._jasmFileList():
            className = None
            with open(src) as f:
                for line in f:
                    if line.lstrip().startswith('.class ') or line.lstrip().startswith('.interface '):
                        className = line.split()[-1]
                        break
            if not className:
                abort('could not file .class or .interface directive in Jasmin source: ' + src)
            else:
                jasminOutputDir = self.subject.jasmin_output_dir()
                classFile = join(jasminOutputDir, className.replace('/', os.sep) + '.class')
                if exists(dirname(classFile)) and (not exists(classFile) or os.path.getmtime(classFile) < os.path.getmtime(src)):
                    logv('Assembling Jasmin file ' + src)
                    run(['jasmin', '-d', jasminOutputDir, src])
                    self._newestOutput = TimeStampFile(classFile)
        self.subject.update_current_annotation_processors_file()
        if self._jasmFileList():
            logvv('Finished Jasmin compilation for {}'.format(self.subject.name))
        # Copy other files
        for nonjavafiletuple in self._nonJavaFileTuples():
            sourceDir = nonjavafiletuple[0]
            nonjavafilelist = nonjavafiletuple[1]
            for src in nonjavafilelist:
                dst = join(outputDir, src[len(sourceDir) + 1:])
                ensure_dir_exists(dirname(dst))
                if exists(dirname(dst)) and (not exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src)):
                    shutil.copyfile(src, dst)
                    self._newestOutput = TimeStampFile(dst)
        if self._nonJavaFileCount():
            logvv('Finished resource copy for {}'.format(self.subject.name))

    def clean(self, forBuild=False):
        genDir = self.subject.source_gen_dir()
        if exists(genDir):
            logv('Cleaning {0}...'.format(genDir))
            for f in os.listdir(genDir):
                rmtree(join(genDir, f))

        outputDir = self.subject.output_dir()
        if exists(outputDir):
            logv('Cleaning {0}...'.format(outputDir))
            rmtree(outputDir)

class JavaCompiler:
    def name(self):
        nyi('name', self)

    # TODO make sure paths have been 'cygwinized' before reaching here
    def build(self, sourceFiles, project, jdk, compliance, outputDir, classPath, processorPath, sourceGenDir,
        disableApiRestrictions, warningsAsErrors, showTasks):
        nyi('build', self)

class JavacLikeCompiler(JavaCompiler):
    def __init__(self, extraJavacArgs):
        self.tmpFiles = []
        self.extraJavacArgs = extraJavacArgs if extraJavacArgs else []

    def _get_compliance_jdk(self, compliance):
        return get_jdk(compliance)

    def build(self, sourceFiles, project, jdk, compliance, outputDir, classPath, processorPath, sourceGenDir,
        disableApiRestrictions, warningsAsErrors, showTasks):
        jvmArgs = ['-Xmx1500m']
        javacArgs = ['-g', '-source', str(compliance), '-target', str(compliance), '-classpath', classPath, '-d', outputDir]
        if processorPath:
            ensure_dir_exists(sourceGenDir)
            javacArgs += ['-processorpath', processorPath, '-s', sourceGenDir]
        else:
            javacArgs += ['-proc:none']
        hybridCrossCompilation = False
        if jdk.javaCompliance != compliance:
            # cross-compilation
            assert jdk.javaCompliance > compliance
            complianceJdk = self._get_compliance_jdk(compliance)
            # complianceJdk.javaCompliance could be different from compliance
            # because of non-strict compliance mode
            if jdk.javaCompliance != complianceJdk.javaCompliance:
                javacArgs = complianceJdk.javacLibOptions(javacArgs)
            else:
                hybridCrossCompilation = True
        if _opts.very_verbose:
            javacArgs.append('-verbose')

        javacArgs.extend(self.extraJavacArgs)
        fileListFile = self.createFileListFile(sourceFiles, project.get_output_root())
        javacArgs.append('@' + _cygpathU2W(fileListFile))
        try:
            self.buildJavacLike(jdk, project, jvmArgs, javacArgs, disableApiRestrictions, warningsAsErrors, showTasks, hybridCrossCompilation)
        finally:
            # Do not clean up temp files if verbose as there's
            # a good chance the user wants to copy and paste the
            # Java compiler command directly
            if not _opts.verbose:
                for n in self.tmpFiles:
                    os.remove(n)

    def buildJavacLike(self, jdk, project, jvmArgs, javacArgs, disableApiRestrictions, warningsAsErrors, showTasks, hybridCrossCompilation):
        """
        *hybridCrossCompilation* is true if the -source compilation option denotes a different JDK version than
        the JDK libraries that will be compiled against.
        """
        nyi('buildJavacLike', self)

    def createFileListFile(self, files, directory):
        if _opts.verbose:
            # use a single file since it will be left on disk
            f = open(join(directory, 'javafilelist.txt'), 'w')
            name = f.name
        else:
            (fd, name) = tempfile.mkstemp(prefix='javafilelist', suffix='.txt', dir=directory)
            f = os.fdopen(fd, 'w')
        f.write(os.linesep.join(files))
        f.close()
        self.tmpFiles.append(name)
        return name

class JavacCompiler(JavacLikeCompiler):
    def __init__(self, altJavac=None, extraJavacArgs=None):
        JavacLikeCompiler.__init__(self, extraJavacArgs)
        self.altJavac = altJavac

    def name(self):
        return 'javac'

    def buildJavacLike(self, jdk, project, jvmArgs, javacArgs, disableApiRestrictions, warningsAsErrors, showTasks, hybridCrossCompilation):
        lint = ['all', '-auxiliaryclass', '-processing']
        overrides = project.get_javac_lint_overrides()
        if overrides:
            if 'none' in overrides:
                lint = ['none']
            else:
                lint += overrides
        if hybridCrossCompilation:
            if lint != ['none'] and warningsAsErrors:
                # disable the "bootstrap class path not set in conjunction with -source N" warning
                # since we are not in strict compliance mode
                assert not _opts.strict_compliance
                lint += ['-options']
        knownLints = jdk.getKnownJavacLints()
        if knownLints:
            lint = [l for l in lint if l in knownLints]
        if lint:
            javacArgs.append('-Xlint:' + ','.join(lint))
        if disableApiRestrictions:
            javacArgs.append('-XDignore.symbol.file')
        if warningsAsErrors:
            javacArgs.append('-Werror')
        if showTasks:
            abort('Showing task tags is not currently supported for javac')
        javacArgs.append('-encoding')
        javacArgs.append('UTF-8')
        javac = self.altJavac if self.altJavac else jdk.javac
        jvmArgs += jdk.java_args
        cmd = [javac] + ['-J' + arg for arg in jvmArgs] + javacArgs
        run(cmd)

class ECJCompiler(JavacLikeCompiler):
    def __init__(self, jdtJar, extraJavacArgs=None):
        JavacLikeCompiler.__init__(self, extraJavacArgs)
        self.jdtJar = jdtJar

    def name(self):
        return 'JDT'

    def _get_compliance_jdk(self, compliance):
        jdk = get_jdk(compliance)
        esc = _convert_to_eclipse_supported_compliance(jdk.javaCompliance)
        if esc < jdk.javaCompliance:
            # We need to emulate strict compliance here so that the right boot
            # class path is selected when compiling with a JDT that does not
            # support a JDK9 boot class path
            jdk = get_jdk(versionCheck=esc.exactMatch, versionDescription=str(esc))
        return jdk

    def buildJavacLike(self, jdk, project, jvmArgs, javacArgs, disableApiRestrictions, warningsAsErrors, showTasks, hybridCrossCompilation):
        jvmArgs += ['-jar', self.jdtJar]
        jdtArgs = javacArgs

        jdtProperties = join(project.dir, '.settings', 'org.eclipse.jdt.core.prefs')
        jdtPropertiesSources = project.eclipse_settings_sources()['org.eclipse.jdt.core.prefs']
        if not exists(jdtProperties) or TimeStampFile(jdtProperties).isOlderThan(jdtPropertiesSources):
            # Try to fix a missing or out of date properties file by running eclipseinit
            project._eclipseinit()
        if not exists(jdtProperties):
            log('JDT properties file {0} not found'.format(jdtProperties))
        else:
            with open(jdtProperties) as fp:
                origContent = fp.read()
                content = origContent
                if [ap for ap in project.declaredAnnotationProcessors if ap.isLibrary()]:
                    # unfortunately, the command line compiler doesn't let us ignore warnings for generated files only
                    content = content.replace('=warning', '=ignore')
                elif warningsAsErrors:
                    content = content.replace('=warning', '=error')
                if not showTasks:
                    content = content + '\norg.eclipse.jdt.core.compiler.problem.tasks=ignore'
                if disableApiRestrictions:
                    content = content + '\norg.eclipse.jdt.core.compiler.problem.forbiddenReference=ignore'
                    content = content + '\norg.eclipse.jdt.core.compiler.problem.discouragedReference=ignore'
            if origContent != content:
                jdtPropertiesTmp = jdtProperties + '.tmp'
                with open(jdtPropertiesTmp, 'w') as fp:
                    fp.write(content)
                self.tmpFiles.append(jdtPropertiesTmp)
                jdtArgs += ['-properties', _cygpathU2W(jdtPropertiesTmp)]
            else:
                jdtArgs += ['-properties', _cygpathU2W(jdtProperties)]

        run_java(jvmArgs + jdtArgs, jdk=jdk)

def is_debug_lib_file(fn):
    return fn.endswith(add_debug_lib_suffix(""))

def _replaceResultsVar(m):
    var = m.group(1)
    if var == 'os':
        return get_os()
    elif var == 'arch':
        return get_arch()
    elif var.startswith('lib:'):
        libname = var[len('lib:'):]
        return add_lib_suffix(add_lib_prefix(libname))
    elif var.startswith('libdebug:'):
        libname = var[len('libdebug:'):]
        return add_debug_lib_suffix(add_lib_prefix(libname))
    else:
        abort('Unknown variable: ' + var)

class NativeProject(Project):
    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, results, output, d, theLicense=None):
        Project.__init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, theLicense)
        self.results = results
        self.output = output

    def getBuildTask(self, args):
        return NativeBuildTask(args, self)

    def getOutput(self, replaceVar=_replaceResultsVar):
        if not self.output:
            return None
        return re.sub(r'<(.+?)>', replaceVar, self.output)

    def getResults(self, replaceVar=_replaceResultsVar):
        results = []
        output = self.getOutput(replaceVar=replaceVar)
        for rt in self.results:
            r = re.sub(r'<(.+?)>', replaceVar, rt)
            results.append(join(self.suite.dir, output, r))
        return results

class NativeBuildTask(ProjectBuildTask):
    def __init__(self, args, project):
        ProjectBuildTask.__init__(self, args, cpu_count(), project)  # assume parallelized
        self._newestOutput = None

    def __str__(self):
        return 'Building {} with GNU Make'.format(self.subject.name)

    def build(self):
        run([gmake_cmd()], cwd=self.subject.dir)
        self._newestOutput = None

    def needsBuild(self, newestInput):
        return (True, None)  # let make decide

    def buildForbidden(self):
        if ProjectBuildTask.buildForbidden(self):
            return True
        if not self.args.native:
            return True

    def cleanForbidden(self):
        if ProjectBuildTask.cleanForbidden(self):
            return True
        if not self.args.native:
            return True
        return False

    def newestOutput(self):
        if self._newestOutput is None:
            results = self.subject.getResults()
            self._newestOutput = None
            for r in results:
                ts = TimeStampFile(r)
                if ts.exists():
                    if not self._newestOutput or ts.isNewerThan(self._newestOutput):
                        self._newestOutput = ts
                else:
                    self._newestOutput = ts
                    break
        return self._newestOutput

    def clean(self, forBuild=False):
        if not forBuild:  # assume make can do incremental builds
            run([gmake_cmd(), 'clean'], cwd=self.subject.dir)
            self._newestOutput = None

def _make_absolute(path, prefix):
    """
    Makes 'path' absolute if it isn't already by prefixing 'prefix'
    """
    if not isabs(path):
        return join(prefix, path)
    return path

@primary_suite_exempt
def sha1(args):
    """generate sha1 digest for given file"""
    parser = ArgumentParser(prog='sha1')
    parser.add_argument('--path', action='store', help='path to file', metavar='<path>', required=True)
    parser.add_argument('--plain', action='store_true', help='just the 40 chars', )
    args = parser.parse_args(args)
    value = sha1OfFile(args.path)
    if args.plain:
        sys.stdout.write(value)
    else:
        print 'sha1 of ' + args.path + ': ' + value

def sha1OfFile(path):
    with open(path, 'rb') as f:
        d = hashlib.sha1()
        while True:
            buf = f.read(4096)
            if not buf:
                break
            d.update(buf)
        return d.hexdigest()

def _get_path_in_cache(name, sha1, urls, ext=None):
    """
    Gets the path an artifact has (or would have) in the download cache.
    """
    assert sha1 != 'NOCHECK', 'artifact for ' + name + ' cannot be cached since its sha1 is NOCHECK'
    userHome = _opts.user_home if hasattr(_opts, 'user_home') else os.path.expanduser('~')
    if ext is None:
        for url in urls:
            # Use extension of first URL whose path component ends with a non-empty extension
            o = urlparse.urlparse(url)
            if o.path == "/remotecontent" and o.query.startswith("filepath"):
                path = o.query
            else:
                path = o.path
            _, ext = os.path.splitext(path)
            if ext:
                break
        if not ext:
            abort('Could not determine a file extension from URL(s):\n  ' + '\n  '.join(urls))
    cacheDir = _cygpathW2U(get_env('MX_CACHE_DIR', join(userHome, '.mx', 'cache')))
    assert os.sep not in name, name + ' cannot contain ' + os.sep
    assert os.pathsep not in name, name + ' cannot contain ' + os.pathsep
    return join(cacheDir, name + '_' + sha1 + ext)

def download_file_with_sha1(name, path, urls, sha1, sha1path, resolve, mustExist, sources=False, canSymlink=True):
    '''
    Downloads an entity from a URL in the list 'urls' (tried in order) to 'path',
    checking the sha1 digest of the result against 'sha1' (if not 'NOCHECK')
    Manages an internal cache of downloads and will link path to the cache entry unless 'canSymLink=False'
    in which case it copies the cache entry.
    '''
    sha1Check = sha1 and sha1 != 'NOCHECK'
    canSymlink = canSymlink and not (get_os() == 'windows' or get_os() == 'cygwin')

    if len(urls) is 0 and not sha1Check:
        return path

    if not _check_file_with_sha1(path, sha1, sha1path, resolve and mustExist):
        if len(urls) is 0:
            abort('SHA1 of {} ({}) does not match expected value ({})'.format(path, sha1OfFile(path), sha1))

        cacheDir = _cygpathW2U(get_env('MX_CACHE_DIR', join(_opts.user_home, '.mx', 'cache')))
        ensure_dir_exists(cacheDir)

        _, ext = os.path.splitext(path)
        cachePath = _get_path_in_cache(name, sha1, urls, ext=ext)

        if not exists(cachePath) or (sha1Check and sha1OfFile(cachePath) != sha1):
            if exists(cachePath):
                log('SHA1 of ' + cachePath + ' does not match expected value (' + sha1 + ') - found ' + sha1OfFile(cachePath) + ' - re-downloading')

            def _findLegacyCachePath():
                for e in os.listdir(cacheDir):
                    if sha1 in e and sha1OfFile(join(cacheDir, e)) == sha1:
                        return join(cacheDir, e)
                return None

            legacyCachePath = _findLegacyCachePath()
            if legacyCachePath:
                logvv('Copying {} to {}'.format(legacyCachePath, cachePath))
                shutil.move(legacyCachePath, cachePath)
            else:
                log('Downloading ' + ("sources " if sources else "") + name + ' from ' + str(urls))
                download(cachePath, urls)

        if path != cachePath:
            d = dirname(path)
            if d != '':
                ensure_dir_exists(d)
            if canSymlink and 'symlink' in dir(os):
                logvv('Symlinking {} to {}'.format(path, cachePath))
                if os.path.lexists(path):
                    os.unlink(path)
                try:
                    os.symlink(cachePath, path)
                except OSError as e:
                    # When doing parallel building, the symlink can fail
                    # if another thread wins the race to create the symlink
                    if not os.path.lexists(path):
                        # It was some other error
                        raise Exception(path, e)
            else:
                logvv('Copying {} to {}'.format(path, cachePath))
                shutil.copy(cachePath, path)

        if not _check_file_with_sha1(path, sha1, sha1path, newFile=True):
            log('SHA1 of ' + sha1OfFile(cachePath) + ' does not match expected value (' + sha1 + ')')
            abort("SHA1 does not match for " + name + ". Broken download? SHA1 not updated in suite.py file?")

    return path

"""
Checks if a file exists and is up to date according to the sha1.
Returns False if the file is not there or does not have the right checksum.
"""
def _check_file_with_sha1(path, sha1, sha1path, mustExist=True, newFile=False):
    sha1Check = sha1 and sha1 != 'NOCHECK'

    def _sha1CachedValid():
        if not exists(sha1path):
            return False
        if TimeStampFile(path, followSymlinks=True).isNewerThan(sha1path):
            return False
        return True

    def _sha1Cached():
        with open(sha1path, 'r') as f:
            return f.read()[0:40]

    def _writeSha1Cached():
        with open(sha1path, 'w') as f:
            f.write(sha1OfFile(path))

    if exists(path):
        if sha1Check and sha1:
            if not _sha1CachedValid() or (newFile and sha1 != _sha1Cached()):
                logv('Create/update SHA1 cache file ' + sha1path)
                _writeSha1Cached()

            if sha1 != _sha1Cached():
                if sha1 == sha1OfFile(path):
                    logv('Fix corrupt SHA1 cache file ' + sha1path)
                    _writeSha1Cached()
                    return True
                return False
    elif mustExist:
        return False

    return True


"""
A BaseLibrary is an entity that is an object that has no structure understood by mx,
typically a jar file. It is used "as is".
"""
class BaseLibrary(Dependency):
    def __init__(self, suite, name, optional, theLicense):
        Dependency.__init__(self, suite, name, theLicense)
        self.optional = optional

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        pass

    def resolveDeps(self):
        licenseId = self.theLicense
        # do not use suite's default license
        if licenseId:
            self.theLicense = get_license(licenseId, context=self)

"""
A library that is just a resource and therefore not a ClasspathDependency
"""
class ResourceLibrary(BaseLibrary):
    def __init__(self, suite, name, path, optional, urls, sha1):
        BaseLibrary.__init__(self, suite, name, optional, None)
        self.path = path.replace('/', os.sep)
        self.sourcePath = None
        self.urls = urls
        self.sha1 = sha1

    def getBuildTask(self, args):
        return LibraryDownloadTask(args, self)

    def get_path(self, resolve):
        path = _make_absolute(self.path, self.suite.dir)
        sha1path = path + '.sha1'
        return download_file_with_sha1(self.name, path, self.urls, self.sha1, sha1path, resolve, not self.optional, canSymlink=True)

    def _check_download_needed(self):
        path = _make_absolute(self.path, self.suite.dir)
        sha1path = path + '.sha1'
        return not _check_file_with_sha1(path, self.sha1, sha1path)

"""
A library that will be provided by the JRE but may be absent.
Any project or normal library that depends on a missing library
will be removed from the global project and library dictionaries
(i.e., _projects and _libs).

The library is searched on the classpaths of the JRE.

This mechanism exists primarily to be able to support code
that may use functionality in one JRE (e.g., Oracle JRE)
that is not present in another JRE (e.g., OpenJDK). A
motivating example is the Java Flight Recorder library
found in the Oracle JRE.
"""
class JreLibrary(BaseLibrary, ClasspathDependency):
    def __init__(self, suite, name, jar, optional, theLicense):
        BaseLibrary.__init__(self, suite, name, optional, theLicense)
        ClasspathDependency.__init__(self)
        self.jar = jar

    def __eq__(self, other):
        if isinstance(other, JreLibrary):
            return self.jar == other.jar
        else:
            return NotImplemented

    def is_present_in_jdk(self, jdk):
        return jdk.hasJarOnClasspath(self.jar)

    def getBuildTask(self, args):
        return NoOpTask(self, args)

    def classpath_repr(self, resolve=True):
        return None # TODO should have a jdk arg and should fail if not available

class NoOpTask(BuildTask):
    def __init__(self, subject, args):
        BuildTask.__init__(self, subject, args, 1)

    def __str__(self):
        return "NoOp"

    def logBuild(self, reason):
        pass

    def logSkip(self, reason):
        pass

    def needsBuild(self, newestInput):
        return (False, None)

    def newestOutput(self):
        # TODO Should still return something for jdk/jre library and NativeTARDistributions
        return None

    def build(self):
        pass

    def clean(self, forBuild=False):
        pass

    def cleanForbidden(self):
        return True

"""
A library that will be provided by the JDK but may be absent.
Any project or normal library that depends on a missing library
will be removed from the global project and library dictionaries
(i.e., _projects and _libs).
"""
class JdkLibrary(BaseLibrary, ClasspathDependency):
    def __init__(self, suite, name, path, optional, theLicense):
        BaseLibrary.__init__(self, suite, name, optional, theLicense)
        ClasspathDependency.__init__(self)
        self.path = path

    def __eq__(self, other):
        if isinstance(other, JdkLibrary):
            return self.path == other.path
        else:
            return NotImplemented

    def is_present_in_jdk(self, jdk):
        return exists(join(jdk.path, self.jar))

    def getBuildTask(self, args):
        return NoOpTask(self, args)

    def classpath_repr(self, resolve=True):
        return self.path  # TODO should have a jdk arg and should fail if not available

"""
A library that is provided (built) by some third-party and made available via a URL.
A Library may have dependencies on other Library's as expressed by the "deps" field.
A Library can only depend on another Library, and not a Project or Distribution
Additional attributes are an SHA1 checksum, location of (assumed) matching sources.
A Library is effectively an "import" into the suite since, unlike a Project or Distribution
it is not built by the Suite.
N.B. Not obvious but a Library can be an annotationProcessor
"""
class Library(BaseLibrary, ClasspathDependency):
    def __init__(self, suite, name, path, optional, urls, sha1, sourcePath, sourceUrls, sourceSha1, deps, theLicense):
        BaseLibrary.__init__(self, suite, name, optional, theLicense)
        ClasspathDependency.__init__(self)
        self.path = path.replace('/', os.sep)
        self.urls = urls
        self.sha1 = sha1
        self.sourcePath = sourcePath.replace('/', os.sep) if sourcePath else None
        self.sourceUrls = sourceUrls
        if sourcePath == path:
            assert sourceSha1 is None or sourceSha1 == sha1
            sourceSha1 = sha1
        self.sourceSha1 = sourceSha1
        self.deps = deps
        abspath = _make_absolute(path, self.suite.dir)
        if not optional and not exists(abspath):
            if not len(urls):
                abort('Non-optional library {0} must either exist at {1} or specify one or more URLs from which it can be retrieved'.format(name, abspath), context=self)

        def _checkSha1PropertyCondition(propName, cond, inputPath):
            if not cond and not optional:
                absInputPath = _make_absolute(inputPath, self.suite.dir)
                if exists(absInputPath):
                    abort('Missing "{0}" property for library {1}. Add the following to the definition of {1}:\n{0}={2}'.format(propName, name, sha1OfFile(absInputPath)), context=self)
                abort('Missing "{0}" property for library {1}'.format(propName, name), context=self)

        _checkSha1PropertyCondition('sha1', sha1, path)
        _checkSha1PropertyCondition('sourceSha1', not sourcePath or sourceSha1, sourcePath)

        for url in urls:
            if url.endswith('/') != self.path.endswith(os.sep):
                abort('Path for dependency directory must have a URL ending with "/": path=' + self.path + ' url=' + url, context=self)

    def resolveDeps(self):
        '''
        Resolves symbolic dependency references to be Dependency objects.
        '''
        BaseLibrary.resolveDeps(self)
        self._resolveDepsHelper(self.deps)

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        if not _is_edge_ignored(DEP_STANDARD, ignoredEdges):
            for d in self.deps:
                if visitEdge:
                    visitEdge(self, DEP_STANDARD, d)
                if d not in visited:
                    d._walk_deps_helper(visited, DepEdge(self, DEP_STANDARD, edge), preVisit, visit, ignoredEdges, visitEdge)


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

        bootClassPathAgent = getattr(self, 'bootClassPathAgent').lower() == 'true' if hasattr(self, 'bootClassPathAgent') else False

        return download_file_with_sha1(self.name, path, self.urls, self.sha1, sha1path, resolve, not self.optional, canSymlink=not bootClassPathAgent)

    def _check_download_needed(self):
        path = _make_absolute(self.path, self.suite.dir)
        sha1path = path + '.sha1'
        return not _check_file_with_sha1(path, self.sha1, sha1path)

    def get_source_path(self, resolve):
        if self.sourcePath is None:
            return None
        path = _make_absolute(self.sourcePath, self.suite.dir)
        sha1path = path + '.sha1'

        return download_file_with_sha1(self.name, path, self.sourceUrls, self.sourceSha1, sha1path, resolve, len(self.sourceUrls) != 0, sources=True)

    def classpath_repr(self, resolve=True):
        path = self.get_path(resolve)
        if path and (exists(path) or not resolve):
            return path
        return None

    def getBuildTask(self, args):
        return LibraryDownloadTask(args, self)

class LibraryDownloadTask(BuildTask):
    def __init__(self, args, lib):
        BuildTask.__init__(self, lib, args, 1)  # TODO use all CPUs to avoid output problems?

    def __str__(self):
        return "Downloading {}".format(self.subject.name)

    def logBuild(self, reason):
        pass

    def logSkip(self, reason):
        pass

    def needsBuild(self, newestInput):
        sup = BuildTask.needsBuild(self, newestInput)
        if sup[0]:
            return sup
        return (self.subject._check_download_needed(), None)

    def newestOutput(self):
        return TimeStampFile(_make_absolute(self.subject.path, self.subject.suite.dir))

    def build(self):
        self.subject.get_path(resolve=True)

    def clean(self, forBuild=False):
        abort('should not reach here')

    def cleanForbidden(self):
        return True

'''
Abstracts the operations of the version control systems
Most operations take a vcdir as the dir in which to execute the operation
Most operations abort on error unless abortOnError=False, and return True
or False for success/failure.

Potentially long running operations should log the command. If '-v' is set
'run'  will log the actual VC command. If '-V' is set the output from
the command should be logged.
'''
class VC(object):
    __metaclass__ = ABCMeta
    """
    base class for all supported Distriuted Version Constrol abstractions

    :ivar str kind: the VC type identifier
    :ivar str proper_name: the long name descriptor of the VCS
    """

    def __init__(self, kind, proper_name):
        self.kind = kind
        self.proper_name = proper_name

    @staticmethod
    def is_valid_kind(kind):
        """
        tests if the given VCS kind is valid or not

        :param str kind: the VCS kind
        :return: True if a valid VCS kind
        :rtype: bool
        """
        for vcs in _vc_systems:
            if kind == vcs.kind:
                return True
        return False

    @staticmethod
    def get_vc(vcdir, abortOnError=True):
        """
        Given that :param:`vcdir` is a repository directory, attempt to determine
        what kind of VCS is it managed by. Return None if it cannot be determined.

        :param str vcdir: a valid path to a version controlled directory
        :param boo abortOnError: if an error occurs, abort mx operations
        :return: an instance of VC or None if it cannot be determined
        :rtype: :class:`VC`
        """
        for vcs in _vc_systems:
            vcs.check()
            if vcs.is_this_vc(vcdir):
                return vcs
        if abortOnError:
            abort('cannot determine VC for ' + vcdir)
        else:
            return None

    def check(self, abortOnError=True):
        '''
        Lazily check whether a particular VC system is available.
        Return None if fails and abortOnError=False
        '''
        abort("VC.check is not implemented")

    def init(self, vcdir, abortOnError=True):
        '''
        Intialize 'vcdir' for vc control
        '''
        abort(self.kind + " init is not implemented")

    def is_this_vc(self, vcdir):
        '''
        Check whether vcdir is managed by this vc.
        Return None if not, True if so
        '''
        abort(self.kind + " is_this_vc is not implemented")

    def metadir(self):
        '''
        Return name of metadata directory
        '''
        abort(self.kind + " metadir is not implemented")

    def add(self, vcdir, path, abortOnError=True):
        '''
        Add path to repo
        '''
        abort(self.kind + " add is not implemented")

    def commit(self, vcdir, msg, abortOnError=True):
        '''
        commit with msg
        '''
        abort(self.kind + " commit is not implemented")

    def tip(self, vcdir, abortOnError=True):
        """
        Get the most recent changeset for repo at :param:`vcdir`.

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and :param:`abortOnError`=False
        :rtype: str
        """
        abort(self.kind + " tip is not implemented")

    def parent(self, vcdir, abortOnError=True):
        """
        Get the parent changeset of the working directory for repo at :param:`vcdir`.

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and :param:`abortOnError`=False
        :rtype: str
        """
        abort(self.kind + " id is not implemented")

    def release_version_from_tags(self, vcdir, prefix, snapshotSuffix='dev', abortOnError=True):
        """
        Returns a release version derived from VC tags that match the pattern <prefix>-<major>.<minor>
        or None if no such tags exist.

        :param str vcdir: a valid repository path
        :param str prefix: the prefix
        :param str snapshotSuffix: the snapshot suffix
        :param bool abortOnError: if True abort on mx error
        :return: a release version
        :rtype: str
        """
        abort(self.kind + " release_version_from_tags is not implemented")

    def clone(self, url, dest=None, rev=None, abortOnError=True, **extra_args):
        """
        Clone the repo at :param:`url` to :param:`dest` using :param:`rev`

        :param str url: the repository url
        :param str dest: the path to destination, if None the destination is
                         chosen by the vcs
        :param str rev: the desired revision, if None use tip
        :param dict extra_args: for subclass-specific information in/out
        :return: True if the operation is successful, False otherwise
        :rtype: bool
        """
        abort(self.kind + " clone is not implemented")

    def _log_clone(self, url, dest=None, rev=None):
        msg = 'Cloning ' + url
        if rev:
            msg += ' revision ' + rev
        if dest:
            msg += ' to ' + dest
        msg += ' with ' + self.proper_name
        log(msg)

    def pull(self, vcdir, rev=None, update=False, abortOnError=True):
        """
        Pull a given changeset (the head if `rev` is None), optionally updating
        the working directory. Updating is only done if something was pulled.
        If there were no new changesets or `rev` was already known locally,
        no update is performed.

        :param str vcdir: a valid repository path
        :param str rev: the desired revision, if None use tip
        :param bool abortOnError: if True abort on mx error
        :return: True if the operation is successful, False otherwise
        :rtype: bool
        """
        abort(self.kind + " pull is not implemented")

    def _log_pull(self, vcdir, rev):
        msg = 'Pulling'
        if rev:
            msg += ' revision ' + rev
        else:
            msg += ' head updates'
        msg += ' in ' + vcdir
        msg += ' with ' + self.proper_name
        log(msg)

    def can_push(self, vcdir, strict=True):
        """
        Check if :param:`vcdir` can be pushed.

        :param str vcdir: a valid repository path
        :param bool strict: if set no uncommitted changes or unadded are allowed
        :return: True if we can push, False otherwise
        :rtype: bool
        """

    def default_push(self, vcdir, abortOnError=True):
        """
        get the default push target for this repo

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: default push target for repo
        :rtype: str
        """
        abort(self.kind + " default_push is not implemented")

    def default_pull(self, vcdir, abortOnError=True):
        """
        get the default pull target for this repo

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: default pull target for repo
        :rtype: str
        """
        abort(self.kind + " default_pull is not implemented")

    def incoming(self, vcdir, abortOnError=True):
        """
        list incoming changesets

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and :param:`abortOnError`=False
        :rtype: str
        """
        abort(self.kind + ": outgoing is not implemented")

    def outgoing(self, vcdir, dest=None, abortOnError=True):
        """
        llist outgoing changesets to 'dest' or default-push if None

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and :param:`abortOnError`=False
        :rtype: str
        """
        abort(self.kind + ": outgoing is not implemented")

    def push(self, vcdir, dest=None, rev=None, abortOnError=True):
        """
        Push :param:`vcdir` at rev :param:`rev` to default if :param:`dest`
        is None, else push to :param:`dest`.

        :param str vcdir: a valid repository path
        :param str rev: the desired revision
        :param str dest: the path to destination
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        abort(self.kind + ": push is not implemented")

    def _log_push(self, vcdir, dest, rev):
        msg = 'Pushing changes'
        if rev:
            msg += ' revision ' + rev
        msg += ' from ' + vcdir
        if dest:
            msg += ' to ' + dest
        else:
            msg += ' to default'
        msg += ' with ' + self.proper_name
        log(msg)

    def update(self, vcdir, rev=None, mayPull=False, clean=False, abortOnError=True):
        """
        update the :param:`vcdir` working directory.
        If :param:`rev` is not specified, update to the tip of the current branch.
        If :param:`rev` is specified, `mayPull` controls whether a pull will be attempted if
        :param:`rev` can not be found locally.
        If :param:`clean` is True, uncommitted changes will be discarded (no backup!).

        :param str vcdir: a valid repository path
        :param str rev: the desired revision
        :param bool mayPull: flag to controll whether to pull or not
        :param bool clean: discard uncommitted changes without backing up
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        abort(self.kind + " update is not implemented")

    def isDirty(self, vcdir, abortOnError=True):
        """
        check whether the working directory is dirty

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: True of the working directory is dirty, False otherwise
        :rtype: bool
        """
        abort(self.kind + " isDirty is not implemented")

    def locate(self, vcdir, patterns=None, abortOnError=True):
        """
        Return a list of paths under vc control that match :param:`patterns`

        :param str vcdir: a valid repository path
        :param patterns: a list of patterns
        :type patterns: str or None or list
        :param bool abortOnError: if True abort on mx error
        :return: a list of paths under vc control
        :rtype: list
        """
        abort(self.kind + " locate is not implemented")

    def bookmark(self, vcdir, name, rev, abortOnError=True):
        """
        Place a bookmark at a given revision

        :param str vcdir: a valid repository path
        :param str name: the name of the bookmark
        :param str rev: the desired revision
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        abort(self.kind + " bookmark is not implemented")

    def latest(self, vcdir, rev1, rev2, abortOnError=True):
        """
        Returns the latest of 2 revisions.
        The revisions should be related in the DAG.

        :param str vcdir: a valid repository path
        :param str rev1: the first revision
        :param str rev2: the second revision
        :param bool abortOnError: if True abort on mx error
        :return: the latest of the 2 revisions
        :rtype: str or None
        """
        abort(self.kind + " latest is not implemented")

    def exists(self, vcdir, rev):
        """
        Check if a given revision exists in the repository.

        :param str vcdir: a valid repository path
        :param str rev: the second revision
        :return: True if revision exists, False otherwise
        :rtype: bool
        """
        abort(self.kind + " exists is not implemented")


class OutputCapture:
    def __init__(self):
        self.data = ""
    def __call__(self, data):
        self.data += data

class LinesOutputCapture:
    def __init__(self):
        self.lines = []
    def __call__(self, data):
        self.lines.append(data.rstrip())

class HgConfig(VC):
    """
    Encapsulates access to Mercurial (hg)
    """
    def __init__(self):
        VC.__init__(self, 'hg', 'Mercurial')
        self.missing = 'no hg executable found'
        self.has_hg = None

    def check(self, abortOnError=True):
        # Mercurial does lazy checking before use of the hg command itself
        return self

    def check_for_hg(self, abortOnError=True):
        if self.has_hg is None:
            try:
                subprocess.check_output(['hg'])
                self.has_hg = True
            except OSError:
                self.has_hg = False
                warn(self.missing)

        if not self.has_hg:
            if abortOnError:
                abort(self.missing)
            else:
                warn(self.missing)

        return self if self.has_hg else None

    def run(self, *args, **kwargs):
        # Ensure hg exists before executing the command
        self.check_for_hg()
        return run(*args, **kwargs)

    def init(self, vcdir, abortOnError=True):
        return self.run(['hg', 'init'], cwd=vcdir, nonZeroIsFatal=abortOnError) == 0

    def is_this_vc(self, vcdir):
        hgdir = join(vcdir, self.metadir())
        return os.path.isdir(hgdir)

    def hg_command(self, vcdir, args, abortOnError=False, quiet=False):
        args = ['hg', '-R', vcdir] + args
        if not quiet:
            print '{0}'.format(" ".join(args))
        out = OutputCapture()
        rc = self.run(args, nonZeroIsFatal=False, out=out)
        if rc == 0 or rc == 1:
            return out.data
        else:
            if abortOnError:
                abort(" ".join(args) + ' returned ' + str(rc))
            return None

    def add(self, vcdir, path, abortOnError=True):
        return self.run(['hg', '-q', '-R', vcdir, 'add', path]) == 0

    def commit(self, vcdir, msg, abortOnError=True):
        return self.run(['hg', '-R', vcdir, 'commit', '-m', msg]) == 0

    def tip(self, vcdir, abortOnError=True):
        self.check_for_hg()
        # We don't use run because this can be called very early before _opts is set
        try:
            return subprocess.check_output(['hg', 'tip', '-R', vcdir, '--template', '{node}'])
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('hg tip failed')
            else:
                return None

    def parent(self, vcdir, abortOnError=True):
        self.check_for_hg()
        # We don't use run because this can be called very early before _opts is set
        try:
            out = subprocess.check_output(['hg', '-R', vcdir, 'parents', '--template', '{node}\n'])
            parents = out.rstrip('\n').split('\n')
            if len(parents) != 1:
                if abortOnError:
                    abort('hg parents returned {} parents (expected 1)'.format(len(parents)))
                return None
            return parents[0]
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('hg parents failed')
            else:
                return None

    def release_version_from_tags(self, vcdir, prefix, snapshotSuffix='dev', abortOnError=True):
        prefix = prefix + '-'
        try:
            tagged_ids_out = subprocess.check_output(['hg', '-R', vcdir, 'log', '--rev', 'ancestors(.) and tag("re:{0}[0-9]+\\.[0-9]+")'.format(prefix), '--template', '{tags},{rev}\n'])
            tagged_ids = [x.split(',') for x in tagged_ids_out.split('\n') if x]
            current_id = subprocess.check_output(['hg', '-R', vcdir, 'log', '--template', '{rev}\n', '--rev', '.']).strip()
        except subprocess.CalledProcessError as e:
            if abortOnError:
                abort('hg tags or hg tip failed: ' + str(e))
            else:
                return None

        if tagged_ids and current_id:
            def single(it):
                v = next(it)
                try:
                    next(it)
                    abort('iterator contained more than a single element')
                except StopIteration:
                    return v
            tagged_ids = [(single((tag for tag in tags.split(' ') if tag.startswith(prefix))), revid) for tags, revid in tagged_ids]
            version_ids = [([int(x) for x in tag[len(prefix):].split('.')], revid) for tag, revid in tagged_ids]
            version_ids = sorted(version_ids, key=lambda e: e[0], reverse=True)
            most_recent_tag_version, most_recent_tag_id = version_ids[0]

            if current_id == most_recent_tag_id:
                return '.'.join((str(e) for e in most_recent_tag_version))
            else:
                major, minor = most_recent_tag_version
                return str(major) + '.' + str(minor + 1) + '-' + snapshotSuffix
        return None

    def metadir(self):
        return '.hg'

    def clone(self, url, dest=None, rev=None, abortOnError=True, **extra_args):
        cmd = ['hg', 'clone']
        if rev:
            cmd.append('-r')
            cmd.append(rev)
        cmd.append(url)
        if dest:
            cmd.append(dest)
        self._log_clone(url, dest, rev)
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def incoming(self, vcdir, abortOnError=True):
        out = OutputCapture()
        rc = self.run(['hg', '-R', vcdir, 'incoming'], nonZeroIsFatal=False, out=out)
        if rc == 0 or rc == 1:
            return out.data
        else:
            if abortOnError:
                abort('incoming returned ' + str(rc))
            return None

    def outgoing(self, vcdir, dest=None, abortOnError=True):
        out = OutputCapture()
        cmd = ['hg', '-R', vcdir, 'outgoing']
        if dest:
            cmd.append(dest)
        rc = self.run(cmd, nonZeroIsFatal=False, out=out)
        if rc == 0 or rc == 1:
            return out.data
        else:
            if abortOnError:
                abort('outgoing returned ' + str(rc))
            return None

    def pull(self, vcdir, rev=None, update=False, abortOnError=True):
        cmd = ['hg', 'pull', '-R', vcdir]
        if rev:
            cmd.append('-r')
            cmd.append(rev)
        if update:
            cmd.append('-u')
        self._log_pull(vcdir, rev)
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def can_push(self, vcdir, strict=True, abortOnError=True):
        out = OutputCapture()
        rc = self.run(['hg', '-R', vcdir, 'status'], nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            output = out.data
            if strict:
                return output == ''
            else:
                if len(output) > 0:
                    for line in output.split('\n'):
                        if len(line) > 0 and not line.startswith('?'):
                            return False
                return True
        else:
            return False

    def _path(self, vcdir, name, abortOnError=True):
        out = OutputCapture()
        rc = self.run(['hg', '-R', vcdir, 'paths'], nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            output = out.data
            prefix = name + ' = '
            for line in output.split(os.linesep):
                if line.startswith(prefix):
                    return line[len(prefix):]
        if abortOnError:
            abort("no '{}' path for repository {}".format(name, vcdir))
        return None

    def default_push(self, vcdir, abortOnError=True):
        push = self._path(vcdir, 'default-push', abortOnError=False)
        if push:
            return push
        return self.default_pull(vcdir, abortOnError=abortOnError)

    def default_pull(self, vcdir, abortOnError=True):
        return self._path(vcdir, 'default', abortOnError=abortOnError)

    def push(self, vcdir, dest=None, rev=None, abortOnError=False):
        cmd = ['hg', '-R', vcdir, 'push']
        if rev:
            cmd.append('-r')
            cmd.append(rev)
        if dest:
            cmd.append(dest)
        self._log_push(vcdir, dest, rev)
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def update(self, vcdir, rev=None, mayPull=False, clean=False, abortOnError=False):
        if rev and mayPull and not self.exists(vcdir, rev):
            self.pull(vcdir, rev=rev, update=False, abortOnError=abortOnError)
        cmd = ['hg', '-R', vcdir, 'update']
        if rev:
            cmd += ['-r', rev]
        if clean:
            cmd += ['-C']
        return self.run(cmd, nonZeroIsFatal=abortOnError) == 0

    def locate(self, vcdir, patterns=None, abortOnError=True):
        if patterns is None:
            patterns = []
        elif not isinstance(patterns, list):
            patterns = [patterns]
        out = LinesOutputCapture()
        rc = self.run(['hg', 'locate', '-R', vcdir] + patterns, out=out, nonZeroIsFatal=False)
        if rc == 1:
            # hg locate returns 1 if no matches were found
            return []
        elif rc == 0:
            return out.lines
        else:
            if abortOnError:
                abort('locate returned: ' + str(rc))
            else:
                return None

    def isDirty(self, vcdir, abortOnError=True):
        self.check_for_hg()
        try:
            return len(subprocess.check_output(['hg', 'status', '-q', '-R', vcdir])) > 0
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('failed to get status')
            else:
                return None

    def bookmark(self, vcdir, name, rev, abortOnError=True):
        ret = run(['hg', '-R', vcdir, 'bookmark', '-r', rev, '-i', '-f', name], nonZeroIsFatal=False)
        if ret != 0:
            logging = abort if abortOnError else warn
            logging("Failed to create bookmark {0} at revision {1} in {2}".format(name, rev, vcdir))

    def latest(self, vcdir, rev1, rev2, abortOnError=True):
        #hg log -r 'heads(ancestors(26030a079b91) and ancestors(6245feb71195))' --template '{node}\n'
        self.check_for_hg()
        try:
            revs = [rev1, rev2]
            revsetIntersectAncestors = ' or '.join(('ancestors({})'.format(rev) for rev in revs))
            revset = 'heads({})'.format(revsetIntersectAncestors)
            out = subprocess.check_output(['hg', '-R', vcdir, 'log', '-r', revset, '--template', '{node}\n'])
            parents = out.rstrip('\n').split('\n')
            if len(parents) != 1:
                if abortOnError:
                    abort('hg log returned {} possible latest (expected 1)'.format(len(parents)))
                return None
            return parents[0]
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('latest failed')
            else:
                return None

    def exists(self, vcdir, rev):
        self.check_for_hg()
        try:
            sentinel = 'exists'
            out = subprocess.check_output(['hg', '-R', vcdir, 'log', '-r', 'present({})'.format(rev), '--template', sentinel])
            return sentinel in out
        except subprocess.CalledProcessError:
            abort('exists failed')


class GitConfig(VC):
    """
    Encapsulates access to Git (git)
    """
    def __init__(self):
        VC.__init__(self, 'git', 'Git')
        self.missing = 'No Git executable found. You must install Git in order to proceed!'
        self.has_git = None

    def check(self, abortOnError=True):
        # Mercurial does lazy checking before use of the git command itself
        return self

    def check_for_git(self, abortOnError=True):
        if self.has_git is None:
            try:
                subprocess.check_output(['git', '--version'])
                self.has_git = True
            except OSError:
                self.has_git = False
                warn(self.missing)

        if not self.has_git:
            if abortOnError:
                abort(self.missing)
            else:
                warn(self.missing)

        return self if self.has_git else None

    def run(self, *args, **kwargs):
        # Ensure hg exists before executing the command
        self.check_for_git()
        return run(*args, **kwargs)

    def init(self, vcdir, abortOnError=True):
        return self.run(['git', 'init'], cwd=vcdir, nonZeroIsFatal=abortOnError) == 0

    def is_this_vc(self, vcdir):
        gitdir = join(vcdir, self.metadir())
        # check for existence to also cover git submodules
        return os.path.exists(gitdir)

    def git_command(self, vcdir, args, abortOnError=False, quiet=False):
        args = ['git'] + args
        if not quiet:
            print '{0}'.format(" ".join(args))
        out = OutputCapture()
        rc = self.run(args, cwd=vcdir, nonZeroIsFatal=False, out=out)
        if rc == 0 or rc == 1:
            return out.data
        else:
            if abortOnError:
                abort(" ".join(args) + ' returned ' + str(rc))
            return None

    def add(self, vcdir, path, abortOnError=True):
        # git add does not support quiet mode, so we capture the output instead ...
        out = OutputCapture()
        return self.run(['git', 'add', path], cwd=vcdir, out=out) == 0

    def commit(self, vcdir, msg, abortOnError=True):
        return self.run(['git', 'commit', '-a', '-m', msg], cwd=vcdir) == 0

    def tip(self, vcdir, abortOnError=True):
        """
        Get the most recent changeset for repo at :param:`vcdir`.

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and :param:`abortOnError`=False
        :rtype: str
        """
        self.check_for_git()
        # We don't use run because this can be called very early before _opts is set
        try:
            return subprocess.check_output(['git', 'rev-list', 'HEAD', '-1'], cwd=vcdir)
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('git rev-list HEAD failed')
            else:
                return None

    def parent(self, vcdir, abortOnError=True):
        """
        Get the parent changeset of the working directory for repo at :param:`vcdir`.

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and :param:`abortOnError`=False
        :rtype: str
        """
        self.check_for_git()
        # We don't use run because this can be called very early before _opts is set
        if exists(join(vcdir, self.metadir(), 'MERGE_HEAD')):
            if abortOnError:
                abort('More than one parent exist during merge')
            return None
        try:
            out = subprocess.check_output(['git', 'show', '--pretty=format:%H', "-s", 'HEAD'], cwd=vcdir)
            return out.strip()
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('git show failed')
            else:
                return None

    def _tags(self, vcdir, prefix, abortOnError=True):
        """
        Get the list of tags starting with :param:`prefix` in the repository at :param:`vcdir` that are ancestors
        of the current HEAD.

        :param str vcdir: a valid repository path
        :param str prefix: the prefix used to filter the tags
        :param bool abortOnError: if True abort on mx error
        :rtype: list of str
        """
        _tags_prefix = 'tag: '
        try:
            tags_out = subprocess.check_output(['git', 'log', '--simplify-by-decoration', '--pretty=format:%d', 'HEAD'], cwd=vcdir)
            tags_out = tags_out.strip()
            tags = []
            for line in tags_out.split('\n'):
                line = line.strip()
                if not line:
                    continue
                assert line.startswith('(') and line.endswith(')'), "Unexpected format: " + line
                search = _tags_prefix + prefix
                for decoration in line[1:-1].split(', '):
                    if decoration.startswith(search):
                        tags.append(decoration[len(_tags_prefix):])
            return tags
        except subprocess.CalledProcessError as e:
            if abortOnError:
                abort('git tag failed: ' + str(e))
            else:
                return None

    def _commitish_revision(self, vcdir, commitish, abortOnError=True):
        """
        Get the commit hash for a commit-ish specifier.

        :param str vcdir: a valid repository path
        :param str commitish: a commit-ish specifier
        :param bool abortOnError: if True abort on mx error
        :rtype: str
        """
        try:
            rev = subprocess.check_output(['git', 'show', '-s', '--format="%H"', commitish], cwd=vcdir)
            return rev.strip()
        except subprocess.CalledProcessError as e:
            if abortOnError:
                abort('git show failed: ' + str(e))
            else:
                return None

    def _latest_revision(self, vcdir, abortOnError=True):
        return self._commitish_revision(vcdir, 'HEAD', abortOnError=abortOnError)


    def release_version_from_tags(self, vcdir, prefix, snapshotSuffix='dev', abortOnError=True):
        """
        Returns a release version derived from VC tags that match the pattern <prefix>-<major>.<minor>
        or None if no such tags exist.

        :param str vcdir: a valid repository path
        :param str prefix: the prefix
        :param str snapshotSuffix: the snapshot suffix
        :param bool abortOnError: if True abort on mx error
        :return: a release version
        :rtype: str
        """
        tag_prefix = prefix + '-'
        matching_tags = self._tags(vcdir, tag_prefix, abortOnError=abortOnError)
        latest_rev = self._latest_revision(vcdir, abortOnError=abortOnError)
        if latest_rev and matching_tags:
            matching_versions = [[int(x) for x in tag[len(tag_prefix):].split('.')] for tag in matching_tags]
            matching_versions = sorted(matching_versions, reverse=True)
            most_recent_version = matching_versions[0]
            most_recent_tag = tag_prefix + '.'.join((str(x) for x in most_recent_version))
            most_recent_tag_revision = self._commitish_revision(vcdir, most_recent_tag)

            if latest_rev == most_recent_tag_revision:
                return most_recent_tag[len(tag_prefix):]
            else:
                major, minor = most_recent_version
                return '{0}.{1}-{2}'.format(major, minor  + 1, snapshotSuffix)
        return None

    def metadir(self):
        return '.git'

    def _clone(self, url, dest=None, abortOnError=True, **extra_args):
        cmd = ['git', 'clone']
        cmd.append(url)
        if dest:
            cmd.append(dest)
        self._log_clone(url, dest)
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def _reset_rev(self, rev, dest=None, abortOnError=True, **extra_args):
        cmd = ['git']
        cwd = None if dest is None else dest
        cmd.extend(['reset', '--hard', rev])
        out = OutputCapture()
        rc = self.run(cmd, nonZeroIsFatal=abortOnError, cwd=cwd, out=out)
        logvv(out.data)
        return rc == 0

    def clone(self, url, dest=None, rev=None, abortOnError=True, **extra_args):
        """
        Clone the repo at :param:`url` to :param:`dest` using :param:`rev`

        :param str url: the repository url
        :param str dest: the path to destination, if None the destination is
                         chosen by the vcs
        :param str rev: the desired revision, if None use tip
        :param dict extra_args: for subclass-specific information in/out
        :return: True if the operation is successful, False otherwise
        :rtype: bool
        """
        # TODO: speedup git clone
        # git clone git://source.winehq.org/git/wine.git ~/wine-git --depth 1
        # downsides: This parameter will have the effect of preventing you from
        # cloning it or fetching from it, and other repositories will be unable
        # to push to you, and you won't be able to push to other repositories.
        self._log_clone(url, dest, rev)
        success = self._clone(url, dest=dest, abortOnError=abortOnError, **extra_args)
        if success and rev:
            success = self._reset_rev(rev, dest=dest, abortOnError=abortOnError, **extra_args)
            if not success:
                #TODO: should the cloned repo be removed from disk if the reset op failed?
                log('reset revision failed, removing {0}'.format(dest))
                shutil.rmtree(os.path.abspath(dest))
        return success

    def _fetch(self, vcdir, abortOnError=True):
        try:
            return subprocess.check_call(['git', 'fetch'], cwd=vcdir)
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('git fetch failed')
            else:
                return None

    def _log_changes(self, vcdir, path=None, incoming=True, abortOnError=True):
        out = OutputCapture()
        cmd = ['git', 'log', '{0}origin/master{1}'.format(
                '..', '' if incoming else '', '..')]
        if path:
            cmd.extend(['--', path])
        rc = self.run(cmd, nonZeroIsFatal=False, cwd=vcdir, out=out)
        if rc == 0 or rc == 1:
            return out.data
        else:
            if abortOnError:
                abort('{0} returned {1}'.format(
                        'incoming' if incoming else 'outgoing', str(rc)))
            return None

    def _active_branch(self, vcdir, abortOnError=True):
        out = OutputCapture()
        cmd = ['git', 'branch']
        rc = self.run(cmd, nonZeroIsFatal=False, cwd=vcdir, out=out)
        if rc == 0:
            for line in out.data.splitlines():
                if line.strip().startswith('*'):
                    print line
                    return line.split()[1].strip()
        if abortOnError:
            abort('no active git branch found')
        return None

    def incoming(self, vcdir, abortOnError=True):
        """
        list incoming changesets

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and :param:`abortOnError`=False
        :rtype: str
        """
        rc = self._fetch(vcdir, abortOnError=abortOnError)
        if rc == 0:
            return self._log_changes(vcdir, incoming=True, abortOnError=abortOnError)
        else:
            if abortOnError:
                abort('incoming returned ' + str(rc))
            return None

    def outgoing(self, vcdir, dest=None, abortOnError=True):
        """
        llist outgoing changesets to 'dest' or default-push if None

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: most recent changeset for specified repository,
                 None if failure and :param:`abortOnError`=False
        :rtype: str
        """
        rc = self._fetch(vcdir, abortOnError=abortOnError)
        if rc == 0:
            return self._log_changes(vcdir, path=dest, incoming=False, abortOnError=abortOnError)
        else:
            if abortOnError:
                abort('outgoing returned ' + str(rc))
            return None

    def pull(self, vcdir, rev=None, update=False, abortOnError=True):
        """
        Pull a given changeset (the head if `rev` is None), optionally updating
        the working directory. Updating is only done if something was pulled.
        If there were no new changesets or `rev` was already known locally,
        no update is performed.

        :param str vcdir: a valid repository path
        :param str rev: the desired revision, if None use tip
        :param bool abortOnError: if True abort on mx error
        :return: True if the operation is successful, False otherwise
        :rtype: bool
        """
        if update and not rev:
            active_branch = self._active_branch(vcdir, abortOnError)
            cmd = ['git', 'pull', 'origin', 'HEAD:{0}'.format(active_branch)]
            self._log_pull(vcdir, rev)
            out = OutputCapture()
            rc = self.run(cmd, nonZeroIsFatal=abortOnError, cwd=vcdir, out=out)
            logvv(out.data)
            return rc == 0
        else:
            rc = self._fetch(vcdir, abortOnError)
            if rc == 0:
                if rev and update:
                    return self.update(vcdir, rev=rev, mayPull=False, clean=False, abortOnError=abortOnError)
            else:
                if abortOnError:
                    abort('fetch returned ' + str(rc))
                return False

    def can_push(self, vcdir, strict=True, abortOnError=True):
        """
        Check if :param:`vcdir` can be pushed.

        :param str vcdir: a valid repository path
        :param bool strict: if set no uncommitted changes or unadded are allowed
        :return: True if we can push, False otherwise
        :rtype: bool
        """
        out = OutputCapture()
        rc = self.run(['git', 'status', '--porcelain'], cwd=vcdir, nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            output = out.data
            if strict:
                return output == ''
            else:
                if len(output) > 0:
                    for line in output.split('\n'):
                        if len(line) > 0 and not line.startswith('??'):
                            return False
                return True
        else:
            return False

    def _path(self, vcdir, name, abortOnError=True):
        out = OutputCapture()
        rc = self.run(['git', 'remote', '-v'], cwd=vcdir, nonZeroIsFatal=abortOnError, out=out)
        if rc == 0:
            output = out.data
            suffix = '({0})'.format(name)
            for line in output.split(os.linesep):
                if line.strip().endswith(suffix):
                    return line.split()[1]
        if abortOnError:
            abort("no '{0}' path for repository {1}".format(name, vcdir))
        return None

    def default_push(self, vcdir, abortOnError=True):
        """
        get the default push target for this repo

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: default push target for repo
        :rtype: str
        """
        push = self._path(vcdir, 'push', abortOnError=False)
        if push:
            return push
        return self.default_pull(vcdir, abortOnError=abortOnError)

    def default_pull(self, vcdir, abortOnError=True):
        """
        get the default pull target for this repo

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: default pull target for repo
        :rtype: str
        """
        return self._path(vcdir, 'fetch', abortOnError=abortOnError)

    def push(self, vcdir, dest=None, rev=None, abortOnError=False):
        """
        Push :param:`vcdir` at rev :param:`rev` to default if :param:`dest`
        is None, else push to :param:`dest`.

        :param str vcdir: a valid repository path
        :param str rev: the desired revision
        :param str dest: the path to destination
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        cmd = ['git', 'push']
        cmd.append(dest if dest else 'origin')
        cmd.append('{0}master'.format('{0}:'.format(rev) if rev else ''))
        self._log_push(vcdir, dest, rev)
        out = OutputCapture()
        rc = self.run(cmd, cwd=vcdir, nonZeroIsFatal=abortOnError, out=out)
        logvv(out.data)
        return rc == 0

    def update(self, vcdir, rev=None, mayPull=False, clean=False, abortOnError=False):
        """
        update the :param:`vcdir` working directory.
        If :param:`rev` is not specified, update to the tip of the current branch.
        If :param:`rev` is specified, `mayPull` controls whether a pull will be attempted if
        :param:`rev` can not be found locally.
        If :param:`clean` is True, uncommitted changes will be discarded (no backup!).

        :param str vcdir: a valid repository path
        :param str rev: the desired revision
        :param bool mayPull: flag to controll whether to pull or not
        :param bool clean: discard uncommitted changes without backing up
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        if rev and mayPull and not self.exists(vcdir, rev):
            self.pull(vcdir, rev=rev, update=False, abortOnError=abortOnError)
        cmd = ['git', 'checkout']
        if rev:
            cmd.extend(['--detach', rev])
            if not _opts.verbose:
                cmd.append('-q')
        else:
            cmd.extend(['master'])
        if clean:
            cmd.append('-f')
        return self.run(cmd, cwd=vcdir, nonZeroIsFatal=abortOnError) == 0

    def locate(self, vcdir, patterns=None, abortOnError=True):
        """
        Return a list of paths under vc control that match :param:`patterns`

        :param str vcdir: a valid repository path
        :param patterns: a list of patterns
        :type patterns: str or list or None
        :param bool abortOnError: if True abort on mx error
        :return: a list of paths under vc control
        :rtype: list
        """
        if patterns is None:
            patterns = []
        elif not isinstance(patterns, list):
            patterns = [patterns]
        patterns = ['"{0}"'.format(pattern) for pattern in patterns]
        out = LinesOutputCapture()
        rc = self.run(['git', 'ls-files'] + patterns, cwd=vcdir, out=out, nonZeroIsFatal=False)
        if rc == 0:
            return out.lines
        else:
            if abortOnError:
                abort('locate returned: ' + str(rc))
            else:
                return None

    def isDirty(self, vcdir, abortOnError=True):
        """
        check whether the working directory is dirty

        :param str vcdir: a valid repository path
        :param bool abortOnError: if True abort on mx error
        :return: True of the working directory is dirty, False otherwise
        :rtype: bool
        """
        self.check_for_git()
        try:
            output = subprocess.check_output(['git', 'status', '--porcelain'], cwd=vcdir)
            return len(output.strip()) > 0
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('failed to get status')
            else:
                return None

    def bookmark(self, vcdir, name, rev, abortOnError=True):
        """
        Place a bookmark at a given revision

        :param str vcdir: a valid repository path
        :param str name: the name of the bookmark
        :param str rev: the desired revision
        :param bool abortOnError: if True abort on mx error
        :return: True on success, False otherwise
        :rtype: bool
        """
        return run(['git', 'branch', '-f', name, rev], cwd=vcdir, nonZeroIsFatal=abortOnError) == 0

    def latest(self, vcdir, rev1, rev2, abortOnError=True):
        """
        Returns the latest of 2 revisions (in chronological order).
        The revisions should be related in the DAG.

        :param str vcdir: a valid repository path
        :param str rev1: the first revision
        :param str rev2: the second revision
        :param bool abortOnError: if True abort on mx error
        :return: the latest of the 2 revisions
        :rtype: str or None
        """
        self.check_for_git()
        try:
            out = subprocess.check_output(['git', 'rev-list', '-n', '1', '--date-order', rev1, rev2], cwd=vcdir)
            changesets = out.strip().split('\n')
            if len(changesets) != 1:
                if abortOnError:
                    abort('git rev-list returned {0} possible latest (expected 1)'.format(len(changesets)))
                return None
            return changesets[0]
        except subprocess.CalledProcessError:
            if abortOnError:
                abort('latest failed')
            else:
                return None

    def exists(self, vcdir, rev):
        """
        Check if a given revision exists in the repository.

        :param str vcdir: a valid repository path
        :param str rev: the second revision
        :return: True if revision exists, False otherwise
        :rtype: bool
        """
        self.check_for_git()
        try:
            out = subprocess.check_output(['git', 'show', '--format=oneline', '-s', rev], cwd=vcdir)
            return out.strip().startswith(rev)
        except subprocess.CalledProcessError:
            abort('exists failed')



class BinaryVC(VC):
    """
    Emulates a VC system for binary suites, as far as possible, but particularly pull/tip
    """
    def __init__(self):
        VC.__init__(self, 'binary', 'MX Binary')

    def check(self, abortOnError=True):
        return True

    def is_this_vc(self, vcdir):
        try:
            return self.parent(vcdir, abortOnError=False)
        except IOError:
            return False

    def clone(self, url, dest=None, rev=None, abortOnError=True, **extra_args):
        '''
        clone is interpreted as downloading the mx-suitename.jar file
        caller is responsible for downloading the suite distributions
        Some additional information must be passed by caller in 'extra_args':
          suite_name: the suite name
          result: an empty dict for output values
        On a successful return 'result' contains:
          adj_version: actual version (adjusted)
        The actual version downloaded is written to the file mx-suitename.jar.version
        '''
        assert dest
        suite_name = extra_args['suite_name']
        metadata = self.Metadata(suite_name, url, None)
        if not rev:
            rev = self._tip(metadata)
        metadata.snapshotVersion = '{0}-SNAPSHOT'.format(rev)

        mxname = _mx_binary_distribution_root(suite_name)
        self._log_clone("{}/{}/{}".format(url, _mavenGroupId(suite_name), mxname), dest, rev)
        mx_jar_path = join(dest, _mx_binary_distribution_jar(suite_name))
        self._pull_artifact(metadata, mxname, mxname, mx_jar_path)
        run([get_jdk(tag=DEFAULT_JDK_TAG).jar, 'xf', mx_jar_path], cwd=dest)
        self._writeMetadata(dest, metadata)
        return True

    def _pull_artifact(self, metadata, artifactId, name, path, sourcePath=None, abortOnVersionError=True, extension='jar'):
        groupId = _mavenGroupId(metadata.suiteName)
        repo = MavenRepo(metadata.repourl)
        snapshot = repo.getSnapshot(groupId, artifactId, metadata.snapshotVersion)
        if not snapshot:
            if abortOnVersionError:
                abort('Version {} not found for {}:{}'.format(metadata.snapshotVersion, groupId, artifactId))
            return False
        build = snapshot.getCurrentSnapshotBuild()
        try:
            (jar_url, jar_sha_url) = build.getSubArtifact(extension)
        except MavenSnapshotArtifact.NonUniqueSubArtifactException:
            abort('Multiple {}s found for {} in snapshot {} in repository {}'.format(extension, name, build.version, repo.repourl))
        download_file_with_sha1(artifactId, path, [jar_url], _hashFromUrl(jar_sha_url), path + '.sha1', resolve=True, mustExist=True, sources=False)
        if sourcePath:
            try:
                (source_url, source_sha_url) = build.getSubArtifactByClassifier('sources')
            except MavenSnapshotArtifact.NonUniqueSubArtifactException:
                abort('Multiple source artifacts found for {} in snapshot {} in repository {}'.format(name, build.version, repo.repourl))
            download_file_with_sha1(artifactId + ' sources', sourcePath, [source_url], _hashFromUrl(source_sha_url), sourcePath + '.sha1', resolve=True, mustExist=True, sources=True)
        return True

    class Metadata:
        def __init__(self, suiteName, repourl, snapshotVersion):
            self.suiteName = suiteName
            self.repourl = repourl
            self.snapshotVersion = snapshotVersion

    def _writeMetadata(self, vcdir, metadata):
        with open(join(vcdir, _mx_binary_distribution_version(metadata.suiteName)), 'w') as f:
            f.write("{0},{1}".format(metadata.repourl, metadata.snapshotVersion))

    def _readMetadata(self, vcdir):
        suiteName = basename(vcdir)
        with open(join(vcdir, _mx_binary_distribution_version(suiteName))) as f:
            repourl, snapshotVersion = f.read().split(',')
        return self.Metadata(suiteName, repourl, snapshotVersion)

    def getDistribution(self, vcdir, distribution):
        suiteName = basename(vcdir)
        if not distribution.needsUpdate(TimeStampFile(join(vcdir, _mx_binary_distribution_version(suiteName)), followSymlinks=False)):
            return
        metadata = self._readMetadata(vcdir)
        artifactId = _map_to_maven_dist_name(distribution.name)
        path = distribution.path[:-len(distribution.localExtension())] + distribution.remoteExtension()
        if distribution.isJARDistribution():
            sourcesPath = distribution.sourcesPath
        else:
            sourcesPath = None
        self._pull_artifact(metadata, artifactId, distribution.remoteName(), path, sourcePath=sourcesPath, extension=distribution.remoteExtension())
        distribution.postPull(path)
        distribution.notify_updated()

    def pull(self, vcdir, rev=None, update=True, abortOnError=True):
        if not update:
            return False  # TODO or True?
        metadata = self._readMetadata(vcdir)
        if rev == self._id(metadata):
            return True

        if not rev:
            rev = self._tip(metadata)

        artifactId = metadata.suiteName
        metadata.snapshotVersion = '{0}-SNAPSHOT'.format(rev)
        tmpdir = tempfile.mkdtemp()
        mxname = _mx_binary_distribution_root(metadata.suiteName)
        tmpmxjar = join(tmpdir, mxname + '.jar')
        if not self._pull_artifact(metadata, artifactId, mxname, tmpmxjar, abortOnVersionError=abortOnError):
            shutil.rmtree(tmpdir)
            return False

        # pull the new version and update 'working directory'
        # i.e. delete first as everything will change
        shutil.rmtree(vcdir)

        mx_jar_path = join(vcdir, _mx_binary_distribution_jar(metadata.suiteName))
        os.mkdir(dirname(mx_jar_path))

        shutil.copy2(tmpmxjar, mx_jar_path)
        shutil.rmtree(tmpdir)
        run([get_jdk(tag=DEFAULT_JDK_TAG).jar, 'xf', mx_jar_path], cwd=vcdir)

        self._writeMetadata(vcdir, metadata)
        return True

    def tip(self, vcdir, abortOnError=True):
        self._tip(self._readMetadata(vcdir))

    def _tip(self, metadata):
        repo = MavenRepo(metadata.repourl)
        latestSnapshotversion = repo.getArtifactVersions(_mavenGroupId(metadata.suiteName), _mx_binary_distribution_root(metadata.suiteName)).latestVersion
        assert latestSnapshotversion.endswith('-SNAPSHOT')
        return latestSnapshotversion[:-len('-SNAPSHOT')]

    def parent(self, vcdir, abortOnError=True):
        return self._id(self._readMetadata(vcdir))

    def _id(self, metadata):
        assert metadata.snapshotVersion.endswith('-SNAPSHOT')
        return metadata.snapshotVersion[:-len('-SNAPSHOT')]

def _hashFromUrl(url):
    logvv('Retrieving SHA1 from {}'.format(url))
    hashFile = urllib2.urlopen(url)
    try:
        return hashFile.read()
    except urllib2.URLError as e:
        abort('Error while retrieving sha1 {0}: {2}'.format(url, str(e)))
    finally:
        if hashFile:
            hashFile.close()

def _map_to_maven_dist_name(name):
    return name.lower().replace('_', '-')

class MavenArtifactVersions:
    def __init__(self, latestVersion, releaseVersion, versions):
        self.latestVersion = latestVersion
        self.releaseVersion = releaseVersion
        self.versions = versions

class MavenSnapshotBuilds:
    def __init__(self, currentTime, currentBuildNumber, snapshots):
        self.currentTime = currentTime
        self.currentBuildNumber = currentBuildNumber
        self.snapshots = snapshots

    def getCurrentSnapshotBuild(self):
        return self.snapshots[(self.currentTime, self.currentBuildNumber)]

class MavenSnapshotArtifact:
    def __init__(self, groupId, artifactId, version, snapshotBuildVersion, repo):
        self.groupId = groupId
        self.artifactId = artifactId
        self.version = version
        self.snapshotBuildVersion = snapshotBuildVersion
        self.subArtifacts = []
        self.repo = repo

    class SubArtifact:
        def __init__(self, extension, classifier):
            self.extension = extension
            self.classifier = classifier

        def __repr__(self):
            return str(self)

        def __str__(self):
            return "{0}.{1}".format(self.classifier, self.extension) if self.classifier else self.extension

    def addSubArtifact(self, extension, classifier):
        self.subArtifacts.append(self.SubArtifact(extension, classifier))

    class NonUniqueSubArtifactException(Exception):
        pass

    def _getUniqueSubArtifact(self, criterion):
        filtered = [sub for sub in self.subArtifacts if criterion(sub.extension, sub.classifier)]
        if len(filtered) == 0:
            return None
        if len(filtered) > 1:
            raise self.NonUniqueSubArtifactException()
        sub = filtered[0]
        if sub.classifier:
            url = "{url}/{group}/{artifact}/{version}/{artifact}-{snapshotBuildVersion}-{classifier}.{extension}".format(
                url=self.repo.repourl,
                group=self.groupId.replace('.', '/'),
                artifact=self.artifactId,
                version=self.version,
                snapshotBuildVersion=self.snapshotBuildVersion,
                classifier=sub.classifier,
                extension=sub.extension)
        else:
            url = "{url}/{group}/{artifact}/{version}/{artifact}-{snapshotBuildVersion}.{extension}".format(
                url=self.repo.repourl,
                group=self.groupId.replace('.', '/'),
                artifact=self.artifactId,
                version=self.version,
                snapshotBuildVersion=self.snapshotBuildVersion,
                extension=sub.extension)
        return (url, url + '.sha1')

    def getSubArtifact(self, extension, classifier=None):
        return self._getUniqueSubArtifact(lambda e, c: e == extension and c == classifier)

    def getSubArtifactByClassifier(self, classifier):
        return self._getUniqueSubArtifact(lambda e, c: c == classifier)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "{0}:{1}:{2}-SNAPSHOT".format(self.groupId, self.artifactId, self.snapshotBuildVersion)

class MavenRepo:
    def __init__(self, repourl):
        self.repourl = repourl
        self.artifactDescs = {}

    def getArtifactVersions(self, groupId, artifactId):
        metadataUrl = "{0}/{1}/{2}/maven-metadata.xml".format(self.repourl, groupId.replace('.', '/'), artifactId)
        logv('Retreiving and parsing {0}'.format(metadataUrl))
        try:
            metadataFile = urllib2.urlopen(metadataUrl)
        except urllib2.HTTPError as e:
            abort('Error while retreiving metadata for {}:{}: {}'.format(groupId, artifactId, str(e)))
        try:
            tree = etreeParse(metadataFile)
            root = tree.getroot()
            assert root.tag == 'metadata'
            assert root.find('groupId').text == groupId
            assert root.find('artifactId').text == artifactId

            versioning = root.find('versioning')
            latest = versioning.find('latest')
            release = versioning.find('release')
            versions = versioning.find('versions')
            releaseVersionString = release.text if release else None
            latestVersionString = latest.text
            versionStrings = [v.text for v in versions.iter('version')]

            return MavenArtifactVersions(latestVersionString, releaseVersionString, versionStrings)
        except urllib2.URLError as e:
            abort('Error while retreiving versions for {0}:{1}: {2}'.format(groupId, artifactId, str(e)))
        finally:
            if metadataFile:
                metadataFile.close()

    def getSnapshot(self, groupId, artifactId, version):
        assert version.endswith('-SNAPSHOT')
        metadataUrl = "{0}/{1}/{2}/{3}/maven-metadata.xml".format(self.repourl, groupId.replace('.', '/'), artifactId, version)
        logv('Retreiving and parsing {0}'.format(metadataUrl))
        try:
            metadataFile = urllib2.urlopen(metadataUrl)
        except urllib2.URLError as e:
            if e.code == 404:
                return None
            abort('Error while retreiving snappshot for {}:{}:{}: {}'.format(groupId, artifactId, version, str(e)))
        try:
            tree = etreeParse(metadataFile)
            root = tree.getroot()
            assert root.tag == 'metadata'
            assert root.find('groupId').text == groupId
            assert root.find('artifactId').text == artifactId
            assert root.find('version').text == version

            versioning = root.find('versioning')
            snapshot = versioning.find('snapshot')
            snapshotVersions = versioning.find('snapshotVersions')
            currentSnapshotTime = snapshot.find('timestamp').text
            currentSnapshotBuildElement = snapshot.find('buildNumber')
            currentSnapshotBuildNumber = int(currentSnapshotBuildElement.text) if currentSnapshotBuildElement is not None else 0

            versionPrefix = version[:-len('-SNAPSHOT')] + '-'
            prefixLen = len(versionPrefix)
            snapshots = {}
            for snapshotVersion in snapshotVersions.iter('snapshotVersion'):
                fullVersion = snapshotVersion.find('value').text
                separatorIndex = fullVersion.index('-', prefixLen)
                timeStamp = fullVersion[prefixLen:separatorIndex]
                buildNumber = int(fullVersion[separatorIndex+1:])
                extension = snapshotVersion.find('extension').text
                classifier = snapshotVersion.find('classifier')
                classifierString = None
                if classifier is not None and len(classifier.text) > 0:
                    classifierString = classifier.text
                artifact = snapshots.setdefault((timeStamp, buildNumber), MavenSnapshotArtifact(groupId, artifactId, version, fullVersion, self))

                artifact.addSubArtifact(extension, classifierString)
            return MavenSnapshotBuilds(currentSnapshotTime, currentSnapshotBuildNumber, snapshots)
        finally:
            if metadataFile:
                metadataFile.close()

class Repository(SuiteConstituent):
    """A Repository is a remote binary repository that can be used to upload binaries with deploy_binary."""
    def __init__(self, suite, name, url, licenses):
        SuiteConstituent.__init__(self, suite, name)
        self.url = url
        self.licenses = licenses

    def __eq__(self, other):
        if not isinstance(other, Repository):
            return False
        if self.name != other.name or self.url != other.url:
            return False
        if len(self.licenses) != len(other.licenses):
            return False
        # accept revolved and unresolved licenses
        for a, b in zip(self.licenses, other.licenses):
            if isinstance(a, License):
                a = a.name
            if isinstance(b, License):
                b = b.name
            if a != b:
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def resolveLicenses(self):
        self.licenses = [get_license(l) for l in self.licenses]

def _mavenGroupId(suite):
    if isinstance(suite, Suite):
        name = suite.name
    else:
        assert isinstance(suite, types.StringTypes)
        name = suite
    return 'com.oracle.' + _map_to_maven_dist_name(name)

def _genPom(dist, versionGetter, validateMetadata='none'):
    groupId = dist.maven_group_id()
    artifactId = dist.maven_artifact_id()
    version = versionGetter(dist.suite)
    pom = XMLDoc()
    pom.open('project', attributes={
        'xmlns': "http://maven.apache.org/POM/4.0.0",
        'xmlns:xsi': "http://www.w3.org/2001/XMLSchema-instance",
        'xsi:schemaLocation': "http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd"
        })
    pom.element('modelVersion', data="4.0.0")
    pom.element('groupId', data=groupId)
    pom.element('artifactId', data=artifactId)
    pom.element('version', data=version)
    if dist.suite.url:
        pom.element('url', data=dist.suite.url)
    elif validateMetadata != 'none':
        if 'suite-url' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            abort("Suite {} is missing the 'url' attribute".format(dist.suite.name))
        warn("Suite {}'s  version is too old to contain the 'url' attribute".format(dist.suite.name))
    acronyms = ['API', 'DSL', 'SL', 'TCK']
    name = ' '.join((t if t in acronyms else t.lower().capitalize() for t in dist.name.split('_')))
    pom.element('name', data=name)
    if hasattr(dist, 'description'):
        pom.element('description', data=dist.description)
    elif validateMetadata != 'none':
        if 'dist-description' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            dist.abort("Distribution is missing the 'description' attribute")
        dist.warn("Distribution's suite version is too old to have the 'description' attribute")
    if dist.suite.developer:
        pom.open('developers')
        pom.open('developer')
        def _addDevAttr(name, default=None):
            if name in dist.suite.developer:
                value = dist.suite.developer[name]
            else:
                value = default
            if value:
                pom.element(name, data=value)
            elif validateMetadata != 'none':
                abort("Suite {}'s developer metadata is missing the '{}' attribute".format(dist.suite.name, name))
        _addDevAttr('name')
        _addDevAttr('email')
        _addDevAttr('organization')
        _addDevAttr('organizationUrl', dist.suite.url)
        pom.close('developer')
        pom.close('developers')
    elif validateMetadata != 'none':
        if 'suite-developer' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
            abort("Suite {} is missing the 'developer' attribute".format(dist.suite.name))
        warn("Suite {}'s version is too old to contain the 'developer' attribute".format(dist.suite.name))
    if dist.theLicense:
        pom.open('licenses')
        pom.open('license')
        pom.element('name', data=dist.theLicense.fullname)
        pom.element('url', data=dist.theLicense.url)
        pom.close('license')
        pom.close('licenses')
    elif validateMetadata != 'none':
        if dist.suite.getMxCompatibility().supportsLicenses() or validateMetadata == 'full':
            dist.abort("Distribution is missing 'license' attribute")
        dist.warn("Distribution's suite version is too old to have the 'license' attribute")
    directDistDeps = [d for d in dist.deps if d.isDistribution()]
    directLibDeps = dist.excludedLibs
    if directDistDeps or directLibDeps:
        pom.open('dependencies')
        for dep in directDistDeps:
            pom.open('dependency')
            depGroupId = _mavenGroupId(dep.suite)
            depArtifactId = _map_to_maven_dist_name(dep.remoteName())
            depVersion = versionGetter(dep.suite)
            pom.element('groupId', data=depGroupId)
            pom.element('artifactId', data=depArtifactId)
            pom.element('version', data=depVersion)
            pom.close('dependency')
        for l in directLibDeps:
            if hasattr(l, 'maven'):
                mavenMetaData = l.maven
                pom.open('dependency')
                pom.element('groupId', data=mavenMetaData['groupId'])
                pom.element('artifactId', data=mavenMetaData['artifactId'])
                pom.element('version', data=mavenMetaData['version'])
                pom.close('dependency')
            elif validateMetadata != 'none':
                if 'library-coordinates' in dist.suite.getMxCompatibility().supportedMavenMetadata() or validateMetadata == 'full':
                    l.abort("Library is missing maven metadata")
                l.warn("Library's suite version is too old to have maven metadata")
        pom.close('dependencies')
    pom.open('scm')
    scm = dist.suite.scm_metadata(abortOnError=validateMetadata != 'none')
    pom.element('connection', data='scm:{}:{}'.format(dist.suite.vc.kind, scm.read))
    if scm.read != scm.write or validateMetadata == 'full':
        pom.element('developerConnection', data='scm:{}:{}'.format(dist.suite.vc.kind, scm.write))
    pom.element('url', data=scm.url)
    pom.close('scm')
    pom.close('project')
    return pom.xml(indent='  ', newl='\n')

def _tmpPomFile(dist, versionGetter, validateMetadata='none'):
    tmp = tempfile.NamedTemporaryFile('w', suffix='.pom', delete=False)
    tmp.write(_genPom(dist, versionGetter, validateMetadata))
    tmp.close()
    return tmp.name

def _deploy_binary_maven(suite, artifactId, groupId, jarPath, version, repositoryId, repositoryUrl, srcPath=None, description=None, settingsXml=None, extension='jar', dryRun=False, pomFile=None, gpg=False, keyid=None, javadocPath=None):
    assert exists(jarPath)
    assert not srcPath or exists(srcPath)

    cmd = ['--batch-mode']

    if not _opts.verbose:
        cmd.append('--quiet')

    if _opts.very_verbose:
        cmd.append('--debug')

    if settingsXml:
        cmd += ['-s', settingsXml]

    if gpg:
        cmd += ['gpg:sign-and-deploy-file']
    else:
        cmd += ['deploy:deploy-file']

    if keyid:
        cmd += ['-Dgpg.keyname=' + keyid]

    cmd += ['-DrepositoryId=' + repositoryId,
        '-Durl=' + repositoryUrl,
        '-DgroupId=' + groupId,
        '-DartifactId=' + artifactId,
        '-Dversion=' + version,
        '-Dfile=' + jarPath,
        '-Dpackaging=' + extension
    ]
    if pomFile:
        cmd.append('-DpomFile=' + pomFile)
    else:
        cmd.append('-DgeneratePom=true')

    if srcPath:
        cmd.append('-Dsources=' + srcPath)
    if javadocPath:
        cmd.append('-Djavadoc=' + javadocPath)

    if description:
        cmd.append('-Ddescription=' + description)

    log('Deploying {0}:{1}...'.format(groupId, artifactId))
    if dryRun:
        log(' '.join((pipes.quote(t) for t in cmd)))
    else:
        run_maven(cmd)

def deploy_binary(args):
    """deploy binaries for the primary suite to remote maven repository.

    All binaries must be built first using 'mx build'.

    usage: mx deploy-binary [-h] [-s SETTINGS] [-n] [--only ONLY] repository

    positional arguments:
      repository            Repository name used for Maven deploy (must be defined
                            in a suite.py file)

    optional arguments:
      -h, --help            show this help message and exit
      -s SETTINGS, --settings SETTINGS
                            Path to settings.mxl file used for Maven
      -n, --dry-run         Dry run that only prints the action a normal run would
                            perform without actually deploying anything
      --only ONLY           Limit deployment to these distributions
    """
    parser = ArgumentParser(prog='mx deploy-binary')
    parser.add_argument('-s', '--settings', action='store', help='Path to settings.mxl file used for Maven')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Dry run that only prints the action a normal run would perform without actually deploying anything')
    parser.add_argument('--only', action='store', help='Limit deployment to these distributions')
    parser.add_argument('repository', action='store', help='Repository name used for Maven deploy (must be defined in a suite.py file)')
    args = parser.parse_args(args)

    s = _primary_suite
    if not s.getMxCompatibility().supportsLicenses():
        log("Not deploying '{0}' because licenses aren't defined".format(s.name))
        return
    if not s.getMxCompatibility().supportsRepositories():
        log("Not deploying '{0}' because repositories aren't defined".format(s.name))
        return
    if not s.vc:
        abort('Current prinary suite has no version control')
    _mvn.check()
    def _versionGetter(suite):
        return '{0}-SNAPSHOT'.format(suite.vc.parent(suite.dir))
    dists = s.dists
    if args.only:
        only = args.only.split(',')
        dists = [d for d in dists if d.name in only]

    mxMetaName = _mx_binary_distribution_root(s.name)
    s.create_mx_binary_distribution_jar()
    mxMetaJar = s.mx_binary_distribution_jar_path()
    assert exists(mxMetaJar)
    for dist in dists:
        if not dist.exists():
            abort("'{0}' is not built, run 'mx build' first".format(dist.name))


    repo = repository(args.repository)

    version = _versionGetter(s)
    log('Deploying {0} distributions for version {1}'.format(s.name, version))
    _deploy_binary_maven(s, _map_to_maven_dist_name(mxMetaName), _mavenGroupId(s), mxMetaJar, version, repo.name, repo.url, settingsXml=args.settings, dryRun=args.dry_run)
    _maven_deploy_dists(dists, _versionGetter, repo.name, repo.url, args.settings, dryRun=args.dry_run, licenses=repo.licenses)

def _maven_deploy_dists(dists, versionGetter, repository_id, url, settingsXml, dryRun=False, validateMetadata='none', licenses=None, gpg=False, keyid=None, generateJavadoc=False):
    if licenses is None:
        licenses = []
    for dist in dists:
        if dist.theLicense not in licenses:
            distLicense = dist.theLicense.name if dist.theLicense else '??'
            abort('Distribution with {} license are not cleared for upload to {}: can not upload {}'.format(distLicense, repository_id, dist.name))
    for dist in dists:
        if dist.isJARDistribution():
            pomFile = _tmpPomFile(dist, versionGetter, validateMetadata)
            if _opts.very_verbose or (dryRun and _opts.verbose):
                with open(pomFile) as f:
                    log(f.read())
            javadocPath = None
            if generateJavadoc:
                projects = [p for p in dist.archived_deps() if p.isJavaProject()]
                tmpDir = tempfile.mkdtemp(prefix='mx-javadoc')
                javadocArgs = ['--base', tmpDir, '--unified', '--projects', ','.join((p.name for p in projects))]
                if dist.javadocType == 'implementation':
                    javadocArgs += ['--implementation']
                else:
                    assert dist.javadocType == 'api'
                if dist.allowsJavadocWarnings:
                    javadocArgs += ['--allow-warnings']
                javadoc(javadocArgs, includeDeps=False, mayBuild=False, quietForNoPackages=True)
                tmpJavadocJar = tempfile.NamedTemporaryFile('w', suffix='.jar', delete=False)
                tmpJavadocJar.close()
                javadocPath = tmpJavadocJar.name
                emptyJavadoc = True
                with zipfile.ZipFile(javadocPath, 'w') as arc:
                    javadocDir = join(tmpDir, 'javadoc')
                    for (dirpath, _, filenames) in os.walk(javadocDir):
                        for filename in filenames:
                            emptyJavadoc = False
                            src = join(dirpath, filename)
                            dst = os.path.relpath(src, javadocDir)
                            arc.write(src, dst)
                shutil.rmtree(tmpDir)
                if emptyJavadoc:
                    javadocPath = None
                    warn('Javadoc for {0} was empty'.format(dist.name))
            _deploy_binary_maven(dist.suite, dist.maven_artifact_id(), dist.maven_group_id(), dist.prePush(dist.path), versionGetter(dist.suite), repository_id, url, srcPath=dist.prePush(dist.sourcesPath), settingsXml=settingsXml, extension=dist.remoteExtension(),
                dryRun=dryRun, pomFile=pomFile, gpg=gpg, keyid=keyid, javadocPath=javadocPath)
            os.unlink(pomFile)
            if javadocPath:
                os.unlink(javadocPath)
        elif dist.isTARDistribution():
            _deploy_binary_maven(dist.suite, dist.maven_artifact_id(), dist.maven_group_id(), dist.prePush(dist.path), versionGetter(dist.suite), repository_id, url, settingsXml=settingsXml, extension=dist.remoteExtension(), dryRun=dryRun, gpg=gpg, keyid=keyid)
        else:
            warn('Unsupported distribution: ' + dist.name)

def maven_deploy(args):
    """deploy jars for the primary suite to remote maven repository.

    All binaries must be built first using 'mx build'.

    usage: mx maven-deploy [-h] [-s SETTINGS] [-n] [--only ONLY]
                           [--validate {none,compat,full}] [--licenses LICENSES]
                           repository-id [repository-url]

    positional arguments:
      repository-id         Repository ID used for Maven deploy
      repository-url        Repository URL used for Maven deploy, if no url is
                            given, the repository-id is looked up in suite.py

    optional arguments:
      -h, --help            show this help message and exit
      -s SETTINGS, --settings SETTINGS
                            Path to settings.mxl file used for Maven
      -n, --dry-run         Dry run that only prints the action a normal run would
                            perform without actually deploying anything
      --only ONLY           Limit deployment to these distributions
      --validate {none,compat,full}
                            Validate that maven metadata is complete enough for
                            publication
      --licenses LICENSES   Comma-separated list of licenses that are cleared for
                            upload. Only used if no url is given. Otherwise
                        licenses are looked up in suite.py
    """
    parser = ArgumentParser(prog='mx maven-deploy')
    parser.add_argument('-s', '--settings', action='store', help='Path to settings.mxl file used for Maven')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Dry run that only prints the action a normal run would perform without actually deploying anything')
    parser.add_argument('--only', action='store', help='Limit deployment to these distributions')
    parser.add_argument('--validate', help='Validate that maven metadata is complete enough for publication', default='compat', choices=['none', 'compat', 'full'])
    parser.add_argument('--licenses', help='Comma-separated list of licenses that are cleared for upload. Only used if no url is given. Otherwise licenses are looked up in suite.py', default='')
    parser.add_argument('--gpg', action='store_true', help='Sign files with gpg before deploying')
    parser.add_argument('--gpg-keyid', help='GPG keyid to use when signing files (implies --gpg)', default=None)
    parser.add_argument('repository_id', metavar='repository-id', action='store', help='Repository ID used for Maven deploy')
    parser.add_argument('url', metavar='repository-url', nargs='?', action='store', help='Repository URL used for Maven deploy, if no url is given, the repository-id is looked up in suite.py')
    args = parser.parse_args(args)

    if args.gpg_keyid and not args.gpg:
        args.gpg = True
        warn('Implicitely setting gpg to true since a keyid was specified')

    s = _primary_suite
    _mvn.check()
    def _versionGetter(suite):
        return suite.release_version(snapshotSuffix='SNAPSHOT')
    dists = [d for d in s.dists if d.maven]
    if args.only:
        only = args.only.split(',')
        dists = [d for d in dists if d.name in only]
    if not dists:
        abort("No distribution to deploy")

    for dist in dists:
        if not dist.exists():
            abort("'{0}' is not built, run 'mx build' first".format(dist.name))

    if args.url:
        licenses = [get_license(l) for l in args.licenses.split(',') if l]
        repo = Repository(None, args.repository_id, args.url, licenses)
    else:
        if not s.getMxCompatibility().supportsRepositories():
            abort("Repositories are not supported in {}'s suite version".format(s.name))
        repo = repository(args.repository_id)

    generateJavadoc = s.getMxCompatibility().mavenDeployJavadoc()

    log('Deploying {0} distributions for version {1}'.format(s.name, _versionGetter(s)))
    _maven_deploy_dists(dists, _versionGetter, repo.name, repo.url, args.settings, dryRun=args.dry_run, validateMetadata=args.validate, licenses=repo.licenses, gpg=args.gpg, keyid=args.gpg_keyid, generateJavadoc=generateJavadoc)

class MavenConfig:
    def __init__(self):
        self.has_maven = None
        self.missing = 'no mvn executable found'


    def check(self, abortOnError=True):
        if self.has_maven is None:
            try:
                run_maven(['--version'], out=lambda e: None)
                self.has_maven = True
            except OSError:
                self.has_maven = False
                warn(self.missing)

        if not self.has_maven:
            if abortOnError:
                abort(self.missing)
            else:
                warn(self.missing)

        return self if self.has_maven else None

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

    def _search_dir(self, searchDir, name):
        if not exists(searchDir):
            return None
        for dd in os.listdir(searchDir):
            sd = _is_suite_dir(join(searchDir, dd), _mxDirName(name))
            if sd is not None:
                return sd

    def _check_exists(self, suite_import, path, check_alternate=True):
        if check_alternate and self.kind == "src" and suite_import.urlinfos is not None and not exists(path):
            return suite_import.urlinfos
        return path

    @staticmethod
    def create_suitemodel(opts, kind):
        envKey = 'MX_' + kind.upper() + '_SUITEMODEL'
        optsKey = kind + '_suitemodel'
        default = os.environ.get(envKey, 'sibling')
        name = getattr(opts, optsKey) or default

        # Communicate the suite model to mx subprocesses
        os.environ[envKey] = name

        if name.startswith('sibling'):
            return SiblingSuiteModel(kind, _primary_suite_path, name)
        elif name.startswith('nested'):
            return NestedImportsSuiteModel(kind, _primary_suite_path, name)
        else:
            abort('unknown suitemodel type: ' + name)


class SiblingSuiteModel(SuiteModel):
    """All suites are siblings in the same parent directory, recorded as _suiteRootDir"""
    def __init__(self, kind, suiteRootDir, option):
        SuiteModel.__init__(self, kind)
        self._suiteRootDir = suiteRootDir

    def find_suite_dir(self, name):
        return self._search_dir(self._suiteRootDir, name)

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
    """Imported suites are all siblings in an 'mx.imports/source' directory of the primary suite"""
    def _imported_suites_dirname(self):
        return 'mx.imports/source'

    def __init__(self, kind, primaryDir, option):
        SuiteModel.__init__(self, kind)
        self._primaryDir = primaryDir

    def find_suite_dir(self, name):
        return self._search_dir(join(self._primaryDir, self._imported_suites_dirname()), name)

    def importee_dir(self, importer_dir, suite_import, check_alternate=True):
        suitename = suite_import.name
        if self.suitenamemap.has_key(suitename):
            suitename = self.suitenamemap[suitename]
        if basename(importer_dir) == basename(self._primaryDir):
            # primary is importer
            this_imported_suites_dirname = join(importer_dir, self._imported_suites_dirname())
            ensure_dir_exists(this_imported_suites_dirname)
            path = join(this_imported_suites_dirname, suitename)
        else:
            path = join(dirname(importer_dir), suitename)
        return self._check_exists(suite_import, path, check_alternate)

    def nestedsuites_dirname(self):
        return self._imported_suites_dirname()

'''
Captures the info in the {"url", "kind"} dict,
and adds a 'vc' field.
'''
class SuiteImportURLInfo:
    def __init__(self, url, kind, vc):
        self.url = url
        self.kind = kind
        self.vc = vc

    def abs_kind(self):
        ''' Maps vc kinds to 'source'
        '''
        return self.kind if self.kind == 'binary' else 'source'

class SuiteImport:
    def __init__(self, name, version, urlinfos, kind=None, dynamicImport=False):
        self.name = name
        self.version = version
        self.urlinfos = [] if urlinfos is None else urlinfos
        self.dynamicImport = dynamicImport
        self.kind = kind

    @staticmethod
    def parse_specification(import_dict, context, dynamicImport=False):
        name = import_dict.get('name')
        if not name:
            abort('suite import must have a "name" attribute', context=context)
        # missing defaults to the tip
        version = import_dict.get("version")
        urls = import_dict.get("urls")
        # urls a list of alternatives defined as dicts
        if not isinstance(urls, list):
            abort('suite import urls must be a list', context=context)
        urlinfos = []
        mainKind = None
        for urlinfo in urls:
            if isinstance(urlinfo, dict) and urlinfo.get('url') and urlinfo.get('kind'):
                kind = urlinfo.get('kind')
                if not VC.is_valid_kind(kind):
                    abort('suite import kind ' + kind + ' illegal', context=context)
            else:
                abort('suite import url must be a dict with {"url", kind", attributes', context=context)
            vc = vc_system(kind)
            if kind != 'binary':
                assert not mainKind or mainKind == kind, "Only expecting one non-binary kind"
                mainKind = kind
            urlinfos.append(SuiteImportURLInfo(urlinfo.get('url'), kind, vc))
        return SuiteImport(name, version, urlinfos, mainKind, dynamicImport=dynamicImport)

    @staticmethod
    def get_source_urls(source, kind=None):
        '''
        Returns a list of SourceImportURLInfo instances
        If source is a string (dir) determine kind, else search the list of
        urlinfos and return the values for source repos
        '''
        if isinstance(source, str):
            if kind:
                vc = vc_system(kind)
            else:
                assert not source.startswith("http:")
                vc = VC.get_vc(source)
            return [SuiteImportURLInfo(source, 'source', vc)]
        elif isinstance(source, list):
            result = [s for s in source if s.kind != 'binary']
            return result
        else:
            abort('unexpected type in SuiteImport.get_source_urls')

def _validate_abolute_url(urlstr, acceptNone=False):
    if urlstr is None:
        return acceptNone
    url = urlparse.urlsplit(urlstr)
    return url.scheme and url.netloc

class SCMMetadata(object):
    def __init__(self, url, read, write):
        self.url = url
        self.read = read
        self.write = write


'''
Command state and methods for all suite subclasses
'''
class Suite:
    def __init__(self, mxDir, primary, internal, importing_suite, dynamicallyImported=False):
        self.imported_by = [] if primary else [importing_suite]
        self.mxDir = mxDir
        self.dir = dirname(mxDir)
        self.name = _suitename(mxDir)
        self.primary = primary
        self.internal = internal
        self.libs = []
        self.jreLibs = []
        self.jdkLibs = []
        self.suite_imports = []
        self.extensions = None
        self.primary = primary
        self.requiredMxVersion = None
        self.dists = []
        self._metadata_initialized = False
        self.loading_imports = False
        self.post_init = False
        self.distTemplates = []
        self.licenseDefs = []
        self.repositoryDefs = []
        self.javacLintOverrides = []
        self.versionConflictResolution = 'none' if importing_suite is None else importing_suite.versionConflictResolution
        self.dynamicallyImported = dynamicallyImported
        self.scm = None
        _suites[self.name] = self
        self._outputRoot = None

    def __str__(self):
        return self.name

    def _load(self):
        '''
        Calls _load_env and _load_extensions
        '''
        # load suites depth first
        self.loading_imports = True
        self.visit_imports(self._find_and_loadsuite)
        self.loading_imports = False
        self._load_env()
        self._load_extensions()
        _loadedSuites.append(self)

    def getMxCompatibility(self):
        return mx_compat.getMxCompatibility(self.requiredMxVersion)

    def get_output_root(self):
        '''
        Gets the root of the directory hierarchy under which generated artifacts for this
        suite such as class files and annotation generated sources should be placed.
        '''
        if not self._outputRoot:
            suiteDict = self.suiteDict
            outputRoot = suiteDict.get('outputRoot')
            if outputRoot:
                self._outputRoot = os.path.realpath(_make_absolute(outputRoot.replace('/', os.sep), self.dir))
            else:
                self._outputRoot = self.getMxCompatibility().getSuiteOutputRoot(self)
        return self._outputRoot

    def get_mx_output_dir(self):
        '''
        Gets the directory into which mx bookkeeping artifacts should be placed.
        '''
        return join(self.get_output_root(), basename(self.mxDir))

    def _load_suite_dict(self):
        dictName = 'suite'

        def expand(value, context):
            if isinstance(value, types.DictionaryType):
                for n, v in value.iteritems():
                    value[n] = expand(v, context + [n])
            elif isinstance(value, types.ListType):
                for i in range(len(value)):
                    value[i] = expand(value[i], context + [str(i)])
            elif isinstance(value, types.StringTypes):
                value = expandvars(value)
                if '$' in value or '%' in value:
                    abort('value of ' + '.'.join(context) + ' contains an undefined environment variable: ' + value)
            elif isinstance(value, types.BooleanType):
                pass
            else:
                abort('value of ' + '.'.join(context) + ' is of unexpected type ' + str(type(value)))

            return value

        moduleName = 'suite'
        modulePath = join(self.mxDir, moduleName + '.py')
        if not exists(modulePath):
            abort('{} is missing'.format(modulePath))

        savedModule = sys.modules.get(moduleName)
        if savedModule:
            warn(modulePath + ' conflicts with ' + savedModule.__file__)
        # temporarily extend the Python path
        sys.path.insert(0, self.mxDir)

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
        supported = [
            'imports',
            'projects',
            'libraries',
            'jrelibraries',
            'jdklibraries',
            'distributions',
            'name',
            'outputRoot',
            'mxversion',
            'versionConflictResolution',
            'developer',
            'url',
            'licenses',
            'licences',
            'defaultLicense',
            'defaultLicence',
            'repositories',
            'javac.lint.overrides',
            'scm'
        ]

        if self.name == 'mx':
            self.requiredMxVersion = version
        elif d.has_key('mxversion'):
            try:
                self.requiredMxVersion = VersionSpec(d['mxversion'])
            except AssertionError as ae:
                abort('Exception while parsing "mxversion" in project file: ' + str(ae))

        if self.requiredMxVersion is None:
            self.requiredMxVersion = mx_compat.minVersion()
            warn("The {} suite does not express any required mx version. Assuming version {}. Consider adding 'mxversion=<version>' to your suite file ({}).".format(self.name, self.requiredMxVersion, self.suite_py()))
        elif self.requiredMxVersion > version:
            abort("The {} suite requires mx version {} while your current mx version is {}. Please update mx.".format(self.name, self.requiredMxVersion, version))
        if not self.getMxCompatibility():
            abort("The {} suite requires mx version {} while your version of mx only supports suite versions {} to {}.".format(self.name, self.requiredMxVersion, mx_compat.minVersion(), version))

        conflictResolution = d.get('versionConflictResolution')
        if conflictResolution:
            self.versionConflictResolution = conflictResolution

        javacLintOverrides = d.get('javac.lint.overrides', None)
        if javacLintOverrides:
            self.javacLintOverrides = javacLintOverrides.split(',')

        unknown = frozenset(d.keys()) - frozenset(supported)
        if unknown:
            abort(modulePath + ' defines unsupported suite attribute: ' + ', '.join(unknown))

        self.suiteDict = d

    def _register_metadata(self):
        '''
        Registers the metadata loaded by _load_metadata into the relevant
        global dictionaries such as _projects, _libs, _jreLibs and _dists.
        '''
        for l in self.libs:
            existing = _libs.get(l.name)
            # Check that suites that define same library are consistent
            if existing is not None and existing != l and _check_global_structures:
                abort('inconsistent library redefinition of ' + l.name + ' in ' + existing.suite.dir + ' and ' + l.suite.dir, context=l)
            _libs[l.name] = l
        for l in self.jreLibs:
            existing = _jreLibs.get(l.name)
            # Check that suites that define same library are consistent
            if existing is not None and existing != l:
                abort('inconsistent JRE library redefinition of ' + l.name + ' in ' + existing.suite.dir + ' and ' + l.suite.dir, context=l)
            _jreLibs[l.name] = l
        for l in self.jdkLibs:
            existing = _jdkLibs.get(l.name)
            # Check that suites that define same library are consistent
            if existing is not None and existing != l:
                abort('inconsistent JDK library redefinition of ' + l.name + ' in ' + existing.suite.dir + ' and ' + l.suite.dir, context=l)
            _jdkLibs[l.name] = l
        for d in self.dists:
            self._register_distribution(d)
        for d in self.distTemplates:
            existing = _distTemplates.get(d.name)
            if existing is not None and _check_global_structures:
                abort('inconsistent distribution template redefinition of ' + d.name + ' in ' + existing.suite.dir + ' and ' + d.suite.dir, context=d)
            _distTemplates[d.name] = d
        for l in self.licenseDefs:
            existing = _licenses.get(l.name)
            if existing is not None and _check_global_structures and l != existing:
                abort("inconsistent license redefinition of {} in {} (initialy defined in {})".format(l.name, self.name, existing.suite.name), context=l)
            _licenses[l.name] = l
        for r in self.repositoryDefs:
            existing = _repositories.get(r.name)
            if existing is not None and _check_global_structures and r != existing:
                abort("inconsistent repository redefinition of {} in {} (initialy defined in {})".format(r.name, self.name, existing.suite.name), context=r)
            _repositories[r.name] = r

    def _register_distribution(self, d):
        existing = _dists.get(d.name)
        if existing is not None and _check_global_structures:
            # allow redefinition, so use path from existing
            # abort('cannot redefine distribution  ' + d.name)
            warn('distribution ' + d.name + ' redefined', context=d)
            d.path = existing.path
        _dists[d.name] = d

    def _resolve_dependencies(self):
        for d in self.projects + self.libs + self.dists:
            d.resolveDeps()
        for r in self.repositoryDefs:
            r.resolveLicenses()

    def _post_init_finish(self):
        if hasattr(self, 'mx_post_parse_cmd_line'):
            self.mx_post_parse_cmd_line(_opts)
        self.post_init = True

    def version(self, abortOnError=True):
        abort('version not implemented')

    def isDirty(self, abortOnError=True):
        abort('isDirty not implemented')

    def _load_metadata(self):
        suiteDict = self.suiteDict
        if suiteDict.get('name') is None:
            abort('Missing "suite=<name>" in ' + self.suite_py())

        libsMap = self._check_suiteDict('libraries')
        jreLibsMap = self._check_suiteDict('jrelibraries')
        jdkLibsMap = self._check_suiteDict('jdklibraries')
        distsMap = self._check_suiteDict('distributions')
        importsMap = self._check_suiteDict('imports')
        scmDict = self._check_suiteDict('scm')
        self.developer = self._check_suiteDict('developer')
        self.url = suiteDict.get('url')
        if not _validate_abolute_url(self.url, acceptNone=True):
            abort('Invalid url in {}'.format(self.suite_py()))
        self.defaultLicense = suiteDict.get(self.getMxCompatibility().defaultLicenseAttribute())

        if scmDict:
            try:
                read = scmDict.pop('read')
            except NameError:
                abort("Missing required 'read' attribute for 'scm'", context=self)
            write = scmDict.pop('write', read)
            url = scmDict.pop('url', read)
            self.scm = SCMMetadata(url, read, write)

        for name, attrs in sorted(jreLibsMap.iteritems()):
            jar = attrs.pop('jar')
            # JRE libraries are optional by default
            optional = attrs.pop('optional', 'true') != 'false'
            theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
            l = JreLibrary(self, name, jar, optional, theLicense)
            self.jreLibs.append(l)

        for name, attrs in sorted(jdkLibsMap.iteritems()):
            jar = attrs.pop('path')
            # JRE libraries are optional by default
            theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
            optional = attrs.pop('optional', 'true') != 'false'
            l = JdkLibrary(self, name, jar, optional, theLicense)
            self.jdkLibs.append(l)

        for name, attrs in sorted(importsMap.iteritems()):
            if name == 'suites':
                pass
            elif name == 'libraries':
                self._load_libraries(attrs)
            else:
                abort('illegal import kind: ' + name)

        licenseDefs = self._check_suiteDict(self.getMxCompatibility().licensesAttribute())
        repositoryDefs = self._check_suiteDict('repositories')

        self._load_libraries(libsMap)
        self._load_distributions(distsMap)
        self._load_licenses(licenseDefs)
        self._load_repositories(repositoryDefs)


    def _check_suiteDict(self, key):
        return dict() if self.suiteDict.get(key) is None else self.suiteDict[key]

    def imports_dir(self, kind):
        return join(join(self.dir, 'mx.imports'), kind)

    def binary_imports_dir(self):
        return self.imports_dir('binary')

    def source_imports_dir(self):
        return self.imports_dir('source')

    def binary_suite_dir(self, name):
        '''
        Returns the mxDir for an imported BinarySuite, creating the parent if necessary
        '''
        dotMxDir = self.binary_imports_dir()
        ensure_dir_exists(dotMxDir)
        return join(dotMxDir, name)

    def _find_binary_suite_dir(self, name):
        '''Attempts to locate a binary_suite directory for suite 'name', returns the mx dir or None'''
        suite_dir = join(self.binary_imports_dir(), name)
        return _is_suite_dir(suite_dir, _mxDirName(name))

    def _extensions_name(self):
        return 'mx_' + self.name.replace('-', '_')

    def _find_extensions(self, name):
        extensionsPath = join(self.mxDir, name + '.py')
        if exists(extensionsPath):
            return name
        else:
            return None

    def _load_extensions(self):
        extensionsName = self._find_extensions(self._extensions_name())
        if extensionsName is not None:
            if extensionsName in sys.modules:
                abort(extensionsName + '.py in suite ' + self.name + ' duplicates ' + sys.modules[extensionsName].__file__)
            # temporarily extend the Python path
            sys.path.insert(0, self.mxDir)
            mod = __import__(extensionsName)

            self.extensions = sys.modules.pop(extensionsName)
            sys.modules[extensionsName] = self.extensions

            # revert the Python path
            del sys.path[0]

            if hasattr(mod, 'mx_post_parse_cmd_line'):
                self.mx_post_parse_cmd_line = mod.mx_post_parse_cmd_line

            if hasattr(mod, 'mx_init'):
                mod.mx_init(self)
            self.extensions = mod

    def _init_imports(self):
        importsMap = self._check_suiteDict("imports")
        suiteImports = importsMap.get("suites")
        if suiteImports:
            if not isinstance(suiteImports, list):
                abort('suites must be a list-valued attribute')
            for entry in suiteImports:
                if not isinstance(entry, dict):
                    abort('suite import entry must be a dict')
                suite_import = SuiteImport.parse_specification(entry, context=self, dynamicImport=self.dynamicallyImported)
                self.suite_imports.append(suite_import)
        if self.primary:
            dynamicImports = _opts.dynamic_imports
            if not dynamicImports:
                envDynamicImports = os.environ.get('DEFAULT_DYNAMIC_IMPORTS')
                if envDynamicImports:
                    dynamicImports = envDynamicImports.split(',')
            if dynamicImports:
                for name in dynamicImports:
                    self.suite_imports.append(SuiteImport(name, version=None, urlinfos=None, dynamicImport=True))

    def re_init_imports(self):
        '''
        If a suite is updated, e.g. by sforceimports, we must re-initialize the potentially
        stale import data from the updated suite.py file
        '''
        self.suite_imports = []
        self._load_suite_dict()
        self._init_imports()

    def _load_distributions(self, distsMap):
        for name, attrs in sorted(distsMap.iteritems()):
            if '<' in name:
                parameters = re.findall(r'<(.+?)>', name)
                self.distTemplates.append(DistributionTemplate(self, name, attrs, parameters))
            else:
                self._load_distribution(name, attrs)

    def _load_distribution(self, name, attrs):
        assert not '>' in name
        context = 'distribution ' + name
        native = attrs.pop('native', False)
        theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
        os_arch = Suite._pop_os_arch(attrs, context)
        Suite._merge_os_arch_attrs(attrs, os_arch, context)
        exclLibs = Suite._pop_list(attrs, 'exclude', context)
        deps = Suite._pop_list(attrs, 'dependencies', context)
        platformDependent = bool(os_arch)
        if native:
            path = attrs.pop('path')
            d = NativeTARDistribution(self, name, deps, path, exclLibs, platformDependent, theLicense)
        else:
            defaultPath = join(self.get_output_root(), 'dists', _map_to_maven_dist_name(name) + '.jar')
            defaultSourcesPath = join(self.get_output_root(), 'dists', _map_to_maven_dist_name(name) + '.src.zip')
            subDir = attrs.pop('subDir', None)
            path = attrs.pop('path', defaultPath)
            sourcesPath = attrs.pop('sourcesPath', defaultSourcesPath)
            if sourcesPath == "<unified>":
                sourcesPath = path
            elif sourcesPath == "<none>":
                sourcesPath = None
            mainClass = attrs.pop('mainClass', None)
            distDeps = Suite._pop_list(attrs, 'distDependencies', context)
            javaCompliance = attrs.pop('javaCompliance', None)
            javadocType = attrs.pop('javadocType', 'implementation')
            allowsJavadocWarnings = attrs.pop('allowsJavadocWarnings', False)
            maven = attrs.pop('maven', True)
            if isinstance(maven, types.DictType) and maven.get('version', None):
                abort("'version' is not supported in maven specification for distributions")
            d = JARDistribution(self, name, subDir, path, sourcesPath, deps, mainClass, exclLibs, distDeps, javaCompliance, platformDependent, theLicense, javadocType=javadocType, allowsJavadocWarnings=allowsJavadocWarnings, maven=maven)
        d.__dict__.update(attrs)
        self.dists.append(d)
        return d

    def _unload_unregister_distribution(self, name):
        self.dists = [d for d in self.dists if d.name != name]
        d = _dists[name]
        del _dists[name]
        return d

    @staticmethod
    def _pop_list(attrs, name, context):
        v = attrs.pop(name, None)
        if not v:
            return []
        if not isinstance(v, list):
            abort('Attribute "' + name + '" for ' + context + ' must be a list', context)
        return v

    @staticmethod
    def _pop_os_arch(attrs, context):
        os_arch = attrs.pop('os_arch', None)
        if os_arch:
            os_attrs = os_arch.pop(get_os(), None)
            if not os_attrs:
                os_attrs = os_arch.pop('<others>', None)
            if os_attrs:
                arch_attrs = os_attrs.pop(get_arch(), None)
                if not arch_attrs:
                    arch_attrs = os_attrs.pop('<others>', None)
                if arch_attrs:
                    return arch_attrs
                else:
                    warn('{} is not available on your architecture ({})'.format(context, get_arch()))
            else:
                warn('{} is not available on your os ({})'.format(context, get_os()))
        return None

    @staticmethod
    def _merge_os_arch_attrs(attrs, os_arch_attrs, context):
        if os_arch_attrs:
            for k, v in os_arch_attrs.iteritems():
                if k in attrs:
                    other = attrs[k]
                    if isinstance(v, types.ListType) and isinstance(other, types.ListType):
                        attrs[k] = v + other
                    else:
                        abort("OS/Arch attribute must not override non-OS/Arch attribute '{}' in {}".format(k, context))
                else:
                    attrs[k] = v

    def _load_libraries(self, libsMap):
        for name, attrs in sorted(libsMap.iteritems()):
            context = 'library ' + name
            attrs.pop('native', False)  # TODO use to make non-classpath libraries
            os_arch = Suite._pop_os_arch(attrs, context)
            Suite._merge_os_arch_attrs(attrs, os_arch, context)
            deps = Suite._pop_list(attrs, 'dependencies', context)
            path = attrs.pop('path', None)
            urls = Suite._pop_list(attrs, 'urls', context)
            sha1 = attrs.pop('sha1', None)
            ext = attrs.pop('ext', None)
            if path is None:
                if not urls:
                    abort('Library without "path" attribute must have a non-empty "urls" list attribute', context)
                if not sha1:
                    abort('Library without "path" attribute must have a non-empty "sha1" attribute', context)
                path = _get_path_in_cache(name, sha1, urls, ext)
            sourcePath = attrs.pop('sourcePath', None)
            sourceUrls = Suite._pop_list(attrs, 'sourceUrls', context)
            sourceSha1 = attrs.pop('sourceSha1', None)
            sourceExt = attrs.pop('sourceExt', None)
            if sourcePath is None and sourceUrls:
                if not sourceSha1:
                    abort('Library without "sourcePath" attribute but with non-empty "sourceUrls" attribute must have a non-empty "sourceSha1" attribute', context)
                sourcePath = _get_path_in_cache(name + '.sources', sourceSha1, sourceUrls, sourceExt)
            theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
            optional = attrs.pop('optional', False)
            resource = attrs.pop('resource', False)
            if resource:
                l = ResourceLibrary(self, name, path, optional, urls, sha1)
            else:
                l = Library(self, name, path, optional, urls, sha1, sourcePath, sourceUrls, sourceSha1, deps, theLicense)
            l.__dict__.update(attrs)
            self.libs.append(l)

    def _load_licenses(self, licenseDefs):
        for name, attrs in sorted(licenseDefs.items()):
            fullname = attrs.pop('name')
            url = attrs.pop('url')
            if not _validate_abolute_url(url):
                abort('Invalid url in license {} in {}'.format(name, self.suite_py()))
            l = License(self, name, fullname, url)
            l.__dict__.update(attrs)
            self.licenseDefs.append(l)

    def _load_repositories(self, repositoryDefs):
        for name, attrs in sorted(repositoryDefs.items()):
            context = 'repository ' + name
            url = attrs.pop('url')
            if not _validate_abolute_url(url):
                abort('Invalid url in repository {}'.format(self.suite_py()), context=context)
            licenses = Suite._pop_list(attrs, self.getMxCompatibility().licensesAttribute(), context=context)
            r = Repository(self, name, url, licenses)
            r.__dict__.update(attrs)
            self.repositoryDefs.append(r)

    @staticmethod
    def _init_metadata_visitor(importing_suite, suite_import, **extra_args):
        imported_suite = suite(suite_import.name)
        if not imported_suite._metadata_initialized:
            # avoid recursive initialization
            imported_suite._metadata_initialized = True
            imported_suite.visit_imports(imported_suite._init_metadata_visitor)
            imported_suite._init_metadata()

    @staticmethod
    def _post_init_visitor(importing_suite, suite_import, **extra_args):
        imported_suite = suite(suite_import.name)
        if not imported_suite.post_init:
            imported_suite.visit_imports(imported_suite._post_init_visitor)
            imported_suite._post_init()

    def _init_metadata(self):
        self._load_metadata()
        self._register_metadata()
        self._resolve_dependencies()

    def _post_init(self):
        self._post_init_finish()

    @staticmethod
    def _find_and_loadsuite(importing_suite, suite_import, fatalIfMissing=True, **extra_args):
        """
        Attempts to locate a suite using the information in suite_import and _binary_suites

        If _binary_suites is None, (the usual case in development), tries to resolve
        an import as a local source suite first, using the SuiteModel in effect.
        If that fails uses the urlsinfo in suite_import to try to locate the suite in
        a source repository and download it. 'binary' urls are ignored.

        If _binary_suites == [a,b,...], then the listed suites are searched for
        using binary urls and no attempt is made to search source urls.

        If _binary_suites == [], source urls are completely ignored.
        """
        # Loaded already? Check for cycles and mismatched versions
        # N.B. Currently only check the versions stated in the suite.py files and not the head version
        # of a source suite as that can and will change during development. I.e, the version
        # in the suite_import is only used when we actually need to download a suite
        for s in _suites.itervalues():
            if s.name == suite_import.name:
                if s.loading_imports:
                    abort("import cycle on suite '{0}' detected in suite '{1}'".format(s.name, importing_suite.name))
                if not extra_args.has_key('noLoad'):
                    # check that all other importers use the same version
                    for otherImporter in s.imported_by:
                        for imported in otherImporter.suite_imports:
                            if imported.name == s.name:
                                if imported.version != suite_import.version:
                                    resolved = _resolve_suite_version_conflict(s.name, s, imported.version, otherImporter, suite_import, importing_suite)
                                    if resolved:
                                        s.vc.update(s.dir, rev=resolved, mayPull=True)
                return s

        searchMode = 'binary' if _binary_suites is not None and (len(_binary_suites) == 0 or suite_import.name in _binary_suites) else 'source'
        version = suite_import.version
        # experimental code to ignore versions, aka pull the tip
        if _suites_ignore_versions:
            if len(_suites_ignore_versions) == 0 or suite_import.name in _suites_ignore_versions:
                version = None

        # The following two functions abstract state that varies between binary and source suites

        def _find_suite_dir():
            '''
            Attempts to locate an existing suite in the local context
            Returns the path to the mx.name dir if found else None
            '''
            if searchMode == 'binary':
                # binary suites are always stored relative to the importing suite in mx-private directory
                return importing_suite._find_binary_suite_dir(suite_import.name)
            else:
                # use the SuiteModel to locate a local source copy of the suite
                return _src_suitemodel.find_suite_dir(suite_import.name)

        def _get_import_dir():
            '''Return directory where the suite will be cloned to'''
            if searchMode == 'binary':
                return importing_suite.binary_suite_dir(suite_import.name)
            else:
                importDir = _src_suitemodel.importee_dir(importing_suite.dir, suite_import, check_alternate=False)
                if exists(importDir):
                    abort("Suite import directory ({0}) for suite '{1}' exists but no suite definition could be found.".format(importDir, suite_import.name))
                return importDir

        def _clone_kwargs():
            if searchMode == 'binary':
                return dict(result=dict())
            else:
                return dict()

        clone_kwargs = _clone_kwargs()
        importMxDir = _find_suite_dir()
        if importMxDir is None:
            # No local copy, so use the URLs in order to "download" one
            importDir = _get_import_dir()
            fail = True
            urlinfos = [urlinfo for urlinfo in suite_import.urlinfos if urlinfo.abs_kind() == searchMode]
            for urlinfo in urlinfos:
                if not urlinfo.vc.check(abortOnError=False):
                    continue
                if searchMode == 'binary':
                    # pass extra necessary extra info
                    clone_kwargs['suite_name'] = suite_import.name

                if urlinfo.vc.clone(urlinfo.url, importDir, version, abortOnError=False, **clone_kwargs):
                    importMxDir = _find_suite_dir()
                    if importMxDir is None:
                        # wasn't a suite after all, this is an error
                        pass
                    else:
                        fail = False
                    # we are done searching either way
                    break
                else:
                    # it is possible that the clone partially populated the target
                    # which will mess an up an alternate, so we clean it
                    if exists(importDir):
                        shutil.rmtree(importDir)

            # end of search
            if fail:
                if fatalIfMissing:
                    abort('import ' + suite_import.name + ' not found (search mode ' + searchMode + ')')
                else:
                    return None

        # Factory method?
        if searchMode == 'binary':
            return BinarySuite(importMxDir, importing_suite=importing_suite, dynamicallyImported=suite_import.dynamicImport)
        else:
            return SourceSuite(importMxDir, importing_suite=importing_suite, load=not extra_args.has_key('noLoad'), dynamicallyImported=suite_import.dynamicImport)

    def visit_imports(self, visitor, **extra_args):
        """
        Visitor support for the suite imports list
        For each entry the visitor function is called with this suite, a SuiteImport instance created
        from the entry and any extra args passed to this call.
        N.B. There is no built-in support for avoiding visiting the same suite multiple times,
        as this function only visits the imports of a single suite. If a (recursive) visitor function
        wishes to visit a suite exactly once, it must manage that through extra_args.
        """
        for suite_import in self.suite_imports:
            visitor(self, suite_import, **extra_args)

    def import_suite(self, name, version=None, urlinfos=None, kind=None):
        """Dynamic import of a suite. Returns None if the suite cannot be found"""
        suite_import = SuiteImport(name, version, urlinfos, kind, dynamicImport=True)
        imported_suite = Suite._find_and_loadsuite(self, suite_import, fatalIfMissing=False)
        if imported_suite:
            # if urlinfos is set, force the import to version in case it already existed
            if urlinfos:
                imported_suite.vc.update(imported_suite.dir, rev=version, mayPull=True)
            # TODO Add support for imports in dynamically loaded suites (no current use case)
            if not imported_suite.post_init:
                imported_suite._init_metadata()
                imported_suite._post_init()
        return imported_suite

    def scm_metadata(self, abortOnError=False):
        return self.scm

    def suite_py(self):
        return join(self.mxDir, 'suite.py')

    def suite_py_mtime(self):
        if not hasattr(self, '_suite_py_mtime'):
            self._suite_py_mtime = os.path.getmtime(self.suite_py())
        return self._suite_py_mtime

    def __abort_context__(self):
        '''
        Returns a string describing where this suite was defined in terms its source file.
        If no such description can be generated, returns None.
        '''
        path = self.suite_py()
        if exists(path):
            return 'In definition of suite {} in {}'.format(self.name, path)
        return None

def _resolve_suite_version_conflict(suiteName, existingSuite, existingVersion, existingImporter, otherImport, otherImportingSuite):
    if otherImport.dynamicImport and (not existingSuite or not existingSuite.dynamicallyImported):
        return None
    if not otherImport.version:
        return None
    conflict_resolution = _opts.version_conflict_resolution
    if conflict_resolution == 'suite':
        if otherImportingSuite:
            conflict_resolution = otherImportingSuite.versionConflictResolution
        else:
            warn("Conflict resolution was set to 'suite' but importing suite is not available")

    if conflict_resolution == 'ignore':
        warn("mismatched import versions on '{}' in '{}' ({}) and '{}' ({})".format(suiteName, otherImportingSuite.name, otherImport.version, existingImporter.name if existingImporter else '?', existingVersion))
        return None
    elif conflict_resolution == 'latest':
        if not existingSuite:
            return None # can not resolve at the moment
        if existingSuite.vc.kind != otherImport.kind:
            return None
        if not isinstance(existingSuite, SourceSuite):
            abort("mismatched import versions on '{}' in '{}' and '{}', 'latest' conflict resolution is only suported for source suites".format(suiteName, otherImportingSuite.name, existingImporter.name if existingImporter else '?'))
        if not existingSuite.vc.exists(existingSuite.dir, rev=otherImport.version):
            return otherImport.version
        resolved = existingSuite.vc.latest(existingSuite.dir, otherImport.version, existingSuite.vc.parent(existingSuite.dir))
        # TODO currently this only handles simple DAGs and it will always do an update assuming that the repo is at a version controlled by mx
        if existingSuite.vc.parent(existingSuite.dir) == resolved:
            return None
        return resolved
    if conflict_resolution == 'none':
        abort("mismatched import versions on '{}' in '{}' ({}) and '{}' ({})".format(suiteName, otherImportingSuite.name, otherImport.version, existingImporter.name if existingImporter else '?', existingVersion))

'''A source suite'''
class SourceSuite(Suite):
    def __init__(self, mxDir, primary=False, load=True, internal=False, importing_suite=None, dynamicallyImported=False):
        Suite.__init__(self, mxDir, primary, internal, importing_suite, dynamicallyImported=dynamicallyImported)
        self.vc = None if internal else VC.get_vc(self.dir)
        self.projects = []
        self._load_suite_dict()
        self._init_imports()
        self._releaseVersion = None
        if load:
            self._load()

    def version(self, abortOnError=True):
        '''
        Return the current head changeset of this suite.
        '''
        # we do not cache the version because it changes in development
        return self.vc.parent(self.dir, abortOnError=abortOnError)

    def isDirty(self, abortOnError=True):
        '''
        Check whether there are pending changes in the source.
        '''
        return self.vc.isDirty(self.dir, abortOnError=abortOnError)

    def release_version(self, snapshotSuffix='dev'):
        """
        Gets the release tag from VC or create a time based once if VC is unavailable
        """
        if not self._releaseVersion:
            tag = self.vc.release_version_from_tags(self.dir, self.name, snapshotSuffix=snapshotSuffix)
            if not tag:
                tag = 'unknown-{0}-{1}'.format(platform.node(), time.strftime('%Y-%m-%d_%H-%M-%S_%Z'))
            self._releaseVersion = tag
        return self._releaseVersion

    def scm_metadata(self, abortOnError=False):
        scm = self.scm
        if scm:
            return scm
        pull = self.vc.default_pull(self.dir, abortOnError=abortOnError)
        if abortOnError and not pull:
            abort("Can not find scm metadata for suite {0} ({1})".format(self.name, self.dir))
        push = self.vc.default_push(self.dir, abortOnError=abortOnError)
        if not push:
            push = pull
        return SCMMetadata(pull, pull, push)

    def _load_metadata(self):
        Suite._load_metadata(self)
        self._load_projects()

    def _load_projects(self):
        '''projects are unique to source suites'''
        projsMap = self._check_suiteDict('projects')

        for name, attrs in sorted(projsMap.iteritems()):
            context = 'project ' + name
            className = attrs.pop('class', None)
            theLicense = attrs.pop(self.getMxCompatibility().licenseAttribute(), None)
            os_arch = Suite._pop_os_arch(attrs, context)
            Suite._merge_os_arch_attrs(attrs, os_arch, context)
            deps = Suite._pop_list(attrs, 'dependencies', context)
            genDeps = Suite._pop_list(attrs, 'generatedDependencies', context)
            if genDeps:
                deps += genDeps
                # Re-add generatedDependencies attribute so it can be used in canonicalizeprojects
                attrs['generatedDependencies'] = genDeps
            workingSets = attrs.pop('workingSets', None)
            jlintOverrides = attrs.pop('lint.overrides', None)
            if className:
                if not self.extensions or not hasattr(self.extensions, className):
                    abort('Project {} requires a custom class ({}) which was not found in {}'.format(name, className, join(self.mxDir, self._extensions_name() + '.py')))
                p = getattr(self.extensions, className)(self, name, deps, workingSets, theLicense=theLicense, **attrs)
            else:
                srcDirs = Suite._pop_list(attrs, 'sourceDirs', context)
                subDir = attrs.pop('subDir', None)
                if subDir is None:
                    d = join(self.dir, name)
                else:
                    d = join(self.dir, subDir, name)
                native = attrs.pop('native', False)
                if native:
                    output = attrs.pop('output', None)
                    results = Suite._pop_list(attrs, 'output', context)
                    p = NativeProject(self, name, subDir, srcDirs, deps, workingSets, results, output, d, theLicense=theLicense)
                else:
                    javaCompliance = attrs.pop('javaCompliance', None)
                    if javaCompliance is None:
                        abort('javaCompliance property required for non-native project ' + name)
                    p = JavaProject(self, name, subDir, srcDirs, deps, javaCompliance, workingSets, d, theLicense=theLicense)
                    p.checkstyleProj = attrs.pop('checkstyle', name)
                    p.checkPackagePrefix = attrs.pop('checkPackagePrefix', 'true') == 'true'
                    ap = Suite._pop_list(attrs, 'annotationProcessors', context)
                    if ap:
                        p.declaredAnnotationProcessors = ap
                    if jlintOverrides:
                        p._javac_lint_overrides = jlintOverrides
            p.__dict__.update(attrs)
            self.projects.append(p)


        # Create a distribution for each project that defines annotation processors
        apProjects = {}
        for p in self.projects:
            if not p.isJavaProject():
                continue
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
                p.definedAnnotationProcessors = annotationProcessors
                apProjects[p.name] = p

        # Initialize the definedAnnotationProcessors list for distributions with direct
        # dependencies on projects that define one or more annotation processors.
        for dist in self.dists:
            aps = []
            for dep in dist.deps:
                name = dep if isinstance(dep, str) else dep.name
                if name in apProjects:
                    aps += apProjects[name].definedAnnotationProcessors
            if aps:
                dist.definedAnnotationProcessors = aps
                # Restrict exported annotation processors to those explicitly defined by the projects
                def _refineAnnotationProcessorServiceConfig(dist):
                    apsJar = dist.path
                    config = 'META-INF/services/javax.annotation.processing.Processor'
                    with zipfile.ZipFile(apsJar, 'r') as zf:
                        currentAps = zf.read(config).split()
                    if currentAps != dist.definedAnnotationProcessors:
                        logv('[updating ' + config + ' in ' + apsJar + ']')
                        with Archiver(apsJar) as arc:
                            with zipfile.ZipFile(apsJar, 'r') as lp:
                                for arcname in lp.namelist():
                                    if arcname == config:
                                        arc.zf.writestr(arcname, '\n'.join(dist.definedAnnotationProcessors) + '\n')
                                    else:
                                        arc.zf.writestr(arcname, lp.read(arcname))
                dist.add_update_listener(_refineAnnotationProcessorServiceConfig)

    @staticmethod
    def _load_env_in_mxDir(mxDir):
        e = join(mxDir, 'env')
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

    def _load_env(self):
        SourceSuite._load_env_in_mxDir(self.mxDir)

    def _register_metadata(self):
        Suite._register_metadata(self)
        for p in self.projects:
            existing = _projects.get(p.name)
            if existing is not None and _check_global_structures:
                abort('cannot override project {} in {} with project of the same name in {}'.format(p.name, existing.dir, p.dir))
            if not hasattr(_opts, 'ignored_projects') or not p.name in _opts.ignored_projects:
                _projects[p.name] = p
            # check all project dependencies are local
            for d in p.deps:
                dp = project(d, False)
                if dp:
                    if not dp in self.projects:
                        dists = [(dist.suite.name + ':' + dist.name) for dist in dp.suite.dists if dp in dist.archived_deps()]
                        if len(dists) > 1:
                            dists = ', '.join(dists[:-1]) + ' or ' + dists[-1]
                        elif dists:
                            dists = dists[0]
                        else:
                            dists = '<name of distribution containing ' + dp.name + '>'
                        p.abort("dependency to project '{}' defined in an imported suite must use {} instead".format(dp.name, dists))
                    elif dp == p:
                        p.abort("recursive dependency in suite '{}' in project '{}'".format(self.name, d))

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

    def mx_binary_distribution_jar_path(self):
        '''
        returns the absolute path of the mx binary distribution jar.
        '''
        return join(self.dir, _mx_binary_distribution_jar(self.name))

    def create_mx_binary_distribution_jar(self):
        '''
        Creates a jar file named name-mx.jar that contains
        the metadata for another suite to import this suite as a BinarySuite.
        TODO check timestamps to avoid recreating this repeatedly, or would
        the check dominate anyway?
        TODO It would be cleaner for subsequent loading if we actually wrote a
        transformed suite.py file that only contained distribution info, to
        detect access to private (non-distribution) state
        '''
        mxMetaJar = self.mx_binary_distribution_jar_path()
        pyfiles = glob.glob(join(self.mxDir, '*.py'))
        with Archiver(mxMetaJar) as arc:
            for pyfile in pyfiles:
                mxDirBase = basename(self.mxDir)
                arc.zf.write(pyfile, arcname=join(mxDirBase, basename(pyfile)))

    def eclipse_settings_sources(self):
        """
        Gets a dictionary from the name of an Eclipse settings file to
        the list of files providing its generated content, in overriding order
        (i.e., settings from files later in the list override settings from
        files earlier in the list).
        A new dictionary is created each time this method is called so it's
        safe for the caller to modify it.
        """
        esdict = {}
        # start with the mxtool defaults
        defaultEclipseSettingsDir = join(_mx_suite.dir, 'eclipse-settings')
        if exists(defaultEclipseSettingsDir):
            for name in os.listdir(defaultEclipseSettingsDir):
                esdict[name] = [os.path.abspath(join(defaultEclipseSettingsDir, name))]

        # append suite overrides
        eclipseSettingsDir = join(self.mxDir, 'eclipse-settings')
        if exists(eclipseSettingsDir):
            for name in os.listdir(eclipseSettingsDir):
                esdict.setdefault(name, []).append(os.path.abspath(join(eclipseSettingsDir, name)))
        return esdict

'''
A pre-built suite downloaded from a Maven repository.
'''
class BinarySuite(Suite):
    def __init__(self, mxDir, importing_suite, dynamicallyImported=False):
        Suite.__init__(self, mxDir, False, False, importing_suite, dynamicallyImported=dynamicallyImported)
        # At this stage the suite directory is guaranteed to exist as is the mx.suitname
        # directory. For a freshly downloaded suite, the actual distribution jars
        # have not been downloaded as we need info from the suite.py for that
        self.vc = BinaryVC()
        self._load_binary_suite()
        self._init_imports()
        self._load()

    def version(self, abortOnError=True):
        '''
        Return the current head changeset of this suite.
        '''
        # we do not cache the version because it changes in development
        return self.vc.parent(self.dir)

    def isDirty(self, abortOnError=True):
        # a binary suite can not be dirty
        return False

    def _load_binary_suite(self):
        '''
        Always load the suite.py file and the distribution info defined there,
        download the jar files for a freshly cloned suite
        '''
        self._load_suite_dict()
        Suite._load_distributions(self, self._check_suiteDict('distributions'))

        for dist in self.dists:
            self.vc.getDistribution(self.dir, dist)

    def _load_env(self):
        pass

    def _load_distributions(self, distsMap):
        # This gets done explicitly in _load_binary_suite as we need the info there
        # so, in that mode, we don't want to call the superclass method again
        pass

    def _register_metadata(self):
        # since we are working with the original suite.py file, we remove some
        # values that should not be visible
        self.projects = []
        Suite._register_metadata(self)

    def _resolve_dependencies(self):
        for d in self.libs + self.dists:
            d.resolveDeps()
        for d in self.dists:
            d.deps = [dep for dep in d.deps if dep and dep.isDistribution()]

class InternalSuite(SourceSuite):
    def __init__(self, mxDir):
        mxMxDir = _is_suite_dir(mxDir)
        assert mxMxDir
        SourceSuite.__init__(self, mxMxDir, internal=True)

class MXSuite(InternalSuite):
    def __init__(self):
        InternalSuite.__init__(self, _mx_home)
        self._init_metadata()
        self._post_init()

    def vc_command_init(self):
        pass

class MXTestsSuite(InternalSuite):
    def __init__(self):
        InternalSuite.__init__(self, join(_mx_home, "tests"))

class PrimarySuite(SourceSuite):
    def __init__(self, mxDir, load):
        SourceSuite.__init__(self, mxDir, primary=True, load=load, importing_suite=None)

    def _depth_first_post_init(self):
        '''depth first _post_init driven by imports graph'''
        self.visit_imports(self._init_metadata_visitor)
        self._init_metadata()
        self.visit_imports(self._post_init_visitor)
        self._post_init()

    @staticmethod
    def load_env(mxDir):
        SourceSuite._load_env_in_mxDir(mxDir)

    @staticmethod
    def _find_suite(importing_suite, suite_import, **extra_args):
        imported_suite = Suite._find_and_loadsuite(importing_suite, suite_import, **extra_args)
        _suites[imported_suite.name] = imported_suite
        PrimarySuite._fake_load(imported_suite)
        imported_suite.visit_imports(PrimarySuite._find_suite, noLoad=True)

    def vc_command_init(self):
        '''A short-circuit startup for vc (s*) commands that only loads the
        import metadata from the suite.py file.
        '''
        # so far we have just loaded the primary suite imports info
        PrimarySuite._fake_load(self)
        # Now visit the imports just loading import info
        self.visit_imports(self._find_suite, noLoad=True)

    @staticmethod
    def _fake_load(s):
        # logically this is wrong as Suite._load has not been executed but it keeps suites() happy
        _loadedSuites.append(s)



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

'''
A simple timing facility.
'''
class Timer():
    def __init__(self, name):
        self.name = name
    def __enter__(self):
        self.start = time.time()
        return self
    def __exit__(self, t, value, traceback):
        elapsed = time.time() - self.start
        print '{} took {} seconds'.format(self.name, elapsed)
        return None

def _bench_test_common(args, parser, suppliedParser):
    parser.add_argument('--J', dest='vm_args', action='append', help='target VM arguments (e.g. --J @-dsa)', metavar='@<args>')
    mx_gate.add_omit_clean_args(parser)
    if suppliedParser:
        parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    cleanArgs = mx_gate.check_gate_noclean_arg(args)

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
    return harness(args, split_j_args(args.vm_args))

def _basic_test_harness(args, vmArgs):
    return 0

def test(args, harness=_basic_test_harness, parser=None):
    '''run tests (suite-specific) after clean build (optional)'''
    suppliedParser = parser is not None
    parser = parser if suppliedParser else ArgumentParser(prog='mx test')
    args = _bench_test_common(args, parser, suppliedParser)
    return harness(args, split_j_args(args.vm_args))

def get_jython_os():
    from java.lang import System as System
    os_name = System.getProperty('os.name').lower()
    if System.getProperty('isCygwin'):
        return 'cygwin'
    elif os_name.startswith('mac'):
        return 'darwin'
    elif os_name.startswith('linux'):
        return 'linux'
    elif os_name.startswith('openbsd'):
        return 'openbsd'
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
    elif sys.platform.startswith('openbsd'):
        return 'openbsd'
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
    if machine in ['sun4v', 'sun4u', 'sparc64']:
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

def vc_system(kind, abortOnError=True):
    for vc in _vc_systems:
        if vc.kind == kind:
            vc.check()
            return vc
    if abortOnError:
        abort('no VC system named ' + kind)
    else:
        return None

def get_opts():
    """
    Gets the parsed command line options.
    """
    assert _argParser.parsed is True
    return _opts

def suites(opt_limit_to_suite=False, includeBinary=True):
    """
    Get the list of all loaded suites.
    """
    res = [s for s in _loadedSuites if not s.internal and (includeBinary or isinstance(s, SourceSuite))]
    if opt_limit_to_suite and _opts.specific_suites:
        res = [s for s in res and s.name in _opts.specific_suites]
    return res

def suite(name, fatalIfMissing=True, context=None):
    """
    Get the suite for a given name.
    """
    s = _suites.get(name)
    if s is None and fatalIfMissing:
        abort('suite named ' + name + ' not found', context=context)
    return s

def primary_suite():
    return _primary_suite

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

    sortedProjects = sorted((p for p in _projects.itervalues() if not p.suite.internal))
    if opt_limit_to_suite:
        return _dependencies_opt_limit_to_suites(sortedProjects)
    else:
        return sortedProjects

def projects_opt_limit_to_suites():
    """
    Get the list of all loaded projects optionally limited by --suite option
    """
    return projects(True)

def _dependencies_opt_limit_to_suites(deps):
    if not _opts.specific_suites:
        return deps
    else:
        result = []
        for d in deps:
            s = d.suite
            if s.name in _opts.specific_suites:
                result.append(d)
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

def get_license(name, fatalIfMissing=True, context=None):
    _, name = splitqualname(name)
    l = _licenses.get(name)
    if l is None and fatalIfMissing:
        abort('license named ' + name + ' not found', context=context)
    return l

def repository(name, fatalIfMissing=True, context=None):
    _, name = splitqualname(name)
    r = _repositories.get(name)
    if r is None and fatalIfMissing:
        abort('repository named ' + name + ' not found', context=context)
    return r

def splitqualname(name):
    pname = name.partition(":")
    if pname[0] != name:
        return pname[0], pname[2]
    else:
        return None, name

def _patchTemplateString(s, args, context):
    def _replaceVar(m):
        groupName = m.group(1)
        if not groupName in args:
            abort("Unknown parameter {}".format(groupName), context=context)
        return args[groupName]
    return re.sub(r'<(.+?)>', _replaceVar, s)

def instantiatedDistributionName(name, args, context):
    return _patchTemplateString(name, args, context).upper()

def reInstantiateDistribution(templateName, oldArgs, newArgs):
    _, name = splitqualname(templateName)
    context = "Template distribution " + name
    t = _distTemplates.get(name)
    if t is None:
        abort('Distribution template named ' + name + ' not found', context=context)
    oldName = instantiatedDistributionName(t.name, oldArgs, context)
    oldDist = t.suite._unload_unregister_distribution(oldName)
    newDist = instantiateDistribution(templateName, newArgs)
    newDist.update_listeners.update(oldDist.update_listeners)

def instantiateDistribution(templateName, args, fatalIfMissing=True, context=None):
    _, name = splitqualname(templateName)
    if not context:
        context = "Template distribution " + name
    t = _distTemplates.get(name)
    if t is None and fatalIfMissing:
        abort('Distribution template named ' + name + ' not found', context=context)
    missingParams = [p for p in t.parameters if p not in args]
    if missingParams:
        abort('Missing parameters while instantiating distribution template ' + t.name + ': ' + ', '.join(missingParams), context=t)

    def _patchAttrs(attrs):
        result = {}
        for k, v in attrs.iteritems():
            if isinstance(v, types.StringType):
                result[k] = _patchTemplateString(v, args, context)
            elif isinstance(v, types.DictType):
                result[k] = _patchAttrs(v)
            else:
                result[k] = v
        return result

    d = t.suite._load_distribution(instantiatedDistributionName(t.name, args, context), _patchAttrs(t.attrs))
    if d is None and fatalIfMissing:
        abort('distribution template ' + t.name + ' could not be instantiated with ' + str(args), context=t)
    t.suite._register_distribution(d)
    d.resolveDeps()
    return d

def _get_reasons_dep_was_removed(name):
    """
    Gets the causality chain for the dependency named *name* being removed.
    Returns None if no dependency named *name* was removed.
    """
    reason = _removedDeps.get(name)
    if reason:
        r = _get_reasons_dep_was_removed(reason)
        if r:
            return ['{} was removed because {} was removed'.format(name, reason)] + r
        return [reason]
    return None

def _missing_dep_message(depName, depType):
    msg = '{} named {} was not found'.format(depType, depName)
    reasons = _get_reasons_dep_was_removed(depName)
    if reasons:
        msg += ':\n  ' + '\n  '.join(reasons)
    return msg

def distribution(name, fatalIfMissing=True, context=None):
    """
    Get the distribution for a given name. This will abort if the named distribution does
    not exist and 'fatalIfMissing' is true.
    """
    _, name = splitqualname(name)
    d = _dists.get(name)
    if d is None and fatalIfMissing:
        abort(_missing_dep_message(name, 'distribution'), context=context)
    return d

def dependency(name, fatalIfMissing=True, context=None):
    """
    Get the project, library or dependency for a given name. This will abort if the dependency
    not exist for 'name' and 'fatalIfMissing' is true.
    """
    if isinstance(name, Dependency):
        return name

    suite_name, name = splitqualname(name)
    if suite_name:
        # reference to a distribution or library from a suite
        referencedSuite = suite(suite_name, context=context)
        if referencedSuite:
            d = _dists.get(name) or _libs.get(name)
            if d:
                if d.suite != referencedSuite:
                    if fatalIfMissing:
                        abort('{dep} exported by {depSuite}, expected {dep} from {referencedSuite}'.format(dep=d.name, referencedSuite=referencedSuite, depSuite=d.suite), context=context)
                    return None
                else:
                    return d
            else:
                if fatalIfMissing:
                    abort('cannot resolve ' + name + ' as a distribution or library of ' + suite_name, context=context)
                return None
    d = _projects.get(name)
    if d is None:
        d = _libs.get(name)
    if d is None:
        d = _jreLibs.get(name)
    if d is None:
        d = _jdkLibs.get(name)
    if d is None:
        d = _dists.get(name)
    if d is None and fatalIfMissing:
        if name in _opts.ignored_projects:
            abort('dependency named ' + name + ' is ignored', context=context)
        abort(_missing_dep_message(name, 'dependency'), context=context)
    return d

def project(name, fatalIfMissing=True, context=None):
    """
    Get the project for a given name. This will abort if the named project does
    not exist and 'fatalIfMissing' is true.
    """
    p = _projects.get(name)
    if p is None and fatalIfMissing:
        if name in _opts.ignored_projects:
            abort('project named ' + name + ' is ignored', context=context)
        abort(_missing_dep_message(name, 'project'), context=context)
    return p

def library(name, fatalIfMissing=True, context=None):
    """
    Gets the library for a given name. This will abort if the named library does
    not exist and 'fatalIfMissing' is true.
    """
    l = _libs.get(name)
    if l is None and fatalIfMissing:
        if _projects.get(name):
            abort(name + ' is a project, not a library', context=context)
        abort(_missing_dep_message(name, 'library'), context=context)
    return l

def classpath_entries(names=None, includeSelf=True, preferProjects=False):
    if names is None:
        roots = set(dependencies())
    else:
        if isinstance(names, types.StringTypes):
            names = [names]
        elif isinstance(names, Dependency):
            names = [names]
        roots = [dependency(n) for n in names]
        invalid = [d for d in roots if not isinstance(d, ClasspathDependency)]
        if invalid:
            abort('class path roots must be classpath dependencies: ' + str(invalid))

    cpEntries = []
    def _preVisit(dst, edge):
        if not isinstance(dst, ClasspathDependency):
            return False
        if dst in roots or dst.isLibrary():
            return True
        if edge and edge.src.isJARDistribution() and edge.kind == DEP_STANDARD:
            preferDist = isinstance(edge.src.suite, BinarySuite) or not preferProjects
            return dst.isJARDistribution() if preferDist else dst.isProject()
        return True
    def _visit(dep, edge):
        if preferProjects and dep.isJARDistribution() and not isinstance(dep.suite, BinarySuite):
            return
        if not includeSelf and dep in roots:
            return
        cpEntries.append(dep)
    walk_deps(roots=roots, visit=_visit, preVisit=_preVisit, ignoredEdges=[DEP_ANNOTATION_PROCESSOR])
    return cpEntries

def classpath(names=None, resolve=True, includeSelf=True, includeBootClasspath=False, preferProjects=False):
    """
    Get the class path for a list of named projects and distributions, resolving each entry in the
    path (e.g. downloading a missing library) if 'resolve' is true. If 'names' is None,
    then all registered dependencies are used.
    """
    cpEntries = classpath_entries(names=names, includeSelf=includeSelf, preferProjects=preferProjects)
    cp = []
    if includeBootClasspath:
        cp.append(get_jdk().bootclasspath())
    if _opts.cp_prefix is not None:
        cp.append(_opts.cp_prefix)
    for dep in cpEntries:
        cp_repr = dep.classpath_repr(resolve)
        if cp_repr:
            cp.append(cp_repr)
    if _opts.cp_suffix is not None:
        cp.append(_opts.cp_suffix)

    return os.pathsep.join(cp)

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

def read_annotation_processors(path):
    r'''
    Reads the META-INF/services/javax.annotation.processing.Processor file based
    in the directory or zip file located at 'path'. Returns the list of lines
    in the file or None if the file does not exist at 'path'.

    From http://docs.oracle.com/javase/8/docs/api/java/util/ServiceLoader.html:

    A service provider is identified by placing a provider-configuration file in
    the resource directory META-INF/services. The file's name is the fully-qualified
    binary name of the service's type. The file contains a list of fully-qualified
    binary names of concrete provider classes, one per line. Space and tab
    characters surrounding each name, as well as blank lines, are ignored.
    The comment character is '#' ('\u0023', NUMBER SIGN); on each line all characters
    following the first comment character are ignored. The file must be encoded in UTF-8.
    '''

    def parse(fp):
        lines = []
        for line in fp:
            line = line.split('#')[0].strip()
            if line:
                lines.append(line)
        return lines

    if exists(path):
        name = 'META-INF/services/javax.annotation.processing.Processor'
        if isdir(path):
            configFile = join(path, name.replace('/', os.sep))
            if exists(configFile):
                with open(configFile) as fp:
                    return parse(fp)
        else:
            assert path.endswith('.jar') or path.endswith('.zip'), path
            with zipfile.ZipFile(path, 'r') as zf:
                if name in zf.namelist():
                    with zf.open(name) as fp:
                        return parse(fp)
    return None

def dependencies(opt_limit_to_suite=False):
    '''
    Gets an iterable over all the registered dependencies. If changes are made to the registered
    dependencies during iteration, the behavior of the iterator is undefined. If 'types' is not
    None, only dependencies of a type in 'types
    '''
    it = itertools.chain(_projects.itervalues(), _libs.itervalues(), _dists.itervalues(), _jdkLibs.itervalues(), _jreLibs.itervalues())
    if opt_limit_to_suite and _opts.specific_suites:
        it = itertools.ifilter(lambda d: d.suite.name in _opts.specific_suites, it)
    itertools.ifilter(lambda d: not d.suite.internal, it)
    return it

def walk_deps(roots=None, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
    '''
    Walks a spanning tree of the dependency graph. The first time a dependency graph node is seen, if the
    'preVisit' function is not None, it is applied with these arguments:
        dep - the dependency node being visited
        edge - a DepEdge object representing last element in the path of dependencies walked to arrive
               at 'dep' or None if 'dep' is a leaf
    If 'preVisit' is None or returns a true condition, then the unvisited dependencies of 'dep' are
    walked. Once all the dependencies of 'dep' have been visited, and 'visit' is not None,
    it is applied with the same arguments as for 'preVisit' and the return value is ignored. Note that
    'visit' is not called if 'preVisit' returns a false condition.
    '''
    visited = set()
    for dep in dependencies() if not roots else roots:
        dep.walk_deps(preVisit, visit, visited, ignoredEdges, visitEdge)

def sorted_dists():
    """
    Gets distributions sorted such that each distribution comes after
    any distributions it depends upon.
    """
    dists = []
    def add_dist(dist):
        if not dist in dists:
            for dep in dist.deps:
                if dep.isDistribution():
                    add_dist(dep)
            if not dist in dists:
                dists.append(dist)

    for d in _dists.itervalues():
        add_dist(d)
    return dists

def extract_VM_args(args, useDoubleDash=False, allowClasspath=False, defaultAllVMArgs=True):
    """
    Partitions 'args' into a leading sequence of HotSpot VM options and the rest. If
    'useDoubleDash' then 'args' is partititioned by the first instance of "--". If
    not 'allowClasspath' then mx aborts if "-cp" or "-classpath" is in 'args'.

   """
    for i in range(len(args)):
        if useDoubleDash:
            if args[i] == '--':
                vmArgs = args[:i]
                remainder = args[i + 1:]
                return vmArgs, remainder
        else:
            if not args[i].startswith('-'):
                if i != 0 and (args[i - 1] == '-cp' or args[i - 1] == '-classpath'):
                    if not allowClasspath:
                        abort('Cannot supply explicit class path option')
                    else:
                        continue
                vmArgs = args[:i]
                remainder = args[i:]
                return vmArgs, remainder

    if defaultAllVMArgs:
        return args, []
    else:
        return [], args

class ArgParser(ArgumentParser):
    # Override parent to append the list of available commands
    def format_help(self):
        return ArgumentParser.format_help(self) + _format_commands()


    def __init__(self, parents=None):
        self.parsed = False
        if not parents:
            parents = []
        ArgumentParser.__init__(self, prog='mx', parents=parents, add_help=len(parents) != 0)

        if len(parents) != 0:
            # Arguments are inherited from the parents
            return

        self.add_argument('-v', action='store_true', dest='verbose', help='enable verbose output')
        self.add_argument('-V', action='store_true', dest='very_verbose', help='enable very verbose output')
        self.add_argument('--no-warning', action='store_false', dest='warn', help='disable warning messages')
        self.add_argument('-y', action='store_const', const='y', dest='answer', help='answer \'y\' to all questions asked')
        self.add_argument('-n', action='store_const', const='n', dest='answer', help='answer \'n\' to all questions asked')
        self.add_argument('-p', '--primary-suite-path', help='set the primary suite directory', metavar='<path>')
        self.add_argument('--dbg', type=int, dest='java_dbg_port', help='make Java processes wait on <port> for a debugger', metavar='<port>')
        self.add_argument('-d', action='store_const', const=8000, dest='java_dbg_port', help='alias for "-dbg 8000"')
        self.add_argument('--attach', dest='attach', help='Connect to existing server running at [<address>:]<port>')
        self.add_argument('--backup-modified', action='store_true', help='backup generated files if they pre-existed and are modified')
        self.add_argument('--cp-pfx', dest='cp_prefix', help='class path prefix', metavar='<arg>')
        self.add_argument('--cp-sfx', dest='cp_suffix', help='class path suffix', metavar='<arg>')
        jargs = self.add_mutually_exclusive_group()
        jargs.add_argument('-J', dest='java_args', help='Java VM arguments (e.g. "-J-dsa")', metavar='<arg>')
        jargs.add_argument('--J', dest='java_args_legacy', help='Java VM arguments (e.g. "--J @-dsa")', metavar='@<args>')
        jpargs = self.add_mutually_exclusive_group()
        jpargs.add_argument('-P', action='append', dest='java_args_pfx', help='prefix Java VM arguments (e.g. "-P-dsa")', metavar='<arg>', default=[])
        jpargs.add_argument('--Jp', action='append', dest='java_args_pfx_legacy', help='prefix Java VM arguments (e.g. --Jp @-dsa)', metavar='@<args>', default=[])
        jaargs = self.add_mutually_exclusive_group()
        jaargs.add_argument('-A', action='append', dest='java_args_sfx', help='suffix Java VM arguments (e.g. "-A-dsa")', metavar='<arg>', default=[])
        jaargs.add_argument('--Ja', action='append', dest='java_args_sfx_legacy', help='suffix Java VM arguments (e.g. --Ja @-dsa)', metavar='@<args>', default=[])
        self.add_argument('--user-home', help='users home directory', metavar='<path>', default=os.path.expanduser('~'))
        self.add_argument('--java-home', help='primary JDK directory (must be JDK 7 or later)', metavar='<path>')
        self.add_argument('--jacoco', help='instruments selected classes using JaCoCo', default='off', choices=['off', 'on', 'append'])
        self.add_argument('--extra-java-homes', help='secondary JDK directories separated by "' + os.pathsep + '"', metavar='<path>')
        self.add_argument('--strict-compliance', action='store_true', dest='strict_compliance', help='observe Java compliance for projects that set it explicitly', default=False)
        self.add_argument('--ignore-project', action='append', dest='ignored_projects', help='name of project to ignore', metavar='<name>', default=[])
        self.add_argument('--kill-with-sigquit', action='store_true', dest='killwithsigquit', help='send sigquit first before killing child processes')
        self.add_argument('--suite', action='append', dest='specific_suites', help='limit command to given suite', metavar='<name>', default=[])
        self.add_argument('--src-suitemodel', help='mechanism for locating imported suites', metavar='<arg>')
        self.add_argument('--dst-suitemodel', help='mechanism for placing cloned/pushed suites', metavar='<arg>')
        self.add_argument('--primary', action='store_true', help='limit command to primary suite')
        self.add_argument('--dynamicimport', action='append', dest='dynamic_imports', help='dynamically import suite <name>', metavar='<name>', default=[])
        self.add_argument('--no-download-progress', action='store_true', help='disable download progress meter')
        self.add_argument('--version', action='store_true', help='print version and exit')
        self.add_argument('--mx-tests', action='store_true', help='load mxtests suite (mx debugging)')
        self.add_argument('--jdk', action='store', help='JDK to use for the "java" command', metavar='<tag:compliance>')
        self.add_argument('--version-conflict-resolution', dest='version_conflict_resolution', action='store', help='resolution mechanism used when a suite is imported with different versions', default='suite', choices=['suite', 'none', 'latest', 'ignore'])
        if get_os() != 'windows':
            # Time outs are (currently) implemented with Unix specific functionality
            self.add_argument('--timeout', help='timeout (in seconds) for command', type=int, default=0, metavar='<secs>')
            self.add_argument('--ptimeout', help='timeout (in seconds) for subprocesses', type=int, default=0, metavar='<secs>')

    def _parse_cmd_line(self, opts, firstParse):
        if firstParse:

            parser = ArgParser(parents=[self])
            parser.add_argument('initialCommandAndArgs', nargs=REMAINDER, metavar='command args...')

            # Legacy support - these options are recognized during first parse and
            # appended to the unknown options to be reparsed in the second parse
            parser.add_argument('--vm', action='store', dest='vm', help='the VM type to build/run')
            parser.add_argument('--vmbuild', action='store', dest='vmbuild', help='the VM build to build/run')


            # Parse the known mx global options and preserve the unknown args, command and
            # command args for the second parse.
            _, self.unknown = parser.parse_known_args(namespace=opts)

            if opts.version:
                print 'mx version ' + str(version)
                sys.exit(0)

            if opts.vm: self.unknown += ['--vm', opts.vm]
            if opts.vmbuild: self.unknown += ['--vmbuild', opts.vmbuild]

            self.initialCommandAndArgs = opts.__dict__.pop('initialCommandAndArgs')

            # For some reason, argparse considers an unknown argument starting with '-'
            # and containing a space as a positional argument instead of an optional
            # argument. We need to treat these as unknown optional arguments.
            while len(self.initialCommandAndArgs) > 0:
                arg = self.initialCommandAndArgs[0]
                if arg.startswith('-'):
                    assert ' ' in arg, arg
                    self.unknown.append(arg)
                    del self.initialCommandAndArgs[0]
                else:
                    break

            # Give the timeout options a default value to avoid the need for hasattr() tests
            opts.__dict__.setdefault('timeout', 0)
            opts.__dict__.setdefault('ptimeout', 0)

            if opts.java_args_legacy:
                opts.java_args = opts.java_args_legacy.lstrip('@')
            if opts.java_args_pfx_legacy:
                opts.java_args_pfx = [s.lstrip('@') for s in opts.java_args_pfx_legacy]
            if opts.java_args_sfx_legacy:
                opts.java_args_sfx = [s.lstrip('@') for s in opts.java_args_sfx_legacy]

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
                opts.strict_compliance = True

            global _primary_suite_path
            _primary_suite_path = opts.primary_suite_path or os.environ.get('MX_PRIMARY_SUITE_PATH')
            if _primary_suite_path:
                _primary_suite_path = os.path.abspath(_primary_suite_path)

            global _src_suitemodel, _dst_suitemodel
            _src_suitemodel = SuiteModel.create_suitemodel(opts, 'src')
            _dst_suitemodel = SuiteModel.create_suitemodel(opts, 'dst')

            # Communicate primary suite path to mx subprocesses
            if _primary_suite_path:
                os.environ['MX_PRIMARY_SUITE_PATH'] = _primary_suite_path

            opts.ignored_projects += os.environ.get('IGNORED_PROJECTS', '').split(',')

            mx_gate._jacoco = opts.jacoco
        else:
            parser = ArgParser(parents=[self])
            parser.add_argument('commandAndArgs', nargs=REMAINDER, metavar='command args...')
            args = self.unknown + self.initialCommandAndArgs
            parser.parse_args(args=args, namespace=opts)
            commandAndArgs = opts.__dict__.pop('commandAndArgs')
            if self.initialCommandAndArgs != commandAndArgs:
                abort('Suite specific global options must use name=value format: {0}={1}'.format(self.unknown[-1], self.initialCommandAndArgs[0]))
            self.parsed = True
            return commandAndArgs

def _format_commands():
    msg = '\navailable commands:\n\n'
    for cmd in sorted([k for k in _commands.iterkeys() if ':' not in k]) + sorted([k for k in _commands.iterkeys() if ':' in k]):
        c, _ = _commands[cmd][:2]
        doc = c.__doc__
        if doc is None:
            doc = ''
        msg += ' {0:<20} {1}\n'.format(cmd, doc.split('\n', 1)[0])
    return msg + '\n'

'''
A factory for creating JDKConfig objects.
'''
class JDKFactory(object):
    def getJDKConfig(self):
        nyi('getJDKConfig', self)

    def description(self):
        nyi('description', self)


def addJDKFactory(tag, compliance, factory):
    assert tag != DEFAULT_JDK_TAG
    complianceMap = _jdkFactories.setdefault(tag, {})
    complianceMap[compliance] = factory

def _getJDKFactory(tag, compliance):
    if tag not in _jdkFactories:
        return None
    complianceMap = _jdkFactories[tag]
    if not compliance:
        highestCompliance = sorted(complianceMap.iterkeys())[-1]
        return complianceMap[highestCompliance]
    if compliance not in complianceMap:
        return None
    return complianceMap[compliance]

'''
A namedtuple for the result of get_jdk_option().
'''
TagCompliance = namedtuple('TagCompliance', ['tag', 'compliance'])

_jdk_option = None
def get_jdk_option():
    '''
    Gets the tag and compliance (as a TagCompliance object) derived from the --jdk option.
    If the --jdk option was not specified, both fields of the returned tuple are None.
    '''
    global _jdk_option
    if _jdk_option is None:
        option = _opts.jdk
        if not option:
            option = os.environ.get('DEFAULT_JDK')
        if not option:
            jdktag = None
            jdkCompliance = None
        else:
            tag_compliance = option.split(':')
            if len(tag_compliance) == 1:
                if len(tag_compliance[0]) > 0:
                    if tag_compliance[0][0].isdigit():
                        jdktag = None
                        jdkCompliance = JavaCompliance(tag_compliance[0])
                    else:
                        jdktag = tag_compliance[0]
                        jdkCompliance = None
                else:
                    jdktag = None
                    jdkCompliance = None
            else:
                if len(tag_compliance) != 2 or not tag_compliance[0] or not tag_compliance[1]:
                    abort('Could not parse --jdk argument \'{}\' (should be of the form "[tag:]compliance")'.format(option))
                jdktag = tag_compliance[0]
                try:
                    jdkCompliance = JavaCompliance(tag_compliance[1])
                except AssertionError as e:
                    abort('Could not parse --jdk argument \'{}\' (should be of the form "[tag:]compliance")\n{}'.format(option, e))

        if jdktag and jdktag != DEFAULT_JDK_TAG:
            factory = _getJDKFactory(jdktag, jdkCompliance)
            if not factory:
                if len(_jdkFactories) == 0:
                    abort("No JDK providers available")
                available = []
                for t, m in _jdkFactories.iteritems():
                    for c in m:
                        available.append('{}:{}'.format(t, c))
                abort("No provider for '{}:{}' JDK (available: {})".format(jdktag, jdkCompliance if jdkCompliance else '*', ', '.join(available)))

        _jdk_option = TagCompliance(jdktag, jdkCompliance)
    return _jdk_option

_canceled_java_requests = set()

DEFAULT_JDK_TAG = 'default'

def get_jdk(versionCheck=None, purpose=None, cancel=None, versionDescription=None, tag=None, versionPerference=None, **kwargs):
    """
    Get a JDKConfig object matching the provided criteria.

    The JDK is selected by consulting the --jdk option, the --java-home option,
    the JAVA_HOME environment variable, the --extra-java-homes option and the
    EXTRA_JAVA_HOMES enviroment variable in that order.
    """
    # Precedence for JDK to use:
    # 1. --jdk option value
    # 2. JDK specified by set_java_command_default_jdk_tag
    # 3. JDK selected by DEFAULT_JDK_TAG tag

    if tag is None:
        jdkOpt = get_jdk_option()
        if versionCheck is None and jdkOpt.compliance:
            versionCheck, versionDescription = _convert_compliance_to_version_check(jdkOpt.compliance)
        tag = jdkOpt.tag if jdkOpt.tag else DEFAULT_JDK_TAG
    else:
        jdkOpt = TagCompliance(tag, None)

    defaultTag = tag == DEFAULT_JDK_TAG
    defaultJdk = defaultTag and versionCheck is None and not purpose

    # Backwards compatibility support
    if kwargs:
        assert len(kwargs) == 1 and 'defaultJdk' in kwargs, 'unsupported arguments: ' + str(kwargs)
        defaultJdk = kwargs['defaultJdk']

    if tag and not defaultTag:
        factory = _getJDKFactory(tag, jdkOpt.compliance)
        if factory:
            jdk = factory.getJDKConfig()
            if jdk.tag is not None:
                assert jdk.tag == tag
            else:
                jdk.tag = tag
        else:
            jdk = None
        return jdk

    # interpret string and compliance as compliance check
    if isinstance(versionCheck, types.StringTypes):
        requiredCompliance = JavaCompliance(versionCheck)
        versionCheck, versionDescription = _convert_compliance_to_version_check(requiredCompliance)
    elif isinstance(versionCheck, JavaCompliance):
        versionCheck, versionDescription = _convert_compliance_to_version_check(versionCheck)

    global _default_java_home, _extra_java_homes
    if cancel and (versionDescription, purpose) in _canceled_java_requests:
        return None

    if defaultJdk:
        if not _default_java_home:
            _default_java_home = _find_jdk(versionCheck=versionCheck, versionDescription=versionDescription, purpose=purpose, cancel=cancel, isDefaultJdk=True)
            if not _default_java_home:
                assert cancel and (versionDescription or purpose)
                _canceled_java_requests.add((versionDescription, purpose))
        return _default_java_home

    for java in _extra_java_homes:
        if not versionCheck or versionCheck(java.version):
            return java

    jdk = _find_jdk(versionCheck=versionCheck, versionDescription=versionDescription, purpose=purpose, cancel=cancel, isDefaultJdk=False)
    if jdk:
        assert jdk not in _extra_java_homes
        _extra_java_homes = _sorted_unique_jdk_configs(_extra_java_homes + [jdk])
    else:
        assert cancel and (versionDescription or purpose)
        _canceled_java_requests.add((versionDescription, purpose))
    return jdk

def _convert_compliance_to_version_check(requiredCompliance):
    if _opts.strict_compliance:
        versionDesc = str(requiredCompliance)
        versionCheck = requiredCompliance.exactMatch
    else:
        versionDesc = '>=' + str(requiredCompliance)
        compVersion = VersionSpec(str(requiredCompliance))
        versionCheck = lambda version: version >= compVersion
    return (versionCheck, versionDesc)

def _find_jdk(versionCheck=None, versionDescription=None, purpose=None, cancel=None, isDefaultJdk=False):
    '''
    Selects a JDK and returns a JDKConfig object representing it.

    First a selection is attempted from the --java-home option, the JAVA_HOME
    environment variable, the --extra-java-homes option and the EXTRA_JAVA_HOMES
    enviroment variable in that order.

    If that produces no valid JDK, then a set of candidate JDKs is built by searching
    the OS-specific locations in which JDKs are normally installed. These candidates
    are filtered by the 'versionCheck' predicate function. The predicate is described
    by the string in 'versionDescription' (e.g. ">= 1.8 and < 1.8.0u20 or >= 1.8.0u40").
    If 'versionCheck' is None, no filtering is performed.

    If running interactively, the user is prompted to select from one of the candidates
    or "<other>". The selection prompt message includes the value of 'purpose' if it is not None.
    If 'cancel' is not None, the user is also given a choice to make no selection,
    the consequences of which are described by 'cancel'. If a JDK is selected, it is returned.
    If the user cancels, then None is returned. If "<other>" is chosen, the user is repeatedly
    prompted for a path to a JDK until a valid path is provided at which point a corresponding
    JDKConfig object is returned. Before returning the user is given the option to persist
    the selected JDK in file "env" in the primary suite's mx directory. The choice will be
    saved as the value for JAVA_HOME if 'isDefaultJdk' is true, otherwise it is set or
    appended to the value for EXTRA_JAVA_HOMES.

    If not running interactively, the first candidate is returned or None if there are no
    candidates.
    '''
    assert (versionDescription and versionCheck) or (not versionDescription and not versionCheck)
    if not versionCheck:
        versionCheck = lambda v: True

    candidateJdks = []
    source = ''
    if _opts and _opts.java_home:
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
        configs = _find_available_jdks(versionCheck)
    elif isDefaultJdk:  # we found something in EXTRA_JAVA_HOMES but we want to set JAVA_HOME, look for further options
        configs = [result] + _find_available_jdks(versionCheck)
    else:
        if not isDefaultJdk:
            return result
        configs = [result]

    configs = _sorted_unique_jdk_configs(configs)

    if len(configs) > 1:
        if not is_interactive():
            msg = "Multiple possible choices for a JDK"
            if purpose:
                msg += ' for ' + purpose
            msg += ': '
            if versionDescription:
                msg += '(version ' + versionDescription + ')'
            selected = configs[0]
            msg += ". Selecting " + str(selected)
            log(msg)
        else:
            msg = 'Please select a '
            if isDefaultJdk:
                msg += 'default '
            msg += 'JDK'
            if purpose:
                msg += ' for ' + purpose
            msg += ': '
            if versionDescription:
                msg += '(version ' + versionDescription + ')'
            log(msg)
            choices = configs + ['<other>']
            if cancel:
                choices.append('Cancel (' + cancel + ')')

            selected = select_items(choices, allowMultiple=False)
            if isinstance(selected, types.StringTypes):
                if selected == '<other>':
                    selected = None
                if cancel and selected == 'Cancel (' + cancel + ')':
                    return None
    elif len(configs) == 1:
        selected = configs[0]
        msg = 'Selected ' + str(selected) + ' as '
        if isDefaultJdk:
            msg += 'default '
        msg += 'JDK'
        if versionDescription:
            msg = msg + ' ' + versionDescription
        if purpose:
            msg += ' for ' + purpose
        log(msg)
    else:
        msg = 'Could not find any JDK'
        if purpose:
            msg += ' for ' + purpose
        msg += ' '
        if versionDescription:
            msg = msg + '(version ' + versionDescription + ')'
        log(msg)
        selected = None

    while not selected:
        if not is_interactive():
            return None
        jdkLocation = raw_input('Enter path of JDK: ')
        selected = _find_jdk_in_candidates([jdkLocation], versionCheck, warn=True)
        if not selected:
            assert versionDescription
            log("Error: No JDK found at '" + jdkLocation + "' compatible with version " + versionDescription)

    varName = 'JAVA_HOME' if isDefaultJdk else 'EXTRA_JAVA_HOMES'
    allowMultiple = not isDefaultJdk
    valueSeparator = os.pathsep if allowMultiple else None
    ask_persist_env(varName, selected.home, valueSeparator)

    os.environ[varName] = selected.home

    return selected

def ask_persist_env(varName, value, valueSeparator=None):
    if not _primary_suite:
        def _deferrable():
            assert _primary_suite
            ask_persist_env(varName, value, valueSeparator)
        _primary_suite_deferrables.append(_deferrable)
        return

    envPath = join(_primary_suite.mxDir, 'env')
    if is_interactive() and ask_yes_no('Persist this setting by adding "{0}={1}" to {2}'.format(varName, value, envPath), 'y'):
        envLines = []
        if exists(envPath):
            with open(envPath) as fp:
                append = True
                for line in fp:
                    if line.rstrip().startswith(varName):
                        _, currentValue = line.split('=', 1)
                        currentValue = currentValue.strip()
                        if not valueSeparator and currentValue:
                            if not ask_yes_no('{0} is already set to {1}, overwrite with {2}?'.format(varName, currentValue, value), 'n'):
                                return
                            else:
                                line = varName + '=' + value + os.linesep
                        else:
                            line = line.rstrip()
                            if currentValue:
                                line += valueSeparator
                            line += value + os.linesep
                        append = False
                    if not line.endswith(os.linesep):
                        line += os.linesep
                    envLines.append(line)
        else:
            append = True

        if append:
            envLines.append(varName + '=' + value + os.linesep)

        with open(envPath, 'w') as fp:
            for line in envLines:
                fp.write(line)

_os_jdk_locations = {
    'darwin': {
        'bases': ['/Library/Java/JavaVirtualMachines'],
        'suffix': 'Contents/Home'
    },
    'linux': {
        'bases': [
            '/usr/lib/jvm',
            '/usr/java'
        ]
    },
    'openbsd': {
        'bases': ['/usr/local/']
    },
    'solaris': {
        'bases': ['/usr/jdk/instances']
    },
    'windows': {
        'bases': [r'C:\Program Files\Java']
    },
}

def _find_available_jdks(versionCheck):
    candidateJdks = []
    os_name = get_os()
    if os_name in _os_jdk_locations:
        jdkLocations = _os_jdk_locations[os_name]
        for base in jdkLocations['bases']:
            if exists(base):
                if 'suffix' in jdkLocations:
                    suffix = jdkLocations['suffix']
                    candidateJdks += [join(base, n, suffix) for n in os.listdir(base)]
                else:
                    candidateJdks += [join(base, n) for n in os.listdir(base)]

    return _filtered_jdk_configs(candidateJdks, versionCheck)

def _sorted_unique_jdk_configs(configs):
    path_seen = set()
    unique_configs = [c for c in configs if c.home not in path_seen and not path_seen.add(c.home)]

    def _compare_configs(c1, c2):
        if c1 == _default_java_home:
            if c2 != _default_java_home:
                return 1
        elif c2 == _default_java_home:
            return -1
        if c1 in _extra_java_homes:
            if c2 not in _extra_java_homes:
                return 1
        elif c2 in _extra_java_homes:
            return -1
        return VersionSpec.__cmp__(c1.version, c2.version)
    return sorted(unique_configs, cmp=_compare_configs, reverse=True)

def is_interactive():
    if get_env('CONTINUOUS_INTEGRATION'):
        return False
    return sys.__stdin__.isatty()

def _filtered_jdk_configs(candidates, versionCheck, warn=False, source=None):
    filtered = []
    for candidate in candidates:
        try:
            config = JDKConfig(candidate)
            if versionCheck(config.version):
                filtered.append(config)
        except JDKConfigException as e:
            if warn and source:
                log('Path in ' + source + "' is not pointing to a JDK (" + e.message + ")")
    return filtered

def _find_jdk_in_candidates(candidates, versionCheck, warn=False, source=None):
    filtered = _filtered_jdk_configs(candidates, versionCheck, warn, source)
    if filtered:
        return filtered[0]
    return None

def find_classpath_arg(vmArgs):
    """
    Searches for the last class path argument in `vmArgs` and returns its
    index and value as a tuple. If no class path argument is found, then
    the tuple (None, None) is returned.
    """
    # If the last argument is '-cp' or '-classpath' then it is not
    # valid since the value is missing. As such, we ignore the
    # last argument.
    for index in reversed(range(len(vmArgs) - 1)):
        if vmArgs[index] in ['-cp', '-classpath']:
            return index + 1, vmArgs[index + 1]
    return None, None

_java_command_default_jdk_tag = None

def set_java_command_default_jdk_tag(tag):
    global _java_command_default_jdk_tag
    assert _java_command_default_jdk_tag is None, 'TODO: need policy for multiple attempts to set the default JDK for the "java" command'
    _java_command_default_jdk_tag = tag

def java_command(args):
    """
    run the java executable in the selected JDK.
    See get_jdk for details on JDK selection.
    """
    run_java(args)

def run_java(args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None, addDefaultArgs=True, jdk=None):
    """
    Runs a Java program by executing the java executable in a JDK.
    """
    if jdk is None:
        jdk = get_jdk()
    return jdk.run_java(args, nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, cwd=cwd, timeout=timeout, env=env, addDefaultArgs=addDefaultArgs)

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

def run_maven(args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None):
    mavenCommand = 'mvn'
    mavenHome = os.getenv('MAVEN_HOME')
    if mavenHome:
        mavenCommand = join(mavenHome, 'bin', mavenCommand)
    return run([mavenCommand] + args, nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, timeout=timeout, env=env, cwd=cwd)

def run_mx(args, suite=None, nonZeroIsFatal=True, out=None, err=None, timeout=None, env=None):
    commands = [sys.executable, join(_mx_home, 'mx.py')]
    cwd = None
    if suite:
        commands += ['-p', suite.dir]
        cwd = suite.dir
    return run(commands + args, nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, timeout=timeout, env=env, cwd=cwd)

def run(args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None, **kwargs):
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
            if '\n' in arg:
                abort("nyi")
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
        p = subprocess.Popen(args, cwd=cwd, stdout=stdout, stderr=stderr, preexec_fn=preexec_fn, creationflags=creationflags, env=env, **kwargs)
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
    if os in ['darwin', 'linux', 'openbsd', 'solaris']:
        return 'lib' + name
    return name

def add_lib_suffix(name):
    """
    Adds the platform specific library suffix to a name
    """
    os = get_os()
    if os == 'windows':
        return name + '.dll'
    if os in ['linux', 'openbsd', 'solaris']:
        return name + '.so'
    if os == 'darwin':
        return name + '.dylib'
    return name

def add_debug_lib_suffix(name):
    """
    Adds the platform specific library suffix to a name
    """
    os = get_os()
    if os == 'windows':
        return name + '.pdb'
    if os in ['linux', 'openbsd', 'solaris']:
        return name + '.debuginfo'
    if os == 'darwin':
        return name + '.dylib.dSYM'
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
        m = re.match(r'(?:1\.)?(\d+).*', ver)
        assert m is not None, 'not a recognized version string: ' + ver
        self.value = int(m.group(1))

    def __str__(self):
        return '1.' + str(self.value)

    def __repr__(self):
        return str(self)

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
        self.parts = tuple((int(f) if f.isdigit() else f for f in re.split(separator, versionString)))
        i = len(self.parts)
        while i > 0 and self.parts[i - 1] == 0:
            i -= 1
        self.strippedParts = tuple(list(self.parts)[:i])

    def __str__(self):
        return self.versionString

    def __cmp__(self, other):
        return cmp(self.strippedParts, other.strippedParts)

    def __hash__(self):
        return self.parts.__hash__()

    def __eq__(self, other):
        return isinstance(other, VersionSpec) and self.strippedParts == other.strippedParts

def _filter_non_existant_paths(paths):
    if paths:
        return os.pathsep.join([path for path in _separatedCygpathW2U(paths).split(os.pathsep) if exists(path)])
    return None

class JDKConfigException(Exception):
    def __init__(self, value):
        Exception.__init__(self, value)

"""
A JDKConfig object encapsulates info about an installed or deployed JDK.
"""
class JDKConfig:
    def __init__(self, home, tag=None):
        self.home = home
        self.tag = tag
        self.jar = exe_suffix(join(self.home, 'bin', 'jar'))
        self.java = exe_suffix(join(self.home, 'bin', 'java'))
        self.javac = exe_suffix(join(self.home, 'bin', 'javac'))
        self.javap = exe_suffix(join(self.home, 'bin', 'javap'))
        self.javadoc = exe_suffix(join(self.home, 'bin', 'javadoc'))
        self.pack200 = exe_suffix(join(self.home, 'bin', 'pack200'))
        self.toolsjar = join(self.home, 'lib', 'tools.jar')
        self._classpaths_initialized = False
        self._bootclasspath = None
        self._extdirs = None
        self._endorseddirs = None
        self._knownJavacLints = None

        if not exists(self.java):
            raise JDKConfigException('Java launcher does not exist: ' + self.java)
        if not exists(self.javac):
            raise JDKConfigException('Javac launcher does not exist: ' + self.java)

        self.java_args = shlex.split(_opts.java_args) if _opts.java_args else []
        self.java_args_pfx = sum(map(shlex.split, _opts.java_args_pfx), [])
        self.java_args_sfx = sum(map(shlex.split, _opts.java_args_sfx), [])

        # Prepend the -d64 VM option only if the java command supports it
        try:
            output = subprocess.check_output([self.java, '-d64', '-version'], stderr=subprocess.STDOUT)
            self.java_args = ['-d64'] + self.java_args
        except subprocess.CalledProcessError as e:
            try:
                output = subprocess.check_output([self.java, '-version'], stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                raise JDKConfigException('{}: {}'.format(e.returncode, e.output))

        def _checkOutput(out):
            return 'java version' in out

        # hotspot can print a warning, e.g. if there's a .hotspot_compiler file in the cwd
        output = output.split('\n')
        version = None
        for o in output:
            if _checkOutput(o):
                assert version is None
                version = o

        def _checkOutput0(out):
            return 'version' in out

        # fall back: check for 'version' if there is no 'java version' string
        if not version:
            for o in output:
                if _checkOutput0(o):
                    assert version is None
                    version = o

        self.version = VersionSpec(version.split()[2].strip('"'))
        self.javaCompliance = JavaCompliance(self.version.versionString)

        attach = None
        if _opts.attach is not None:
            attach = 'server=n,address=' + _opts.attach
        else:
            if _opts.java_dbg_port is not None:
                attach = 'server=y,address=' + str(_opts.java_dbg_port)

        if attach is not None:
            self.java_args += ['-Xdebug', '-Xrunjdwp:transport=dt_socket,' + attach + ',suspend=y']

    def _init_classpaths(self):
        if not self._classpaths_initialized:
            _, binDir = _compile_mx_class('ClasspathDump', jdk=self)
            self._bootclasspath, self._extdirs, self._endorseddirs = [x if x != 'null' else None for x in subprocess.check_output([self.java, '-cp', _cygpathU2W(binDir), 'ClasspathDump'], stderr=subprocess.PIPE).split('|')]
            if self.javaCompliance <= JavaCompliance('1.8'):
                # All 3 system properties accessed by ClasspathDump are expected to exist
                if not self._bootclasspath or not self._extdirs or not self._endorseddirs:
                    warn("Could not find all classpaths: boot='" + str(self._bootclasspath) + "' extdirs='" + str(self._extdirs) + "' endorseddirs='" + str(self._endorseddirs) + "'")
            self._bootclasspath_unfiltered = self._bootclasspath
            self._bootclasspath = _filter_non_existant_paths(self._bootclasspath)
            self._extdirs = _filter_non_existant_paths(self._extdirs)
            self._endorseddirs = _filter_non_existant_paths(self._endorseddirs)
            self._classpaths_initialized = True

    def __repr__(self):
        return "JDKConfig(" + str(self.home) + ")"

    def __str__(self):
        return "Java " + str(self.version) + " (" + str(self.javaCompliance) + ") from " + str(self.home)

    def __hash__(self):
        return hash(self.home)

    def __cmp__(self, other):
        if other is None:
            return False
        if isinstance(other, JDKConfig):
            compilanceCmp = cmp(self.javaCompliance, other.javaCompliance)
            if compilanceCmp:
                return compilanceCmp
            versionCmp = cmp(self.version, other.version)
            if versionCmp:
                return versionCmp
            return cmp(self.home, other.home)
        raise TypeError()

    def processArgs(self, args, addDefaultArgs=True):
        '''
        Return a list composed of the arguments specified by the -P, -J and -A options (in that order)
        prepended to 'args' if 'addDefaultArgs' is true otherwise just return 'args'.
        '''
        if addDefaultArgs:
            return self.java_args_pfx + self.java_args + self.java_args_sfx + args
        return args

    def run_java(self, args, nonZeroIsFatal=True, out=None, err=None, cwd=None, timeout=None, env=None, addDefaultArgs=True):
        cmd = [self.java] + self.processArgs(args, addDefaultArgs=addDefaultArgs)
        return run(cmd, nonZeroIsFatal=nonZeroIsFatal, out=out, err=err, cwd=cwd)

    def bootclasspath(self, filtered=True):
        self._init_classpaths()
        return _separatedCygpathU2W(self._bootclasspath if filtered else self._bootclasspath_unfiltered)

    """
    Add javadoc style options for the library paths of this JDK.
    """
    def javadocLibOptions(self, args):
        self._init_classpaths()
        if args is None:
            args = []
        if self._bootclasspath:
            args.append('-bootclasspath')
            args.append(_separatedCygpathU2W(self._bootclasspath))
        if self._extdirs:
            args.append('-extdirs')
            args.append(_separatedCygpathU2W(self._extdirs))
        return args

    """
    Add javac style options for the library paths of this JDK.
    """
    def javacLibOptions(self, args):
        args = self.javadocLibOptions(args)
        if self._endorseddirs:
            args.append('-endorseddirs')
            args.append(_separatedCygpathU2W(self._endorseddirs))
        return args

    def hasJarOnClasspath(self, jar):
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

    def getKnownJavacLints(self):
        '''
        Gets the lint warnings supported by this JDK.
        '''
        if self._knownJavacLints is None:
            out = subprocess.check_output([self.javac, '-X'], stderr=subprocess.STDOUT)
            if self.javaCompliance < JavaCompliance('1.9'):
                lintre = re.compile(r"-Xlint:\{([a-z-]+(?:,[a-z-]+)*)\}")
                m = lintre.search(out)
                if not m:
                    self._knownJavacLints = []
                else:
                    self._knownJavacLints = m.group(1).split(',')
            else:
                self._knownJavacLints = []
                lines = out.split(os.linesep)
                inLintSection = False
                for line in lines:
                    if not inLintSection:
                        if line.strip() == '-Xlint:key,...':
                            inLintSection = True
                    else:
                        if line.startswith('         '):
                            warning = line.split()[0]
                            self._knownJavacLints.append(warning)
                            self._knownJavacLints.append('-' + warning)
                        elif line.strip().startswith('-X'):
                            return self._knownJavacLints
                warn('Did not find lint warnings in output of "javac -X"')
        return self._knownJavacLints

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

def logvv(msg=None):
    if _opts.very_verbose:
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
    '''
    Replaces each "@" prefixed element in the class path 'cpArg' with
    the class path for the dependency named by the element without the "@" prefix.
    '''
    if '@' not in cpArg:
        return cpArg
    cp = []
    for part in cpArg.split(os.pathsep):
        if part.startswith('@'):
            cp += classpath(part[1:]).split(os.pathsep)
        else:
            cp.append(part)
    return os.pathsep.join(cp)

def expand_project_in_args(args, insitu=True):
    '''
    Looks for the first -cp or -classpath argument in 'args' and
    calls expand_project_in_class_path_arg on it. If 'insitu' is true,
    then 'args' is updated in place otherwise a copy of 'args' is modified.
    The updated object is returned.
    '''
    for i in range(len(args)):
        if args[i] == '-cp' or args[i] == '-classpath':
            if i + 1 < len(args):
                if not insitu:
                    args = list(args) # clone args
                args[i + 1] = expand_project_in_class_path_arg(args[i + 1])
            break
    return args

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

def abort(codeOrMessage, context=None):
    """
    Aborts the program with a SystemExit exception.
    If 'codeOrMessage' is a plain integer, it specifies the system exit status;
    if it is None, the exit status is zero; if it has another type (such as a string),
    the object's value is printed and the exit status is 1.

    The 'context' argument can provide extra context for an error message.
    If 'context' is callable, it is called and the returned value is printed.
    If 'context' defines a __abort_context__ method, the latter is called and
    its return value is printed. Otherwise str(context) is printed.
    """

    if _opts and hasattr(_opts, 'killwithsigquit') and _opts.killwithsigquit:
        _send_sigquit()

    def is_alive(p):
        if isinstance(p, subprocess.Popen):
            return p.poll() is None
        assert is_jython() or isinstance(p, multiprocessing.Process), p
        return p.is_alive()

    for p, args in _currentSubprocesses:
        if is_alive(p):
            p.terminate()
            time.sleep(0.1)
        if is_alive(p):
            try:
                if get_os() == 'windows':
                    p.terminate()
                else:
                    _kill_process_group(p.pid, signal.SIGKILL)
            except BaseException as e:
                if is_alive(p):
                    log('error while killing subprocess {0} "{1}": {2}'.format(p.pid, ' '.join(args), e))

    if _opts and hasattr(_opts, 'verbose') and _opts.verbose:
        import traceback
        traceback.print_stack()
    if context is not None:
        if callable(context):
            contextMsg = context()
        elif hasattr(context, '__abort_context__'):
            contextMsg = context.__abort_context__()
        else:
            contextMsg = str(context)

        if contextMsg:
            if isinstance(codeOrMessage, int):
                # Log the context separately so that SystemExit
                # communicates the intended exit status
                log(contextMsg)
            else:
                codeOrMessage = contextMsg + ":\n" + codeOrMessage
    raise SystemExit(codeOrMessage)

def download(path, urls, verbose=False, abortOnError=True):
    """
    Attempts to downloads content for each URL in a list, stopping after the first successful download.
    If the content cannot be retrieved from any URL, the program is aborted, unless abortOnError=False.
    The downloaded content is written to the file indicated by 'path'.
    """
    d = dirname(path)
    if d != '':
        ensure_dir_exists(d)

    assert not path.endswith(os.sep)

    _, binDir = _compile_mx_class('URLConnectionDownload')
    command = [get_jdk(tag=DEFAULT_JDK_TAG).java, '-cp', _cygpathU2W(binDir), 'URLConnectionDownload']
    if _opts.no_download_progress or not sys.stderr.isatty():
        command.append('--no-progress')
    command.append(_cygpathU2W(path))
    command += urls
    if run(command, nonZeroIsFatal=False) == 0:
        return True

    if abortOnError:
        abort('Could not download to ' + path + ' from any of the following URLs:\n\n    ' +
              '\n    '.join(urls) + '\n\nPlease use a web browser to do the download manually')
    else:
        return False

def update_file(path, content, showDiff=False):
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

        if existed:
            log('modified ' + path)
            if _opts.backup_modified:
                log('backup ' + path + '.orig')
            if showDiff:
                log('diff: ' + path)
                log(''.join(difflib.unified_diff(old.splitlines(1), content.splitlines(1))))

        else:
            log('created ' + path)
        return True
    except IOError as e:
        abort('Error while writing to ' + path + ': ' + str(e))

# Builtin commands

def _defaultEcjPath():
    return get_env('JDT')

def build(args, parser=None):
    """builds the artifacts of one or more dependencies"""

    suppliedParser = parser is not None
    if not suppliedParser:
        parser = ArgumentParser(prog='mx build')

    parser = parser if parser is not None else ArgumentParser(prog='mx build')
    parser.add_argument('-f', action='store_true', dest='force', help='force build (disables timestamp checking)')
    parser.add_argument('-c', action='store_true', dest='clean', help='removes existing build output')
    parallelize = parser.add_mutually_exclusive_group()
    parallelize.add_argument('-n', '--serial', action='store_const', const=False, dest='parallelize', help='serialize Java compilation')
    parallelize.add_argument('-p', action='store_const', const=True, dest='parallelize', help='parallelize Java compilation (default)')
    parser.add_argument('-s', '--shallow-dependency-checks', action='store_const', const=True, help="ignore modification times "\
                        "of output files for each of P's dependencies when determining if P should be built. That "\
                        "is, only P's sources, suite.py of its suite and whether any of P's dependencies have "\
                        "been built are considered. This is useful when an external tool (such as an Eclipse) performs incremental "\
                        "compilation that produces finer grained modification times than mx's build system. Shallow "\
                        "dependency checking only applies to non-native projects. This option can be also set by defining" \
                        "the environment variable MX_BUILD_SHALLOW_DEPENDENCY_CHECKS to true.")
    parser.add_argument('--source', dest='compliance', help='Java compliance level for projects without an explicit one')
    parser.add_argument('--Wapi', action='store_true', dest='warnAPI', help='show warnings about using internal APIs')
    parser.add_argument('--dependencies', '--projects', action='store', help='comma separated dependencies to build (omit to build all dependencies)', metavar='<names>')
    parser.add_argument('--only', action='store', help='comma separated dependencies to build, without checking their dependencies (omit to build all dependencies)')
    parser.add_argument('--no-java', action='store_false', dest='java', help='do not build Java projects')
    parser.add_argument('--no-native', action='store_false', dest='native', help='do not build native projects')
    parser.add_argument('--no-javac-crosscompile', action='store_false', dest='javac_crosscompile', help="Use javac from each project's compliance levels rather than perform a cross compilation using the default JDK")
    parser.add_argument('--warning-as-error', '--jdt-warning-as-error', action='store_true', help='convert all Java compiler warnings to errors')
    parser.add_argument('--jdt-show-task-tags', action='store_true', help='show task tags as Eclipse batch compiler warnings')
    parser.add_argument('--alt-javac', dest='alt_javac', help='path to alternative javac executable', metavar='<path>')
    parser.add_argument('-A', dest='extra_javac_args', action='append', help='pass <flag> directly to Java source compiler', metavar='<flag>', default=[])
    compilerSelect = parser.add_mutually_exclusive_group()
    compilerSelect.add_argument('--error-prone', dest='error_prone', help='path to error-prone.jar', metavar='<path>')
    compilerSelect.add_argument('--jdt', help='path to a stand alone Eclipse batch compiler jar (e.g. ecj.jar). ' +
                                'This can also be specified with the JDT environment variable.', default=_defaultEcjPath(), metavar='<path>')
    compilerSelect.add_argument('--force-javac', action='store_true', dest='force_javac', help='use javac even if an Eclipse batch compiler jar is specified')

    if suppliedParser:
        parser.add_argument('remainder', nargs=REMAINDER, metavar='...')

    args = parser.parse_args(args)

    if get_os() == 'windows':
        if args.parallelize:
            warn('parallel builds are not supported on windows: can not use -p')
            args.parallelize = False
    else:
        if args.parallelize is None:
            # Enable parallel compilation by default
            args.parallelize = True

    if is_jython():
        if args.parallelize:
            warn('multiprocessing not available in jython: can not use -p')
            args.parallelize = False

    if not args.force_javac and args.jdt is not None:
        if not args.jdt.endswith('.jar'):
            abort('Path for Eclipse batch compiler does not look like a jar file: ' + args.jdt)
        if not exists(args.jdt):
            abort('Eclipse batch compiler jar does not exist: ' + args.jdt)
        else:
            with zipfile.ZipFile(args.jdt, 'r') as zf:
                if 'org/eclipse/jdt/internal/compiler/apt/' not in zf.namelist():
                    abort('Specified Eclipse compiler does not include annotation processing support. ' +
                          'Ensure you are using a stand alone ecj.jar, not org.eclipse.jdt.core_*.jar ' +
                          'from within the plugins/ directory of an Eclipse IDE installation.')
    if args.only is not None:
        # N.B. This build will not respect any dependencies (including annotation processor dependencies)
        names = args.only.split(',')
        roots = [dependency(name) for name in names]
    elif args.dependencies is not None:
        if len(args.dependencies) == 0:
            abort('The value of the --dependencies argument cannot be the empty string')
        names = args.dependencies.split(',')
        roots = [dependency(name) for name in names]
    else:
        # Omit Libraries so that only the ones required to build other
        # dependencies are downloaded
        roots = [d for d in dependencies() if not d.isLibrary()]

    if roots:
        roots = _dependencies_opt_limit_to_suites(roots)
        # N.B. Limiting to a suite only affects the starting set of dependencies. Dependencies in other suites will still be built

    sortedTasks = []
    taskMap = {}
    depsMap = {}

    def _createTask(dep, edge):
        task = dep.getBuildTask(args)
        assert task.subject not in taskMap
        sortedTasks.append(task)
        taskMap[dep] = task
        lst = depsMap.setdefault(dep, [])
        for d in lst:
            task.deps.append(taskMap[d])

    def _registerDep(src, edgeType, dst):
        lst = depsMap.setdefault(src, [])
        lst.append(dst)

    walk_deps(visit=_createTask, visitEdge=_registerDep, roots=roots, ignoredEdges=[DEP_EXCLUDED])

    if _opts.verbose:
        log("++ Serialized build plan ++")
        for task in sortedTasks:
            if task.deps:
                log(str(task) + " [depends on " + ', '.join([str(t.subject) for t in task.deps]) + ']')
            else:
                log(str(task))
        log("-- Serialized build plan --")

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
                    t.pullSharedMemoryState()
                    t.cleanSharedMemoryState()
                    t._finished = True
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
            return d

        def sortWorklist(tasks):
            for t in tasks:
                t._d = None
            return sorted(tasks, compareTasks)

        cpus = cpu_count()
        worklist = sortWorklist(sortedTasks)
        active = []
        failed = []
        def _activeCpus():
            cpus = 0
            for t in active:
                cpus += t.parallelism
            return cpus
        while len(worklist) != 0:
            while True:
                active, failed = checkTasks(active)
                if len(failed) != 0:
                    assert not active, active
                    break
                if _activeCpus() >= cpus:
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
                task.pushSharedMemoryState()

            def depsDone(task):
                for d in task.deps:
                    if d.proc is None or not d._finished:
                        return False
                return True

            for task in worklist:
                if depsDone(task) and _activeCpus() + task.parallelism <= cpus:
                    worklist.remove(task)
                    task.initSharedMemoryState()
                    task.proc = multiprocessing.Process(target=executeTask, args=(task,))
                    task._finished = False
                    task.proc.start()
                    active.append(task)
                    task.sub = _addSubprocess(task.proc, [str(task)])
                if _activeCpus() >= cpus:
                    break

            worklist = sortWorklist(worklist)

        failed += joinTasks(active)
        if len(failed):
            for t in failed:
                log('{0} failed'.format(t))
            abort('{0} build tasks failed'.format(len(failed)))
    else:  # not parallelize
        for t in sortedTasks:
            t.execute()

    # TODO check for distributions overlap (while loading suites?)

    if suppliedParser:
        return args
    return None

def build_suite(s):
    '''build all projects in suite (for dynamic import)'''
    # Note we must use the "build" method in "s" and not the one
    # in the dict. If there isn't one we use mx.build
    project_names = [p.name for p in s.projects]
    if hasattr(s.extensions, 'build'):
        build_command = s.extensions.build
    else:
        build_command = build
    build_command(['--dependencies', ','.join(project_names)])

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
    if args.projects is not None:
        projectsToProcess = [project(name) for name in args.projects.split(',')]
    else:
        projectsToProcess = projects(True)

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
    for p in projectsToProcess:
        if not p.isJavaProject():
            continue
        sourceDirs = p.source_dirs()

        batch = Batch(join(p.dir, '.settings'))

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
        for chunk in _chunk_files_for_command_line(javafiles, pathFunction=lambda f: f.path):
            run([args.eclipse_exe,
                '-nosplash',
                '-application',
                'org.eclipse.jdt.core.JavaCodeFormatter',
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
    """
    Builds all distributions in this suite that define one or more annotation processors.
    Returns the jar files for the built distributions.
    """
    apDists = [d for d in s.dists if d.isJARDistribution() and d.definedAnnotationProcessors]
    if not apDists:
        return []

    names = [ap.name for ap in apDists]
    build(['--dependencies', ",".join(names)])
    return [ap.path for ap in apDists]

@primary_suite_exempt
def pylint(args):
    """run pylint (if available) over Python source files (found by '<vc> locate' or by tree walk with -walk)"""

    parser = ArgumentParser(prog='mx pylint')
    _add_command_primary_option(parser)
    parser.add_argument('--walk', action='store_true', help='use tree walk find .py files')
    args = parser.parse_args(args)

    rcfile = join(dirname(__file__), '.pylintrc')
    if not exists(rcfile):
        log('pylint configuration file does not exist: ' + rcfile)
        return -1

    try:
        output = subprocess.check_output(['pylint', '--version'], stderr=subprocess.STDOUT)
        m = re.match(r'.*pylint (\d+)\.(\d+)\.(\d+).*', output, re.DOTALL)
        if not m:
            log('could not determine pylint version from ' + output)
            return -1
        major, minor, micro = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if major != 1 or minor != 1:
            log('require pylint version = 1.1.x (got {0}.{1}.{2})'.format(major, minor, micro))
            return -1
    except BaseException as e:
        log('pylint is not available: ' + str(e))
        return -1

    def findfiles_by_walk(pyfiles):
        for suite in suites(True, includeBinary=False):
            if args.primary and not suite.primary:
                continue
            for root, dirs, files in os.walk(suite.dir):
                for f in files:
                    if f.endswith('.py'):
                        pyfile = join(root, f)
                        pyfiles.append(pyfile)
                if 'bin' in dirs:
                    dirs.remove('bin')
                if 'lib' in dirs:
                    # avoids downloaded .py files
                    dirs.remove('lib')

    def findfiles_by_vc(pyfiles):
        for suite in suites(True, includeBinary=False):
            if args.primary and not suite.primary:
                continue
            files = suite.vc.locate(suite.dir, ['*.py'])
            for pyfile in files:
                if exists(pyfile):
                    pyfiles.append(pyfile)

    pyfiles = []

    # Process mxtool's own py files only if mx is the primary suite
    if _primary_suite is _mx_suite:
        for root, _, files in os.walk(dirname(__file__)):
            for f in files:
                if f.endswith('.py'):
                    pyfile = join(root, f)
                    pyfiles.append(pyfile)
    if args.walk:
        findfiles_by_walk(pyfiles)
    else:
        findfiles_by_vc(pyfiles)

    env = os.environ.copy()

    pythonpath = dirname(__file__)
    for suite in suites(True):
        pythonpath = os.pathsep.join([pythonpath, suite.mxDir])

    env['PYTHONPATH'] = pythonpath

    for pyfile in pyfiles:
        log('Running pylint on ' + pyfile + '...')
        run(['pylint', '--reports=n', '--rcfile=' + rcfile, pyfile], env=env)

    return 0

"""
Utility for creating and updating a zip or tar file atomically.
"""
class Archiver:
    def __init__(self, path, kind='zip'):
        self.path = path
        self.kind = kind

    def __enter__(self):
        if self.path:
            ensure_dir_exists(dirname(self.path))
            fd, tmp = tempfile.mkstemp(suffix='', prefix=basename(self.path) + '.', dir=dirname(self.path))
            self.tmpFd = fd
            self.tmpPath = tmp
            if self.kind == 'zip':
                self.zf = zipfile.ZipFile(tmp, 'w')
            elif self.kind == 'tar':
                self.zf = tarfile.open(tmp, 'w')
            elif self.kind == 'tgz':
                self.zf = tarfile.open(tmp, 'w:gz')
            else:
                abort('unsupported archive kind: ' + self.kind)
        else:
            self.tmpFd = None
            self.tmpPath = None
            self.zf = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.zf:
            self.zf.close()
            os.close(self.tmpFd)
            if exc_value:
                # If an error occurred, delete the temp file
                # instead of moving it into the destination
                os.remove(self.tmpPath)
            else:
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
    parser.add_argument('--parsable', action='store_true', dest='parsable', help='Outputs results in a stable parsable way (one archive per line, <ARCHIVE>=<path>)')
    parser.add_argument('names', nargs=REMAINDER, metavar='[<project>|@<distribution>]...')
    args = parser.parse_args(args)

    archives = []
    for name in args.names:
        if name.startswith('@'):
            dname = name[1:]
            d = distribution(dname)
            d.make_archive()
            archives.append(d.path)
            if args.parsable:
                log('{0}={1}'.format(dname, d.path))
        else:
            p = project(name)
            path = p.make_archive()
            archives.append(path)
            if args.parsable:
                log('{0}={1}'.format(name, path))

    if not args.parsable:
        logv("generated archives: " + str(archives))
    return archives

def checkoverlap(args):
    """check all distributions for overlap

    The exit code of this command reflects how many projects are included in more than one distribution."""

    projToDist = {}
    for d in sorted_dists():
        if d.internal:
            continue
        for p in d.archived_deps():
            if p.isProject():
                if p in projToDist:
                    projToDist[p].append(d)
                else:
                    projToDist[p] = [d]

    count = 0
    for p in projToDist:
        ds = projToDist[p]
        if len(ds) > 1:
            remove = []
            for d in ds:
                if hasattr(d, 'overlaps'):
                    overlaps = d.overlaps
                    if not isinstance(overlaps, list):
                        abort('Attribute "overlaps" must be a list', d)
                    if len([o for o in ds if o.name in overlaps]) != 0:
                        remove.append(d)
            ds = [d for d in ds if d not in remove]
            if len(ds) > 1:
                print '{} is in more than one distribution: {}'.format(p, [d.name for d in ds])
                count += 1
    return count

def canonicalizeprojects(args):
    """check all project specifications for canonical dependencies

    The exit code of this command reflects how many projects have non-canonical dependencies."""

    nonCanonical = []
    for s in suites(True, includeBinary=False):
        for p in (p for p in s.projects if p.isJavaProject()):
            if p.name.endswith('.test'):
                continue
            if p.checkPackagePrefix:
                for pkg in p.defined_java_packages():
                    if not pkg.startswith(p.name):
                        p.abort('package in {0} does not have prefix matching project name: {1}'.format(p, pkg))

            ignoredDeps = set([d for d in p.deps if d.isJavaProject()])
            for pkg in p.imported_java_packages():
                for dep in p.deps:
                    if not dep.isProject():
                        ignoredDeps.discard(dep)
                    else:
                        if pkg in dep.defined_java_packages():
                            ignoredDeps.discard(dep)
                        if pkg in dep.extended_java_packages():
                            ignoredDeps.discard(dep)

            genDeps = frozenset([dependency(name, context=p) for name in getattr(p, "generatedDependencies", [])])
            incorrectGenDeps = genDeps - ignoredDeps
            ignoredDeps -= genDeps
            if incorrectGenDeps:
                p.abort('{0} should declare following as normal dependencies, not generatedDependencies: {1}'.format(p, ', '.join([d.name for d in incorrectGenDeps])))

            if len(ignoredDeps) != 0:
                candidates = set()
                # Compute candidate dependencies based on projects required by p
                for d in dependencies():
                    if d.isJavaProject() and not d.defined_java_packages().isdisjoint(p.imported_java_packages()):
                        candidates.add(d)
                # Remove non-canonical candidates
                for c in list(candidates):
                    c.walk_deps(visit=lambda dep, edge: candidates.discard(dep) if dep.isJavaProject() else None)
                candidates = [d.name for d in candidates]

                msg = 'Non-generated source code in {0} does not use any packages defined in these projects: {1}\nIf the above projects are only ' \
                        'used in generated sources, declare them in a "generatedDependencies" attribute of {0}.\nComputed project dependencies: {2}'
                p.abort(msg.format(
                    p, ', '.join([d.name for d in ignoredDeps]), ','.join(candidates)))

            excess = frozenset([d for d in p.deps if d.isJavaProject()]) - set(p.canonical_deps())
            if len(excess) != 0:
                nonCanonical.append(p)
    if len(nonCanonical) != 0:
        for p in nonCanonical:
            canonicalDeps = p.canonical_deps()
            if len(canonicalDeps) != 0:
                log(p.__abort_context__() + ':\nCanonical dependencies for project ' + p.name + ' are: [')
                for d in canonicalDeps:
                    name = d.suite.name + ':' + d.name if d.suite is not p.suite else d.name
                    log('        "' + name + '",')
                log('      ],')
            else:
                log(p.__abort_context__() + ':\nCanonical dependencies for project ' + p.name + ' are: []')
    return len(nonCanonical)


"""
Represents a file and its modification time stamp at the time the TimeStampFile is created.
"""
class TimeStampFile:
    def __init__(self, path, followSymlinks=True):
        self.path = path
        if exists(path):
            if followSymlinks:
                self.timestamp = os.path.getmtime(path)
            else:
                self.timestamp = os.lstat(path).st_mtime
        else:
            self.timestamp = None

    @staticmethod
    def newest(paths):
        """
        Creates a TimeStampFile for the file in 'paths' with the most recent modification time.
        Entries in 'paths' that do not correspond to an existing file are ignored.
        """
        ts = None
        for path in paths:
            if exists(path):
                if not ts:
                    ts = TimeStampFile(path)
                elif ts.isNewerThan(path):
                    ts = TimeStampFile(path)
        return ts

    def isOlderThan(self, arg):
        if not self.timestamp:
            return True
        if isinstance(arg, types.IntType) or isinstance(arg, types.LongType) or isinstance(arg, types.FloatType):
            return self.timestamp < arg
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

    def isNewerThan(self, arg):
        if not self.timestamp:
            return False
        if isinstance(arg, types.IntType) or isinstance(arg, types.LongType) or isinstance(arg, types.FloatType):
            return self.timestamp > arg
        if isinstance(arg, TimeStampFile):
            if arg.timestamp is None:
                return False
            else:
                return arg.timestamp < self.timestamp
        elif isinstance(arg, types.ListType):
            files = arg
        else:
            files = [arg]
        for f in files:
            if os.path.getmtime(f) < self.timestamp:
                return True
        return False

    def exists(self):
        return exists(self.path)

    def __str__(self):
        if self.timestamp:
            ts = time.strftime('[%Y-%m-%d %H:%M:%S]', time.localtime(self.timestamp))
        else:
            ts = '[does not exist]'
        return self.path + ts

    def touch(self):
        if exists(self.path):
            os.utime(self.path, None)
        else:
            ensure_dir_exists(dirname(self.path))
            file(self.path, 'a')
        self.timestamp = os.path.getmtime(self.path)

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
        if not p.isJavaProject():
            continue
        if args.primary and not p.suite.primary:
            continue
        sourceDirs = p.source_dirs()

        config = join(project(p.checkstyleProj).dir, '.checkstyle_checks.xml')
        if not exists(config):
            logv('[No Checkstyle configuration found for {0} - skipping]'.format(p))
            continue

        # skip checking this Java project if its Java compliance level is "higher" than the configured JDK
        jdk = get_jdk(p.javaCompliance)
        assert jdk

        for sourceDir in sourceDirs:
            javafilelist = []
            for root, _, files in os.walk(sourceDir):
                javafilelist += [join(root, name) for name in files if name.endswith('.java') and name != 'package-info.java']
            if len(javafilelist) == 0:
                logv('[no Java sources in {0} - skipping]'.format(sourceDir))
                continue

            timestamp = TimeStampFile(join(p.suite.get_mx_output_dir(), 'checkstyle-timestamps', sourceDir[len(p.suite.dir) + 1:].replace(os.sep, '_') + '.timestamp'))
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

def rmtree(dirPath):
    path = dirPath
    if get_os() == 'windows':
        path = unicode("\\\\?\\" + dirPath)
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)

def clean(args, parser=None):
    """remove all class files, images, and executables

    Removes all files created by a build, including Java class files, executables, and
    generated images.
    """

    suppliedParser = parser is not None

    parser = parser if suppliedParser else ArgumentParser(prog='mx clean')
    parser.add_argument('--no-native', action='store_false', dest='native', help='do not clean native projects')
    parser.add_argument('--no-java', action='store_false', dest='java', help='do not clean Java projects')
    parser.add_argument('--dependencies', '--projects', action='store', help='comma separated projects to clean (omit to clean all projects)')
    parser.add_argument('--no-dist', action='store_false', dest='dist', help='do not delete distributions')

    args = parser.parse_args(args)

    if args.dependencies is not None:
        deps = [dependency(name) for name in args.dependencies.split(',')]
    else:
        deps = dependencies(True)

    # TODO should we clean all the instantiations of a template?, how to enumerate all instantiations?
    for dep in deps:
        task = dep.getBuildTask(args)
        if task.cleanForbidden():
            continue
        task.logClean()
        task.clean()

        for configName in ['netbeans-config.zip', 'eclipse-config.zip']:
            config = TimeStampFile(join(dep.suite.get_mx_output_dir(), configName))
            if config.exists():
                os.unlink(config.path)

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
    parser.add_argument('--dist', action='store_true', help='group projects by distribution')
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
        def visit(dep, edge):
            ident = len(ids)
            ids[dep.name] = str(ident)
            igv.open('node', {'id' : str(ident)})
            igv.open('properties')
            igv.element('p', {'name' : 'name'}, dep.name)
            igv.close('properties')
            igv.close('node')
        walk_deps(visit=visit)
        igv.close('nodes')
        igv.open('edges')
        for p in projects():
            fromIndex = 0
            for dep in p.canonical_deps():
                toIndex = nextToIndex.get(dep, 0)
                nextToIndex[dep] = toIndex + 1
                igv.element('edge', {'from' : ids[p.name], 'fromIndex' : str(fromIndex), 'to' : ids[dep.name], 'toIndex' : str(toIndex), 'label' : 'dependsOn'})
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
    if args.dist:
        for d in sorted_dists():
            print 'subgraph "cluster_' + d.name + '" {'
            print 'label="' + d.name + '";'
            print 'color=blue;'
            print '"' + d.name + ':DUMMY" [shape=point style=invis]'

            if d.isJARDistribution():
                for p in d.archived_deps():
                    if p.isProject():
                        print '"' + p.name + '";'
            print '}'
    for p in projects():
        for dep in p.canonical_deps():
            if args.dist and dep.isDistribution():
                print '"' + p.name + '"->"' + dep.name + ':DUMMY" [lhead=cluster_' + dep.name + ' color=blue];'
            else:
                print '"' + p.name + '"->"' + dep.name + '";'
        if p is JavaProject:
            for apd in p.declaredAnnotationProcessors:
                print '"' + p.name + '"->"' + apd.name + '" [style="dashed"];'
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
            if not dep.isJavaProject():
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
    ensure_dir_exists(eclipseLaunches)
    launchFile = join(eclipseLaunches, name + '.launch')
    return update_file(launchFile, launch), launchFile

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

    eclipseLaunches = join(suite.mxDir, 'eclipse-launches')
    ensure_dir_exists(eclipseLaunches)
    return update_file(join(eclipseLaunches, name + '.launch'), launch)

def eclipseinit_cli(args):
    parser = ArgumentParser(prog='mx eclipseinit')
    parser.add_argument('--no-build', action='store_false', dest='buildProcessorJars', help='Do not build annotation processor jars.')
    parser.add_argument('-C', '--log-to-console', action='store_true', dest='logToConsole', help='Send builder output to eclipse console.')
    args = parser.parse_args(args)
    eclipseinit(None, args.buildProcessorJars, logToConsole=args.logToConsole)

def eclipseinit(args, buildProcessorJars=True, refreshOnly=False, logToConsole=False):
    """(re)generate Eclipse project configurations and working sets"""
    for s in suites(True):
        _eclipseinit_suite(s, buildProcessorJars, refreshOnly, logToConsole)

    generate_eclipse_workingsets()

def _check_ide_timestamp(suite, configZip, ide, settingsFile=None):
    """
    Returns True if and only if suite.py for *suite*, all *configZip* related resources in
    *suite* and mx itself are older than *configZip*.
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
        for p in [p for p in suite.projects]:
            if not p.eclipse_config_up_to_date(configZip):
                return False
    return True

EclipseLinkedResource = namedtuple('LinkedResource', ['name', 'type', 'location'])
def _eclipse_linked_resource(name, tp, location):
    return EclipseLinkedResource(name, tp, location)

def get_eclipse_project_rel_locationURI(path, eclipseProjectDir):
    """
    Gets the URI for a resource relative to an Eclipse project directory (i.e.,
    the directory containing the ```.project``` file for the project). The URI
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

def _convert_to_eclipse_supported_compliance(compliance):
    """
    Downgrades a given Java compliance to a level supported by Eclipse.
    This accounts for the reality that Eclipse (and JDT) usually add support for JDK releases later
    than javac support is available.
    """
    if compliance and compliance > "1.8":
        return JavaCompliance("1.8")
    return compliance

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

def _eclipseinit_project(p, files=None, libFiles=None):
    eclipseJavaCompliance = _convert_to_eclipse_supported_compliance(p.javaCompliance)

    ensure_dir_exists(p.dir)

    linkedResources = []

    out = XMLDoc()
    out.open('classpath')

    for src in p.srcDirs:
        srcDir = join(p.dir, src)
        ensure_dir_exists(srcDir)
        out.element('classpathentry', {'kind' : 'src', 'path' : src})

    processors = p.annotation_processors()
    if processors:
        genDir = p.source_gen_dir()
        ensure_dir_exists(genDir)
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

    # Every Java program depends on a JRE
    out.element('classpathentry', {'kind' : 'con', 'path' : 'org.eclipse.jdt.launching.JRE_CONTAINER/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/JavaSE-' + str(eclipseJavaCompliance)})

    if exists(join(p.dir, 'plugin.xml')):  # eclipse plugin project
        out.element('classpathentry', {'kind' : 'con', 'path' : 'org.eclipse.pde.core.requiredPlugins'})

    containerDeps = set()
    libraryDeps = set()
    projectDeps = set()
    distributionDeps = set()

    def processDep(dep, edge):
        if dep is p:
            return
        if dep.isLibrary():
            if hasattr(dep, 'eclipse.container'):
                container = getattr(dep, 'eclipse.container')
                containerDeps.add(container)
                dep.walk_deps(visit=lambda dep2, edge2: libraryDeps.discard(dep2))
            else:
                libraryDeps.add(dep)
        elif dep.isProject():
            projectDeps.add(dep)
        elif dep.isJdkLibrary() or dep.isJreLibrary() or dep.isDistribution():
            pass
        else:
            abort('unexpected dependency: ' + str(dep))
    p.walk_deps(visit=processDep)

    for dep in sorted(containerDeps):
        out.element('classpathentry', {'exported' : 'true', 'kind' : 'con', 'path' : dep})

    for dep in sorted(distributionDeps):
        out.element('classpathentry', {'exported' : 'true', 'kind' : 'lib', 'path' : dep.path, 'sourcepath' : dep.sourcesPath})

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


    out.element('classpathentry', {'kind' : 'output', 'path' : _get_eclipse_output_path(p, linkedResources)})
    out.close('classpath')
    classpathFile = join(p.dir, '.classpath')
    update_file(classpathFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(classpathFile)

    csConfig = join(project(p.checkstyleProj, context=p).dir, '.checkstyle_checks.xml')
    if exists(csConfig):
        out = XMLDoc()

        dotCheckstyle = join(p.dir, ".checkstyle")
        checkstyleConfigPath = '/' + p.checkstyleProj + '/.checkstyle_checks.xml'
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

    out.close('buildSpec')
    out.open('natures')
    out.element('nature', data='org.eclipse.jdt.core.javanature')
    if exists(csConfig):
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
            out.element('locationURI', data=get_eclipse_project_rel_locationURI(lr.location, p.dir))
            out.close('link')
        out.close('linkedResources')
    out.close('projectDescription')
    projectFile = join(p.dir, '.project')
    update_file(projectFile, out.xml(indent='\t', newl='\n'))
    if files:
        files.append(projectFile)

    settingsDir = join(p.dir, ".settings")
    ensure_dir_exists(settingsDir)

    # copy a possibly modified file to the project's .settings directory
    for name, sources in p.eclipse_settings_sources().iteritems():
        out = StringIO.StringIO()
        print >> out, '# GENERATED -- DO NOT EDIT'
        for source in sources:
            print >> out, '# Source:', source
            with open(source) as f:
                print >> out, f.read()
        content = out.getvalue().replace('${javaCompliance}', str(eclipseJavaCompliance))
        if processors:
            content = content.replace('org.eclipse.jdt.core.compiler.processAnnotations=disabled', 'org.eclipse.jdt.core.compiler.processAnnotations=enabled')
        update_file(join(settingsDir, name), content)
        if files:
            files.append(join(settingsDir, name))

    if processors:
        out = XMLDoc()
        out.open('factorypath')
        out.element('factorypathentry', {'kind' : 'PLUGIN', 'id' : 'org.eclipse.jst.ws.annotations.core', 'enabled' : 'true', 'runInBatchMode' : 'false'})
        processorsPath = classpath_entries(names=processors)
        for e in processorsPath:
            if e.isDistribution():
                out.element('factorypathentry', {'kind' : 'WKSPJAR', 'id' : '/{0}/{1}'.format(e.name, basename(e.path)), 'enabled' : 'true', 'runInBatchMode' : 'false'})
            else:
                out.element('factorypathentry', {'kind' : 'EXTJAR', 'id' : e.classpath_repr(resolve=True), 'enabled' : 'true', 'runInBatchMode' : 'false'})
        out.close('factorypath')
        update_file(join(p.dir, '.factorypath'), out.xml(indent='\t', newl='\n'))
        if files:
            files.append(join(p.dir, '.factorypath'))

def _capture_eclipse_settings(logToConsole):
    # Capture interesting settings which drive the output of the projects.
    # Changes to these values should cause regeneration of the project files.
    value = 'logToConsole=%s\n' % logToConsole
    if os.environ.get('PATH'):
        value = value + 'PATH=%s\n' % os.environ['PATH']
    if os.environ.get('JAVA_HOME'):
        value = value + 'JAVA_HOME=%s\n' % os.environ['JAVA_HOME']
    if os.environ.get('DEFAULT_VM'):
        value = value + 'DEFAULT_VM=%s\n' % os.environ['DEFAULT_VM']
    return value

def _eclipseinit_suite(suite, buildProcessorJars=True, refreshOnly=False, logToConsole=False):
    # a binary suite archive is immutable and no project sources, only the -sources.jar
    # TODO We may need the project (for source debugging) but it needs different treatment
    if isinstance(suite, BinarySuite):
        return

    mxOutputDir = ensure_dir_exists(suite.get_mx_output_dir())
    configZip = TimeStampFile(join(mxOutputDir, 'eclipse-config.zip'))
    configLibsZip = join(mxOutputDir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    settingsFile = join(mxOutputDir, 'eclipse-project-settings')
    update_file(settingsFile, _capture_eclipse_settings(logToConsole))
    if _check_ide_timestamp(suite, configZip, 'eclipse', settingsFile):
        logv('[Eclipse configurations for {} are up to date - skipping]'.format(suite.name))
        return

    files = []
    libFiles = []
    if buildProcessorJars:
        files += _processorjars_suite(suite)

    for p in suite.projects:
        p._eclipseinit(files, libFiles)

    _, launchFile = make_eclipse_attach(suite, 'localhost', '8000', deps=dependencies())
    files.append(launchFile)

    # Create an Eclipse project for each distribution that will create/update the archive
    # for the distribution whenever any (transitively) dependent project of the
    # distribution is updated.
    for dist in suite.dists:
        if not dist.isJARDistribution():
            continue
        projectDir = dist.get_ide_project_dir()
        if not projectDir:
            continue
        ensure_dir_exists(projectDir)
        relevantResources = []
        for d in dist.archived_deps():
            # Eclipse does not seem to trigger a build for a distribution if the references
            # to the constituent projects are of type IRESOURCE_PROJECT.
            if d.isProject():
                for srcDir in d.srcDirs:
                    relevantResources.append(RelevantResource('/' + d.name + '/' + srcDir, IRESOURCE_FOLDER))
                relevantResources.append(RelevantResource('/' +d.name + '/' + _get_eclipse_output_path(d), IRESOURCE_FOLDER))
            elif d.isDistribution():
                relevantResources.append(RelevantResource('/' +d.name, IRESOURCE_PROJECT))
        out = XMLDoc()
        out.open('projectDescription')
        out.element('name', data=dist.name)
        out.element('comment', data='Updates ' + dist.path + ' if a project dependency of ' + dist.name + ' is updated')
        out.open('projects')
        for d in dist.deps:
            out.element('project', data=d.name)
        out.close('projects')
        out.open('buildSpec')
        dist.dir = projectDir
        javaCompliances = [_convert_to_eclipse_supported_compliance(p.javaCompliance) for p in dist.archived_deps() if p.isProject()]
        if len(javaCompliances) > 0:
            dist.javaCompliance = max(javaCompliances)
        _genEclipseBuilder(out, dist, 'Create' + dist.name + 'Dist', '-v archive @' + dist.name, relevantResources=relevantResources, logToFile=True, refresh=True, async=False, logToConsole=logToConsole, appendToLogFile=False, refreshFile='/{0}/{1}'.format(dist.name, basename(dist.path)))
        out.close('buildSpec')
        out.open('natures')
        out.element('nature', data='org.eclipse.jdt.core.javanature')
        out.close('natures')
        out.open('linkedResources')
        out.open('link')
        out.element('name', data=basename(dist.path))
        out.element('type', data=str(IRESOURCE_FILE))
        out.element('location', data=get_eclipse_project_rel_locationURI(dist.path, projectDir))
        out.close('link')
        out.close('linkedResources')
        out.close('projectDescription')
        projectFile = join(projectDir, '.project')
        update_file(projectFile, out.xml(indent='\t', newl='\n'))
        files.append(projectFile)

    _zip_files(files + [settingsFile], suite.dir, configZip.path)
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

RelevantResource = namedtuple('RelevantResource', ['path', 'type'])

# http://grepcode.com/file/repository.grepcode.com/java/eclipse.org/4.4.2/org.eclipse.core/resources/3.9.1/org/eclipse/core/resources/IResource.java#76
IRESOURCE_FILE = 1
IRESOURCE_FOLDER = 2
IRESOURCE_PROJECT = 4

def _genEclipseBuilder(dotProjectDoc, p, name, mxCommand, refresh=True, refreshFile=None, relevantResources=None, async=False, logToConsole=False, logToFile=False, appendToLogFile=True, xmlIndent='\t', xmlStandalone=None):
    externalToolDir = join(p.dir, '.externalToolBuilders')
    launchOut = XMLDoc()
    consoleOn = 'true' if logToConsole else 'false'
    launchOut.open('launchConfiguration', {'type' : 'org.eclipse.ui.externaltools.ProgramBuilderLaunchConfigurationType'})
    launchOut.element('booleanAttribute', {'key' : 'org.eclipse.debug.core.capture_output', 'value': consoleOn})
    launchOut.open('mapAttribute', {'key' : 'org.eclipse.debug.core.environmentVariables'})
    launchOut.element('mapEntry', {'key' : 'JAVA_HOME', 'value' : get_jdk().home})
    # On the mac, applications are launched with a different path than command
    # line tools, so capture the current PATH.  In general this ensures that
    # the eclipse builders see the same path as a working command line build.
    if os.environ.get('PATH'):
        launchOut.element('mapEntry', {'key' : 'PATH', 'value' : os.environ['PATH']})
    # The mx builders are run inside the directory of their associated suite,
    # not the primary suite, so they might not see the env file of the primary
    # suite.  Capture DEFAULT_VM in case it was only defined in the primary
    # suite.
    if os.environ.get('DEFAULT_VM'):
        launchOut.element('mapEntry', {'key' : 'DEFAULT_VM', 'value' : os.environ['DEFAULT_VM']})
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

    ensure_dir_exists(externalToolDir)
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

def _netbeansinit_project(p, jdks=None, files=None, libFiles=None, dists=None):
    dists = [] if dists is None else dists
    ensure_dir_exists(join(p.dir, 'nbproject'))

    jdk = get_jdk(p.javaCompliance)
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
    out.open('target', {'name' : 'clean'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true'})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'clean'})
    out.element('arg', {'value' : '--projects'})
    out.element('arg', {'value' : p.name})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'compile'})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true'})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'build'})
    buildOnly = p.name
    for d in dists:
        buildOnly = buildOnly + ',' + d.name
    out.element('arg', {'value' : '--only'})
    out.element('arg', {'value' : buildOnly})
    out.element('arg', {'value' : '--force-javac'})
    out.element('arg', {'value' : '--no-native'})
    out.close('exec')
    out.close('target')
    out.open('target', {'name' : 'jar', 'depends' : 'compile'})
    out.close('target')
    out.element('target', {'name' : 'test', 'depends' : 'run'})
    out.element('target', {'name' : 'test-single', 'depends' : 'run'})
    out.open('target', {'name' : 'run', 'depends' : 'compile'})
    out.element('property', {'name' : 'test.class', 'value' : p.name})
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true'})
    out.element('env', {'key' : 'JAVA_HOME', 'value' : jdk.home})
    out.element('arg', {'value' : os.path.abspath(__file__)})
    out.element('arg', {'value' : 'unittest'})
    out.element('arg', {'value' : '${test.class}'})
    out.close('exec')
    out.close('target')
    out.element('target', {'name' : 'debug-test', 'depends' : 'debug'})
    out.open('target', {'name' : 'debug', 'depends' : 'init,compile'})
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
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true'})
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
    out.open('exec', {'executable' : sys.executable, 'failonerror' : 'true'})
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
            out.close('reference')
    p.walk_deps(visit=processDep, ignoredEdges=[DEP_EXCLUDED])

    if firstDep:
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
        ensure_dir_exists(genSrcDir)
        genSrcDir = genSrcDir.replace('\\', '\\\\')
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
""" + annotationProcessorSrcFolder + """
source.encoding=UTF-8""".replace(':', os.pathsep).replace('/', os.sep)
    print >> out, content

    # Workaround for NetBeans "too clever" behavior. If you want to be
    # able to press F6 or Ctrl-F5 in NetBeans and run/debug unit tests
    # then the project must have its main.class property set to an
    # existing class with a properly defined main method. Until this
    # behavior is remedied, we specify a well known Truffle class
    # that will be on the class path for most Truffle projects.
    # This can be overridden by defining a netbeans.project.properties
    # attribute for a project in suite.py (see below).
    print >> out, "main.class=com.oracle.truffle.api.impl.Accessor"

    # Add extra properties specified in suite.py for this project
    if hasattr(p, 'netbeans.project.properties'):
        properties = getattr(p, 'netbeans.project.properties')
        for prop in [properties] if isinstance(properties, str) else properties:
            print >> out, prop

    mainSrc = True
    for src in p.srcDirs:
        srcDir = join(p.dir, src)
        ensure_dir_exists(srcDir)
        ref = 'file.reference.' + p.name + '-' + src
        print >> out, ref + '=' + src
        if mainSrc:
            print >> out, 'src.dir=${' + ref + '}'
            mainSrc = False
        else:
            print >> out, 'src.' + src + '.dir=${' + ref + '}'

    javacClasspath = []

    deps = []
    p.walk_deps(visit=lambda dep, edge: deps.append(dep) if dep.isLibrary() or dep.isProject() else None)
    annotationProcessorOnlyDeps = []
    if len(p.annotation_processors()) > 0:
        for apDep in p.annotation_processors():
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
    mxOutputDir = ensure_dir_exists(suite.get_mx_output_dir())
    configZip = TimeStampFile(join(mxOutputDir, 'netbeans-config.zip'))
    configLibsZip = join(mxOutputDir, 'eclipse-config-libs.zip')
    if refreshOnly and not configZip.exists():
        return

    if _check_ide_timestamp(suite, configZip, 'netbeans'):
        logv('[NetBeans configurations are up to date - skipping]')
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

    ensure_dir_exists(ideaProjectDirectory)
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

    # create the modules (1 IntelliJ module = 1 mx project/distribution)
    for p in suite.projects_recursive():
        if not p.isJavaProject():
            continue

        jdk = get_jdk(p.javaCompliance)
        assert jdk

        ensure_dir_exists(p.dir)

        processors = p.annotation_processors()
        if processors:
            annotationProcessorProfiles.setdefault(tuple(processors), []).append(p)

        intellijLanguageLevel = _complianceToIntellijLanguageLevel(jdk.javaCompliance)

        moduleXml = XMLDoc()
        moduleXml.open('module', attributes={'type': 'JAVA_MODULE', 'version': '4'})

        moduleXml.open('component', attributes={'name': 'NewModuleRootManager', 'LANGUAGE_LEVEL': intellijLanguageLevel, 'inherit-compiler-output': 'false'})
        moduleXml.element('output', attributes={'url': 'file://$MODULE_DIR$/' + p.output_dir(relative=True)})

        moduleXml.open('content', attributes={'url': 'file://$MODULE_DIR$'})
        for src in p.srcDirs:
            srcDir = join(p.dir, src)
            ensure_dir_exists(srcDir)
            moduleXml.element('sourceFolder', attributes={'url':'file://$MODULE_DIR$/' + src, 'isTestSource': 'false'})

        if processors:
            genDir = p.source_gen_dir()
            ensure_dir_exists(genDir)
            moduleXml.element('sourceFolder', attributes={'url':'file://$MODULE_DIR$/' + p.source_gen_dir_name(), 'isTestSource': 'false'})

        for name in ['.externalToolBuilders', '.settings', 'nbproject']:
            _intellij_exclude_if_exists(moduleXml, p, name)
        moduleXml.close('content')

        moduleXml.element('orderEntry', attributes={'type': 'jdk', 'jdkType': 'JavaSDK', 'jdkName': str(jdk.javaCompliance)})
        moduleXml.element('orderEntry', attributes={'type': 'sourceFolder', 'forTests': 'false'})

        def processDep(dep, edge):
            if dep is p:
                return

            if dep.isLibrary():
                libraries.add(dep)
                moduleXml.element('orderEntry', attributes={'type': 'library', 'name': dep.name, 'level': 'project'})
            elif dep.isProject():
                moduleXml.element('orderEntry', attributes={'type': 'module', 'module-name': dep.name})
        p.walk_deps(visit=processDep, ignoredEdges=[DEP_EXCLUDED])

        moduleXml.close('component')

        # Checkstyle
        csConfig = join(project(p.checkstyleProj, context=p).dir, '.checkstyle_checks.xml')
        if exists(csConfig):
            moduleXml.open('component', attributes={'name': 'CheckStyle-IDEA-Module'})
            moduleXml.open('option', attributes={'name': 'configuration'})
            moduleXml.open('map')
            moduleXml.element('entry', attributes={'key' : "active-configuration", 'value': "PROJECT_RELATIVE:" + join(project(p.checkstyleProj).dir, ".checkstyle_checks.xml") + ":" + p.checkstyleProj})
            moduleXml.close('map')
            moduleXml.close('option')
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

    ensure_dir_exists(librariesDirectory)

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
            compilerXml.open('profile', attributes={'default': 'false', 'name': '-'.join([ap.name for ap in processors]), 'enabled': 'true'})
            compilerXml.element('sourceOutputDir', attributes={'name': 'src_gen'})  # TODO use p.source_gen_dir() ?
            compilerXml.element('outputRelativeToContentRoot', attributes={'value': 'true'})
            compilerXml.open('processorPath', attributes={'useClasspath': 'false'})

            # IntelliJ supports both directories and jars on the annotation processor path whereas
            # Eclipse only supports jars.
            for apDep in processors:
                def processApDep(dep, edge):
                    if dep.isLibrary():
                        compilerXml.element('entry', attributes={'name': '$PROJECT_DIR$/' + os.path.relpath(dep.path, suite.dir)})
                    elif dep.isProject():
                        compilerXml.element('entry', attributes={'name': '$PROJECT_DIR$/' + os.path.relpath(dep.output_dir(), suite.dir)})
                apDep.walk_deps(visit=processApDep)
            compilerXml.close('processorPath')
            for module in modules:
                compilerXml.element('module', attributes={'name': module.name})
            compilerXml.close('profile')
        compilerXml.close('annotationProcessing')

    compilerXml.close('component')
    compilerXml.close('project')
    compilerFile = join(ideaProjectDirectory, 'compiler.xml')
    update_file(compilerFile, compilerXml.xml(indent='  ', newl='\n'))

    # Write misc.xml for global JDK config
    miscXml = XMLDoc()
    miscXml.open('project', attributes={'version' : '4'})

    sources = suite.eclipse_settings_sources().get('org.eclipse.jdt.core.prefs')
    if sources:
        out = StringIO.StringIO()
        print >> out, '# GENERATED -- DO NOT EDIT'
        for source in sources:
            print >> out, '# Source:', source
            with open(source) as f:
                for line in f:
                    if line.startswith('org.eclipse.jdt.core.formatter.'):
                        print >> out, line.strip()
        formatterConfigFile = join(ideaProjectDirectory, 'EclipseCodeFormatter.prefs')
        update_file(formatterConfigFile, out.getvalue())
        miscXml.open('component', attributes={'name' : 'EclipseCodeFormatter'})
        miscXml.element('option', attributes={'name' : 'formatter', 'value' : 'ECLIPSE'})
        miscXml.element('option', attributes={'name' : 'id', 'value' : '1450878132508'})
        miscXml.element('option', attributes={'name' : 'name', 'value' : suite.name})
        miscXml.element('option', attributes={'name' : 'pathToConfigFileJava', 'value' : '$PROJECT_DIR$/.idea/' + basename(formatterConfigFile)})
        miscXml.element('option', attributes={'name' : 'useOldEclipseJavaFormatter', 'value' : 'true'}) # Eclipse 4.4
        miscXml.close('component')
    miscXml.element('component', attributes={'name' : 'ProjectRootManager', 'version': '2', 'languageLevel': _complianceToIntellijLanguageLevel(jdk.javaCompliance), 'project-jdk-name': str(jdk.javaCompliance), 'project-jdk-type': 'JavaSDK'})
    miscXml.close('project')
    miscFile = join(ideaProjectDirectory, 'misc.xml')
    update_file(miscFile, miscXml.xml(indent='  ', newl='\n'))

    # Write checkstyle-idea.xml for the CheckStyle-IDEA
    checkstyleXml = XMLDoc()
    checkstyleXml.open('project', attributes={'version': '4'})
    checkstyleXml.open('component', attributes={'name': 'CheckStyle-IDEA'})
    checkstyleXml.open('option', attributes={'name' : "configuration"})
    checkstyleXml.open('map')

    # Initialize an entry for each style that is used
    checkstyleProjects = set([])
    for p in suite.projects_recursive():
        if not p.isJavaProject():
            continue
        csConfig = join(project(p.checkstyleProj, context=p).dir, '.checkstyle_checks.xml')
        if p.checkstyleProj in checkstyleProjects or not exists(csConfig):
            continue
        checkstyleProjects.add(p.checkstyleProj)
        checkstyleXml.element('entry', attributes={'key' : "location-" + str(len(checkstyleProjects)), 'value': "PROJECT_RELATIVE:" + join(project(p.checkstyleProj).dir, ".checkstyle_checks.xml") + ":" + p.checkstyleProj})

    checkstyleXml.close('map')
    checkstyleXml.close('option')
    checkstyleXml.close('component')
    checkstyleXml.close('project')
    checkstyleFile = join(ideaProjectDirectory, 'checkstyle-idea.xml')
    update_file(checkstyleFile, checkstyleXml.xml(indent='  ', newl='\n'))

    # mx integration
    # 1) Make an ant file for archiving the project.
    antXml = XMLDoc()
    antXml.open('project', attributes={'name': suite.name, 'default': 'archive'})
    antXml.open('target', attributes={'name': 'archive'})
    antXml.open('exec', attributes={'executable': '/bin/bash'})
    antXml.element('arg', attributes={'value': 'mx'})
    antXml.element('arg', attributes={'value': 'archive'})

    distDeps = set([])
    for p in suite.projects_recursive():
        for dep in p.deps:
            if dep.isJARDistribution():
                distDeps.add(dep.name)

    for dist in distDeps:
        antXml.element('arg', attributes={'value': '@' + dist})

    antXml.close('exec')
    antXml.close('target')
    antXml.close('project')
    antFile = join(ideaProjectDirectory, 'ant-mx-archive.xml')
    update_file(antFile, antXml.xml(indent='  ', newl='\n'))

    # 2) Tell IDEA that there is an ant-build.
    metaAntXml = XMLDoc()
    metaAntXml.open('project', attributes={'version': '4'})
    metaAntXml.open('component', attributes={'name': 'AntConfiguration'})
    metaAntXml.open('buildFile', attributes={'url': 'file://$PROJECT_DIR$/.idea/ant-mx-archive.xml'})
    metaAntXml.element('executeOn', attributes={'event': 'afterCompilation', 'target': 'archive'})
    metaAntXml.close('buildFile')
    metaAntXml.close('component')
    metaAntXml.close('project')
    metaAntFile = join(ideaProjectDirectory, 'ant.xml')
    update_file(metaAntFile, metaAntXml.xml(indent='  ', newl='\n'))


    # TODO look into copyright settings
    # TODO should add vcs.xml support

def ideclean(args):
    """remove all IDE project configurations"""
    def rm(path):
        if exists(path):
            os.remove(path)

    for s in suites():
        rm(join(s.get_mx_output_dir(), 'eclipse-config.zip'))
        rm(join(s.get_mx_output_dir(), 'netbeans-config.zip'))
        shutil.rmtree(join(s.dir, '.idea'), ignore_errors=True)

    for p in projects():
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
            log("Error removing {0}".format(p.name + '.jar'))

    for d in _dists.itervalues():
        if not d.isJARDistribution():
            continue
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
    for suite in suites(True, includeBinary=False):
        projectDirs = [p.dir for p in suite.projects]
        distIdeDirs = [d.get_ide_project_dir() for d in suite.dists if d.isJARDistribution() and d.get_ide_project_dir() is not None]
        for dirpath, dirnames, files in os.walk(suite.dir):
            if dirpath == suite.dir:
                # no point in traversing vc metadata dir, lib, .workspace
                # if there are nested source suites must not scan those now, as they are not in projectDirs (but contain .project files)
                dirnames[:] = [d for d in dirnames if d not in [suite.vc.metadir(), suite.mxDir, 'lib', '.workspace', 'mx.imports']]
            elif dirpath == suite.mxDir:
                # don't want to traverse mx.name as it contains a .project
                dirnames[:] = []
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
                    indicatorsInVC = suite.vc.locate(suite.dir, indicators)
                    # Only proceed if there are indicator files that are not under VC
                    if len(indicators) > len(indicatorsInVC):
                        if ask_yes_no(dirpath + ' looks like a removed project -- delete it', 'n'):
                            shutil.rmtree(dirpath)
                            log('Deleted ' + dirpath)

def find_packages(project, pkgs=None, onlyPublic=True, packages=None, exclude_packages=None):
    packages = [] if packages is None else packages
    exclude_packages = [] if exclude_packages is None else exclude_packages
    sourceDirs = project.source_dirs()
    def is_visible(name):
        if onlyPublic:
            return name == 'package-info.java'
        else:
            return name.endswith('.java')
    if pkgs is None:
        pkgs = set()
    for sourceDir in sourceDirs:
        for root, _, files in os.walk(sourceDir):
            if len([name for name in files if is_visible(name)]) != 0:
                pkg = root[len(sourceDir) + 1:].replace(os.sep, '.')
                if len(packages) == 0 or pkg in packages:
                    if len(exclude_packages) == 0 or not pkg in exclude_packages:
                        pkgs.add(pkg)
    return pkgs

_javadocRefNotFound = re.compile("Tag @link(plain)?: reference not found: ")

def javadoc(args, parser=None, docDir='javadoc', includeDeps=True, stdDoclet=True, mayBuild=True, quietForNoPackages=False):
    """generate javadoc for some/all Java projects"""

    parser = ArgumentParser(prog='mx javadoc') if parser is None else parser
    parser.add_argument('-d', '--base', action='store', help='base directory for output')
    parser.add_argument('--unified', action='store_true', help='put javadoc in a single directory instead of one per project')
    parser.add_argument('--implementation', action='store_true', help='include also implementation packages')
    parser.add_argument('--force', action='store_true', help='(re)generate javadoc even if package-list file exists')
    parser.add_argument('--projects', action='store', help='comma separated projects to process (omit to process all projects)')
    parser.add_argument('--Wapi', action='store_true', dest='warnAPI', help='show warnings about using internal APIs')
    parser.add_argument('--argfile', action='store', help='name of file containing extra javadoc options')
    parser.add_argument('--arg', action='append', dest='extra_args', help='extra Javadoc arguments (e.g. --arg @-use)', metavar='@<arg>', default=[])
    parser.add_argument('-m', '--memory', action='store', help='-Xmx value to pass to underlying JVM')
    parser.add_argument('--packages', action='store', help='comma separated packages to process (omit to process all packages)')
    parser.add_argument('--exclude-packages', action='store', help='comma separated packages to exclude')
    parser.add_argument('--allow-warnings', action='store_true', help='Exit normally even if warnings were found')

    args = parser.parse_args(args)

    # build list of projects to be processed
    if args.projects is not None:
        partialJavadoc = True
        candidates = [project(name) for name in args.projects.split(',')]
    else:
        partialJavadoc = False
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
            return (False, 'Already visited')
        if not args.implementation and p.name.endswith('.test'):
            return (False, 'Test project')
        if args.force or args.unified or check_package_list(p):
            projects.append(p)
            return (True, None)
        return (False, 'package-list file exists')

    projects = []
    for p in candidates:
        if p.isJavaProject():
            if includeDeps:
                p.walk_deps(visit=lambda dep, edge: assess_candidate(dep, projects)[0] if dep.isProject() else None)
            added, reason = assess_candidate(p, projects)
            if not added:
                logv('[{0} - skipping {1}]'.format(reason, p.name))
    snippets = []
    for p in projects_opt_limit_to_suites():
        if p.isJavaProject():
            snippets += p.source_dirs()
    snippets = os.pathsep.join(snippets)
    snippetslib = library('CODESNIPPET-DOCLET').get_path(resolve=True)

    if not projects:
        log('All projects were skipped.')
        if not _opts.verbose:
            log('Re-run with global -v option to see why.')
        return

    extraArgs = [a.lstrip('@') for a in args.extra_args]
    if args.argfile is not None:
        extraArgs += ['@' + args.argfile]
    memory = '2g'
    if args.memory is not None:
        memory = args.memory
    memory = '-J-Xmx' + memory

    if mayBuild:
        # The project must be built to ensure javadoc can find class files for all referenced classes
        build(['--no-native', '--dependencies', ','.join((p.name for p in projects))])
    if not args.unified:
        for p in projects:
            pkgs = find_packages(p, set(), False, packages, exclude_packages)
            jdk = get_jdk(p.javaCompliance)
            links = ['-linkoffline', 'http://docs.oracle.com/javase/' + str(jdk.javaCompliance.value) + '/docs/api/', _mx_home + '/javadoc/jdk']
            out = outDir(p)
            def visit(dep, edge):
                if dep.isProject():
                    depOut = outDir(dep)
                    links.append('-link')
                    links.append(os.path.relpath(depOut, out))
            p.walk_deps(visit=visit)
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

            if not pkgs:
                if quietForNoPackages:
                    return
                else:
                    abort('No packages to generate javadoc for!')

            # windowTitle onloy applies to the standard doclet processor
            windowTitle = []
            if stdDoclet:
                windowTitle = ['-windowtitle', p.name + ' javadoc']
            try:
                log('Generating {2} for {0} in {1}'.format(p.name, out, docDir))

                # Once https://bugs.openjdk.java.net/browse/JDK-8041628 is fixed,
                # this should be reverted to:
                # javadocExe = get_jdk().javadoc
                # we can then also respect _opts.relatex_compliance
                javadocExe = jdk.javadoc

                run([javadocExe, memory,
                     '-XDignore.symbol.file',
                     '-classpath', cp,
                     '-quiet',
                     '-d', out,
                     '-overview', overviewFile,
                     '-sourcepath', sp,
                     '-doclet', 'org.apidesign.javadoc.codesnippet.Doclet',
                     '-docletpath', snippetslib,
                     '-snippetpath', snippets,
                     '-source', str(jdk.javaCompliance)] +
                     jdk.javadocLibOptions([]) +
                     ([] if jdk.javaCompliance < JavaCompliance('1.8') else ['-Xdoclint:none']) +
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
        jdk = get_jdk()
        pkgs = set()
        sproots = []
        names = []
        for p in projects:
            find_packages(p, pkgs, not args.implementation, packages, exclude_packages)
            sproots += p.source_dirs()
            names.append(p.name)

        links = ['-linkoffline', 'http://docs.oracle.com/javase/' + str(jdk.javaCompliance.value) + '/docs/api/', _mx_home + '/javadoc/jdk']
        overviewFile = os.sep.join([_primary_suite.dir, _primary_suite.name, 'overview.html'])
        out = join(_primary_suite.dir, docDir)
        if args.base is not None:
            out = join(args.base, docDir)
        cp = classpath()
        sp = os.pathsep.join(sproots)
        nowarnAPI = []
        if not args.warnAPI:
            nowarnAPI.append('-XDignore.symbol.file')

        def find_group(pkg):
            for p in sproots:
                info = p + os.path.sep + pkg.replace('.', os.path.sep) + os.path.sep + 'package-info.java'
                if exists(info):
                    f = open(info, "r")
                    for line in f:
                        m = re.search('group="(.*)"', line)
                        if m:
                            return m.group(1)
            return None
        groups = OrderedDict()
        for p in pkgs:
            g = find_group(p)
            if g is None:
                continue
            if not groups.has_key(g):
                groups[g] = set()
            groups[g].add(p)
        groupargs = list()
        for k, v in groups.iteritems():
            if len(v) == 0:
                continue
            groupargs.append('-group')
            groupargs.append(k)
            groupargs.append(':'.join(v))

        if not pkgs:
            if quietForNoPackages:
                return
            else:
                abort('No packages to generate javadoc for!')

        log('Generating {2} for {0} in {1}'.format(', '.join(names), out, docDir))

        class WarningCapture:
            def __init__(self, prefix, forward, ignoreBrokenRefs):
                self.prefix = prefix
                self.forward = forward
                self.ignoreBrokenRefs = ignoreBrokenRefs
                self.warnings = 0

            def __call__(self, msg):
                shouldPrint = self.forward
                if ': warning - ' in  msg:
                    if not self.ignoreBrokenRefs or not _javadocRefNotFound.search(msg):
                        self.warnings += 1
                        shouldPrint = True
                    else:
                        shouldPrint = False
                if shouldPrint or _opts.verbose:
                    log(self.prefix + msg)

        captureOut = WarningCapture('stdout: ', False, partialJavadoc)
        captureErr = WarningCapture('stderr: ', True, partialJavadoc)

        run([get_jdk().javadoc, memory,
             '-classpath', cp,
             '-quiet',
             '-d', out,
             '-doclet', 'org.apidesign.javadoc.codesnippet.Doclet',
             '-docletpath', snippetslib,
             '-snippetpath', snippets,
             '-sourcepath', sp] +
             ([] if jdk.javaCompliance < JavaCompliance('1.8') else ['-Xdoclint:none']) +
             (['-overview', overviewFile] if exists(overviewFile) else []) +
             groupargs +
             links +
             extraArgs +
             nowarnAPI +
             list(pkgs), True, captureOut, captureErr)

        if not args.allow_warnings and captureErr.warnings:
            abort('Error: Warnings in the javadoc are not allowed!')
        if args.allow_warnings and not captureErr.warnings:
            logv("Warnings were allowed but there was none")

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

    projects_arg = []
    if args.projects is not None:
        projects_arg = ['--projects', args.projects]
        projects = [project(name) for name in args.projects.split(',')]
    else:
        projects = []
        walk_deps(visit=lambda dep, edge: projects.append(dep) if dep.isProject() else None, ignoredEdges=[DEP_EXCLUDED])

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

@primary_suite_exempt
def sclone(args):
    """clone a suite repository, and its imported suites"""
    parser = ArgumentParser(prog='mx sclone')
    parser.add_argument('--source', help='url/path of repo containing suite', metavar='<url>')
    parser.add_argument('--dest', help='destination directory (default basename of source)', metavar='<path>')
    parser.add_argument("--no-imports", action='store_true', help='do not clone imported suites')
    parser.add_argument("--kind", help='vc kind for URL suites', default='hg')
    parser.add_argument('--ignore-version', action='store_true', help='ignore version mismatch for existing suites')
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

    if args.dest is not None:
        dest = args.dest
    else:
        dest = basename(source.rstrip('/'))

    dest = os.path.abspath(dest)
    # We can now set the primary dir for the src/dst suitemodel
    _dst_suitemodel.set_primary_dir(dest)
    _src_suitemodel.set_primary_dir(source)

    _sclone(source, dest, None, args.no_imports, args.kind, primary=True, ignoreVersion=args.ignore_version)

def _sclone(source, dest, suite_import, no_imports=False, vc_kind=None, manual=None, primary=False, ignoreVersion=False, importingSuite=None):
    rev = suite_import.version if suite_import is not None and suite_import.version is not None else None
    url_vcs = SuiteImport.get_source_urls(source, vc_kind)
    if manual is not None:
        assert len(url_vcs) > 0
        revname = rev if rev else 'tip'
        if suite_import.name in manual:
            if manual[suite_import.name] == revname:
                return None
            resolved = _resolve_suite_version_conflict(suite_import.name, None, manual[suite_import.name], None, suite_import, importingSuite)
            if not resolved:
                return None
            revname = resolved
        log("Clone {} at revision {} into {}".format(' or '.join(("{} with {}".format(url_vc.url, url_vc.vc.kind) for url_vc in url_vcs)), revname, dest))
        manual[suite_import.name] = revname
        return None
    for url_vc in url_vcs:
        if url_vc.vc.clone(url_vc.url, rev=rev, dest=dest):
            break

    if not exists(dest):
        if len(url_vcs) == 0:
            reason = 'no url provided'
            if suite_import.dynamicImport:
                reason += ' for dynamic import. Dynamically imported suites should be cloned first (clone {} to {})'.format(suite_import.name, dest)
        else:
            reason = 'none of the urls worked'
        warn("Could not clone {}: {}".format(suite_import.name, reason))
        return None

    mxDir = _is_suite_dir(dest)
    if mxDir is None:
        warn(dest + ' is not an mx suite')
        return None

    # create a Suite (without loading) to enable imports visitor
    s = SourceSuite(mxDir, load=False, dynamicallyImported=suite_import.dynamicImport if suite_import else False, primary=primary)
    if not no_imports:
        s.visit_imports(_scloneimports_visitor, source=dest, manual=manual, ignoreVersion=ignoreVersion)
    return s

def _scloneimports_visitor(s, suite_import, source, manual=None, ignoreVersion=False, **extra_args):
    """
    cloneimports visitor for Suite.visit_imports.
    The destination information is encapsulated by 's'
    """
    _scloneimports(s, suite_import, source, manual, ignoreVersion)

def _scloneimports_suitehelper(sdir, primary=False, dynamicallyImported=False):
    mxDir = _is_suite_dir(sdir)
    if mxDir is None:
        abort(sdir + ' is not an mx suite')
    else:
        # create a Suite (without loading) to enable imports visitor
        return SourceSuite(mxDir, primary=primary, load=False, dynamicallyImported=dynamicallyImported)

def _scloneimports(s, suite_import, source, manual=None, ignoreVersion=False):
    # clone first, then visit imports once we can locate them
    importee_source = _src_suitemodel.importee_dir(source, suite_import)
    importee_dest = _dst_suitemodel.importee_dir(s.dir, suite_import)
    if exists(importee_dest):
        # already exists in the suite model, but may be wrong version
        importee_suite = _scloneimports_suitehelper(importee_dest, dynamicallyImported=suite_import.dynamicImport)
        existingRevision = importee_suite.version()
        if not ignoreVersion and existingRevision != suite_import.version:
            resolved = _resolve_suite_version_conflict(suite_import.name, importee_suite, existingRevision, None, suite_import, s)
            if resolved:
                assert resolved != existingRevision
                if manual:
                    if suite_import.name not in manual or manual[suite_import.name] != resolved:
                        log("Update {} to revision {} with {}".format(importee_dest, resolved, importee_suite.vc.kind))
                        manual[suite_import.name] = resolved
                else:
                    importee_suite.vc.update(importee_dest, rev=resolved, mayPull=True)
        importee_suite.visit_imports(_scloneimports_visitor, source=importee_dest, manual=manual, ignoreVersion=ignoreVersion)
    else:
        _sclone(importee_source, importee_dest, suite_import, manual=manual, ignoreVersion=ignoreVersion, importingSuite=s)
        # _clone handles the recursive visit of the new imports

@primary_suite_exempt
def scloneimports(args):
    """clone the imports of an existing suite"""
    parser = ArgumentParser(prog='mx scloneimports')
    parser.add_argument('--source', help='url/path of repo containing suite', metavar='<url>')
    parser.add_argument('--manual', action='store_true', help='does not actually do the clones but prints the necessary clones')
    parser.add_argument('--ignore-version', action='store_true', help='ignore version mismatch for existing suites')
    parser.add_argument('nonKWArgs', nargs=REMAINDER, metavar='source [dest]...')
    args = parser.parse_args(args)
    # check for non keyword args
    if args.source is None:
        args.source = _kwArg(args.nonKWArgs)
    if not args.source:
        abort('scloneimports: url/path of repo containing suite missing')

    if not os.path.isdir(args.source):
        abort(args.source + ' is not a directory')

    source = os.path.realpath(args.source)
    vcs = VC.get_vc(source)
    s = _scloneimports_suitehelper(source, primary=True)

    default_path = vcs.default_pull(source)

    # We can now set the primary directory for the dst suitemodel
    # N.B. source is effectively the destination and the default_path is the (original) source
    _dst_suitemodel.set_primary_dir(source)
    s.visit_imports(_scloneimports_visitor, source=default_path, manual={} if args.manual else None, ignoreVersion=args.ignore_version)

def _spush_import_visitor(s, suite_import, dest, checks, clonemissing, **extra_args):
    """push visitor for Suite.visit_imports"""
    if dest is not None:
        dest = _dst_suitemodel.importee_dir(dest, suite_import)
    _spush(suite(suite_import.name), suite_import, dest, checks, clonemissing)

def _spush_check_import_visitor(s, suite_import, **extra_args):
    """push check visitor for Suite.visit_imports"""
    importedVersion = suite(suite_import.name).version()
    if importedVersion != suite_import.version:
        abort('imported version of ' + suite_import.name + ' in suite ' + s.name + ' does not match tip')

def _spush(s, suite_import, dest, checks, clonemissing):
    vcs = s.vc
    if checks['on']:
        if not vcs.can_push(s.dir, checks['strict'], abortOnError=False):
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

    def get_version():
        if suite_import is not None and suite_import.version is not None:
            return suite_import.version
        else:
            return None

    if dest_exists:
        vcs.push(s.dir, rev=get_version(), dest=dest)
    else:
        vcs.clone(s.dir, rev=get_version(), dest=dest)

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
    s.vc.update(s.dir)

def supdate(args):
    """update primary suite and all its imports"""

    parser = ArgumentParser(prog='mx supdate')
    args = parser.parse_args(args)
    s = _check_primary_suite()

    _supdate(s, None)

def _sbookmark_visitor(s, suite_import):
    imported_suite = suite(suite_import.name)
    if isinstance(imported_suite, SourceSuite):
        imported_suite.vc.bookmark(imported_suite.dir, s.name + '-import', suite_import.version)

def sbookmarkimports(args):
    """place bookmarks on the imported versions of suites in version control"""
    parser = ArgumentParser(prog='mx sbookmarkimports')
    parser.add_argument('--all', action='store_true', help='operate on all suites (default: primary suite only)')
    args = parser.parse_args(args)
    if args.all:
        for s in suites():
            s.visit_imports(_sbookmark_visitor)
    else:
        _check_primary_suite().visit_imports(_sbookmark_visitor)


def _scheck_imports_visitor(s, suite_import, bookmark_imports, ignore_uncommitted):
    """scheckimports visitor for Suite.visit_imports"""
    _scheck_imports(s, suite(suite_import.name), suite_import, bookmark_imports, ignore_uncommitted)

def _scheck_imports(importing_suite, imported_suite, suite_import, bookmark_imports, ignore_uncommitted):
    importedVersion = imported_suite.version()
    if imported_suite.isDirty() and not ignore_uncommitted:
        msg = 'uncommitted changes in {}, please commit them and re-run scheckimports'.format(imported_suite.name)
        if isinstance(imported_suite, SourceSuite) and imported_suite.vc and imported_suite.vc.kind == 'hg':
            msg = '{}\nIf the only uncommitted change is an updated imported suite version, then you can run:\n\nhg -R {} commit -m "updated imported suite version"'.format(msg, imported_suite.dir)
        abort(msg)
    if importedVersion != suite_import.version:
        print 'imported version of {} in {} ({}) does not match parent ({})'.format(imported_suite.name, importing_suite.name, suite_import.version, importedVersion)
        if exists(importing_suite.suite_py()) and is_interactive() and ask_yes_no('Update ' + importing_suite.suite_py()):
            with open(importing_suite.suite_py()) as fp:
                contents = fp.read()
            if contents.count(str(suite_import.version)) == 1:
                newContents = contents.replace(suite_import.version, str(importedVersion))
                update_file(importing_suite.suite_py(), newContents, showDiff=True)
                suite_import.version = importedVersion
                if bookmark_imports:
                    _sbookmark_visitor(importing_suite, suite_import)
            else:
                print 'Could not update as the substring {} does not appear exactly once in {}'.format(suite_import.version, importing_suite.suite_py())

def scheckimports(args):
    """check that suite import versions are up to date"""
    parser = ArgumentParser(prog='mx scheckimports')
    parser.add_argument('-b', '--bookmark-imports', action='store_true', help="keep the import bookmarks up-to-date when updating the suites.py file")
    parser.add_argument('-i', '--ignore-uncommitted', action='store_true', help="Ignore uncommitted changes in the suite")
    args = parser.parse_args(args)
    # check imports of all suites
    for s in suites():
        s.visit_imports(_scheck_imports_visitor, bookmark_imports=args.bookmark_imports, ignore_uncommitted=args.ignore_uncommitted)

def _sforce_imports_visitor(s, suite_import, import_map, strict_versions, **extra_args):
    """sforceimports visitor for Suite.visit_imports"""
    _sforce_imports(s, suite(suite_import.name), suite_import, import_map, strict_versions)

def _sforce_imports(importing_suite, imported_suite, suite_import, import_map, strict_versions):
    suite_import_version = suite_import.version
    if imported_suite.name in import_map:
        # we have seen this already
        resolved = _resolve_suite_version_conflict(imported_suite.name, imported_suite, import_map[imported_suite.name], None, suite_import, importing_suite)
        if not resolved:
            return
        suite_import_version = resolved
    else:
        import_map[imported_suite.name] = suite_import_version

    if suite_import_version:
        # normal case, a specific version
        importedVersion = imported_suite.version()
        if importedVersion != suite_import_version:
            if imported_suite.isDirty():
                if is_interactive():
                    if not ask_yes_no('WARNING: Uncommited changes in {} will be lost! Really continue'.format(imported_suite.name), default='n'):
                        abort('aborting')
                else:
                    abort('Uncommited changes in {}, aborting.'.format(imported_suite.name))
            if imported_suite.vc.kind != suite_import.kind:
                abort('Wrong VC type for {} ({}), expecting {}, got {}'.format(imported_suite.name, imported_suite.dir, suite_import.kind, imported_suite.vc.kind))
            imported_suite.vc.update(imported_suite.dir, suite_import_version, mayPull=True, clean=True)
    else:
        # unusual case, no version specified, so pull the head
        imported_suite.vc.pull(imported_suite.dir, update=True)

    # now (may) need to force imports of this suite if the above changed its import revs
    # N.B. the suite_imports from the old version may now be invalid
    imported_suite.re_init_imports()
    imported_suite.visit_imports(_sforce_imports_visitor, import_map=import_map, strict_versions=strict_versions)

def sforceimports(args):
    '''force working directory revision of imported suites to match primary suite imports'''
    parser = ArgumentParser(prog='mx sforceimports')
    parser.add_argument('--strict-versions', action='store_true', help='strict version checking')
    args = parser.parse_args(args)
    _check_primary_suite().visit_imports(_sforce_imports_visitor, import_map=dict(), strict_versions=args.strict_versions)

def _spull_import_visitor(s, suite_import, update_versions, only_imports, update_all, no_update):
    """pull visitor for Suite.visit_imports"""
    _spull(s, suite(suite_import.name), suite_import, update_versions, only_imports, update_all, no_update)

def _spull(importing_suite, imported_suite, suite_import, update_versions, only_imports, update_all, no_update):
    # suite_import is None if importing_suite is primary suite
    primary = suite_import is None
    # proceed top down to get any updated version ids first

    if not primary or not only_imports:
        # skip pull of primary if only_imports = True
        vcs = imported_suite.vc
        # by default we pull to the revision id in the import, but pull head if update_versions = True
        rev = suite_import.version if not update_versions and suite_import and suite_import.version else None
        if rev and vcs.kind != suite_import.kind:
            abort('Wrong VC type for {} ({}), expecting {}, got {}'.format(imported_suite.name, imported_suite.dir, suite_import.kind, imported_suite.vc.kind))
        vcs.pull(imported_suite.dir, rev, update=not no_update)

    if not primary and update_versions:
        importedVersion = vcs.parent(imported_suite.dir)
        if importedVersion != suite_import.version:
            if exists(importing_suite.suite_py()):
                with open(importing_suite.suite_py()) as fp:
                    contents = fp.read()
                if contents.count(str(suite_import.version)) == 1:
                    newContents = contents.replace(suite_import.version, str(importedVersion))
                    log('Updating "version" attribute in import of suite ' + suite_import.name + ' in ' + importing_suite.suite_py() + ' to ' + importedVersion)
                    update_file(importing_suite.suite_py(), newContents, showDiff=True)
                else:
                    log('Could not update as the substring {} does not appear exactly once in {}'.format(suite_import.version, importing_suite.suite_py()))
                    log('Please update "version" attribute in import of suite ' + suite_import.name + ' in ' + importing_suite.suite_py() + ' to ' + importedVersion)
            suite_import.version = importedVersion

    imported_suite.re_init_imports()
    if not primary and not update_all:
        update_versions = False
    imported_suite.visit_imports(_spull_import_visitor, update_versions=update_versions, only_imports=only_imports, update_all=update_all, no_update=no_update)

def spull(args):
    """pull primary suite and all its imports"""
    parser = ArgumentParser(prog='mx spull')
    parser.add_argument('--update-versions', action='store_true', help='pull tip of directly imported suites and update suite.py')
    parser.add_argument('--update-all', action='store_true', help='pull tip of all imported suites (transitively)')
    parser.add_argument('--only-imports', action='store_true', help='only pull imported suites, not the primary suite')
    parser.add_argument('--no-update', action='store_true', help='only pull, without updating')
    args = parser.parse_args(args)

    if args.update_all and not args.update_versions:
        abort('--update-all can only be used in conjuction with --update-versions')

    _spull(_check_primary_suite(), _check_primary_suite(), None, args.update_versions, args.only_imports, args.update_all, args.no_update)

def _sincoming_import_visitor(s, suite_import, **extra_args):
    _sincoming(suite(suite_import.name), suite_import)

def _sincoming(s, suite_import):
    s.visit_imports(_sincoming_import_visitor)

    output = s.vc.incoming(s.dir)
    if output:
        print output

def sincoming(args):
    '''check incoming for primary suite and all imports'''
    parser = ArgumentParser(prog='mx sincoming')
    args = parser.parse_args(args)
    s = _check_primary_suite()

    _sincoming(s, None)

def _hg_command_import_visitor(s, suite_import, **extra_args):
    _hg_command(suite(suite_import.name), suite_import, **extra_args)

def _hg_command(s, suite_import, **extra_args):
    s.visit_imports(_hg_command_import_visitor, **extra_args)

    if isinstance(s.vc, HgConfig):
        out = s.vc.hg_command(s.dir, extra_args['args'])
        print out

def hg_command(args):
    '''Run a Mercurial command in every suite'''
    s = _check_primary_suite()
    _hg_command(s, None, args=args)

def _soutgoing_import_visitor(s, suite_import, dest, **extra_args):
    if dest is not None:
        dest = _dst_suitemodel.importee_dir(dest, suite_import)
    _soutgoing(suite(suite_import.name), suite_import, dest)

def _soutgoing(s, suite_import, dest):
    s.visit_imports(_soutgoing_import_visitor, dest=dest)

    output = s.vc.outgoing(s.dir, dest)
    if output:
        print output

def soutgoing(args):
    '''check outgoing for primary suite and all imports'''
    parser = ArgumentParser(prog='mx soutgoing')
    parser.add_argument('--dest', help='url/path of repo to push to (default as per hg push)', metavar='<path>')
    parser.add_argument('nonKWArgs', nargs=REMAINDER, metavar='source [dest]...')
    args = parser.parse_args(args)
    if args.dest is None:
        args.dest = _kwArg(args.nonKWArgs)
    if len(args.nonKWArgs) > 0:
        abort('unrecognized args: ' + ' '.join(args.nonKWArgs))
    s = _check_primary_suite()

    if args.dest is not None:
        _dst_suitemodel.set_primary_dir(args.dest)

    _soutgoing(s, None, args.dest)

def _stip_import_visitor(s, suite_import, **extra_args):
    _stip(suite(suite_import.name), suite_import)

def _stip(s, suite_import):
    s.visit_imports(_stip_import_visitor)

    print 'tip of ' + s.name + ': ' + s.vc.tip(s.dir)

def stip(args):
    '''check tip for primary suite and all imports'''
    parser = ArgumentParser(prog='mx stip')
    args = parser.parse_args(args)
    s = _check_primary_suite()

    _stip(s, None)

def _sversions_rev(rev, isdirty, with_color):
    if with_color:
        color_on, color_off = '\033[93m', '\033[0m'
    else:
        color_on = color_off = ''
    return color_on + rev[0:12] + color_off + rev[12:] + ' +'[int(isdirty)]

def sversions(args):
    '''print working directory revision for primary suite and all imports'''
    parser = ArgumentParser(prog='mx sversions')
    parser.add_argument('--color', action='store_true', help='color the short form part of the revision id')
    args = parser.parse_args(args)
    with_color = args.color
    visited = set()

    def _sversions_import_visitor(s, suite_import, **extra_args):
        _sversions(suite(suite_import.name), suite_import)

    def _sversions(s, suite_import):
        if s.dir in visited:
            return
        visited.add(s.dir)
        if s.vc == None:
            print 'No version control info for suite ' + s.name
        else:
            print _sversions_rev(s.vc.parent(s.dir), s.vc.isDirty(s.dir), with_color) + ' ' + s.name
        s.visit_imports(_sversions_import_visitor)

    primary_suite = _check_primary_suite()
    if not isinstance(primary_suite, MXSuite):
        _sversions(primary_suite, None)

def findclass(args, logToConsole=True, resolve=True, matcher=lambda string, classname: string in classname):
    """find all classes matching a given substring"""
    matches = []
    for entry, filename in classpath_walk(includeBootClasspath=True, resolve=resolve):
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

    parser = ArgumentParser(prog='mx javap')
    parser.add_argument('-r', '--resolve', action='store_true', help='perform eager resolution (e.g., download missing jars) of class search space')
    parser.add_argument('classes', nargs=REMAINDER, metavar='<class name patterns...>')

    args = parser.parse_args(args)

    javapExe = get_jdk().javap
    if not exists(javapExe):
        abort('The javap executable does not exist: ' + javapExe)
    else:
        candidates = findclass(args.classes, resolve=args.resolve, logToConsole=False)
        if len(candidates) == 0:
            log('no matches')
        selection = select_items(candidates)
        run([javapExe, '-private', '-verbose', '-classpath', classpath(resolve=args.resolve)] + selection)

def show_projects(args):
    """show all projects"""
    for s in suites():
        if len(s.projects) != 0:
            log(s.suite_py())
            for p in s.projects:
                log('\t' + p.name)

def show_suites(args):
    """show all suites

    usage: mx suites [-h] [--locations] [--licenses]

    optional arguments:
      -h, --help   show this help message and exit
      --locations  show element locations on disk
      --licenses   show element licenses
    """
    parser = ArgumentParser(prog='mx suites')
    parser.add_argument('-p', '--locations', action='store_true', help='show element locations on disk')
    parser.add_argument('-l', '--licenses', action='store_true', help='show element licenses')
    parser.add_argument('-a', '--archived-deps', action='store_true', help='show archived deps for distributions')
    args = parser.parse_args(args)
    def _location(e):
        if args.locations:
            if isinstance(e, Suite):
                return e.mxDir
            if isinstance(e, Library):
                return join(e.suite.dir, e.path)
            if isinstance(e, Distribution):
                return e.path
            if isinstance(e, Project):
                return e.dir
        return None
    def _show_section(name, section):
        if section:
            log('  ' + name + ':')
            for e in section:
                location = _location(e)
                out = '    ' + e.name
                data = []
                if location:
                    data.append(location)
                if args.licenses:
                    if e.theLicense:
                        l = e.theLicense.name
                    else:
                        l = '??'
                    data.append(l)
                if data:
                    out += ' (' + ', '.join(data) + ')'
                log(out)
                if name == 'distributions' and args.archived_deps:
                    for a in e.archived_deps():
                        log('      ' + a.name)

    for s in suites(True):
        location = _location(s)
        if location:
            log('{} ({})'.format(s.name, location))
        else:
            log(s.name)
        _show_section('libraries', s.libs)
        _show_section('jrelibraries', s.jreLibs)
        _show_section('jdklibraries', s.jdkLibs)
        _show_section('projects', s.projects)
        _show_section('distributions', s.dists)

def _compile_mx_class(javaClassName, classpath=None, jdk=None, myDir=None):
    myDir = _mx_home if myDir is None else myDir
    binDir = join(_mx_suite.get_output_root(), 'bin' if not jdk else '.jdk' + str(jdk.version))
    javaSource = join(myDir, javaClassName + '.java')
    javaClass = join(binDir, javaClassName + '.class')
    if not exists(javaClass) or getmtime(javaClass) < getmtime(javaSource):
        ensure_dir_exists(binDir)
        javac = jdk.javac if jdk else get_jdk(tag=DEFAULT_JDK_TAG).javac
        cmd = [javac, '-d', _cygpathU2W(binDir)]
        if classpath:
            cmd += ['-cp', _separatedCygpathU2W(binDir + os.pathsep + classpath)]
        cmd += [_cygpathU2W(javaSource)]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            abort('failed to compile:' + javaSource)


    return (myDir, binDir)

def assessannotationprocessors(args):
    '''apply heuristics to determine if projects declare exactly the
    annotation processors they need

    This process automatically analyzes annotation processors annotated
    with @SupportedAnnotationTypes. Extra annotation processor dependencies
    and the annotation types they support can be supplied on the command line.
    Note that this tool is only based on heuristics and may thus result in
    incorrect suggestions. For example, two different annotations that have
    the same unqualified name (e.g. @NodeInfo) will cause misleading suggestions
    about missing annotation processors.
    '''
    parser = ArgumentParser(prog='mx assesaps')
    parser.add_argument('apspecs', help='annotation processor spec with the format <name>:<ap>,... where <name> is a ' +
                        'substring matching the name of a unique dependency defining one or more annotation processors ' +
                        'and the list of comma separated <ap>\'s are annotation types processed by <name>', nargs='*', metavar='apspec')

    args = parser.parse_args(args)

    allProjects = [p for p in dependencies() if p.isJavaProject()]
    apDists = [d for d in dependencies() if d.isJARDistribution() and d.definedAnnotationProcessors]
    packageToProject = {}
    for p in allProjects:
        for pkg in p.defined_java_packages():
            packageToProject[pkg] = p

    def pkgAndClass(fqn):
        '''Partitions a fully qualified class name into a package name and class name.
        Assumes package components always start with a lower case letter and class names
        start with an upper case letter.'''
        m = re.search(r'\.[A-Z]', fqn)
        assert m, fqn
        return fqn[0:m.start()], fqn[m.start() + 1:]

    apdepToAnnotations = {}
    supportedAnnotationTypesRE = re.compile(r'@SupportedAnnotationTypes\({?([^}\)]+)}?\)')
    annotationRE = re.compile(r'"([^"]+)"')

    for apDist in apDists:
        for p in [p for p in apDist.deps if p.isJavaProject()]:
            matches = p.find_classes_with_annotations(None, ['@SupportedAnnotationTypes'])
            if matches:
                for apFqn, pathAndLineNo in matches.iteritems():
                    pkg, _ = pkgAndClass(apFqn)
                    apProject = packageToProject[pkg]
                    assert apProject, apFqn
                    path, lineNo = pathAndLineNo
                    with open(path) as fp:
                        for m in supportedAnnotationTypesRE.finditer(fp.read()):
                            sat = m.group(1)
                            for annotation in annotationRE.finditer(sat):
                                parts = annotation.group(1).split('.')
                                name = None
                                for p in reversed(parts):
                                    name = (p + '.' + name) if name else p
                                    if p[0].isupper():
                                        apdepToAnnotations.setdefault(apDist, []).append(name)
                                assert not name[0].isupper()
                                apdepToAnnotations[apDist].append(name)

    for apspec in args.apspecs:
        if ':' not in apspec:
            abort(apspec + ' does not contain ":"')
        apdep, annotations = apspec.split(':', 1)
        candidates = [d for d in dependencies() if apdep in d.name]
        if not candidates:
            abort(apdep + ' does not match any dependency')
        elif len(candidates) > 1:
            abort('"{}" matches more than one dependency: {}'.format(apdep, ', '.join([c.name for c in candidates])))
        apdep = candidates[0]
        annotations = annotations.split(',')
        apdepToAnnotations[apdep] = annotations

    for apdep, annotations in apdepToAnnotations.iteritems():
        annotations = ['@' + a for a in annotations]
        log('-- Analyzing ' + str(apdep) + ' with supported annotations ' + ','.join(annotations) + ' --')
        for p in allProjects:
            matches = p.find_classes_with_annotations(None, annotations)
            apdepName = apdep.name if apdep.suite is p.suite else apdep.suite.name + ':' + apdep.name
            if matches:
                if apdep not in p.declaredAnnotationProcessors:
                    context = p.__abort_context__()
                    if context:
                        log(context)
                        log('"annotationProcessors" attribute should include "{}"'.format(apdepName))
                    else:
                        log('"annotationProcessors" attribute of {} should include "{}":'.format(p, apdepName))
                    log("Witness:")
                    witness = matches.popitem()
                    (_, (path, lineNo)) = witness
                    log(path + ':' + str(lineNo))
                    with open(path) as fp:
                        log(fp.readlines()[lineNo - 1])
            else:
                if apdep in p.declaredAnnotationProcessors:
                    context = p.__abort_context__()
                    if context:
                        log(context)
                        log('"annotationProcessors" attribute should not include {}'.format(apdepName))
                    else:
                        log('"annotationProcessors" attribute of {} should not include {}'.format(p, apdepName))
                    log('Could not find any matches for these patterns: ' + ', '.join(annotations))

def _add_command_primary_option(parser):
    parser.add_argument('--primary', action='store_true', help='limit checks to primary suite')

def checkcopyrights(args):
    '''run copyright check on the sources'''
    class CP(ArgumentParser):
        def format_help(self):
            return ArgumentParser.format_help(self) + self._get_program_help()

        def _get_program_help(self):
            help_output = subprocess.check_output([get_jdk().java, '-cp', _cygpathU2W(binDir), 'CheckCopyright', '--help'])
            return '\nother argumemnts preceded with --\n' +  help_output

    # ensure compiled form of code is up to date
    myDir, binDir = _compile_mx_class('CheckCopyright')

    parser = CP(prog='mx checkcopyrights')

    _add_command_primary_option(parser)
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
        rc = run([get_jdk().java, '-cp', _cygpathU2W(binDir), 'CheckCopyright', '--copyright-dir', _cygpathU2W(myDir)] + custom_args + args.remainder, cwd=s.dir, nonZeroIsFatal=False)
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

def split_j_args(extraVmArgsList):
    extraVmArgs = []
    if extraVmArgsList:
        for e in extraVmArgsList:
            extraVmArgs += [x for x in shlex.split(e.lstrip('@'))]
    return extraVmArgs

def junit(args, harness=_basic_junit_harness, parser=None):
    '''run Junit tests'''
    suppliedParser = parser is not None
    parser = parser if suppliedParser else ArgumentParser(prog='mx junit')
    parser.add_argument('--tests', action='store', help='pattern to match test classes')
    parser.add_argument('--J', dest='vm_args', action='append', help='target VM arguments (e.g. --J @-dsa)', metavar='@<args>')
    if suppliedParser:
        parser.add_argument('remainder', nargs=REMAINDER, metavar='...')
    args = parser.parse_args(args)

    vmArgs = ['-ea', '-esa']

    if args.vm_args:
        vmArgs = vmArgs + split_j_args(args.vm_args)

    testfile = os.environ.get('MX_TESTFILE', None)
    if testfile is None:
        (_, testfile) = tempfile.mkstemp(".testclasses", "mx")
        os.close(_)

    candidates = []
    jdk = get_jdk()
    for p in projects_opt_limit_to_suites():
        if not p.isJavaProject() or jdk.javaCompliance < p.javaCompliance:
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
                warn('no tests matched by substring "' + t + '"')

    projectscp = classpath([pcp.name for pcp in projects_opt_limit_to_suites() if pcp.isJavaProject() and pcp.javaCompliance <= jdk.javaCompliance])

    if len(classes) != 0:
        # Compiling wrt projectscp avoids a dependency on junit.jar in mxtool itself
        # However, perhaps because it's Friday 13th javac is not actually compiling
        # this file, yet not returning error. It is perhaps related to annotation processors
        # so the workaround is to extract the junit path as that is all we need.
        junitpath = [s for s in projectscp.split(":") if "junit" in s]
        if len(junitpath) is 0:
            junitpath = [s for s in projectscp.split(":") if "JUNIT" in s]
        junitpath = junitpath[0]

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

def mvn_local_install(suite_name, dist_name, path, version):
    if not exists(path):
        abort('File ' + path + ' does not exists')
    run_maven(['install:install-file', '-DgroupId=com.oracle.' + suite_name, '-DartifactId=' + dist_name, '-Dversion=' +
            version, '-Dpackaging=jar', '-Dfile=' + path, '-DcreateChecksum=true'])

def maven_install(args):
    '''
    Install the primary suite in a maven repository, mainly for testing as it
    only actually does the install if --local is set.
    '''
    parser = ArgumentParser(prog='mx maven-install')
    parser.add_argument('--no-checks', action='store_true', help='checks on status are disabled')
    parser.add_argument('--test', action='store_true', help='print info about JARs to be installed')
    args = parser.parse_args(args)

    _mvn.check()
    s = _primary_suite
    nolocalchanges = args.no_checks or s.vc.can_push(s.dir, strict=False)
    version = s.vc.parent(s.dir)
    releaseVersion = s.release_version(snapshotSuffix='SNAPSHOT')
    arcdists = []
    for dist in s.dists:
        # ignore non-exported dists
        if not dist.internal and not dist.name.startswith('COM_ORACLE'):
            arcdists.append(dist)

    mxMetaName = _mx_binary_distribution_root(s.name)
    s.create_mx_binary_distribution_jar()
    mxMetaJar = s.mx_binary_distribution_jar_path()
    if not args.test:
        if nolocalchanges:
            mvn_local_install(s.name, _map_to_maven_dist_name(mxMetaName), mxMetaJar, version)
        else:
            print 'Local changes found, skipping install of ' + version + ' version'
        mvn_local_install(s.name, _map_to_maven_dist_name(mxMetaName), mxMetaJar, releaseVersion)
        for dist in arcdists:
            if nolocalchanges:
                mvn_local_install(s.name, _map_to_maven_dist_name(dist.name), dist.path, version)
            mvn_local_install(s.name, _map_to_maven_dist_name(dist.name), dist.path, releaseVersion)
    else:
        print 'jars to deploy manually for version: ' + version
        print 'name: ' + _map_to_maven_dist_name(mxMetaName) + ', path: ' + os.path.relpath(mxMetaJar, s.dir)
        for dist in arcdists:
            print 'name: ' + _map_to_maven_dist_name(dist.name) + ', path: ' + os.path.relpath(dist.path, s.dir)

def ensure_dir_exists(path, mode=None):
    """
    Ensures all directories on 'path' exists, creating them first if necessary with os.makedirs().
    """
    if not isdir(path):
        try:
            if mode:
                os.makedirs(path, mode=mode)
            else:
                os.makedirs(path)
        except OSError as e:
            if e.errno == errno.EEXIST and isdir(path):
                # be happy if another thread already created the path
                pass
            else:
                raise e
    return path

def show_envs(args):
    '''print environment variables and their values

    By default only variables starting with "MX" are shown.
    The --all option forces all variables to be printed'''
    parser = ArgumentParser(prog='mx envs')
    parser.add_argument('--all', action='store_true', help='show all variables, not just those starting with "MX"')
    args = parser.parse_args(args)

    for key, value in os.environ.iteritems():
        if args.all or key.startswith('MX'):
            print '{0}: {1}'.format(key, value)

def show_version(args):
    '''print mx version'''

    parser = ArgumentParser(prog='mx version')
    parser.add_argument('--oneline', action='store_true', help='show mx revision and version in one line')
    args = parser.parse_args(args)
    if args.oneline:
        vc = VC.get_vc(_mx_home, abortOnError=False)
        if vc == None:
            print 'No version control info for mx %s' % version
        else:
            print _sversions_rev(vc.parent(_mx_home), vc.isDirty(_mx_home), False) + ' mx %s' % version
        return

    print version
    vc = VC.get_vc(_mx_home, abortOnError=False)
    if isinstance(vc, HgConfig):
        out = vc.hg_command(_mx_home, ['id', '-i'], quiet=True, abortOnError=False)
        if out:
            print 'hg:', out

@suite_context_free
def update(args):
    '''update mx to the latest version'''
    parser = ArgumentParser(prog='mx update')
    parser.add_argument('-n', '--dry-run', action='store_true', help='show incoming changes without applying them')
    args = parser.parse_args(args)

    vc = VC.get_vc(_mx_home, abortOnError=False)
    if isinstance(vc, GitConfig):
        if args.dry_run:
            print vc.incoming(_mx_home)
        else:
            print vc.pull(_mx_home, update=True)
    else:
        print 'Cannot update mx as git is unavailable'

def remove_doubledash(args):
    if '--' in args:
        args.remove('--')

def ask_yes_no(question, default=None):
    """"""
    assert not default or default == 'y' or default == 'n'
    questionMark = '? [yn]: '
    if default:
        questionMark = questionMark.replace(default, default.upper())
    if _opts.answer:
        answer = str(_opts.answer)
        print question + questionMark + answer
    else:
        if is_interactive():
            answer = raw_input(question + questionMark) or default
            while not answer:
                answer = raw_input(question + questionMark)
        else:
            if default:
                answer = default
            else:
                abort("Can not answer '" + question + "?' if stdin is not a tty")
    return answer.lower().startswith('y')

def add_argument(*args, **kwargs):
    """
    Defines a single command-line argument.
    """
    assert _argParser is not None
    _argParser.add_argument(*args, **kwargs)

def update_commands(suite, new_commands):
    for key, value in new_commands.iteritems():
        assert ':' not in key
        old = _commands.get(key)
        if old is not None:
            oldSuite = _commandsToSuite.get(key)
            if not oldSuite:
                # Core mx command is overridden by first suite
                # defining command of same name. The core mx
                # command has its name prefixed with ':'.
                _commands[':' + key] = old
            else:
                # Previously specified command from another suite
                # is made available using a qualified name.
                # The last (primary) suite (depth-first init) always defines the generic command
                # N.B. Dynamically loaded suites loaded via Suite.import_suite register after the primary
                # suite but they must not override the primary definition.
                if oldSuite == _primary_suite:
                    # ensure registered as qualified by the registering suite
                    key = suite.name  + ':' + key
                else:
                    qkey = oldSuite.name + ':' + key
                    _commands[qkey] = old
        _commands[key] = value
        _commandsToSuite[key] = suite

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

def warn(msg, context=None):
    if _opts.warn:
        if context is not None:
            if callable(context):
                contextMsg = context()
            elif hasattr(context, '__abort_context__'):
                contextMsg = context.__abort_context__()
            else:
                contextMsg = str(context)
            msg = contextMsg + ":\n" + msg
        print 'WARNING: ' + msg

# Table of commands in alphabetical order.
# Keys are command names, value are lists: [<function>, <usage msg>, <format args to doc string of function>...]
# If any of the format args are instances of Callable, then they are called with an 'env' are before being
# used in the call to str.format().
# Suite extensions should not update this table directly, but use update_commands
_commands = {
    'about': [about, ''],
    'assessaps': [assessannotationprocessors, '[options]'],
    'bench': [bench, ''],
    'build': [build, '[options]'],
    'canonicalizeprojects': [canonicalizeprojects, ''],
    'checkcopyrights': [checkcopyrights, '[options]'],
    'checkheaders': [mx_gate.checkheaders, ''],
    'checkoverlap': [checkoverlap, ''],
    'checkstyle': [checkstyle, ''],
    'sigtest': [mx_sigtest.sigtest, ''],
    'clean': [clean, ''],
    'eclipseinit': [eclipseinit_cli, ''],
    'eclipseformat': [eclipseformat, ''],
    'exportlibs': [exportlibs, ''],
    'findbugs': [mx_findbugs.findbugs, ''],
    'findclass': [findclass, ''],
    'fsckprojects': [fsckprojects, ''],
    'gate': [mx_gate.gate, '[options]'],
    'help': [help_, '[command]'],
    'ideclean': [ideclean, ''],
    'ideinit': [ideinit, ''],
    'intellijinit': [intellijinit, ''],
    'jacocoreport' : [mx_gate.jacocoreport, '[output directory]'],
    'archive': [_archive, '[options]'],
    'maven-install' : [maven_install, ''],
    'maven-deploy' : [maven_deploy, ''],
    'deploy-binary' : [deploy_binary, ''],
    'projectgraph': [projectgraph, ''],
    'sclone': [sclone, '[options]'],
    'sbookmarkimports': [sbookmarkimports, '[options]'],
    'scheckimports': [scheckimports, '[options]'],
    'scloneimports': [scloneimports, '[options]'],
    'sforceimports': [sforceimports, ''],
    'sincoming': [sincoming, ''],
    'soutgoing': [soutgoing, '[options]'],
    'spull': [spull, '[options]'],
    'spush': [spush, '[options]'],
    'stip': [stip, ''],
    'sversions': [sversions, '[options]'],
    'supdate': [supdate, ''],
    'hg': [hg_command, '[options]'],
    'pylint': [pylint, ''],
    'java': [java_command, '[-options] class [args...]'],
    'javap': [javap, '[options] <class name patterns>'],
    'javadoc': [javadoc, '[options]'],
    'junit': [junit, '[options]'],
    'site': [site, '[options]'],
    'netbeansinit': [netbeansinit, ''],
    'suites': [show_suites, ''],
    'envs': [show_envs, '[options]'],
    'version': [show_version, ''],
    'update': [update, ''],
    'projects': [show_projects, ''],
    'sha1': [sha1, ''],
    'test': [test, '[options]'],
    'unittest' : [mx_unittest.unittest, '[unittest options] [--] [VM options] [filters...]', mx_unittest.unittestHelpSuffix],
}
_commandsToSuite = {}

_argParser = ArgParser()

def _mxDirName(name):
    return 'mx.' + name

def _mx_binary_distribution_root(name):
    return name + '-mx'

def _mx_binary_distribution_jar(name):
    '''the (relative) path to the location of the mx binary distribution jar'''
    return join('dists', _mx_binary_distribution_root(name) + '.jar')

def _mx_binary_distribution_version(name):
    '''the (relative) path to the location of the mx binary distribution version file'''
    return join('dists', _mx_binary_distribution_root(name) + '.version')

def _suitename(mxDir):
    base = os.path.basename(mxDir)
    parts = base.split('.')
    if len(parts) == 3:
        assert parts[0] == ''
        assert parts[1] == 'mx'
        return parts[2]
    assert len(parts) == 2, parts
    assert parts[0] == 'mx'
    return parts[1]

def _is_suite_dir(d, mxDirName=None):
    """
    Checks if d contains a suite.
    If mxDirName is None, matches any suite name, otherwise checks for exactly *mxDirName* or '.' + *mxDirName*.
    """
    if os.path.isdir(d):
        for f in [mxDirName, '.' + mxDirName] if mxDirName else [e for e in os.listdir(d) if e.startswith('mx.') or e.startswith('.mx.')]:
            mxDir = join(d, f)
            if exists(mxDir) and isdir(mxDir) and (exists(join(mxDir, 'suite.py'))):
                return mxDir

def _check_primary_suite():
    if _primary_suite is None:
        abort('no primary suite found')
    else:
        return _primary_suite

# vc (suite) commands only perform a partial load of the suite metadata, to avoid
# problems with suite invariant checks aborting the operation
_vc_commands = ['sclone', 'scloneimports', 'scheckimports', 'sbookmarkimports', 'sforceimports', 'spull',
                'sincoming', 'soutgoing', 'spull', 'spush', 'stip', 'sversions', 'supdate']

def _needs_primary_suite(command):
    return not command in _primary_suite_exempt and not command in _suite_context_free

def _needs_primary_suite_check(args):
    if len(args) == 0:
        return False
    for s in args:
        if s in _primary_suite_exempt:
            return False
    return True

def _check_vc_command():
    '''check for a vc command after the initial parse'''
    for command in _argParser.initialCommandAndArgs:
        if command and not command.startswith('-'):
            hits = [c for c in _vc_commands if c.startswith(command)]
            if len(hits) > 0:
                return True
    return False

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
    return None

def _check_dependency_cycles():
    '''
    Checks for cycles in the dependency graph.
    '''
    path = []
    def _visitEdge(src, edgeType, dst):
        if dst in path:
            abort('dependency cycle detected: ' + ' -> '.join([d.name for d in path] + [dst.name]), context=dst)
    def _preVisit(dep, edge):
        path.append(dep)
        return True
    def _visit(dep, edge):
        last = path.pop(-1)
        assert last is dep
    walk_deps(ignoredEdges=[DEP_EXCLUDED], preVisit=_preVisit, visitEdge=_visitEdge, visit=_visit)

def _remove_unsatisfied_deps():
    '''
    Remove projects and libraries that (recursively) depend on an optional library
    whose artifact does not exist or on a JRE library that is not present in the
    JDK for a project. Also remove projects whose Java compliance requirement
    cannot be satisfied by the configured JDKs. Removed projects and libraries are
    also removed from distributions in which they are listed as dependencies.
    Returns a map from the name of a removed dependency to the reason it was removed.
    A reason may be the name of another removed dependency.
    '''
    removedDeps = {}
    def visit(dep, edge):
        if dep.isLibrary():
            if dep.optional:
                try:
                    dep.optional = False
                    path = dep.get_path(resolve=True)
                except SystemExit:
                    path = None
                finally:
                    dep.optional = True
                if not path:
                    reason = 'optional library {} was removed as {} does not exist'.format(dep, dep.path)
                    logv('[' + reason + ']')
                    removedDeps[dep] = reason
        elif dep.isJavaProject():
            # TODO this lookup should be the same as the one used in build
            depJdk = get_jdk(dep.javaCompliance, cancel='some projects will be removed which may result in errors', purpose="building projects with compliance " + str(dep.javaCompliance), tag=DEFAULT_JDK_TAG)
            if depJdk is None:
                reason = 'project {0} was removed as Java compliance {1} cannot be satisfied by configured JDKs'.format(dep, dep.javaCompliance)
                logv('[' + reason + ']')
                removedDeps[dep] = reason
            else:
                for depDep in list(dep.deps):
                    if depDep in removedDeps:
                        logv('[removed {} because {} was removed]'.format(dep, depDep))
                        removedDeps[dep] = depDep.name
                    elif depDep.isJreLibrary() or depDep.isJdkLibrary():
                        lib = depDep
                        if not lib.is_present_in_jdk(depJdk):
                            if lib.optional:
                                reason = 'project {} was removed as dependency {} is missing'.format(dep, lib)
                                logv('[' + reason + ']')
                                removedDeps[dep] = reason
                            else:
                                abort('JRE/JDK library {} required by {} not found'.format(lib, dep), context=dep)
        elif dep.isDistribution():
            dist = dep
            for distDep in list(dist.deps):
                if distDep in removedDeps:
                    logv('[{0} was removed from distribution {1}]'.format(distDep, dist))
                    dist.deps.remove(distDep)

    walk_deps(visit=visit)

    res = {}
    for dep, reason in removedDeps.iteritems():
        res[dep.name] = reason
        dep.getSuiteRegistry().remove(dep)
        dep.getGlobalRegistry().pop(dep.name)
    return res

def _get_command_property(command, propertyName):
    c = _commands.get(command)
    if c and len(c) >= 4:
        props = c[3]
        if props and propertyName in props:
            return props[propertyName]
    return None

def _init_primary_suite(s):
    global _primary_suite
    assert not _primary_suite
    _primary_suite = s
    for deferrable in _primary_suite_deferrables:
        deferrable()

def main():
    global _mx_suite
    _mx_suite = MXSuite()
    os.environ['MX_HOME'] = _mx_home

    _argParser._parse_cmd_line(_opts, firstParse=True)
    vc_command = _check_vc_command()

    global _vc_systems
    _vc_systems = [HgConfig(), GitConfig(), BinaryVC()]
    global _mvn
    _mvn = MavenConfig()

    primarySuiteMxDir = None
    if len(_argParser.initialCommandAndArgs) == 0 or _argParser.initialCommandAndArgs[0] not in _suite_context_free:
        primary_suite_error = 'no primary suite found'
        primarySuiteMxDir = _findPrimarySuiteMxDir()
        if primarySuiteMxDir == _mx_suite.mxDir:
            _init_primary_suite(_mx_suite)
        elif primarySuiteMxDir:
            _src_suitemodel.set_primary_dir(dirname(primarySuiteMxDir))
            # We explicitly load the 'env' file of the primary suite now as it might influence
            # the suite loading logic. It will get loaded again, to ensure it overrides any
            # settings in imported suites
            PrimarySuite.load_env(primarySuiteMxDir)
            global _binary_suites
            bs = os.environ.get('MX_BINARY_SUITES')
            if bs is not None:
                if len(bs) > 0:
                    _binary_suites = bs.split(',')
                else:
                    _binary_suites = []

            # support advanced use where import version ids are ignored (so get head)
            # experimental, not observed in all commands
            global _suites_ignore_versions
            igv = os.environ.get('MX_IGNORE_VERSIONS')
            if igv  is not None:
                if len(igv) > 0:
                    _suites_ignore_versions = igv.split(',')
                else:
                    _suites_ignore_versions = []

            # This will load all explicitly imported suites, unless it's a vc command
            _init_primary_suite(PrimarySuite(primarySuiteMxDir, load=not vc_command))
        else:
            # in general this is an error, except for the _primary_suite_exempt commands,
            # and an extensions command will likely not parse in this case, as any extra arguments
            # will not have been added to _argParser.
            # If the command line does not contain a string matching one of the exemptions, we can safely abort,
            # but not otherwise, as we can't be sure the string isn't in a value for some other option.
            if _needs_primary_suite_check(_argParser.initialCommandAndArgs):
                abort(primary_suite_error)

        commandAndArgs = _argParser._parse_cmd_line(_opts, firstParse=False)

        if primarySuiteMxDir is None:
            if len(commandAndArgs) > 0 and _needs_primary_suite(commandAndArgs[0]):
                abort(primary_suite_error)
            else:
                warn(primary_suite_error)
        else:
            os.environ['MX_PRIMARY_SUITE_PATH'] = dirname(primarySuiteMxDir)
    else:
        commandAndArgs = _argParser._parse_cmd_line(_opts, firstParse=False)

    if _opts.mx_tests:
        MXTestsSuite()

    if primarySuiteMxDir:
        if vc_command:
            _primary_suite.vc_command_init()
        else:
            if primarySuiteMxDir != _mx_suite.mxDir:
                _primary_suite._depth_first_post_init()
            _check_dependency_cycles()

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

    if primarySuiteMxDir and not vc_command:
        if not _get_command_property(command, "keepUnsatisfiedDependencies"):
            global _removedDeps
            _removedDeps = _remove_unsatisfied_deps()

    def term_handler(signum, frame):
        abort(1)
    if not is_jython():
        signal.signal(signal.SIGTERM, term_handler)

    def quit_handler(signum, frame):
        _send_sigquit()
    if not is_jython() and get_os() != 'windows':
        signal.signal(signal.SIGQUIT, quit_handler)

    try:
        if _opts.timeout != 0:
            def alarm_handler(signum, frame):
                abort('Command timed out after ' + str(_opts.timeout) + ' seconds: ' + ' '.join(commandAndArgs))
            signal.signal(signal.SIGALRM, alarm_handler)
            signal.alarm(_opts.timeout)
        retcode = c(command_args)
        if retcode is not None and retcode != 0:
            abort(retcode)
    except KeyboardInterrupt:
        # no need to show the stack trace when the user presses CTRL-C
        abort(1)

version = VersionSpec("5.6.15")

currentUmask = None

if __name__ == '__main__':
    # Capture the current umask since there's no way to query it without mutating it.
    currentUmask = os.umask(0)
    os.umask(currentUmask)

    main()
