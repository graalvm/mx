#!/usr/bin/env python2.7
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

import mx
import os
from os.path import join, exists

def _should_test_project(p):
    if not p.isJavaProject():
        return False
    if hasattr(p, 'jackpot'):
        return p.jackpot.lower() == 'true' or p.jackpot is True
    return True

def jackpot(args, suite=None, nonZeroIsFatal=False):
    """run Jackpot 3.0 against non-test Java projects"""
    jackpotHome = mx.get_env('JACKPOT_HOME', None)
    if jackpotHome:
        jackpotJar = join(jackpotHome, 'jackpot.jar')
    else:
        jackpotJar = mx.library('JACKPOT').get_path(resolve=True)
    assert exists(jackpotJar)
    if suite is None:
        suite = mx._primary_suite
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

        javaCompliance = p.javaCompliance
        if javaCompliance.value < 10:
            sourceLevel = javaCompliance.value
        else:
            sourceLevel = 9

        groups = groups + ['--group', "--classpath " + mx._separatedCygpathU2W(_escape_string(os.pathsep.join(javacClasspath))) + " --source " + str(sourceLevel) + " " + " ".join([_escape_string(d) for d in p.source_dirs()])]

    cmd = ['-classpath', mx._cygpathU2W(jackpotJar), 'org.netbeans.modules.jackpot30.cmdline.Main']
    cmd = cmd + ['--fail-on-warnings', '--progress'] + args + groups

    return mx.run_java(cmd, nonZeroIsFatal=nonZeroIsFatal, jdk=mx.get_jdk(javaCompliance))

def _escape_string(s):
    return s.replace("\\", "\\\\").replace(" ", "\\ ")
