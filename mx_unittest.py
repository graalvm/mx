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
import re
import tempfile
import fnmatch
from argparse import ArgumentParser, RawDescriptionHelpFormatter

def _find_classes_with_annotations(p, pkgRoot, annotations, includeInnerClasses=False):
    """
    Scan the sources of project 'p' for Java source files containing a line starting with 'annotation'
    (ignoring preceding whitespace) and return the fully qualified class name for each Java
    source file matched in a list.
    """

    matches = lambda line: len([a for a in annotations if line == a or line.startswith(a + '(')]) != 0
    return p.find_classes_with_matching_source_line(pkgRoot, matches, includeInnerClasses)

def _run_tests(args, harness, vmLauncher, annotations, testfile, blacklist, whitelist, regex):


    vmArgs, tests = mx.extract_VM_args(args)
    for t in tests:
        if t.startswith('-'):
            mx.abort('VM option ' + t + ' must precede ' + tests[0])

    candidates = {}
    for p in mx.projects_opt_limit_to_suites():
        if mx.java().javaCompliance < p.javaCompliance:
            continue
        for c in _find_classes_with_annotations(p, None, annotations).keys():
            candidates[c] = p

    classes = []
    if len(tests) == 0:
        classes = candidates.keys()
        projectsCp = mx.classpath([pcp.name for pcp in mx.projects_opt_limit_to_suites() if pcp.javaCompliance <= mx.java().javaCompliance])
    else:
        projs = set()
        found = False
        if len(tests) == 1 and '#' in tests[0]:
            words = tests[0].split('#')
            if len(words) != 2:
                mx.abort("Method specification is class#method: " + tests[0])
            t, method = words

            for c, p in candidates.iteritems():
                # prefer exact matches first
                if t == c:
                    found = True
                    classes.append(c)
                    projs.add(p.name)
            if not found:
                for c, p in candidates.iteritems():
                    if t in c:
                        found = True
                        classes.append(c)
                        projs.add(p.name)
            if not found:
                mx.log('warning: no tests matched by substring "' + t)
            elif len(classes) != 1:
                mx.abort('More than one test matches substring {0} {1}'.format(t, classes))

            classes = [c + "#" + method for c in classes]
        else:
            for t in tests:
                if '#' in t:
                    mx.abort('Method specifications can only be used in a single test: ' + t)
                for c, p in candidates.iteritems():
                    if t in c:
                        found = True
                        classes.append(c)
                        projs.add(p.name)
                if not found:
                    mx.log('warning: no tests matched by substring "' + t)
        projectsCp = mx.classpath(projs)

    if blacklist:
        classes = [c for c in classes if not any((glob.match(c) for glob in blacklist))]

    if whitelist:
        classes = [c for c in classes if any((glob.match(c) for glob in whitelist))]

    if regex:
        classes = [c for c in classes if re.search(regex, c)]

    if len(classes) != 0:
        f_testfile = open(testfile, 'w')
        for c in classes:
            f_testfile.write(c + '\n')
        f_testfile.close()
        harness(projectsCp, vmLauncher, vmArgs)

def _unittest(args, annotations, vmLauncher=None, prefixCp="", blacklist=None, whitelist=None, verbose=False, fail_fast=False, enable_timing=False, regex=None, color=False, eager_stacktrace=False, gc_after_test=False):
    testfile = os.environ.get('MX_TESTFILE', None)
    if testfile is None:
        (_, testfile) = tempfile.mkstemp(".testclasses", "mxtool")
        os.close(_)

    coreCp = mx.classpath(['com.oracle.mxtool.junit', 'HCFDIS'])

    coreArgs = []
    if verbose:
        coreArgs.append('-JUnitVerbose')
    if fail_fast:
        coreArgs.append('-JUnitFailFast')
    if enable_timing:
        coreArgs.append('-JUnitEnableTiming')
    if color:
        coreArgs.append('-JUnitColor')
    if eager_stacktrace:
        coreArgs.append('-JUnitEagerStackTrace')
    if gc_after_test:
        coreArgs.append('-JUnitGCAfterTest')


    def harness(projectsCp, vmLauncher, vmArgs):
        prefixArgs = ['-esa', '-ea']
        if gc_after_test:
            prefixArgs.append('-XX:-DisableExplicitGC')
        with open(testfile) as fp:
            testclasses = [l.rstrip() for l in fp.readlines()]

        # Run the VM in a mode where application/test classes can
        # access classes normally hidden behind the JVMCI class loader
        cp = prefixCp + coreCp + os.pathsep + projectsCp

        # suppress menubar and dock when running on Mac
        vmArgs = prefixArgs + ['-Djava.awt.headless=true'] + vmArgs + ['-cp', mx._separatedCygpathU2W(cp)]
        mainClass = 'com.oracle.mxtool.junit.MxJUnitWrapper'
        # Execute Junit directly when one test is being run. This simplifies
        # replaying the VM execution in a native debugger (e.g., gdb).
        mainClassArgs = coreArgs + (testclasses if len(testclasses) == 1 else ['@' + mx._cygpathU2W(testfile)])

        vmLauncher(vmArgs, mainClass, mainClassArgs)

    if vmLauncher is None:
        vmLauncher = lambda vmArgs, mainClass, mainClassArgs: mx.run_java(vmArgs + [mainClass] + mainClassArgs)

    try:
        _run_tests(args, harness, vmLauncher, annotations, testfile, blacklist, whitelist, regex)
    finally:
        if os.environ.get('MX_TESTFILE') is None:
            os.remove(testfile)

unittestHelpSuffix = """
    Unittest options:

      --blacklist <file>     run all testcases not specified in the blacklist
      --whitelist <file>     run only testcases which are included
                             in the given whitelist
      --verbose              enable verbose JUnit output
      --fail-fast            stop after first JUnit test class that has a failure
      --enable-timing        enable JUnit test timing
      --regex <regex>        run only testcases matching a regular expression
      --color                enable colors output
      --eager-stacktrace     print stacktrace eagerly
      --gc-after-test        force a GC after each test

    To avoid conflicts with VM options '--' can be used as delimiter.

    If filters are supplied, only tests whose fully qualified name
    includes a filter as a substring are run.

    For example, this command line:

       mx unittest -G:Dump= -G:MethodFilter=BC_aload.* -G:+PrintCFG BC_aload

    will run all JUnit test classes that contain 'BC_aload' in their
    fully qualified name and will pass these options to the VM:

        -G:Dump= -G:MethodFilter=BC_aload.* -G:+PrintCFG

    To get around command line length limitations on some OSes, the
    JUnit class names to be executed are written to a file that a
    custom JUnit wrapper reads and passes onto JUnit proper. The
    MX_TESTFILE environment variable can be set to specify a
    file which will not be deleted once the unittests are done
    (unlike the temporary file otherwise used).

    As with all other commands, using the global '-v' before 'unittest'
    command will cause mx to show the complete command line
    it uses to run the VM.
"""

def unittest(args, vmLauncher=None):
    """run the JUnit tests (all testcases)"""

    parser = ArgumentParser(prog='mx unittest',
          description='run the JUnit tests',
          add_help=False,
          formatter_class=RawDescriptionHelpFormatter,
          epilog=unittestHelpSuffix,
        )
    parser.add_argument('--blacklist', help='run all testcases not specified in <file>', metavar='<file>')
    parser.add_argument('--whitelist', help='run testcases specified in <file> only', metavar='<file>')
    parser.add_argument('--verbose', help='enable verbose JUnit output', action='store_true')
    parser.add_argument('--fail-fast', help='stop after first JUnit test class that has a failure', action='store_true')
    parser.add_argument('--enable-timing', help='enable JUnit test timing', action='store_true')
    parser.add_argument('--regex', help='run only testcases matching a regular expression', metavar='<regex>')
    parser.add_argument('--color', help='enable color output', action='store_true')
    parser.add_argument('--eager-stacktrace', help='print stacktrace eagerly', action='store_true')
    parser.add_argument('--gc-after-test', help='force a GC after each test', action='store_true')

    ut_args = []
    delimiter = False
    # check for delimiter
    while len(args) > 0:
        arg = args.pop(0)
        if arg == '--':
            delimiter = True
            break
        ut_args.append(arg)

    if delimiter:
        # all arguments before '--' must be recognized
        parsed_args = parser.parse_args(ut_args)
    else:
        # parse all know arguments
        parsed_args, args = parser.parse_known_args(ut_args)

    if parsed_args.whitelist:
        try:
            with open(parsed_args.whitelist) as fp:
                parsed_args.whitelist = [re.compile(fnmatch.translate(l.rstrip())) for l in fp.readlines() if not l.startswith('#')]
        except IOError:
            mx.log('warning: could not read whitelist: ' + parsed_args.whitelist)
    if parsed_args.blacklist:
        try:
            with open(parsed_args.blacklist) as fp:
                parsed_args.blacklist = [re.compile(fnmatch.translate(l.rstrip())) for l in fp.readlines() if not l.startswith('#')]
        except IOError:
            mx.log('warning: could not read blacklist: ' + parsed_args.blacklist)

    _unittest(args, ['@Test', '@Parameters'], vmLauncher=vmLauncher, **parsed_args.__dict__)
