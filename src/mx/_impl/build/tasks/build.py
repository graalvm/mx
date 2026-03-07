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

from __future__ import annotations

__all__ = [
    "Buildable",
    "BuildTask"
]

import datetime, time, os, sys, json
import multiprocessing.dummy as multiprocessing
from abc import abstractmethod
from os import path
from typing import Optional, Tuple

from mx._impl.support.timestampfile import TimeStampFile

from .task import Args, Dependency, Task
from ...mx_util import SafeFileCreation
from ...support.envvars import get_env
from ...support.logging import abort, log, logv, logvv, nyi, warn
from ...support.options import _opts

class Buildable(object):
    """A mixin for Task subclasses that can be built."""
    built: bool = False
    _builtBox: Optional[multiprocessing.Value] = None

    def initSharedMemoryState(self) -> None:
        self._builtBox = multiprocessing.Value('b', 1 if self.built else 0)

    def pushSharedMemoryState(self) -> None:
        if self._builtBox is None:
            return abort("Shared memory state not initialized")
        self._builtBox.value = 1 if self.built else 0

    def pullSharedMemoryState(self) -> None:
        if self._builtBox is None:
            return abort("Shared memory state not initialized")
        self.built = bool(self._builtBox.value)

    def cleanSharedMemoryState(self) -> None:
        self._builtBox = None

    # @abstractmethod should be abstract but subclasses in some suites miss this method
    def newestOutput(self) -> TimeStampFile | None:
        """
        Gets a TimeStampFile representing the build output file for this task
        with the newest modification time or None if no build output file exists.
        """
        nyi('newestOutput', self)

class BuildTask(Buildable, Task):
    """A Task used to build a dependency."""

    def __init__(self, subject: Dependency, args: Args, parallelism: int):
        super(BuildTask, self).__init__(subject, args, parallelism)
        self._saved_config_path = path.join(subject.suite.get_mx_output_dir(), 'savedConfig', type(subject).__name__,
                                            subject._extra_artifact_discriminant(), self.name)

    def _get_config(self) -> dict:
        """
        Gets the config for this task's subject.
        """
        config = {}
        if self.deps:
            config["deps"] = [d.name for d in self.deps]
        if hasattr(self.subject, "_orig_attrs"):
            config.update(self.subject._orig_attrs)
        return config or None

    def _persist_config(self) -> None:
        """
        Saves the config for this task's subject to a file.
        """
        config = self._get_config()
        if config:
            with SafeFileCreation(self._saved_config_path) as sfc:
                with open(sfc.tmpPath, 'w') as f:
                    json.dump(config, f)
        elif path.exists(self._saved_config_path):
            os.remove(self._saved_config_path)

    def _has_config_changed(self) -> bool:
        """
        Returns True if there is a saved config for this task's subject,
        and it has changed since the last time it was built.
        """
        if path.exists(self._saved_config_path):
            with open(self._saved_config_path) as f:
                old_config = json.load(f)
        else:
            old_config = None
        new_config = self._get_config()
        return old_config != new_config

    def execute(self):
        """
        Execute the build task.
        """
        if self.buildForbidden():
            self.logSkip()
            return
        buildNeeded = False
        reason = "unknown"
        if self.args.clean and not self.cleanForbidden():
            self.logClean()
            self.clean()
            buildNeeded = True
            reason = 'clean'
        if not buildNeeded:
            updated = [dep for dep in self.deps if getattr(dep, 'built', False)]
            if updated:
                buildNeeded = True
                if not _opts.verbose:
                    reason = f'dependency {updated[0].subject} updated'
                else:
                    reason = 'dependencies updated: ' + ', '.join(str(u.subject) for u in updated)
        if not buildNeeded and self._has_config_changed():
            buildNeeded = True
            reason = 'config was changed'
        if not buildNeeded:
            newestInput = None
            newestInputDep = None
            for dep in self.deps:
                depNewestOutput = getattr(dep, 'newestOutput', lambda: None)()
                if depNewestOutput and (not newestInput or depNewestOutput.isNewerThan(newestInput)):
                    newestInput = depNewestOutput
                    newestInputDep = dep
            if newestInputDep:
                logvv(f'Newest dependency for {self.subject.name}: {newestInputDep.subject.name} ({newestInput})')

            if get_env('MX_BUILD_SHALLOW_DEPENDENCY_CHECKS') is None:
                shallow_dependency_checks = self.args.shallow_dependency_checks is True
            else:
                shallow_dependency_checks = get_env('MX_BUILD_SHALLOW_DEPENDENCY_CHECKS') == 'true'
                if self.args.shallow_dependency_checks is not None and shallow_dependency_checks is True:
                    warn('Explicit -s argument to build command is overridden by MX_BUILD_SHALLOW_DEPENDENCY_CHECKS')

            if newestInput and shallow_dependency_checks and not self.subject.isNativeProject():
                newestInput = None
            if __name__ != self.__module__ and not self.subject.suite.getMxCompatibility().newestInputIsTimeStampFile():
                newestInput = newestInput.timestamp if newestInput else float(0)
            buildNeeded, reason = self.needsBuild(newestInput)
        if buildNeeded:
            if not self.args.clean and not self.cleanForbidden():
                self.clean(forBuild=True)
            start_time = time.time()
            self.logBuild(reason)
            try:
                _built = self.build()
            except:
                # In concurrent builds, this helps identify on the console which build failed
                log(self._timestamp() + f"{self}: Failed due to error: {sys.exc_info()[1]}")
                raise
            self._persist_config()
            # The build task is `built` if the `build()` function returns True or None (legacy)
            self.built = _built or _built is None
            self.logBuildDone(time.time() - start_time)
            logv(f'Finished {self}')
        else:
            self.logSkip(reason)

    def _timestamp(self) -> str:
        if self.args.print_timing:
            return time.strftime('[%H:%M:%S] ')
        return ''

    def logBuild(self, reason: Optional[str] = None) -> None:
        timestamp = self._timestamp()
        if self.args.build_logs == 'oneline':
            self.log(f'{timestamp}{self}...', echo=True, log=False)
        if reason:
            self.log(f'{timestamp}{self}... [{reason}]')
        else:
            self.log(f'{timestamp}{self}...')

    def logBuildDone(self, duration: float) -> None:
        timestamp = self._timestamp()
        if timestamp:
            durationStr = str(datetime.timedelta(seconds=duration))
            # Strip hours if 0
            if durationStr.startswith('0:'):
                durationStr = durationStr[2:]
            self.log(f'{timestamp}{self} [duration: {duration}]', echo=True)

    def logClean(self) -> None:
        self.log(f'Cleaning {self.name}...')

    def logSkip(self, reason: Optional[str] = None) -> None:
        self.status = "skipped"
        if reason:
            self.statusInfo = reason
            logv(f'[{reason} - skipping {self.name}]')
        else:
            logv(f'[skipping {self.name}]')

    def needsBuild(self, newestInput: None | float | TimeStampFile) -> Tuple[bool, str]:
        """
        Returns True if the current artifacts of this task are out dated.
        The 'newestInput' argument is either None or a TimeStampFile
        denoting the artifact of a dependency with the most recent modification time.
        Apart from 'newestInput', this method does not inspect this task's dependencies.
        """
        if self.args.force:
            return (True, 'forced build')
        return (False, 'unimplemented')

    def buildForbidden(self) -> bool:
        if not self.args.only:
            return False
        projectNames = self.args.only.split(',')
        return self.subject.name not in projectNames

    def cleanForbidden(self) -> bool:
        return False

    @abstractmethod
    def build(self) -> Optional[bool]:
        """
        Build the artifacts.
        """
        nyi('build', self)

    @abstractmethod
    def clean(self, forBuild: bool = False) -> Optional[bool]:
        """
        Clean the build artifacts.
        """
        nyi('clean', self)
