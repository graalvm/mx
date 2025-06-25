#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2007, 2021, Oracle and/or its affiliates. All rights reserved.
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

__all__ = [
    "Tags",
    "Task",
    "add_gate_argument",
    "add_gate_runner",
    "prepend_gate_runner",
    "add_omit_clean_args",
    "gate_clean",
    "check_gate_noclean_arg",
    "parse_tags_argument",
    "gate",
    "checkheaders",
    "JACOCO_EXEC",
    "add_jacoco_includes",
    "add_jacoco_excludes",
    "add_jacoco_excluded_annotations",
    "add_jacoco_whitelisted_packages",
    "get_jacoco_dest_file",
    "get_jacoco_agent_path",
    "get_jacoco_agent_args",
    "jacocoreport",
    "lcov_report",
    "coverage_upload",
    "sonarqube_upload",
    "make_test_report",
]

import os, re, time, json
import tempfile
import atexit
import zipfile
import urllib.parse
import urllib.request
import hashlib
import shutil
import glob
import sys
from os.path import join, exists, basename, abspath, dirname, isabs
from argparse import ArgumentParser
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import mx
from . import mx_util
from . import mx_javacompliance
from .mx_urlrewrites import rewriteurl
from .mx_javacompliance import JavaCompliance

"""
Predefined Task tags.
"""
class Tags:
    always = 'always'       # special tag that is always implicitly selected
    style = 'style'         # code style checks (without build)
    build = 'build'         # build
    ecjbuild = 'ecjbuild'   # build with ecj only
    fullbuild = 'fullbuild' # full build (including warnings, spotbugs and ide init)

"""
Context manager for a single gate task that can prevent the
task from executing or time and log its execution.
"""
class Task:
    # A list of strings. If not empty, only tasks whose title
    # matches at least one of the substrings in this list will return
    # a non-None value from __enter__. The body of a 'with Task(...) as t'
    # statement should check 't' and exit immediately if it is None.
    filters = []
    strict_filters = []  # Like `filters`, but the entire title must match
    log = True  # whether to log task messages
    dryRun = False
    startAtFilter = None
    filtersExclude = False

    tasks = []

    tags = None
    tagsExclude = False
    # map from tag to a pair [from(inclusive), to(exclusive)]
    tags_range = dict()
    # map from tag to count
    tags_count = dict()

    verbose = False
    startTime = None

    def tag_matches(self, _tags):
        for t in _tags:
            assert isinstance(t, str), f'{t} is not a string and thus not a valid tag'
            if Task.tags is not None and t in Task.tags: # pylint: disable=unsupported-membership-test
                if t not in Task.tags_range:
                    # no range restriction
                    return True
                else:
                    frm, to = Task.tags_range[t]
                    cnt = Task.tags_count[t]
                    # increment counter
                    Task.tags_count[t] += 1
                    if frm <= cnt < to:
                        return True
        return False

    def _timestamp(self, suffix):
        stamp = time.strftime('gate: %d %b %Y %H:%M:%S')
        if Task.startTime:
            duration = timedelta(seconds=time.time() - Task.startTime)
            # Strip microseconds and convert to a string
            duration = str(duration - timedelta(microseconds=duration.microseconds))
            # Strip hours if 0
            if duration.startswith('0:'):
                duration = duration[2:]
            stamp += f'(+{duration})'
        return stamp + suffix

    def __init__(self, title,
                 tasks=None,
                 disableJacoco=False,
                 tags=None,
                 legacyTitles=None,
                 description=None,
                 report=None):
        """
        :param report: if not None, then `make_test_report` is called when this task ends.
                 The component used for the report will be the name of the primary suite
                 if `report` is True otherwise it will use the value of `report`.
        """
        self.tasks = tasks
        self.title = title
        self.legacyTitles = legacyTitles or []
        self.skipped = False
        self.tags = tags
        self.description = description
        self.report = report
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
            elif len(Task.filters) > 0:
                assert len(Task.strict_filters) == 0, "A Task cannot have both `filters` and `strict_filters`"
                titles = [self.title] + self.legacyTitles
                if Task.filtersExclude:
                    self.skipped = any([f in t for t in titles for f in Task.filters])
                else:
                    self.skipped = not any([f in t for t in titles for f in Task.filters])
            elif len(Task.strict_filters) > 0:
                assert len(Task.filters) == 0, "A Task cannot have both `filters` and `strict_filters`"
                titles = [self.title] + self.legacyTitles
                if Task.filtersExclude:
                    self.skipped = any([f == t for t in titles for f in Task.strict_filters])
                else:
                    self.skipped = not any([f == t for t in titles for f in Task.strict_filters])
            if Task.tags is not None:
                if Task.tagsExclude:
                    self.skipped = all([t in Task.tags for t in self.tags]) if tags else False # pylint: disable=unsupported-membership-test
                else:
                    _tags = self.tags if self.tags else []
                    self.skipped = not self.tag_matches(_tags)
        if not self.skipped:
            self.start = time.time()
            self.end = None
            self.duration = None
            self.disableJacoco = disableJacoco
            if Task.log:
                mx.log(self._timestamp(' BEGIN: ') + title)
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
            if self.report is not None:
                test_results = [{
                    'name': self.title,
                    'status': "PASSED" if exc_value is None else "FAILED",
                    'duration': str(self.duration)
                }]
                component = mx.primary_suite().name if self.report is True else str(self.report)
                make_test_report(test_results, self.title, component=component)

    @staticmethod
    def _human_fmt(num):
        for unit in ['', 'K', 'M', 'G']:
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}B"
            num /= 1024.0
        return f"{num:.1f}TB"

    @staticmethod
    def _diskstats():
        if hasattr(os, 'statvfs'):
            _, f_frsize, f_blocks, _, f_bavail, _, _, _, _, _ = os.statvfs(os.getcwd())
            total = f_frsize * f_blocks
            free = f_frsize * f_bavail
            return f' [disk (free/total): {Task._human_fmt(free)}/{Task._human_fmt(total)}]'
        return ''

    def stop(self):
        if Task.log:
            self.end = time.time()
            self.duration = timedelta(seconds=self.end - self.start)
            mx.log(self._timestamp(' END:   ') + self.title + ' [' + str(self.duration) + ']' + Task._diskstats())
        return self
    def abort(self, codeOrMessage):
        if Task.log:
            self.end = time.time()
            self.duration = timedelta(seconds=self.end - self.start)
            mx.log(self._timestamp(' ABORT: ') + self.title + ' [' + str(self.duration) + ']' + Task._diskstats())
            mx.abort(codeOrMessage)
        return self

    def __repr__(self):
        return "Task: " + self.title

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
    parser.add_argument('--omit-clean-all', action='store_false', dest='cleanAll', help='omit cleaning non-default build targets')
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
        args.cleanAll = False
    cleanArgs = []
    if not args.cleanNative:
        cleanArgs.append('--no-native')
    if not args.cleanJava:
        cleanArgs.append('--no-java')
    if not args.cleanDist:
        cleanArgs.append('--no-dist')
    if args.cleanAll:
        cleanArgs.append('--all')
    return cleanArgs

def parse_tags_argument(tags_arg, exclude):
    pattern = re.compile(r"^(?P<tag>[^:]*)(?::(?P<from>\d+):(?P<to>\d+)?)?$")
    tags = tags_arg.split(',')
    Task.tags = []
    for tag_spec in tags:
        m = pattern.match(tag_spec)
        if not m:
            mx.abort(f'--tags option requires the format `name[:from:[to]]`: {tag_spec}')
        (tag, t_from, t_to) = m.groups()
        if t_from:
            if exclude:
                mx.abort(f'-x option cannot be used tag ranges: {tag_spec}')
            frm = int(t_from)
            to = int(t_to) if t_to else sys.maxsize
            # insert range tuple
            Task.tags_range[tag] = (frm, to)
            # sanity check
            if to <= frm:
                mx.abort(f'`from` must be less than `to` for tag ranges: {tag_spec}')
            # init counter
            Task.tags_count[tag] = 0
        Task.tags.append(tag)


_command_level = 0
def gate(args):
    """run the tests used to validate a push

    If this command exits with a 0 exit code, then the gate passed."""
    default_summary = ['duration', 'title', 'description', 'tags']

    parser = ArgumentParser(prog='mx gate')
    add_omit_clean_args(parser)
    parser.add_argument('--all-suites', action='store_true', help='run gate tasks for all suites, not just the primary suite')
    parser.add_argument('--dry-run', action='store_true', help='just show the tasks that will be run without running them')
    parser.add_argument('-x', action='store_true', help='makes --task-filter, --strict-task-filter, or --tags an exclusion instead of inclusion filter')
    jacoco = parser.add_mutually_exclusive_group()
    jacoco.add_argument('--jacocout', help='specify the output directory for jacoco report')
    jacoco.add_argument('--jacoco-zip', help='specify the output zip file for jacoco report')
    parser.add_argument('--jacoco-omit-excluded', action='store_true', help='omit excluded files from jacoco report')
    parser.add_argument('--jacoco-omit-src-gen', action='store_true', help='omit excluded files from jacoco report')
    parser.add_argument('--jacoco-format', default=None, help='Jacoco output format', choices=['html', 'xml', 'lcov'])
    parser.add_argument('--jacoco-relativize-paths', '--jacoco-generic-paths', action='store_true', help='Make source file paths in LCOV repo based (i.e. <repo name>/<repo path>)')
    parser.add_argument('--strict-mode', action='store_true', help='abort if a task cannot be executed due to missing tool configuration')
    parser.add_argument('--no-warning-as-error', action='store_true', help='compile warnings are not treated as errors')
    parser.add_argument('-B', dest='extra_build_args', action='append', metavar='<build_args>', help='append additional arguments to mx build commands used in the gate')
    parser.add_argument('-p', '--partial', help='run only a subset of the tasks in the gate (index/total). Eg. "--partial 2/5" runs the second fifth of the tasks in the gate. Tasks with tag build are repeated for each run.')
    summary = parser.add_mutually_exclusive_group()
    summary.add_argument('--summary', action='store_const', const=default_summary, default=None, help='print a human readable summary of the executed tasks')
    summary.add_argument('--summary-format', dest='summary', action='store', default=None, help='--summary with a comma separated list of entries. Possible values ' + str(default_summary))
    filtering = parser.add_mutually_exclusive_group()
    filtering.add_argument('-t', '--task-filter', help='comma separated list of substrings to select subset of tasks to be run')
    filtering.add_argument('-T', '--strict-task-filter', help='comma separated list of strings to select subset of tasks to be run. The entire task name must match.')
    filtering.add_argument('-s', '--start-at', help='substring to select starting task')
    filtering.add_argument('--tags', help='comma separated list of tags to select subset of tasks to be run. Tags can have a range specifier `name[:from:[to]]`.'
                           'If present only the [from,to) tasks are executed. If `to` is omitted all tasks starting with `from` are executed.')

    for a, k in _extra_gate_arguments:
        parser.add_argument(*a, **k)
    args = parser.parse_args(args)
    cleanArgs = check_gate_noclean_arg(args)

    if args.dry_run:
        Task.dryRun = True
    if args.start_at:
        Task.startAtFilter = args.start_at
    elif args.task_filter:
        Task.filters = args.task_filter.split(',')
        Task.filtersExclude = args.x
    elif args.strict_task_filter:
        Task.strict_filters = args.strict_task_filter.split(',')
        Task.filtersExclude = args.x
    elif args.tags:
        parse_tags_argument(args.tags, args.x)
        Task.tagsExclude = args.x
        if not Task.tagsExclude:
            # implicitly include 'always'
            Task.tags += [Tags.always]
    elif args.x:
        mx.abort('-x option cannot be used without --task-filter, --strict-task-filter, or the --tags option')

    if args.jacoco_zip:
        args.jacocout = 'html'

    if not args.extra_build_args:
        args.extra_build_args = []

    if args.partial:
        partialArgs = args.partial.split('/')
        if len(partialArgs) != 2:
            mx.abort('invalid partial argument specified')

        selected = int(partialArgs[0]) - 1
        total = int(partialArgs[1])
        if selected < 0 or selected >= total:
            mx.abort('out of bounds partial argument specified')

        tasks = _collect_tasks(cleanArgs, args)

        # build and always tags must be run by every partial gate run
        alwaysTags = [Tags.always, Tags.build]
        buildTasks = [task for task in tasks if not task.skipped and any([f in t for t in alwaysTags for f in task.tags])]
        nonBuildTasks = [task for task in tasks if not task.skipped and not any([f in t for t in alwaysTags for f in task.tags])]

        partialTasks = nonBuildTasks[selected::total]
        runTaskNames = [task.title for task in buildTasks + partialTasks]

        # We have already ran the filters in the dry run when collecting
        # so we can safely overwrite other filter settings.
        # We set `strict_filters` rather than `filters` because we want
        # exact matches, not matches by substring.
        Task.strict_filters = runTaskNames
        Task.filters = []
        Task.filtersExclude = False
        Task.tags = None

        mx.log('Running gate with partial tasks ' + args.partial + ". " + str(len(partialTasks)) + " out of " + str(len(nonBuildTasks)) + " non-build tasks selected.")
        if len(partialTasks) == 0:
            mx.log('No partial tasks left to run. Finishing gate early.')
            return

    Task.startTime = time.time()
    tasks = []
    total = Task('Gate')
    all_commands = []

    def mx_command_entered(command, *args, **kwargs):
        global _command_level
        if _command_level == 0:
            gate_command_str = command_in_gate_message(command.command, args, kwargs)
            # store the formatted gate command as the command might modify args/kwargs
            all_commands.append(gate_command_str)
            mx.log(mx.colorize('Running: ' + gate_command_str, color='blue'))
        _command_level = _command_level + 1

    def mx_command_left(_, *__, **___):
        global _command_level
        assert _command_level >= 0
        _command_level = _command_level - 1

    def print_commands_on_failure():
        sys.stdout.flush()
        sys.stderr.flush()

        mx.log_error('\nThe sequence of mx commands that were executed until the failure follows:\n')
        for gate_command_str in all_commands:
            mx.log_error(gate_command_str)

        mx.log_error('\nIf the previous sequence is incomplete or some commands were executed programmatically use:\n')
        mx.log_error(mx.current_mx_command() + '\n')

        sys.stderr.flush()

    def command_in_gate_message(command, command_args, kwargs):
        one_list = len(command_args) == 1 and isinstance(command_args[0], list)
        kwargs_absent = len(kwargs) == 0
        if one_list and kwargs_absent:  # gate command reproducible on the command line
            message = mx.current_mx_command([command] + command_args[0])
        else:
            args_message = '(Programmatically executed. '
            if not one_list:
                args_message += 'Args: ' + str(command_args)
            if not kwargs_absent:
                args_message += 'Kwargs: ' + str(kwargs)
            args_message += ')'
            message = mx.current_mx_command([command, args_message])
        return message

    try:
        mx._mx_commands.add_command_callback(mx_command_entered, mx_command_left)
        _run_gate(cleanArgs, args, tasks)
        if mx.primary_suite().getMxCompatibility().gate_strict_tags_and_tasks():
            if Task.tags is not None:
                for tag in Task.tags:  # pylint: disable=not-an-iterable
                    if not any((tag in task.tags for task in tasks)):
                        mx.abort(f'Tag "{tag}" not part of any task.\n'
                                 f'Run the following command to see all available tasks and their tags:\n'
                                 f'  mx -v gate --dry-run')
            elif len(Task.filters) > 0:
                for f in Task.filters:
                    if not any([f in t for task in tasks for t in [task.title] + task.legacyTitles]):
                        mx.abort(f'Filter "{f}" does not match any task.\n'
                                 f'Run the following command to see all available tasks and their tags:\n'
                                 f'  mx -v gate --dry-run')
            elif len(Task.strict_filters) > 0:
                for f in Task.strict_filters:
                    if not any([f == t for task in tasks for t in [task.title] + task.legacyTitles]):
                        mx.abort(f'Strict filter "{f}" does not match any task.\n'
                                 f'Run the following command to see all available tasks and their tags:\n'
                                 f'  mx -v gate --dry-run')
    except KeyboardInterrupt:
        total.abort(1)
    except BaseException as e:
        import traceback
        traceback.print_exc()
        print_commands_on_failure()
        total.abort(str(e))
    finally:
        mx._mx_commands.remove_command_callback(mx_command_entered, mx_command_left)

    total.stop()

    if args.summary:
        mx.log('Gate task summary:')
        res = [{'duration': str(t.duration), 'title': t.title, 'tags': f"[{', '.join(t.tags)}]" if t.tags else '', 'description': t.description or ''} for t in tasks]
        # collect lengths
        maxLengths = {}
        for e in res:
            for key in e.keys():
                maxLengths[key + 'Max'] = max(maxLengths.get(key + 'Max', 0), len(e[key]))
        # build format string
        fmt = '  '
        args_summary = args.summary
        if not isinstance(args_summary, list):
            args_summary = args_summary.split(',')
        if args.dry_run:
            args_summary.remove('duration')
        for entry in args_summary:
            if entry + 'Max' in maxLengths:
                fmt += '  {{{0}:<{{{0}Max}}}}'.format(entry)
            else:
                mx.abort(f"Unknown entry supplied to `mx gate --summary-format`: {entry}\nKnown entries are: {', '.join(default_summary)}")
        for e in res:
            # Python >= 3.5 could use {**e, **maxLengths} directly
            values = e.copy()
            values.update(maxLengths)
            mx.log(fmt.format(**values))
    else:
        mx.log('Gate task times:')
        for t in tasks:
            mx.log('  ' + str(t.duration) + '\t' + t.title + ("" if not (Task.verbose and t.tags) else (' [' + ','.join(t.tags) + ']')))
        mx.log('  =======')
        mx.log('  ' + str(total.duration))

    if args.task_filter:
        Task.filters = []

def _collect_tasks(cleanArgs, args):
    prevDryRun = Task.dryRun
    prevLog = Task.log
    Task.dryRun = True
    Task.log = False
    tasks = []
    try:
        _run_gate(cleanArgs, args, tasks)
    finally:
        Task.dryRun = prevDryRun
        Task.log = prevLog
    return tasks


def _run_mx_suite_tests():
    """
    Mx suite specific tests.
    """
    mx_javacompliance._test()

    # Ensure mx_util.py only imports from the Python standard library
    mx_util_py = join(dirname(__file__), 'mx_util.py')
    with open(mx_util_py) as fp:
        content = fp.read()
        matches = list(re.finditer(r'(import +mx_|from +mx_)', content))
        if matches:
            nl = '\n'
            violations = nl.join([f'line {content[0:m.start()].count(nl) + 1}: {m.group()}' for m in matches])
            assert False, f'{mx_util_py} must only import from the Python standard library:{nl}{violations}'

    from tests import os_arch_tests, bench_rules_tests, java_argument_file_test
    os_arch_tests.tests()
    bench_rules_tests.tests()
    java_argument_file_test.tests()

    from tests import code_owners_tests, stoml_tests
    code_owners_tests.tests()
    stoml_tests.tests()

    from tests import test_maven_projects
    test_maven_projects.tests()

    mx.checkmarkdownlinks(['--no-external', './**/*.md'])

    # (JDK, project_compliance, javaPreviewNeeded) -> expected javac args
    get_release_args_data = {
        (19, '19+', None):     ['-target', '19', '-source', '19'],
        (20, '19+', None):     ['-target', '19', '-source', '19'],
        (19, '19+', '19+'):    ['-target', '19', '-source', '19', '--enable-preview'],
        (20, '19+', '19+'):    ['-target', '20', '-source', '20', '--enable-preview'],
        (20, '19+', '19'):     ['-target', '20', '-source', '20'],
        (21, '19+', '19'):     ['-target', '20', '-source', '20'],
        (22, '19+', '20'):     ['-target', '21', '-source', '21'],
        (22, '19+', '19..20'): ['-target', '21', '-source', '21'],
    }
    for k, expect in get_release_args_data.items():
        jdk_compliance = JavaCompliance(k[0])
        project_compliance = JavaCompliance(k[1])
        javaPreviewNeeded = JavaCompliance(k[2]) if k[2] else None
        actual = mx.JavacLikeCompiler.get_release_args(jdk_compliance, project_compliance, javaPreviewNeeded)
        assert actual == expect, f'{k}: {actual} != {expect}'


    with tempfile.TemporaryDirectory(prefix="SafeFileCreation_test") as tmp_dir:
        from multiprocessing import Process
        cpus = mx.cpu_count()
        processes = []
        print(f'SafeFileCreation_test: starting {cpus} processes')
        for _ in range(cpus):
            p = Process(target=mx_util._create_tmp_files, args=(tmp_dir, 1000,))
            p.start()
            processes.append(p)
        print(f'SafeFileCreation_test: joining {cpus} processes')
        errors = 0
        for p in processes:
            p.join()
            if p.exitcode != 0:
                errors += 1
        assert errors == 0, f'{errors} SafeFileCreation_test subprocesses exited with an error'

    if mx.is_windows():
        def win(s, min_length=0):
            extra = min_length - len(s)
            if extra > 0:
                padding = 'X' * extra
                s += padding
            return s.replace('/', '\\')

        def _test(value, expect, open_fp):
            actual = mx._safe_path(value)
            if actual != expect:
                nl = os.linesep
                assert False, f'Failed safe_path test{nl} input: {value} (len={len(value)}){nl}expect: {expect} (len={len(expect)}){nl}actual: {actual} (len={len(actual)})'
            if open_fp and value != open_fp.name:
                try:
                    with mx.open(value, 'w') as fp:
                        fp.write('blah')
                    with mx.open(value, 'r') as fp:
                        contents = fp.read()
                        assert contents == 'blah', contents
                finally:
                    if os.path.exists(value):
                        os.unlink(value)

        with tempfile.NamedTemporaryFile(prefix="safe_path_test", mode="w") as fp:
            cases = {
                win('C:/Home/mydir') : win('C:/Home/mydir'),
                win('C:/Home/mydir', 258) : win('C:/Home/mydir', 258),
                win('C:/Home/mydir', 259) : win('//?/') + win('C:/Home/mydir', 259),
                win('C:/Home/mydir', 260) : win('//?/') + win('C:/Home/mydir', 260),
                win('//Mac/Home/mydir') : win('//Mac/Home/mydir'),
                win('//Mac/Home/mydir', 258) : win('//Mac/Home/mydir', 258),
                win('//Mac/Home/mydir', 259) : win('//?/UNC/') + win('Mac/Home/mydir', 257),
                win('//Mac/Home/mydir', 260) : win('//?/UNC/') + win('Mac/Home/mydir', 258),
                win(fp.name) : win(fp.name),
                win(fp.name, 258) : win(fp.name, 258),
                win(fp.name, 259) : win('//?/') + win(fp.name, 259),
                win(fp.name, 260) : win('//?/') + win(fp.name, 260),
            }
            for value, expect in cases.items():
                _test(value, expect, fp if value.startswith(fp.name) else None)

def _run_gate(cleanArgs, args, tasks):
    global _jacoco
    with Task('Versions', tasks, tags=[Tags.always]) as t:
        if t:
            mx.command_function('version')(['--oneline'])
            mx.command_function('sversions')([])
            mx.log(f"Python version: {sys.version_info}")

    with Task('JDKReleaseInfo', tasks, tags=[Tags.always]) as t:
        if t:
            jdkDirs = os.pathsep.join([mx.get_env('JAVA_HOME', ''), mx.get_env('EXTRA_JAVA_HOMES', '')])
            for jdkDir in jdkDirs.split(os.pathsep):
                release = join(jdkDir, 'release')
                if exists(release):
                    mx.log('==== ' + jdkDir + ' ====')
                    with open(release) as fp:
                        mx.log(fp.read().strip())

    if mx.primary_suite() is mx._mx_suite:
        with Task('MxTests', tasks, tags=[Tags.always]) as t:
            if t:
                _run_mx_suite_tests()

    with Task('VerifyMultiReleaseProjects', tasks, tags=[Tags.always]) as t:
        if t:
            mx.command_function('verifymultireleaseprojects')([])

    for suiteRunner in _pre_gate_runners:
        suite, runner = suiteRunner
        if args.all_suites or suite is mx.primary_suite():
            runner(args, tasks)

    if mx.primary_suite().getMxCompatibility().gate_run_pyformat():
        with Task("Format python code", tasks, tags=[Tags.style]) as t:
            if t:
                if mx.command_function("pyformat")(["--dry-run"]) != 0:
                    mx.abort_or_warn("Python formatting tools not configured correctly", args.strict_mode)

    with Task('Pylint', tasks, tags=[Tags.style]) as t:
        if t:
            if mx.command_function('pylint')(['--primary']) != 0:
                mx.abort_or_warn('Pylint not configured correctly. Cannot execute Pylint task.', args.strict_mode)

    if not args.noClean:
        gate_clean(cleanArgs, tasks, tags=[Tags.build, Tags.fullbuild, Tags.ecjbuild])

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

    with Task('BuildWithEcj', tasks, tags=[Tags.fullbuild, Tags.ecjbuild], legacyTitles=['BuildJavaWithEcj']) as t:
        if t:
            defaultBuildArgs = ['-p']
            if not args.no_warning_as_error:
                defaultBuildArgs += ['--warning-as-error']
            if not mx.get_env('JDT'):
                defaultBuildArgs += ['--jdt=builtin']
            mx.command_function('build')(defaultBuildArgs + args.extra_build_args)
            fullbuild = True if Task.tags is None else Tags.fullbuild in Task.tags # pylint: disable=unsupported-membership-test
            if fullbuild:
                gate_clean(cleanArgs + ['--keep-logs'], tasks, name='CleanAfterEcjBuild', tags=[Tags.fullbuild])

    with Task('BuildWithJavac', tasks, tags=[Tags.build, Tags.fullbuild], legacyTitles=['BuildJavaWithJavac']) as t:
        if t:
            defaultBuildArgs = ['-p']
            if not args.no_warning_as_error:
                defaultBuildArgs += ['--warning-as-error']
            mx.command_function('build')(defaultBuildArgs + ['--force-javac'] + args.extra_build_args)

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
                mx.abort_or_warn('ECLIPSE_EXE environment variable not set. Cannot execute CodeFormatCheck task.', args.strict_mode)

    with Task('Checkstyle', tasks, tags=[Tags.style]) as t:
        if t and mx.command_function('checkstyle')(['--primary']) != 0:
            t.abort('Checkstyle warnings were found')

    with Task('SpotBugs', tasks, tags=[Tags.fullbuild]) as t:
        _spotbugs_strict_mode = args.strict_mode and mx.primary_suite().getMxCompatibility().gate_spotbugs_strict_mode()
        if t and mx.command_function('spotbugs')(['--strict-mode'] if _spotbugs_strict_mode else []) != 0:
            t.abort('SpotBugs warnings were found')

    jacoco_exec = get_jacoco_dest_file()
    if exists(jacoco_exec):
        os.unlink(jacoco_exec)

    if args.jacocout is not None:
        _jacoco = 'append'
    else:
        _jacoco = 'off'

    for suiteRunner in _gate_runners:
        suite, runner = suiteRunner
        if args.all_suites or suite is mx.primary_suite():
            runner(args, tasks)

    if args.jacocout is not None:
        jacoco_args = [args.jacocout]
        if args.jacoco_omit_excluded:
            jacoco_args = ['--omit-excluded'] + jacoco_args
        if args.jacoco_format:
            jacoco_args = ['--format', args.jacoco_format] + jacoco_args
        if args.jacoco_relativize_paths:
            jacoco_args += ['--relativize-paths']
        if args.jacoco_omit_src_gen:
            jacoco_args += ['--exclude-src-gen']
        mx.command_function('jacocoreport')(jacoco_args)
        _jacoco = 'off'
    if args.jacoco_zip is not None:
        mx.log(f'Creating JaCoCo report archive: {args.jacoco_zip}')
        with zipfile.ZipFile(args.jacoco_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(jacoco_exec, join(args.jacocout, jacoco_exec))
            for root, _, files in os.walk(args.jacocout):
                for f in files:
                    zf.write(os.path.join(root, f))
        mx.log('Archiving done.')

def checkheaders(args):
    """check Java source headers against any required pattern"""
    mx.log('The checkheaders command is obsolete.  The checkstyle or checkcopyrights command performs\n'\
           'the required checks depending on the mx configuration.')
    return 0


JACOCO_EXEC = None

_jacoco = 'off'

_jacoco_includes = []
_jacoco_excludes = []

def add_jacoco_includes(patterns):
    """
    Adds to the list of JaCoCo includes.
    """
    global _jacoco_includes
    global _jacoco_excludes
    _jacoco_includes.extend(patterns)
    # .* is explicit on include patterns so handle appropriately
    for pattern in patterns:
        if pattern.endswith('.*'):
            _jacoco_excludes = [exclude for exclude in _jacoco_excludes if not exclude.startswith(pattern[:-2])]
        else:
            _jacoco_excludes = [exclude for exclude in _jacoco_excludes if exclude != pattern]

def add_jacoco_excludes(patterns):
    """
    Adds to the list of JaCoCo excludes.
    """
    global _jacoco_includes
    global _jacoco_excludes
    _jacoco_excludes.extend(patterns)
    # .* is implicit on exclude patterns, but not include patterns
    for pattern in patterns:
        _jacoco_includes = [include for include in _jacoco_includes if not include.startswith(pattern)]


_jacoco_excluded_annotations = ['@Test']

def add_jacoco_excluded_annotations(annotations):
    """
    Adds to the list of annotations which if present denote a class that should
    be excluded from JaCoCo analysis.
    """
    _jacoco_excluded_annotations.extend(annotations)

_jacoco_whitelisted_packages = []

def add_jacoco_whitelisted_packages(packages):
    """
    Adds to the list of JaCoCo whitelisted packages.
    """
    _jacoco_whitelisted_packages.extend(packages)

def _jacoco_is_package_whitelisted(package):
    if not _jacoco_whitelisted_packages:
        return True
    return any(package.startswith(w) for w in _jacoco_whitelisted_packages)


def _jacoco_excludes_includes():
    """
    Gets a tuple of lists, the classes to include/exclude respectively in JaCoco execution analysis.
    See https://www.eclemma.org/jacoco/trunk/doc/agent.html for details on the "includes" and "excludes" agent options.
    """
    includes = list(_jacoco_includes)
    baseExcludes = set(_jacoco_excludes)
    excludes = []
    excluded_projects = set()
    aps = mx.annotation_processors()
    for p in mx.projects():
        if p.isJavaProject():
            projsetting = getattr(p, 'jacoco', '')
            assert isinstance(projsetting, str), f'jacoco must be a string, not a {type(projsetting)}'
            if not _jacoco_is_package_whitelisted(p.name):
                pass
            elif projsetting == 'exclude' or p.name in baseExcludes or p in aps:
                excluded_projects.add(p.name)
                excludes.extend((package + '.*' for package in p.defined_java_packages()))
            elif projsetting == 'include':
                includes.extend((package + '.*' for package in p.defined_java_packages()))
            packagelist = getattr(p, 'jacocoExcludePackages', [])
            assert isinstance(packagelist, list), f'jacocoExcludePackages must be a list, not a {type(packagelist)}'
            for packagename in packagelist:
                excludes.append(packagename + ".*")
    if _jacoco_whitelisted_packages:
        includes.extend((x + '.*' for x in _jacoco_whitelisted_packages))

    def _filter(l):
        # filter out specific classes which are already covered by a baseExclude
        return [clazz for clazz in l if not any([clazz.startswith(package) for package in baseExcludes])]

    for p in mx.projects():
        if p.isJavaProject() and p.name not in excluded_projects and _jacoco_is_package_whitelisted(p.name):
            excludes += _filter(
                p.find_classes_with_annotations(None, _jacoco_excluded_annotations, includeInnerClasses=True,
                                                includeGenSrc=True).keys())
            excludes += _filter(p.find_classes_with_matching_source_line(None, lambda line: 'JaCoCo Exclude' in line,
                                                                         includeInnerClasses=True,
                                                                         includeGenSrc=True).keys())
    return excludes, includes

def get_jacoco_dest_file():
    return JACOCO_EXEC or mx.get_opts().jacoco_dest_file

def jacoco_library():
    # Might be not available in source bundles
    return mx.library('JACOCOAGENT_0.8.13', fatalIfMissing=False)

def get_jacoco_agent_path(resolve):
    jacoco_lib = jacoco_library()
    if jacoco_lib is None:
        mx.abort("The JaCoCo library is not defined")
    return jacoco_lib.get_path(resolve)

def get_jacoco_agent_args(jacoco=None, agent_option_prefix=''):
    '''
    Gets the args to be added to a VM command line for injecting the JaCoCo agent
    if use of JaCoCo has been requested otherwise returns None.
    '''
    if jacoco is None:
        jacoco = _jacoco

    if jacoco in ('on', 'append'):
        excludes, includes = _jacoco_excludes_includes()
        agent_options = ','.join((k + '=' + v for k, v in {
            'append' : 'true' if jacoco == 'append' else 'false',
            'inclbootstrapclasses' : 'true',
            'includes' : ':'.join(includes),
            'excludes' : ':'.join(excludes),
            'destfile' : get_jacoco_dest_file(),
        }.items()))

        agent_path = get_jacoco_agent_path(True)
        agent_args = f'{agent_option_prefix}-javaagent:{agent_path}={agent_options}'

        # Use java args file to handle long command lines
        mxbuild_dir = Path("mxbuild")
        argsfile_dir = mxbuild_dir.joinpath("jacoco") if mxbuild_dir.exists() else Path.cwd()
        now = datetime.now().isoformat().replace(':', '_')
        argsfile_dir.mkdir(exist_ok=True)
        argsfile = argsfile_dir.joinpath(f"agent-{now}.argsfile").absolute()
        mx.log(f"JaCoCo agent config: '{argsfile}'")
        if not mxbuild_dir.exists() and not mx.get_opts().verbose:
            # Remove argsfile at exit if not in a mxbuild dir and not verbose
            atexit.register(os.remove, str(argsfile))
        argsfile.write_text(agent_args)
        return [f'@{argsfile}']
    return None

def jacocoreport(args, exec_files=None):
    """Create a JaCoCo coverage report

    Parses the supplied arguments and creates a coverage report from Jacoco exec files. By default, the file returned
    by :get_jacoco_dest_file: is used. This is typically the 'jacoco.exec' file in the current directory. Alternatively,
    you can specify a list of JaCoCo files to use with the `exec_files` parameter.

    :param list args: a list of arguments to parse.
    :param list exec_files: a list of jacoco.exec files to use instead of the one returned by :get_jacoco_dest_file:.
    """
    _jacocoreport(args, exec_files)

def _jacocoreport(args, exec_files=None):
    """
    :return: the included projects and excludes used for this report
    """

    parser = ArgumentParser(prog='mx jacocoreport')
    parser.add_argument('--format', help='Export format', default='html', choices=['html', 'xml', 'lcov', 'lcov+html'])
    parser.add_argument('--omit-excluded', action='store_true', help='Omit excluded files from report')
    parser.add_argument('--exclude-src-gen', action='store_true', help='Omit generated source files from report')
    parser.add_argument('--relativize-paths', '--generic-paths', action='store_true', help='Convert LCOV source file paths to <repo name>/<repo root relative path>. '
                        'For example, convert /tmp/workspace/mx/java/ClasspathDump.java to mx/java/ClasspathDump.java')
    parser.add_argument('--extra-lcov', help='Comma separated urls, files or globs with existing LCOV output that should also be processed when --format=lcov+html')
    parser.add_argument('output_directory', help='Output directory', default='coverage', nargs='?')
    args = parser.parse_args(args)

    return _make_coverage_report(args.output_directory,
                                 fmt=args.format,
                                 exec_files=exec_files,
                                 omit_excluded=args.omit_excluded,
                                 exclude_generated_sources=args.exclude_src_gen,
                                 relativize_lcov_paths=args.relativize_paths,
                                 extra_lcov=args.extra_lcov)

def lcov_report(args):
    """Create an html coverage report using genhtml

    Creates a coverage report by first converting a Jacoco exec output to LCOV and then
    feeding the LCOV to genhtml (https://ltp.sourceforge.net/coverage/lcov/genhtml.1.php).

    :param list args: a list of arguments to parse.
    """

    parser = ArgumentParser(prog='mx lcov-report')
    parser.add_argument('--extra-lcov', help='Comma separated urls, files or globs with existing LCOV output that should '
                        'also be processed')
    parser.add_argument('output_directory', help='Output directory', default='coverage', nargs='?')
    args = parser.parse_args(args)

    _make_coverage_report(args.output_directory,
                                 fmt='lcov+html',
                                 omit_excluded=True,
                                 exclude_generated_sources=True,
                                 relativize_lcov_paths=True,
                                 extra_lcov=args.extra_lcov)

def _make_coverage_report(output_directory,
                          exec_files=None,
                          fmt='lcov+html',
                          omit_excluded=True,
                          exclude_generated_sources=True,
                          relativize_lcov_paths=True,
                          extra_lcov=None):
    """
    :return: the included projects and excludes used for this report
    """
    if fmt == 'lcov+html':
        import subprocess
        try:
            subprocess.run('genhtml --version'.split(), check=True)
        except OSError as e:
            mx.abort(f'The genhtml utility appears to be missing (error: {e}) and needs to be installed (e.g., `brew install lcov` or `dnf install lcov`)')

    dist_name = "MX_JACOCO_REPORT"
    mx.command_function("build")(['--dependencies', dist_name])
    dist = mx.distribution(dist_name)
    jdk = mx.get_jdk(dist.javaCompliance)

    # list of strings of the form "project-dir:binary-dir"
    includedirs = []
    includedprojects = []
    for p in mx.projects():
        projsetting = getattr(p, 'jacoco', '')
        if projsetting in ('include', '') and _jacoco_is_package_whitelisted(p.name):
            if isinstance(p, mx.ClasspathDependency):
                if omit_excluded and p.is_test_project():  # skip test projects when omit-excluded
                    continue
                if not getattr(p, 'defaultBuild', True):   # skip projects that are not built by default
                    if omit_excluded or not os.path.exists(p.classpath_repr(jdk)):
                        continue
                source_dirs = []
                if p.isJavaProject():
                    if exclude_generated_sources:
                        source_dirs += p.source_dirs()
                    else:
                        source_dirs += p.source_dirs() + [p.source_gen_dir()]
                includedirs.append(os.pathsep.join([p.dir, p.classpath_repr(jdk)] + source_dirs))
                includedprojects.append(p.name)

    def _run_reporter(exec_files, output_directory, extra_args=None):
        sink = lambda line: line
        out = None if mx.get_opts().verbose else sink

        files_arg = []
        if exec_files is None:
            exec_files = [get_jacoco_dest_file()]
        for exec_file in exec_files:
            files_arg += ['--in', exec_file]

        # Generate report
        jacaco_java_args = ['-jar', dist.path, '--out',
                 output_directory, '--format', fmt] + files_arg + (extra_args or []) + sorted(includedirs)
        jacaco_java_args_file = join(os.getcwd(), 'jacoco_command_args.txt')
        if jdk.javaCompliance > '8':
            # Pass jacaco args in an args file to avoid command line length issues on Windows
            with open(jacaco_java_args_file, mode="w") as fp:
                fp.writelines((a + os.linesep for a in jacaco_java_args))
                fp.flush()
            jacaco_java_args = ['@' + jacaco_java_args_file]

        mx.log(f'Analyzing coverage data in {", ".join(exec_files)}')
        mx.run_java(jacaco_java_args, jdk=jdk, addDefaultArgs=False, out=out)
        if jdk.javaCompliance > '8':
            os.unlink(jacaco_java_args_file)

        lcov_info = abspath(join(output_directory, 'lcov.info'))

        # Current working directory to be used when running genhtml
        genhtml_cwd = None

        # Transform file paths in LCOV to repo based paths
        if fmt.startswith('lcov'):
            if relativize_lcov_paths:
                genhtml_cwd_repo = None
                relativize_map = {}
                for s in mx.suites():
                    repo_name, _ = os.path.splitext(basename(urllib.parse.urlparse(s.vc.default_pull(s.vc_dir)).path))
                    repo_dir = s.vc_dir
                    relativize_map[repo_dir] = repo_name

                    repo_dir_parent = dirname(repo_dir)
                    if genhtml_cwd is None:
                        genhtml_cwd_repo = repo_dir
                        genhtml_cwd = repo_dir_parent
                    elif repo_dir_parent != genhtml_cwd and fmt == 'lcov+html':
                        mx.abort(f'Local repositories {genhtml_cwd_repo} and {repo_dir} do not share a common parent directory as required by --relativize-paths')

                lcov_info_tmp = lcov_info + '.tmp'
                with open(lcov_info) as fp_in, open(lcov_info_tmp, 'w') as fp_out:
                    for line in fp_in:
                        if line.startswith("SF:"):
                            sf_path = line[3:]
                            for repo_dir, repo_name in relativize_map.items():
                                if sf_path.startswith(repo_dir):
                                    line = line.replace(repo_dir, repo_name, 1)
                                    break
                        fp_out.write(line)
                shutil.move(lcov_info_tmp, lcov_info)
                mx.log(f'Generated LCOV coverage report with relativized paths in {lcov_info}')
            else:
                mx.log(f'Generated LCOV coverage report in {lcov_info}')

        if fmt == 'lcov+html':
            if genhtml_cwd is None:
                # If no CWD has been determined yet, use the parent directory
                # of the primary suite's repo root.
                genhtml_cwd = dirname(mx.primary_suite().vc_dir)

            def copy_lcov(source, fp_in, fp_out):
                """
                Copies the LCOV data from `fp_in` originating from `source` to `fp_out`.
                In the copying process:
                  - file paths are transformed to use the separator for the current OS.
                  - coverage data is removed for files that do not exist (e.g., a file
                    that has subsequently been deleted or renamed since coverage data
                    was gathered).
                """
                skipping = False
                line_no = 1
                for line in fp_in:
                    if line.startswith("SF:"):
                        if os.sep == '/':
                            if '\\' in line: line = line.replace('\\', '/')
                        else:
                            if '/' in line: line = line.replace('/', '\\')

                        sf_path = line[3:].strip()
                        full_path = sf_path
                        if not isabs(sf_path):
                            full_path = join(genhtml_cwd, sf_path)
                        if not exists(full_path):
                            mx.warn(f'{source}:{line_no}: {full_path} does not exist - skipping')
                            skipping = True
                    elif line.startswith('end_of_record\n'):
                        skipping = False

                    if not skipping:
                        fp_out.write(line)
                    line_no += 1

            genhtml_lcov_info = abspath(join(output_directory, 'genhtml_lcov.info'))
            if exists(genhtml_lcov_info):
                os.remove(genhtml_lcov_info)
            shutil.copy(lcov_info, genhtml_lcov_info)

            if extra_lcov:
                def has_gzip_magic_number(path):
                    """Determines if the content of `path` is gzipped"""
                    with open(path, 'rb') as cache_fp:
                        gzip_header = cache_fp.read(2)
                        return len(gzip_header) == 2 and gzip_header == b'\x1f\x8b'

                with open(genhtml_lcov_info, 'a') as fp:
                    lcovs = OrderedDict()
                    for e in extra_lcov.split(','):
                        if e.startswith('https://') or e.startswith('http://'):

                            def download_and_cache(url):
                                d = hashlib.sha1()
                                d.update(url.encode())
                                url_hash = d.hexdigest()
                                cache_dir = mx_util.ensure_dir_exists(abspath(join(output_directory, '.cache', url_hash)))
                                cache = join(cache_dir, 'lcov.info')
                                cache_url = join(cache_dir, 'url')
                                if not exists(cache):
                                    data = join(cache_dir, 'data')
                                    with open(data, 'wb') as cache_fp:
                                        mx.log(f'Downloading {url} to {cache}')
                                        cache_fp.write(urllib.request.urlopen(url).read())
                                    if has_gzip_magic_number(data):
                                        import gzip
                                        with gzip.open(data, 'rt') as data_in, open(cache, 'w') as cache_out:
                                            cache_out.write(data_in.read())
                                    else:
                                        shutil.move(data, cache)
                                    with open(cache_url, 'w') as cache_url_fp:
                                        print(url, file=cache_url_fp)
                                else:
                                    mx.log(f'Reading cached {url} from {cache}. Delete {cache} to force re-downloading')
                                return cache

                            cache = download_and_cache(e)
                            lcovs[cache] = cache
                        else:
                            for p in glob.glob(e):
                                lcovs[abspath(p)] = abspath(p)
                    for source, lcov in lcovs.items():
                        if has_gzip_magic_number(lcov):
                            import gzip
                            with gzip.open(lcov, 'rt') as lcov_in:
                                copy_lcov(source, lcov_in, fp)
                        else:
                            with open(lcov) as lcov_in:
                                copy_lcov(source, lcov_in, fp)

            genhtml_args = ['--legend', '--prefix', genhtml_cwd, '-o', abspath(output_directory), genhtml_lcov_info]

            mx.log(f'Generating HTML from LCOV with genhtml')
            mx.run(['genhtml'] + genhtml_args, cwd=genhtml_cwd, out=out)
            mx.log(f'Generated LCOV+HTML report in {join(output_directory, "index.html")}')
        elif fmt == 'html':
            mx.log(f'Generated HTML coverage report in {join(output_directory, "index.html")}')
        elif fmt == 'xml':
            mx.log(f'Generated XML coverage report in {join(output_directory, "jacoco.xml")}')

    output_directory = mx_util.ensure_dir_exists(abspath(output_directory))
    if not omit_excluded:
        _run_reporter(exec_files, output_directory)
        excludes = []
    else:
        with tempfile.NamedTemporaryFile(suffix="jacoco-report-exclude", mode="w") as fp:
            excludes, _ = _jacoco_excludes_includes()
            fp.writelines((e + "\n" for e in excludes))
            fp.flush()
            _run_reporter(exec_files, output_directory, ['--exclude-file', fp.name])
    return includedprojects, excludes

def _parse_java_properties(args):
    prop_re = re.compile('-D(?P<key>[^=]+)=(?P<value>.*)')
    remainder = []
    java_properties = {}
    for arg in args:
        m = prop_re.match(arg)
        if m:
            java_properties[m.group('key')] = m.group('value')
        else:
            remainder.append(arg)
    return java_properties, remainder


def _jacoco_excludes_includes_projects(limit_to_primary=False):
    includes = []
    excludes = []

    projects = mx.projects(limit_to_primary=limit_to_primary)
    for p in projects:
        if p.isJavaProject():
            projsetting = getattr(p, 'jacoco', '')
            if not _jacoco_is_package_whitelisted(p.name):
                excludes.append(p)
            elif projsetting == 'exclude':
                excludes.append(p)
            else:
                includes.append(p)
    return excludes, includes

def _jacoco_exclude_classes(projects):
    excludeClasses = {}

    for p in projects:
        r = p.find_classes_with_annotations(None, _jacoco_excluded_annotations, includeGenSrc=True)
        excludeClasses.update(r)
        r = p.find_classes_with_matching_source_line(None, lambda line: 'JaCoCo Exclude' in line, includeGenSrc=True)
        excludeClasses.update(r)
    return excludeClasses

def coverage_upload(args):
    parser = ArgumentParser(prog='mx coverage-upload')
    parser.add_argument('--upload-url', required=False, default=mx.get_env('COVERAGE_UPLOAD_URL'), help='Format is like rsync: user@host:/directory')
    parser.add_argument('--build-name', required=False, default=mx.get_env('BUILD_NAME'))
    parser.add_argument('--build-url', required=False, default=mx.get_env('BUILD_URL'))
    parser.add_argument('--build-number', required=False, default=mx.get_env('BUILD_NUMBER'))
    args, other_args = parser.parse_known_args(args)
    if not args.upload_url:
        parser.print_help()
        return
    remote_host, remote_basedir = args.upload_url.split(':')
    if not remote_host:
        mx.abort(f'Cannot determine remote host from {args.upload_url}')

    primary = mx.primary_suite()
    if not primary.vc:
        mx.abort('coverage_upload requires the primary suite to be in a vcs repository')
    info = primary.vc.parent_info(primary.dir)
    rev = primary.vc.parent(primary.dir)
    if len(remote_basedir) > 0 and not remote_basedir.endswith('/'):
        remote_basedir += '/'
    remote_dir = f"{primary.name}_{datetime.fromtimestamp(info['author-ts']).strftime('%Y-%m-%d_%H_%M')}_{rev[:7]}"
    if args.build_name:
        remote_dir += '_' + args.build_name
    if args.build_number:
        remote_dir += '_' + args.build_number
    upload_dir = remote_basedir + remote_dir
    includes, excludes = _jacocoreport(['--omit-excluded'] + other_args)

    # Upload jar+sources
    coverage_sources = 'java_sources.tar.gz'
    coverage_binaries = 'java_binaries.tar.gz'

    with mx.Archiver(os.path.realpath(coverage_sources), kind='tgz') as sources, mx.Archiver(os.path.realpath(coverage_binaries), kind='tgz') as binaries:
        def _visit_deps(dep, edge):
            if dep.isJavaProject() and not dep.is_test_project() and getattr(dep, 'defaultBuild', True):
                binaries.zf.add(dep.output_dir(), dep.name)
                for d in dep.source_dirs():
                    sources.zf.add(d, dep.name)
                if os.path.exists(dep.source_gen_dir()):
                    sources.zf.add(dep.source_gen_dir(), dep.name)
        mx.walk_deps(mx.projects(), visit=_visit_deps)

    files = [get_jacoco_dest_file(), 'coverage', coverage_sources, coverage_binaries]
    print(f"Syncing {' '.join(files)} to {remote_host}:{upload_dir}")
    mx.run([
        'bash',
        '-c',
        r'tar -czf - {files} | ssh {remote} bash -c \'"mkdir -p {remotedir} && cd {remotedir} && cat | tar -x{verbose}z && chmod -R 755 ."\''
            .format(
                files=" ".join(files),
                remote=remote_host,
                remotedir=upload_dir,
                verbose='v' if mx._opts.verbose else '')
    ])
    def upload_string(content, path):
        mx.run(['ssh', remote_host, 'bash', '-c', 'cat > "' + path + '"'], stdin=content)

    upload_string(json.dumps({
        'timestamp': time.time(),
        'suite': primary.name,
        'revision': rev,
        'directory': remote_dir,
        'build_name': args.build_name,
        'build_url': args.build_url,
        'jdk_version': str(mx.get_jdk().version),
        'build_number': args.build_number,
        'primary_info': info,
        'excludes': [str(e) for e in excludes],
        'includes': [str(i) for i in includes]}), upload_dir + '/description.json')
    mx.run(['ssh', remote_host, 'bash', '-c', r'"(echo \[; for i in {remote_basedir}/*/description.json; do if \[ -s \$i \];then cat \$i; echo ,; fi done; echo null\]) |jq \"del(.. | .excludes?, .includes?)\" > {remote_basedir}/index.json"'.format(remote_basedir=remote_basedir)])
    upload_string("""<html>
<script language="javascript">
  function urlChange(url) {
    if (url.pathname !== "blank") {
      window.history.replaceState(null, null, url.pathname.replace("/coverage_upload/", "/coverage_upload/#"))
    }
  }
</script>
<frameset rows="40,*">
  <frame id="navigation" src="navigation.html"/>
  <frame id="content" src="" onload="urlChange(this.contentWindow.location);" />
</frameset>
</html>""", remote_basedir + '/index.html')
    js_library_url = rewriteurl("https://ajax.googleapis.com/ajax/libs/angularjs/1.7.7/angular.js")
    upload_string(r"""<html>
    <head>
        <script src="%js_library_url"></script>
        <script language="javascript">
        var App = angular.module('myApp', [])
            .controller('IndexCtrl', function IndexCtrl($scope, $http) {
                var hash = parent.window.location.hash;
                if(hash) {
                    hash = hash.substring(1, hash.length); // remove leading hash
                }
                $http.get('index.json').then(function(response, status) {
                    var data = response.data.filter(x => x != null);
                    /*
                        #GR-17399
                        Filter build that are unique per suite with revision as key and merge builds.
                    */
                    data = data
                        .filter(x => !x.hasOwnProperty('merge'))
                        .filter( // filter builds that are unique per suite with revision as key
                            x => !data
                                .filter(z => x != z && x.jdk_version == z.jdk_version && x.suite == z.suite) // exclude self build and build for other suites.
                                .map(z => z.revision) // map from array of build to array of revision
                                .includes(x.revision) // check if revision of x is index data.
                        ).concat(data.filter(x => x.hasOwnProperty('merge'))); // concat unique build with merged build.

                    data.sort((l,r) => r.timestamp - l.timestamp);
                    if(data.length > 0) {
                        var startdir;
                        if(hash) {
                            startdir = data.find(build => hash.includes(build.directory));
                            startdir.hash = hash;
                        }
                        if(!startdir) {
                            startdir = data[0];
                        }
                        $scope.directory = startdir;
                    }
                    $scope.data = data;
                });
                $scope.$watch('directory', (dir, olddir) => {
                    if(dir) {
                        var content = parent.document.getElementById("content");
                        var contentDocument = content.contentDocument || content.contentWindow.document;
                        var newpath;
                        if(!olddir){
                            newpath = "total.html";
                        }
                        else if(olddir.suite === dir.suite && ! contentDocument.location.href.includes('total.html') ) {
                            newpath = contentDocument.location.href.replace(olddir.directory, dir.directory);
                        } else {
                            newpath = dir.hasOwnProperty('hash') ? hash : dir.directory + "/coverage/";
                        }
                        contentDocument.location.href = newpath;
                        parent.window.history.replaceState(undefined, undefined, "#" + newpath.replace(/^.+coverage_upload\//, ""));
                    }
                });
                $scope.step = (i) => $scope.directory = $scope.data[$scope.data.indexOf($scope.directory)+i];
            });
        function copy(url) {
            var content = parent.document.getElementById("content");
            var contentDocument = content.contentDocument || content.contentWindow.document;
            var copyText = document.getElementById("copy");
            copyText.value = contentDocument.location.href.replace("coverage_upload/", "coverage_upload/#");
            copyText.select();
            document.execCommand("copy");
        }
        </script>
    </head>
    <body ng-app="myApp" ng-controller="IndexCtrl">
       <button ng-click="step(1)" ng-disabled="data.indexOf(directory) >= data.length-1">&lt;&lt;</button>
       <button ng-click="step(-1)" ng-disabled="data.indexOf(directory) <= 0">&gt;&gt;</button>
       <select ng-model="directory" ng-options="(i.timestamp*1000|date:'yy-MM-dd hh:mm') + ' ' + i.build_name + ' ' + i.revision.substr(0,8) group by i.suite for i in data"></select>
       <a href="{{directory.build_url}}" ng-if="directory.build_url" target="_blank">Build</a> Commit: {{directory.revision.substr(0,5)}}: {{directory.primary_info.description}}
       <input type="text" style="opacity: 0;width: 20;" id="copy" />
       <button style="float: right;" onclick="copy(window.location);">Share url</button>
    </body>
</html>""".replace("%js_library_url", js_library_url), remote_basedir + '/navigation.html')
    jquery_library_url = rewriteurl("http://ajax.googleapis.com/ajax/libs/jquery/3.5.1/jquery.min.js")
    upload_string(r""" <?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
    <meta http-equiv="Content-Type" content="text/html;charset=UTF-8" />
    <style>
        body,
        td {
            font-family: sans-serif;
            font-size: 10pt;
        }

        h1 {
            font-weight: bold;
            font-size: 18pt;
        }

        table.coverage {
            empty-cells: show;
            border-collapse: collapse;
        }

        table.coverage thead {
            background-color: #e0e0e0;
        }

        table.coverage thead td {
            white-space: nowrap;
            padding: 2px 14px 0px 6px;
            border-bottom: #b0b0b0 1px solid;
        }

        table.coverage thead td.bar {
            border-left: #cccccc 1px solid;
        }

        table.coverage thead td.ctr1 {
            text-align: right;
            border-left: #cccccc 1px solid;
        }

        table.coverage thead td.ctr2 {
            text-align: right;
            padding-left: 2px;
        }

        table.coverage thead td.sortable {
            cursor: pointer;
            background-position: right center;
            background-repeat: no-repeat;
        }

        table.coverage tbody td {
            white-space: nowrap;
            padding: 2px 6px 2px 6px;
            border-bottom: #d6d3ce 1px solid;
        }

        table.coverage tbody tr:hover {
            background: #f0f0d0 !important;
        }

        table.coverage tbody td.bar {
            border-left: #e8e8e8 1px solid;
        }

        table.coverage tbody td.ctr1 {
            text-align: right;
            padding-right: 14px;
            border-left: #e8e8e8 1px solid;
        }

        table.coverage tbody td.ctr2 {
            text-align: right;
            padding-right: 14px;
            padding-left: 2px;
        }
    </style>
    <title>Total latest graal coverage information</title>
    <script src="%jquery_library_url" type="text/javascript"></script>
    <script type="text/javascript">
        $(document).ready(function () {
            var groupBy = function (xs, key) {
                return xs.reduce(function (rv, x) {
                    (rv[x[key]] = rv[x[key]] || []).push(x);
                    return rv;
                }, {});
            };

            $.get('index.json', function (data) {
                var data = data.filter(x => x != null);
                /*
                    #GR-17399
                    Filter build that are unique per suite with revision as key and merge builds.
                */
                data = data
                    .filter(x => !x.hasOwnProperty('merge'))
                    .filter( // filter builds that are unique per suite with revision as key
                        x => !data
                            .filter(z => x != z && x.jdk_version == z.jdk_version && x.suite == z.suite) // exclude self build and build for other suites.
                            .map(z => z.revision) // map from array of build to array of revision
                            .includes(x.revision) // check if revision of x is index data.
                    ).concat(data.filter(x => x.hasOwnProperty('merge'))); // concat unique build with merged build.

                data.sort((l, r) => r.timestamp - l.timestamp);

                // Group index data by suite.
                data = groupBy(data, 'suite');

                // Get latest coverage data for each suite.
                for (const [key, value] of Object.entries(data)) {
                    data[key] = value[0];

                }

                for (const [suite_name, report] of Object.entries(data)) {

                    // Get Total Data for each suite for latest coverage report
                    if(suite_name === "consolidated"){
                        continue;
                    }
                    $.get(report.directory+"/coverage/index.html", function (data) {
                        var html = $(data);
                        var total_information = $('tfoot > tr', html);
                        var suite_link = "<a href='" + report.directory+"/coverage/index.html" + "' target='_blank'>" + suite_name + "<a/>";
                        // Add link element instend of total text.
                        $('td:first-child', total_information).html(suite_link);
                        // Add Total for each suite to tbody of this document
                        $('tbody').append(total_information);
                    });
                }
            });
        });
    </script>
</head>

<body>
    <h1>Total graal coverage information</h1>
    <table class="coverage" cellspacing="0" id="coveragetable">
        <thead>
            <tr>
                <td class="sortable" id="a" >Suite</td>
                <td class="down sortable bar" id="b" >Missed Instructions</td>
                <td class="sortable ctr2" id="c" >Cov.</td>
                <td class="sortable bar" id="d" >Missed Branches</td>
                <td class="sortable ctr2" id="e" >Cov.</td>
                <td class="sortable ctr1" id="f" >Missed</td>
                <td class="sortable ctr2" id="g" >Cxty</td>
                <td class="sortable ctr1" id="h" >Missed</td>
                <td class="sortable ctr2" id="i" >Lines</td>
                <td class="sortable ctr1" id="j" >Missed</td>
                <td class="sortable ctr2" id="k" >Methods</td>
                <td class="sortable ctr1" id="l" >Missed</td>
                <td class="sortable ctr2" id="m" >Classes</td>
            </tr>
        </thead>
        <tbody>

        </tbody>
    </table>
</body>
</html>""".replace("%jquery_library_url", jquery_library_url), remote_basedir + "/total.html")


def sonarqube_upload(args):
    """run SonarQube scanner and upload JaCoCo results"""

    sonarqube_cli = mx.library("SONARSCANNER_CLI_4_2_0_1873", True)

    parser = ArgumentParser(prog='mx sonarqube-upload')
    parser.add_argument('--exclude-generated', action='store_true', help='Exclude generated source files')
    parser.add_argument('--skip-coverage', action='store_true', default=False, help='Do not upload coverage reports')
    args, sonar_args = mx.extract_VM_args(args, useDoubleDash=True, defaultAllVMArgs=True)
    args, other_args = parser.parse_known_args(args)
    java_props, other_args = _parse_java_properties(other_args)

    def _check_required_prop(prop):
        if prop not in java_props:
            mx.abort("Required property '{prop}' not present. (Format is '-D{prop}=<value>')".format(prop=prop))

    _check_required_prop('sonar.projectKey')
    _check_required_prop('sonar.host.url')

    basedir = mx.primary_suite().dir

    # collect excluded projects
    excludes, includes = _jacoco_excludes_includes_projects(limit_to_primary=True)
    # collect excluded classes
    exclude_classes = _jacoco_exclude_classes(includes)
    java_bin = []
    java_src = []
    java_libs = []

    def _visit_deps(dep, edge):
        if dep.isJARDistribution() or dep.isLibrary():
            java_libs.append(dep.classpath_repr())

    mx.walk_deps(includes, visit=_visit_deps)

    # collect all sources and binaries -- do exclusion later
    for p in includes:
        java_src.extend(p.source_dirs())
        if not args.exclude_generated:
            gen_dir = p.source_gen_dir()
            if os.path.exists(gen_dir):
                java_src.append(gen_dir)
        java_bin.append(p.output_dir())

    java_src = [os.path.relpath(s, basedir) for s in java_src]
    java_bin = [os.path.relpath(b, basedir) for b in java_bin]

    # Overlayed sources and classes must be excluded
    jdk_compliance = mx.get_jdk().javaCompliance
    overlayed_sources = []
    overlayed_classfiles = {}
    for p in includes:
        if hasattr(p, "multiReleaseJarVersion") and jdk_compliance not in p.javaCompliance: # JDK9+ overlays
            for srcDir in p.source_dirs():
                for root, _, files in os.walk(srcDir):
                    for name in files:
                        if name.endswith('.java') and name != 'package-info.java':
                            overlayed_sources.append(join(os.path.relpath(root, basedir), name))
        elif hasattr(p, "overlayTarget"): # JDK8 overlays
            target = mx.project(p.overlayTarget)
            overlay_sources = []
            for srcDir in p.source_dirs():
                for root, _, files in os.walk(srcDir):
                    for name in files:
                        if name.endswith('.java') and name != 'package-info.java':
                            overlay_sources.append(join(os.path.relpath(root, srcDir), name))
            print(p, target, overlay_sources)
            for srcDir in target.source_dirs():
                for root, _, files in os.walk(srcDir):
                    for name in files:
                        if name.endswith('.java') and name != 'package-info.java':
                            s = join(os.path.relpath(root, srcDir), name)
                            if s in overlay_sources:
                                overlayed = join(os.path.relpath(root, basedir), name)
                                overlayed_sources.append(overlayed)
            for s in overlay_sources:
                classfile = join(os.path.relpath(target.output_dir(), basedir), s[:-len('java')] + 'class')
                with open(classfile, 'rb') as fp:
                    overlayed_classfiles[classfile] = fp.read()

    exclude_dirs = []
    for p in excludes:
        exclude_dirs.extend(p.source_dirs())
        exclude_dirs.append(p.source_gen_dir())

    javaCompliance = max([p.javaCompliance for p in includes]) if includes else JavaCompliance('1.7')

    jacoco_exec = get_jacoco_dest_file()
    if not os.path.exists(jacoco_exec) and not args.skip_coverage:
        mx.abort('No JaCoCo report file found: ' + jacoco_exec)

    def _add_default_prop(key, value):
        if key not in java_props:
            java_props[key] = value

    # default properties
    _add_default_prop('sonar.java.source', str(javaCompliance))
    _add_default_prop('sonar.projectBaseDir', basedir)
    if not args.skip_coverage:
        _add_default_prop('sonar.jacoco.reportPaths', jacoco_exec)
    _add_default_prop('sonar.sources', ','.join(java_src))
    _add_default_prop('sonar.java.binaries', ','.join(java_bin))
    _add_default_prop('sonar.java.libraries', ','.join(java_libs))
    exclude_patterns = [os.path.relpath(e, basedir) + '**' for e in exclude_dirs] + \
                       overlayed_sources + \
                       list(set([os.path.relpath(match[0], basedir) for _, match in exclude_classes.items()]))
    if exclude_patterns:
        _add_default_prop('sonar.exclusions', ','.join(exclude_patterns))
        _add_default_prop('sonar.coverage.exclusions', ','.join(exclude_patterns))
    _add_default_prop('sonar.verbose', 'true' if mx._opts.verbose else 'false')

    with tempfile.NamedTemporaryFile(suffix="-sonarqube.properties", mode="w+") as fp:
        # prepare properties file
        fp.writelines((f'{k}={v}\n' for k, v in java_props.items()))
        fp.flush()

        # Since there's no options to exclude individual classes,
        # we temporarily delete the overlayed class files instead.
        for classfile in overlayed_classfiles:
            os.remove(classfile)

        try:
            # run sonarqube cli
            java_args = other_args + ['-Dproject.settings=' + fp.name, '-jar', sonarqube_cli.get_path(True)] + sonar_args
            exit_code = mx.run_java(java_args, nonZeroIsFatal=False)
        finally:
            # Restore temporarily deleted class files
            for classfile, data in overlayed_classfiles.items():
                with open(classfile, 'wb') as cf:
                    cf.write(data)

        if exit_code != 0:
            fp.seek(0)
            mx.abort(f"SonarQube scanner terminated with non-zero exit code: {exit_code}\n  Properties file:\n{''.join('    ' + l for l in fp.readlines())}")

def _get_repo_name(suite):
    vc = suite.vc
    if vc is None:
        return ''
    repo_url = vc.default_pull(suite.vc_dir)
    return str(repo_url).split('.git')[0].split('/')[-1]

def _get_commit(suite):
    """
    Get commit revision of `suite`.
    """
    vc = suite.vc
    if vc is None:
        return ''
    info = vc.parent(suite.vc_dir)
    return str(info)

def _unpack_test_results(test_results):
    if not isinstance(test_results, list):
        assert isinstance(test_results, str), f'test_results must be a string, not a {type(test_results)}'
        if test_results.endswith('.gz'):
            import gzip
            with gzip.open(test_results, 'rt') as f_in:
                test_results = json.load(f_in)
        else:
            with open(test_results, 'r') as f_in:
                test_results = json.load(f_in)
    assert isinstance(test_results, list), f'test results must be a list, not a {type(test_results)}'
    expected_keys = frozenset(('name', 'status', 'duration'))
    for i, e in enumerate(test_results):
        assert isinstance(test_results, list), f'test result {i} must be a dict, not a {type(e)}'
        assert frozenset(e.keys()) == expected_keys, f'fields of test result {i} must be {", ".join(expected_keys)}, not {", ".join(e.keys())}'

    return test_results

def make_test_report(test_results, task, component=None, tags=None, fatalIfUploadFails=False):
    """
    Creates a test report based on `test_results`. The report is a dict with the following fields:
        repo: simple name of git repository containing the primary suite (e.g., "graal")
        commit: git commit hash of the primary suite (e.g., "5dc7ecdf43515028d4f40265b0e183af67e88b08")
        timestamp: current time in ISO 8601 format in UTC (e.g., "2022-05-20T13:21:42+00:00")
        testCollection: a name for the report. In combination with `tags`, this name uniquely
            identifies the test report. The name is composed as follows:
                f"{build}_{comp}"
            where:
                build = get_env('BUILD_NAME', 'unclassified')
                comp = component or mx.primary_suite().name
            Example: "gate-test-java11-compiler-linux-amd64-vectorization_compiler"
        tags: key/value pairs describing the test configuration. (e.g., {"gcc-version": "7.4"})
        tests: `test_results`

    If ${MX_TEST_REPORTS_LOCATION} is defined, then the report is uploaded as a gzipped JSON document
    to an Artifactory server. The name of the JSON document is:
                f"{testCollection}_{sha1(all_tags)}.json.gz"
            where:
                build = get_env('BUILD_NAME', 'unclassified')
                all_tags = tags + predefined_tags
                sha1(d) = sha1([f"{k}{v}".encode() for k,v in sorted(d.items())])
            Example: gate-test-java11-compiler-linux-amd64-vectorization_compiler_9237330eb7a50c4b41a7a432ae143686dc9e7932.json.gz

    Further details of uploading are configured by the following environment variables:

    MX_TEST_REPORTS_LOCATION: Base URL of the Artifactory end point for the upload. If ".", the
          document is saved in the current working directory.
    MX_TEST_UPLOAD_API_USER: Authentication header key (e.g. "X-JFrog-Art-Api")
    MX_TEST_UPLOAD_API_KEY_PATH_<OS>: OS specific path to a file containing the
          authentication header value. OS must match `mx.get_os().upper()`.
          Example: MX_TEST_UPLOAD_API_KEY_PATH_DARWIN=/private/secrets/artifactory_api_key

    :param test_results: array of dicts (or name of a JSON file containing such an array),
             one per test. Each dict must have exactly these keys:
               name: unique name for the test
               status: "PASSED", "FAILED" or "IGNORED"
               duration: duration of test in milliseconds
    :param task: a name that can be used to differentiate between different configurations that run the same tests
    :param component: name of the tested component. Defaults to the name of the primary suite.
    :param tags: dict describing test details that make it unique compared to other test reports
             with the same `testCollection` value (e.g., {'task': 'XcompUnitTests: hosted-product compiler' }).
    :param fatalIfUploadFails: if uploading the report fails, mx.abort is called. Otherwise a warning is displayed on the console.
    """
    if mx.get_jdk():
        java_version = str(mx.get_jdk().javaCompliance)
    else:
        java_version = "None"
    primary_suite = mx.primary_suite()
    component = component or primary_suite.name
    results_commit = _get_commit(primary_suite)
    results_repo_name = _get_repo_name(primary_suite)
    results_timestamp = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(timespec='seconds')
    build = mx.get_env("BUILD_NAME", "unclassified")

    if tags is None:
        tags = dict()

    # Ensure tags has a job_type entry
    if 'job_type' not in tags:
        job_types = {"gate", "post-merge", "ondemand", "daily", "weekly", "bench"}
        tags['job_type'] = 'unclassified'
        for job in job_types:
            if job in build:
                tags['job_type'] = job
                break

    # Add the predefined tags and ensure they are not already defined
    predefined_tags = {
        'os':  mx.get_os(),
        'arch': mx.get_arch(),
        'java_version': java_version,
        'component': component,
        'task': task,
    }
    conflicting_tags = frozenset(predefined_tags.keys()).intersection(tags.keys())
    if conflicting_tags:
        mx.abort(f'Cannot overwrite predefined tag(s): {", ".join(conflicting_tags)}')
    tags.update(predefined_tags)

    name = f'{build}_{component}'
    test_results = _unpack_test_results(test_results)
    test_report = {
        'repo': results_repo_name,
        'commit': results_commit,
        'timestamp': results_timestamp,
        'testCollection': name,
        'tags': tags,
        'tests': test_results
    }

    mandatory_tags = {'os', 'arch', 'java_version', 'component', 'job_type', 'task'}
    missing_tags = frozenset(tags.keys()).difference(mandatory_tags)
    assert len(missing_tags) == 0, f'The following mandatory tags are missing in the test report: {", ".join(missing_tags)}'

    upload_url_base = mx.get_env('MX_TEST_REPORTS_LOCATION')
    if upload_url_base is not None:

        def test_report_for_console():
            test_report_json = json.dumps(test_report)
            if len(test_report_json) > 4000:
                test_report_json = test_report_json[:4000] + ' ... (truncated)'
            return test_report_json

        # Compute the sha1 of the tags
        d = hashlib.sha1()
        for n, v in sorted(tags.items()):
            d.update(n.encode())
            d.update(v.encode())
        tags_sha1 = d.hexdigest()

        report_file = f'{name}_{tags_sha1}.json.gz'
        import gzip
        test_report_json = gzip.compress(json.dumps(test_report).encode())
        if upload_url_base == '.':
            local_path = abspath(report_file)
            with open(local_path, 'wb') as fp:
                fp.write(test_report_json)
                mx.log(f'Saved report to {local_path}')
                return test_report

        upload_url = f'{upload_url_base}{results_repo_name}/{results_commit}/{report_file}'
        auth_header = mx.get_env('MX_TEST_UPLOAD_API_USER', default='Authorization')
        auth_value = None
        api_key_path_name = 'MX_TEST_UPLOAD_API_KEY_PATH_' + mx.get_os().upper()
        api_key_path = mx.get_env(api_key_path_name)
        if api_key_path:
            with open(api_key_path) as key:
                auth_value = key.read().strip()
        else:
            mx.warn(f'{api_key_path_name} is not defined, skipping authentication')

        already_uploaded = mx.download(report_file, [upload_url], verbose=False, abortOnError=False, verifyOnly=True)
        if already_uploaded:
            mx.warn(f'Cannot overwrite existing test report at {upload_url}.\nLocal test report: {test_report_for_console()}')
        else:
            req = urllib.request.Request(url=upload_url, data=test_report_json, method='PUT')
            if auth_value:
                req.add_header(auth_header, auth_value)
            mx.log(f'uploading test report to {upload_url}')
            try:
                urllib.request.urlopen(req)
            except:
                ex = sys.exc_info()[0]
                message = f'Uploading test report to {upload_url} failed: {ex}\nTest report: {test_report_for_console()}'
                if fatalIfUploadFails:
                    mx.abort(message)
                else:
                    mx.warn(message)
    return test_report
