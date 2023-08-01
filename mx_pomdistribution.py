#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2023, Oracle and/or its affiliates. All rights reserved.
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

import mx


class POMDistribution(mx.Distribution):
    """
        Represents a Maven artifact with POM packaging used to group Maven dependencies. It does not contain any actual
        code or resources like traditional JARDistribution but acts as a metadata container that defines the project's
        dependencies and other essential project information.

        :param Suite suite: the suite in which the distribution is defined
        :param str name: the name of the distribution which must be unique across all suites
        :param list distDependencies: the `JARDistribution` dependencies that must be on the class path when this distribution
               is on the class path (at compile or run time)
        :param list runtimeDependencies: the `JARDistribution` dependencies that must be on the class path when this distribution
               is on the class path (at run time)
        :param str | None theLicense: license applicable when redistributing the built artifact of the distribution
        """
    def __init__(self, suite, name, distDependencies, runtimeDependencies, theLicense, **kwArgs):
        mx.Distribution.__init__(self, suite, name, distDependencies + runtimeDependencies, [], False, theLicense, **kwArgs)
        self.runtimeDependencies = runtimeDependencies

    def getBuildTask(self, args):
        return mx.NoOpTask(self, args)

    def make_archive(self):
        pass

    def exists(self):
        return True

    def remoteExtension(self):
        return 'pom'

    def localExtension(self):
        return 'xml'

    def resolveDeps(self):
        super(POMDistribution, self).resolveDeps()
        new_runtime_deps = []
        for runtime_dep in self.runtimeDependencies:
            new_runtime_deps.append(mx.dependency(runtime_dep, fatalIfMissing=True, context=self))
        self.runtimeDependencies = new_runtime_deps

    def is_runtime_dependency(self, dependency):
        return dependency in self.runtimeDependencies
