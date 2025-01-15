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

__all__ = [
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

import subprocess, sys

from .envvars import env_var_to_bool
from .logging import abort, logv


def is_continuous_integration() -> bool:
    return env_var_to_bool("CI") or env_var_to_bool("CONTINUOUS_INTEGRATION")


def is_darwin() -> bool:
    return sys.platform.startswith("darwin")


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_openbsd() -> bool:
    return sys.platform.startswith("openbsd")


def is_sunos() -> bool:
    return sys.platform.startswith("sunos")


def is_windows() -> bool:
    return sys.platform.startswith("win32")


def is_cygwin() -> bool:
    return sys.platform.startswith("cygwin")


def get_os() -> str:
    """
    Get a canonical form of sys.platform.
    """
    if is_darwin():
        return "darwin"
    elif is_linux():
        return "linux"
    elif is_openbsd():
        return "openbsd"
    elif is_sunos():
        return "solaris"
    elif is_windows():
        return "windows"
    elif is_cygwin():
        return "cygwin"
    else:
        return abort("Unknown operating system " + sys.platform)


_os_variant = None


def get_os_variant() -> str:
    global _os_variant
    if _os_variant is None:
        if get_os() == "linux":
            try:
                from .processes import _check_output_str

                proc_output = _check_output_str(["ldd", "--version"], stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                proc_output = e.output

            if proc_output and "musl" in proc_output:
                _os_variant = "musl"
        if _os_variant is None:
            _os_variant = ""
        logv(f"OS variant detected: {_os_variant if _os_variant else 'none'}")
    return _os_variant
