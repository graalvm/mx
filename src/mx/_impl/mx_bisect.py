#
# ----------------------------------------------------------------------------------------------------
#
# Copyright (c) 2020, Oracle and/or its affiliates. All rights reserved.
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

__all__ = [
    "BuildSteps",
    "DefaultBuildStepsStrategy",
    "define_bisect_default_build_steps",
    "mx_bisect",
    "Config",
    "Commit",
    "CommitStatus",
    "IssueSearchInfra",
    "BisectStrategy",
    "BisectBayesianSearch",
    "BisectSearch",
    "Bisect",
]

import os, subprocess, math, signal, time, re
from . import mx
from .mx import VC
from datetime import datetime
from argparse import ArgumentParser
from threading import Thread


class BuildSteps:

    def __init__(self):
        pass

    def clone_repo(self, process_number):
        return []

    def git_log_filtering_strategy(self):
        return []

    def default_start_date(self):
        return ''

    def after_checkout(self, jdk_distribution, paths):
        pass

    def get_default_setup_cmd(self):
        return ''

    def get_default_prepare_cmd(self):
        return ''

    def update_env_variables(self, path, env_variables):
        pass

    def clean_tmp_files(self):
        pass


class DefaultBuildStepsStrategy(BuildSteps):

    def __init__(self):
        BuildSteps.__init__(self)

    def git_log_filtering_strategy(self):
        mx.log('Default commits filtering strategy')
        git_log_strategy = ['git', 'log', '--first-parent']
        return git_log_strategy

    def default_start_date(self):
        # Date the common.json was added to the repository
        default_start_date = '2020-01-22'
        mx.log('default_start_date: ' + default_start_date)
        return default_start_date

    def get_default_setup_cmd(self):
        return 'mx clean; mx build'


_build_steps_strategy = DefaultBuildStepsStrategy()


def define_bisect_default_build_steps(bs):
    global _build_steps_strategy
    _build_steps_strategy = bs

def _update_cmd_if_stripped(cmd_to_update):
    if mx._opts.strip_jars and cmd_to_update.find('--strip-jars') == -1:
        cmd_to_update = re.sub(r'\b(mx)\b', 'mx --strip-jars', cmd_to_update)
    return cmd_to_update

@mx.command('mx', 'bisect', '[options]')
@mx.optional_suite_context
def mx_bisect(args):
    """
    'mx bisect' script helps to find two kinds of issues: transient and permanent.
    The permanent ones could be reproduced during every run, while transients may demand dozens of runs to be faced.
    By default, script performs transient issues searching using '--strategy bayesian' for this.
    To specify that the issue is permanent, provide '--strategy bisect' argument.

    The detailed commands execution log is located at mxbuild dir and named 'bisect_<date-time>.log'

    There are several stages (phases) the script passing through:
    - run prepare command (one time before all test cycle)
    - run setup command (after each commit checkout)
    - check if the last commit in a range fails
    - continuously move to the past by checkout and analyze the so-called median commit until reach non-failed commit
    - find the initial issue inside the range between non-failed and last failed commits

    The following options should be used only for transient issues:
    --confidence, --failed and --passed, --parallel

    Usage examples to show arguments combinations:

    To run specific 'mx' command or test/gate:
    cd graal/substratevm
    mx bisect --after 5.weeks "mx helloworld"
    By default bayesian search strategy will be used.

    For transient issue the confidence can be specified (by default is 0.99):
    mx bisect --confidence 0.1 --after 5.weeks "mx helloworld"

    To specify the range of commits between dates to analyze:
    mx bisect --after 2020-5-10 --before 2020-5-12 "mx helloworld"

    To specify the range of commits between commits to analyze:
    mx bisect --start-commit 547bd9c4dd --end-commit 3feaa5f359 "mx helloworld"

    Specifying the number of failed and passed tests for transient issues can speed up the algorithm:
    mx bisect --failed 2 --passed 8 --after 2020-5-10 --before 2020-5-12 "mx helloworld"

    To specify the command that should be executed after each commit checkout (for example 'mx build'):
    mx bisect --confidence 0.1 --setup-cmd "mx build" "mx helloworld"

    To specify that '--setup-cmd' command should be executed before each run:
    mx bisect --confidence 0.1 --setup-cmd "mx clean; mx build" --run-setup-every-time "mx helloworld"

    To specify the command that should be executed only once before start of the tests:
    mx bisect --confidence 0.1 --after 5.weeks --prepare-cmd "pwd" "mx helloworld"

    To specify that the command can be executed in parallel specify the number of parallel process:
    mx bisect --confidence 0.1 --after 5.weeks --parallel 3 "mx helloworld"

    To specify the dedicated version of java:
    mx bisect --confidence 0.1 --after 5.weeks --java-home <java-path> "mx helloworld"

    To run internal self-check test that generates commit with the transient issue use
    mx bisect selfcheck
    To test binary search for constantly reproducible issue, specify '--strategy bisect' option:
    mx bisect --strategy bisect selfcheck

    """

    if not os.environ.get('JAVA_HOME'):
        mx.log('Please set env variable: JAVA_HOME')
        return

    parser = ArgumentParser(prog='mx bisect')
    parser.add_argument('cmd', help='Command(s) to execute, should be separated by ";"')
    parser.add_argument('--strategy',
                        help='Strategy for issue search', choices=['bayesian', 'bisect'],
                        default='bayesian')
    parser.add_argument('--after', help='Start date of the commits range to analyze')
    parser.add_argument('--before', help='End date of the commits range to analyze', default='')
    parser.add_argument('--start-commit', dest='start_commit', help='Start commit hash of the range to analyze')
    parser.add_argument('--end-commit', dest='end_commit', help='End commit hash of the range to analyze', default='')
    parser.add_argument('--confidence',
                        help='Confidence that the commit is the culprit. Should be in a range (0.0, 1.0)', default=0.99,
                        type=float)
    parser.add_argument('--failed',
                        help='The number of known failed tests for the provided command since appearing of the transient issue',
                        default=0, type=int)
    parser.add_argument('--passed',
                        help='The number of known passed tests for the provided command since appearing of the transient issue',
                        default=0, type=int)
    parser.add_argument('--setup-cmd', dest='setup_cmd',
                        help='This command will be executed after each commit checkout')
    parser.add_argument('--run-setup-every-time', dest='run_setup_every_time', action="store_true",
                        help='Run setup_cmd (for example "mx build") before every test run', default=False)
    parser.add_argument('--prepare-cmd', dest='prepare_cmd',
                        help='This command will be executed one time at the script start')
    parser.add_argument('--parallel', help='Can execute "cmd" in N processes in parallel', default=1, type=int)
    parser.add_argument('--timeout', help='Timeout for test (sec)', default=3600, type=int)
    parser.add_argument('--jdk-distribution', dest='jdk_distribution',
                        help='The name of the JDK distribution (default is "openjdk8") from common.json',
                        default='openjdk8')
    parser.add_argument('--java-home', dest='java_home',
                        help='To run all commands using specific Java version',
                        default='')
    parser.add_argument('--grep-commits', dest='commits_filter',
                        help='Filter commits with log message that matches the specified pattern ', default='')
    parser.add_argument('--grep-error', dest='error_pattern', help='Text that should be in the error message',
                        default='')

    args = parser.parse_args(args)
    after = args.after
    before = args.before
    start_commit = args.start_commit
    end_commit = args.end_commit
    cmd = args.cmd
    passed = args.passed
    failed = args.failed
    commits_filter = args.commits_filter
    error_pattern = args.error_pattern
    confidence = args.confidence
    jdk_distribution = args.jdk_distribution
    java_home = args.java_home
    parallel = args.parallel
    timeout = args.timeout
    setup_cmd = args.setup_cmd
    run_setup_every_time = args.run_setup_every_time
    prepare_cmd = args.prepare_cmd

    if (passed == 0) ^ (failed == 0):
        mx.log("You should specify both 'passed' and 'failed' tests count for the same time period")
        return

    cmd = _update_cmd_if_stripped(cmd)

    config = Config(cmd=cmd, after=after, before=before, start_commit=start_commit, end_commit=end_commit,
                    passed=passed, failed=failed, commits_filter=commits_filter,
                    error_pattern=error_pattern, confidence=confidence, jdk_distribution=jdk_distribution,
                    java_home=java_home,
                    parallel=parallel, timeout=timeout, setup_cmd=setup_cmd, run_setup_every_time=run_setup_every_time,
                    prepare_cmd=prepare_cmd)
    bisect = Bisect(config, _build_steps_strategy, args.strategy)

    if 'selfcheck' in cmd:
        if args.strategy == 'bisect':
            script_name = _generate_tmp_test_commits(1)
        else:
            script_name = _generate_tmp_test_commits(5)
        config.cmd = 'bash ' + script_name
        config.setup_cmd = ' '
        config.start_commit = bisect.bisect_infra.original_commit

    bisect.bisect_search()


class Config:

    def __init__(self, cmd='', after='', before='', start_commit='', end_commit='',
                 passed=0, failed=0, commits_filter='', error_pattern='',
                 confidence=0.99, jdk_distribution='openjdk8', java_home=None, parallel=1,
                 setup_cmd='', run_setup_every_time=False, prepare_cmd='', timeout=3600):
        self.timeout = timeout
        self.prepare_cmd = prepare_cmd
        self.setup_cmd = setup_cmd
        self.run_setup_every_time = run_setup_every_time
        self.parallel = parallel
        self.java_home = java_home
        self.jdk_distribution = jdk_distribution
        self.confidence = confidence
        self.error_pattern = error_pattern
        self.commits_filter = commits_filter
        self.failed = failed
        self.passed = passed
        self.end_commit = end_commit
        self.start_commit = start_commit
        self.before = before
        self.after = after
        self.cmd = cmd


class Commit:

    def __init__(self, commit_hash, msg, date):
        self.hash = commit_hash
        self.msg = msg
        self.date = date

    def __repr__(self):
        return f'Commit: hash {self.hash} date: {self.date} message: {self.msg}'


class CommitStatus:

    def __init__(self, commit, passed, failed):
        self.commit = commit
        self.passed = passed
        self.failed = failed

    def __repr__(self):
        return f'CommitStatus[hash: {self.commit.hash}, passed: {self.passed}, failed: {self.failed}]'


class IssueSearchInfra:
    _mx_path = mx._mx_path
    paths = []  # paths where mx command should be executed

    def __init__(self, config, build_steps):
        self.config = config
        self.build_steps = build_steps

        log_dir = 'mxbuild'
        log_file_name = os.path.join(log_dir, 'bisect_' + str(datetime.now().strftime('%Y%m%d%H%M%S') + '.log'))
        mx.log('The log file with commands output: ' + os.path.join(os.getcwd(), log_file_name))
        if not os.path.exists(log_dir):
            os.mkdir(log_dir)
        self.log_file = open(log_file_name, 'w+')

        if self.config.parallel >= 2:
            self.paths = self.build_steps.clone_repo(self.config.parallel)
            self.original_commit = None
        else:
            self.paths = [os.getcwd()]
            self.original_commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'],
                                                           universal_newlines=True).strip()
            self.original_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                                                           universal_newlines=True).strip()

    def execute_commands_in_parallel(self, cmd):

        def redirect(stream):
            while True:
                try:
                    line = stream.readline()
                    if line:
                        mx.logv(line.strip())
                        self.log_file.write(line)
                    else:
                        return
                except ValueError:
                    return

        process_number = len(self.paths)
        new_env = os.environ.copy()
        self.log_file.write('-- Running command: ' + str(cmd) + '\n')
        arr = [None] * process_number
        joiners = [None] * process_number
        for i in range(process_number):
            self._set_env_variables(self.paths[i], new_env)
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, env=new_env,
                                       cwd=self.paths[i], universal_newlines=True)
            arr[i] = process
            th = Thread(target=redirect, args=(process.stdout,))
            joiners[i] = th
            th.start()

        pattern = self.config.error_pattern
        for i in range(process_number):
            process = arr[i]
            try:
                _, stderr = process.communicate(timeout=self.config.timeout)
                joiners[i].join(10)
                if process.returncode != 0:
                    mx.log(f'Error: {stderr}')
                    self.log_file.write(stderr)
                    if pattern:
                        if pattern in stderr:
                            return False
                    else:
                        return False
            except subprocess.TimeoutExpired:
                mx.log(f'Time out expired: {self.config.timeout}')
                mx.log(f"Time out expired Kill proc: {process.pid}")
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                return False
        return True

    def _set_env_variables(self, path, new_env):
        if self.config.java_home:
            new_env['JAVA_HOME'] = self.config.java_home
        mx.logv('JAVA_HOME: ' + new_env['JAVA_HOME'])
        new_env['JVMCI_VERSION_CHECK'] = 'ignore'
        new_env['MX_PRIMARY_SUITE_PATH'] = path
        build_dir = self._get_build_dir(path)
        new_env['BUILD_DIR'] = build_dir
        self._set_mx_path(build_dir, new_env)
        self.build_steps.update_env_variables(path, new_env)

    def _get_build_dir(self, path):
        _, repo_path = VC.get_vc_root(path)
        build_dir = os.path.dirname(repo_path)
        return build_dir

    def _set_mx_path(self, build_dir, new_env):
        mx_dir = os.path.join(build_dir, 'mx')
        if os.path.exists(mx_dir):
            mx.logv("MX_DIR: " + mx_dir)
            new_env['PATH'] = mx_dir + ':' + new_env["PATH"]
            new_env['MX_HOME'] = mx_dir
        else:
            mx.logv("MX_DIR: " + mx._mx_home)
            new_env['PATH'] = mx._mx_home + ':' + new_env["PATH"]
            new_env['MX_HOME'] = mx._mx_home

    def commits_in_range(self):
        grep_filter = str(self.config.commits_filter).replace('[', r'\[').replace(']', r'\]')
        commits_filter = self.build_steps.git_log_filtering_strategy()
        git_log_command_base = commits_filter + ['--grep=' + grep_filter, '--pretty=format:%h|%ct|%s']

        if self.config.start_commit is not None:
            commits_range = [self.config.start_commit + '..' + self.config.end_commit]
        elif self.config.after is not None:
            commits_range = ['--after="' + self.config.after + '"', '--before="' + self.config.before + '"']
        else:
            commits_range = ['--after="' + self.build_steps.default_start_date() + '"',
                             '--before="' + self.config.before + '"']

        mx.log('Commits Filtering Strategy: ' + ' '.join(commits_filter + commits_range))
        unparsed_commits = subprocess.check_output(git_log_command_base + commits_range,
                                                   universal_newlines=True).splitlines()

        def commit_parser(c):
            commit_hash, date, msg = c.split('|', 2)
            commit = Commit(commit_hash, msg, datetime.fromtimestamp(int(date)))
            mx.logv(commit)
            return commit

        mx.logv('---------- Commits in range to analyze')
        commits = list(map(commit_parser, unparsed_commits))
        mx.log(f'Commits in range to analyze: {len(commits)}, hashes [{commits[len(commits) - 1].hash} - {commits[0].hash}]')
        return commits

    def checkout_commit(self, commit_hash):
        log_msg = f'---------- Checkout commit {commit_hash}'
        mx.log(log_msg)
        self.log_file.write(log_msg + '\n')
        for path in self.paths:
            subprocess.call(['git', '-c', 'advice.detachedHead=false', 'checkout', commit_hash], cwd=path)

    def checkout_commit_steps(self, commit_hash):
        self.checkout_commit(commit_hash)
        self.build_steps.after_checkout(self.config.jdk_distribution, self.paths)

    def run_test_cmd_in_parallel(self):
        if self.config.run_setup_every_time:
            self.run_setup_cmd()
        return self.execute_commands_in_parallel(self.config.cmd)

    def run_setup_cmd(self):
        if self.config.setup_cmd:
            cmd = self.config.setup_cmd
        elif self.build_steps.get_default_setup_cmd():
            cmd = self.build_steps.get_default_setup_cmd()
        else:
            return None
        cmd = _update_cmd_if_stripped(cmd)
        mx.log('---------- Stage: Setup Start')
        self.log_file.write('---------- Running setup step \n')
        start_time = time.time()
        result = self.execute_commands_in_parallel(cmd)
        end_time = time.time()
        mx.log(f'---------- Stage: Setup End. Total time: {end_time - start_time:.2f} sec')
        return result

    def run_prepare_cmd(self):
        if self.config.prepare_cmd:
            cmd = self.config.prepare_cmd
        elif self.build_steps.get_default_prepare_cmd():
            cmd = self.build_steps.get_default_prepare_cmd()
        else:
            return None
        mx.log('---------- Stage: Prepare')
        cmd = _update_cmd_if_stripped(cmd)
        return self.execute_commands_in_parallel(cmd)

    def commit_info(self, commit_hash, formatter):
        return subprocess.check_output(['git', 'show', '--pretty=' + formatter, '-s', commit_hash],
                                       universal_newlines=True).strip()

    def reset_original_commit(self):
        if self.original_commit:
            subprocess.run(['git', 'checkout', '-q', self.original_branch], check=True)
            subprocess.run(['git', 'reset', '--hard', self.original_commit], check=True)


class BisectStrategy:

    def __init__(self, infra):
        self.infra = infra
        self.commits_list = self.commits()

    def commits(self):
        return list()

    def run_setup(self, c):
        commit_hash = self.commits_list[c].commit.hash
        self.infra.checkout_commit_steps(commit_hash)
        self.infra.run_setup_cmd()

    def run_test_multiple_times(self, commit_number, times_to_run=1):
        parallel_level = self.infra.config.parallel
        n = times_to_run
        mx.log(f'---------- Stage: Run test {n} times')
        while n > 0:
            log_msg = f"Verifying Commit: {commit_number}, hash: {self.commits_list[commit_number].commit.hash}, iteration: {times_to_run - n}, date: {self.commits_list[commit_number].commit.date}, message: {self.commits_list[commit_number].commit.msg}"
            mx.log(log_msg)
            self.infra.log_file.write('\n---------- Running test(s)\n')
            self.infra.log_file.write(log_msg + '\n')
            if n <= parallel_level:
                p = n
            else:
                p = parallel_level
            n -= parallel_level
            start_time = time.time()
            is_passed = self.infra.run_test_cmd_in_parallel()
            end_time = time.time()
            if is_passed:
                self.update_commit_stat(commit_number, p, 0)
                mx.log(f'Test Passed. Total time: {end_time - start_time:.2f} sec')
            else:
                self.update_commit_stat(commit_number, 0, 1)
                mx.log(f'Test Failed. Total time: {end_time - start_time:.2f} sec\n')
                return False
        return True

    def update_commit_stat(self, commit_number, passed, failed):
        commit = self.commits_list[commit_number]
        commit.passed += passed
        commit.failed += failed
        self.commits_list[commit_number] = commit

    def test_next_commit(self):
        return -1, True

    def print_commits_list_and_calc_total_steps(self, start_commit_number, end_commit_number, print_log):
        total_steps = 0
        for i in range(start_commit_number, end_commit_number):
            print_log(str(i) + " " + str(self.commits_list[i]))
            total_steps += self.commits_list[i].passed + self.commits_list[i].failed
        return total_steps


class BisectBayesianSearch(BisectStrategy):
    last_failed_commit = 0
    # If we have no failed/passed statistics we should use the lower_failure_rate to evaluate confident number of retries,
    # let's taking it as 1/30 (1 failed build from 30) by default
    lower_failure_rate = 1.0 / 30

    def __init__(self, infra):
        BisectStrategy.__init__(self, infra)
        # We should check the start searching commit if it failed or not
        self.update_commit_stat(0, -1, 0)
        self.confidence = 1 - infra.config.confidence
        self.failed_tests = infra.config.failed
        self.passed_tests = infra.config.passed

    def commits(self):
        git_commits = self.infra.commits_in_range()
        # We assume that every commit has been tested and passed
        commits = [CommitStatus(c, 1, 0) for c in git_commits]
        return list(commits)

    def test_next_commit(self):
        median = self._median_position()
        mx.log(f"---------- Median to analyze: {median}")
        mx.log(self.commits_list[median].commit)
        mx.log(f"Commits in range: {median - self.last_failed_commit}")
        mx.logv("Analyzed commits:")
        self._print_list_with_probabilities(self.last_failed_commit, median, mx.logv)

        self.run_setup(median)
        retries = self._retries_number()
        is_passed = self.run_test_multiple_times(median, retries)

        mx.logv("Analysis results:")
        self._print_list_with_probabilities(self.last_failed_commit, median, mx.logv)

        if not is_passed:
            self.last_failed_commit = median
            return median, False
        else:
            failure_position = self._search_failure_in_range(median)

            mx.logv("Final trace:")
            total_steps = self.print_commits_list_and_calc_total_steps(0, median + 1, mx.logv)
            mx.logv(f"Total steps in range: {total_steps}")

            mx.log('\n---------- Final range with probabilities:')
            self._print_final_list_with_probabilities(failure_position, median)

            return failure_position, True

    def _median_position(self):
        if self.commits_list[0].failed == 0:
            median = 0
            mx.log('\n---------- Stage: Running the first commit to be sure the failure is reproducible')
        else:
            median = self._calculate_median_position()
            if median == self.last_failed_commit:
                median += 1
        return median

    def _calculate_median_position(self, cdf_probability=0.5):
        cdf = 0.0
        i = self.last_failed_commit
        while cdf <= cdf_probability:
            prob = self._probability_of_commit(i)
            cdf += prob
            i += 1
        return i - 1

    def _probability_of_commit(self, commit_number):
        passed_after_last_failure = 0
        for i in range(self.last_failed_commit + 1, commit_number + 1):
            passed_after_last_failure += self.commits_list[i].passed
        failed, passed = self._get_failed_passed_total_count()
        prob = self._calculate_probability_of_failure(failed, passed, passed_after_last_failure)
        return prob

    def _calculate_probability_of_failure(self, failed, passed, passed_commits_count):
        # using expression (20) from the article http://www.coppit.org/papers/isolating_intermittent_failures.pdf
        res = 1.0
        for i in range(passed + 1, passed + failed + 1 + 1):
            r = 1.0 * i / (i + passed_commits_count)
            res *= r
        return (failed + 1) * res / (passed + failed + 2 + passed_commits_count)

    def _search_failure_in_range(self, median):
        retries = self._retries_number()
        failed_tests, passed_tests = self._get_failed_passed_total_count()
        mx.log("\nFinal range:")
        self._print_list_with_probabilities(self.last_failed_commit, median, mx.log)
        mx.log(f"   Last failed: {self.last_failed_commit}")
        mx.log(f"   Last passed: {median}")
        mx.log(f"   Total Passed: {passed_tests}, Failed: {failed_tests}")
        mx.log(f"   Confident retries: {retries}")

        failure_position = self._linear_search_with_retries(self.last_failed_commit, median, retries)
        return failure_position

    def _linear_search_with_retries(self, start, end, retries):
        mx.log('---------- Stage: Running linear issue search inside the range')
        for i in range(start + 1, end):
            self.run_setup(i)
            is_passed = self.run_test_multiple_times(i, retries)
            if is_passed:
                return i - 1
        return end - 1

    def _get_failed_passed_total_count(self):
        failed, passed = self._get_failed_passed_count(self.last_failed_commit)
        return self.failed_tests + failed, self.passed_tests + passed

    def _get_failed_passed_count(self, commit_number):
        passed = 0
        failed = 0
        for i in range(commit_number + 1):
            passed += self.commits_list[i].passed
            failed += self.commits_list[i].failed
        return failed, passed

    def _retries_number(self):
        failed_tests, passed_tests = self._get_failed_passed_total_count()
        if failed_tests + passed_tests < 1 / self.lower_failure_rate:
            retries = self._calculate_retries(1, int(1 / self.lower_failure_rate), self.confidence)
        else:
            retries = self._calculate_retries(failed_tests, passed_tests, self.confidence)
        return retries

    def _calculate_retries(self, failed_tests, passed_tests, confident_probability):
        if failed_tests == 0:
            return 0
        failure_rate = 1.0 * failed_tests / (failed_tests + passed_tests)
        return int(math.log(confident_probability, 1 - failure_rate) + 1)

    def _print_list_with_probabilities(self, start, end, print_log):
        for i in range(start, end + 1):
            pr = self._probability_of_commit(i)
            print_log(str(i) + " " + str(self.commits_list[i]) + f" probability: {pr:.4f}")

    def _print_final_list_with_probabilities(self, failure_position, end):

        def print_commit(prob, commit_hash, message):
            mx.log(f'  {prob:.4f}       {commit_hash}      {message}')

        if failure_position != -1:
            position = failure_position
            total_failed, total_passed = self._get_failed_passed_count(position)
            failure_rate = 1.0 * total_failed / (total_failed + total_passed)
            passed = self.commits_list[position + 1].passed
        else:
            position = 0
            total_failed, total_passed = (self.commits_list[position].failed, self.commits_list[position].passed)
            failure_rate = self.lower_failure_rate
            passed = total_passed
            mx.log(f'The issue is not reproduced locally after {total_passed} retries.\nYou can try to increase the "--confidence" level or should re-run test on CI')

        mx.log(f'Failure rate: {failure_rate:.2f}')
        mx.log(f"Total Passed: {total_passed}, Failed: {total_failed}")
        mx.log("Probability    Hash         Message")
        prob = 1 - math.pow(1 - failure_rate, passed)

        print_commit(prob,
                     self.commits_list[position].commit.hash,
                     self.commits_list[position].commit.msg)
        for i in range(position + 1, end + 1):
            prob = math.pow(1 - failure_rate, passed) * failure_rate
            print_commit(prob,
                         self.commits_list[i].commit.hash,
                         self.commits_list[i].commit.msg)
            passed += 1


class BisectSearch(BisectStrategy):

    def __init__(self, infra):
        BisectStrategy.__init__(self, infra)
        self.start = 0
        self.end = len(self.commits_list) - 1
        # We assume that the first commit failed
        self.update_commit_stat(0, 0, 1)
        # We assume that the last commit passed
        self.update_commit_stat(self.end, 1, 0)

    def commits(self):
        git_commits = self.infra.commits_in_range()
        commits = [CommitStatus(c, 0, 0) for c in git_commits]
        return list(commits)

    def test_next_commit(self):
        if self.end - self.start >= 2:
            median = int(self.start + (self.end - self.start) / 2)
            mx.log(f'Median: {median}')
        else:
            mx.log('\nBisect search result:')
            self.print_commits_list_and_calc_total_steps(self.start, self.end + 1, mx.log)
            return self.end - 1, True

        self.run_setup(median)
        is_passed = self.run_test_multiple_times(median)
        if is_passed:
            self.end = median
        else:
            self.start = median

        return median, False


class Bisect:

    def __init__(self, config, build_steps, strategy='bayesian'):
        self.build_steps = build_steps
        self.bisect_infra = IssueSearchInfra(config, build_steps)
        self.strategy = strategy

    def bisect_search(self):
        self.bisect_infra.run_prepare_cmd()

        mx.log(f'Issue search strategy:   {self.strategy}')
        if self.strategy == 'bayesian':
            issue_search = BisectBayesianSearch(self.bisect_infra)
        elif self.strategy == 'bisect':
            issue_search = BisectSearch(self.bisect_infra)
        else:
            mx.log('There is no such strategy')
            return

        while True:
            tested_commit, should_stop = issue_search.test_next_commit()
            if should_stop:
                break

        mx.log(f"Failure position: ~ {tested_commit}")
        if tested_commit != -1:
            mx.log(self.bisect_infra.commit_info(issue_search.commits_list[tested_commit].commit.hash, 'medium'))
        self.build_steps.clean_tmp_files()
        self.bisect_infra.reset_original_commit()


def _generate_tmp_test_commits(failure_rate=5):
    script_name = 'self_check_script.sh'

    for i in range(10):
        with open(script_name, 'w') as f:
            f.write('echo ' + '.' * i + '\n')
        subprocess.run(['git', 'add', script_name], check=True)
        subprocess.run(['git', 'commit', '-m', 'Good script ' + str(i)], check=True)

    for i in range(20):
        with open(script_name, 'w') as f:
            f.write('if [ $(( ( RANDOM % ' + str(
                failure_rate) + ' )  + 1 )) == 1 ]\n then\n echo "An error occurred" 1>&2 \n exit 1\n else echo ' + '.' * i + '\n fi')
        subprocess.run(['git', 'add', script_name], check=True)
        subprocess.run(['git', 'commit', '-m', 'Failure script ' + str(i)], check=True)

    return script_name
