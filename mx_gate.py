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

import os, re, time, datetime, json
import tempfile
import atexit
import zipfile
from os.path import join, exists
from argparse import ArgumentParser

import mx
import mx_javacompliance
import sys
from mx_urlrewrites import rewriteurl


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
    log = True # whether to log task messages
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
    startTime = None

    def tag_matches(self, _tags):
        for t in _tags:
            assert isinstance(t, str), '{} is not a string and thus not a valid tag'.format(t)
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
            duration = datetime.timedelta(seconds=time.time() - Task.startTime)
            # Strip microseconds and convert to a string
            duration = str(duration - datetime.timedelta(microseconds=duration.microseconds))
            # Strip hours if 0
            if duration.startswith('0:'):
                duration = duration[2:]
            stamp += '(+{})'.format(duration)
        return stamp + suffix

    def __init__(self, title, tasks=None, disableJacoco=False, tags=None, legacyTitles=None, description=None):
        self.tasks = tasks
        self.title = title
        self.legacyTitles = legacyTitles or []
        self.skipped = False
        self.tags = tags
        self.description = description
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
                titles = [self.title] + self.legacyTitles
                if Task.filtersExclude:
                    self.skipped = any([f in t for t in titles for f in Task.filters])
                else:
                    self.skipped = not any([f in t for t in titles for f in Task.filters])
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
        if Task.log:
            self.end = time.time()
            self.duration = datetime.timedelta(seconds=self.end - self.start)
            mx.log(self._timestamp(' END:   ') + self.title + ' [' + str(self.duration) + ']' + Task._diskstats())
        return self
    def abort(self, codeOrMessage):
        if Task.log:
            self.end = time.time()
            self.duration = datetime.timedelta(seconds=self.end - self.start)
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


_command_level = 0
def gate(args):
    """run the tests used to validate a push

    If this command exits with a 0 exit code, then the gate passed."""
    default_summary = ['duration', 'title', 'description', 'tags']

    parser = ArgumentParser(prog='mx gate')
    add_omit_clean_args(parser)
    parser.add_argument('--all-suites', action='store_true', help='run gate tasks for all suites, not just the primary suite')
    parser.add_argument('--dry-run', action='store_true', help='just show the tasks that will be run without running them')
    parser.add_argument('-x', action='store_true', help='makes --task-filter or --tags an exclusion instead of inclusion filter')
    jacoco = parser.add_mutually_exclusive_group()
    jacoco.add_argument('--jacocout', help='specify the output directory for jacoco report')
    jacoco.add_argument('--jacoco-zip', help='specify the output zip file for jacoco report')
    parser.add_argument('--jacoco-omit-excluded', action='store_true', help='omit excluded files from jacoco report')
    parser.add_argument('--strict-mode', action='store_true', help='abort if a task cannot be executed due to missing tool configuration')
    parser.add_argument('--no-warning-as-error', action='store_true', help='compile warnings are not treated as errors')
    parser.add_argument('-B', dest='extra_build_args', action='append', metavar='<build_args>', help='append additional arguments to mx build commands used in the gate')
    parser.add_argument('-p', '--partial', help='run only a subset of the tasks in the gate (index/total). Eg. "--partial 2/5" runs the second fifth of the tasks in the gate. Tasks with tag build are repeated for each run.')
    summary = parser.add_mutually_exclusive_group()
    summary.add_argument('--summary', action='store_const', const=default_summary, default=None, help='print a human readable summary of the executed tasks')
    summary.add_argument('--summary-format', dest='summary', action='store', default=None, help='--summary with a comma separated list of entries. Possible values ' + str(default_summary))
    filtering = parser.add_mutually_exclusive_group()
    filtering.add_argument('-t', '--task-filter', help='comma separated list of substrings to select subset of tasks to be run')
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
    elif args.tags:
        parse_tags_argument(args.tags, args.x)
        Task.tagsExclude = args.x
        if not Task.tagsExclude:
            # implicitly include 'always'
            Task.tags += [Tags.always]
    elif args.x:
        mx.abort('-x option cannot be used without --task-filter or the --tags option')

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

        # we have already ran the filters in the dry run when collecting
        # so we can safely overwrite other filter settings.
        Task.filters = runTaskNames
        Task.filtersExclude = False

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
        res = [{'duration': str(t.duration), 'title': t.title, 'tags': '[{}]'.format(', '.join(t.tags)) if t.tags else '', 'description': t.description or ''} for t in tasks]
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
                mx.abort('Unknown entry supplied to `mx gate --summary-format`: {}\n'
                         'Known entries are: {}'.format(entry, ', '.join(default_summary)))
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
                assert False, 'Failed safe_path test{} input: {} (len={}){}expect: {} (len={}){}actual: {} (len={})'.format(nl,
                    value, len(value), nl,
                    expect, len(expect), nl,
                    actual, len(actual))
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
            mx.log("Python version: {}".format(sys.version_info))

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

    with Task('Pylint', tasks, tags=[Tags.style]) as t:
        if t:
            if mx.command_function('pylint')(['--primary']) != 0:
                _warn_or_abort('Pylint not configured correctly. Cannot execute Pylint task.', args.strict_mode)

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
            fullbuild = True if Task.tags is None else Tags.fullbuild in Task.tags # pylint: disable=unsupported-membership-test
            # Using ecj alone is not compatible with --warning-as-error (see GR-3969)
            if not args.no_warning_as_error and fullbuild:
                defaultBuildArgs += ['--warning-as-error']
            if mx.get_env('JDT'):
                mx.command_function('build')(defaultBuildArgs + args.extra_build_args)
                if fullbuild:
                    gate_clean(cleanArgs, tasks, name='CleanAfterEcjBuild', tags=[Tags.fullbuild])
            else:
                _warn_or_abort('JDT environment variable not set. Cannot execute BuildWithEcj task.', args.strict_mode)

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
                _warn_or_abort('ECLIPSE_EXE environment variable not set. Cannot execute CodeFormatCheck task.', args.strict_mode)

    with Task('Checkstyle', tasks, tags=[Tags.style]) as t:
        if t and mx.command_function('checkstyle')(['--primary']) != 0:
            t.abort('Checkstyle warnings were found')

    with Task('SpotBugs', tasks, tags=[Tags.fullbuild]) as t:
        if t and mx.command_function('spotbugs')([]) != 0:
            t.abort('FindBugs warnings were found')

    with Task('VerifyLibraryURLs', tasks, tags=[Tags.fullbuild]) as t:
        if t:
            mx.command_function('verifylibraryurls')([])

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
        mx.command_function('jacocoreport')(jacoco_args)
        _jacoco = 'off'
    if args.jacoco_zip is not None:
        mx.log('Creating JaCoCo report archive: {}'.format(args.jacoco_zip))
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
    baseExcludes = list(_jacoco_excludes)
    aps = mx.annotation_processors()
    for p in mx.projects():
        if p.isJavaProject():
            projsetting = getattr(p, 'jacoco', '')
            if not _jacoco_is_package_whitelisted(p.name):
                pass
            elif projsetting == 'exclude':
                baseExcludes.append(p.name)
            elif p in aps:
                # Exclude all annotation processors from JaCoco analysis
                baseExcludes.append(p.name)
            elif projsetting == 'include':
                includes.append(p.name + '.*')
    if _jacoco_whitelisted_packages:
        includes.extend((x + '.*' for x in _jacoco_whitelisted_packages))

    def _filter(l):
        # filter out specific classes which are already covered by a baseExclude package
        return [clazz for clazz in l if not any([clazz.startswith(package) for package in baseExcludes])]

    excludes = []
    for p in mx.projects():
        if p.isJavaProject() and p.name not in baseExcludes and _jacoco_is_package_whitelisted(p.name):
            excludes += _filter(
                p.find_classes_with_annotations(None, _jacoco_excluded_annotations, includeInnerClasses=True,
                                                includeGenSrc=True).keys())
            excludes += _filter(p.find_classes_with_matching_source_line(None, lambda line: 'JaCoCo Exclude' in line,
                                                                         includeInnerClasses=True,
                                                                         includeGenSrc=True).keys())
    excludes += [package + '.*' for package in baseExcludes]
    return excludes, includes

def get_jacoco_dest_file():
    return JACOCO_EXEC or mx.get_opts().jacoco_dest_file

def get_jacoco_agent_path(resolve):
    return mx.library('JACOCOAGENT_0.8.7_CUSTOM', True).get_path(resolve)

def get_jacoco_agent_args(jacoco=None):
    '''
    Gets the args to be added to a VM command line for injecting the JaCoCo agent
    if use of JaCoCo has been requested otherwise returns None.
    '''
    if jacoco is None:
        jacoco = _jacoco

    if jacoco in ('on', 'append'):
        excludes, includes = _jacoco_excludes_includes()
        with tempfile.NamedTemporaryFile(prefix="jacoco_excludes", mode="w", delete=False) as excludesfile:
            # Make sure to remove temporary file when program exits
            atexit.register(os.remove, excludesfile.name)
            excludesfile.write(':'.join(excludes))
            excludesfile.flush()
            agentOptions = {
                            'append' : 'true' if jacoco == 'append' else 'false',
                            'inclbootstrapclasses' : 'true',
                            'includes' : ':'.join(includes),
                            'excludesfile' : excludesfile.name,
                            'destfile' : get_jacoco_dest_file(),
            }
        return ['-javaagent:' + get_jacoco_agent_path(True) + '=' + ','.join([k + '=' + v for k, v in agentOptions.items()])]
    return None


def jacocoreport(args, exec_files=None):
    """Create a JaCoCo coverage report

    Parses the supplied arguments and creates a coverage report from Jacoco exec files. By default, the file returned
    by :get_jacoco_dest_file: is used. This is typically the 'jacoco.exec' file in the current directory. Alternatively,
    you can specify a list of JaCoCo files to use with the `exec_files` parameter.

    :param list args: a list of arguments to parse.
    :param list exec_files: a list of jacoco.exec files to use instead of the one returned by :get_jacoco_dest_file:.
    :return: the included projects and excludes used for this report"""

    _jacocoreport(args, exec_files)


def _jacocoreport(args, exec_files=None):
    dist_name = "MX_JACOCO_REPORT"
    mx.command_function("build")(['--dependencies', dist_name])
    dist = mx.distribution(dist_name)
    jdk = mx.get_jdk(dist.javaCompliance)

    parser = ArgumentParser(prog='mx jacocoreport')
    parser.add_argument('--format', help='Export format (HTML or XML)', default='html', choices=['html', 'xml'])
    parser.add_argument('--omit-excluded', action='store_true', help='omit excluded files from report')
    parser.add_argument('output_directory', help='Output directory', default='coverage', nargs='?')
    args = parser.parse_args(args)

    # list of strings of the form "project-dir:binary-dir"
    includedirs = []
    includedprojects = []
    for p in mx.projects():
        projsetting = getattr(p, 'jacoco', '')
        if projsetting in ('include', '') and _jacoco_is_package_whitelisted(p.name):
            if isinstance(p, mx.ClasspathDependency):
                if args.omit_excluded and p.is_test_project():  # skip test projects when omit-excluded
                    continue
                source_dirs = []
                if p.isJavaProject():
                    source_dirs += p.source_dirs() + [p.source_gen_dir()]
                includedirs.append(":".join([p.dir, p.classpath_repr(jdk)] + source_dirs))
                includedprojects.append(p.name)

    def _run_reporter(extra_args=None):
        files_arg = []
        if exec_files is None:
            files_arg = ['--in', get_jacoco_dest_file()]
        else:
            for exec_file in exec_files:
                files_arg += ['--in', exec_file]

        mx.run_java(['-cp', mx.classpath([dist_name], jdk=jdk), '-jar', dist.path, '--out',
                     args.output_directory, '--format', args.format] + files_arg +
                    (extra_args or []) +
                    sorted(includedirs),
                    jdk=jdk, addDefaultArgs=False)

    if not args.omit_excluded:
        _run_reporter()
        excludes = []
    else:
        with tempfile.NamedTemporaryFile(suffix="jacoco-report-exclude", mode="w") as fp:
            excludes, _ = _jacoco_excludes_includes()
            fp.writelines((e + "\n" for e in excludes))
            fp.flush()
            _run_reporter(['--exclude-file', fp.name])
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
        mx.abort('Cannot determine remote host from {}'.format(args.upload_url))

    primary = mx.primary_suite()
    if not primary.vc:
        mx.abort('coverage_upload requires the primary suite to be in a vcs repository')
    info = primary.vc.parent_info(primary.dir)
    rev = primary.vc.parent(primary.dir)
    if len(remote_basedir) > 0 and not remote_basedir.endswith('/'):
        remote_basedir += '/'
    remote_dir = '{}_{}_{}'.format(primary.name, datetime.datetime.fromtimestamp(info['author-ts']).strftime('%Y-%m-%d_%H_%M'), rev[:7])
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
            if dep.isJavaProject() and not dep.is_test_project():
                binaries.zf.add(dep.output_dir(), dep.name)
                for d in dep.source_dirs():
                    sources.zf.add(d, dep.name)
                if os.path.exists(dep.source_gen_dir()):
                    sources.zf.add(dep.source_gen_dir(), dep.name)
        mx.walk_deps(mx.projects(), visit=_visit_deps)

    files = [get_jacoco_dest_file(), 'coverage', coverage_sources, coverage_binaries]
    print("Syncing {} to {}:{}".format(" ".join(files), remote_host, upload_dir))
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

    javaCompliance = max([p.javaCompliance for p in includes]) if includes else mx.JavaCompliance('1.7')

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
        fp.writelines(('{}={}\n'.format(k, v) for k, v in java_props.items()))
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
            mx.abort('SonarQube scanner terminated with non-zero exit code: {}\n  Properties file:\n{}'.format(
                exit_code, ''.join(('    ' + l for l in fp.readlines()))))
