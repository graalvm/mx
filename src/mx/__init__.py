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
"""
The mx package.

Also serves as the proxy file for the original mx module.

DO NOT WRITE IMPLEMENTATION CODE HERE.

See docs/package-structure.md for more details.
"""

# mx exports its own open symbol which redefines a builtin
from ._impl.mx import *  # pylint: disable=redefined-builtin

# import the symbols that have been moved already
from ._impl.legacy import *

# For some reason these private symbols are used externally
from ._impl.support.processes import _addSubprocess, _removeSubprocess
from ._impl.mx import (
    _mx_path,
    _opts,
    _replaceResultsVar,
    _cache_dir,
    _chunk_files_for_command_line,
    _encode,
    _entries_to_classpath,
    _get_dependency_path,
    _missing_dep_message,
    _mx_home,
    _needsUpdate,
    # Only used by tests
    _primary_suite_init,
)

from mx._legacy.oldnames import redirect as _redirect

from ._impl import legacy as _legacy
import mx._impl.mx as _orig

__all__ = []
__all__ += _legacy.__all__
__all__ += _orig.__all__

# Unlike all the modules in oldnames, this module is used for both the legacy
# access and access in the package system to the `mx` module because there is
# no good way to overload the name.
_redirect(
    __name__,
    allowed_internal_reads=[
        "_mx_path",
        "_opts",
        "_replaceResultsVar",
        "_addSubprocess",
        "_cache_dir",
        "_check_global_structures",
        "_chunk_files_for_command_line",
        "_encode",
        "_entries_to_classpath",
        "_get_dependency_path",
        "_missing_dep_message",
        "_mx_home",
        "_mx_suite",
        "_needsUpdate",
        "_removeSubprocess",
        "_primary_suite_init",
    ],
    allowed_writes=["_check_global_structures"],
)
