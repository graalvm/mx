#!/usr/bin/env python2.7
#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2007, 2015, Oracle and/or its affiliates. All rights reserved.
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
from os.path import exists
from argparse import ArgumentParser

def _should_test_project(p):
    if not p.isJavaProject():
        return False
    return len(mx.find_packages(p)) > 0

def sigtest(args, suite=None, projects=None):
    parser = ArgumentParser(prog='mx sigtest')
    parser.add_argument('--generate', action='store_true', help='Generates signature files for projects with API')

    args = parser.parse_args(args)

    if args.generate:
        _sigtest_generate(args)
    else:
        parser.print_help()

def _sigtest_generate(args, suite=None, projects=None):
    """run sigtest against Java projects with API"""
    sigtestlib = mx.library('SIGTEST').get_path(resolve=True)
    nonTestProjects = [p for p in mx.projects() if _should_test_project(p)]
    if not nonTestProjects:
        return 0
    javaCompliance = max([p.javaCompliance for p in nonTestProjects])

    for p in nonTestProjects:
        sigtestResults = p.dir + os.sep + 'sigtest-report.out'
        cmd = ['-cp', mx._cygpathU2W(sigtestlib), 'com.sun.tdk.signaturetest.Setup',
            '-Static', '-FileName', sigtestResults,
            '-ClassPath', mx.classpath(p) + os.pathsep + mx.get_jdk(javaCompliance).bootclasspath(),
        ]
        for pkg in mx.find_packages(p):
            cmd = cmd + ['-PackageWithoutSubpackages', pkg]
        exitcode = mx.run_java(cmd, nonZeroIsFatal=False, jdk=mx.get_jdk(javaCompliance))
        if exitcode != 0:
            mx.abort('Exit code was ' + str(exitcode) + ' while generating ' + sigtestResults)
        if not exists(sigtestResults):
            mx.abort('Cannot generate ' + sigtestResults)
        mx.log("Sigtest snapshot generated to " + sigtestResults)
    return 0
