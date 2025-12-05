# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2018, 2019, Oracle and/or its affiliates. All rights reserved.
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

__all__ = [
    "lazy_default",
    "lazy_class_default",
    "Ninja",
    "NativeDependency",
    "TargetSelection",
    "MultitargetProject",
    "TargetArchBuildTask",
    "NinjaProject",
    "NinjaBuildTask",
    "NinjaManifestGenerator",
    "DefaultNativeProject",
    "NinjaToolchainTemplate",
]

import abc
import collections
import errno
import filecmp
import itertools
import os
import subprocess
import sys
from pathlib import Path

from . import mx, mx_util
from . import mx_compdb
from . import mx_subst
from .build import tasks

_target_jdk = None
"""JDK for which native projects should be built."""


def _get_target_jdk():
    global _target_jdk
    if not _target_jdk:
        _target_jdk = mx.get_jdk(tag=mx.DEFAULT_JDK_TAG)
    return _target_jdk


# Support for conditional compilation based on the JDK version.
mx_subst.results_substitutions.register_no_arg('jdk_ver', lambda: str(_get_target_jdk().javaCompliance.value))

# Support for inheriting toolchains.
def _ninja_toolchain_path(toolchain):
    dist = mx.distribution(toolchain)
    path = os.path.join(dist.get_output(), 'toolchain.ninja')
    # See ninja_syntax.escape_path
    # Unfortunately, this could be used before ninja_syntax is loaded/loadable
    path = path.replace('$ ', '$$ ').replace(' ', '$ ').replace(':', '$:')
    return path

mx_subst.path_substitutions.register_with_arg('ninja-toolchain', _ninja_toolchain_path)


class lazy_default(object):  # pylint: disable=invalid-name
    def __init__(self, init):
        self.init = init

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return vars(instance).setdefault(self.init.__name__, self.init(instance))


class lazy_class_default(object):  # pylint: disable=invalid-name
    def __init__(self, init):
        self.init = init

    def __get__(self, instance, owner):
        try:
            return vars(self)[self.init.__name__]
        except KeyError:
            return vars(self).setdefault(self.init.__name__, self.init(owner))

class TargetSpec(object):
    """Description of a native target.

    Attributes
        os: str, optional
            The operating system this toolchain is targetting.
            Defaults to the host OS.
        arch: str, optional
            The CPU architecture this toolchain is targetting.
            Defaults to the host architecture.
        libc: str, optional
            The standard C library this toolchain is targetting.
            If the target os is "linux", possible values are "glibc" and "musl". The default is the host
            libc, or "glibc" when cross-compiling to linux.
            On other operating systems, the default and only possible value is "default".
        variant: str, optional
            Code generation variant of his toolchain.
            This can be used to express things like different optimization levels, debug builds,
            instrumentations and so on.
    """
    def __init__(self, target_dict):
        self.os = target_dict.get('os', mx.get_os())
        self.arch = target_dict.get('arch', mx.get_arch())
        self.libc = target_dict.get('libc', TargetSpec._default_libc(self.os))
        self.variant = target_dict.get('variant')

    @classmethod
    def _default_libc(cls, os):
        if os == 'linux':
            if mx.get_os() == 'linux':
                return mx.get_os_variant() or 'glibc'
            else:
                # no way to detect "host libc" when cross-compiling, default to glibc in that case
                return "glibc"
        else:
            return 'default'

    @property
    def name(self):
        name = f'{self.os}-{self.arch}-{self.libc}'
        if self.variant:
            name = f'{name}-{self.variant}'
        return name

    @property
    def subdir(self):
        paths = [f"{self.os}-{self.arch}"]
        libc_var = [self.libc]
        if self.variant:
            libc_var.append(self.variant)
        paths.append('-'.join(libc_var))
        return os.path.join(*paths)


class ToolchainSpec(object):
    """Description of a native toolchain.

    Attributes
        kind: str
            The build system this toolchain is used for.
        target: TargetSpec
            The target this toolchain is producing code for.
        compiler: str, optional
            The compiler this toolchain is using. Can be used to select special compilers that are shipped
            with mx suites as library dependencies or even built using mx.
            Defaults to the special value 'host', which means "the compiler installed on the host os".
    """
    def __init__(self, toolchain_dict):
        self.kind = toolchain_dict.get('kind')
        self.target = TargetSpec(toolchain_dict.get('target'))
        self.compiler = toolchain_dict.get('compiler', 'host')

class MultitargetSpec(object):
    """Declaration of a project that it wants to be built for multiple targets.

    A native project is multi-target if it has a "multitarget" attribute that contains a MultitargetSpec
    or a list of MultitargetSpec. This selects which toolchains can be used for building a project.

    Attributes
        os: list of str, optional
            Build this project for all these operating systems.
            Defaults to only the host OS.
        arch: list of str, optional
            Build this project for all these CPU architectures.
            Defaults to only the host architecture.
        libc: list of str, optional
            Build this project for all these standard C libraries.
            Defaults to only the default libc for each OS.
        variant: list of str, optional
            Build this project with these code generation variants.
            Defaults to all.
        compiler: list of str, optional
            List of compatible compilers for this project, in order of preference.
            Each os/arch/libc/variant combination will be built with the first compiler from this list that
            exists for this os/arch/libc/variant combination.
            Defaults to ["host", "*"], i.e. any compiler but prefer the compiler from the host.
    """
    def __init__(self, multitarget):
        self.os = multitarget.get('os', [mx.get_os()])
        self.arch = multitarget.get('arch', [mx.get_arch()])
        self.libc = multitarget.get('libc', [TargetSpec._default_libc(os) for os in self.os])
        self.variant = multitarget.get('variant', ['*'])
        self.compiler = multitarget.get('compiler', ['host', '*'])

    def matches(self, target_spec):
        def _match(attribute):
            allowed_list = getattr(self, attribute)
            return getattr(target_spec, attribute) in allowed_list or "*" in allowed_list
        return _match('os') and _match('arch') and _match('libc') and _match('variant')

    @classmethod
    def get(cls, multitargets):
        if not multitargets:
            return [cls.default()]
        elif isinstance(multitargets, list):
            return [MultitargetSpec(t) for t in multitargets]
        else:
            return [MultitargetSpec(multitargets)]

    @classmethod
    def default(cls):
        return MultitargetSpec({
            "variant": [None],
            "compiler": ["host"],
        })

class TargetSelection(object):
    """Select which targets of multitarget projects are built. Without this argument, only the host target is built.

    This is a comma-separated list of <os>-<arch>-<libc>[-<variant>] tuples. Each component can also be '*'
    to indicate all. <os>, <arch> and <libc> can be 'default' to indicate the host os/architecture/libc.

    Can also be specified using the MULTITARGET environment variable.
    """
    def __init__(self, spec_string):
        spec = spec_string.split('-')
        def _get(idx, default):
            if spec[idx] == 'default':
                return default
            else:
                return spec[idx]
        self.os = _get(0, default=mx.get_os())
        self.arch = _get(1, default=mx.get_arch())
        self.libc = _get(2, default=TargetSpec._default_libc(self.os))
        if len(spec) > 3:
            self.variant = spec[3]
        else:
            self.variant = None

    def __repr__(self):
        ret = f"{self.os}-{self.arch}-{self.libc}"
        if self.variant is not None:
            ret = f"{ret}-{self.variant}"
        return ret

    def matches(self, target_spec):
        def _match(attribute):
            selector = getattr(self, attribute)
            if selector == '*':
                return True
            else:
                return selector == getattr(target_spec, attribute)
        return _match('os') and _match('arch') and _match('libc') and _match('variant')

    _global = None
    _extra = []

    @classmethod
    def parse_args(cls, opts):
        cmdline = opts.multitarget or []
        env = mx.get_env('MULTITARGET')
        if env:
            cmdline += [env]
        cls._global = [TargetSelection(target) for arg in cmdline for target in arg.split(',')]

    @classmethod
    def add_extra(cls, target):
        cls._extra.append(TargetSelection(target))

    @classmethod
    def get_selection(cls, always=None):
        ret = cls._global or [TargetSelection('default-default-default')]
        if always:
            ret = ret + always
        return ret + cls._extra

class Target(object):
    def __init__(self, spec):
        self.spec = spec
        self.toolchains = {}

    def add_toolchain(self, t):
        toolchains = self.toolchains.setdefault(t.spec.kind, {})
        if t.spec.compiler in toolchains:
            other = toolchains[t.spec.compiler]
            mx.abort(f"Error: Compiler '{t.spec.compiler}' declared twice for {self.spec.name}: {t.toolchain_dist} and {other.toolchain_dist}")
        toolchains[t.spec.compiler] = t

    _registry = {}

    @classmethod
    def get(cls, spec):
        ret = cls._registry.get(spec.name)
        if ret is None:
            ret = Target(spec)
            cls._registry[spec.name] = ret
        return ret

    @classmethod
    def selected(cls, selections):
        for target in cls._registry.values():
            if any((s.matches(target.spec) for s in selections)):
                yield target

class Toolchain(object):
    """A native toolchain for multitarget projects.

    A native toolchain is created by adding the `native_toolchain` property to a distribution.
    See ToolchainSpec for the possible attributes of the `native_toolchain` property.
    """
    def __init__(self, toolchain_dist):
        self.toolchain_dist = toolchain_dist
        if hasattr(toolchain_dist, 'native_toolchain'):
            spec = toolchain_dist.native_toolchain
        else:
            # This is an explicitly selected toolchain distribution that doesn't declare its target.
            # For backwards compatibility, assume it is a ninja toolchain for the host target.
            spec = {'kind': 'ninja', 'target': {}, 'compiler': 'unknown'}
        self.spec = ToolchainSpec(spec)

    def __repr__(self):
        return self.toolchain_dist.__repr__()

    @property
    def target(self):
        return self.spec.name

    def get_path(self):
        return self.toolchain_dist.get_output()

    @classmethod
    def register(cls, toolchain_dist):
        t = Toolchain(toolchain_dist)
        target = Target.get(t.spec.target)
        target.add_toolchain(t)

class Ninja(object):
    """Encapsulates access to Ninja (ninja).

    Abstracts the operations of the Ninja build system that are necessary for
    the NinjaBuildTask to build a NinjaProject.
    """
    binary = 'ninja'
    default_manifest = 'build.ninja'

    def __init__(self, build_dir, parallelism, targets=None):
        self.build_dir = build_dir
        self.parallelism = str(parallelism)
        self.targets = targets or []

    def needs_build(self):
        out = mx.LinesOutputCapture()
        details = mx.LinesOutputCapture()

        self._run('-n', '-d', 'explain', *self.targets, out=out, err=details)
        if details.lines:
            if out.lines and out.lines[0] == "ninja: no work to do.":
                mx.logv("Despite presumed dirty or modified files, ninja has nothing to do.")
                return False, out.lines[0]
            return True, [l for l in details.lines if l.startswith('ninja explain:')][0]
        else:
            assert out.lines == ['ninja: no work to do.']
            return False, out.lines[0]

    def compdb(self, out):
        self._run('-t', 'compdb', *self.targets, out=out)

    def build(self):
        self._run(*self.targets)

    def clean(self):
        self._run('-t', 'clean', *self.targets)

    def _run(self, *args, **kwargs):
        cmd = [self.binary, '-j', self.parallelism]
        mx_verbose_env = mx.get_env('MX_VERBOSE', None)
        if mx.get_opts().very_verbose or mx_verbose_env:
            cmd += ['-v']
        cmd += args

        out = kwargs.get('out')
        err = kwargs.get('err')
        verbose = mx.get_opts().verbose or mx_verbose_env
        if verbose:
            if callable(out) and '-n' not in args:
                out = mx.TeeOutputCapture(out)
            if callable(err):
                err = mx.TeeOutputCapture(err)
        if out is None:
            out = lambda msg: mx.log(msg, important=False)
        if err is None:
            err = lambda msg: mx.log(msg, important=True)

        rc = mx.run(cmd, nonZeroIsFatal=False, out=out, err=err, cwd=self.build_dir)
        if rc:
            mx.abort(rc)


class NativeDependency(mx.Dependency):
    """A Dependency that can be included and linked in when building native projects.

    Attributes
        include_dirs : iterable of str
            Directories with headers provided by this dependency.
        libs : iterable of str
            Libraries provided by this dependency.
    """
    include_dirs = ()
    libs = ()

class MultitargetNativeDependency(NativeDependency):

    libs = property(lambda self: self.target_libs(TargetSpec({})))

    def target_libs(self, target):
        return []

    @classmethod
    def _get_libs(cls, dep, target):
        if isinstance(dep, MultitargetNativeDependency):
            return dep.target_libs(target)
        elif isinstance(dep, NativeDependency):
            return dep.libs
        else:
            return []


class MultitargetProject(mx.AbstractNativeProject, MultitargetNativeDependency):
    """A Project containing native code that can be built for multiple targets.

    Attributes
        multitarget : list of MultitargetSpec, optional
            Targets for which this project can be built.

            If present, the target specific results for each target architecture are in
            a separate subdir of the archive. Otherwise, the archivable results for
            the host architecture are at the root of the archive.

            The subdirectory name contains all components of the target that are specified, in
            the form "os-arch/libc-variant". If a target component is not specified, that component
            is also skipped in the subdirectory name.
        toolchain : str, optional
            Toolchain distribution for building this project.
            Only one of multitarget or toolchain can be specified.
        default_targets : list of str, optional
            The default targets to build for this project if the --multitarget argument
            is not specified.
            Defaults to the host target only.
        always_build_targets : list of str, optional
            The targets that should be always built, regardless of the --multitarget argument.
    """

    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, ignore=False, **kwargs):
        mt_spec = kwargs.pop('multitarget', None)
        self._ignore = ignore
        self._multitarget = bool(mt_spec)  # remember whether we need to put stuff in target-specific subdirs
        self._multitarget_spec = MultitargetSpec.get(mt_spec)
        self._explicit_toolchain = kwargs.pop('toolchain', None)
        if self._multitarget and self._explicit_toolchain:
            mx.abort(f"Can not have an explicitly specified toolchain in multitarget project {self}!")
        self._default_targets = [TargetSelection(s) for s in kwargs.pop('default_targets', ['default-default-default'])]
        self._always_build_targets = [TargetSelection(s) for s in kwargs.pop('always_build_targets', [])]
        self._toolchains = None  # lazy init
        super(MultitargetProject, self).__init__(suite, name, subDir, srcDirs, deps, workingSets, d, **kwargs)
        self.out_dir = self.get_output_root()

    @property
    def toolchain_kind(self):
        return None

    def _toolchain_for_target(self, target):
        toolchains = target.toolchains[self.toolchain_kind]
        def _first_matching_compiler():
            for mt_spec in self._multitarget_spec:
                if mt_spec.matches(target.spec):
                    for c in mt_spec.compiler:
                        if c == "*":
                            for c1 in toolchains:
                                return toolchains[c1]
                        elif c in toolchains:
                            return toolchains.get(c)
            return None
        ret = _first_matching_compiler()
        if ret:
            yield ret

    def _toolchains_for_selection(self, selection):
        return [toolchain for target in Target.selected(selection) for toolchain in self._toolchain_for_target(target)]

    @property
    def toolchains(self):
        if self._toolchains is None:
            if self._explicit_toolchain:
                self._toolchains = [self._explicit_toolchain]
            elif self.toolchain_kind is None:
                # subclass that doesn't support multitarget yet
                self._toolchains = []
            else:
                selected_targets = TargetSelection.get_selection(always=self._always_build_targets)
                mx.logv(f"Selected targets for {self}: {selected_targets}")
                selected_toolchains = self._toolchains_for_selection(selected_targets)
                if len(selected_toolchains) == 0:
                    mx.logv(f"No toolchains selected for {self}, using default {self._default_targets}")
                    selected_toolchains = self._toolchains_for_selection(self._default_targets)
                self._toolchains = selected_toolchains
                mx.logv(f"Selected toolchains for {self}: {self._toolchains}")
            if len(self._toolchains) > 1:
                assert self._multitarget, "more than one toolchain even though this is not a multitarget project?"
        return self._toolchains

    @property
    def ignore(self):
        if self.toolchain_kind is not None and len(self.toolchains) == 0:
            return f"no toolchains selected for {self} -- ignoring"
        else:
            return self._ignore

    @ignore.setter
    def ignore(self, ignore):
        self._ignore = ignore

    def getBuildTask(self, args):
        if self.toolchain_kind:
            if len(self.toolchains) == 1:
                t = self.toolchains[0]
                return self._build_task(t.spec.target.name, args, toolchain=t)
            else:
                class MultitargetBuildTask(tasks.Buildable, tasks.TaskSequence):
                    subtasks = [self._build_task(toolchain.spec.target.name, args, toolchain=toolchain) for toolchain in self.toolchains]

                    def execute(self):
                        super(MultitargetBuildTask, self).execute()
                        self.built = any(t.built for t in self.subtasks)

                    def newestOutput(self):
                        return mx.TimeStampFile.newest(t.newestOutput().path for t in self.subtasks)

                    def cleanForbidden(self):
                        return False

                    def logClean(self) -> None:
                        self.log(f'Cleaning {self.name}...')

                    def clean(self, forBuild=False):
                        for t in self.subtasks:
                            t.clean(forBuild=forBuild)

                return MultitargetBuildTask(self, args)
        else:
            # subclass that doesn't support multitarget, mimic old behavior
            return self._build_task(mx.get_arch(), args)

    @abc.abstractmethod
    def _build_task(self, target_arch, args, toolchain=None):
        """:rtype: TargetArchBuildTask"""

    def resolveDeps(self):
        super(MultitargetProject, self).resolveDeps()
        if self._explicit_toolchain:
            self._explicit_toolchain = Toolchain(mx.distribution(self._explicit_toolchain, context=self))
        self.buildDependencies += [t.toolchain_dist for t in self.toolchains]

    def getArchivableResults(self, use_relpath=True, single=False):
        if self._multitarget:
            if single:
                raise ValueError("single not supported")
            for toolchain in self.toolchains:
                subdir = toolchain.spec.target.subdir
                for file_path, archive_path in self._archivable_results(subdir, use_relpath, single):
                    yield file_path, os.path.join(subdir, archive_path)
        elif self.toolchain_kind:
            assert len(self.toolchains) == 1
            yield from self._archivable_results(self.toolchains[0].spec.target.subdir, use_relpath, single)
        else:
            # subclass that doesn't support multitarget yet, default to old directory layout
            yield from self._archivable_results(mx.get_arch(), use_relpath, single)
        if not single:
            yield from self._archivable_results_no_arch(use_relpath)

    def _archivable_result(self, use_relpath, base_dir, file_path):
        assert not os.path.isabs(file_path)
        archive_path = file_path if use_relpath else os.path.basename(file_path)
        return os.path.join(base_dir, file_path), archive_path

    @abc.abstractmethod
    def _archivable_results(self, target_arch, use_relpath, single):
        """:rtype: typing.Iterable[(str, str)]"""

    def _archivable_results_no_arch(self, use_relpath):
        """:rtype: typing.Iterable[(str, str)]"""
        yield from ()


class TargetArchBuildTask(mx.AbstractNativeBuildTask):
    def __init__(self, args, project, target_arch=None, toolchain=None):
        self.target_arch = target_arch
        super(TargetArchBuildTask, self).__init__(args, project)
        if toolchain is None:
            self.toolchain = None
            # for backwards compatibility, should happen only on subclasses that don't support multitarget yet
            self.out_dir = os.path.join(self.subject.out_dir, self.target_arch)
        else:
            self.toolchain = toolchain
            self.out_dir = os.path.join(self.subject.out_dir, toolchain.spec.target.subdir)

    @property
    def name(self):
        return f'{super(TargetArchBuildTask, self).name}_{self.target_arch}'

class NinjaProject(MultitargetProject):
    """A MultitargetProject that is built using the Ninja build system.

    What distinguishes Ninja from other build systems is that its input files are
    not meant to be written by hand. Instead, they should be generated, which in
    this case is the responsibility of the NinjaProject subclasses.

    Subclasses are expected to generate an appropriate build manifest using the
    NinjaManifestGenerator.

    Attributes
        cflags : list of str, optional
            Flags used during compilation step.
        ldflags : list of str, optional
            Flags used during linking step.
        ldlibs : list of str, optional
            Flags used during linking step.
        use_jdk_headers : bool, optional
            Whether to add directories with JDK headers to the list of directories
            searched for header files. Default is False.
    """

    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, **kwargs):
        context = 'project ' + name
        self._cflags = mx.Suite._pop_list(kwargs, 'cflags', context)
        self._ldflags = mx.Suite._pop_list(kwargs, 'ldflags', context)
        self._ldlibs = mx.Suite._pop_list(kwargs, 'ldlibs', context)
        self.use_jdk_headers = kwargs.pop('use_jdk_headers', False)
        super(NinjaProject, self).__init__(suite, name, subDir, srcDirs, deps, workingSets, d, **kwargs)

    def isJDKDependent(self):
        """Returns whether this NinjaProject is JDK dependent.

        A NinjaProject is considered to be JDK dependent if it uses JDK headers
        or `<jdk_ver>` substitution in its `cflags` (presumably for conditional
        compilation).
        """
        return self.use_jdk_headers or any('<jdk_ver>' in f for f in self._cflags)

    def resolveDeps(self):
        super(NinjaProject, self).resolveDeps()
        self.buildDependencies += self._ninja_deps
        if self.use_jdk_headers or self.suite.getMxCompatibility().is_using_jdk_headers_implicitly(self):
            self.buildDependencies += [self._jdk_dep]

    @lazy_class_default
    def _ninja_deps(cls):  # pylint: disable=no-self-argument
        deps = []

        try:
            subprocess.check_output(['ninja', '--version'], stderr=subprocess.STDOUT)
        except OSError:
            dep = mx.library('NINJA', False)
            if dep:
                deps.append(dep)
                Ninja.binary = os.path.join(dep.get_path(False), 'ninja')
            else:
                # necessary until GR-13214 is resolved
                mx.warn('Make `ninja` binary available via PATH to build native projects.')

        try:
            import ninja_syntax  # pylint: disable=unused-variable, unused-import
        except ImportError:
            dep = mx.library('NINJA_SYNTAX')
            deps.append(dep)
            module_path = os.path.join(dep.get_path(True), f'ninja_syntax-{dep.version}')
            # note that the import machinery needs this path to exist now, otherwise it will be ignored
            sys.path.append(module_path)

        return deps

    @lazy_class_default
    def _jdk_dep(cls):  # pylint: disable=no-self-argument
        class JavaHome(NativeDependency):
            def __init__(self):
                super(JavaHome, self).__init__(mx.suite('mx'), 'JAVA_HOME', None)
                self.include_dirs = None

            def getBuildTask(self, args):
                # Ensure that the name is set correctly now that JAVA_HOME is definitely configured
                if not self.include_dirs:
                    jdk = _get_target_jdk()
                    self.name = 'JAVA_HOME=' + jdk.home
                    self.include_dirs = jdk.include_dirs
                return mx.NoOpTask(self, args)

            def _walk_deps_visit_edges(self, *args, **kwargs):
                pass

        return JavaHome()

    def _build_task(self, target_arch, args, toolchain=None):
        return NinjaBuildTask(args, self, target_arch, toolchain=toolchain)

    def generate_manifest(self, output_dir, filename):
        """Generates a Ninja manifest used to build this project."""
        mx.abort("Must override either generate_manifest or generate_manifest_for_task.")

    def generate_manifest_for_task(self, task, output_dir, filename):
        self.generate_manifest(output_dir, filename)

    @property
    def cflags(self):
        return self._cflags

    @property
    def ldflags(self):
        return self._ldflags

    @property
    def ldlibs(self):
        return self._ldlibs

    @property
    def source_tree(self):
        return self._source['tree']

    @lazy_default
    def _source(self):
        source_tree = []
        source_files = collections.defaultdict(list)

        for source_dir in self.source_dirs():
            for root, _, files in os.walk(source_dir):
                rel_root = os.path.relpath(root, self.dir)
                source_tree.append(rel_root)

                # group files by extension
                grouping = collections.defaultdict(list)
                for f in files:
                    grouping[os.path.splitext(f)[1]].append(os.path.join(rel_root, f))
                for ext in grouping.keys():
                    source_files[ext] += grouping[ext]

        return dict(tree=source_tree, files=source_files)


class NinjaBuildTask(TargetArchBuildTask):
    default_parallelism = 1
    """
    By default, we disable parallelism per project for the following reasons:
        #. It allows mx to build whole projects in parallel, which works well for
           smallish projects like ours.
        #. It is a safe default in terms of compatibility. Although projects may
           explicitly request greater parallelism, that may not work out of the
           box. In particular, the parallelization of debug builds on Windows may
           require special consideration.
    """

    def __init__(self, args, project, target_arch, ninja_targets=None, **kwArgs):
        super(NinjaBuildTask, self).__init__(args, project, target_arch, **kwArgs)
        cpu_overbooking = getattr(project, "cpu_overbooking", False)
        parallelism = self.parallelism
        if cpu_overbooking:
            parallelism = mx.cpu_count()
        self._reason = None
        self._manifest = os.path.join(self.out_dir, Ninja.default_manifest)
        self.ninja = Ninja(self.out_dir, parallelism, targets=ninja_targets)

    def __str__(self):
        return f'Building {self.name} with Ninja'

    def needsBuild(self, newestInput):
        is_needed, self._reason = super(NinjaBuildTask, self).needsBuild(newestInput)
        if is_needed:
            return True, self._reason

        if not os.path.exists(self._manifest):
            self._reason = 'no build manifest'
            return True, self._reason

        mx.logv(f'Checking whether to build {self.name} with Ninja...')
        is_needed, self._reason = self.ninja.needs_build()
        return is_needed, self._reason

    def newestOutput(self):
        return mx.TimeStampFile.newest([os.path.join(self.out_dir, self.subject._target)])

    def needsGenerateManifest(self):
        return self._reason is None \
                or os.path.basename(self._manifest) in self._reason \
                or 'phony' in self._reason

    def build(self):
        if not os.path.exists(self._manifest) or self.needsGenerateManifest():
            with mx_util.SafeFileCreation(self._manifest) as sfc:
                output_dir = os.path.dirname(sfc.tmpPath)
                tmpfilename = os.path.basename(sfc.tmpPath)
                self.subject.generate_manifest_for_task(self, output_dir, tmpfilename)

                if os.path.exists(self._manifest) \
                        and not filecmp.cmp(self._manifest, sfc.tmpPath, shallow=False):
                    self.ninja.clean()

        with mx_compdb.CompdbCapture(self.subject.suite) as out:
            if out:
                self.ninja.compdb(out=out)
        self.ninja.build()

    def clean(self, forBuild=False):
        if not forBuild:
            try:
                mx.rmtree(self.out_dir)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise

class NinjaManifestGenerator(object):
    """Abstracts the writing of the Ninja build manifest.

    Essentially, this is a wrapper around the `ninja_syntax.Writer` with several
    methods added to make it easier to write a NinjaProject build manifest.

    For more details about Ninja, see https://ninja-build.org/manual.html.
    """

    def __init__(self, project, output_dir, filename, toolchain=None):
        import ninja_syntax
        self.project = project
        self.output_dir = output_dir
        self.toolchain = toolchain
        self.n = ninja_syntax.Writer(open(os.path.join(output_dir, filename), 'w'))  # pylint: disable=invalid-name
        self._generate()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def newline(self):
        self.n.newline()

    def comment(self, text):
        self.n.comment(text)

    def variables(self, **kwargs):
        for key, value in kwargs.items():
            self.n.variable(key, value)
        self.newline()

    def include_dirs(self, dirs):
        def quote(path):
            has_spaces = ' ' in path or ('$project' in path and ' ' in self.project.dir)
            return f'"{path}"' if has_spaces else path

        self.variables(includes=['-I' + quote(self._resolve(d)) for d in dirs])

    def include(self, path):
        import ninja_syntax
        self.n.include(ninja_syntax.escape_path(path))

    def cc(self, source_file):  # pylint: disable=invalid-name
        return self.n.build(self._output(source_file), 'cc', self._resolve(source_file))[0]

    def cxx(self, source_file):
        return self.n.build(self._output(source_file), 'cxx', self._resolve(source_file))[0]

    def asm(self, source_file):
        asm_source = self._resolve(source_file)
        if self.toolchain and getattr(self.toolchain.toolchain_dist, 'asm_requires_cpp', False):
            asm_source = self.n.build(self._output(source_file, '.asm'), 'cpp', asm_source)
        return self.n.build(self._output(source_file), 'asm', asm_source)[0]

    def ar(self, archive, members):  # pylint: disable=invalid-name
        return self.n.build(archive, 'ar', members)[0]

    def link(self, program, files):
        return self.n.build(program, 'link', files)[0]

    def linkxx(self, program, files):
        return self.n.build(program, 'linkxx', files)[0]

    def close(self):
        self.n.close()

    def _output(self, source_file, ext=None):
        if ext is None:
            ext = '.obj' if mx.is_windows() else '.o'
        path = os.path.splitext(source_file)[0] + ext
        if os.path.isabs(path):
            common = os.path.commonpath([path, self.output_dir])
            if common:
                return str(Path(path).relative_to(common))
            (drive, path) = os.path.splitdrive(path)
            assert path.startswith(os.path.sep)
            path = path[1:]  # strip leading /
            if drive:
                path = os.path.join(drive.replace(':', '_'), path)
        return path

    @staticmethod
    def _resolve(path):
        return os.path.join('$project', path)

    def _generate(self):
        self.comment('Generated by mx. Do not edit.')
        self.newline()

        self.variables(ninja_required_version='1.3')

        self.comment('Directories')
        self.variables(project=self.project.dir)

        self._generate_mx_interface()

    def _generate_mx_interface(self):
        def phony(target):
            return self.n.build(self._resolve(target), 'phony')[0]

        self.comment('Manifest dependencies')
        deps = [phony(d) for d in self.project.source_tree]
        deps += [self.project.suite.suite_py()]
        self.newline()

        self.comment('Used by mx to check...')
        self.n.rule('dry_run',
                    command='DRY_RUN $out',
                    generator=True)
        self.newline()

        self.comment('...whether manifest needs to be regenerated')
        self.n.build(Ninja.default_manifest, 'dry_run', implicit=deps)
        self.newline()


class DefaultNativeProject(NinjaProject):
    """A NinjaProject that makes many assumptions when generating a build manifest.

    It is assumed that:
        #. Directory layout is fixed:
            - `include` is a flat subdir containing public headers, and
            - `src` subdir contains sources and private headers.

        #. There is only one deliverable:
            - Kind is the value of the `native` attribute, and
            - Name is the value of the `deliverable` attribute if it is specified,
              otherwise it is derived from the `name` of the project.

        #. All source files are supported and necessary to build the deliverable.

        #. All `include_dirs` and `libs` provided by build dependencies are necessary
           to build the deliverable.

        #. The deliverable and the public headers are intended for distribution.

    Attributes
        native : {'static_lib', 'shared_lib'}
            Kind of the deliverable.

            Depending on the value, the necessary flags will be prepended to `cflags`
            and `ldflags` automatically.
        deliverable : str, optional
            Name of the deliverable. By default, it is derived from the `name` of the
            project.
    """
    include = 'include'
    src = 'src'

    _kinds = dict(
        static_lib=dict(
            target=lambda name: mx.add_lib_prefix(name) + ('.lib' if mx.is_windows() else '.a'),
        ),
        shared_lib=dict(
            target=lambda name: mx.add_lib_suffix(mx.add_lib_prefix(name)),
        ),
        executable=dict(
            target=mx.exe_suffix,
        ),
    )

    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, kind, **kwargs):
        self.deliverable = kwargs.pop('deliverable', name.split('.')[-1])
        if srcDirs:
            mx.abort('"sourceDirs" is not supported for default native projects')
        srcDirs += [self.include, self.src]
        super(DefaultNativeProject, self).__init__(suite, name, subDir, srcDirs, deps, workingSets, d, **kwargs)
        try:
            self._kind = self._kinds[kind]
        except KeyError:
            mx.abort(f'"native" should be one of {list(self._kinds.keys())}, but "{kind}" is given')

        include_dir = os.path.join(self.dir, self.include)
        if next(os.walk(include_dir))[1]:
            mx.abort('include directory must have a flat structure')

        self.include_dirs = [include_dir]
        self.kind = kind

    @property
    def toolchain_kind(self):
        return "ninja"

    def target_libs(self, target):
        if self.kind == 'static_lib':
            yield os.path.join(self.out_dir, target.subdir, self._target)

    def resolveDeps(self):
        super(DefaultNativeProject, self).resolveDeps()
        for t in self.toolchains:
            if not isinstance(t.toolchain_dist, mx.AbstractDistribution) or not t.toolchain_dist.get_output():
                mx.abort(f"Cannot generate manifest: the specified toolchain ({t.toolchain_dist}) must be an AbstractDistribution that returns a value for get_output", context=self)

    @property
    def _target(self):
        return self._kind['target'](self.deliverable)

    @property
    def cflags(self):
        default_cflags = []
        if self._kind == self._kinds['shared_lib']:
            default_cflags += dict(
                windows=['-MD'],
            ).get(mx.get_os(), ['-fPIC'])

        if mx.is_linux() or mx.is_darwin():
            # Do not leak host paths via dwarf debuginfo
            def add_debug_prefix(prefix_dir):
                def quote(path):
                    return f'"{path}"' if ' ' in path else path

                return f'-fdebug-prefix-map={quote(prefix_dir)}={quote(os.path.basename(prefix_dir))}'

            default_cflags += [add_debug_prefix(self.suite.vc_dir)]
            default_cflags += [add_debug_prefix(self.suite.get_output_root())]
            default_cflags += [add_debug_prefix(_get_target_jdk().home)]
            default_cflags += ['-gno-record-gcc-switches']

        return default_cflags + super(DefaultNativeProject, self).cflags

    @property
    def ldflags(self):
        default_ldflags = []
        if self._kind == self._kinds['shared_lib']:
            default_ldflags += dict(
                darwin=['-dynamiclib', '-undefined', 'dynamic_lookup'],
                windows=['-dll'],
            ).get(mx.get_os(), ['-shared', '-fPIC'])

        return default_ldflags + super(DefaultNativeProject, self).ldflags

    @property
    def h_files(self):
        return self._source['files'].get('.h', [])

    @property
    def c_files(self):
        return self._source['files'].get('.c', [])

    @property
    def cxx_files(self):
        return self._source['files'].get('.cc', []) + self._source['files'].get('.cpp', [])

    @property
    def asm_sources(self):
        return self._source['files'].get('.S', [])

    def generate_manifest_for_task(self, task, output_dir, filename):
        unsupported_source_files = list(set(self._source['files'].keys()) - {'.h', '.hpp', '.c', '.cc', '.cpp', '.S', '.swp'})
        if unsupported_source_files:
            mx.abort(f'{unsupported_source_files} source files are not supported by default native projects')

        with NinjaManifestGenerator(self, output_dir, filename, toolchain=task.toolchain) as gen:
            gen.comment("Toolchain configuration")
            gen.include(os.path.join(task.toolchain.get_path(), 'toolchain.ninja'))
            gen.newline()
            gen.variables(cflags=[mx_subst.path_substitutions.substitute(cflag) for cflag in self.cflags])
            if self._kind != self._kinds['static_lib']:
                gen.variables(
                    ldflags=[mx_subst.path_substitutions.substitute(ldflag) for ldflag in self.ldflags],
                    ldlibs=[mx_subst.path_substitutions.substitute(ldlib) for ldlib in self.ldlibs],
                )
            gen.include_dirs(collections.OrderedDict.fromkeys(
                # remove the duplicates while maintaining the ordering
                [os.path.dirname(h_file) for h_file in self.h_files] + list(itertools.chain.from_iterable(
                    getattr(d, 'include_dirs', []) for d in self.buildDependencies))
            ).keys())

            gen.comment('Compiled project sources')
            object_files = [gen.cc(f) for f in self.c_files]
            gen.newline()
            object_files += [gen.cxx(f) for f in self.cxx_files]
            gen.newline()
            object_files += [gen.asm(f) for f in self.asm_sources]
            gen.newline()

            gen.comment('Project deliverable')
            if self._kind == self._kinds['static_lib']:
                gen.ar(self._target, object_files)
            else:
                link = gen.linkxx if self.cxx_files else gen.link
                dep_libs = list(itertools.chain.from_iterable(MultitargetNativeDependency._get_libs(d, target=task.toolchain.spec.target) for d in self.buildDependencies))
                link(self._target, object_files + dep_libs)

    def _archivable_results(self, target_arch, use_relpath, single):
        yield self._archivable_result(use_relpath, os.path.join(self.out_dir, target_arch), self._target)

    def _archivable_results_no_arch(self, use_relpath):
        for header in os.listdir(os.path.join(self.dir, self.include)):
            yield self._archivable_result(use_relpath, self.dir, os.path.join(self.include, header))


class NinjaToolchainTemplate(mx.Project):
    def __init__(self, suite, name, deps, workingSets, theLicense, template, output_file, **kwArgs):
        super(NinjaToolchainTemplate, self).__init__(suite, name, subDir=None, srcDirs=[], deps=deps, workingSets=workingSets, d=suite.dir, theLicense=theLicense, **kwArgs)
        self.template = os.path.join(mx.suite('mx').dir, template)
        self.output_file = os.path.join(self.get_output_base(), output_file)

    def isJDKDependent(self):
        return False

    def getArchivableResults(self, use_relpath=True, single=False):
        out = self.output_file
        yield out, os.path.basename(out)

    def getBuildTask(self, args):
        return NinjaToolchainTemplateBuildTask(self, args)


class NinjaToolchainTemplateBuildTask(mx.BuildTask):
    def __init__(self, subject, args):
        super(NinjaToolchainTemplateBuildTask, self).__init__(subject, args, 1)

    def __str__(self):
        return "Generating " + self.subject.name

    def newestOutput(self):
        return mx.TimeStampFile(self.subject.output_file)

    def needsBuild(self, newestInput):
        sup = super(NinjaToolchainTemplateBuildTask, self).needsBuild(newestInput)
        if sup[0]:
            return sup

        output_file = self.subject.output_file
        if not os.path.exists(output_file):
            return True, output_file + ' does not exist'
        with open(output_file, "r") as f:
            on_disk = f.read()
        if on_disk != self.contents():
            return True, f'the content of {output_file} changed'

        return False, 'up to date'

    def build(self):
        mx_util.ensure_dir_exists(self.subject.get_output_root())
        with open(self.subject.output_file, "w") as f:
            f.write(self.contents())

    def clean(self, forBuild=False):
        output_root = self.subject.get_output_root()
        if os.path.exists(output_root):
            mx.rmtree(output_root)

    def contents(self):
        substitutions = mx_subst.SubstitutionEngine()
        # Windows
        substitutions.register_with_arg('cl', lambda s: getattr(self.args, 'alt_cl', '') or s)
        substitutions.register_with_arg('link', lambda s: getattr(self.args, 'alt_link', '') or s)
        substitutions.register_with_arg('lib', lambda s: getattr(self.args, 'alt_lib', '') or s)
        substitutions.register_with_arg('ml', lambda s: getattr(self.args, 'alt_ml', '') or s)
        # Other platforms
        substitutions.register_with_arg('cc', lambda s: getattr(self.args, 'alt_cc', '') or s)
        substitutions.register_with_arg('cxx', lambda s: getattr(self.args, 'alt_cxx', '') or s)
        substitutions.register_with_arg('ar', lambda s: getattr(self.args, 'alt_ar', '') or s)
        # Common
        substitutions.register_with_arg('cflags', lambda s: getattr(self.args, 'alt_cflags', '') or s)
        substitutions.register_with_arg('cxxflags', lambda s: getattr(self.args, 'alt_cxxflags', '') or s)
        substitutions.register_with_arg('ldflags', lambda s: getattr(self.args, 'alt_ldflags', '') or s)

        with open(self.subject.template, "r") as f:
            template = f.read()

        return substitutions.substitute(template)
