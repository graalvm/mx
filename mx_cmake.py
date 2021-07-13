# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2021, 2021, Oracle and/or its affiliates. All rights reserved.
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
import shutil

import mx
import mx_native
import mx_subst


class CMakeSupport(object):
    @staticmethod
    def check_cmake():
        try:
            CMakeSupport.run_cmake(["--version"], silent=False, nonZeroIsFatal=False)
        except OSError as e:
            mx.abort(str(e) + "\nError executing 'cmake --version'. Are you sure 'cmake' is installed? ")

    @staticmethod
    def run_cmake(cmdline, silent, *args, **kwargs):
        log_error = kwargs.pop("log_error", False)
        if mx._opts.verbose:
            mx.run(["cmake"] + cmdline, *args, **kwargs)
        else:
            with open(os.devnull, 'w') as fnull:
                err = mx.OutputCapture() if silent else None
                try:
                    mx.run(["cmake"] + cmdline, out=fnull, err=err, *args, **kwargs)
                except:
                    if log_error and err and err.data:
                        mx.log_error(err.data)
                    raise


class CMakeBuildTaskMixin(object):

    def __init__(self, args, project, *otherargs, **kwargs):
        super(CMakeBuildTaskMixin, self).__init__(args, project, *otherargs, **kwargs)
        self._cmake_config_file = os.path.join(project.suite.get_mx_output_dir(), 'cmakeConfig',
                                               mx.get_os() + '-' + mx.get_arch() if project.isPlatformDependent() else '',
                                               type(project).__name__,
                                               project._extra_artifact_discriminant(),
                                               self.name)

    def _write_guard(self, source_dir, cmake_config):
        with mx.SafeFileCreation(self.guard_file()) as sfc:
            with open(sfc.tmpPath, 'w') as fp:
                fp.write(self._guard_data(source_dir, cmake_config))

    def _guard_data(self, source_dir, cmake_config):
        return source_dir + '\n' + '\n'.join(cmake_config)

    def _need_configure(self):
        source_dir = self.subject.source_dirs()[0]
        cmake_lists = os.path.join(source_dir, "CMakeLists.txt")
        guard_file = self.guard_file()
        cmake_config = self.subject.cmake_config()
        if not os.path.exists(guard_file):
            return True, "No CMake configuration found - reconfigure"
        if os.path.exists(cmake_lists) and mx.TimeStampFile(cmake_lists).isNewerThan(mx.TimeStampFile(guard_file)):
            return True, cmake_lists + " is newer than the configuration - reconfigure"
        with open(guard_file, 'r') as fp:
            if fp.read() != self._guard_data(source_dir, cmake_config):
                return True, "CMake configuration changed - reconfigure"
            return False, None

    def guard_file(self):
        return self._cmake_config_file


class CMakeBuildTask(CMakeBuildTaskMixin, mx.NativeBuildTask):

    def __str__(self):
        return 'Building {} with CMake'.format(self.subject.name)

    def _build_run_args(self):
        cmdline, cwd, env = super(CMakeBuildTask, self)._build_run_args()

        def _flatten(lst):
            for e in lst:
                if isinstance(e, list):
                    for sub in _flatten(e):
                        yield sub
                else:
                    yield e

        # flatten cmdline to support for multiple make targets
        return list(_flatten(cmdline)), cwd, env

    def build(self):
        # get cwd and env
        self._configure()
        # This is copied from the super call because we want to make it
        # less verbose but calling super does not allow us to do that.
        # super(CMakeBuildTask, self).build()
        cmdline, cwd, env = self._build_run_args()
        if mx._opts.verbose:
            mx.run(cmdline, cwd=cwd, env=env)
        else:
            with open(os.devnull, 'w') as fnull:
                mx.run(cmdline, cwd=cwd, env=env, out=fnull)
        self._newestOutput = None
        # END super(CMakeBuildTask, self).build()
        source_dir = self.subject.source_dirs()[0]
        self._write_guard(source_dir, self.subject.cmake_config())

    def needsBuild(self, newestInput):
        mx.logv('Checking whether to build {} with CMake'.format(self.subject.name))
        need_configure, reason = self._need_configure()
        return need_configure, "rebuild needed by CMake ({})".format(reason)

    def _need_configure(self):
        if not os.path.exists(os.path.join(self.subject.dir, 'Makefile')):
            return True, "No existing Makefile - reconfigure"
        return super(CMakeBuildTask, self)._need_configure()

    def _configure(self, silent=False):
        need_configure, _ = self._need_configure()
        if not need_configure:
            return
        _, cwd, env = self._build_run_args()
        source_dir = self.subject.source_dirs()[0]
        cmakefile = os.path.join(self.subject.dir, 'CMakeCache.txt')
        if os.path.exists(cmakefile):
            # remove cache file if it exist
            os.remove(cmakefile)
        cmdline = ["-G", "Unix Makefiles", source_dir] + self.subject.cmake_config()
        CMakeSupport.check_cmake()
        CMakeSupport.run_cmake(cmdline, silent=silent, cwd=cwd, env=env)
        return True


class CMakeMixin(object):
    @staticmethod
    def config_entry(key, value):
        value_substitute = mx_subst.path_substitutions.substitute(value)
        if mx.is_windows():
            # cmake does not like backslashes
            value_substitute = value_substitute.replace("\\", "/")
        return '-D{}={}'.format(key, value_substitute)

    def __init__(self, *args, **kwargs):
        super(CMakeMixin, self).__init__(*args, **kwargs)
        self._cmake_config_raw = kwargs.pop('cmakeConfig', {})

    def cmake_config(self):
        return [CMakeMixin.config_entry(k, v.replace('{{}}', '$')) for k, v in sorted(self._cmake_config_raw.items())]


class CMakeNinjaBuildTask(CMakeBuildTaskMixin, mx_native.NinjaBuildTask):

    def needsBuild(self, newestInput):
        mx.logv('Checking whether to reconfigure {} with CMake'.format(self.subject.name))
        need_configure, reason = self._need_configure()
        if need_configure:
            return need_configure, "reconfigure needed by CMake ({})".format(reason)
        return super(CMakeNinjaBuildTask, self).needsBuild(newestInput)

    def build(self):
        super(CMakeNinjaBuildTask, self).build()
        # write guard file
        source_dir = self.subject.source_dirs()[0]
        self._write_guard(source_dir, self.subject.cmake_config())
        # call install targets
        if self.subject._install_targets:
            self.ninja._run(*self.subject._install_targets)

    def newestOutput(self):
        return mx.TimeStampFile.newest([_path for _path, _ in self.subject.getArchivableResults()])


class CMakeNinjaProject(CMakeMixin, mx_native.NinjaProject):  # pylint: disable=too-many-ancestors
    """A CMake project that is built using Ninja.

    Attributes
        ninja_targets: list of str, optional
            Targets that should be built using Ninja
        ninja_install_targets: list of str, optional
            Targets that executed after a successful build. In contrast to `ninja_targets`, the `ninja_install_targets`
            are not considered when deciding whether a project needs to be rebuilt. This is needed because `install`
            targets created by CMake are often executed unconditionally, which would cause the project to be always
            rebuilt.
    """
    def __init__(self, suite, name, deps, workingSets, subDir, ninja_targets=None, ninja_install_targets=None,
                 cmake_show_warnings=True, results=None, output=None, **args):
        projectDir = args.pop('dir', None)
        if projectDir:
            d_rel = projectDir
        elif subDir is None:
            d_rel = name
        else:
            d_rel = os.path.join(subDir, name)
        d = os.path.join(suite.dir, d_rel.replace('/', os.sep))
        srcDir = args.pop('sourceDir', d)
        if not srcDir:
            mx.abort("Exactly one 'sourceDir' is required")
        srcDir = mx_subst.path_substitutions.substitute(srcDir)
        self._install_targets = [mx_subst.path_substitutions.substitute(x) for x in ninja_install_targets or []]
        self._ninja_targets = [mx_subst.path_substitutions.substitute(x) for x in ninja_targets or []]
        super(CMakeNinjaProject, self).__init__(suite, name, subDir, [srcDir], deps, workingSets, d, results=results, output=output, **args)
        # self.dir = self.getOutput()
        self.silent = not cmake_show_warnings

    def generate_manifest(self, path, extra_cmake_config=None):
        source_dir = self.source_dirs()[0]
        out_dir = os.path.dirname(path)
        cmakefile = os.path.join(out_dir, 'CMakeCache.txt')
        if os.path.exists(cmakefile):
            # remove cache file if it exist
            os.remove(cmakefile)
        cmake_config = self.cmake_config()
        if extra_cmake_config:
            cmake_config.extend(extra_cmake_config)

        # explicitly set ninja executable if not on path
        cmake_make_program = 'CMAKE_MAKE_PROGRAM'
        if cmake_make_program not in cmake_config and mx_native.Ninja.binary != 'ninja':
            cmake_config.append(CMakeMixin.config_entry(cmake_make_program, mx_native.Ninja.binary))

        # cmake will always create build.ninja - there is nothing we can do about it ATM
        cmdline = ["-G", "Ninja", source_dir] + cmake_config
        CMakeSupport.check_cmake()
        CMakeSupport.run_cmake(cmdline, silent=self.silent, cwd=out_dir, log_error=True)
        # move the build.ninja to the temporary path (just move it back later ... *sigh*)
        shutil.copyfile(os.path.join(out_dir, mx_native.Ninja.default_manifest), path)
        return True

    def _build_task(self, target_arch, args):
        return CMakeNinjaBuildTask(args, self, target_arch, self._ninja_targets)

    def getResults(self, replaceVar=mx_subst.results_substitutions):
        return [mx_subst.as_engine(replaceVar).substitute(rt, dependency=self) for rt in self.results]

    def _archivable_results(self, target_arch, use_relpath, single):
        def result(base_dir, file_path):
            assert not mx.isabs(file_path)
            archive_path = file_path if use_relpath else mx.basename(file_path)
            return mx.join(base_dir, file_path), archive_path

        out_dir_arch = mx.join(self.out_dir, target_arch)
        for _result in self.getResults():
            yield result(out_dir_arch, _result)
