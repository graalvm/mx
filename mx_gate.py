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

import os, re, time, datetime
from os.path import join, exists
from argparse import ArgumentParser
import xml.dom.minidom

import mx
import mx_microbench
import sys

"""
Predefined Task tags.
"""
class Tags:
    always = 'always'       # special tag that is always implicitly selected
    style = 'style'         # code style checks (without build)
    build = 'build'         # build
    fullbuild = 'fullbuild' # full build (including warnings, findbugs and ide init)

"""
Context manager for a single gate task that can prevent the
task from executing or time and log its execution.
"""
class Task:
    # None or a list of strings. If not None, only tasks whose title
    # matches at least one of the substrings in this list will return
    # a non-None value from __enter__. The body of a 'with Task(...) as t'
    # statement should check 't' and exit immediately if it is None.
    filters = None
    dryRun = False
    startAtFilter = None
    filtersExclude = False

    tags = None
    tagsExclude = False
    # map from tag to a pair [from(inclusive), to(exclusive)]
    tags_range = dict()
    # map from tag to count
    tags_count = dict()

    verbose = False


    def tag_matches(self, _tags):
        for t in _tags:
            if t in Task.tags:
                if t not in Task.tags_range:
                    # no range restriction
                    return True
                else:
                    frm, to = Task.tags_range[t]
                    cnt = Task.tags_count[t]
                    # increment counter
                    Task.tags_count[t] += 1
                    if frm <= cnt and cnt < to:
                        return True
        return False

    def __init__(self, title, tasks=None, disableJacoco=False, tags=None, legacyTitles=None):
        self.tasks = tasks
        self.title = title
        self.legacyTitles = legacyTitles or []
        self.skipped = False
        self.tags = tags
        if tasks is not None:
            for t in tasks:
                if t.title == title:
                    mx.abort('Gate task with title "' + title + '" is already defined')

            if Task.startAtFilter:
                assert not Task.filters
                if Task.startAtFilter in title:
                    self.skipped = False
                    Task.startAtFilter = None
                else:
                    self.skipped = True
            elif Task.filters:
                titles = [self.title] + self.legacyTitles
                if Task.filtersExclude:
                    self.skipped = any([f in t for t in titles for f in Task.filters])
                else:
                    self.skipped = not any([f in t for t in titles for f in Task.filters])
            if Task.tags is not None:
                if Task.tagsExclude:
                    self.skipped = all([t in Task.tags for t in self.tags]) if tags else False
                else:
                    _tags = self.tags if self.tags else []
                    self.skipped = not self.tag_matches(_tags)
        if not self.skipped:
            self.start = time.time()
            self.end = None
            self.duration = None
            self.disableJacoco = disableJacoco
            mx.log(time.strftime('gate: %d %b %Y %H:%M:%S: BEGIN: ') + title)
    def __enter__(self):
        assert self.tasks is not None, "using Task with 'with' statement requires to pass the tasks list in the constructor"
        if self.skipped:
            return None
        if self.disableJacoco:
            self.jacacoSave = _jacoco
        if Task.dryRun:
            return None
        return self
    def __exit__(self, exc_type, exc_value, traceback):
        if not self.skipped:
            self.tasks.append(self.stop())
            if self.disableJacoco:
                global _jacoco
                _jacoco = self.jacacoSave

    @staticmethod
    def _human_fmt(num):
        for unit in ['', 'K', 'M', 'G']:
            if abs(num) < 1024.0:
                return "%3.1f%sB" % (num, unit)
            num /= 1024.0
        return "%.1fTB" % (num)

    @staticmethod
    def _diskstats():
        if hasattr(os, 'statvfs'):
            _, f_frsize, f_blocks, _, f_bavail, _, _, _, _, _ = os.statvfs(os.getcwd())
            total = f_frsize * f_blocks
            free = f_frsize * f_bavail
            return ' [disk (free/total): {}/{}]'.format(Task._human_fmt(free), Task._human_fmt(total))
        return ''

    def stop(self):
        self.end = time.time()
        self.duration = datetime.timedelta(seconds=self.end - self.start)
        mx.log(time.strftime('gate: %d %b %Y %H:%M:%S: END:   ') + self.title + ' [' + str(self.duration) + ']' + Task._diskstats())
        return self
    def abort(self, codeOrMessage):
        self.end = time.time()
        self.duration = datetime.timedelta(seconds=self.end - self.start)
        mx.log(time.strftime('gate: %d %b %Y %H:%M:%S: ABORT: ') + self.title + ' [' + str(self.duration) + ']' + Task._diskstats())
        mx.abort(codeOrMessage)
        return self

_gate_runners = []
_pre_gate_runners = []
_extra_gate_arguments = []

def add_gate_argument(*args, **kwargs):
    """
    Adds an argument declaration to the ArgumentParser used by the gate method.
    """
    _extra_gate_arguments.append((args, kwargs))

def add_gate_runner(suite, runner):
    """
    Adds a gate runner function for a given suite to be called by the gate once common gate tasks
    have been executed. The 'runner' function is called with these arguments:
      args: the argparse.Namespace object containing result of parsing gate command line
      tasks: list of Task to which extra Tasks should be added
    """
    suiteRunner = (suite, runner)
    _gate_runners.append(suiteRunner)

def prepend_gate_runner(suite, runner):
    """
    Prepends a gate runner function for a given suite to be called by the gate before common gate tasks
    are executed. The 'runner' function is called with these arguments:
      args: the argparse.Namespace object containing result of parsing gate command line
      tasks: list of Task to which extra Tasks should be added
    """
    suiteRunner = (suite, runner)
    _pre_gate_runners.append(suiteRunner)

def add_omit_clean_args(parser):
    parser.add_argument('-j', '--omit-java-clean', action='store_false', dest='cleanJava', help='omit cleaning Java native code')
    parser.add_argument('-n', '--omit-native-clean', action='store_false', dest='cleanNative', help='omit cleaning and building native code')
    parser.add_argument('-e', '--omit-ide-clean', action='store_false', dest='cleanIDE', help='omit ideclean/ideinit')
    parser.add_argument('-d', '--omit-dist-clean', action='store_false', dest='cleanDist', help='omit cleaning distributions')
    parser.add_argument('-o', '--omit-clean', action='store_true', dest='noClean', help='equivalent to -j -n -e')

def gate_clean(cleanArgs, tasks, name='Clean', tags=None):
    with Task(name, tasks, tags=tags) as t:
        if t:
            mx.command_function('clean')(cleanArgs)

def check_gate_noclean_arg(args):
    '''
    Checks the -o option (noClean) and sets the sub-options in args appropriately
    and returns the relevant args for the clean command (N.B. IDE currently ignored).
    '''
    if args.noClean:
        args.cleanIDE = False
        args.cleanJava = False
        args.cleanNative = False
        args.cleanDist = False
    cleanArgs = []
    if not args.cleanNative:
        cleanArgs.append('--no-native')
    if not args.cleanJava:
        cleanArgs.append('--no-java')
    if not args.cleanDist:
        cleanArgs.append('--no-dist')
    return cleanArgs

def _warn_or_abort(msg, strict_mode):
    reporter = mx.abort if strict_mode else mx.warn
    reporter(msg)


def parse_tags_argument(tags_arg, exclude):
    pattern = re.compile(r"^(?P<tag>[^:]*)(?::(?P<from>\d+):(?P<to>\d+)?)?$")
    tags = tags_arg.split(',')
    Task.tags = []
    for tag_spec in tags:
        m = pattern.match(tag_spec)
        if not m:
            mx.abort('--tags option requires the format `name[:from:[to]]`: {0}'.format(tag_spec))
        (tag, t_from, t_to) = m.groups()
        if t_from:
            if exclude:
                mx.abort('-x option cannot be used tag ranges: {0}'.format(tag_spec))
            frm = int(t_from)
            to = int(t_to) if t_to else sys.maxsize
            # insert range tuple
            Task.tags_range[tag] = (frm, to)
            # sanity check
            if to <= frm:
                mx.abort('`from` must be less than `to` for tag ranges: {0}'.format(tag_spec))
            # init counter
            Task.tags_count[tag] = 0
        Task.tags.append(tag)

def gate(args):
    """run the tests used to validate a push

    If this command exits with a 0 exit code, then the gate passed."""

    parser = ArgumentParser(prog='mx gate')
    add_omit_clean_args(parser)
    parser.add_argument('--all-suites', action='store_true', help='run gate tasks for all suites, not just the primary suite')
    parser.add_argument('--dry-run', action='store_true', help='just show the tasks that will be run without running them')
    parser.add_argument('-x', action='store_true', help='makes --task-filter or --tags an exclusion instead of inclusion filter')
    parser.add_argument('--jacocout', help='specify the output directory for jacoco report')
    parser.add_argument('--strict-mode', action='store_true', help='abort if a task cannot be executed due to missing tool configuration')
    parser.add_argument('-B', dest='extra_build_args', action='append', metavar='<build_args>', help='append additional arguments to mx build commands used in the gate')
    filtering = parser.add_mutually_exclusive_group()
    filtering.add_argument('-t', '--task-filter', help='comma separated list of substrings to select subset of tasks to be run')
    filtering.add_argument('-s', '--start-at', help='substring to select starting task')
    filtering.add_argument('--tags', help='comma separated list of tags to select subset of tasks to be run. Tags can have a range specifier `name[:from:[to]]`.'
                           'If present only the [from,to) tasks are executed. If `to` is omitted all tasks starting with `from` are executed.')
    for a, k in _extra_gate_arguments:
        parser.add_argument(*a, **k)

    args = parser.parse_args(args)
    cleanArgs = check_gate_noclean_arg(args)

    global _jacoco
    if args.dry_run:
        Task.dryRun = True
    if args.start_at:
        Task.startAtFilter = args.start_at
    elif args.task_filter:
        Task.filters = args.task_filter.split(',')
        Task.filtersExclude = args.x
    elif args.tags:
        parse_tags_argument(args.tags, args.x)
        Task.tagsExclude = args.x
        if not Task.tagsExclude:
            # implicitly include 'always'
            Task.tags += [Tags.always]
    elif args.x:
        mx.abort('-x option cannot be used without --task-filter or the --tags option')

    if not args.extra_build_args:
        args.extra_build_args = []

    tasks = []
    total = Task('Gate')
    try:
        with Task('Versions', tasks, tags=[Tags.always]) as t:
            if t:
                mx.command_function('version')(['--oneline'])
                mx.command_function('sversions')([])

        with Task('JDKReleaseInfo', tasks, tags=[Tags.always]) as t:
            if t:
                jdkDirs = os.pathsep.join([mx.get_env('JAVA_HOME', ''), mx.get_env('EXTRA_JAVA_HOMES', '')])
                for jdkDir in jdkDirs.split(os.pathsep):
                    release = join(jdkDir, 'release')
                    if exists(release):
                        mx.log('==== ' + jdkDir + ' ====')
                        with open(release) as fp:
                            mx.log(fp.read().strip())

        for suiteRunner in _pre_gate_runners:
            suite, runner = suiteRunner
            if args.all_suites or suite is mx.primary_suite():
                runner(args, tasks)

        with Task('Pylint', tasks, tags=[Tags.style]) as t:
            if t:
                if mx.command_function('pylint')(['--primary']) != 0:
                    _warn_or_abort('Pylint not configured correctly. Cannot execute Pylint task.', args.strict_mode)

        gate_clean(cleanArgs, tasks, tags=[Tags.build, Tags.fullbuild])

        with Task('Distribution Overlap Check', tasks, tags=[Tags.style]) as t:
            if t:
                if mx.command_function('checkoverlap')([]) != 0:
                    t.abort('Found overlapping distributions.')

        with Task('Canonicalization Check', tasks, tags=[Tags.style]) as t:
            if t:
                mx.log(time.strftime('%d %b %Y %H:%M:%S - Ensuring mx/projects files are canonicalized...'))
                if mx.command_function('canonicalizeprojects')([]) != 0:
                    t.abort('Rerun "mx canonicalizeprojects" and modify the suite.py files as suggested.')

        with Task('Verify Java Sources in Project', tasks, tags=[Tags.style]) as t:
            if t:
                mx.log(time.strftime('%d %b %Y %H:%M:%S - Ensuring all Java sources are in a Java project directory...'))
                if mx.command_function('verifysourceinproject')([]) != 0:
                    t.abort('Move or delete the Java sources that are not in a Java project directory.')

        if mx._is_supported_by_jdt(mx.DEFAULT_JDK_TAG):
            with Task('BuildWithEcj', tasks, tags=[Tags.fullbuild], legacyTitles=['BuildJavaWithEcj']) as t:
                if t:
                    if mx.get_env('JDT'):
                        mx.command_function('build')(['-p', '--warning-as-error'] + args.extra_build_args)
                        gate_clean(cleanArgs, tasks, name='CleanAfterEcjBuild', tags=[Tags.fullbuild])
                    else:
                        _warn_or_abort('JDT environment variable not set. Cannot execute BuildWithEcj task.', args.strict_mode)

        with Task('BuildWithJavac', tasks, tags=[Tags.build, Tags.fullbuild], legacyTitles=['BuildJavaWithJavac']) as t:
            if t: mx.command_function('build')(['-p', '--warning-as-error', '--force-javac'] + args.extra_build_args)

        with Task('IDEConfigCheck', tasks, tags=[Tags.fullbuild]) as t:
            if t:
                if args.cleanIDE:
                    mx.command_function('ideclean')([])
                    mx.command_function('ideinit')([])

        with Task('CodeFormatCheck', tasks, tags=[Tags.style]) as t:
            if t:
                eclipse_exe = mx.get_env('ECLIPSE_EXE')
                if eclipse_exe is not None:
                    if mx.command_function('eclipseformat')(['-e', eclipse_exe, '--primary']) != 0:
                        t.abort('Formatter modified files - run "mx eclipseformat", check in changes and repush')
                else:
                    _warn_or_abort('ECLIPSE_EXE environment variable not set. Cannot execute CodeFormatCheck task.', args.strict_mode)

        with Task('Checkstyle', tasks, tags=[Tags.style]) as t:
            if t and mx.command_function('checkstyle')(['--primary']) != 0:
                t.abort('Checkstyle warnings were found')

        with Task('Checkheaders', tasks, tags=[Tags.style]) as t:
            if t and mx.command_function('checkheaders')([]) != 0:
                t.abort('Checkheaders warnings were found')

        with Task('FindBugs', tasks, tags=[Tags.fullbuild]) as t:
            if t and mx.command_function('findbugs')([]) != 0:
                t.abort('FindBugs warnings were found')

        with Task('VerifyLibraryURLs', tasks, tags=[Tags.fullbuild]) as t:
            if t:
                mx.command_function('verifylibraryurls')([])

        if mx._primary_suite is mx._mx_suite:
            with Task('TestJMH', tasks, tags=[Tags.fullbuild]) as t:
                if t: mx_microbench.get_microbenchmark_executor().microbench(['--', '-foe', 'true', 'com.oracle.mxtool.bench.TestJMH'])

        if exists('jacoco.exec'):
            os.unlink('jacoco.exec')

        if args.jacocout is not None:
            _jacoco = 'append'
        else:
            _jacoco = 'off'

        for suiteRunner in _gate_runners:
            suite, runner = suiteRunner
            if args.all_suites or suite is mx.primary_suite():
                runner(args, tasks)

        if args.jacocout is not None:
            mx.command_function('jacocoreport')([args.jacocout])
            _jacoco = 'off'

    except KeyboardInterrupt:
        total.abort(1)

    except BaseException as e:
        import traceback
        traceback.print_exc()
        total.abort(str(e))

    total.stop()

    mx.log('Gate task times:')
    for t in tasks:
        mx.log('  ' + str(t.duration) + '\t' + t.title + ("" if not (Task.verbose and t.tags) else (' [' + ','.join(t.tags) + ']')))
    mx.log('  =======')
    mx.log('  ' + str(total.duration))

    if args.task_filter:
        Task.filters = None

def checkheaders(args):
    """check Java source headers against any required pattern"""
    failures = {}
    for p in mx.projects():
        if not p.isJavaProject():
            continue

        csConfig = join(mx.project(p.checkstyleProj).dir, '.checkstyle_checks.xml')
        if not exists(csConfig):
            mx.log('Cannot check headers for ' + p.name + ' - ' + csConfig + ' does not exist')
            continue
        dom = xml.dom.minidom.parse(csConfig)
        for module in dom.getElementsByTagName('module'):
            if module.getAttribute('name') == 'RegexpHeader':
                for prop in module.getElementsByTagName('property'):
                    if prop.getAttribute('name') == 'header':
                        value = prop.getAttribute('value')
                        matcher = re.compile(value, re.MULTILINE)
                        for sourceDir in p.source_dirs():
                            for root, _, files in os.walk(sourceDir):
                                for name in files:
                                    if name.endswith('.java') and name != 'package-info.java':
                                        f = join(root, name)
                                        with open(f) as fp:
                                            content = fp.read()
                                        if not matcher.match(content):
                                            failures[f] = csConfig
    for n, v in failures.iteritems():
        mx.log('{0}: header does not match RegexpHeader defined in {1}'.format(n, v))
    return len(failures)

_jacoco = 'off'

_jacoco_includes = []

def add_jacoco_includes(patterns):
    """
    Adds to the list of JaCoCo includes.
    """
    _jacoco_includes.extend(patterns)

_jacoco_excluded_annotations = ['@Test']

def add_jacoco_excluded_annotations(annotations):
    """
    Adds to the list of annotations which if present denote a class that should
    be excluded from JaCoCo analysis.
    """
    _jacoco_excluded_annotations.extend(annotations)

def get_jacoco_agent_args():
    '''
    Gets the args to be added to a VM command line for injecting the JaCoCo agent
    if use of JaCoCo has been requested otherwise returns None.
    '''
    if _jacoco == 'on' or _jacoco == 'append':
        jacocoagent = mx.library("JACOCOAGENT", True)

        includes = list(_jacoco_includes)
        baseExcludes = []
        for p in mx.projects():
            projsetting = getattr(p, 'jacoco', '')
            if projsetting == 'exclude':
                baseExcludes.append(p.name)
            if projsetting == 'include':
                includes.append(p.name + '.*')

        def _filter(l):
            # filter out specific classes which are already covered by a baseExclude package
            return [clazz for clazz in l if not any([clazz.startswith(package) for package in baseExcludes])]
        excludes = []
        for p in mx.projects():
            if p.isJavaProject():
                excludes += _filter(p.find_classes_with_annotations(None, _jacoco_excluded_annotations, includeInnerClasses=True).keys())
                excludes += _filter(p.find_classes_with_matching_source_line(None, lambda line: 'JaCoCo Exclude' in line, includeInnerClasses=True).keys())

        excludes += [package + '.*' for package in baseExcludes]
        agentOptions = {
                        'append' : 'true' if _jacoco == 'append' else 'false',
                        'bootclasspath' : 'true',
                        'includes' : ':'.join(includes),
                        'excludes' : ':'.join(excludes),
                        'destfile' : 'jacoco.exec'
        }
        return ['-javaagent:' + jacocoagent.get_path(True) + '=' + ','.join([k + '=' + v for k, v in agentOptions.items()])]
    return None

def jacocoreport(args):
    """create a JaCoCo coverage report

    Creates the report from the 'jacoco.exec' file in the current directory.
    Default output directory is 'coverage', but an alternative can be provided as an argument."""
    jacocoreport = mx.library("JACOCOREPORT", True)
    out = 'coverage'
    if len(args) == 1:
        out = args[0]
    elif len(args) > 1:
        mx.abort('jacocoreport takes only one argument : an output directory')

    includes = list(_jacoco_includes)
    for p in mx.projects():
        projsetting = getattr(p, 'jacoco', '')
        if projsetting == 'include' or projsetting == '':
            includes.append(p.name)

    includedirs = set()

    for p in mx.projects():
        projsetting = getattr(p, 'jacoco', '')
        if projsetting == 'exclude':
            continue
        for include in includes:
            if include in p.dir:
                includedirs.add(p.dir)

    for i in includedirs:
        bindir = i + '/bin'
        mx.ensure_dir_exists(bindir)

    mx.run_java(['-jar', jacocoreport.get_path(True), '--in', 'jacoco.exec', '--out', out] + sorted(includedirs))
