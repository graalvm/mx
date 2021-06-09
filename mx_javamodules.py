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

from __future__ import print_function

import os
import re
import zipfile
import pickle
import shutil
import mx_javacompliance
from os.path import join, exists, dirname, basename
from collections import defaultdict

from zipfile import ZipFile

import mx

# Temporary imports and (re)definitions while porting mx from Python 2 to Python 3
import sys
import itertools
if sys.version_info[0] < 3:
    from StringIO import StringIO
else:
    from io import StringIO

class JavaModuleDescriptor(mx.Comparable):
    """
    Describes a Java module. This class closely mirrors ``java.lang.module.ModuleDescriptor``.

    :param str name: the name of the module
    :param dict exports: dict from a package defined by this module to the modules it's exported to. An
             empty list denotes an unqualified export.
    :param dict requires: dict from a module dependency to the modifiers of the dependency
    :param dict concealedRequires: dict from a module dependency to its concealed packages required by this module
    :param set uses: the service types used by this module
    :param dict provides: dict from a service name to the set of providers of the service defined by this module
    :param iterable packages: the packages defined by this module
    :param set conceals: the packages defined but not exported to anyone by this module
    :param str jarpath: path to module jar file
    :param JARDistribution dist: distribution from which this module was derived
    :param Library lib: library from which this module was derived
    :param list modulepath: list of `JavaModuleDescriptor` objects for the module dependencies of this module
    :param dict alternatives: name to JavaModuleDescriptor for alternative definitions of the module. If this
                    is an alternative itself, then the dict has a single entry mapping its alternative name to None.
    :param bool boot: specifies if this module is in the boot layer
    :param JDKConfig jdk: the JDK containing this module
    """
    def __init__(self, name, exports, requires, uses, provides, packages=None, concealedRequires=None,
                 jarpath=None, dist=None, lib=None, modulepath=None, alternatives=None, boot=False, jdk=None, opens=None):
        self.name = name
        self.exports = exports
        self.requires = requires
        self.concealedRequires = concealedRequires if concealedRequires else {}
        self.uses = frozenset(uses)
        self.opens = opens if opens else {}
        self.provides = provides
        exportedPackages = frozenset(exports.keys())
        self.packages = exportedPackages if packages is None else frozenset(packages)
        assert len(exports) == 0 or exportedPackages.issubset(self.packages), exportedPackages - self.packages
        self.conceals = self.packages - exportedPackages
        self.jarpath = jarpath
        self.dist = dist
        self.lib = lib
        self.modulepath = modulepath
        self.alternatives = alternatives
        self.boot = boot
        self.jdk = jdk
        if not self.dist and not self.jarpath and not self.jdk:
            mx.abort('JavaModuleDescriptor requires at least one of the "dist", "jarpath" or "jdk" attributes: ' + self.name)

    def __str__(self):
        return 'module:' + self.name

    def __repr__(self):
        return self.__str__()

    def __cmp__(self, other):
        assert isinstance(other, JavaModuleDescriptor)
        return (self.name > other.name) - (self.name < other.name)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, JavaModuleDescriptor) and self.name == other.name

    def get_jmod_path(self, respect_stripping=True, alt_module_info_name=None):
        """
        Gets the path to the .jmod file corresponding to this module descriptor.

        :param bool respect_stripping: Specifies whether or not to return a path
               to a stripped .jmod file if this module is based on a dist
        """
        if respect_stripping and self.dist is not None:
            assert alt_module_info_name is None, 'alternate modules not supported for stripped dist ' + self.dist.name
            return join(dirname(self.dist.path), self.name + '.jmod')
        if self.dist is not None:
            qualifier = '_' + alt_module_info_name if alt_module_info_name else ''
            return join(dirname(self.dist.original_path()), self.name + qualifier + '.jmod')
        if self.jarpath:
            return join(dirname(self.jarpath), self.name + '.jmod')
        assert self.jdk, self.name
        p = join(self.jdk.home, 'jmods', self.name + '.jmod')
        assert exists(p), p
        return p

    @staticmethod
    def load(dist, jdk, fatalIfNotCreated=True, pickled_path=None):
        """
        Unpickles the module descriptor corresponding to a given distribution.

        :param str dist: the distribution for which to read the pickled object
        :param JDKConfig jdk: used to resolve pickled references to JDK modules
        :param bool fatalIfNotCreated: specifies whether to abort if a descriptor has not been created yet
        """
        if not pickled_path:
            _, pickled_path, _ = get_java_module_info(dist, fatalIfNotModule=True)  # pylint: disable=unpacking-non-sequence
        if not exists(pickled_path):
            if fatalIfNotCreated:
                mx.abort(pickled_path + ' does not exist')
            else:
                return None
        with open(pickled_path, 'rb') as fp:
            jmd = pickle.load(fp)
        jdkmodules = {m.name: m for m in jdk.get_modules()}
        resolved = []
        for name in jmd.modulepath:
            if name.startswith('dist:'):
                distName = name[len('dist:'):]
                resolved.append(as_java_module(mx.distribution(distName), jdk))
            elif name.startswith('lib:'):
                libName = name[len('lib:'):]
                resolved.append(get_library_as_module(mx.dependency(libName), jdk))
            else:
                resolved.append(jdkmodules[name])
        jmd.modulepath = resolved
        jmd.dist = mx.distribution(jmd.dist)
        if jmd.alternatives:
            alternatives = {}
            for alt_name, value in jmd.alternatives.items():
                if value is not None:
                    alt_pickled_path = JavaModuleDescriptor._get_alt_pickled_path(pickled_path, alt_name)
                    value = JavaModuleDescriptor.load(dist, jdk, fatalIfNotCreated=fatalIfNotCreated, pickled_path=alt_pickled_path)
                alternatives[alt_name] = value
            jmd.alternatives = alternatives

        if not os.path.isabs(jmd.jarpath):
            jmd.jarpath = join(dirname(pickled_path), jmd.jarpath)
        return jmd

    def _get_alternative_name(self):
        if self.alternatives and len(self.alternatives) == 1:
            alt_name, jmd = next(iter(self.alternatives.items()))
            if jmd is None:
                return alt_name
        return None

    @staticmethod
    def _get_alt_pickled_path(pickled_path, alt_name):
        assert pickled_path.endswith('.jar.pickled')
        return pickled_path[:-len('.jar.pickled')] + '-' + alt_name + '.jar.pickled'

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
        _, pickled_path, _ = get_java_module_info(dist, fatalIfNotModule=True)  # pylint: disable=unpacking-non-sequence
        assert pickled_path.endswith('.pickled')
        alt_name = self._get_alternative_name()
        if alt_name:
            pickled_path = JavaModuleDescriptor._get_alt_pickled_path(pickled_path, alt_name)
        modulepath = self.modulepath
        jarpath = self.jarpath
        alternatives = self.alternatives
        self.modulepath = []
        for m in modulepath:
            if m.dist:
                pickled_name = 'dist:' + m.dist.name
            elif m.lib:
                pickled_name = 'lib:' + m.lib.suite.name + ':' + m.lib.name
            else:
                pickled_name = m.name
            self.modulepath.append(pickled_name)
        self.dist = dist.name
        self.jarpath = os.path.relpath(jarpath, dirname(pickled_path))
        if self.alternatives:
            self.alternatives = {alt_name : None if v is None else alt_name for alt_name, v in self.alternatives.items()}
        try:
            with mx.SafeFileCreation(pickled_path) as sfc, open(sfc.tmpPath, 'wb') as f:
                pickle.dump(self, f)
        finally:
            # Restore fields that were modified for pickling
            self.modulepath = modulepath
            self.dist = dist
            self.jarpath = jarpath
            self.alternatives = alternatives

    def as_module_info(self, extras_as_comments=True):
        """
        Gets this module descriptor expressed as the contents of a ``module-info.java`` file.

        :param bool extras_as_comments: whether to emit comments documenting attributes not supported
                    by the module-info.java format
        """
        out = StringIO()
        print('module ' + self.name + ' {', file=out)
        for dependency, modifiers in sorted(self.requires.items()):
            modifiers_string = (' '.join(sorted(modifiers)) + ' ') if len(modifiers) != 0 else ''
            print('    requires ' + modifiers_string + dependency + ';', file=out)
        for source, targets in sorted(self.exports.items()):
            targets_string = (' to ' + ', '.join(sorted(targets))) if len(targets) != 0 else ''
            print('    exports ' + source + targets_string + ';', file=out)
        for use in sorted(self.uses):
            print('    uses ' + use + ';', file=out)
        for opens in sorted(self.opens):
            print('    opens ' + opens + ';', file=out)
        for service, providers in sorted(self.provides.items()):
            print('    provides ' + service + ' with ' + ', '.join((p for p in providers)) + ';', file=out)
        if extras_as_comments:
            for pkg in sorted(self.conceals):
                print('    // conceals: ' + pkg, file=out)
            if self.jarpath:
                print('    // jarpath: ' + self.jarpath.replace('\\', '\\\\'), file=out)
            if self.dist:
                print('    // dist: ' + self.dist.name, file=out)
            if self.modulepath:
                print('    // modulepath: ' + ', '.join([jmd.name for jmd in self.modulepath]), file=out)
            if self.concealedRequires:
                for dependency, packages in sorted(self.concealedRequires.items()):
                    for package in sorted(packages):
                        print('    // concealed-requires: ' + dependency + '/' + package, file=out)
        print('}', file=out)
        return out.getvalue()

    def get_package_visibility(self, package, importer):
        """
        Gets the visibility of `package` in this module.

        :param str package: a package name
        :param str importer: the name of the module importing the package (use "<unnamed>" or None for the unnamed module)
        :return: if `package` is in this module, then return 'concealed' or 'exported' depending on the
                 visibility of the package with respect to `importer` otherwise return None
        """
        targets = self.exports.get(package, None)
        if targets is not None:
            if len(targets) == 0 or importer in targets:
                return 'exported'
            return 'concealed'
        elif package in self.conceals:
            return 'concealed'

    def collect_required_exports(self, required_exports):
        """
        Adds required exports information that is needed to use this module to `required_exports`.

        :param defaultdict(set) required_exports: dict where required exports information of this module should be added
        """
        concealedRequires = self.concealedRequires
        for module_name, packages in concealedRequires.items():
            for package_name in packages:
                required_exports[(module_name, package_name)].add(self)

def lookup_package(modulepath, package, importer):
    """
    Searches `modulepath` for the module defining `package`.

    :param list modulepath: an iterable of `JavaModuleDescriptors`
    :param str package: a package name
    :param str importer: the name of the module importing the package (use "<unnamed>" or None for the unnamed module)
    :return: if the package is found, then a tuple containing the defining module
             and a value of 'concealed' or 'exported' denoting the visibility of the package.
             Otherwise (None, None) is returned.
    """
    for jmd in modulepath:
        visibility = jmd.get_package_visibility(package, importer)
        if visibility is not None:
            return jmd, visibility
    return (None, None)

def get_module_deps(dist):
    """
    Gets the JAR distributions and their constituent Java projects whose artifacts (i.e., class files and
    resources) are the input to the Java module jar created by `make_java_module` for a given distribution.

    :return: the set of `JARDistribution` objects and their constituent `JavaProject` transitive
             dependencies denoted by the ``moduledeps`` attribute
    """
    if dist.suite.getMxCompatibility().moduleDepsEqualDistDeps():
        return dist.archived_deps()

    if not hasattr(dist, '.module_deps'):
        roots = getattr(dist, 'moduledeps', [])
        if not roots:
            return roots
        for root in roots:
            if not root.isJARDistribution():
                mx.abort('moduledeps can only include JAR distributions: {}\n'
                         'Try updating to mxversion >= 5.34.4 where `moduledeps` is not needed.'.format(root), context=dist)

        moduledeps = []
        def _visit(dep, edges):
            if dep is not dist:
                if dep.isJavaProject() or dep.isJARDistribution():
                    if dep not in moduledeps:
                        moduledeps.append(dep)
                else:
                    mx.abort('modules can only include JAR distributions and Java projects: {}\n'
                             'Try updating to mxversion >= 5.34.4 where `moduledeps` is not needed.'.format(dep), context=dist)
        def _preVisit(dst, edge):
            return not dst.isJreLibrary() and not dst.isJdkLibrary()
        mx.walk_deps(roots, preVisit=_preVisit, visit=_visit)
        setattr(dist, '.module_deps', moduledeps)
    return getattr(dist, '.module_deps')


def as_java_module(dist, jdk, fatalIfNotCreated=True):
    """
    Gets the Java module created from a given distribution.

    :param JARDistribution dist: a distribution that defines a Java module
    :param JDKConfig jdk: a JDK with a version >= 9 that can be used to resolve references to JDK modules
    :param bool fatalIfNotCreated: specifies whether to abort if a descriptor has not been created yet
    :return: the descriptor for the module
    :rtype: `JavaModuleDescriptor`
    """
    if not hasattr(dist, '.javaModule'):
        jmd = JavaModuleDescriptor.load(dist, jdk, fatalIfNotCreated)
        if jmd:
            setattr(dist, '.javaModule', jmd)
        return jmd
    return getattr(dist, '.javaModule')

def get_module_name(dist):
    """
    Gets the name of the module defined by `dist`.
    """
    if dist.suite.getMxCompatibility().moduleDepsEqualDistDeps():
        module_name = getattr(dist, 'moduleName', None)
        mi = getattr(dist, 'moduleInfo', None)
        if mi is not None:
            if module_name:
                mx.abort('The "moduleName" and "moduleInfo" attributes are mutually exclusive', context=dist)
            module_name = mi.get('name', None)
            if module_name is None:
                mx.abort('The "moduleInfo" attribute requires either a "name" sub-attribute', context=dist)
        elif module_name is not None and len(module_name) == 0:
            mx.abort('"moduleName" attribute cannot be empty', context=dist)
    else:
        if not get_module_deps(dist):
            return None
        module_name = dist.name.replace('_', '.').lower()
    return module_name


def get_java_module_info(dist, fatalIfNotModule=False):
    """
    Gets the metadata for the module derived from `dist`.

    :param JARDistribution dist: a distribution possibly defining a module
    :param bool fatalIfNotModule: specifies whether to abort if `dist` does not define a module
    :return: None if `dist` does not define a module otherwise a tuple containing
             the name of the module, the descriptor pickle path, and finally the path to the
             (unstripped) modular jar file
    """
    if not dist.isJARDistribution():
        if fatalIfNotModule:
            mx.abort('Distribution ' + dist.name + ' is not a JARDistribution')
        return None
    module_name = get_module_name(dist)
    if not module_name:
        if fatalIfNotModule:
            mx.abort('Distribution ' + dist.name + ' does not define a module')
        return None
    return module_name, dist.original_path() + '.pickled', dist.original_path()

def get_library_as_module(dep, jdk):
    """
    Converts a (modular or non-modular) jar library to a module descriptor.

    :param Library dep: a library dependency
    :param JDKConfig jdk: a JDK with a version >= 9 that can be used to describe the module
    :return: a module descriptor
    """
    assert dep.isLibrary()

    def is_valid_module_name(name):
        identRE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
        return all(identRE.match(ident) for ident in name.split('.'))

    if hasattr(dep, 'moduleName'):
        moduleName = dep.moduleName
    else:
        moduleName = jdk.get_automatic_module_name(dep.path)
        if not is_valid_module_name(moduleName):
            mx.abort("Invalid identifier in automatic module name derived for library {}: {} (path: {})".format(dep.name, moduleName, dep.path))
        dep.moduleName = moduleName

    modulesDir = mx.ensure_dir_exists(join(mx.primary_suite().get_output_root(), 'modules'))
    cache = join(modulesDir, moduleName + '.desc')
    fullpath = dep.get_path(resolve=True)
    save = False
    if not exists(cache) or mx.TimeStampFile(fullpath).isNewerThan(cache) or mx.TimeStampFile(__file__).isNewerThan(cache):
        out = mx.LinesOutputCapture()
        err = mx.LinesOutputCapture()
        rc = mx.run([jdk.java, '--module-path', fullpath, '--describe-module', moduleName], out=out, err=err, nonZeroIsFatal=False)
        lines = out.lines
        if rc != 0:
            mx.abort("java --describe-module {} failed. Please verify the moduleName attribute of {}.\nstdout:\n{}\nstderr:\n{}".format(moduleName, dep.name, "\n".join(lines), "\n".join(err.lines)))
        save = True
    else:
        with open(cache) as fp:
            lines = fp.read().splitlines()

    assert lines and lines[0].startswith(moduleName), (dep.name, moduleName, lines)

    accepted_modifiers = set(['transitive'])
    requires = {}
    exports = {}
    provides = {}
    opens = {}
    uses = set()
    packages = set()

    for line in lines[1:]:
        parts = line.strip().split()
        assert len(parts) >= 2, '>>>'+line+'<<<'
        if parts[0:2] == ['qualified', 'exports']:
            parts = parts[1:]
        a = parts[0]
        if a == 'requires':
            module = parts[1]
            modifiers = parts[2:]
            requires[module] = set(m for m in modifiers if m in accepted_modifiers)
        elif a == 'exports':
            source = parts[1]
            if len(parts) > 2:
                assert parts[2] == 'to'
                targets = parts[3:]
            else:
                targets = []
            exports[source] = targets
        elif a == 'uses':
            uses.update(parts[1:])
        elif a == 'opens':
            opens.update(parts[1:])
        elif a == 'contains':
            packages.update(parts[1:])
        elif a == 'provides':
            assert len(parts) >= 4 and parts[2] == 'with'
            service = parts[1]
            providers = parts[3:]
            provides.setdefault(service, []).extend(providers)
        else:
            mx.abort('Cannot parse module descriptor line: ' + str(parts))
    packages.update(exports.keys())

    if save:
        try:
            with open(cache, 'w') as fp:
                fp.write('\n'.join(lines) + '\n')
        except IOError as e:
            mx.warn('Error writing to ' + cache + ': ' + str(e))
            os.remove(cache)

    return JavaModuleDescriptor(moduleName, exports, requires, uses, provides, packages, jarpath=fullpath, opens=opens, lib=dep)


_versioned_prefix = 'META-INF/versions/'
_special_versioned_prefix = 'META-INF/_versions/'  # used for versioned services
_versioned_re = re.compile(r'META-INF/_?versions/([1-9][0-9]*)/(.+)')


def make_java_module(dist, jdk, javac_daemon=None, alt_module_info_name=None):
    """
    Creates a Java module from a distribution.
    This updates the JAR by adding `module-info` classes.

    The `META-INF` directory can not be versioned. However, we make an exception here for `META-INF/services`:
    if different versions should have different service providers, a `META-INF/_versions/<version>/META-INF/services`
    directory can be used (note the `_` before `versions`).
    These service provider declarations will be used to build the versioned module-info files and the
    `META-INF/_versions/<version>` directories will be removed from the archive.
    This is done using a separate versioning directory so that the JAR can be a valid multi-release JAR before this
    transformation.

    input:
        com/foo/MyProvider.class                                    # JDK 8 or earlier specific provider
        META-INF/services/com.foo.MyService                         # Contains: com.foo.MyProvider
        META-INF/_versions/9/META-INF/services/com.foo.MyService    # Contains: com.foo.MyProvider
        META-INF/versions/9/com/foo/MyProvider.class                # JDK 9 and 10 specific provider
        META-INF/_versions/11/META-INF/services/com.foo.MyService   # Contains: provides com.foo.MyService with com.foo.MyProvider
        META-INF/versions/11/com/foo/MyProvider.class               # JDK 11 and later specific provider

    output:
        com/foo/MyProvider.class                        # JDK 8 or earlier specific provider
        META-INF/services/com.foo.MyService             # Contains: com.foo.MyProvider
        META-INF/versions/9/module-info.class           # Contains: provides com.foo.MyService with com.foo.MyProvider
        META-INF/versions/9/com/foo/MyProvider.class    # JDK 9 and 10 specific provider
        META-INF/versions/11/module-info.class          # Contains: provides com.foo.MyService with com.foo.MyProvider
        META-INF/versions/11/com/foo/MyProvider.class   # JDK 11 and later specific provider

    :param JARDistribution dist: the distribution from which to create a module
    :param JDKConfig jdk: a JDK with a version >= 9 that can be used to compile the module-info class
    :return: the `JavaModuleDescriptor` for the created Java module
    """
    info = get_java_module_info(dist)
    if info is None:
        return None

    times = []
    with mx.Timer('total', times):
        moduleName, _, moduleJar = info  # pylint: disable=unpacking-non-sequence
        exports = {}
        requires = {}
        opens = {}
        concealedRequires = {}
        base_uses = set()

        modulepath = list()
        with mx.Timer('requires', times):
            if dist.suite.getMxCompatibility().moduleDepsEqualDistDeps():
                module_deps = dist.archived_deps()
                for dep in mx.classpath_entries(dist, includeSelf=False):
                    if dep.isJARDistribution():
                        jmd = as_java_module(dep, jdk)
                        modulepath.append(jmd)
                        requires[jmd.name] = {jdk.get_transitive_requires_keyword()}
                    elif (dep.isJdkLibrary() or dep.isJreLibrary()) and dep.is_provided_by(jdk):
                        pass
                    elif dep.isLibrary():
                        jmd = get_library_as_module(dep, jdk)
                        modulepath.append(jmd)
                        requires[jmd.name] = set()
                    else:
                        mx.abort(dist.name + ' cannot depend on ' + dep.name + ' as it does not define a module')
            else:
                module_deps = get_module_deps(dist)

        jdk_modules = list(jdk.get_modules())
        java_projects = [d for d in module_deps if d.isJavaProject()]
        java_libraries = [d for d in module_deps if d.isLibrary()]

        # Collect packages in the module first
        with mx.Timer('packages', times):
            module_packages = dict()
            for project in java_projects:
                for package in project.defined_java_packages():
                    module_packages[package] = project.javaCompliance

                # Collect the required modules denoted by the dependencies of each project
                entries = mx.classpath_entries(project, includeSelf=False)
                for e in entries:
                    e_module_name = e.get_declaring_module_name()
                    if e_module_name and e_module_name != moduleName:
                        requires.setdefault(e_module_name, set())

        def _parse_packages_spec(packages_spec, available_packages, project_scope):
            """
            Parses a packages specification against a set of available packages:
              "org.graalvm.foo,org.graalvm.bar" -> set("org.graalvm.foo", "org.graalvm.bar")
              "<package-info>" -> set of all entries in `available_packages` denoting a package with a package-info.java file
              "org.graalvm.*" -> set of all entries in `available_packages` that start with "org.graalvm."
              "org.graalvm.compiler.code" -> set("org.graalvm.compiler.code")
            """
            if not packages_spec:
                mx.abort('exports attribute cannot have entry with empty packages specification', context=dist)
            res = dict()
            for spec in packages_spec.split(','):
                if spec.endswith('*'):
                    prefix = spec[0:-1]
                    selection = {p: javaCompliance for p, javaCompliance in available_packages.items() if p.startswith(prefix)}
                    if not selection:
                        mx.abort('The export package specifier "{}" does not match any of {}'.format(spec, available_packages.keys()), context=dist)
                    res.update(selection)
                elif spec == '<package-info>':
                    if not project_scope:
                        mx.abort('The export package specifier "<package-info>" can only be used in a project, not a distribution', context=dist)
                    res.update({p: project_scope.javaCompliance for p in mx._find_packages(project_scope, onlyPublic=True)})
                else:
                    if spec not in module_packages:
                        mx.abort('Cannot export package {0} from {1} as it is not defined by any project in the module {1}'.format(spec, moduleName), context=dist)
                    if project_scope and spec not in available_packages.keys() and project_scope.suite.requiredMxVersion >= mx.VersionSpec("5.226.1"):
                        mx.abort('Package {} in "exports" attribute not defined by project {}'.format(spec, project_scope), context=project_scope)
                    res[spec] = available_packages[spec]
            return res

        def _process_exports(export_specs, available_packages, project_scope=None):
            unqualified_exports = []
            for export in export_specs:
                if ' to ' in export:
                    splitpackage = export.split(' to ')
                    packages_spec = splitpackage[0].strip()
                    targets = [n.strip() for n in splitpackage[1].split(',')]
                    if not targets:
                        mx.abort('exports attribute must have at least one target for qualified export', context=dist)
                    for p in _parse_packages_spec(packages_spec, available_packages, project_scope).items():
                        exports.setdefault(p, set()).update(targets)
                else:
                    unqualified_exports.append(export)

            for unqualified_export in unqualified_exports:
                for p in _parse_packages_spec(unqualified_export, available_packages, project_scope).items():
                    exports[p] = set()

        module_info = getattr(dist, 'moduleInfo', None)
        alt_module_info = None

        if alt_module_info_name is not None:
            assert isinstance(alt_module_info_name, str)
            alt_module_info_attr_name = 'moduleInfo:' + alt_module_info_name
            alt_module_info = getattr(dist, alt_module_info_attr_name, None)
            if alt_module_info is None or not isinstance(alt_module_info, dict):
                mx.abort('"{}" attribute must be a dictionary'.format(alt_module_info_attr_name), context=dist)
            if module_info is None:
                mx.abort('"{}" attribute found but required "moduleInfo" attribute is missing'.format(alt_module_info_attr_name), context=dist)
            invalid = [k for k in alt_module_info.keys() if k != 'exports']
            if invalid:
                mx.abort('Sub-attribute(s) "{}" of "{}" attribute not supported. Only "exports" is currently supported.'.format('", "'.join(invalid), alt_module_info_attr_name), context=dist)
            alt_module_jar = join(dirname(moduleJar), basename(moduleJar)[:-len('.jar')] + '-' + alt_module_info_name + '.jar')
            alt_module_src_zip = alt_module_jar[:-len('.jar')] + '.src.zip'
            module_src_zip = moduleJar[:-len('.jar')] + '.src.zip'
            if exists(alt_module_jar):
                os.remove(alt_module_jar)
            shutil.copy(moduleJar, alt_module_jar)
            if exists(alt_module_src_zip):
                os.remove(alt_module_src_zip)
            if exists(module_src_zip):
                shutil.copy(module_src_zip, alt_module_src_zip)
            moduleJar = alt_module_jar
            alternatives = {alt_module_info_name : None}
        else:
            alt_module_info_names = [key[len('moduleInfo:'):] for key in dir(dist) if key.startswith('moduleInfo:')]
            alternatives = {name : make_java_module(dist, jdk, javac_daemon=javac_daemon, alt_module_info_name=name) for name in alt_module_info_names}

        mx.log('Building Java module {} ({}) from {}'.format(moduleName, basename(moduleJar), dist.name))

        if module_info:
            for entry in module_info.get("requires", []):
                parts = entry.split()
                qualifiers = parts[0:-1]
                name = parts[-1]
                requires.setdefault(name, set()).update(qualifiers)
            base_uses.update(module_info.get('uses', []))
            _process_exports((alt_module_info or module_info).get('exports', []), module_packages)

            opens = module_info.get('opens', {})

            requires_concealed = module_info.get('requiresConcealed', None)
            if requires_concealed is not None:
                parse_requiresConcealed_attribute(jdk, requires_concealed, concealedRequires, None, dist, modulepath)

        enhanced_module_usage_info = dist.suite.getMxCompatibility().enhanced_module_usage_info()

        with mx.Timer('projects', times):
            for project in java_projects:
                base_uses.update(getattr(project, 'uses', []))
                for m in getattr(project, 'runtimeDeps', []):
                    requires.setdefault(m, set()).add('static')

                if not enhanced_module_usage_info:
                    # In the absence of "requiresConcealed" and "requires" attributes, the import statements
                    # in the Java sources need to be scanned to determine what modules are
                    # required and what concealed packages are used.
                    allmodules = modulepath + jdk_modules
                    for pkg in itertools.chain(project.imported_java_packages(projectDepsOnly=False), getattr(project, 'imports', [])):
                        # Only consider packages not defined by the module we're creating. This handles the
                        # case where we're creating a module that will upgrade an existing upgradeable
                        # module in the JDK such as jdk.internal.vm.compiler.
                        if pkg not in module_packages.keys():
                            module, visibility = lookup_package(allmodules, pkg, moduleName)
                            if module and module.name != moduleName:
                                requires.setdefault(module.name, set())
                                if visibility != 'exported':
                                    assert visibility == 'concealed'
                                    concealedRequires.setdefault(module.name, set()).add(pkg)
                else:
                    for module, packages in project.get_concealed_imported_packages(jdk).items():
                        concealedRequires.setdefault(module, set()).update(packages)
                    for module in getattr(project, 'requires', []):
                        requires.setdefault(module, set())

                if not module_info:
                    # If neither an "exports" nor distribution-level "moduleInfo" attribute is present,
                    # all packages are exported.
                    default_exported_java_packages = [] if module_info else project.defined_java_packages()
                    available_packages = {package: project.javaCompliance for package in project.defined_java_packages()}
                    _process_exports(getattr(project, 'exports', default_exported_java_packages), available_packages, project)

        if enhanced_module_usage_info:
            with mx.Timer('libraries', times):
                for library in java_libraries:
                    base_uses.update(getattr(library, 'uses', []))
                    for m in getattr(library, 'runtimeDeps', []):
                        requires.setdefault(m, set()).add('static')

                    requires_concealed = getattr(library, 'requiresConcealed', None)
                    if requires_concealed is not None:
                        concealed = {}
                        parse_requiresConcealed_attribute(jdk, requires_concealed, concealed, None, library)
                        for module, packages in concealed.items():
                            concealedRequires.setdefault(module, set()).update(packages)
                    for module in getattr(library, 'requires', []):
                        requires.setdefault(module, set())
                    if hasattr(library, 'exports'):
                        java9 = mx_javacompliance.JavaCompliance('9+')
                        for package in getattr(library, 'exports'):
                            exports.setdefault((package, java9), set())
                            module_packages.setdefault(package, java9)
                    if not module_info:
                        mx.warn("Module {} re-packages library {} but doesn't have a `moduleInfo` attribute. Note that library packages are not auto-exported")

        build_directory = mx.ensure_dir_exists(moduleJar + ".build")
        try:
            files_to_remove = set()

            # To compile module-info.java, all classes it references must either be given
            # as Java source files or already exist as class files in the output directory.
            # As such, the jar file for each constituent distribution must be unpacked
            # in the output directory.
            versions = {}
            for d in [dist] + [md for md in module_deps if md.isJARDistribution()]:
                if d.isJARDistribution():
                    with zipfile.ZipFile(d.original_path(), 'r') as zf:
                        for arcname in sorted(zf.namelist()):
                            m = _versioned_re.match(arcname)
                            if m:
                                version = m.group(1)
                                unversioned_name = m.group(2)
                                if version <= jdk.javaCompliance:
                                    versions.setdefault(version, {})[unversioned_name] = arcname
                                else:
                                    # Ignore resource whose version is too high
                                    pass
                                if unversioned_name.startswith('META-INF/services/'):
                                    files_to_remove.add(arcname)
                                elif unversioned_name.startswith('META-INF/'):
                                    mx.abort("META-INF resources can not be versioned and will make modules fail to load ({}).".format(arcname))
            default_jmd = None

            all_versions = list(sorted(versions.keys(), key=int))
            if '9' not in all_versions:
                # 9 is the first version that supports modules and can be versioned in the JAR:
                # if there is no `META-INF/versions/9` then we should add a `module-info.class` to the root of the JAR
                # so that the module works on JDK 9.
                default_version = 'common'
                if all_versions:
                    max_version = str(max((int(v) for v in all_versions)))
                else:
                    max_version = default_version
                all_versions = all_versions + ['common']
            else:
                max_version = str(max((int(v) for v in all_versions)))
                default_version = max_version

            last_dest_dir = None
            unversioned_resources = set()
            for version in all_versions:
                unversioned_resources_backup = {}
                with mx.Timer('jmd@' + version, times):
                    uses = base_uses.copy()
                    provides = {}
                    dest_dir = join(build_directory, version)
                    if exists(dest_dir):
                        # Clean up any earlier build artifacts
                        mx.rmtree(dest_dir)

                    if last_dest_dir:
                        # The unversioned resources have been preserved from the
                        # last dest_dir so we can simply reuse last_dest_dir by
                        # renaming it. This avoids the need for extracting the
                        # unversioned resources for each version.
                        os.rename(last_dest_dir, dest_dir)

                    int_version = int(version) if version != 'common' else -1

                    for d in [dist] + [md for md in module_deps if md.isJARDistribution()]:
                        if d.isJARDistribution():
                            with zipfile.ZipFile(d.original_path(), 'r') as zf:
                                # Extract unversioned resources first
                                if not last_dest_dir:
                                    for name in zf.namelist():
                                        m = _versioned_re.match(name)
                                        if not m:
                                            zf.extract(name, mx._safe_path(dest_dir))
                                            rel_name = name if os.sep == '/' else name.replace('/', os.sep)
                                            unversioned_resources.add(rel_name)

                                # Extract versioned resources second
                                for name in zf.namelist():
                                    m = _versioned_re.match(name)
                                    if m:
                                        file_version = int(m.group(1))
                                        if file_version > int_version:
                                            continue
                                        unversioned_name = m.group(2)
                                        if name.startswith(_special_versioned_prefix):
                                            if not unversioned_name.startswith('META-INF/services'):
                                                raise mx.abort("The special versioned directory ({}) is only supported for META-INF/services files. Got {}".format(_special_versioned_prefix, name))
                                        if unversioned_name:
                                            contents = zf.read(name)
                                            dst = join(dest_dir, unversioned_name)
                                            if exists(dst) and dst not in unversioned_resources_backup:
                                                with open(dst, 'rb') as fp:
                                                    unversioned_contents = fp.read()
                                                    if unversioned_contents != contents:
                                                        unversioned_resources_backup[dst] = unversioned_contents
                                            parent = dirname(dst)
                                            if parent and not exists(parent):
                                                os.makedirs(parent)
                                            with open(dst, 'wb') as fp:
                                                fp.write(contents)

                                servicesDir = join(dest_dir, 'META-INF', 'services')
                                if exists(servicesDir):
                                    for servicePathName in os.listdir(servicesDir):
                                        # While a META-INF provider configuration file must use a fully qualified binary
                                        # name[1] of the service, a provides directive in a module descriptor must use
                                        # the fully qualified non-binary name[2] of the service.
                                        #
                                        # [1] https://docs.oracle.com/javase/9/docs/api/java/util/ServiceLoader.html
                                        # [2] https://docs.oracle.com/javase/9/docs/api/java/lang/module/ModuleDescriptor.Provides.html#service--
                                        service = servicePathName.replace('$', '.')

                                        assert '/' not in service
                                        with open(join(servicesDir, servicePathName)) as fp:
                                            serviceContent = fp.read()
                                        provides.setdefault(service, set()).update(provider.replace('$', '.') for provider in serviceContent.splitlines())
                                        # Service types defined in the module are assumed to be used by the module
                                        serviceClassfile = service.replace('.', '/') + '.class'
                                        if exists(join(dest_dir, serviceClassfile)):
                                            uses.add(service)

                    version_java_compliance = None if version == 'common' else mx.JavaCompliance(version + '+')

                    def allow_export(java_compliance):
                        if version_java_compliance is None:
                            return True
                        return java_compliance <= version_java_compliance

                    exports_clean = {package_java_compliance[0]: targets for package_java_compliance, targets in exports.items() if allow_export(package_java_compliance[1])}

                    requires_clean = {}
                    for required_module_spec, requires_directives in requires.items():
                        if '@' in required_module_spec:
                            module_name, java_compliance = required_module_spec.split('@', 1)
                            module_java_compliance = mx_javacompliance.JavaCompliance(java_compliance)
                            if module_java_compliance not in jdk.javaCompliance:
                                continue
                        else:
                            module_name = required_module_spec
                        requires_clean[module_name] = requires_directives

                    jmd = JavaModuleDescriptor(moduleName, exports_clean, requires_clean, uses, provides, packages=module_packages.keys(), concealedRequires=concealedRequires,
                                               jarpath=moduleJar, dist=dist, modulepath=modulepath, alternatives=alternatives, opens=opens)

                    # Compile module-info.class
                    module_info_java = join(dest_dir, 'module-info.java')
                    with open(module_info_java, 'w') as fp:
                        print(jmd.as_module_info(), file=fp)

                last_dest_dir = dest_dir

                with mx.Timer('compile@' + version, times):
                    def safe_path_arg(p):
                        r"""
                        Return `p` with all `\` characters replaced with `\\`, all spaces replaced
                        with `\ ` and the result enclosed in double quotes.
                        """
                        return '"{}"'.format(p.replace('\\', '\\\\').replace(' ', '\\ '))

                    javac_args = ['-d', safe_path_arg(dest_dir)]
                    modulepath_jars = [m.jarpath for m in modulepath if m.jarpath]
                    # TODO we should rather use the right JDK
                    javac_args += ['-target', version if version != 'common' else '9', '-source', version if version != 'common' else '9']

                    # The --system=none and --limit-modules options are used to support distribution defined modules
                    # that override non-upgradeable modules in the source JDK (e.g. org.graalvm.sdk is part of a
                    # GraalVM JDK). This means --module-path needs to contain the jmods for the JDK modules.
                    javac_args.append('--system=none')
                    if requires_clean:
                        javac_args.append('--limit-modules=' + ','.join(requires_clean.keys()))
                    jdk_jmods = (mx.get_opts().jmods_dir or join(jdk.home, 'jmods'))
                    if not exists(jdk_jmods):
                        mx.abort('Missing directory containing JMOD files: ' + jdk_jmods)
                    modulepath_jars.extend((join(jdk_jmods, m) for m in os.listdir(jdk_jmods) if m.endswith('.jmod')))
                    javac_args.append('--module-path=' + safe_path_arg(os.pathsep.join(modulepath_jars)))

                    if concealedRequires:
                        for module, packages in concealedRequires.items():
                            for package in packages:
                                javac_args.append('--add-exports=' + module + '/' + package + '=' + moduleName)
                    # https://blogs.oracle.com/darcy/new-javac-warning-for-setting-an-older-source-without-bootclasspath
                    # Disable the "bootstrap class path not set in conjunction with -source N" warning
                    # as we're relying on the Java compliance of project to correctly specify a JDK range
                    # providing the API required by the project. Also disable the warning about unknown
                    # modules in qualified exports (not sure how to avoid these since we build modules
                    # separately).
                    javac_args.append('-Xlint:-options,-module')
                    javac_args.append(safe_path_arg(module_info_java))

                    # Convert javac args to @args file
                    javac_args_file = mx._derived_path(dest_dir, '.javac_args')
                    with open(javac_args_file, 'w') as fp:
                        fp.write(os.linesep.join(javac_args))
                    javac_args = ['@' + javac_args_file]

                    if javac_daemon:
                        javac_daemon.compile(javac_args)
                    else:
                        mx.run([jdk.javac] + javac_args, cmdlinefile=dest_dir + '.cmdline')

                # Create .jmod for module
                if version == max_version:
                    # Delete module-info.java so that it does not get included in the .jmod file
                    os.remove(module_info_java)

                    # Temporarily move META-INF/services out of dest_dir. JDK 9+ service lookup
                    # still processes this directory but ProGuard does not.
                    services_dir = join(dest_dir, 'META-INF', 'services')
                    tmp_services_dir = None
                    if exists(services_dir):
                        tmp_services_dir = join(build_directory, version + '_services_tmp')
                        os.rename(services_dir, tmp_services_dir)

                    jmod_path = jmd.get_jmod_path(respect_stripping=False, alt_module_info_name=alt_module_info_name)
                    if exists(jmod_path):
                        os.remove(jmod_path)

                    jdk_jmod = join(jdk_jmods, basename(jmod_path))
                    jmod_args = ['create', '--class-path=' + dest_dir]
                    if not dist.is_stripped():
                        # There is a ProGuard bug that corrupts the ModuleTarget
                        # attribute of module-info.class.
                        target_os = mx.get_os()
                        target_os = 'macos' if target_os == 'darwin' else target_os
                        target_arch = mx.get_arch()
                        jmod_args.append('--target-platform={}-{}'.format(target_os, target_arch))
                    if exists(jdk_jmod):
                        with ZipFile(jdk_jmod, 'r') as zf:
                            # Copy commands and legal notices (if any) from JDK version of the module
                            for jmod_dir, jmod_option in (('bin', '--cmds'), ('legal', '--legal-notices')):
                                entries = [name for name in zf.namelist() if name.startswith(jmod_dir + '/')]
                                if entries:
                                    extracted_dir = join(dest_dir, jmod_dir)
                                    assert not exists(extracted_dir), extracted_dir
                                    zf.extractall(dest_dir, entries)
                                    entries_dir = mx._derived_path(dest_dir, '.' + jmod_dir)
                                    if exists(entries_dir):
                                        shutil.rmtree(entries_dir)
                                    os.rename(extracted_dir, entries_dir)
                                    jmod_args.extend([jmod_option, join(entries_dir)])
                    mx.run([jdk.exe_path('jmod')] + jmod_args + [jmod_path])

                    if tmp_services_dir:
                        os.rename(tmp_services_dir, services_dir)

                # Append the module-info.class
                module_info_arc_dir = ''
                if version != 'common':
                    module_info_arc_dir = _versioned_prefix + version + '/'
                if version == default_version:
                    default_jmd = jmd

                with mx.Timer('jar@' + version, times):
                    with ZipFile(moduleJar, 'a') as zf:
                        module_info_class = join(dest_dir, 'module-info.class')
                        zf.write(module_info_class, module_info_arc_dir + basename(module_info_class))

                if version != max_version:
                    # Leave output in place for last version so that the jmod command above
                    # can be manually re-executed (helps debugging).
                    with mx.Timer('cleanup@' + version, times):
                        if unversioned_resources_backup:
                            for dst, contents in unversioned_resources_backup.items():
                                with open(dst, 'wb') as fp:
                                    fp.write(contents)
                        for dirpath, dirnames, filenames in os.walk(dest_dir, topdown=False):
                            del_dirpath = True
                            for filename in filenames:
                                abs_filename = join(dirpath, filename)
                                rel_filename = os.path.relpath(abs_filename, dest_dir)
                                if rel_filename not in unversioned_resources:
                                    os.remove(abs_filename)
                                else:
                                    del_dirpath = False
                            for dname in dirnames:
                                if exists(join(dirpath, dname)):
                                    del_dirpath = False
                            if del_dirpath:
                                os.rmdir(dirpath)

            if files_to_remove:
                with mx.Timer('cleanup', times), mx.SafeFileCreation(moduleJar) as sfc:
                    with ZipFile(moduleJar, 'r') as inzf, ZipFile(sfc.tmpPath, 'w', inzf.compression) as outzf:
                        for info in inzf.infolist():
                            if info.filename not in files_to_remove:
                                outzf.writestr(info, inzf.read(info))
        finally:
            if not mx.get_opts().verbose:
                # Preserve build directory so that javac command can be re-executed
                # by cutting and pasting verbose output.
                mx.rmtree(build_directory)
        default_jmd.save()

    mx.logv('[' + moduleName + ' times: ' + ', '.join(['{}={:.3f}s'.format(name, secs) for name, secs in sorted(times, key=lambda pair: pair[1], reverse=True)]) + ']')
    return default_jmd

def get_transitive_closure(roots, observable_modules):
    """
    Gets the transitive closure of the dependences of a set of root modules
    (i.e. `roots`) with respect to a set of observable modules (i.e. `observable_modules`)

    :param iterable roots: the roots modules (JavaModulesDescriptors or module names) for
                           which the transitive closure is being requested
    :param iterable observable_modules: set of modules in which the transitive dependencies must exist
    """
    name_to_module = {m.name : m for m in observable_modules}
    transitive_closure = set()
    def lookup_module(name):
        m = name_to_module.get(name, None)
        if m is None:
            mx.abort('{} is not in the set of observable modules {}'.format(name, list(name_to_module.keys())))
        return m
    def add_transitive(mod):
        if mod not in transitive_closure:
            transitive_closure.add(mod)
            for name in mod.requires.keys():
                add_transitive(lookup_module(name))
    for root in roots:
        if isinstance(root, str):
            root = lookup_module(root)
        add_transitive(root)
    return transitive_closure

def parse_requiresConcealed_attribute(jdk, value, result, importer, context, modulepath=None):
    """
    Parses the "requiresConcealed" attribute value in `value` and updates `result`
    which is a dict from module name to set of package names.

    :param str importer: the name of the module importing the packages ("<unnamed>" or None denotes the unnamed module)
    :param context: context value to use when reporting errors
    :return: `result`
    """
    if value is None:
        return result
    all_modules = (modulepath or []) + list(jdk.get_modules())
    if not isinstance(value, dict):
        mx.abort('"requiresConcealed" attribute must be a dict', context=context)
    for module, packages in value.items():
        if '@' in module:
            module, java_compliance = module.split('@', 1)
            java_compliance = mx_javacompliance.JavaCompliance(java_compliance, context=context)
            if java_compliance not in jdk.javaCompliance:
                continue

        matches = [jmd for jmd in all_modules if jmd.name == module]
        if not matches:
            mx.abort('Module {} in "requiresConcealed" attribute does not exist in {}'.format(module, jdk), context=context)
        jmd = matches[0]

        package_set = result.setdefault(module, set())

        if packages == '*':
            star = True
            packages = jmd.packages
        else:
            star = False
            if not isinstance(packages, list):
                mx.abort('Packages for module {} in "requiresConcealed" attribute must be either "*" or a list of package names'.format(module), context=context)
        for package in packages:
            if package.endswith('?'):
                optional = True
                package = package[0:-1]
            else:
                optional = False
            visibility = jmd.get_package_visibility(package, importer)
            if visibility == 'concealed':
                package_set.add(package)
            elif visibility == 'exported':
                if not star:
                    suffix = '' if not importer else ' from module {}'.format(importer)
                    mx.warn('Package {} is not concealed in module {}{}'.format(package, module, suffix), context=context)
            elif not optional:
                m, _ = lookup_package(all_modules, package, importer)
                suffix = '' if not m else ' but in module {}'.format(m.name)
                mx.abort('Package {} is not defined in module {}{}'.format(package, module, suffix), context=context)
    return result

def requiredExports(distributions, jdk):
    """
    Collects requiredExports information for all passed-in distributions that are modules. The structure of this
    information is described in the return value documentation.

    :param distributions: list of Distribution objects that should be looked through for requiredExports information
    :param JDKConfig jdk: a JDK with a version >= 9 that can be used to compile the module-info class
    :return: A dictionary with (module_name, package_name) keys and values that are sets of `JavaModuleDescriptors` that require the export
    described by the given key. For example: ('java.base', 'jdk.internal.module'): set([module:org.graalvm.nativeimage.pointsto,
    module:org.graalvm.nativeimage.builder]) means that module java.base needs to be updated to export (i.e. --add-exports)
    jdk.internal.module to the modules org.graalvm.nativeimage.pointsto and org.graalvm.nativeimage.builder.
    """
    def _opt_as_java_module(dist):
        if not get_java_module_info(dist, fatalIfNotModule=False):
            return None
        return as_java_module(dist, jdk, fatalIfNotCreated=False)

    required_exports = defaultdict(set)

    for dist in distributions:
        target_module = _opt_as_java_module(dist)
        if target_module:
            target_module.collect_required_exports(required_exports)

    return required_exports
