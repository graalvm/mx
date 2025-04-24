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

__all__ = [
    "CMakeNinjaProject",
    "CMakeNinjaBuildTask",
]

import os
import shutil
import errno

from . import mx, mx_util
from . import mx_native
from . import mx_subst


class CMakeNinjaProject(mx_native.NinjaProject):  # pylint: disable=too-many-ancestors
    """A CMake project that is built using Ninja.

    Attributes
        ninja_targets: list of str, optional
            Targets that should be built using Ninja
        ninja_install_targets: list of str, optional
            Targets that should be executed after a successful build. In contrast to `ninja_targets`, the `ninja_install_targets`
            are not considered when deciding whether a project needs to be rebuilt. This is needed because `install`
            targets created by CMake are often executed unconditionally, which would cause the project to be always
            rebuilt.
        cmakeConfig: dict, optional
            Additional arguments passed to CMake in the form '-D{key}={value}'.
            Path substitution is performed on the values.
        cmakePreset: str, optional
            The CMake preset to use.
        cmakeSubdir: str, optional
            Subdirectory of sourceDir that contains the CMakeLists.txt. If omitted, CMakeLists.txt is assumed to be in sourceDir.
        symlinkSource: bool, optional
            Whether to symlink the source directory next to the build directory. This may be necessary to work around problems with
            long paths on Windows.
    """
    def __init__(self, suite, name, deps, workingSets, subDir, ninja_targets=None, ninja_install_targets=None,
                 cmake_show_warnings=True, results=None, output=None, **args):
        projectDir = args.pop('dir', None)
        self._cmake_toolchain = args.pop('toolchain', None)
        self._cmake_subdir = args.pop('cmakeSubdir', None)
        self._symlink_source = args.pop('symlinkSource', False)
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
        extraBuildDeps = []
        srcDir = mx_subst.path_substitutions.substitute(srcDir, resolve=False, collectDeps=extraBuildDeps)
        self._install_targets = [mx_subst.path_substitutions.substitute(x, resolve=False, collectDeps=extraBuildDeps) for x in ninja_install_targets or []]
        self._ninja_targets = [mx_subst.path_substitutions.substitute(x, resolve=False, collectDeps=extraBuildDeps) for x in ninja_targets or []]
        super(CMakeNinjaProject, self).__init__(suite, name, subDir, [srcDir], deps, workingSets, d, results=results, output=output, **args)
        self.silent = not cmake_show_warnings
        self._cmake_config_raw = args.pop('cmakeConfig', {})
        self._cmake_preset = args.pop('cmakePreset', None)
        self.buildDependencies += extraBuildDeps
        if self._cmake_toolchain:
            self.buildDependencies += [self._cmake_toolchain]

    @property
    def toolchain_kind(self):
        return "cmake" if self._multitarget else None

    def resolveDeps(self):
        super(CMakeNinjaProject, self).resolveDeps()
        self._cmake_toolchain = mx.distribution(self._cmake_toolchain, context=self) if self._cmake_toolchain else None
        if self._cmake_toolchain and (not isinstance(self._cmake_toolchain, mx.AbstractDistribution) or not self._cmake_toolchain.get_output()):
            mx.abort(f"Cannot generate manifest: the specified toolchain ({self._cmake_toolchain}) must be an AbstractDistribution that returns a value for get_output", context=self)

    @staticmethod
    def config_entry(key, value):
        value_substitute = mx_subst.path_substitutions.substitute(value)
        if mx.is_windows():
            # cmake does not like backslashes
            value_substitute = value_substitute.replace("\\", "/")
        return f'-D{key}={value_substitute}'

    @staticmethod
    def check_cmake():
        try:
            CMakeNinjaProject.run_cmake(["--version"], silent=False, nonZeroIsFatal=False)
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

    def _toolchain_config(self):
        return {"CMAKE_TOOLCHAIN_FILE": os.path.join(tc.get_output(), 'cmake', 'toolchain.cmake') for tc in [self._cmake_toolchain] if tc}

    def cmake_config(self):
        cfgArgs = [CMakeNinjaProject.config_entry(k, v) for k, v in sorted({**self._cmake_config_raw, **self._toolchain_config()}.items())]
        if self._cmake_preset:
            cfgArgs = ["--preset", self._cmake_preset] + cfgArgs
        return cfgArgs

    def sourceDir(self, create=False):
        src_dir = self.source_dirs()[0]
        if self._symlink_source:
            src_link = os.path.join(self.out_dir, 'src')

            if create:
                def checklink():
                    target = os.readlink(src_link)
                    return os.path.samefile(src_dir, target)

                def mklink():
                    try:
                        os.symlink(src_dir, src_link)
                    except OSError:
                        if os.path.lexists(src_link) and checklink():
                            # assume another thread racily created the same link
                            pass
                        else:
                            raise

                if not os.path.exists(src_link):
                    mklink()
                elif os.path.islink(src_link):
                    if not checklink():
                        # update outdated source symlink (e.g. change in suite.py)
                        os.unlink(src_link)
                        mklink()
                else:
                    mx.abort(f"{src_link} already exists and is not a symlink!")

            return src_link
        return src_dir

    def generate_manifest_for_task(self, task, output_dir, filename):
        extra_cmake_config = []
        if task.toolchain:
            extra_cmake_config.append("-DCMAKE_TOOLCHAIN_FILE=" + os.path.join(task.toolchain.get_path(), "toolchain.cmake"))
        self.generate_manifest(output_dir, filename, extra_cmake_config=extra_cmake_config)

    def generate_manifest(self, output_dir, filename, extra_cmake_config=None):
        source_dir = self.sourceDir(create=True)
        if self._cmake_subdir:
            source_dir = os.path.join(source_dir, self._cmake_subdir)
        cmakefile = os.path.join(output_dir, 'CMakeCache.txt')
        if os.path.exists(cmakefile):
            # remove cache file if it exist
            os.remove(cmakefile)
        cmake_config = self.cmake_config()
        if extra_cmake_config:
            cmake_config.extend(extra_cmake_config)
        if mx._opts.extra_cmake_arg:
            cmake_config.extend(mx._opts.extra_cmake_arg)
        extra_from_env = mx.get_env('EXTRA_CMAKE_ARGS', None)
        if extra_from_env:
            cmake_config.extend(extra_from_env.split(' '))

        # explicitly set ninja executable if not on path
        cmake_make_program = 'CMAKE_MAKE_PROGRAM'
        if cmake_make_program not in cmake_config and mx_native.Ninja.binary != 'ninja':
            cmake_config.append(CMakeNinjaProject.config_entry(cmake_make_program, mx_native.Ninja.binary))

        # cmake will always create build.ninja - there is nothing we can do about it ATM

        # Always specify -S and -B explicitly to override settings from presets. This is for compatibility
        # with CMake 3.20, in this version the "binaryDir" attribute in presets is mandatory.
        cmdline = ["-G", "Ninja", "-S", source_dir, "-B", output_dir] + cmake_config

        CMakeNinjaProject.check_cmake()
        CMakeNinjaProject.run_cmake(cmdline, silent=self.silent, cwd=output_dir, log_error=True)
        # move the build.ninja to the temporary path (just move it back later ... *sigh*)
        path = os.path.join(output_dir, filename)
        shutil.copyfile(os.path.join(output_dir, mx_native.Ninja.default_manifest), path)
        return True

    def _build_task(self, target_arch, args, toolchain=None):
        return CMakeNinjaBuildTask(args, self, target_arch, self._ninja_targets, toolchain=toolchain)

    def getResults(self, replaceVar=mx_subst.results_substitutions):
        return [mx_subst.as_engine(replaceVar).substitute(rt, dependency=self) for rt in self.results]

    def _archivable_results(self, target_arch, use_relpath, single):
        out_dir_arch = os.path.join(self.out_dir, target_arch)
        for _result in self.getResults():
            yield self._archivable_result(use_relpath, out_dir_arch, _result)

class CMakeNinjaBuildTask(mx_native.NinjaBuildTask):
    """A build task which executes Ninja on a project configured by CMake."""
    def __init__(self, args, project, *otherargs, **kwargs):
        super(CMakeNinjaBuildTask, self).__init__(args, project, *otherargs, **kwargs)
        self._cmake_config_file = os.path.join(project.suite.get_mx_output_dir(), 'cmakeConfig',
                                               mx.get_os() + '-' + mx.get_arch() if project.isPlatformDependent() else '',
                                               type(project).__name__,
                                               project._extra_artifact_discriminant(),
                                               self.name)

    def needsBuild(self, newestInput):
        mx.logv(f'Checking whether to reconfigure {self.subject.name} with CMake')
        need_configure, reason = self._need_configure()
        if need_configure:
            return need_configure, f"reconfigure needed by CMake ({reason})"
        return super(CMakeNinjaBuildTask, self).needsBuild(newestInput)

    def build(self):
        super(CMakeNinjaBuildTask, self).build()
        # write guard file
        source_dir = self.subject.sourceDir()
        self._write_guard(source_dir, self.subject.cmake_config())
        # call install targets
        if self.subject._install_targets:
            self.ninja._run(*self.subject._install_targets)

    def newestOutput(self):
        return mx.TimeStampFile.newest([_path for _path, _ in self.subject.getArchivableResults()])

    def _write_guard(self, source_dir, cmake_config):
        with mx_util.SafeFileCreation(self.guard_file()) as sfc:
            with open(sfc.tmpPath, 'w') as fp:
                fp.write(self._guard_data(source_dir, cmake_config))

    def _guard_data(self, source_dir, cmake_config):
        return source_dir + '\n' + '\n'.join(cmake_config)

    def _need_configure(self):
        source_dir = self.subject.sourceDir()
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

    def clean(self, forBuild=False):
        super().clean(forBuild=forBuild)
        if not forBuild:
            src_link = os.path.join(self.subject.out_dir, 'src')
            if os.path.lexists(src_link):
                try:
                    os.unlink(src_link)
                except OSError as e:
                    if e.errno != errno.ENOENT:
                        raise
