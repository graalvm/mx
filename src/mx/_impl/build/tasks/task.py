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
from abc import ABCMeta, abstractmethod
from argparse import Namespace
from typing import Dict, Optional, MutableSequence

from ..daemon import Daemon
from ..suite import Dependency
from ...support.logging import nyi, setLogTask
from ...support.processes import Process

__all__ = ["Task", "TaskAbortException"]

Args = Namespace

class TaskAbortException(Exception):
    pass

class Task(object, metaclass=ABCMeta):
    """A task executed during a build."""

    subject: Dependency
    deps: MutableSequence[Task]
    args: Args
    parallelism: int
    proc: Optional[Process]

    def __init__(self, subject: Dependency, args: Args, parallelism: int):
        """
        :param subject: the dependency for which this task is executed
        :param args: arguments of the build command
        :param parallelism: the number of CPUs used when executing this task
        """
        self.subject = subject
        self.args = args
        self.parallelism = parallelism
        self.deps = []
        self.proc = None
        self._exitcode = 0

    def __str__(self) -> str:
        return nyi('__str__', self)

    def __repr__(self) -> str:
        return str(self)

    @property
    def name(self) -> str:
        return self.subject.name

    def enter(self):
        setLogTask(self)

    def abort(self, code):
        self._exitcode = code
        raise TaskAbortException(code)

    @property
    def exitcode(self):
        if self._exitcode != 0:
            return self._exitcode
        else:
            return self.proc.exitcode

    @property
    def build_time(self):
        return getattr(self.subject, "build_time", 1)

    def initSharedMemoryState(self) -> None:
        pass

    def pushSharedMemoryState(self) -> None:
        pass

    def pullSharedMemoryState(self) -> None:
        pass

    def cleanSharedMemoryState(self) -> None:
        pass

    def prepare(self, daemons: Dict[str, Daemon]):
        """
        Perform any task initialization that must be done in the main process.
        This will be called just before the task is launched.
        The 'daemons' argument is a dictionary for storing any persistent state
        that might be shared between tasks.
        """

    @abstractmethod
    def execute(self) -> None:
        """Executes this task."""
