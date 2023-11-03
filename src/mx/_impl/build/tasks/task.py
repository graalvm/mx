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

class Task(object, metaclass=ABCMeta):
    """A task executed during a build.

    :type deps: list[Task]
    :param Dependency subject: the dependency for which this task is executed
    :param list[str] args: arguments of the build command
    :param int parallelism: the number of CPUs used when executing this task
    """

    def __init__(self, subject, args, parallelism):
        self.subject = subject
        self.args = args
        self.parallelism = parallelism
        self.deps = []
        self.proc = None

    def __str__(self):
        nyi('__str__', self)

    def __repr__(self):
        return str(self)

    @property
    def name(self):
        return self.subject.name

    @property
    def build_time(self):
        return getattr(self.subject, "build_time", 1)

    def initSharedMemoryState(self):
        pass

    def pushSharedMemoryState(self):
        pass

    def pullSharedMemoryState(self):
        pass

    def cleanSharedMemoryState(self):
        pass

    def prepare(self, daemons):
        """
        Perform any task initialization that must be done in the main process.
        This will be called just before the task is launched.
        The 'daemons' argument is a dictionary for storing any persistent state
        that might be shared between tasks.
        """

    @abstractmethod
    def execute(self):
        """Executes this task."""
