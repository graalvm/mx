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

from typing import Any, Callable, TypeVar, Union


def compare(a, b):
    """
    Support for comparing objects given removal of `cmp` function in Python 3.
    https://portingguide.readthedocs.io/en/latest/comparisons.html
    """
    return (a > b) - (a < b)


Ty = TypeVar("Ty")

ComparisonResult = Union[int, type(NotImplemented)]


class Comparable(object):
    def _checked_cmp(self, other, f: Callable[[Any, Any], Ty]) -> Ty:
        compar = self.__cmp__(other)  # pylint: disable=assignment-from-no-return
        return f(compar, 0) if compar is not NotImplemented else f(compare(id(self), id(other)), 0)

    def __lt__(self, other: Any) -> bool:
        return self._checked_cmp(other, lambda a, b: a < b)

    def __gt__(self, other: Any) -> bool:
        return self._checked_cmp(other, lambda a, b: a > b)

    def __eq__(self, other: Any) -> bool:
        return self._checked_cmp(other, lambda a, b: a == b)

    def __le__(self, other: Any) -> bool:
        return self._checked_cmp(other, lambda a, b: a <= b)

    def __ge__(self, other: Any) -> bool:
        return self._checked_cmp(other, lambda a, b: a >= b)

    def __ne__(self, other: Any) -> bool:
        return self._checked_cmp(other, lambda a, b: a != b)

    def __cmp__(self, other: Any) -> ComparisonResult:  # to override
        raise TypeError("No override for compare")
