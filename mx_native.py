# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2018, 2018, Oracle and/or its affiliates. All rights reserved.
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
import abc
import collections
import errno
import filecmp
import os
import subprocess
import sys

import mx


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


class Ninja(object):
    """Encapsulates access to Ninja (ninja).

    Abstracts the operations of the Ninja build system that are necessary for
    the NinjaBuildTask to build a NinjaProject.
    """
    binary = 'ninja'
    default_manifest = 'build.ninja'

    def __init__(self, build_dir, parallelism):
        self.build_dir = build_dir
        self.parallelism = str(parallelism)

    def needs_build(self):
        out = mx.LinesOutputCapture()
        details = mx.LinesOutputCapture()

        self._run('-n', '-d', 'explain', out=out, err=details)
        if details.lines:
            return True, details.lines[0]
        else:
            assert out.lines == ['ninja: no work to do.']
            return False, out.lines[0]

    def build(self):
        self._run()

    def clean(self):
        self._run('-t', 'clean')

    def _run(self, *args, **kwargs):
        cmd = [self.binary, '-j', self.parallelism]
        if mx.get_opts().very_verbose:
            cmd += ['-v']
        cmd += args

        out = kwargs.get('out', mx.OutputCapture())
        err = kwargs.get('err', subprocess.STDOUT)
        if mx.get_opts().verbose:
            if callable(out) and '-n' not in args:
                out = mx.TeeOutputCapture(out)
            if callable(err):
                err = mx.TeeOutputCapture(err)

        try:
            rc = mx.run(cmd, nonZeroIsFatal=False, out=out, err=err, cwd=self.build_dir)
        except OSError as e:
            if e.errno != errno.EACCES:
                mx.abort('Error executing \'{}\': {}'.format(' '.join(cmd), str(e)))
            mx.logv('{} is not executable. Trying to change permissions...'.format(self.binary))
            os.chmod(self.binary, 0o755)
            self._run(*args, **kwargs)  # retry
        else:
            not rc or mx.abort(rc)  # pylint: disable=expression-not-assigned


class NinjaProject(mx.AbstractNativeProject):
    """A Project containing native code that is built using the Ninja build system.

    What distinguishes Ninja from other build systems is that its input files are
    not meant to be written by hand. Instead, they should be generated, which in
    this case is the responsibility of the NinjaProject subclasses.

    Subclasses are expected to generate an appropriate build manifest using the
    NinjaManifestGenerator.
    """

    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, theLicense, **kwargs):
        context = 'project ' + name
        self.buildDependencies = mx.Suite._pop_list(kwargs, 'buildDependencies', context) + self._ninja_deps
        self.cflags = mx.Suite._pop_list(kwargs, 'cflags', context)
        super(NinjaProject, self).__init__(suite, name, subDir, srcDirs, deps, workingSets, d, theLicense,
                                           **kwargs)
        self.out_dir = self.get_output_root()

    @lazy_class_default
    def _ninja_deps(cls):  # pylint: disable=no-self-argument
        deps = []

        try:
            subprocess.check_output(['ninja', '--version'], stderr=subprocess.STDOUT)
        except OSError:
            dep = mx.library('NINJA')
            deps.append(dep.qualifiedName())
            Ninja.binary = mx.join(dep.get_path(False), 'ninja')

        try:
            import ninja_syntax  # pylint: disable=unused-variable
        except ImportError:
            dep = mx.library('NINJA_SYNTAX')
            deps.append(dep.qualifiedName())
            module_path = mx.join(dep.get_path(False), 'ninja_syntax-{}'.format(dep.version))
            # module_path might not exist yet, so we need to ensure that file system will be used
            sys.path_importer_cache[module_path] = None
            sys.path.append(module_path)

        return deps

    def getBuildTask(self, args):
        return NinjaBuildTask(args, self)

    @abc.abstractmethod
    def generate_manifest(self, path):
        """Generates a Ninja manifest used to build this project."""

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
                    grouping[os.path.splitext(f)[1]].append(mx.join(rel_root, f))
                for ext in grouping.keys():
                    source_files[ext] += grouping[ext]

        return dict(tree=source_tree, files=source_files)


class NinjaBuildTask(mx.AbstractNativeBuildTask):
    def __init__(self, args, project):
        super(NinjaBuildTask, self).__init__(args, project)
        self._reason = None
        self._manifest = mx.join(project.out_dir, Ninja.default_manifest)
        self.ninja = Ninja(project.out_dir, self.parallelism)

    def __str__(self):
        return 'Building {} with Ninja'.format(self.subject.name)

    def needsBuild(self, newestInput):
        if not mx.exists(self._manifest):
            self._reason = 'no build manifest'
            return True, self._reason

        mx.logv('Checking whether to build {} with Ninja...'.format(self.subject.name))

        is_needed, self._reason = self.ninja.needs_build()
        if is_needed:
            return True, self._reason

        is_forced, reason = super(NinjaBuildTask, self).needsBuild(newestInput)
        if is_forced:
            self._reason = reason
            return True, self._reason

        return False, self._reason

    def newestOutput(self):
        return mx.TimeStampFile.newest([mx.join(self.subject.out_dir, self.subject._target)])

    def build(self):
        if not mx.exists(self._manifest) \
                or self._reason is None \
                or mx.basename(self._manifest) in self._reason \
                or 'phony' in self._reason:
            with mx.SafeFileCreation(self._manifest) as sfc:
                self.subject.generate_manifest(sfc.tmpPath)

                if mx.exists(self._manifest) \
                        and not filecmp.cmp(self._manifest, sfc.tmpPath, shallow=False):
                    self.ninja.clean()

        self.ninja.build()

    def clean(self, forBuild=False):
        if not forBuild:
            try:
                mx.rmtree(self.subject.out_dir)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise


class NinjaManifestGenerator(object):
    """Abstracts the writing of the Ninja build manifest.

    Essentially, this is a wrapper around the `ninja_syntax.Writer` with several
    methods added to make it easier to write a NinjaProject build manifest.

    For more details about Ninja, see https://ninja-build.org/manual.html.
    """

    def __init__(self, project, output):
        import ninja_syntax
        self.project = project
        self.n = ninja_syntax.Writer(output)  # pylint: disable=invalid-name
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

    def include(self, dirs):
        self.variables(includes=['-I' + self._resolve(d) for d in dirs])

    def cc_rule(self):
        if mx.get_os() == 'windows':
            command = 'cl -nologo -showIncludes $includes $cflags -c $in -Fo$out'
            depfile = None
            deps = 'msvc'
        else:
            command = 'gcc -MMD -MF $out.d $includes $cflags -c $in -o $out'
            depfile = '$out.d'
            deps = 'gcc'

        self.n.rule('cc',
                    command=command,
                    description='CC $out',
                    depfile=depfile,
                    deps=deps)
        self.newline()

        def build(source_file):
            output = os.path.splitext(source_file)[0] + ('.obj' if mx.get_os() == 'windows' else '.o')
            return self.n.build(output, 'cc', self._resolve(source_file))[0]

        return build

    def ar_rule(self):
        if mx.get_os() == 'windows':
            command = 'lib -nologo -out:$out $in'
        else:
            command = 'ar -rc $out $in'

        self.n.rule('ar',
                    command=command,
                    description='AR $out')
        self.newline()

        return lambda archive, members: self.n.build(archive, 'ar', members)[0]

    def close(self):
        self.n.close()

    @staticmethod
    def _resolve(path):
        return mx.join('$project', path)

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
    include = 'include'
    src = 'src'

    _kinds = dict(
        static_lib=dict(
            target=lambda name: mx.add_lib_prefix(name) + ('.lib' if mx.get_os() == 'windows' else '.a'),
        ),
    )

    def __init__(self, suite, name, subDir, srcDirs, deps, workingSets, d, theLicense, kind, **kwargs):
        if srcDirs:
            mx.abort('"sourceDirs" is not supported for default native projects')
        srcDirs += [self.include, self.src]
        super(DefaultNativeProject, self).__init__(suite, name, subDir, srcDirs, deps, workingSets, d, theLicense,
                                                   **kwargs)
        if next(os.walk(mx.join(self.dir, self.include)))[1]:
            mx.abort('include directory must have a flat structure')
        try:
            self._kind = self._kinds[kind]
        except KeyError:
            mx.abort('"native" should be one of {}, but "{}" is given'.format(self._kinds.keys(), kind))
        self._deliverable = name.split('.')[-1]

    @property
    def _target(self):
        return self._kind['target'](self._deliverable)

    @property
    def c_files(self):
        return self._source['files']['.c']

    @property
    def h_files(self):
        return self._source['files']['.h']

    def generate_manifest(self, path):
        unsupported_files = list(self._source['files'].viewkeys() - {'.c', '.h'})
        if unsupported_files:
            mx.abort('{} files are not supported by default native projects'.format(unsupported_files))

        with NinjaManifestGenerator(self, open(path, 'w')) as gen:
            gen.comment('Project rules')
            cc = gen.cc_rule()
            ar = gen.ar_rule()

            gen.variables(cflags=self.cflags)
            gen.include(collections.OrderedDict.fromkeys([mx.dirname(h_file) for h_file in self.h_files]).keys())

            gen.comment('Compiled project sources')
            object_files = [cc(f) for f in self.c_files]
            gen.newline()

            gen.comment('Project deliverable')
            ar(self._target, object_files)

    def getArchivableResults(self, use_relpath=True, single=False):
        def result(base_dir, file_path):
            assert not mx.isabs(file_path)
            archive_path = file_path if use_relpath else mx.basename(file_path)
            return mx.join(base_dir, file_path), archive_path

        yield result(self.out_dir, self._target)

        if not single:
            for header in os.listdir(mx.join(self.dir, self.include)):
                yield result(self.dir, mx.join(self.include, header))
