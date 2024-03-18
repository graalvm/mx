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

from abc import abstractmethod
from typing import Sequence

from .task import Args, Dependency, Task

__all__ = ["TaskSequence"]

class TaskSequence(Task):
    """A Task that executes a sequence of subtasks."""

    def __init__(self, subject: Dependency, args: Args) -> None:
        super(TaskSequence, self).__init__(subject, args, max(t.parallelism for t in self.subtasks))

    def __str__(self) -> str:
        def indent(s, padding='  '):
            return padding + s.replace('\n', '\n' + padding)

        return self.__class__.__name__ + '[\n' + indent('\n'.join(map(str, self.subtasks))) + '\n]'

    @property
    @abstractmethod
    def subtasks(self) -> Sequence[Task]:
        pass

    def execute(self) -> None:
        for subtask in self.subtasks:
            assert subtask.subject == self.subject
            subtask.deps += self.deps
            subtask.execute()
