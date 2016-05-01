#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2016, Oracle and/or its affiliates. All rights reserved.
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

import os
import zipfile
import pickle
import StringIO
import shutil
import itertools
from os.path import join, exists

import mx

class JavaModuleDescriptor(object):
    """
    Describes a Java module. This class closely mirrors ``java.lang.module.ModuleDescriptor``.

    :param str name: the name of the module
    :param dict exports: dict from a package defined by this module to the modules it's exported to. An
             empty list denotes an unqualified export.
    :param dict requires: dict from a module dependency to the modifiers of the dependency
    :param dict concealedRequires: dict from a module dependency to its concealed packages required by this module
    :param set uses: the list of service types used by this module
    :param dict provides: dict from a service name to the set of providers of the service defined by this module
    :param set packages: the list of packages defined by this module
    :param set conceals: the list of packages defined but not exported by this module
    :param str jarpath: path to module jar file
    :param set modulepath: list of `JavaModuleDescriptor` objects for the module dependencies of this module
    :param JARDistribution dist: distribution from which this module was derived
    """
    def __init__(self, name, exports, requires, uses, provides, packages=None, concealedRequires=None, jarpath=None, dist=None, modulepath=None):
        self.name = name
        self.exports = exports
        self.requires = requires
        self.concealedRequires = concealedRequires if concealedRequires else {}
        self.uses = frozenset(uses)
        self.provides = provides
        exportedPackages = frozenset(exports.viewkeys())
        self.packages = exportedPackages if packages is None else frozenset(packages)
        assert len(exports) == 0 or exportedPackages.issubset(self.packages)
        self.conceals = self.packages - exportedPackages
        self.jarpath = jarpath
        self.dist = dist
        self.modulepath = modulepath

    def __str__(self):
        return 'module:' + self.name

    def __repr__(self):
        return self.__str__()

    def __cmp__(self, other):
        assert isinstance(other, JavaModuleDescriptor)
        return cmp(self.name, other.name)

    @staticmethod
    def load(dist, jdk):
        """
        Unpickles the module descriptor corresponding to a given distribution.

        :param str dist: the distribution for which to read the pickled object
        :param JDKConfig jdk: used to resolve pickled references to JDK modules
        """
        _, moduleDir, _ = _get_java_module_info(dist)
        path = moduleDir + '.pickled'
        if not exists(path):
            mx.abort(path + ' does not exist')
        with open(path, 'rb') as fp:
            jmd = pickle.load(fp)
        jdkmodules = {m.name : m for m in jdk.get_boot_layer_modules()}
        resolved = []
        for name in jmd.modulepath:
            if name.startswith('dist:'):
                distName = name[len('dist:'):]
                resolved.append(mx.distribution(distName).as_java_module(jdk))
            else:
                resolved.append(jdkmodules[name])
        jmd.modulepath = resolved
        jmd.dist = mx.distribution(jmd.dist)
        return jmd

    def save(self):
        """
        Pickles this module descriptor to a file if it corresponds to a distribution.
        Otherwise, does nothing.

        :return: the path to which this module descriptor was pickled or None
        """
        dist = self.dist
        if not dist:
            # Don't pickle a JDK module
            return None
        _, moduleDir, _ = _get_java_module_info(dist)
        path = moduleDir + '.pickled'
        modulepath = self.modulepath
        self.modulepath = [m.name if not m.dist else 'dist:' + m.dist.name for m in modulepath]
        self.dist = dist.name
        try:
            with open(path, 'wb') as fp:
                pickle.dump(self, fp)
        finally:
            self.modulepath = modulepath
            self.dist = dist

    def as_module_info(self):
        """
        Gets this module descriptor expressed as the contents of a ``module-info.java`` file.
        """
        out = StringIO.StringIO()
        print >> out, 'module ' + self.name + ' {'
        for dependency, modifiers in sorted(self.requires.iteritems()):
            modifiers_string = (' '.join(sorted(modifiers)) + ' ') if len(modifiers) != 0 else ''
            print >> out, '    requires ' +  modifiers_string + dependency + ';'
        for source, targets in sorted(self.exports.iteritems()):
            targets_string = (' to ' + ', '.join(sorted(targets))) if len(targets) != 0 else ''
            print >> out, '    exports ' + source + targets_string + ';'
        for use in sorted(self.uses):
            print >> out, '    uses ' + use + ';'
        for service, providers in sorted(self.provides.iteritems()):
            for provider in providers:
                print >> out, '    provides ' + service + ' with ' + provider + ';'
        for pkg in sorted(self.conceals):
            print >> out, '    // conceals: ' + pkg
        if self.jarpath:
            print >> out, '    // jarpath: ' + self.jarpath
        if self.dist:
            print >> out, '    // dist: ' + self.dist.name
        if self.modulepath:
            print >> out, '    // modulepath: ' + ', '.join([jmd.name for jmd in self.modulepath])
        if self.concealedRequires:
            for dependency, packages in sorted(self.concealedRequires.iteritems()):
                for package in sorted(packages):
                    print >> out, '    // concealed-requires: ' + dependency + '/' + package
        print >> out, '}'
        return out.getvalue()

def lookup_package(modulepath, package, importer):
    """
    Searches a given module path for the module defining a given package.

    :param list modulepath: a list of `JavaModuleDescriptors`
    :param str package: the name of the package to lookup
    :param str importer: the name of the module importing the package (use "<unnamed>" for the unnamed module)
    :return: if the package is found, then a tuple containing the defining module
             and a value of 'concealed' or 'exported' denoting the visibility of the package.
             Otherwise (None, None) is returned.
    """
    for jmd in modulepath:
        targets = jmd.exports.get(package, None)
        if targets is not None:
            if len(targets) == 0 or importer in targets:
                return jmd, 'exported'
            return jmd, 'concealed'
        elif package in jmd.conceals:
            return jmd, 'concealed'
    return (None, None)

def get_module_deps(dist):
    """
    Gets the JAR distributions and their constituent Java projects whose artifacts (i.e., class files and
    resources) are the input to the Java module jar created by `make_java_module` for a given distribution.

    :return: the set of `JARDistribution` objects and their constituent `JavaProject` transitive
             dependencies denoted by the ``moduledeps`` attribute
    """
    if not hasattr(dist, '.module_deps'):
        roots = getattr(dist, 'moduledeps', [])
        if not roots:
            return roots
        for root in roots:
            if not root.isJARDistribution():
                mx.abort('moduledeps can (currently) only include JAR distributions: ' + str(root), context=dist)

        moduledeps = []
        def _visit(dep, edges):
            if dep is not dist:
                if dep.isJavaProject() or dep.isJARDistribution():
                    moduledeps.append(dep)
                else:
                    mx.abort('modules can (currently) only include JAR distributions and Java projects: ' + str(dep), context=dist)
        def _preVisit(dst, edge):
            return not dst.isJreLibrary()
        mx.walk_deps(roots, preVisit=_preVisit, visit=_visit)
        dist.walk_deps(visit=_visit, preVisit=_preVisit)
        result = moduledeps
        setattr(dist, '.module_deps', result)
    return getattr(dist, '.module_deps')

def as_java_module(dist, jdk):
    """
    Gets the Java module created from a given distribution.

    :param JARDistribution dist: a distribution that defines a Java module
    :param JDKConfig jdk: a JDK with a version >= 9 that can be used to resolve references to JDK modules
    :return: the descriptor for the module
    :rtype: `JavaModuleDescriptor`
    """
    if not hasattr(dist, '.javaModule'):
        jmd = JavaModuleDescriptor.load(dist, jdk)
        setattr(dist, '.javaModule', jmd)
    return getattr(dist, '.javaModule')

def _get_java_module_info(dist):
    assert len(get_module_deps(dist)) != 0
    modulesDir = mx.ensure_dir_exists(join(dist.suite.get_output_root(), 'modules'))
    moduleName = dist.name.replace('_', '.').lower()
    moduleDir = mx.ensure_dir_exists(join(modulesDir, moduleName))
    moduleJar = join(modulesDir, moduleName + '.jar')
    return moduleName, moduleDir, moduleJar

def make_java_module(dist, jdk):
    """
    Creates a Java module from a distribution.

    :param JARDistribution dist: the distribution from which to create a module
    :param JDKConfig jdk: a JDK with a version >= 9 that can be used to compile the module-info class
    :param list projects: the `JavaProject`s in the dist/module
    :return: the `JavaModuleDescriptor` for the created Java module
    """
    moduledeps = get_module_deps(dist)
    if not moduledeps:
        return None

    moduleName, moduleDir, moduleJar = _get_java_module_info(dist)
    exports = {}
    requires = {}
    concealedRequires = {}
    addExports = set()
    uses = set()


    # Prepend JDK modules to module path
    modulepath = list(jdk.get_boot_layer_modules())
    usedModules = set()

    javaprojects = [d for d in moduledeps if d.isJavaProject()]

    for dep in javaprojects:
        uses.update(getattr(dep, 'uses', []))
        for pkg in itertools.chain(dep.imported_java_packages(projectDepsOnly=False), getattr(dep, 'imports', [])):
            depModule, visibility = lookup_package(modulepath, pkg, moduleName)
            if depModule:
                if visibility == 'exported':
                    # A distribution based module re-exports all its imported packages
                    requires.setdefault(depModule.name, set())
                    usedModules.add(depModule)
                else:
                    assert visibility == 'concealed'
                    concealedRequires.setdefault(depModule.name, set()).add(pkg)
                    usedModules.add(depModule)
                    addExports.add('-XaddExports:' + depModule.name + '/' + pkg + '=' + moduleName)

        for pkg in getattr(dep, 'exports', []):
            exports.setdefault(pkg, [])

    provides = {}
    for d in [dist] + [md for md in moduledeps if md.isJARDistribution()]:
        if d.isJARDistribution():
            with zipfile.ZipFile(d.path, 'r') as zf:
                # To compile module-info.java, all classes it references must either be given
                # as Java source files or already exist as class files in the output directory.
                # As such, the jar file for each constituent distribution must be unpacked
                # in the output directory.
                zf.extractall(path=moduleDir)
                names = frozenset(zf.namelist())
                for arcname in names:
                    if arcname.startswith('META-INF/services/') and not arcname == 'META-INF/services/':
                        service = arcname[len('META-INF/services/'):]
                        assert '/' not in service
                        provides.setdefault(service, set()).update(zf.read(arcname).splitlines())
                        # Service types defined in the module are assumed to be used by the module
                        serviceClass = service.replace('.', '/') + '.class'
                        if serviceClass in names:
                            uses.add(service)

    jmd = JavaModuleDescriptor(moduleName, exports, requires, uses, provides, concealedRequires=concealedRequires,
                               jarpath=moduleJar, dist=dist, modulepath=modulepath)

    # Compile module-info.class
    moduleInfo = join(moduleDir, 'module-info.java')
    with open(moduleInfo, 'w') as fp:
        print >> fp, jmd.as_module_info()
    javacCmd = [jdk.javac, '-d', moduleDir]
    modulepathJars = [m.jarpath for m in jmd.modulepath if m.jarpath]
    if modulepathJars:
        javacCmd.append('-mp')
        javacCmd.append(os.pathsep.join(modulepathJars))
    javacCmd.extend(addExports)
    javacCmd.append(moduleInfo)
    mx.run(javacCmd)

    # Create the module jar
    shutil.make_archive(moduleJar, 'zip', moduleDir)
    os.rename(moduleJar + '.zip', moduleJar)
    jmd.save()
    return jmd
