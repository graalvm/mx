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
import re
import pickle
import shutil
import mx_javacompliance
from os.path import join, exists, dirname, basename, isdir, islink
from collections import defaultdict

from zipfile import ZipFile

import mx

# Temporary imports and (re)definitions while porting mx from Python 2 to Python 3
import itertools
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
                mx.abort(f'moduledeps can only include JAR distributions: {root}\nTry updating to mxversion >= 5.34.4 where `moduledeps` is not needed.', context=dist)

        moduledeps = []
        def _visit(dep, edges):
            if dep is not dist:
                if dep.isJavaProject() or dep.isJARDistribution():
                    if dep not in moduledeps:
                        moduledeps.append(dep)
                else:
                    mx.abort(f'modules can only include JAR distributions and Java projects: {dep}\nTry updating to mxversion >= 5.34.4 where `moduledeps` is not needed.', context=dist)
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
            mx.abort(f"Invalid identifier in automatic module name derived for library {dep.name}: {moduleName} (path: {dep.path})")
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
            out_lines = "\n".join(out.lines)
            err_lines = "\n".join(err.lines)
            mx.abort(f"java --describe-module {moduleName} failed. Please verify the moduleName attribute of {dep.name}.\nstdout:\n{out_lines}\nstderr:\n{err_lines}")
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
            with mx.SafeFileCreation(cache) as sfc, open(sfc.tmpPath, 'w') as fp:
                fp.write('\n'.join(lines) + '\n')
        except IOError as e:
            mx.warn('Error writing to ' + cache + ': ' + str(e))
            os.remove(cache)

    return JavaModuleDescriptor(moduleName, exports, requires, uses, provides, packages, jarpath=fullpath, opens=opens, lib=dep)


_versioned_prefix = 'META-INF/versions/'
_special_versioned_prefix = 'META-INF/_versions/'  # used for versioned services
_versioned_re = re.compile(r'META-INF/_?versions/([1-9][0-9]*)/(.+)')
_javamodule_buildlevel = None

def make_java_module(dist, jdk, archive, javac_daemon=None, alt_module_info_name=None):
    """
    Creates a Java module from a distribution.
    This updates the jar (or exploded jar) by adding `module-info` classes.

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
    :param _Archive archive: info about the jar being converted to a module
    :param CompilerDaemon javac_daemon: compiler daemon (if not None) to use for compiling module-info.java
    :param str alt_module_info_name: name of alternative module descriptor in `dist` (in the attribute "moduleInfo:" + `alt_module_info_name`)
    :return: the `JavaModuleDescriptor` for the latest version of the created Java module
    """
    info = get_java_module_info(dist)
    if info is None:
        return None

    from mx_jardistribution import _FileContentsSupplier, _Archive, _staging_dir_suffix

    times = []
    with mx.Timer('total', times):
        moduleName, _, module_jar = info  # pylint: disable=unpacking-non-sequence
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
            module_packages = set()
            for project in java_projects:
                module_packages.update(project.defined_java_packages())

                # Collect the required modules denoted by the dependencies of each project
                entries = mx.classpath_entries(project, includeSelf=False)
                for e in entries:
                    e_module_name = e.get_declaring_module_name()
                    if e_module_name and e_module_name != moduleName:
                        requires.setdefault(e_module_name, set())
            for library in java_libraries:
                module_packages.update(library.defined_java_packages())

        def _parse_packages_spec(packages_spec, available_packages, project_scope):
            """
            Parses a packages specification against a set of available packages:
              "org.graalvm.foo,org.graalvm.bar" -> set("org.graalvm.foo", "org.graalvm.bar")
              "<package-info>" -> set of all entries in `available_packages` denoting a package with a package-info.java file
              "org.graalvm.*" -> set of all entries in `available_packages` that start with "org.graalvm."
              "org.graalvm.compiler.code" -> set("org.graalvm.compiler.code")

            :param dict available_packages: map from package names to JavaCompliance values
            :return dict: entries from `available_packages` selected by `packages_spec`
            """
            if not packages_spec:
                mx.abort('exports attribute cannot have entry with empty packages specification', context=dist)
            res = set()
            for spec in packages_spec.split(','):
                if spec.endswith('*'):
                    prefix = spec[0:-1]
                    selection = set(p for p in available_packages if p.startswith(prefix))
                    if not selection:
                        mx.abort(f'The export package specifier "{spec}" does not match any of {available_packages}', context=dist)
                    res.update(selection)
                elif spec == '<package-info>':
                    if not isinstance(project_scope, mx.Project):
                        mx.abort('The export package specifier "<package-info>" can only be used in a project, not a distribution', context=dist)
                    res.update(mx._find_packages(project_scope, onlyPublic=True))
                else:
                    if spec not in module_packages:
                        mx.abort(f'Cannot export package {spec} from {moduleName} as it is not defined by any project in the module {moduleName}', context=dist)
                    if project_scope and spec not in available_packages and project_scope.suite.requiredMxVersion >= mx.VersionSpec("5.226.1"):
                        mx.abort(f'Package {spec} in "exports" attribute not defined by project {project_scope}', context=project_scope)
                    res.add(spec)
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
                    for p in _parse_packages_spec(packages_spec, available_packages, project_scope):
                        exports.setdefault(p, set()).update(targets)
                else:
                    unqualified_exports.append(export)

            for unqualified_export in unqualified_exports:
                for p in _parse_packages_spec(unqualified_export, available_packages, project_scope):
                    exports[p] = set()

        module_info = getattr(dist, 'moduleInfo', None)
        alt_module_info = None

        if alt_module_info_name is not None:
            assert not archive.exploded, archive
            assert isinstance(alt_module_info_name, str)
            alt_module_info_attr_name = 'moduleInfo:' + alt_module_info_name
            alt_module_info = getattr(dist, alt_module_info_attr_name, None)
            if alt_module_info is None or not isinstance(alt_module_info, dict):
                mx.abort(f'"{alt_module_info_attr_name}" attribute must be a dictionary', context=dist)
            if module_info is None:
                mx.abort(f'"{alt_module_info_attr_name}" attribute found but required "moduleInfo" attribute is missing', context=dist)
            invalid = [k for k in alt_module_info.keys() if k != 'exports']
            if invalid:
                invalid = '", "'.join(invalid)
                mx.abort(f'Sub-attribute(s) "{invalid}" of "{alt_module_info_attr_name}" attribute not supported. Only "exports" is currently supported.', context=dist)
            alt_module_jar = join(dirname(module_jar), basename(module_jar)[:-len('.jar')] + '-' + alt_module_info_name + '.jar')
            alt_module_src_zip = alt_module_jar[:-len('.jar')] + '.src.zip'
            module_src_zip = module_jar[:-len('.jar')] + '.src.zip'

            def replicate(src, dst):
                """
                Replicates `src` at `dst`.
                If `src` does not exist, `dst` is deleted.
                If `exploded` is True, `src` is assumed to be a directory and it is deep copied to `dst`,
                otherwise `src` is assumed to be a normal file and is copied to `dst`.
                """
                if isdir(dst) and not islink(dst):
                    mx.rmtree(dst)
                elif exists(dst):
                    os.remove(dst)
                if exists(src):
                    if isdir(src):
                        mx.copytree(src, dst, symlinks=True)
                    else:
                        shutil.copy(src, dst)

            replicate(module_jar, alt_module_jar)
            replicate(module_jar + _staging_dir_suffix, alt_module_jar + _staging_dir_suffix)
            replicate(module_src_zip, alt_module_src_zip)
            module_jar = alt_module_jar
            module_jar_staging_dir = module_jar + _staging_dir_suffix
            alternatives = {alt_module_info_name : None}
        elif not archive.exploded:
            alt_module_info_names = [key[len('moduleInfo:'):] for key in dir(dist) if key.startswith('moduleInfo:')]
            alternatives = {
                name : make_java_module(dist, jdk, archive, javac_daemon=javac_daemon, alt_module_info_name=name)
                for name in alt_module_info_names
            }
            module_jar_staging_dir = module_jar + _staging_dir_suffix
        else:
            alternatives = {}
            module_jar_staging_dir = module_jar

        mx.log(f'Building Java module {moduleName} ({basename(module_jar)}) from {dist.name}')

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
                        if pkg not in module_packages:
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
                    _process_exports(getattr(project, 'exports', default_exported_java_packages), project.defined_java_packages(), project)

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
                        _process_exports(getattr(library, 'exports'), library.defined_java_packages(), library)
                    if not module_info:
                        mx.warn("Module {} re-packages library {} but doesn't have a `moduleInfo` attribute. Note that library packages are not auto-exported")

        # Add all modules imported by concealed requires to the list of requires.
        for module in concealedRequires:
            if module != 'java.base':
                requires.setdefault(module, set())

        build_directory = mx.ensure_dir_exists(module_jar + ".build")
        try:
            files_to_remove = set()

            # To compile module-info.java, all classes it references must either be given
            # as Java source files or already exist as class files in the output directory.
            # This is due to the constraint that all the classes in a module must be in
            # a single directory (or jar).
            # As such, the jar file for each constituent distribution must be unpacked
            # in the output directory.

            # Set of ints representing version numbers
            versions = set()

            # List of 4-tuples representing a versioned resource:
            #  str arcname: name of resource within its archive
            #  _ArchiveEntry entry: describes the contents of the resource
            #  int version: earliest Java version in which resource is valid
            # str unversioned_name: name of the resource in a version-flattened archive
            versioned = []

            # List of 2-tuples representing a versioned resource:
            #  str arcname: name of resource within its archive
            #  _ArchiveEntry entry: describes the contents of the resource
            unversioned = []

            for arcname, entry in archive.entries.items():
                m = _versioned_re.match(arcname)
                if m:
                    version = int(m.group(1))
                    versions.add(version)
                    if version > jdk.javaCompliance.value:
                        # Ignore resource whose version is too high
                        continue
                    unversioned_name = m.group(2)
                    if not archive.exploded:
                        if unversioned_name.startswith('META-INF/services/'):
                            files_to_remove.add(arcname)
                        elif unversioned_name.startswith('META-INF/'):
                            mx.abort(f"META-INF resources can not be versioned and will make modules fail to load ({arcname}).")
                    versioned.append((arcname, entry, version, unversioned_name))
                else:
                    unversioned.append((arcname, entry))

            if archive.exploded:
                jmod_version = None
                all_versions = [str(jdk.javaCompliance.value)]
            else:
                # Ensure that created .jmod is compatible with the default JDK
                default_jdk = mx.get_jdk(tag=mx.DEFAULT_JDK_TAG)
                try:
                    jmod_version = str(max(v for v in versions if v <= default_jdk.javaCompliance.value))
                except ValueError:
                    jmod_version = None if default_jdk.javaCompliance < '9' else 'common'

                # Sort versions in increasing order as expected by the rest of the code
                all_versions = [str(v) for v in sorted(versions)]
                if '9' not in all_versions:
                    # 9 is the first version that supports modules and can be versioned in the JAR:
                    # if there is no `META-INF/versions/9` then we should add a `module-info.class`
                    # to the root of the JAR so that the module works on JDK 9.
                    all_versions = ['common'] + all_versions

            assert jmod_version is None or jmod_version in all_versions

            for version in all_versions:
                restore_files = {}
                with mx.Timer('jmd@' + version, times):
                    uses = base_uses.copy()
                    provides = {}
                    int_version = int(version) if version != 'common' else -1

                    # Modify staging directory in-situ
                    dest_dir = module_jar_staging_dir

                    if not archive.exploded:
                        def create_missing_dirs(path):
                            if not exists(path):
                                create_missing_dirs(dirname(path))
                                os.mkdir(path)
                                _Archive.create_jdk_8268216(path)

                        def sync_file(src, dst, restore_files):
                            """
                            Ensures that `dst` points at or contains the same contents as `src`.

                            :param dict restore_files: map from `dst` to a callable that will restore its original
                                        content or to None should `dst` be deleted once the module-info.class has
                                        been produced
                            """
                            while islink(src):
                                src = os.readlink(src)
                            if not mx.can_symlink():
                                mx.ensure_dir_exists(dirname(dst))
                                if exists(dst):
                                    restore_files[dst] = _FileContentsSupplier(dst, eager=True).restore
                                    os.remove(dst)
                                else:
                                    restore_files[dst] = None
                                shutil.copy(src, dst)
                            else:
                                if exists(dst):
                                    if islink(dst):
                                        target = os.readlink(dst)
                                        if target == src:
                                            return
                                        if mx.is_windows() and target.startswith('\\\\?\\') and target[4:] == src:
                                            # os.readlink was changed in python 3.8 to include a \\?\ prefix on Windows
                                            return
                                        restore_files[dst] = lambda: os.symlink(target, dst)
                                    else:
                                        restore_files[dst] = _FileContentsSupplier(dst, eager=True).restore
                                    os.remove(dst)
                                else:
                                    restore_files[dst] = None
                                    create_missing_dirs(dirname(dst))
                                os.symlink(src, dst)

                        # Put versioned resources into their non-versioned locations
                        for arcname, entry, entry_version, unversioned_name in versioned:
                            if entry_version > int_version:
                                continue
                            if arcname.startswith(_special_versioned_prefix):
                                if not unversioned_name.startswith('META-INF/services'):
                                    mx.abort(f"The special versioned directory ({_special_versioned_prefix}) is only supported for META-INF/services files. Got {name}")
                            if unversioned_name:
                                dst = join(dest_dir, unversioned_name)
                                sync_file(entry.staged, dst, restore_files)

                    services_dir = join(dest_dir, 'META-INF', 'services')
                    if exists(services_dir):
                        for servicePathName in os.listdir(services_dir):
                            if servicePathName == _Archive.jdk_8268216:
                                continue
                            # While a META-INF provider configuration file must use a fully qualified binary
                            # name[1] of the service, a provides directive in a module descriptor must use
                            # the fully qualified non-binary name[2] of the service.
                            #
                            # [1] https://docs.oracle.com/javase/9/docs/api/java/util/ServiceLoader.html
                            # [2] https://docs.oracle.com/javase/9/docs/api/java/lang/module/ModuleDescriptor.Provides.html#service--
                            service = servicePathName.replace('$', '.')

                            assert '/' not in service
                            with open(join(services_dir, servicePathName)) as fp:
                                serviceContent = fp.read()
                            provides.setdefault(service, set()).update(provider.replace('$', '.') for provider in serviceContent.splitlines())
                            # Service types defined in the module are assumed to be used by the module
                            serviceClassfile = service.replace('.', '/') + '.class'
                            if exists(join(dest_dir, serviceClassfile)):
                                uses.add(service)

                    def exported_package_exists(p):
                        package_exists = exists(join(dest_dir, p.replace('.', os.sep)))
                        if not package_exists and dist.suite.getMxCompatibility().enforce_spec_compliant_exports():
                            pp = [proj for proj in java_projects if p in proj.defined_java_packages()][0]
                            dist.abort(f'Modular multi-release JARs cannot export packages defined only by versioned projects: {p} is defined by {pp} with multiReleaseJarVersion={pp.multiReleaseJarVersion}')
                        return package_exists

                    # Exports of modular multi-release JARs must be exactly the same in all versions,
                    # but for backward compatibility we tolerate version-specific exports.
                    exports_clean = {p: exports[p] for p in exports if exported_package_exists(p)}

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

                    jmd = JavaModuleDescriptor(moduleName, exports_clean, requires_clean, uses, provides, packages=module_packages, concealedRequires=concealedRequires,
                                               jarpath=module_jar, dist=dist, modulepath=modulepath, alternatives=alternatives, opens=opens)

                    # Compile module-info.class
                    module_info_java = join(dest_dir, 'module-info.java')
                    with open(module_info_java, 'w') as fp:
                        print(jmd.as_module_info(), file=fp)

                with mx.Timer('compile@' + version, times):
                    def safe_path_arg(p):
                        r"""
                        Return `p` with all `\` characters replaced with `\\`, all spaces replaced
                        with `\ ` and the result enclosed in double quotes.
                        """
                        return '"' + p.replace('\\', '\\\\').replace(' ', '\\ ')  + '"'

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
                if version == jmod_version:
                    assert not archive.exploded

                    class HideDirectory(object):
                        def __init__(self, dirpath):
                            self.dirpath = dirpath
                            self.tmp_dirpath = None
                        def __enter__(self):
                            if exists(self.dirpath):
                                self.tmp_dirpath = join(build_directory, f'{version}_{basename(self.dirpath)}.{os.getpid()}')
                                os.rename(self.dirpath, self.tmp_dirpath)
                        def __exit__(self, exc_type, exc_value, traceback):
                            if self.tmp_dirpath:
                                os.rename(self.tmp_dirpath, self.dirpath)

                    # Temporarily move META-INF/services and META-INF/versions out of dest_dir
                    # so that they do not end up in the jmod.
                    with HideDirectory(join(dest_dir, 'META-INF', 'services')), HideDirectory(join(dest_dir, 'META-INF', 'versions')):
                        jmod_path = jmd.get_jmod_path(respect_stripping=False, alt_module_info_name=alt_module_info_name)
                        if exists(jmod_path):
                            os.remove(jmod_path)

                        jdk_jmod = join(default_jdk.home, 'jmods', basename(jmod_path))
                        jmod_args = ['create', '--class-path=' + dest_dir]
                        if not dist.is_stripped():
                            # There is a ProGuard bug that corrupts the ModuleTarget
                            # attribute of module-info.class.
                            target_os = mx.get_os()
                            target_os = 'macos' if target_os == 'darwin' else target_os
                            target_arch = mx.get_arch()
                            jmod_args.append(f'--target-platform={target_os}-{target_arch}')
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
                        mx.run([default_jdk.exe_path('jmod')] + jmod_args + [jmod_path])

                with mx.Timer('jar@' + version, times):
                    if not archive.exploded:
                        # Append the module-info.class
                        module_info_arc_dir = '' if version == 'common' else _versioned_prefix + version + '/'
                        with ZipFile(module_jar, 'a') as zf:
                            module_info_class = join(dest_dir, 'module-info.class')
                            arcname = module_info_arc_dir + basename(module_info_class)
                            zf.write(module_info_class, arcname)
                        os.remove(module_info_class)

                if restore_files:
                    for dst, restore in restore_files.items():
                        os.remove(dst)
                        if restore is not None:
                            restore()

            if files_to_remove:
                with mx.Timer('cleanup', times), mx.SafeFileCreation(module_jar) as sfc:
                    with ZipFile(module_jar, 'r') as inzf, ZipFile(sfc.tmpPath, 'w', inzf.compression) as outzf:
                        for info in inzf.infolist():
                            if info.filename not in files_to_remove:
                                outzf.writestr(info, inzf.read(info))
        finally:
            if not mx.get_opts().verbose:
                # Preserve build directory so that javac command can be re-executed
                # by cutting and pasting verbose output.
                mx.rmtree(build_directory)
        jmd.save()

    mx.logv('[' + moduleName + ' times: ' + ', '.join([f'{name}={secs:.3f}s' for name, secs in sorted(times, key=lambda pair: pair[1], reverse=True)]) + ']')
    assert version == (str(max(versions)) if versions else str(jdk.javaCompliance.value) if archive.exploded else 'common')
    return jmd

def get_transitive_closure(roots, observable_modules):
    """
    Gets the transitive closure of the dependencies of a set of root modules
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
            mx.abort(f'{name} is not in the set of observable modules {list(name_to_module.keys())}')
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
            if jdk.javaCompliance not in java_compliance:
                continue

        matches = [jmd for jmd in all_modules if jmd.name == module]
        if not matches:
            mx.abort(f'Module {module} in "requiresConcealed" attribute does not exist in {jdk}', context=context)
        jmd = matches[0]

        package_set = result.setdefault(module, set())

        if packages == '*':
            star = True
            packages = jmd.packages
        else:
            star = False
            if not isinstance(packages, list):
                mx.abort(f'Packages for module {module} in "requiresConcealed" attribute must be either "*" or a list of package names', context=context)
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
                    suffix = '' if not importer else f' from module {importer}'
                    mx.warn(f'Package {package} is not concealed in module {module}{suffix}', context=context)
            elif not optional:
                m, _ = lookup_package(all_modules, package, importer)
                suffix = '' if not m else f' but in module {m.name}'
                mx.abort(f'Package {package} is not defined in module {module}{suffix}', context=context)
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
