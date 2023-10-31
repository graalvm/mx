#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2023, 2024, Oracle and/or its affiliates. All rights reserved.
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
r"""
helper functions for dealing with paths
"""

import os
import os.path as ospath

from .system import is_windows
from .options import _opts
from .logging import warn
from .. import mx

Path = str

def _safe_path(path: Path):
    """
    If not on Windows, this function returns `path`.
    Otherwise, it return a potentially transformed path that is safe for file operations.
    This works around the MAX_PATH limit on Windows:
    https://msdn.microsoft.com/en-us/library/windows/desktop/aa365247(v=vs.85).aspx#maxpath
    """
    if is_windows():
        if _opts.verbose and '/' in path:
            warn(f"Forward slash in path on windows: {path}")
            import traceback
            traceback.print_stack()
        path = ospath.normpath(path)
        MAX_PATH = 260 # pylint: disable=invalid-name
        path_len = len(path) + 1 # account for trailing NUL
        if ospath.isabs(path) and path_len >= MAX_PATH:
            if path.startswith('\\\\'):
                if path[2:].startswith('?\\'):
                    # if it already has a \\?\ don't do the prefix
                    pass
                else:
                    # Only a UNC path has a double slash prefix.
                    # Replace it with `\\?\UNC\'. For example:
                    #
                    #   \\Mac\Home\mydir
                    #
                    # becomes:
                    #
                    #   \\?\UNC\Mac\Home\mydir
                    #
                    path = '\\\\?\\UNC' + path[1:]
            else:
                path = '\\\\?\\' + path
        path = str(path)
    return path

def lstat(name: Path):
    """
    Wrapper for builtin open function that handles long path names on Windows.
    """
    return os.lstat(_safe_path(name))

def canonicalize(p: Path):
    if mx.is_windows() and p.startswith("\\\\?\\"):
        return p[4:]
    return p

def equal(p1: Path, p2: Path):
    return canonicalize(p1) == canonicalize(p2)
