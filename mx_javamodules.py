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
import itertools
from os.path import join, exists, dirname, basename
from tempfile import mkdtemp

from zipfile import ZipFile

import mx

# Temporary imports and (re)definitions while porting mx from Python 2 to Python 3
import sys
if sys.version_info[0] < 3:
    from StringIO import StringIO
else:
    from io import StringIO

class JavaModuleDescriptor(object):
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
    :param set conceals: the packages defined but not exported to everyone by this module
    :param str jarpath: path to module jar file
    :param JARDistribution dist: distribution from which this module was derived
    :param list modulepath: list of `JavaModuleDescriptor` objects for the module dependencies of this module
    :param bool boot: specifies if this module is in the boot layer
    """
    def __init__(self, name, exports, requires, uses, provides, packages=None, concealedRequires=None, jarpath=None, dist=None, modulepath=None, boot=False):
        self.name = name
        self.exports = exports
        self.requires = requires
        self.concealedRequires = concealedRequires if concealedRequires else {}
        self.uses = frozenset(uses)
        self.provides = provides
        exportedPackages = frozenset(exports.keys())
        self.packages = exportedPackages if packages is None else frozenset(packages)
        assert len(exports) == 0 or exportedPackages.issubset(self.packages), exportedPackages - self.packages
        self.conceals = self.packages - exportedPackages
        self.jarpath = jarpath
        self.dist = dist
        self.modulepath = modulepath
        self.boot = boot

    def __str__(self):
        return 'module:' + self.name

    def __repr__(self):
        return self.__str__()

    def __cmp__(self, other):
        assert isinstance(other, JavaModuleDescriptor)
        return (self.name > other.name) - (self.name < other.name)

    @staticmethod
    def load(dist, jdk, fatalIfNotCreated=True):
        """
        Unpickles the module descriptor corresponding to a given distribution.

        :param str dist: the distribution for which to read the pickled object
        :param JDKConfig jdk: used to resolve pickled references to JDK modules
        :param bool fatalIfNotCreated: specifies whether to abort if a descriptor has not been created yet
        """
        _, path, _ = get_java_module_info(dist, fatalIfNotModule=True)  # pylint: disable=unpacking-non-sequence
        if not exists(path):
            if fatalIfNotCreated:
                mx.abort(path + ' does not exist')
            else:
                return None
        with open(path, 'rb') as fp:
            jmd = pickle.load(fp)
        jdkmodules = {m.name: m for m in jdk.get_modules()}
        resolved = []
        for name in jmd.modulepath:
            if name.startswith('dist:'):
                distName = name[len('dist:'):]
                resolved.append(as_java_module(mx.distribution(distName), jdk))
            else:
                resolved.append(jdkmodules[name])
        jmd.modulepath = resolved
        jmd.dist = mx.distribution(jmd.dist)
        if not os.path.isabs(jmd.jarpath):
            jmd.jarpath = join(dirname(path), jmd.jarpath)
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
        _, path, _ = get_java_module_info(dist, fatalIfNotModule=True)  # pylint: disable=unpacking-non-sequence
        modulepath = self.modulepath
        jarpath = self.jarpath
        self.modulepath = [m.name if not m.dist else 'dist:' + m.dist.name for m in modulepath]
        self.dist = dist.name
        self.jarpath = os.path.relpath(jarpath, dirname(path))
        try:
            with mx.SafeFileCreation(path) as sfc, open(sfc.tmpPath, 'wb') as f:
                pickle.dump(self, f)
        finally:
            self.modulepath = modulepath
            self.dist = dist
            self.jarpath = jarpath

    def as_module_info(self):
        """
        Gets this module descriptor expressed as the contents of a ``module-info.java`` file.
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
        for service, providers in sorted(self.provides.items()):
            print('    provides ' + service + ' with ' + ', '.join((p for p in providers)) + ';', file=out)
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
    if dist.suite.getMxCompatibility().moduleDepsEqualDistDeps():
        return dist.archived_deps()

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
                    if dep not in moduledeps:
                        moduledeps.append(dep)
                else:
                    mx.abort('modules can (currently) only include JAR distributions and Java projects: ' + str(dep), context=dist)
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
    if dist.suite.getMxCompatibility().moduleDepsEqualDistDeps():
        module_name = getattr(dist, 'moduleName', None)
        if not module_name:

            return None
        assert len(module_name) > 0, '"moduleName" attribute of distribution ' + dist.name + ' cannot be empty'
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
             the name of the module, the descriptor pickle path, and finally the path to the jar file containing the built module
    """
    module_name = get_module_name(dist)
    if not module_name:
        if fatalIfNotModule:
            mx.abort('Distribution ' + dist.name + ' does not define a module')
        return None
    return module_name, dist.path + '-module.pickled', dist.path


def _expand_package_info(dep, packages):
    """
    Converts a list of package names to a unique set of package names,
    expanding any '<package-info>' entry in the list to the set of
    packages in the project that contain a ``package-info.java`` file.
    """
    if '<package-info>' in packages:
        result = set((e for e in packages if e != '<package-info>'))
        result.update(mx._find_packages(dep, onlyPublic=True))
    else:
        result = set(packages)
    return result


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
        rc = mx.run([jdk.java, '--module-path', fullpath, '--describe-module', moduleName], out=out, err=out, nonZeroIsFatal=False)
        lines = out.lines
        if rc != 0:
            mx.abort("java --describe-module {} failed. Please verify the moduleName attribute of {}.\n{}".format(moduleName, dep.name, "\n".join(lines)))
        save = True
    else:
        with open(cache) as fp:
            lines = fp.read().splitlines()

    assert lines and lines[0].startswith(moduleName), (dep.name, moduleName, lines)

    accepted_modifiers = set(['transitive'])
    requires = {}
    exports = {}
    provides = {}
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

    return JavaModuleDescriptor(moduleName, exports, requires, uses, provides, packages, jarpath=fullpath)


_versioned_prefix = 'META-INF/versions/'
_special_versioned_prefix = 'META-INF/_versions/'  # used for versioned services
_versioned_re = re.compile(r'META-INF/_?versions/([1-9][0-9]*)/(.+)')


def make_java_module(dist, jdk):
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

    moduleName, _, moduleJar = info  # pylint: disable=unpacking-non-sequence
    mx.log('Building Java module ' + moduleName + ' from ' + dist.name)
    exports = {}
    requires = {}
    concealedRequires = {}
    base_uses = set()

    modulepath = list()
    usedModules = set()

    if dist.suite.getMxCompatibility().moduleDepsEqualDistDeps():
        moduledeps = dist.archived_deps()
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
        moduledeps = get_module_deps(dist)

    # Append JDK modules to module path
    jdkModules = jdk.get_modules()
    if not isinstance(jdkModules, list):
        jdkModules = list(jdkModules)
    allmodules = modulepath + jdkModules

    javaprojects = [d for d in moduledeps if d.isJavaProject()]

    # Collect packages in the module first
    packages = set()
    for dep in javaprojects:
        packages.update(dep.defined_java_packages())

    for dep in javaprojects:
        base_uses.update(getattr(dep, 'uses', []))
        for pkg in getattr(dep, 'runtimeDeps', []):
            requires.setdefault(pkg, {'static'})

        for pkg in itertools.chain(dep.imported_java_packages(projectDepsOnly=False), getattr(dep, 'imports', [])):
            # Only consider packages not defined by the module we're creating. This handles the
            # case where we're creating a module that will upgrade an existing upgradeable
            # module in the JDK such as jdk.internal.vm.compiler.
            if pkg not in packages:
                depModule, visibility = lookup_package(allmodules, pkg, moduleName)
                if depModule and depModule.name != moduleName:
                    requires.setdefault(depModule.name, set())
                    if visibility == 'exported':
                        # A distribution based module does not re-export its imported JDK packages
                        usedModules.add(depModule)
                    else:
                        assert visibility == 'concealed'
                        concealedRequires.setdefault(depModule.name, set()).add(pkg)
                        usedModules.add(depModule)

        # If an "exports" attribute is not present, all packages are exported
        for package in _expand_package_info(dep, getattr(dep, 'exports', dep.defined_java_packages())):
            if ' to ' in package:
                splitpackage = package.split(' to ')
                package = splitpackage[0].strip()
                if not package:
                    mx.abort('exports attribute cannot have empty package value', context=dist)
                targets = [n.strip() for n in splitpackage[1].split(',')]
                if not targets:
                    mx.abort('exports attribute must have at least one target for qualified export', context=dist)
                exports.setdefault(package, targets)
            else:
                exports.setdefault(package, [])

    work_directory = mkdtemp()
    try:
        files_to_remove = set()

        # To compile module-info.java, all classes it references must either be given
        # as Java source files or already exist as class files in the output directory.
        # As such, the jar file for each constituent distribution must be unpacked
        # in the output directory.
        versions = {}
        for d in [dist] + [md for md in moduledeps if md.isJARDistribution()]:
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

        all_versions = set(versions.keys())
        if '9' not in all_versions:
            # 9 is the first version that supports modules and can be versioned in the JAR:
            # if there is no `META-INF/versions/9` then we should add a `module-info.class` to the root of the JAR
            # so that the module works on JDK 9.
            all_versions = all_versions | {'common'}
            default_version = 'common'
        else:
            default_version = str(max((int(v) for v in all_versions)))

        for version in all_versions:
            uses = base_uses.copy()
            provides = {}
            dest_dir = join(work_directory, version)
            int_version = int(version) if version != 'common' else -1

            for d in [dist] + [md for md in moduledeps if md.isJARDistribution()]:
                if d.isJARDistribution():
                    with zipfile.ZipFile(d.original_path(), 'r') as zf:
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
                                    dst = join(dest_dir, unversioned_name)
                                    parent = dirname(dst)
                                    if parent and not exists(parent):
                                        os.makedirs(parent)
                                    with open(dst, 'wb') as fp:
                                        fp.write(zf.read(name))
                            else:
                                zf.extract(name, dest_dir)

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
                                provides.setdefault(service, set()).update(serviceContent.splitlines())
                                # Service types defined in the module are assumed to be used by the module
                                serviceClassfile = service.replace('.', '/') + '.class'
                                if exists(join(dest_dir, serviceClassfile)):
                                    uses.add(service)

            jmd = JavaModuleDescriptor(moduleName, exports, requires, uses, provides, packages=packages, concealedRequires=concealedRequires,
                                       jarpath=moduleJar, dist=dist, modulepath=modulepath)

            # Compile module-info.class
            module_info_java = join(dest_dir, 'module-info.java')
            with open(module_info_java, 'w') as fp:
                print(jmd.as_module_info(), file=fp)
            javacCmd = [jdk.javac, '-d', dest_dir]
            jdkModuleNames = [m.name for m in jdkModules]
            modulepathJars = [m.jarpath for m in jmd.modulepath if m.jarpath and m.name not in jdkModuleNames]
            upgrademodulepathJars = [m.jarpath for m in jmd.modulepath if m.jarpath and m.name in jdkModuleNames]
            # TODO we should rather use the right JDK
            javacCmd += ['-target', version if version != 'common' else '9', '-source', version if version != 'common' else '9']
            if modulepathJars:
                javacCmd.append('--module-path')
                javacCmd.append(os.pathsep.join(modulepathJars))
            if upgrademodulepathJars:
                javacCmd.append('--upgrade-module-path')
                javacCmd.append(os.pathsep.join(upgrademodulepathJars))
            if concealedRequires:
                for module, packages_ in concealedRequires.items():
                    for package in packages_:
                        javacCmd.append('--add-exports=' + module + '/' + package + '=' + moduleName)
            # https://blogs.oracle.com/darcy/new-javac-warning-for-setting-an-older-source-without-bootclasspath
            # Disable the "bootstrap class path not set in conjunction with -source N" warning
            # as we're relying on the Java compliance of project to correctly specify a JDK range
            # providing the API required by the project. Also disable the warning about unknown
            # modules in qualified exports (not sure how to avoid these since we build modules
            # separately).
            javacCmd.append('-Xlint:-options,-module')
            javacCmd.append(module_info_java)
            mx.run(javacCmd)
            module_info_class = join(dest_dir, 'module-info.class')

            # Append the module-info.class
            module_info_arc_dir = ''
            if version != 'common':
                module_info_arc_dir = _versioned_prefix + version + '/'
            if version == default_version:
                default_jmd = jmd

            with ZipFile(moduleJar, 'a') as zf:
                zf.write(module_info_class, module_info_arc_dir + basename(module_info_class))
                zf.write(module_info_java, module_info_arc_dir + basename(module_info_java))

        if files_to_remove:
            with mx.SafeFileCreation(moduleJar) as sfc:
                with ZipFile(moduleJar, 'r') as inzf, ZipFile(sfc.tmpPath, 'w', inzf.compression) as outzf:
                    for info in inzf.infolist():
                        if info.filename not in files_to_remove:
                            outzf.writestr(info, inzf.read(info))
    finally:
        shutil.rmtree(work_directory)
    default_jmd.save()
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
            mx.abort('{} is not in the set of observable modules {}'.format(name, name_to_module.keys()))
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
