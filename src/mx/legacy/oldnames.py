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

_accessed_set = set()
_undefined_set = set()


def redirect(thismodule, targetmodule):
    global _accessed_set
    global _undefined_set

    import sys

    thismodule = sys.modules[thismodule]
    othermodule = sys.modules[targetmodule]

    class interceptor:
        def __setattr__(self, name, value):
            mem_name = f"{thismodule}.{name}"
            _accessed_set.add(mem_name)
            if hasattr(thismodule):
                target = thismodule
            else:
                target = othermodule
                _undefined_set.add(target)
            setattr(target, name, value)

        def __getattr__(self, name):
            mem_name = f"{thismodule}.{name}"
            _accessed_set.add(mem_name)
            if hasattr(thismodule, name):
                target = thismodule
            else:
                target = othermodule
                _undefined_set.add(mem_name)
            return getattr(target, name)

    sys.modules[thismodule] = interceptor()
