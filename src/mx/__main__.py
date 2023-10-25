#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2022, Oracle and/or its affiliates. All rights reserved.
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
"""
Entry point for mx shell launchers that will test Python version requirements before
calling mx.py. The latter assumes a compatible python interpreter is being used.
"""
import sys, os

_min_required_version = (3, 8)
_min_required_version_str = f'{".".join((str(d) for d in _min_required_version))}'
if sys.version_info < _min_required_version:
    major, minor, micro, _, _ = sys.version_info
    msg = f"mx requires python {_min_required_version_str}+, not {major}.{minor}.{micro} ({sys.executable})"
    env_exe = os.environ.get("MX_PYTHON", None)
    if env_exe != sys.executable:
        msg += (
            os.linesep + "The path to the Python interpreter can be specified with the MX_PYTHON environment variable."
        )
    raise SystemExit(msg)

from .mx import _main_wrapper

_main_wrapper()
