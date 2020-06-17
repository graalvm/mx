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

from __future__ import print_function

import mx
import os
import re
import tempfile
import fnmatch
from argparse import ArgumentParser, RawDescriptionHelpFormatter, ArgumentTypeError, Action
from os.path import exists, join, basename


def _read_cached_testclasses(cachesDir, jar, jdk):
    """
    Reads the cached list of test classes in `jar`.

    :param str cachesDir: directory containing files with cached test lists
    :param JDKConfig jdk: the JDK for which the cached list of classes must be found
    :return: the cached list of test classes in `jar` or None if the cache doesn't
             exist or is out of date
    """
    jdkVersion = '.jdk' + str(jdk.javaCompliance)
    cache = join(cachesDir, basename(jar) + jdkVersion + '.testclasses')
    if exists(cache) and mx.TimeStampFile(cache).isNewerThan(jar):
        # Only use the cached result if the source jar is older than the cache file
        try:
            with open(cache) as fp:
                return [line.strip() for line in fp.readlines()]
        except IOError as e:
            mx.warn('Error reading from ' + cache + ': ' + str(e))
    return None

def _write_cached_testclasses(cachesDir, jar, jdk, testclasses, excludedclasses):
    """
    Writes `testclasses` to a cache file specific to `jar`.

    :param str cachesDir: directory containing files with cached test lists
    :param JDKConfig jdk: the JDK for which the cached list of classes must be written
    :param list testclasses: a list of test class names
    :param list excludedclasses: a list of excluded class names
    """
    jdkVersion = '.jdk' + str(jdk.javaCompliance)
    cache = join(cachesDir, basename(jar) + jdkVersion + '.testclasses')
    exclusions = join(cachesDir, basename(jar) + jdkVersion + '.excludedclasses')
    try:
        with open(cache, 'w') as fp:
            for classname in testclasses:
                print(classname, file=fp)
        with open(exclusions, 'w') as fp:
            if excludedclasses:
                mx.warn('Unsupported class files listed in ' + exclusions)
            for classname in excludedclasses:
                print(classname[1:], file=fp)
    except IOError as e:
        mx.warn('Error writing to ' + cache + ': ' + str(e))

def _find_classes_by_annotated_methods(annotations, dists, jdk=None):
    if len(dists) == 0:
        return {}

    candidates = {}

    # Create map from jar file to the binary suite distribution defining it
    jarsToDists = {d.classpath_repr(): d for d in dists}

    primarySuite = mx.primary_suite()
    cachesDir = None
    jarsToParse = []
    if primarySuite and primarySuite != mx._mx_suite:
        cachesDir = mx.ensure_dir_exists(join(primarySuite.get_output_root(), 'unittest'))
        for d in dists:
            jar = d.classpath_repr()
            testclasses = _read_cached_testclasses(cachesDir, jar, jdk if jdk else mx.get_jdk())
            if testclasses is not None:
                for classname in testclasses:
                    candidates[classname] = jarsToDists[jar]
            else:
                jarsToParse.append(jar)

    if jarsToParse:
        # Ensure Java support class is built
        mx.build(['--no-daemon', '--dependencies', 'com.oracle.mxtool.junit'])

        cp = mx.classpath(['com.oracle.mxtool.junit'] + list(jarsToDists.values()), jdk=jdk)
        out = mx.LinesOutputCapture()
        mx.run_java(['-cp', cp, 'com.oracle.mxtool.junit.FindClassesByAnnotatedMethods'] + annotations + jarsToParse, out=out, addDefaultArgs=False)

        for line in out.lines:
            parts = line.split(os.pathsep)
            jar = parts[0]
            reportedclasses = parts[1:] if len(parts) > 1 else []
            testclasses = [c for c in reportedclasses if not c.startswith("!")]
            excludedclasses = [c for c in reportedclasses if c.startswith("!")]
            if cachesDir:
                _write_cached_testclasses(cachesDir, jar, jdk if jdk else mx.get_jdk(), testclasses, excludedclasses)
            for classname in testclasses:
                candidates[classname] = jarsToDists[jar]
    return candidates

def _find_classes_with_annotations(p, pkgRoot, annotations, includeInnerClasses=False):
    """
    Scan the sources of project 'p' for Java source files containing a line starting with
    any element of 'annotations' (ignoring preceding whitespace) and return the list of fully
    qualified class names for each Java source file matched.
    """
    matches = lambda line: len([a for a in annotations if line == a or line.startswith(a + '(')]) != 0
    return p.find_classes_with_matching_source_line(pkgRoot, matches, includeInnerClasses)


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

    # this is what should be used
    compat_suite = suite if suite else mx.primary_suite()
    if suite != mx._mx_suite and compat_suite.getMxCompatibility().useDistsForUnittest():
        jar_distributions = [d for d in mx.sorted_dists() if d.isJARDistribution() and exists(d.classpath_repr(resolve=False)) and (not suite or d.suite == suite)]
        # find a corresponding distribution for each test
        candidates = _find_classes_by_annotated_methods(annotations, jar_distributions, vmLauncher.jdk())
    else:
        binary_deps = [d for d in mx.dependencies(opt_limit_to_suite=True) if d.isJARDistribution() and
                       isinstance(d.suite, mx.BinarySuite) and (not suite or suite == d.suite)]
        candidates = _find_classes_by_annotated_methods(annotations, binary_deps, vmLauncher.jdk())
        for p in mx.projects(opt_limit_to_suite=True):
            if not p.isJavaProject():
                continue
            if suite and not p.suite == suite:
                continue
            if vmLauncher.jdk().javaCompliance < p.javaCompliance:
                continue
            for c in _find_classes_with_annotations(p, None, annotations):
                candidates[c] = p

    classes = []
    if len(tests) == 0:
        classes = list(candidates.keys())
        depsContainingTests = set(candidates.values())
    else:
        depsContainingTests = set()
        found = False
        if len(tests) == 1 and '#' in tests[0]:
            words = tests[0].split('#')
            if len(words) != 2:
                mx.abort("Method specification is class#method: " + tests[0])
            t, method = words

            for c, p in candidates.items():
                # prefer exact matches first
                if t == c:
                    found = True
                    classes.append(c)
                    depsContainingTests.add(p)
            if not found:
                for c, p in candidates.items():
                    if t in c:
                        found = True
                        classes.append(c)
                        depsContainingTests.add(p)
            if not found:
                mx.abort('no tests matched by substring: ' + t + ' (did you forget to run "mx build"?)')
            elif len(classes) != 1:
                mx.abort('More than one test matches substring {0} {1}'.format(t, classes))

            classes = [c + "#" + method for c in classes]
        else:
            for t in tests:
                if '#' in t:
                    mx.abort('Method specifications can only be used in a single test: ' + t)
                for c, p in candidates.items():
                    if t in c:
                        found = True
                        classes.append(c)
                        depsContainingTests.add(p)
                if not found:
                    mx.abort('no tests matched by substring: ' + t + ' (did you forget to run "mx build"?)')

    if blacklist:
        classes = [c for c in classes if not any((glob.match(c) for glob in blacklist))]

    if whitelist:
        classes = [c for c in classes if any((glob.match(c) for glob in whitelist))]

    if regex:
        classes = [c for c in classes if re.search(regex, c)]

    if len(classes) != 0:
        f_testfile = open(testfile, 'w')
        for c in sorted(classes):
            f_testfile.write(c + '\n')
        f_testfile.close()
        harness(depsContainingTests, vmLauncher, vmArgs)

#: A `_VMLauncher` object.
_vm_launcher = None

_config_participants = []
def set_vm_launcher(name, launcher, jdk=None):
    """
    Sets the details for running the JVM given the components of unit test command line.

    :param str name: a descriptive name for the launcher
    :param callable launcher: a function taking 3 positional arguments; the first is a list of the
           arguments to go before the main class name on the JVM command line, the second is the
           name of the main class to run and the third is a list of the arguments to go after
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

def _unittest(args, annotations, junit_args, prefixCp="", blacklist=None, whitelist=None, regex=None, suite=None):
    testfile = os.environ.get('MX_TESTFILE', None)
    if testfile is None:
        (_, testfile) = tempfile.mkstemp(".testclasses", "mxtool")
        os.close(_)

    mainClass = 'com.oracle.mxtool.junit.MxJUnitWrapper'
    mx.build(['--no-daemon', '--dependencies', 'JUNIT_TOOL'])
    coreCp = mx.classpath(['JUNIT_TOOL'])

    def harness(unittestDeps, vmLauncher, vmArgs):
        prefixArgs = ['-esa', '-ea']
        if '-JUnitGCAfterTest' in junit_args:
            prefixArgs.append('-XX:-DisableExplicitGC')
        with open(testfile) as fp:
            testclasses = [l.rstrip() for l in fp.readlines()]

        jdk = vmLauncher.jdk()
        vmArgs += mx.get_runtime_jvm_args(unittestDeps, cp_prefix=prefixCp+coreCp, jdk=jdk)

        # suppress menubar and dock when running on Mac
        vmArgs = prefixArgs + ['-Djava.awt.headless=true'] + vmArgs

        if jdk.javaCompliance > '1.8':
            # This is required to access jdk.internal.module.Modules for supporting
            # the @AddExports annotation.
            vmArgs = vmArgs + ['--add-exports=java.base/jdk.internal.module=ALL-UNNAMED']

        # Execute Junit directly when one test is being run. This simplifies
        # replaying the VM execution in a native debugger (e.g., gdb).
        mainClassArgs = junit_args + (testclasses if len(testclasses) == 1 else ['@' + mx._cygpathU2W(testfile)])

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
    To avoid conflicts with VM options, '--' can be used as delimiter.

    If test filters are supplied, only tests whose fully qualified name
    includes a filter as a substring are run.

    For example:

       mx unittest -Dgraal.Dump= -Dgraal.MethodFilter=BC_aload -Dgraal.PrintCFG=true BC_aload

    will run all JUnit test classes that contain 'BC_aload' in their
    fully qualified name and will pass these options to the VM:

        -Dgraal.Dump= -Dgraal.MethodFilter=BC_aload -Dgraal.PrintCFG=true

    To get around command line length limitations on some OSes, the
    JUnit class names to be executed are written to a file that a
    custom JUnit wrapper reads and passes onto JUnit proper. The
    MX_TESTFILE environment variable can be set to specify a
    file which will not be deleted once the unit tests are done
    (unlike the temporary file otherwise used).

    As with all other commands, using the global '-v' before 'unittest'
    command will cause mx to show the complete command line
    it uses to run the VM.
    
    The grammar for the argument to the --open-packages option is:

      export_spec  ::= module_spec "/" package_spec [ "=" target_spec [ "," target_spec ]* ]
      module_spec  ::= name [ "*" ]
      package_spec ::= name [ "*" ] | "*"
      target_spec  ::= "ALL-UNNAMED" | name [ "*" ] | "*"
      
    Examples:

    Export and open all packages in jdk.internal.vm.compiler to all unnamed modules:
    
      --open-packages jdk.internal.vm.compiler/*=ALL-UNNAMED
    
    Equivalent shorthand form:
    
      --open-packages jdk.internal.vm.compiler/*
    
    Export and open all packages starting with "org.graalvm.compiler." in all
    modules whose name starts with "jdk.internal.vm." to all unnamed modules:
    
      --open-packages jdk.internal.vm.*/org.graalvm.compiler.*
    
    Same as above but also export and open to the org.graalvm.enterprise module:
    
      --open-packages jdk.internal.vm.*/org.graalvm.compiler.*=ALL-UNNAMED,org.graalvm.enterprise
"""

def is_strictly_positive(value):
    try:
        if int(value) <= 0:
            raise ArgumentTypeError("%s must be greater than 0" % value)
    except ValueError:
        raise ArgumentTypeError("%s: integer greater than 0 expected" % value)
    return value


@mx.command(suite_name="mx",
            command_name='unittest',
            usage_msg='[unittest options] [--] [VM options] [filters...]',
            doc_function=lambda: unittestHelpSuffix,
            auto_add=False)
def unittest(args):
    """run the JUnit tests"""

    junit_arg_actions = []
    junit_args = []
    class MxJUnitWrapperArg(Action):
        def __init__(self, **kwargs):
            kwargs['required'] = False
            Action.__init__(self, **kwargs)
            junit_arg_actions.append(self)
        def __call__(self, parser, namespace, values, option_string=None):
            junit_args.append('-' + self.dest)
            junit_args.append(values)

    class MxJUnitWrapperBoolArg(Action):
        def __init__(self, **kwargs):
            kwargs['required'] = False
            kwargs['nargs'] = 0
            Action.__init__(self, **kwargs)
            junit_arg_actions.append(self)
        def __call__(self, parser, namespace, values, option_string=None):
            junit_args.append('-' + self.dest)

    parser = ArgumentParser(prog='mx unittest',
          description='run the JUnit tests',
          formatter_class=RawDescriptionHelpFormatter,
          epilog=unittestHelpSuffix,
        )

    parser.add_argument('--blacklist', help='run all testcases not specified in <file>', metavar='<file>')
    parser.add_argument('--whitelist', help='run testcases specified in <file> only', metavar='<file>')
    parser.add_argument('--verbose', help='enable verbose JUnit output', dest='JUnitVerbose', action=MxJUnitWrapperBoolArg)
    parser.add_argument('--very-verbose', help='enable very verbose JUnit output', dest='JUnitVeryVerbose', action=MxJUnitWrapperBoolArg)
    parser.add_argument('--max-class-failures', help='stop after N test classes that have a failure (default is no limit)', metavar='<N>', dest='JUnitMaxClassFailures', action=MxJUnitWrapperArg)
    parser.add_argument('--fail-fast', help='alias for --max-class-failures=1', dest='JUnitFailFast', action=MxJUnitWrapperBoolArg)
    parser.add_argument('--enable-timing', help='enable JUnit test timing (requires --verbose/--very-verbose)', dest='JUnitEnableTiming', action=MxJUnitWrapperBoolArg)
    parser.add_argument('--regex', help='run only testcases matching a regular expression', metavar='<regex>')
    parser.add_argument('--color', help='enable color output', dest='JUnitColor', action=MxJUnitWrapperBoolArg)
    parser.add_argument('--gc-after-test', help='force a GC after each test', dest='JUnitGCAfterTest', action=MxJUnitWrapperBoolArg)
    parser.add_argument('--record-results', help='record test class results to passed.txt and failed.txt', dest='JUnitRecordResults', action=MxJUnitWrapperBoolArg)
    parser.add_argument('--suite', help='run only the unit tests in <suite>', metavar='<suite>')
    parser.add_argument('--repeat', help='run each test <n> times', dest='JUnitRepeat', action=MxJUnitWrapperArg, type=is_strictly_positive, metavar='<n>')
    parser.add_argument('--open-packages', dest='JUnitOpenPackages', action=MxJUnitWrapperArg, metavar='<module>/<package>[=<target-module>(,<target-module>)*]',
                        help="export and open packages regardless of module declarations (see more detail and examples below)")
    eagerStacktrace = parser.add_mutually_exclusive_group()
    eagerStacktrace.add_argument('--eager-stacktrace', action='store_const', const=True, dest='eager_stacktrace', help='print test errors as they occur (default)')
    eagerStacktrace.add_argument('--no-eager-stacktrace', action='store_const', const=False, dest='eager_stacktrace', help='print test errors after all tests have run')

    # Augment usage text to mention test filters and options passed to the VM
    usage = parser.format_usage().strip()
    if usage.startswith('usage: '):
        usage = usage[len('usage: '):]
    parser.usage = usage + ' [test filters...] [VM options...]'

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
        # parse all known arguments
        parsed_args, args = parser.parse_known_args(ut_args)

    # Remove junit_args values from parsed_args
    for a in junit_arg_actions:
        parsed_args.__dict__.pop(a.dest)

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
        junit_args.append('-JUnitEagerStackTrace')
    parsed_args.__dict__.pop('eager_stacktrace')

    _unittest(args, ['@Test', '@Parameters'], junit_args, **parsed_args.__dict__)
