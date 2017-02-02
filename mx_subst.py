#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2016, 2016, Oracle and/or its affiliates. All rights reserved.
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

import re
import mx


class SubstitutionEngine(object):
    def __init__(self, chain=None):
        assert chain is None or isinstance(chain, SubstitutionEngine)
        self._chain = chain
        self._subst = {}
        self._hasArg = {}

    def register_with_arg(self, var, function):
        self._subst[var] = function
        self._hasArg[var] = True

    def register_no_arg(self, var, function):
        self._subst[var] = function
        self._hasArg[var] = False

    def _replace(self, m):
        var = m.group(1)
        if var in self._subst:
            fn = self._subst[var]
            if self._hasArg[var]:
                arg = m.group(3)
                return fn(arg)
            else:
                if m.group(3) is not None:
                    mx.warn('Ignoring argument in substitution ' + m.group(0))
                if callable(fn):
                    return fn()
                else:
                    return fn
        elif self._chain is not None:
            return self._chain._replace(m)
        else:
            mx.abort('Unknown substitution: ' + m.group(0))

    def substitute(self, string):
        return re.sub(r'<(.+?)(:(.+?))?>', self._replace, string)


class CompatSubstitutionEngine(SubstitutionEngine):
    def __init__(self, replaceFn):
        super(CompatSubstitutionEngine, self).__init__()
        self._replaceFn = replaceFn

    def _replace(self, m):
        # simulate behavior of old regex matcher
        return re.sub(r'<(.+?)>', self._replaceFn, m.group(0))


def as_engine(subst):
    if isinstance(subst, SubstitutionEngine):
        return subst
    else:
        return CompatSubstitutionEngine(subst)


results_substitutions = SubstitutionEngine()
path_substitutions = SubstitutionEngine(results_substitutions)
