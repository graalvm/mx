#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2015, Oracle and/or its affiliates. All rights reserved.
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

from __future__ import print_function

import tempfile
import mx
import os
from os.path import join, exists


def _should_test_project(p):
    if not p.isJavaProject():
        return False
    if hasattr(p, 'jackpot'):
        return p.jackpot.lower() == 'true' or p.jackpot is True
    return True


@mx.command(suite_name="mx",
            command_name='jackpot',
            usage_msg='[--apply]',
            auto_add=False)
def jackpot(args, suite=None, nonZeroIsFatal=False):
    """run Jackpot 11.1 against non-test Java projects"""

    jackpotHome = mx.get_env('JACKPOT_HOME', None)
    if jackpotHome:
        jackpotJar = join(jackpotHome, 'jackpot.jar')
    else:
        jackpotJar = mx.library('JACKPOT').get_path(resolve=True)
    assert exists(jackpotJar)
    if suite is None:
        suite = mx.primary_suite()
    nonTestProjects = [p for p in mx.projects() if _should_test_project(p)]
    if not nonTestProjects:
        return 0
    groups = []
    for p in nonTestProjects:
        javacClasspath = []

        deps = []
        p.walk_deps(visit=lambda dep, edge: deps.append(dep) if dep.isLibrary() or dep.isJavaProject() else None)
        annotationProcessorOnlyDeps = []
        if len(p.annotation_processors()) > 0:
            for apDep in p.annotation_processors():
                if not apDep in deps:
                    deps.append(apDep)
                    annotationProcessorOnlyDeps.append(apDep)

        for dep in deps:
            if dep == p:
                continue

            if dep in annotationProcessorOnlyDeps:
                continue

            javacClasspath.append(dep.classpath_repr(resolve=True))

        sourceLevel = min(p.javaCompliance.value, 9)

        groups = groups + ['--group', "--classpath " + mx._separatedCygpathU2W(_escape_string(os.pathsep.join(javacClasspath))) + " --source " + str(sourceLevel) + " " + " ".join([_escape_string(d) for d in p.source_dirs()])]

    cmd = ['--add-exports=jdk.compiler/com.sun.tools.javac.code=ALL-UNNAMED', '--add-opens=java.base/java.net=ALL-UNNAMED', '--add-opens=java.desktop/sun.awt=ALL-UNNAMED']
    cmd = cmd + ['-classpath', mx._cygpathU2W(jackpotJar), 'org.netbeans.modules.jackpot30.cmdline.Main']
    jackCmd = ['--fail-on-warnings', '--progress'] + args + groups

    jdk = mx.get_jdk(mx.JavaCompliance("11+"), cancel='cannot run Jackpot', purpose="run Jackpot")
    if jdk is None:
        mx.warn('Skipping Jackpot since JDK 11 is not available')
        return 0
    else:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jackpot') as f:
            for c in jackCmd:
                print(c, file=f)
            f.flush()
            ret = mx.run_java(cmd + ['@' + f.name], nonZeroIsFatal=nonZeroIsFatal, jdk=jdk)
            if ret != 0:
                mx.warn('To simulate the failure execute `mx -p {0} jackpot`.'.format(suite.dir))
                mx.warn('To fix the error automatically try `mx -p {0} jackpot --apply`'.format(suite.dir))
            return ret

def _escape_string(s):
    return s.replace("\\", "\\\\").replace(" ", "\\ ")
