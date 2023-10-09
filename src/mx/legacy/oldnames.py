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

from .._impl import mx
import sys
import traceback
import atexit

# Stores accesses to internal symbols
_internal_accesses = set()
# Whether an exit handler was already installed
_exit_handler_set = False


class ModuleInterceptor:
    def __init__(self, thisname, targetname, allowed_writes):
        self.__dict__["_thisname"] = thisname
        self.__dict__["_targetname"] = targetname
        self.__dict__["_allowed_writes"] = allowed_writes or []
        self.__dict__["_thismodule"] = sys.modules[thisname]
        self.__dict__["_othermodule"] = sys.modules[targetname]

    def __get_target(self, name, is_set: bool):
        if name.startswith("__"):
            return self.__dict__["_thismodule"]

        mem_name = f"{self.__dict__['_thisname']}.{name}"

        if name.startswith("_"):
            _internal_accesses.add(mem_name)

            frame = traceback.extract_stack()[-3]
            mx.warn(
                f"Access to internal symbol detected ({'write' if is_set else 'read'}): {mem_name} at {frame.filename}:{frame.lineno} {frame.line}"
            )

        if is_set:
            if name not in self.__dict__["_allowed_writes"]:
                traceback.print_stack()
                mx.abort(f"Disallowed write to {mem_name}")

        return self.__dict__["_othermodule"]

    def __setattr__(self, name, value):
        target = self.__get_target(name, True)
        setattr(target, name, value)

    def __getattr__(self, name):
        target = self.__get_target(name, False)
        return getattr(target, name)


def redirect(thisname: str, allowed_writes: [str] = None):
    global _exit_handler_set
    """
    Redirects all attribute accesses on the ``thisname`` module to the
    ``mx._impl.{thisname}`` module.

    The only exception are builtins (names starting with two underscores).

    Produces warnings for accesses to internal symbols (which should not be accessed from outside)

    Produces errors for writes to symbols (we should not rely on setting arbitrary symbols from the outside) that are
    not explicitly allowed in ``allowed_writes``.

    At the end (using an exit handler), the final list of these symbols are produced.

    :param: allowed_writes: List of symbols that are allowed to be set. All other assignments will produce an error.
    """

    sys.modules[thisname] = ModuleInterceptor(thisname, "mx._impl." + thisname, allowed_writes)

    def exit_handler():
        if _internal_accesses:
            mx.warn(f"The following internal mx symbols were accessed: {', '.join(_internal_accesses)}")

    if not _exit_handler_set:
        atexit.register(exit_handler)
        _exit_handler_set = True
