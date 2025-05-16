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

from __future__ import annotations
from abc import ABCMeta
import os.path
from typing import Any, Optional

from ...support.comparable import ComparisonResult, compare, Comparable

# TODO: Replace with actual type
Suite = Any

class SuiteConstituent(Comparable, metaclass=ABCMeta):
    name: str
    suite: Suite
    build_time: int
    """Expected build time in minutes (Used to schedule parallel jobs efficiently)"""

    internal: bool
    """Should this constituent be visible outside its suite"""

    def __init__(self, suite: Suite, name: str, build_time: int = 1):
        self.name = name
        self.suite = suite
        self.build_time = build_time
        self.internal = False

    def origin(self) -> Optional[tuple[Suite, int]]:
        """
        Gets a 2-tuple (file, line) describing the source file where this constituent
        is defined or None if the location cannot be determined.
        """
        suitepy = self.suite.suite_py()
        if os.path.exists(suitepy):
            import tokenize
            with open(suitepy) as fp:
                candidate = None
                for t in tokenize.generate_tokens(fp.readline):
                    _, tval, (srow, _), _, _ = t
                    if candidate is None:
                        if tval in ('"' + self.name + '"', "'" + self.name + "'"):
                            candidate = srow
                    else:
                        if tval == ':':
                            return (suitepy, srow)
                        else:
                            candidate = None

    def __abort_context__(self) -> str:
        """
        Gets a description of where this constituent was defined in terms of source file
        and line number. If no such description can be generated, None is returned.
        """
        loc = self.origin()
        if loc:
            path, lineNo = loc
            return f'  File "{path}", line {lineNo} in definition of {self.name}'
        return f'  {self.suite.name}:{self.name}'

    def _comparison_key(self) -> tuple[str, Suite]:
        return self.name, self.suite

    def __cmp__(self, other) -> ComparisonResult:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return compare(self._comparison_key(), other._comparison_key())

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._comparison_key() == other._comparison_key()

    def __ne__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._comparison_key() != other._comparison_key()

    def __hash__(self):
        return hash(self._comparison_key())

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name
