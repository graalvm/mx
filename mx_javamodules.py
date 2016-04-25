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
    :param set moduledeps: list of `JavaModuleDescriptor` objects for the module dependencies of this module
    :param JARDistribution dist: distribution from which this module was derived
    """
    def __init__(self, name, exports, requires, uses, provides, packages=None, concealedRequires=None, jarpath=None, dist=None, moduledeps=None):
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
        self.moduledeps = moduledeps

    def __str__(self):
        return 'module:' + self.name

    def __repr__(self):
        return self.__str__()

    def __cmp__(self, other):
        assert isinstance(other, JavaModuleDescriptor)
        return cmp(self.name, other.name)

    @staticmethod
    def load(path, jdk):
        """
        Unpickles this module descriptor from a file.

        :param str path: where to read the pickled object
        :param JDKConfig jdk: used to resolve pickled references to JDK modules
        """
        with open(path, 'rb') as fp:
            jmd = pickle.load(fp)
        jdkmodules = {m.name : m for m in jdk.get_boot_layer_modules()}
        resolved = []
        for name in jmd.moduledeps:
            if name.startswith('dist:'):
                distName = name[len('dist:'):]
                resolved.append(mx.distribution(distName).as_java_module(jdk))
            else:
                resolved.append(jdkmodules[name])
        jmd.moduledeps = resolved
        jmd.dist = mx.distribution(jmd.dist)
        return jmd

    def save(self, path):
        """
        Pickles this module descriptor to a file.

        :param str path: where to write the pickled object
        """
        moduledeps = self.moduledeps
        dist = self.dist
        self.moduledeps = [m.name if not m.dist else 'dist:' + m.dist.name for m in moduledeps]
        self.dist = dist.name
        try:
            with open(path, 'wb') as fp:
                pickle.dump(self, fp)
        finally:
            self.moduledeps = moduledeps
            self.dist = dist

    def modulepath(self):
        """
        Gets the modules that must be put on the VM and javac ``-modulepath``  option when deploying or
        compiling against this module.

        :return: a list of this module's dependencies whose `jarpath` is not None
        :rtype: list
        """
        mp = [jmd for jmd in self.moduledeps if jmd.jarpath]
        if self.jarpath:
            mp.append(self)
        return mp

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
        if self.moduledeps:
            print >> out, '    // moduledeps: ' + ', '.join([jmd.name for jmd in self.moduledeps])
        modulepath = self.modulepath()
        if modulepath:
            print >> out, '    // modulepath: ' + os.pathsep.join([m.jarpath for m in modulepath])
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

def get_java_module_info(dist):
    modulesDir = mx.ensure_dir_exists(join(dist.suite.get_output_root(), 'modules'))
    moduleName = dist.name.replace('_', '.').lower()
    moduleDir = mx.ensure_dir_exists(join(modulesDir, moduleName))
    moduleJar = join(modulesDir, moduleName + '.jar')
    return moduleName, moduleDir, moduleJar

def make_java_module(dist, jdk, services, javaprojects):
    """
    Creates a Java module from a distribution.

    :param JARDistribution dist: the distribution from which to create a module
    :param JDKConfig jdk: a JDK with a version >= 9 that can be used to compile the module-info class
    :param dict services: dict from a service name to the set of providers of the service defined by the module
    :param list projects: the `JavaProject`s in the dist/module
    """
    moduleName, moduleDir, moduleJar = get_java_module_info(dist)

    modulepath = jdk.get_boot_layer_modules()
    moduledeps = set()
    exports = {}
    requires = {}
    concealedRequires = {}
    addExports = set()
    uses = set()

    for dep in javaprojects:
        uses.update(getattr(dep, 'uses', []))

    def _visitDep(dep, edges):
        if dep is not dist and dep.isJARDistribution():
            jmd = dep.as_java_module(jdk)
            modulepath.append(jmd)
            moduledeps.add(jmd)
    dist.walk_deps(visit=_visitDep)

    for dep in javaprojects:
        for pkg in itertools.chain(dep.imported_java_packages(projectDepsOnly=False), getattr(dep, 'imports', [])):
            depModule, visibility = lookup_package(modulepath, pkg, moduleName)
            if depModule:
                if visibility == 'exported':
                    # A distribution based module re-exports all its imported packages
                    requires.setdefault(depModule.name, set()).add('public')
                    moduledeps.add(depModule)
                else:
                    assert visibility == 'concealed'
                    concealedRequires.setdefault(depModule.name, set()).add(pkg)
                    moduledeps.add(depModule)
                    addExports.add('-XaddExports:' + depModule.name + '/' + pkg + '=' + moduleName)

        for pkg in dep.defined_java_packages():
            # A distribution based module exports all its packages to the world
            exports.setdefault(pkg, [])

    with zipfile.ZipFile(dist.path, 'r') as zf:
        zf.extractall(path=moduleDir)
        names = frozenset(zf.namelist())
        for service in services:
            serviceClass = service.replace('.', '/') + '.class'
            if serviceClass in names:
                uses.add(service)

    jmd = JavaModuleDescriptor(moduleName, exports, requires, uses, services, concealedRequires=concealedRequires,
                               jarpath=moduleJar, dist=dist, moduledeps=moduledeps)

    # Compile module-info.class
    moduleInfo = join(moduleDir, 'module-info.java')
    with open(moduleInfo, 'w') as fp:
        print >> fp, jmd.as_module_info()
    modulepath = [m for m in jmd.modulepath() if m != jmd]
    mp = ['-mp', os.pathsep.join([m.jarpath for m in modulepath])] if modulepath else []
    mx.run([jdk.javac, '-d', moduleDir] + mp + list(addExports) + [moduleInfo])

    # Create the module jar
    shutil.make_archive(moduleJar, 'zip', moduleDir)
    os.rename(moduleJar + '.zip', moduleJar)

    return jmd

def get_empty_module():
    """
    Gets an empty module represented by an empty module jar.
    """
    modulesDir = mx.ensure_dir_exists(join(mx._mx_suite.get_output_root(), 'modules'))
    moduleName = 'empty.app'
    moduleJar = join(modulesDir, moduleName + '.jar')
    if not exists(moduleJar):
        with zipfile.ZipFile(moduleJar, 'w'):
            pass
    return moduleName, moduleJar
