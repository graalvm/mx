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
from argparse import ArgumentParser, RawDescriptionHelpFormatter, ArgumentTypeError
from os.path import exists, join


def _find_classes_by_annotated_elements(annotations, dists, jdk=None):
    if len(dists) == 0:
        return {}

    candidates = {}
    # Ensure Java support class is built
    mx.build(['--dependencies', 'com.oracle.mxtool.junit'])
    # Create map from jar file to the binary suite distribution defining it
    jars = {d.classpath_repr(): d for d in dists}
    cp = mx.classpath(['com.oracle.mxtool.junit'] + [d.name for d in dists], jdk=jdk)
    out = mx.OutputCapture()
    mx.run_java(['-cp', cp, 'com.oracle.mxtool.junit.FindClassesByAnnotatedElements'] + annotations + jars.keys(), out=out, addDefaultArgs=False)
    for line in out.data.strip().split('\n'):
        name, jar = line.split(' ')
        # Record class name to the binary suite distribution containing it
        candidates[name] = jars[jar]
    return candidates


class _VMLauncher(object):
    """
    Launcher to run the unit tests. See `set_vm_launcher` for descriptions of the parameters.
    """
    def __init__(self, name, launcher, jdk):
        self.name = name
        self.launcher = launcher
        self._jdk = jdk

    def jdk(self):
        if callable(self._jdk):
            return self._jdk()
        return self._jdk

def _run_tests(args, harness, vmLauncher, annotations, testfile, blacklist, whitelist, regex, suite):
    vmArgs, tests = mx.extract_VM_args(args)
    for t in tests:
        if t.startswith('-'):
            mx.abort('VM option ' + t + ' must precede ' + tests[0])

    # find a corresponding project for each test
    project_candidates = {}
    jdk = mx.get_jdk()
    for p in mx.projects(opt_limit_to_suite=True):
        if p.isJavaProject() and (not suite or p.suite == suite) and jdk.javaCompliance >= p.javaCompliance:
            for c in p.find_classes_with_annotations(None, annotations):
                project_candidates[c] = p

    jar_distributions = [d for d in mx.sorted_dists() if d.isJARDistribution() and (not suite or d.suite == suite)]
    # find a corresponding distribution for each test
    candidates = _find_classes_by_annotated_elements(annotations, jar_distributions, jdk)

    # list tests that are found in projects and not found in distributions
    for c, p in project_candidates.items():
        if c not in candidates.keys():
            mx.warn("Test " + str(c) + " will not be executed. Its class is not present in test distributions.")

    # now add the dependencies
    classes = []
    if len(tests) == 0:
        classes = candidates.keys()
        depsContainingTests = set(candidates.values())
    else:
        depsContainingTests = set()
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
                    depsContainingTests.add(p)
            if not found:
                for c, p in candidates.iteritems():
                    if t in c:
                        found = True
                        classes.append(c)
                        depsContainingTests.add(p)
            if not found:
                mx.log('warning: no tests matched by substring: ' + t)
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
                        depsContainingTests.add(p)
                if not found:
                    mx.log('warning: no tests matched by substring: ' + t)

    unittestCp = mx.classpath(depsContainingTests, jdk=vmLauncher.jdk())
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
        harness(unittestCp, vmLauncher, vmArgs)

#: A `_VMLauncher` object.
_vm_launcher = None

_config_participants = []
def set_vm_launcher(name, launcher, jdk=None):
    """
    Sets the details for running the JVM given the components of unit test command line.

    :param str name: a descriptive name for the launcher
    :param callable launcher: a function taking 3 positional arguments; the first is a list of the
           arguments to go before the main class name on the JVM command line, the second is the
           name of the main class to run run and the third is a list of the arguments to go after
           the main class name on the JVM command line
    :param jdk: a `JDKConfig` or no-arg callable that produces a `JDKConfig` object denoting
           the JDK containing the JVM that will be executed. This is used to resolve JDK
           relative dependencies (such as `JdkLibrary`s) needed by the unit tests.
    """
    global _vm_launcher
    assert _vm_launcher is None, 'cannot override unit test VM launcher ' + _vm_launcher.name
    if jdk is None:
        def _jdk():
            jdk = mx.get_jdk()
            mx.warn('Assuming ' + str(jdk) + ' contains JVM executed by ' + name)
            return _jdk
    _vm_launcher = _VMLauncher(name, launcher, jdk)

def add_config_participant(p):
    _config_participants.append(p)

def _unittest(args, annotations, prefixCp="", blacklist=None, whitelist=None, verbose=False, very_verbose=False, fail_fast=False, enable_timing=False, regex=None, color=False, eager_stacktrace=False, gc_after_test=False, suite=None, repeat=None):
    testfile = os.environ.get('MX_TESTFILE', None)
    if testfile is None:
        (_, testfile) = tempfile.mkstemp(".testclasses", "mxtool")
        os.close(_)

    mainClass = 'com.oracle.mxtool.junit.MxJUnitWrapper'
    if not exists(join(mx.project('com.oracle.mxtool.junit').output_dir(), mainClass.replace('.', os.sep) + '.class')):
        mx.build(['--only', 'com.oracle.mxtool.junit'])
    coreCp = mx.classpath(['com.oracle.mxtool.junit'])

    coreArgs = []
    if very_verbose:
        coreArgs.append('-JUnitVeryVerbose')
    elif verbose:
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
    if repeat:
        coreArgs.append('-JUnitRepeat')
        coreArgs.append(repeat)


    def harness(unittestCp, vmLauncher, vmArgs):
        prefixArgs = ['-esa', '-ea']
        if gc_after_test:
            prefixArgs.append('-XX:-DisableExplicitGC')
        with open(testfile) as fp:
            testclasses = [l.rstrip() for l in fp.readlines()]

        cp = prefixCp + coreCp + os.pathsep + unittestCp

        # suppress menubar and dock when running on Mac
        vmArgs = prefixArgs + ['-Djava.awt.headless=true'] + vmArgs + ['-cp', mx._separatedCygpathU2W(cp)]
        # Execute Junit directly when one test is being run. This simplifies
        # replaying the VM execution in a native debugger (e.g., gdb).
        mainClassArgs = coreArgs + (testclasses if len(testclasses) == 1 else ['@' + mx._cygpathU2W(testfile)])

        config = (vmArgs, mainClass, mainClassArgs)
        for p in _config_participants:
            config = p(config)

        vmLauncher.launcher(*config)

    vmLauncher = _vm_launcher
    if vmLauncher is None:
        jdk = mx.get_jdk()
        def _run_vm(vmArgs, mainClass, mainClassArgs):
            mx.run_java(vmArgs + [mainClass] + mainClassArgs, jdk=jdk)
        vmLauncher = _VMLauncher('default VM launcher', _run_vm, jdk)

    try:
        _run_tests(args, harness, vmLauncher, annotations, testfile, blacklist, whitelist, regex, mx.suite(suite) if suite else None)
    finally:
        if os.environ.get('MX_TESTFILE') is None:
            os.remove(testfile)

unittestHelpSuffix = """
    Unittest options:

      --blacklist <file>     run all testcases not specified in the blacklist
      --whitelist <file>     run only testcases which are included
                             in the given whitelist
      --very-verbose         enable very verbose JUnit output
      --verbose              enable verbose JUnit output
      --fail-fast            stop after first JUnit test class that has a failure
      --enable-timing        enable JUnit test timing (requires --verbose or --very-verbose)
      --regex <regex>        run only testcases matching a regular expression
      --color                enable colors output
      --eager-stacktrace     print stacktrace eagerly (default)
      --no-eager-stacktrace  do not print stacktrace eagerly
      --gc-after-test        force a GC after each test

    To avoid conflicts with VM options '--' can be used as delimiter.

    If filters are supplied, only tests whose fully qualified name
    includes a filter as a substring are run.

    For example, this command line:

       mx unittest -Dgraal.Dump= -Dgraal.MethodFilter=BC_aload -Dgraal.PrintCFG=true BC_aload

    will run all JUnit test classes that contain 'BC_aload' in their
    fully qualified name and will pass these options to the VM:

        -Dgraal.Dump= -Dgraal.MethodFilter=BC_aload -Dgraal.PrintCFG=true

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

def is_strictly_positive(value):
    try:
        if int(value) <= 0:
            raise ArgumentTypeError("%s must be greater than 0" % value)
    except ValueError:
        raise ArgumentTypeError("%s: integer greater than 0 expected" % value)
    return value


def unittest(args):
    """run the JUnit tests"""

    parser = ArgumentParser(prog='mx unittest',
          description='run the JUnit tests',
          add_help=False,
          formatter_class=RawDescriptionHelpFormatter,
          epilog=unittestHelpSuffix,
        )
    parser.add_argument('--blacklist', help='run all testcases not specified in <file>', metavar='<file>')
    parser.add_argument('--whitelist', help='run testcases specified in <file> only', metavar='<file>')
    parser.add_argument('--verbose', help='enable verbose JUnit output', action='store_true')
    parser.add_argument('--very-verbose', help='enable very verbose JUnit output', action='store_true')
    parser.add_argument('--fail-fast', help='stop after first JUnit test class that has a failure', action='store_true')
    parser.add_argument('--enable-timing', help='enable JUnit test timing (requires --verbose/--very-verbose)', action='store_true')
    parser.add_argument('--regex', help='run only testcases matching a regular expression', metavar='<regex>')
    parser.add_argument('--color', help='enable color output', action='store_true')
    parser.add_argument('--gc-after-test', help='force a GC after each test', action='store_true')
    parser.add_argument('--suite', help='run only the unit tests in <suite>', metavar='<suite>')
    parser.add_argument('--repeat', help='run only the unit tests in <suite>', type=is_strictly_positive)
    eagerStacktrace = parser.add_mutually_exclusive_group()
    eagerStacktrace.add_argument('--eager-stacktrace', action='store_const', const=True, dest='eager_stacktrace', help='print test errors as they occur (default)')
    eagerStacktrace.add_argument('--no-eager-stacktrace', action='store_const', const=False, dest='eager_stacktrace', help='print test errors after all tests have run')

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
    if parsed_args.eager_stacktrace is None:
        parsed_args.eager_stacktrace = True

    _unittest(args, ['@Test', '@Parameters'], **parsed_args.__dict__)
