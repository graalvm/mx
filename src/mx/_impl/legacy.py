#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2023, 2023, Oracle and/or its affiliates. All rights reserved.
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
r"""
This module reconstructs the old mx.py structure.
"""

# pylint: disable=unused-import

__all__ = []

__all__ += ["Daemon"]
from .build.daemon import Daemon

__all__ += ["Dependency", "SuiteConstituent"]
from .build.suite import Dependency, SuiteConstituent

__all__ += ["Buildable", "BuildTask", "NoOpTask", "Task", "TaskSequence"]
from .build.tasks import Buildable, BuildTask, NoOpTask, Task, TaskSequence

__all__ += [
    "check_get_env",
    "env_var_to_bool",
    "get_env",
    "str_to_bool",
]
from .support.envvars import check_get_env, env_var_to_bool, get_env, str_to_bool

__all__ += ["compare", "Comparable"]
from .support.comparable import compare, Comparable

__all__ += [
    "abort",
    "abort_or_warn",
    "colorize",
    "log",
    "logv",
    "logvv",
    "log_error",
    "log_deprecation",
    "nyi",
    "warn",
]
from .support.logging import (
    abort,
    abort_or_warn,
    colorize,
    log,
    logv,
    logvv,
    log_error,
    log_deprecation,
    nyi,
    warn,
)

__all__ += ["waitOn"]
from .support.processes import waitOn

__all__ += [
    "lstat",
]
from .support.path import lstat

__all__ += ["ERROR_TIMEOUT", "terminate_subprocesses"]
from .support.processes import ERROR_TIMEOUT, terminate_subprocesses

__all__ += [
    "get_os",
    "get_os_variant",
    "is_continuous_integration",
    "is_darwin",
    "is_linux",
    "is_openbsd",
    "is_sunos",
    "is_windows",
    "is_cygwin",
]
from .support.system import (
    get_os,
    get_os_variant,
    is_continuous_integration,
    is_darwin,
    is_linux,
    is_openbsd,
    is_sunos,
    is_windows,
    is_cygwin,
)

__all__ += ["TimeStampFile"]
from .support.timestampfile import TimeStampFile
