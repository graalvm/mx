#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2024, 2024, Oracle and/or its affiliates. All rights reserved.
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

class Dependency(SuiteConstituent):
    """
    A dependency is a library, distribution or project specified in a suite.
    The name must be unique across all Dependency instances.
    """
    def __init__(self, suite, name, theLicense, **kwArgs):
        SuiteConstituent.__init__(self, suite, name)
        if isinstance(theLicense, str):
            theLicense = [theLicense]
        self.theLicense = theLicense
        self.__dict__.update(kwArgs)

    def isBaseLibrary(self):
        return isinstance(self, BaseLibrary)

    def isLibrary(self):
        return isinstance(self, Library)

    def isResourceLibrary(self):
        return isinstance(self, ResourceLibrary)

    def isPackedResourceLibrary(self):
        return isinstance(self, PackedResourceLibrary)

    def isJreLibrary(self):
        return isinstance(self, JreLibrary)

    def isJdkLibrary(self):
        return isinstance(self, JdkLibrary)

    def isProject(self):
        return isinstance(self, Project)

    def isJavaProject(self):
        return isinstance(self, JavaProject)

    def isNativeProject(self):
        return isinstance(self, AbstractNativeProject)

    def isArchivableProject(self):
        return isinstance(self, ArchivableProject)

    def isDistribution(self):
        return isinstance(self, Distribution)

    def isJARDistribution(self):
        return isinstance(self, JARDistribution)

    def isPOMDistribution(self):
        return isinstance(self, POMDistribution)

    def isLayoutJARDistribution(self):
        return isinstance(self, LayoutJARDistribution)

    def isLayoutDirDistribution(self):
        return isinstance(self, LayoutDirDistribution)

    def isClasspathDependency(self):
        return isinstance(self, ClasspathDependency)

    def isTARDistribution(self):
        return isinstance(self, AbstractTARDistribution)

    def isZIPDistribution(self):
        return isinstance(self, AbstractZIPDistribution)

    def isLayoutDistribution(self):
        return isinstance(self, LayoutDistribution)

    def isProjectOrLibrary(self):
        return self.isProject() or self.isLibrary()

    def isPlatformDependent(self):
        return False

    def isJDKDependent(self):
        return None

    def getGlobalRegistry(self):
        if self.isProject():
            return _projects
        if self.isLibrary() or self.isResourceLibrary():
            return _libs
        if self.isDistribution():
            return _dists
        if self.isJreLibrary():
            return _jreLibs
        assert self.isJdkLibrary(), f"'{self}' has unexpected type '{type(self).__name__}'"
        return _jdkLibs

    def getGlobalRemovedRegistry(self):
        if self.isProject():
            return _removed_projects
        if self.isLibrary() or self.isResourceLibrary():
            return _removed_libs
        if self.isDistribution():
            return _removed_dists
        if self.isJreLibrary():
            return _removed_jreLibs
        assert self.isJdkLibrary(), f"'{self}' has unexpected type '{type(self).__name__}'"
        return _removed_jdkLibs

    def getSuiteRegistry(self):
        if self.isProject():
            return self.suite.projects
        if self.isLibrary() or self.isResourceLibrary():
            return self.suite.libs
        if self.isDistribution():
            return self.suite.dists
        if self.isJreLibrary():
            return self.suite.jreLibs
        assert self.isJdkLibrary(), f"'{self}' has unexpected type '{type(self).__name__}'"
        return self.suite.jdkLibs

    def getSuiteRemovedRegistry(self):
        if self.isProject():
            return self.suite.removed_projects
        if self.isLibrary() or self.isResourceLibrary():
            return self.suite.removed_libs
        if self.isDistribution():
            return self.suite.removed_dists
        if self.isJreLibrary():
            return self.suite.removed_jreLibs
        assert self.isJdkLibrary(), f"'{self}' has unexpected type '{type(self).__name__}'"
        return self.suite.removed_jdkLibs

    def get_output_base(self):
        return self.suite.get_output_root(platformDependent=self.isPlatformDependent(), jdkDependent=self.isJDKDependent())

    def getBuildTask(self, args):
        """
        Return a BuildTask that can be used to build this dependency.
        :rtype : BuildTask
        """
        nyi('getBuildTask', self)

    def abort(self, msg):
        """
        Aborts with given message prefixed by the origin of this dependency.
        """
        abort(msg, context=self)

    def warn(self, msg):
        """
        Warns with given message prefixed by the origin of this dependency.
        """
        warn(msg, context=self)

    def qualifiedName(self):
        return f'{self.suite.name}:{self.name}'

    def walk_deps(self, preVisit=None, visit=None, visited=None, ignoredEdges=None, visitEdge=None):
        """
        Walk the dependency graph rooted at this object.
        See documentation for mx.walk_deps for more info.
        """
        if visited is not None:
            if self in visited:
                return
        else:
            visited = set()
        if ignoredEdges is None:
            # Default ignored edges
            ignoredEdges = [DEP_ANNOTATION_PROCESSOR, DEP_EXCLUDED, DEP_BUILD]
        self._walk_deps_helper(visited, None, preVisit, visit, ignoredEdges, visitEdge)

    def _walk_deps_helper(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        _debug_walk_deps_helper(self, edge, ignoredEdges)
        assert self not in visited, self
        if not preVisit or preVisit(self, edge):
            visited.add(self)
            self._walk_deps_visit_edges(visited, edge, preVisit, visit, ignoredEdges, visitEdge)
            if visit:
                visit(self, edge)

    def _walk_deps_visit_edges(self, visited, edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        nyi('_walk_deps_visit_edges', self)

    def _walk_deps_visit_edges_helper(self, deps, visited, in_edge, preVisit=None, visit=None, ignoredEdges=None, visitEdge=None):
        for dep_type, dep_list in deps:
            if not _is_edge_ignored(dep_type, ignoredEdges):
                for dst in dep_list:
                    out_edge = DepEdge(self, dep_type, in_edge)
                    if visitEdge:
                        visitEdge(self, dst, out_edge)
                    if dst not in visited:
                        dst._walk_deps_helper(visited, out_edge, preVisit, visit, ignoredEdges, visitEdge)

    def getArchivableResults(self, use_relpath=True, single=False):
        """
        Generates (file_path, archive_path) tuples for all the build results of this dependency.
        :param use_relpath: When `False` flattens all the results to the root of the archive
        :param single: When `True` expects a single result.
                        Might throw `ValueError` if that does not make sense for this dependency type.
        :rtype: collections.Iterable[(str, str)]
        """
        nyi('getArchivableResults', self)

    def contains_dep(self, dep, includeAnnotationProcessors=False):
        """
        Determines if the dependency graph rooted at this object contains 'dep'.
        Returns the path from this object to 'dep' if so, otherwise returns None.
        """
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

    """Only JavaProjects define Java packages"""
    def defined_java_packages(self):
        return []

    def mismatched_imports(self):
        return {}

    def _extra_artifact_discriminant(self):
        """
        An extra string to help identify the current build configuration. It will be used in the generated path for the
        built artifacts and will avoid unnecessary rebuilds when frequently changing this build configuration.
        :rtype : str
        """
        return ''

    def _resolveDepsHelper(self, deps, fatalIfMissing=True):
        """
        Resolves any string entries in 'deps' to the Dependency objects named
        by the strings. The 'deps' list is updated in place.
        """
        if deps:
            assert all((isinstance(d, (str, Dependency)) for d in deps))
            if isinstance(deps[0], str):
                resolvedDeps = []
                for name in deps:
                    if not isinstance(name, str):
                        assert isinstance(name, Dependency)
                        # already resolved
                        resolvedDeps.append(name)
                        continue
                    s, _ = splitqualname(name)
                    if s and s in _jdkProvidedSuites:
                        logvv(f'[{self}: ignoring dependency {name} as it is provided by the JDK]')
                        continue
                    dep = dependency(name, context=self, fatalIfMissing=fatalIfMissing)
                    if not dep:
                        continue
                    if dep.isProject() and self.suite is not dep.suite:
                        abort('cannot have an inter-suite reference to a project: ' + dep.name, context=self)
                    if s is None and self.suite is not dep.suite:
                        current_suite_dep = self.suite.dependency(dep.name, fatalIfMissing=False)
                        if dep != current_suite_dep:
                            raise abort('inter-suite reference must use qualified form ' + dep.suite.name + ':' + dep.name, context=self)
                        dep = current_suite_dep  # prefer our version
                    if self.suite is not dep.suite and dep.internal:
                        abort('cannot reference internal ' + dep.name + ' from ' + self.suite.name + ' suite', context=self)
                    selfJC = getattr(self, 'javaCompliance', None)
                    depJC = getattr(dep, 'javaCompliance', None)
                    if selfJC and depJC and selfJC.value < depJC.value:
                        if self.suite.getMxCompatibility().checkDependencyJavaCompliance():
                            abort('cannot depend on ' + name + ' as it has a higher Java compliance than ' + str(selfJC), context=self)
                    resolvedDeps.append(dep)
                deps[:] = resolvedDeps
            assert all((isinstance(d, Dependency) for d in deps))

    def get_output_root(self):
        """
        Gets the root of the directory hierarchy under which generated artifacts for this
        dependency such as class files and annotation generated sources should be placed.
        """
        if self.suite._output_root_includes_config():
            return join(self.get_output_base(), self.name)

        # Legacy code
        assert self.isProject(), self
        if not self.subDir:
            return join(self.get_output_base(), self.name)
        names = self.subDir.split(os.sep)
        parents = len([n for n in names if n == os.pardir])
        if parents != 0:
            return os.sep.join([self.get_output_base(), f'{self.suite}-parent-{parents}'] + names[parents:] + [self.name])
        return join(self.get_output_base(), self.subDir, self.name)
