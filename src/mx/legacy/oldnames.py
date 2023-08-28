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

# Stores accesses to internal symbols
_internal_accesses = set()
# Sotres writes to non-internal symbols
_settattrs = set()
# Whether an exit handler was already installed
_exit_handler_set = False


def redirect(thisname: str, targetname: str, capture_writes: bool = True):
    global _exit_handler_set
    """
    Redirects all attribute accesses on the ``thisname`` module to the
    ``targetname`` module.

    The only exception are builtins (names starting with two underscores).

    Produces warnings for accesses to internal symbols (which should not be accessed from outside)
    and writes to non-internal symbols (we should not rely on setting arbitrary symbols from the outside).

    At the end (using an exit handler), the final list of these symbols are produced.

    :param capture_writes: Whether writes to non-internal symbols should be captured and reported, defaults to True
    """
    import sys
    from .. import mx

    thismodule = sys.modules[thisname]
    othermodule = sys.modules[targetname]

    class interceptor:
        def __get_target(self, name, is_set: bool):
            if name.startswith("__"):
                return thismodule

            mem_name = f"{thisname}.{name}"
            if name.startswith("_"):
                _internal_accesses.add(mem_name)
                import traceback

                frame = traceback.extract_stack()[-3]
                mx.warn(
                    f"Access to internal symbol detected: {mem_name} at {frame.filename}:{frame.lineno} {frame.line}"
                )
            elif is_set and capture_writes:
                _settattrs.add(mem_name)
                import traceback

                frame = traceback.extract_stack()[-3]
                mx.warn(f"Write to symbol detected: {mem_name} at {frame.filename}:{frame.lineno} {frame.line}")

            return othermodule

        def __setattr__(self, name, value):
            target = self.__get_target(name, True)
            setattr(target, name, value)

        def __getattr__(self, name):
            target = self.__get_target(name, False)
            return getattr(target, name)

    sys.modules[thisname] = interceptor()

    def exit_handler():
        if _internal_accesses:
            mx.warn(f"The following internal mx symbols were accessed: {', '.join(_internal_accesses)}")
        if _settattrs:
            mx.warn(f"The following mx symbols were overwritten: {', '.join(_settattrs)}")

    if not _exit_handler_set:
        import atexit

        atexit.register(exit_handler)
        _exit_handler_set = True
